"""Shadow tape v0.2 record stream: the public replies the runner read, as replay-v2 bundle records.

Beside each daily journal tape the runner writes ``records/<day>/<day>-<run>-records.jsonl``: rows in the
replay bundle row format (``sequence, captured_at, condition_id | group_id, kind, payload, payload_sha256,
source_hashes``), strictly ordered by ``(captured_at, sequence)``, with sequences unique across every run of
the UTC day. After the day closes, ``bundle_day`` writes ``bundle.json`` (bundle format v0.2) next to the
day's sealed streams, so ``bundle_v02.open_stream_bundle`` + ``lockstep.stream_source`` read the tape
directly; there is no converter.

What is recorded (contract: docs/operations/maker-shadow-runner.md, "Tape v0.2 record stream"):

- ``book``: both tokens' full-depth CLOB levels exactly as received (the shadow's decision book is built
  from them; its construction is not this module's), stamped at the shadow's decision instant;
- ``terms``/``outcome_view``/``descriptor``/``info_event``: the decision's own inputs for that minute; a
  minute without terms writes an explicit absence record the frozen decoder refuses, so a replay drops its
  terms exactly when the shadow had none;
- ``trade``: newly seen public prints (data-api), identity, price, size, side and venue time only;
- ``coverage`` (v0.2 group record, one group per condition): trade-poll health, valid for 60 s;
- ``plugin_input``: the raw Gamma market object and CLOB reward record, on change (provenance only).

Public reads only; nothing here can place, cancel or sign. Paths are explicit caller inputs.
"""
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path

from maker_core.evidence.journal import canonical_bytes, digest, plain, write_new

BUNDLE_FORMAT = "maker_core.replay.bundle.v0.2"
STREAM_SEAL_SCHEMA = "maker_core.shadow_records_seal.v0.1"
COVERAGE_SECONDS = 60  # The replay decoder's cap on a coverage record's validity.
TRADES_PAGE = 500  # ``public_feed.TRADES_LIMIT``: a full page cannot prove continuity.
MAX_LINE_BYTES = 1024**2  # The replay reader's per-record cap.
MAX_SEQUENCE = 2**31 - 1
CHUNK = 1024**2
KIND_ORDER = ("plugin_input", "descriptor", "info_event", "terms", "outcome_view", "book", "trade", "coverage")
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


class RecordingReads:
    """``PublicReads`` proxy that keeps the latest raw reply of every read, for the record stream.

    A trade poll made by ``poll`` is served once to the runner's own ``trades`` read of the same condition,
    so the shadow's paper fills and the tape see the same prints.
    """

    def __init__(self, reads, clock):
        self.reads, self.clock = reads, clock
        self.books, self.rewards, self.gamma = {}, {}, {}
        self.polls, self.served = {}, {}

    def book(self, asset_id):
        value = self.reads.book(asset_id)
        self.books[str(asset_id)] = value
        return value

    def reward_terms(self, condition_id):
        value = self.reads.reward_terms(condition_id)
        self.rewards[str(condition_id).lower()] = value
        return value

    def events(self, slugs):
        value = self.reads.events(slugs)
        for event in value if isinstance(value, list) else ():
            source = digest(event)
            for market in event.get("markets") or ():
                if isinstance(market, dict) and market.get("conditionId"):
                    self.gamma[str(market["conditionId"]).lower()] = (event, market, source)
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


class RecordStream:
    """One run's record stream for one UTC day: ordered, numbered, fsynced per batch, sealed streaming."""

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
        self.trade_seen, self.trade_newest = {}, {}
        self.groups, self.described, self.outcomes = {}, set(), {}  # outcomes: condition -> recorded YES/NO tokens

    # -- writing ----------------------------------------------------------------------------------------
    def write(self, entries):
        """Append ``(at, owner, kind, payload, sources, group)`` entries in captured order; return a summary."""
        rank = {kind: i for i, kind in enumerate(KIND_ORDER)}
        ordered = sorted(enumerate(entries), key=lambda e: (e[1][0], rank.get(e[1][2], 99), e[0]))
        chunks, first, dropped = [], None, {k: 0 for k in self.dropped}
        for _, (at, owner, kind, payload, sources, group) in ordered:
            if not self.start <= at < self.start + timedelta(days=1):
                dropped["outside_day"] += 1
                continue
            if self.last_at is not None and at < self.last_at:
                dropped["out_of_order"] += 1
                continue
            if group and self.groups.get(owner) not in self.described:
                dropped["undescribed_group"] += 1  # The reader expands a group only over seen members.
                continue
            if self.sequence > MAX_SEQUENCE:
                raise ValueError("record_sequence_cap")
            raw = canonical_bytes(_row(self.sequence, at, owner, kind, payload, sources, group=group))
            if len(raw) > MAX_LINE_BYTES:
                dropped["oversize"] += 1
                continue
            chunks.append(raw)
            first = self.sequence if first is None else first
            self.first_sequence = self.sequence if self.first_sequence is None else self.first_sequence
            self.last_sequence, self.last_at = self.sequence, at
            self.sequence += 1
            self.kinds[kind] = self.kinds.get(kind, 0) + 1
            if kind == "descriptor":
                self.described.add(owner)
            if not group:
                minute = at.replace(second=0, microsecond=0)
                entry = self.conditions[owner]
                entry["first_minute"] = min(entry["first_minute"], minute.isoformat())
                entry["last_minute"] = max(entry["last_minute"], minute.isoformat())
        if chunks:
            blob = b"".join(chunks)
            self.handle.write(blob)
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.sha.update(blob)
            self.bytes += len(blob)
            self.records += len(chunks)
        for key, value in dropped.items():
            self.dropped[key] += value
        return {"stream": self.path.name, "first_sequence": first,
                "last_sequence": None if first is None else first + len(chunks) - 1, "records": len(chunks),
                "dropped": {k: v for k, v in dropped.items() if v}}

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
        """Close and seal: the file is re-hashed in bounded chunks and must equal what was written."""
        self.handle.close()
        check, size = hashlib.sha256(), 0
        with self.path.open("rb") as handle:
            while chunk := handle.read(CHUNK):
                check.update(chunk)
                size += len(chunk)
        if check.hexdigest() != self.sha.hexdigest() or size != self.bytes:
            raise ValueError("record_stream_changed_before_seal")
        conditions = {cid: dict(v) for cid, v in sorted(self.conditions.items()) if v["last_minute"]}
        seal = {"schema_version": STREAM_SEAL_SCHEMA, "stream": self.path.name, "utc_day": self.day,
                "run_id": self.run_id, "sha256": self.sha.hexdigest(), "bytes": self.bytes, "records": self.records,
                "first_sequence": self.first_sequence, "last_sequence": self.last_sequence,
                "kinds": dict(sorted(self.kinds.items())), "dropped": dict(self.dropped), "conditions": conditions,
                "coverage_groups": {group_id(cid): [cid] for cid in conditions}}
        write_new(self.path.with_name(self.path.name.replace("-records.jsonl", "-records.seal.json")), seal)
        return seal


def _levels(rows):
    return [[str(row["price"]), str(row["size"])] for row in rows or ()]


def _venue(reply):
    return {k: v for k, v in sorted(reply.items()) if k not in ("bids", "asks") and not isinstance(v, (dict, list))}


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
    """Turns one shadow minute (its tape payload plus the proxy's raw replies) into record-stream entries."""

    def __init__(self, reads: RecordingReads, *, market_id: Callable[[str], str | None], domain_id="weather"):
        if not isinstance(reads, RecordingReads):
            raise TypeError("recording_reads_required")
        self.reads, self.market_id, self.domain_id = reads, market_id, domain_id

    def poll(self, condition_ids):
        self.reads.poll(sorted(condition_ids))

    def _trades(self, stream, cid, outcomes, at, polls):
        entries = []
        for polled_at, rows, error in polls:
            when = at or polled_at
            ok = error is None
            emitted = []
            if ok:
                rows = [r for r in rows if str(r.get("conditionId", "")).lower() == cid]
                stamps = []
                for row in rows:
                    try:
                        stamps.append(int(row["timestamp"]))
                    except (KeyError, TypeError, ValueError):
                        ok = False
                newest = stream.trade_newest.get(cid)
                if newest is not None and len(rows) >= TRADES_PAGE and (not stamps or min(stamps) > newest):
                    ok = False  # A full page that does not reach the previous poll may have skipped prints.
                seen = stream.trade_seen.setdefault(cid, set())
                baseline = newest is None
                tokens = {v: k for k, v in outcomes.items()}
                for row in rows:
                    try:
                        key = _trade_key(row)
                    except (KeyError, TypeError, ValueError, InvalidOperation):
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    outcome, side = tokens.get(str(row.get("asset"))), str(row.get("side", "")).upper()
                    if baseline or outcome is None or side not in ("BUY", "SELL"):
                        continue
                    traded = datetime.fromtimestamp(int(row["timestamp"]), tz=timezone.utc)
                    emitted.append((when, cid, "trade", {
                        "trade_id": key, "outcome": outcome, "price": str(row["price"]), "size": str(row["size"]),
                        "traded_at_utc": traded.isoformat(), "aggressor_side": side,
                        "venue": {"transactionHash": row.get("transactionHash"), "asset": str(row.get("asset")),
                                  "timestamp": int(row["timestamp"])}},
                        {"data_trades": digest(rows)}, False))
                if stamps:
                    stream.trade_newest[cid] = max(stamps + ([newest] if newest is not None else []))
                elif newest is None:
                    stream.trade_newest[cid] = 0
            entries.extend(emitted)
            entries.append((when, group_id(cid), "coverage",
                            {"trade_stream_ok": ok, "valid_until_utc": (when + timedelta(seconds=COVERAGE_SECONDS)).isoformat(),
                             **({} if error is None else {"error": error})},
                            {"data_trades": digest({"rows": rows if error is None else None, "error": error})}, True))
        return entries

    def minute(self, stream: RecordStream, record: Mapping):
        """Entries for one minute: every evaluated condition's records at its decision instant."""
        polls = self.reads.take_polls()
        entries = []
        for row in record.get("conditions", ()):
            cid = row["condition_id"]
            if "decision" not in row:
                continue
            inputs = row["inputs"]
            at = _time(inputs["now"])
            market = _market_payload(inputs["market"])
            outcomes = stream.outcomes[cid] = dict(market["outcome_tokens"])
            gamma = self.reads.gamma.get(cid)
            gamma_hash = market.get("source_hashes", {}).get("gamma_event") or (gamma[2] if gamma else None)
            gamma_sources = {"gamma_event": gamma_hash} if gamma_hash else {"shadow_runner": digest(market)}
            stream.register(cid, market_id=self.market_id(market["event_id"]), domain_id=self.domain_id)
            if gamma is not None and stream.changed(cid, "gamma_market", gamma[1]):
                event, raw_market, source = gamma
                entries.append((at, cid, "plugin_input", {
                    "source": "gamma_market", "event_slug": event.get("slug"), "event_id": event.get("id"),
                    "neg_risk": event.get("negRisk"), "market": raw_market}, {"gamma_event": source}, False))
            descriptor = {"market": market, "horizon_days": row["horizon_days"]}
            if stream.changed(cid, "descriptor", descriptor):
                entries.append((at, cid, "descriptor", descriptor, gamma_sources, False))
            events = {"events": inputs.get("events") or []}
            if stream.changed(cid, "info_event", events):
                entries.append((at, cid, "info_event", events, {"shadow_runner": digest(events)}, False))
            reward = self.reads.rewards.get(cid)
            reward_hash = digest({"record": reward})
            if stream.changed(cid, "clob_reward", {"record": reward}):
                entries.append((at, cid, "plugin_input", {"source": "clob_reward", "record": reward},
                                {"clob_reward": reward_hash}, False))
            terms = inputs.get("terms")
            if terms is not None:
                payload = {k: terms[k] for k in ("as_of_utc", "min_size", "max_spread_cents", "rate_per_day")}
            else:
                payload = {"as_of_utc": inputs["book"]["as_of_utc"],
                           "absent": (row.get("venue") or {}).get("terms_reason") or "no_terms"}
            entries.append((at, cid, "terms", payload, {"clob_reward": reward_hash}, False))
            view = _view_payload(inputs["fair_value"])
            entries.append((at, cid, "outcome_view", view, {"shadow_runner": digest(view)}, False))
            yes, no = (self.reads.books.get(outcomes[o]) for o in ("YES", "NO"))
            if yes is not None and no is not None:
                book = {"as_of_utc": inputs["book"]["as_of_utc"], "yes_bids": _levels(yes.get("bids")),
                        "yes_asks": _levels(yes.get("asks")), "no_bids": _levels(no.get("bids")),
                        "no_asks": _levels(no.get("asks")),
                        "post_only_available": inputs["book"].get("post_only_available", True),
                        "venue": {"yes": _venue(yes), "no": _venue(no)}}
                entries.append((at, cid, "book", book, {"clob_book_yes": digest(yes), "clob_book_no": digest(no)},
                                False))
            entries.extend(self._trades(stream, cid, outcomes, at, polls.pop(cid, ())))
        entries.extend(self._orphan_polls(stream, polls))
        return entries

    def _orphan_polls(self, stream, polls):
        """Polls of conditions not evaluated in this batch: kept at receipt time once a descriptor exists."""
        entries = []
        for cid, rows in sorted(polls.items()):
            outcomes = self._outcomes(stream, cid)
            if outcomes is not None:
                entries.extend(self._trades(stream, cid, outcomes, None, rows))
        return entries

    def _outcomes(self, stream, cid):
        if cid not in stream.described:
            return None  # A coverage group record may not precede its member's first descriptor.
        return stream.outcomes.get(cid)  # the tokens of the condition's last recorded descriptor

    def between(self, stream: RecordStream):
        """Entries for a mid-minute trade poll (descriptor-seen conditions only), at receipt time."""
        return self._orphan_polls(stream, self.reads.take_polls())


# -- day bundle and read paths ---------------------------------------------------------------------------
def _stream_seals(root, day):
    folder, seals, unsealed = day_directory(root, day), [], []
    for path in sorted(folder.glob(f"{day}-*-records.jsonl")):
        seal_path = path.with_name(path.name.replace("-records.jsonl", "-records.seal.json"))
        if not seal_path.is_file():
            unsealed.append(path.name)
            continue
        seal = json.loads(seal_path.read_bytes())
        if (seal.get("schema_version") != STREAM_SEAL_SCHEMA or seal.get("stream") != path.name
                or seal.get("utc_day") != day):
            raise ValueError("record_stream_seal_mismatch")
        seals.append(seal)
    return seals, unsealed


def verify_stream(root, seal):
    """Re-hash one sealed stream in bounded chunks and count its records; raises on any difference."""
    path = day_directory(root, seal["utc_day"]) / seal["stream"]
    check, size, lines = hashlib.sha256(), 0, 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            check.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    if check.hexdigest() != seal["sha256"] or size != seal["bytes"] or lines != seal["records"]:
        raise ValueError("record_stream_differs_from_seal")
    return path


def records_summary(root, day):
    """Scorer read path for v0.2: every sealed stream of ``day`` verified against its seal, kinds counted."""
    seals, unsealed = _stream_seals(root, day)
    kinds = {}
    for seal in seals:
        verify_stream(root, seal)
        for kind, count in seal["kinds"].items():
            kinds[kind] = kinds.get(kind, 0) + count
    return {"streams": [{"stream": s["stream"], "sha256": s["sha256"], "records": s["records"]} for s in seals],
            "unsealed_streams": unsealed, "records": sum(s["records"] for s in seals),
            "kinds": dict(sorted(kinds.items())),
            "dropped": {k: sum(s["dropped"].get(k, 0) for s in seals) for k in ("out_of_order", "outside_day",
                                                                                "oversize", "undescribed_group")}}


def day_active_intervals(root, day):
    """Per-run active intervals ``(condition_id, start, end)`` for ``stream_source(active_intervals=...)``."""
    seals, unsealed = _stream_seals(root, day)
    if unsealed:
        raise ValueError("unsealed_record_stream")
    end_of_day = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    out = []
    for seal in seals:
        for cid, entry in seal["conditions"].items():
            start = _time(entry["first_minute"])
            out.append((cid, start, min(end_of_day, _time(entry["last_minute"]) + timedelta(minutes=1))))
    return sorted(out)


def bundle_day(root, day, *, clock):
    """Write ``records/<day>/bundle.json`` (bundle v0.2) over the day's sealed streams, after the day closes.

    Refuses an open day, an unsealed stream, a stream that differs from its seal, a condition without a
    registry market id, or a condition whose market identity differs between runs. Create-only.
    """
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc)
    end, sealed_at = start + timedelta(days=1), clock()
    if sealed_at < end:
        raise ValueError("utc_day_not_closed")
    seals, unsealed = _stream_seals(root, day)
    if unsealed:
        raise ValueError("unsealed_record_stream")
    seals = [s for s in seals if s["records"]]
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
    path = day_directory(root, day) / "bundle.json"
    write_new(path, manifest)
    return path, manifest


__all__ = ["BUNDLE_FORMAT", "COVERAGE_SECONDS", "RawRecorder", "RecordStream", "RecordingReads",
           "STREAM_SEAL_SCHEMA", "bundle_day", "day_active_intervals", "day_directory", "group_id",
           "next_sequence", "records_summary", "stream_name", "verify_stream"]
