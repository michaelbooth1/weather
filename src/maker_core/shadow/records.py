"""Shadow tape v0.2 record stream: the public replies the runner read, as replay-v2 bundle records.

Beside each daily journal tape the runner writes ``records/<day>/<day>-<run>-records.jsonl``: rows in the
replay bundle row format (``sequence, captured_at, condition_id | group_id, kind, payload, payload_sha256,
source_hashes``), strictly ordered by ``(captured_at, sequence)``, with sequences unique across every run of
the UTC day. After the day closes, ``bundle_day`` writes ``bundle.json`` (bundle format v0.2) next to the
day's sealed streams, so ``bundle_v02.open_stream_bundle`` + ``lockstep.stream_source`` read the tape
directly; there is no converter.

Every record is stamped at its RECEIPT time (contract: docs/operations/maker-shadow-runner.md, "Tape v0.2
record stream"):

- ``book``: both tokens' full-depth CLOB levels exactly as received, ``captured_at = as_of`` = the receipt of
  the later of the two reads. Read at the shadow's minute and again by the mid-minute refresh (~+30 s), so no
  recorded book is older than the replay engine's 60 s freshness limit at the next decision. The shadow's
  decision book is built from the minute's reads; its construction is not this module's;
- ``terms``: the reward record's receipt (an explicit absence record, which the frozen decoder refuses, when
  the shadow had no terms); ``descriptor``: at the minute's book receipt, on change;
- ``outcome_view``/``info_event``: at the decision instant, where the shadow computes them;
- ``trade``: newly seen public prints (data-api), identity, price, size, side and venue time only, at poll
  receipt; ``coverage`` (v0.2 group record, one group per condition): that poll's health, valid for 60 s
  from the poll's receipt;
- ``plugin_input``: an allowlisted projection of the Gamma market object and of the CLOB reward record, on
  change (provenance only; address-like values are dropped and counted).

Trade-poll baselines and seen prints are per run, so a print just before 00:00 UTC that is first polled after
the day roll lands in the next day's stream. A recorder or file fault never stops the runner: ``TapeWriter``
records it as not-OK coverage with a coded reason, and a stream whose file write failed is sealed ``broken``
(``bundle_day`` excludes that run's stream, and only it, from the day's bundle). Public reads only; nothing
here can place, cancel or sign. Paths are explicit caller inputs.
"""
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re

from maker_core.evidence.journal import SecretGuard, canonical_bytes, digest, plain, write_new

BUNDLE_FORMAT = "maker_core.replay.bundle.v0.2"
STREAM_SEAL_SCHEMA = "maker_core.shadow_records_seal.v0.1"
GAPS_SCHEMA = "maker_core.shadow_bundle_gaps.v0.1"
SEAL_FIELDS = ("stream", "utc_day", "status", "sha256", "bytes", "records", "kinds", "dropped", "conditions")
COVERAGE_SECONDS = 60  # The replay decoder's cap on a coverage record's validity.
TRADE_CLOCK_SKEW = timedelta(seconds=5)  # The replay decoder's bound on venue time after capture.
TRADES_PAGE = 500  # ``public_feed.TRADES_LIMIT``: a full page cannot prove continuity.
SEEN_MARGIN_SECONDS = 3600  # Seen print keys older than a poll's oldest print minus this are forgotten.
MAX_LINE_BYTES = 1024**2  # The replay reader's per-record cap.
# An unsealed stream is excluded from the day bundle only this long after the UTC day closed: before that its run
# may still be sealing it at the day roll, and a create-only bundle would drop it for good.
UNSEALED_GRACE = timedelta(hours=1)
MAX_SEQUENCE = 2**31 - 1
CHUNK = 1024**2
KIND_ORDER = ("plugin_input", "descriptor", "info_event", "terms", "outcome_view", "book", "trade", "coverage")
# Replay-v2 ``bundle.Limits`` a shadow day must be read with: the default (100k records, 64 MiB, 300 s) refuses a
# 12-band day. Sized for 24 bands with the mid-minute book refresh (~280k records, ~0.5 GB), with headroom.
SHADOW_REPLAY_LIMITS = {"max_records": 600_000, "max_bytes": 1024**3, "max_seconds": 900.0}
GAMMA_MARKET_KEYS = frozenset({
    "conditionId", "slug", "question", "outcomes", "clobTokenIds", "active", "closed", "enableOrderBook",
    "orderPriceMinTickSize", "orderMinSize", "endDate", "startDate", "bestBid", "bestAsk", "lastTradePrice",
    "spread", "groupItemTitle", "groupItemThreshold", "clobRewards"})
GAMMA_REWARD_KEYS = ("rewardsDailyRate", "startDate", "endDate", "rewardsAmount")
REWARD_KEYS = ("condition_id", "rewards_max_spread", "rewards_min_size")
REWARD_CONFIG_KEYS = ("start_date", "end_date", "rate_per_day", "total_rewards")
# The CLOB ``/book`` reply's scalar fields kept in a book record's ``venue`` block; anything else is dropped.
BOOK_VENUE_KEYS = frozenset({"market", "asset_id", "timestamp", "hash", "min_order_size", "tick_size", "neg_risk",
                             "last_trade_price"})
ADDRESS = re.compile(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
D = Decimal


def sha256_hex(raw):
    return hashlib.sha256(raw).hexdigest()


def group_id(condition_id):
    return "cov-" + condition_id.removeprefix("0x")[:24]


def stream_name(day, run_id):
    return f"{day}-{run_id}-records.jsonl"


def day_directory(root, day):
    return Path(root) / "records" / day


def _time(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(value):
    return _time(value).astimezone(timezone.utc).isoformat()


def _address_like(value):
    if isinstance(value, str):
        return ADDRESS.search(value) is not None
    if isinstance(value, Mapping):
        return any(_address_like(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_address_like(v) for v in value)
    return False


def gamma_market_projection(market):
    """Allowlisted Gamma market keys; any other key, or an address-like value, is dropped and counted."""
    kept, dropped = {}, 0
    for key, value in sorted(market.items()):
        if key not in GAMMA_MARKET_KEYS:
            dropped += 1
            continue
        if key == "clobRewards":
            value = [{k: row[k] for k in GAMMA_REWARD_KEYS if k in row}
                     for row in value if isinstance(row, dict)] if isinstance(value, list) else None
        if _address_like(value):
            dropped += 1
            continue
        kept[key] = value
    return kept, dropped


def reward_projection(record):
    """Allowlisted CLOB reward record (condition, spread, size, dated rates); None stays None."""
    if not isinstance(record, Mapping):
        return None
    out = {k: record[k] for k in REWARD_KEYS if k in record and not _address_like(record[k])}
    configs = record.get("rewards_config")
    if isinstance(configs, list):
        out["rewards_config"] = [{k: row[k] for k in REWARD_CONFIG_KEYS if k in row and not _address_like(row[k])}
                                 for row in configs if isinstance(row, Mapping)]
    return out


class RecordingReads:
    """``PublicReads`` proxy that keeps the latest raw reply of every read with its local receipt time.

    A trade poll made by ``poll`` is served once to the runner's own ``trades`` read of the same condition,
    so the shadow's paper fills and the tape see the same prints. Reads, replies and exceptions are the
    wrapped reader's, unchanged: the shadow's decision inputs do not depend on the proxy.
    """

    def __init__(self, reads, clock):
        self.reads, self.clock = reads, clock
        self.books, self.rewards, self.gamma = {}, {}, {}  # values carry the receipt time first
        self.polls, self.served = {}, {}

    def book(self, asset_id):
        value = self.reads.book(asset_id)
        self.books[str(asset_id)] = (self.clock(), value)
        return value

    def reward_terms(self, condition_id):
        value = self.reads.reward_terms(condition_id)
        self.rewards[str(condition_id).lower()] = (self.clock(), value)
        return value

    def events(self, slugs):
        value = self.reads.events(slugs)
        received = self.clock()
        for event in value if isinstance(value, list) else ():
            source = digest(event)
            for market in event.get("markets") or ():
                if isinstance(market, dict) and market.get("conditionId"):
                    self.gamma[str(market["conditionId"]).lower()] = (received, event, market, source)
        return value

    def _read_trades(self, cid):
        try:
            rows = self.reads.trades(cid)
            error = None
        except Exception as exc:  # A failed poll is recorded as unhealthy coverage, then re-raised.
            rows, error = None, exc
        self.polls.setdefault(cid, []).append((self.clock(), rows, None if error is None else type(error).__name__))
        return rows, error

    def poll(self, condition_ids):
        """One public trade read per condition; failures are kept as unhealthy polls, never raised."""
        for cid in condition_ids:
            rows, error = self._read_trades(cid)
            self.served[cid] = None if error is not None else rows

    def trades(self, condition_id):
        cid = str(condition_id).lower()
        if cid in self.served:
            rows = self.served.pop(cid)
            if rows is None:
                raise RuntimeError("trade_poll_failed")
            return list(rows)
        rows, error = self._read_trades(cid)
        if error is not None:
            raise error
        return rows

    def take_polls(self):
        polls, self.polls = self.polls, {}
        self.served = {}
        return polls


def _row(sequence, at, owner, kind, payload, sources, *, group=False):
    payload = plain(payload)
    row = {"sequence": sequence, "captured_at": at.isoformat(), "group_id" if group else "condition_id": owner,
           "kind": kind, "payload": payload, "payload_sha256": sha256_hex(canonical_bytes(payload)),
           "source_hashes": dict(sorted(sources.items()))}
    return row


def _last_sequence(path):
    """The sequence of an unsealed stream's last complete line (a crashed run), or None."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 2 * MAX_LINE_BYTES))
            lines = handle.read().split(b"\n")
        for line in reversed(lines[:-1]):
            try:
                return int(json.loads(line)["sequence"])
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        return None
    return None


def next_sequence(directory, day):
    """One past the largest sequence of every stream of ``day`` already on disk (sealed or not)."""
    last = -1
    for path in sorted(day_directory(directory, day).glob(f"{day}-*-records.jsonl")):
        seal = path.with_name(path.name.replace("-records.jsonl", "-records.seal.json"))
        if seal.is_file():
            value = json.loads(seal.read_bytes())
            if value.get("last_sequence") is not None:
                last = max(last, int(value["last_sequence"]))
        else:
            found = _last_sequence(path)
            if found is not None:
                last = max(last, found)
    return last + 1


def _file_digest(path):
    check, size, lines = hashlib.sha256(), 0, 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            check.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    return check.hexdigest(), size, lines


class RecordStream:
    """One run's record stream for one UTC day: ordered, numbered, fsynced per batch, sealed streaming.

    A failed file write marks the stream ``broken``: later writes are skipped and the seal records the bytes
    actually on disk with ``status = "broken"``. ``fault`` writes not-OK coverage for every described group.
    """

    def __init__(self, directory, day, run_id):
        self.root, self.day, self.run_id = Path(directory), day, run_id
        self.path = day_directory(directory, day) / stream_name(day, run_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc)
        self.sequence = next_sequence(directory, day)
        self.first_sequence = self.last_sequence = None
        self.handle = self.path.open("xb")
        self.sha, self.bytes, self.records, self.last_at = hashlib.sha256(), 0, 0, None
        self.kinds, self.conditions, self.dropped = {}, {}, {"out_of_order": 0, "outside_day": 0, "oversize": 0,
                                                              "undescribed_group": 0}
        self.emitted = {}  # (condition, label) -> payload hash, for on-change records
        self.groups, self.described = {}, set()
        self.faults, self.broken = {}, None
        self.incomplete_refreshes = {}  # minute (ISO) -> refresh cut short or skipped (owner decision N7)

    # -- writing ----------------------------------------------------------------------------------------
    def write(self, entries):
        """Append ``(at, owner, kind, payload, sources, group)`` entries in captured order; return a summary.

        The batch is built on local state and the stream's sequence, clock and counters advance only after its
        bytes are written and fsynced: an error while building leaves the stream unchanged (nothing written),
        and an error while writing marks it broken (the file may hold part of the batch).
        """
        if self.broken:
            return {"stream": self.path.name, "first_sequence": None, "last_sequence": None, "records": 0,
                    "dropped": {}, "broken": self.broken}
        rank = {kind: i for i, kind in enumerate(KIND_ORDER)}
        ordered = sorted(enumerate(entries), key=lambda e: (e[1][0], rank.get(e[1][2], 99), e[0]))
        chunks, rows, dropped = [], [], {k: 0 for k in self.dropped}
        sequence, last_at, described = self.sequence, self.last_at, set(self.described)
        for _, (at, owner, kind, payload, sources, group) in ordered:
            if not self.start <= at < self.start + timedelta(days=1):
                dropped["outside_day"] += 1
                continue
            if last_at is not None and at < last_at:
                dropped["out_of_order"] += 1
                continue
            if group and self.groups.get(owner) not in described:
                dropped["undescribed_group"] += 1  # The reader expands a group only over seen members.
                continue
            if sequence > MAX_SEQUENCE:
                raise ValueError("record_sequence_cap")
            condition = None if group else self.conditions[owner]  # an unregistered owner fails before writing
            raw = canonical_bytes(_row(sequence, at, owner, kind, payload, sources, group=group))
            if len(raw) > MAX_LINE_BYTES:
                dropped["oversize"] += 1
                continue
            chunks.append(raw)
            rows.append((sequence, at, kind, condition))
            last_at, sequence = at, sequence + 1
            if kind == "descriptor":
                described.add(owner)
        if chunks:
            blob = b"".join(chunks)
            try:
                self.handle.write(blob)
                self.handle.flush()
                os.fsync(self.handle.fileno())
            except Exception as error:  # The file may now hold part of the batch: sealed broken, never bundled.
                self.broken = "write:" + type(error).__name__
                raise
            self.sha.update(blob)
            self.bytes += len(blob)
            self.records += len(chunks)
        for number, at, kind, condition in rows:  # durable: commit the batch's sequence, clock and counters
            self.first_sequence = number if self.first_sequence is None else self.first_sequence
            self.last_sequence = number
            self.kinds[kind] = self.kinds.get(kind, 0) + 1
            if condition is not None:
                minute = at.replace(second=0, microsecond=0).isoformat()
                condition["first_minute"] = min(condition["first_minute"], minute)
                condition["last_minute"] = max(condition["last_minute"], minute)
        self.sequence, self.last_at, self.described = sequence, last_at, described
        for key, value in dropped.items():
            self.dropped[key] += value
        first = rows[0][0] if rows else None
        return {"stream": self.path.name, "first_sequence": first,
                "last_sequence": None if first is None else rows[-1][0], "records": len(chunks),
                "dropped": {k: v for k, v in dropped.items() if v}}

    def count_fault(self, code, n=1):
        self.faults[code] = self.faults.get(code, 0) + n

    def incomplete_refresh(self, code, minute, refreshed, left):
        """Count a mid-minute refresh cut short, skipped or ended late and name it on the seal
        (``incomplete_refreshes``: ``{minute, refreshed, left}`` band counts, by minute), so a replay can tell
        which minutes lack refreshed books; nothing is written to the stream itself."""
        self.count_fault(code)
        if minute is not None:
            at = minute.astimezone(timezone.utc).isoformat()
            self.incomplete_refreshes[at] = {"minute": at, "refreshed": int(refreshed), "left": int(left)}

    def fault(self, code, at):
        """Count a coded recorder fault and mark every described condition's trade stream not OK from ``at``."""
        self.count_fault(code)
        summary = {"stream": self.path.name, "fault": code, "records": 0}
        if self.broken:
            return dict(summary, broken=self.broken)
        at = max(at, self.last_at) if self.last_at is not None else at
        until = (at + timedelta(seconds=COVERAGE_SECONDS)).isoformat()
        entries = [(at, gid, "coverage", {"trade_stream_ok": False, "valid_until_utc": until, "error": code},
                    {"shadow_runner": digest({"fault": code})}, True)
                   for gid, cid in sorted(self.groups.items()) if cid in self.described]
        try:
            return dict(self.write(entries), fault=code)
        except Exception as error:  # noqa: BLE001 - a fault record must not raise
            return dict(summary, broken=self.broken or "fault_write:" + type(error).__name__)

    def changed(self, cid, label, value):
        key, value_hash = (cid, label), digest(value)
        if self.emitted.get(key) == value_hash:
            return False
        self.emitted[key] = value_hash
        return True

    def register(self, cid, *, market_id, domain_id):
        self.groups[group_id(cid)] = cid
        self.conditions.setdefault(cid, {"market_id": market_id, "domain_id": domain_id,
                                         "first_minute": "9999", "last_minute": ""})

    def close(self):
        """Close and seal: the file is re-hashed in bounded chunks; a difference from what was written, or an
        earlier failed write, seals the stream ``broken`` with the bytes actually on disk."""
        try:
            self.handle.close()
        except OSError as error:
            self.broken = self.broken or "close:" + type(error).__name__
        sha, size, lines = _file_digest(self.path)
        if not self.broken and (sha != self.sha.hexdigest() or size != self.bytes or lines != self.records):
            self.broken = "record_stream_changed_before_seal"
        conditions = {cid: dict(v) for cid, v in sorted(self.conditions.items()) if v["last_minute"]}
        seal = {"schema_version": STREAM_SEAL_SCHEMA, "stream": self.path.name, "utc_day": self.day,
                "run_id": self.run_id, "status": "broken" if self.broken else "ok", "broken_reason": self.broken,
                "sha256": sha, "bytes": size, "records": lines,
                "first_sequence": self.first_sequence, "last_sequence": self.last_sequence,
                "kinds": dict(sorted(self.kinds.items())), "dropped": dict(self.dropped),
                "faults": fault_list(self.faults),
                "incomplete_refreshes": [row for _, row in sorted(self.incomplete_refreshes.items())],
                "conditions": conditions,
                "coverage_groups": {group_id(cid): [cid] for cid in conditions}}
        write_new(self.path.with_name(self.path.name.replace("-records.jsonl", "-records.seal.json")), seal)
        return seal


def fault_list(faults):
    """Fault counts as ``[{"fault_code", "count"}]``: codes are values, so the seal's secret scrubber (which
    drops mapping keys containing ``key``, ``token``, ...) never removes one such as ``between:KeyError``."""
    return [{"fault_code": code, "count": count} for code, count in sorted(faults.items())]


def _levels(rows):
    return [[str(row["price"]), str(row["size"])] for row in rows or ()]


def _venue(reply):
    """Allowlisted scalar fields of a CLOB book reply (``BOOK_VENUE_KEYS``); address-like values dropped."""
    return {k: v for k, v in sorted(reply.items()) if k in BOOK_VENUE_KEYS and not isinstance(v, (dict, list))
            and not (isinstance(v, str) and ADDRESS.search(v))}


MALFORMED = (KeyError, TypeError, ValueError, AttributeError, InvalidOperation)


def _book(at, yes, no, post_only):
    return {"as_of_utc": at.isoformat(), "yes_bids": _levels(yes.get("bids")), "yes_asks": _levels(yes.get("asks")),
            "no_bids": _levels(no.get("bids")), "no_asks": _levels(no.get("asks")), "post_only_available": post_only,
            "venue": {"yes": _venue(yes), "no": _venue(no)}}


def _market_payload(market_row):
    """The tape's market projection (``outcomes``) back to a ``MarketDescriptor`` field mapping."""
    row = dict(market_row)
    row["outcome_tokens"] = row.pop("outcomes")
    return row


def _view_payload(value):
    value = dict(value)
    kind = value.pop("type")
    return {"available": kind == "view", "value": value}


def _trade_key(row):
    # The paper ledger's print key (``paper.parse_prints``), so a tape trade and a paper fill share one identity.
    return "|".join(str(x) for x in (row.get("transactionHash"), row.get("asset"), D(str(row["price"])),
                                     D(str(row["size"])), row["timestamp"]))


class RawRecorder:
    """Turns the proxy's raw replies (and each shadow minute's own derived inputs) into record-stream entries.

    Per run it keeps each condition's last recorded descriptor (carried into a new day's stream at its first
    record, so the day's coverage group is described) and the trade-poll baseline and seen prints (carried
    across the UTC day roll).

    The trade state is transactional: a batch (``minute`` or ``between``) stages its seen-print and baseline
    updates, ``commit`` applies them after the batch's records are written, and ``abort`` discards them with
    the batch's untaken polls and returns the batch's earliest poll receipt. A print in a failed batch is
    therefore polled again and re-emitted, and the fault's not-OK coverage starts no later than its receipt.
    """

    def __init__(self, reads: RecordingReads, *, market_id: Callable[[str], str | None], domain_id="weather"):
        if not isinstance(reads, RecordingReads):
            raise TypeError("recording_reads_required")
        self.reads, self.market_id, self.domain_id = reads, market_id, domain_id
        self.known = {}  # condition -> {"descriptor", "outcomes", "market_id", "sources", "post_only"}
        self.trade_seen, self.trade_newest = {}, {}  # condition -> {key: venue seconds}, newest venue seconds
        self.pending, self.batch_start = {}, None  # staged trade state of the open batch; its first poll receipt

    def poll(self, condition_ids):
        self.reads.poll(sorted(condition_ids))

    def _take(self):
        polls = self.reads.take_polls()
        stamps = [at for rows in polls.values() for at, _, _ in rows]
        if stamps:
            self.batch_start = min(stamps + ([self.batch_start] if self.batch_start is not None else []))
        return polls

    def commit(self):
        """Apply the batch's staged trade state; call after its records were written."""
        for cid, (seen, newest) in self.pending.items():
            self.trade_seen[cid] = seen
            if newest is None:
                self.trade_newest.pop(cid, None)
            else:
                self.trade_newest[cid] = newest
        self.pending, self.batch_start = {}, None

    def abort(self):
        """Discard a failed batch (staged trade state and untaken polls); its earliest poll receipt, or None."""
        untaken = self.reads.take_polls()
        stamps = [at for rows in untaken.values() for at, _, _ in rows]
        if self.batch_start is not None:
            stamps.append(self.batch_start)
        self.pending, self.batch_start = {}, None
        return min(stamps) if stamps else None

    def _book_entries(self, stream, at, cid, yes, no, post_only, stage):
        """A book record, or none and a counted ``<stage>:book_malformed`` fault for an unparsable reply."""
        try:
            payload = _book(at, yes, no, post_only)
        except MALFORMED:
            stream.count_fault(f"{stage}:book_malformed")
            return []
        return [(at, cid, "book", payload, {"clob_book_yes": digest(yes), "clob_book_no": digest(no)}, False)]

    def _ensure(self, stream, cid, at):
        """Register ``cid`` in ``stream`` and, if this stream has no descriptor yet, carry the last one forward."""
        known = self.known.get(cid)
        if known is None:
            return []
        stream.register(cid, market_id=known["market_id"], domain_id=self.domain_id)
        if cid in stream.described or not stream.changed(cid, "descriptor", known["descriptor"]):
            return []
        return [(at, cid, "descriptor", known["descriptor"], known["sources"], False)]

    def _trades(self, stream, cid, outcomes, polls):
        entries = []
        tokens = {v: k for k, v in outcomes.items()}
        for polled_at, rows, error in polls:
            entries.extend(self._ensure(stream, cid, polled_at))
            ok = error is None
            if ok and not isinstance(rows, list):
                ok, rows = False, []
            if ok:
                rows = [r for r in rows if isinstance(r, Mapping) and str(r.get("conditionId", "")).lower() == cid]
                parsed = []
                for row in rows:
                    try:
                        parsed.append((_trade_key(row), int(row["timestamp"]), row))
                    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
                        ok = False  # an unreadable print: this poll cannot prove the stream complete
                stamps = [stamp for _, stamp, _ in parsed]
                if cid not in self.pending:  # staged on a copy; committed only after the batch is written
                    self.pending[cid] = (dict(self.trade_seen.get(cid, {})), self.trade_newest.get(cid))
                seen, newest = self.pending[cid]
                if newest is not None and len(rows) >= TRADES_PAGE and (not stamps or min(stamps) > newest):
                    ok = False  # A full page that does not reach the previous poll may have skipped prints.
                baseline = newest is None
                for key, stamp, row in parsed:
                    if key in seen:
                        continue
                    seen[key] = stamp
                    outcome, side = tokens.get(str(row.get("asset"))), str(row.get("side", "")).upper()
                    if baseline or outcome is None or side not in ("BUY", "SELL"):
                        continue
                    try:
                        traded = datetime.fromtimestamp(stamp, tz=timezone.utc)
                    except (ValueError, OverflowError, OSError):
                        ok = False
                        continue
                    if traded - polled_at > TRADE_CLOCK_SKEW:
                        ok = False  # the replay decoder refuses this print: the poll is not a complete record
                    entries.append((polled_at, cid, "trade", {
                        "trade_id": key, "outcome": outcome, "price": str(row["price"]), "size": str(row["size"]),
                        "traded_at_utc": traded.isoformat(), "aggressor_side": side,
                        "venue": {"transactionHash": row.get("transactionHash"), "asset": str(row.get("asset")),
                                  "timestamp": stamp}},
                        {"data_trades": digest(rows)}, False))
                if stamps:
                    floor = min(stamps) - SEEN_MARGIN_SECONDS  # an older print can no longer reappear in a page
                    self.pending[cid] = ({k: v for k, v in seen.items() if v >= floor},
                                         max(stamps + ([newest] if newest is not None else [])))
                elif newest is None:
                    self.pending[cid] = (seen, 0)
            entries.append((polled_at, group_id(cid), "coverage",
                            {"trade_stream_ok": ok,
                             "valid_until_utc": (polled_at + timedelta(seconds=COVERAGE_SECONDS)).isoformat(),
                             **({} if error is None else {"error": error})},
                            {"data_trades": digest({"rows": rows if error is None else None, "error": error})}, True))
        return entries

    def minute(self, stream: RecordStream, record: Mapping):
        """Entries for one minute: the polls, books and reward records it read, each at its receipt time, and
        the decision's own derived inputs (view, events) at its decision instant."""
        polls = self._take()
        entries = []
        for row in record.get("conditions", ()):
            cid = row["condition_id"]
            if "decision" not in row:
                continue
            inputs = row["inputs"]
            now = _time(inputs["now"])
            market = _market_payload(inputs["market"])
            outcomes = dict(market["outcome_tokens"])
            yes, no = (self.reads.books.get(outcomes[o]) for o in ("YES", "NO"))
            received = max(yes[0], no[0]) if yes is not None and no is not None else now
            market_id = self.market_id(market["event_id"])
            stream.register(cid, market_id=market_id, domain_id=self.domain_id)
            entries.extend(self._trades(stream, cid, outcomes, polls.pop(cid, ())))
            gamma = self.reads.gamma.get(cid)
            gamma_hash = market.get("source_hashes", {}).get("gamma_event") or (gamma[3] if gamma else None)
            sources = {"gamma_event": gamma_hash} if gamma_hash else {"shadow_runner": digest(market)}
            if gamma is not None:
                gamma_at, event, raw_market, source = gamma
                projected, dropped = gamma_market_projection(raw_market)
                if stream.changed(cid, "gamma_market", projected):
                    entries.append((received, cid, "plugin_input", {
                        "source": "gamma_market", "received_at_utc": gamma_at.isoformat(),
                        "event_slug": event.get("slug"), "event_id": event.get("id"), "neg_risk": event.get("negRisk"),
                        "market": projected, "dropped_keys": dropped}, {"gamma_event": source}, False))
            descriptor = {"market": market, "horizon_days": row["horizon_days"]}
            if stream.changed(cid, "descriptor", descriptor):
                entries.append((received, cid, "descriptor", descriptor, sources, False))
            events = {"events": inputs.get("events") or []}
            if stream.changed(cid, "info_event", events):
                entries.append((now, cid, "info_event", events, {"shadow_runner": digest(events)}, False))
            reward_at, reward = self.reads.rewards.get(cid) or (now, None)
            reward_hash = digest({"record": reward})
            projected = reward_projection(reward)
            if stream.changed(cid, "clob_reward", {"record": projected}):
                entries.append((reward_at, cid, "plugin_input", {"source": "clob_reward", "record": projected},
                                {"clob_reward": reward_hash}, False))
            terms = inputs.get("terms")
            if terms is not None:
                payload = {"as_of_utc": reward_at.isoformat(),
                           **{k: terms[k] for k in ("min_size", "max_spread_cents", "rate_per_day")}}
            else:
                payload = {"as_of_utc": reward_at.isoformat(),
                           "absent": (row.get("venue") or {}).get("terms_reason") or "no_terms"}
            entries.append((reward_at, cid, "terms", payload, {"clob_reward": reward_hash}, False))
            view = _view_payload(inputs["fair_value"])
            entries.append((now, cid, "outcome_view", view, {"shadow_runner": digest(view)}, False))
            post_only = inputs["book"].get("post_only_available", True)
            if yes is not None and no is not None:
                entries.extend(self._book_entries(stream, received, cid, yes[1], no[1], post_only, "minute"))
            self.known[cid] = {"descriptor": descriptor, "outcomes": outcomes, "market_id": market_id,
                               "sources": sources, "post_only": post_only}
        entries.extend(self._orphan_polls(stream, polls))
        return entries

    def _orphan_polls(self, stream, polls):
        """Polls of conditions not evaluated in this batch: kept at receipt time once a descriptor is known."""
        entries = []
        for cid, rows in sorted(polls.items()):
            known = self.known.get(cid)
            if known is not None:
                entries.extend(self._trades(stream, cid, known["outcomes"], rows))
        return entries

    def between(self, stream: RecordStream, condition_ids, proceed=None):
        """Mid-minute refresh, for conditions with a recorded descriptor: one trade poll and both books read
        again, each at receipt time, so the recorded book never ages past the replay freshness limit between
        two shadow minutes. A failed, mismatched or malformed book read is counted and skipped. ``proceed``,
        if given, is called before each band's reads with the number of bands left (this one included); False
        stops the refresh there (the run's hard deadline), keeping what was read."""
        entries, failed = [], 0
        bands = sorted(set(condition_ids) & set(self.known))
        for index, cid in enumerate(bands):
            if proceed is not None and not proceed(len(bands) - index):
                break
            known = self.known[cid]
            self.reads.poll([cid])
            replies = []
            for outcome in ("YES", "NO"):
                try:
                    reply = self.reads.book(known["outcomes"][outcome])
                except Exception:  # noqa: BLE001 - a failed public read costs this refresh only
                    break
                if not isinstance(reply, Mapping) or str(reply.get("market", "")).lower() != cid:
                    break
                replies.append((self.reads.books[known["outcomes"][outcome]][0], reply))
            if len(replies) != 2:
                failed += 1
                continue
            at = max(replies[0][0], replies[1][0])
            entries.extend(self._ensure(stream, cid, at))
            entries.extend(self._book_entries(stream, at, cid, replies[0][1], replies[1][1], known["post_only"],
                                              "refresh"))
        entries.extend(self._orphan_polls(stream, self._take()))
        if failed:
            stream.count_fault("refresh:book_read", failed)
        return entries


# -- day bundle and read paths ---------------------------------------------------------------------------
# Every refusal below is a ``ValueError`` whose message is a stable code (the bundle CLI prints it as
# ``{"refused": code}``): utc_day_not_closed, unsealed_record_stream (only within ``UNSEALED_GRACE`` of the day
# close; later an unsealed stream excludes its own run), no_sealed_record_stream, bundle_unreadable,
# record_stream_seal_unreadable, record_stream_seal_mismatch, record_stream_unreadable,
# record_stream_differs_from_seal, tape_seal_unreadable, condition_without_market_id,
# condition_identity_differs_between_runs.
def _read_json(path, code):
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise ValueError(code) from None
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _stream_seals(root, day):
    folder, seals, unsealed = day_directory(root, day), [], []
    for path in sorted(folder.glob(f"{day}-*-records.jsonl")):
        seal_path = path.with_name(path.name.replace("-records.jsonl", "-records.seal.json"))
        if not seal_path.is_file():
            unsealed.append(path.name)
            continue
        seal = _read_json(seal_path, "record_stream_seal_unreadable")
        if (seal.get("schema_version") != STREAM_SEAL_SCHEMA or seal.get("stream") != path.name
                or seal.get("utc_day") != day or any(k not in seal for k in SEAL_FIELDS)):
            raise ValueError("record_stream_seal_mismatch")
        seals.append(seal)
    return seals, unsealed


def _stream_run_id(day, name):
    return name[len(day) + 1:-len("-records.jsonl")]


def _excluded_streams(day, seals, unsealed, bundled):
    """Streams of ``day`` with records that are not in the bundle, ``[{run_id, stream, reason}]``: an unsealed
    stream (a killed run), a stream sealed ``broken`` (a failed file write) or one sealed after the bundle was
    written. Each excludes only its own run's records and active intervals (owner decision Q-D5)."""
    out = [{"run_id": _stream_run_id(day, name), "stream": name, "reason": "unsealed_record_stream"}
           for name in unsealed if name not in bundled]
    for seal in seals:
        if seal["stream"] in bundled or (seal.get("status") == "ok" and not seal["records"]):
            continue
        reason = ("sealed_after_bundle" if seal.get("status") == "ok"
                  else "broken_record_stream:" + str(seal.get("broken_reason")))
        out.append({"run_id": seal.get("run_id"), "stream": seal["stream"], "reason": reason})
    return sorted(out, key=lambda row: row["stream"])


def stream_gaps(root, day):
    """Runs of ``day`` whose quotes tape sealed without a record stream (it could not be opened, or sealing
    it failed): explicit gap sources, ``[{run_id, tape, reason}]``. Their minutes have no raw records."""
    gaps = []
    for path in sorted(Path(root).glob(f"{day}-*.seal.json")):
        seal = _read_json(path, "tape_seal_unreadable")
        if seal.get("utc_day") == day and seal.get("records_stream") is None and seal.get("records_stream_error"):
            gaps.append({"run_id": seal.get("run_id"), "tape": seal.get("tape"),
                         "reason": seal["records_stream_error"]})
    return gaps


def verify_stream(root, seal):
    """Re-hash one sealed stream in bounded chunks and count its records; raises on any difference."""
    path = day_directory(root, seal["utc_day"]) / seal["stream"]
    try:
        sha, size, lines = _file_digest(path)
    except OSError:
        raise ValueError("record_stream_unreadable") from None
    if sha != seal["sha256"] or size != seal["bytes"] or lines != seal["records"]:
        raise ValueError("record_stream_differs_from_seal")
    return path


def records_summary(root, day, streams=None):
    """Scorer read path for v0.2: every sealed stream of ``day`` verified against its seal, kinds counted.

    With ``streams`` (stream file names, e.g. a bundle's), only those streams are read and counted.
    """
    seals, unsealed = _stream_seals(root, day)
    if streams is not None:
        seals = [s for s in seals if s["stream"] in streams]
        unsealed = [name for name in unsealed if name in streams]
    kinds = {}
    for seal in seals:
        verify_stream(root, seal)
        for kind, count in seal["kinds"].items():
            kinds[kind] = kinds.get(kind, 0) + count
    return {"streams": [{"stream": s["stream"], "sha256": s["sha256"], "records": s["records"]} for s in seals],
            "unsealed_streams": unsealed, "stream_gaps": stream_gaps(root, day),
            "records": sum(s["records"] for s in seals),
            "broken_streams": [s["stream"] for s in seals if s.get("status") != "ok"],
            "faults": _summed_faults(seals),
            "kinds": dict(sorted(kinds.items())),
            "dropped": {k: sum(s["dropped"].get(k, 0) for s in seals) for k in ("out_of_order", "outside_day",
                                                                                "oversize", "undescribed_group")}}


def _summed_faults(seals):
    total = {}
    for seal in seals:
        for row in seal.get("faults") or ():
            total[row["fault_code"]] = total.get(row["fault_code"], 0) + row["count"]
    return fault_list(total)


def day_active_intervals(root, day):
    """Per-run active intervals ``(condition_id, start, end)`` for ``stream_source(active_intervals=...)``.

    Only the runs whose streams are in the day's ``bundle.json`` (before it is written: the streams sealed
    ``ok``); an unsealed or broken stream's run has no interval, so the replay claims nothing for it.
    """
    seals, _ = _stream_seals(root, day)
    bundle = day_directory(root, day) / "bundle.json"
    if bundle.is_file():
        bundled = {row["path"] for row in _read_json(bundle, "bundle_unreadable").get("streams") or ()}
        seals = [s for s in seals if s["stream"] in bundled]
    else:
        seals = [s for s in seals if s.get("status") == "ok"]
    end_of_day = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    out = []
    for seal in seals:
        for cid, entry in seal["conditions"].items():
            start = _time(entry["first_minute"])
            out.append((cid, start, min(end_of_day, _time(entry["last_minute"]) + timedelta(minutes=1))))
    return sorted(out)


def bundle_day(root, day, *, clock):
    """Write ``records/<day>/bundle.json`` (bundle v0.2) over the day's sealed streams, after the day closes.

    A stream sealed ``broken`` (a failed file write), or one still unsealed ``UNSEALED_GRACE`` after the day
    closed (a killed run), excludes only its own run (owner decision Q-D5): it is left out of the bundle and
    named under ``excluded_streams``, and ``day_active_intervals`` gives its run no interval. Refuses an open
    day, an unsealed stream within the grace, a day with no bundleable stream, an unreadable or malformed
    seal, a bundled stream that differs from its seal, a condition without a registry market id, or a
    condition whose market identity differs between runs, each with a coded ``ValueError``. Create-only.
    Runs that sealed their quotes tape without a stream (``stream_gaps``) and the excluded streams are named in
    ``gaps.json`` beside the bundle (schema ``GAPS_SCHEMA``; the bundle format itself admits no extra field),
    written first and atomically; a re-run fills it in when ``bundle.json`` exists without it, validating only
    the bundled streams. ``gaps.json`` also names, per bundled stream, the minutes whose mid-minute refresh was
    cut short, skipped or ended late (``incomplete_refreshes``, owner decision N7; their books may age past
    60 s). They are also returned under the manifest's ``gaps`` and ``excluded`` keys by ``bundle_day``
    only. Read the day with ``Limits(**SHADOW_REPLAY_LIMITS)``.
    """
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc)
    end, sealed_at = start + timedelta(days=1), clock()
    if sealed_at < end:
        raise ValueError("utc_day_not_closed")
    seals, unsealed = _stream_seals(root, day)
    if unsealed and sealed_at < end + UNSEALED_GRACE:
        raise ValueError("unsealed_record_stream")  # its run may still be sealing it at the day roll
    every_seal, seals = seals, [s for s in seals if s.get("status") == "ok" and s["records"]]
    path = day_directory(root, day) / "bundle.json"
    gaps_path = path.with_name("gaps.json")
    if path.exists() and gaps_path.exists():
        raise FileExistsError(str(path))
    existing = _read_json(path, "bundle_unreadable") if path.exists() else None
    if existing is not None:  # a fill-in validates only the bundled streams, never one sealed after the bundle
        bundled = {row.get("path") for row in existing.get("streams") or ()}
        seals = [s for s in seals if s["stream"] in bundled]
    if not seals:
        raise ValueError("no_sealed_record_stream")
    conditions = {}
    for seal in seals:
        verify_stream(root, seal)
        for cid, entry in seal["conditions"].items():
            if not entry.get("market_id"):
                raise ValueError("condition_without_market_id")
            known = conditions.setdefault(cid, dict(entry))
            if (known["market_id"], known["domain_id"]) != (entry["market_id"], entry["domain_id"]):
                raise ValueError("condition_identity_differs_between_runs")
            known["first_minute"] = min(known["first_minute"], entry["first_minute"])
            known["last_minute"] = max(known["last_minute"], entry["last_minute"])
    manifest = {
        "format": BUNDLE_FORMAT, "day": day, "sealed_at": sealed_at.astimezone(timezone.utc).isoformat(),
        "provenance": "captured",
        "conditions": [{"condition_id": cid, "market_id": e["market_id"], "domain_id": e["domain_id"],
                        "active_from": _iso(e["first_minute"]),
                        "active_until": min(end, _time(e["last_minute"]) + timedelta(minutes=1)).isoformat()}
                       for cid, e in sorted(conditions.items())],
        "coverage_groups": [{"group_id": group_id(cid), "condition_ids": [cid]} for cid in sorted(conditions)],
        "streams": [{"path": s["stream"], "sha256": s["sha256"], "bytes": s["bytes"], "records": s["records"]}
                    for s in seals]}
    gaps = stream_gaps(root, day)
    bundled = {s["path"] for s in (existing or manifest)["streams"]}
    excluded = _excluded_streams(day, every_seal, unsealed, bundled)
    incomplete = [{"run_id": s.get("run_id"), "stream": s["stream"], "refreshes": s["incomplete_refreshes"]}
                  for s in every_seal if s["stream"] in bundled and s.get("incomplete_refreshes")]
    # gaps.json first, atomically (a temp file renamed over it), then the create-only bundle.json: a bundle
    # never exists without its gap sources, and a re-run after a failure in between fills gaps.json in.
    _replace_json(gaps_path, {"schema_version": GAPS_SCHEMA, "day": day, "bundle": path.name,
                              "runs_without_record_stream": gaps, "excluded_streams": excluded,
                              "incomplete_refreshes": incomplete})
    if existing is not None:
        return path, dict(existing, gaps=gaps, excluded=excluded)
    write_new(path, manifest)
    return path, dict(manifest, gaps=gaps, excluded=excluded)


def _replace_json(path, value):
    """Write ``value`` to ``path`` atomically: a fsynced temp file beside it, renamed over it."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(canonical_bytes(SecretGuard().clean(value)))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["BOOK_VENUE_KEYS", "BUNDLE_FORMAT", "COVERAGE_SECONDS", "GAPS_SCHEMA", "RawRecorder", "RecordStream",
           "RecordingReads", "SHADOW_REPLAY_LIMITS", "STREAM_SEAL_SCHEMA", "UNSEALED_GRACE", "bundle_day",
           "day_active_intervals", "day_directory", "fault_list", "gamma_market_projection", "group_id",
           "next_sequence", "records_summary", "reward_projection", "stream_gaps", "stream_name", "verify_stream"]
