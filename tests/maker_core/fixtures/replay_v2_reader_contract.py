"""Vendored minimal replay-v2 input-reader contract, for the shadow tape v0.2 round-trip test.

The replay-v2 reader lives only on the build line (``codex/maker-replay-v2-build-20261003``), not on this
branch. This module mirrors, at build-line commit ``2d8cccb13``, exactly the admission and decode rules a
bundle v0.2 day must pass:

- ``maker_core/replay/bundle_v02.py``: ``open_stream_bundle`` (manifest keys, day/seal, conditions and
  coverage groups, stream path/hash/bytes/records) and ``_record``/``_stream``/``records`` (row keys,
  in-day capture, payload hash, source hashes, per-stream order, global sequence uniqueness, k-way merge);
- ``maker_core/replay/bundle.py`` helpers (``_keys``, ``_identity``, ``_hash``, ``timestamp``, ``KINDS``,
  ``MAX_LINE_BYTES``, ``MAX_STREAMS``);
- ``maker_core/replay/payloads.py``: ``decode`` for every kind the shadow writes;
- ``maker_core/replay/v2/lockstep.py``: ``decode_record`` and ``items`` (group expansion over members whose
  descriptor was seen) and ``kernel.group_by_instant``; ``kernel.ingest``/``valid_coverage`` (latest state).

Byte/record/time ``Limits`` are not mirrored (the build line takes them as arguments). When the build line
lands on master, the round-trip test should switch to the real reader and this file should be deleted.
Fixture code only; no IO beyond the bundle directory it is given.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import heapq
import json
from pathlib import Path
import re

from maker_core.contracts import InfoEvent, MarketDescriptor, OutcomeView, Unavailable, utc_time
from maker_core.evidence.journal import canonical_bytes
from maker_core.quoting.policy import Book, RewardTerms

PINNED_AT = "2d8cccb13"
FORMAT_V02 = "maker_core.replay.bundle.v0.2"
KINDS = frozenset({"descriptor", "book", "terms", "trade", "plugin_input", "outcome_view", "info_event",
                   "settlement", "coverage"})
MAX_LINE_BYTES = 1024**2
MAX_STREAMS = 64
MAX_SEQUENCE = 2**31 - 1
MAX_TRADE_CLOCK_SKEW = timedelta(seconds=5)
_V01_FIELDS = "sequence captured_at condition_id kind payload payload_sha256 source_hashes"
_GROUP_FIELDS = "sequence captured_at group_id kind payload payload_sha256 source_hashes"


class BundleError(ValueError):
    pass


@dataclass(frozen=True)
class Record:
    sequence: int
    captured_at: datetime
    owner: str
    kind: str
    payload: dict
    payload_sha256: str
    grouped: bool


@dataclass(frozen=True)
class Coverage:
    trade_stream_ok: bool
    valid_until_utc: datetime


@dataclass(frozen=True)
class Trade:
    trade_id: str
    outcome: str
    price: D
    size: D
    traded_at: datetime
    aggressor_side: str


@dataclass(frozen=True)
class Descriptor:
    market: MarketDescriptor
    horizon_days: int


def timestamp(value):
    if not isinstance(value, str):
        raise BundleError("timestamp_requires_utc_text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        utc_time(result)
    except (ValueError, TypeError) as exc:
        raise BundleError("timestamp_requires_utc_text") from exc
    return result


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BundleError("invalid_sha256")
    return value


def _identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        raise BundleError("invalid_identity")
    return value


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise BundleError("unexpected_fields")


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise BundleError("invalid_or_unbounded_integer")
    return value


def _json(raw):
    try:
        value = json.loads(raw)
        canonical_bytes(value)
        return value
    except (ValueError, UnicodeError) as exc:
        raise BundleError("invalid_json") from exc


class StreamBundle:
    """``bundle_v02.open_stream_bundle`` pass one; ``records()`` is pass two."""

    def __init__(self, directory):
        self.root = Path(directory)
        manifest = _json((self.root / "bundle.json").read_bytes())
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_V02:
            raise BundleError("unsupported_bundle_format")
        _keys(manifest, "format day sealed_at provenance conditions streams coverage_groups")
        self.day = date.fromisoformat(manifest["day"])
        if self.day.isoformat() != manifest["day"]:
            raise BundleError("noncanonical_day")
        self.start = datetime.combine(self.day, datetime.min.time(), tzinfo=timezone.utc)
        end = self.start + timedelta(days=1)
        if timestamp(manifest["sealed_at"]) < end:
            raise BundleError("day_not_closed_at_seal")
        if manifest["provenance"] not in ("synthetic", "captured"):
            raise BundleError("invalid_provenance")
        self.conditions = {}
        for value in manifest["conditions"]:
            _keys(value, "condition_id market_id domain_id active_from active_until")
            cid = _identity(value["condition_id"])
            _identity(value["market_id"]), _identity(value["domain_id"])
            a, b = timestamp(value["active_from"]), timestamp(value["active_until"])
            if (cid in self.conditions or not self.start <= a <= b <= end or a.second or a.microsecond
                    or b.second or b.microsecond):
                raise BundleError("duplicate_condition_or_invalid_active_window")
            self.conditions[cid] = (a, b)
        if not 1 <= len(self.conditions) <= 2000:
            raise BundleError("condition_count_cap")
        self.groups, members = {}, set()
        for value in manifest["coverage_groups"]:
            _keys(value, "group_id condition_ids")
            gid, cids = _identity(value["group_id"]), value["condition_ids"]
            if gid in self.groups or not isinstance(cids, list) or not cids:
                raise BundleError("duplicate_or_empty_coverage_group")
            for cid in cids:
                if cid not in self.conditions or cid in members:
                    raise BundleError("unknown_or_shared_coverage_group_member")
                members.add(cid)
            if cids != sorted(cids):
                raise BundleError("noncanonical_coverage_group_order")
            self.groups[gid] = tuple(cids)
        streams = manifest["streams"]
        if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_STREAMS:
            raise BundleError("stream_count_cap")
        self.streams, names = [], {"bundle.json"}
        for stream in streams:
            _keys(stream, "path sha256 bytes records")
            name = stream["path"]
            if (not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9_-]+\.jsonl", name) is None
                    or name.casefold() in names):
                raise BundleError("invalid_or_duplicate_stream_path")
            names.add(name.casefold())
            raw = (self.root / name).read_bytes()
            if len(raw) != _integer(stream["bytes"], 2**62):
                raise BundleError("input_byte_cap_or_size_mismatch")
            if hashlib.sha256(raw).hexdigest() != _hash(stream["sha256"]):
                raise BundleError("stream_hash_or_size_mismatch")
            if raw.count(b"\n") != _integer(stream["records"], 2**62):
                raise BundleError("stream_record_count_mismatch")
            if raw and not raw.endswith(b"\n"):
                raise BundleError("record_too_large_or_unterminated")
            self.streams.append(name)

    def _record(self, value):
        grouped = isinstance(value, dict) and value.get("kind") == "coverage"
        _keys(value, _GROUP_FIELDS if grouped else _V01_FIELDS)
        sequence = _integer(value["sequence"], MAX_SEQUENCE)
        captured = timestamp(value["captured_at"])
        if not self.start <= captured < self.start + timedelta(days=1):
            raise BundleError("duplicate_sequence_or_capture_outside_day")
        kind = _identity(value["kind"])
        owner = _identity(value["group_id" if grouped else "condition_id"])
        if grouped and owner not in self.groups:
            raise BundleError("unknown_coverage_group")
        if not grouped and (owner not in self.conditions or kind not in KINDS):
            raise BundleError("unknown_condition_or_record_kind")
        payload = value["payload"]
        if not isinstance(payload, dict):
            raise BundleError("payload_not_object")
        if hashlib.sha256(canonical_bytes(payload)).hexdigest() != _hash(value["payload_sha256"]):
            raise BundleError("payload_hash_mismatch")
        sources = value["source_hashes"]
        if not isinstance(sources, dict) or not 1 <= len(sources) <= 64:
            raise BundleError("missing_or_unbounded_source_hashes")
        for name, digest in sources.items():
            _identity(name), _hash(digest)
        return Record(sequence, captured, owner, kind, payload, value["payload_sha256"], grouped)

    def _stream(self, name, seen):
        last = None
        with (self.root / name).open("rb") as handle:
            while line := handle.readline(MAX_LINE_BYTES + 1):
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    raise BundleError("record_too_large_or_unterminated")
                record = self._record(_json(line))
                key = (record.captured_at, record.sequence)
                if last is not None and key <= last:
                    raise BundleError("unsorted_stream")
                last = key
                if record.sequence in seen:
                    raise BundleError("duplicate_sequence_or_capture_outside_day")
                seen.add(record.sequence)
                yield record

    def records(self):
        seen, last = set(), None
        order = lambda r: (r.captured_at, r.sequence)  # noqa: E731
        for record in heapq.merge(*(self._stream(n, seen) for n in self.streams), key=order):
            if last is not None and order(record) <= last:
                raise BundleError("unsorted_or_duplicate_merged_record")
            last = order(record)
            yield record


def _number(value, *, minimum=D(0), maximum=None):
    if isinstance(value, bool):
        raise BundleError("boolean_number")
    result = D(str(value))
    if not result.is_finite() or result < minimum or (maximum is not None and result > maximum):
        raise BundleError("invalid_numeric_payload")
    return result


def _captured(value, record):
    result = timestamp(value)
    if result > record.captured_at:
        raise BundleError("payload_time_after_capture")
    return result


def decode(row):
    """``payloads.decode`` for the shadow's kinds (settlement is never written by the shadow)."""
    p = row.payload
    if row.kind == "coverage":
        until = timestamp(p["valid_until_utc"])
        if type(p["trade_stream_ok"]) is not bool or not 0 < (until - row.captured_at).total_seconds() <= 60:
            raise BundleError("invalid_trade_coverage")
        return Coverage(p["trade_stream_ok"], until)
    if row.kind == "descriptor":
        m = dict(p["market"])
        m["close_at_utc"] = timestamp(m["close_at_utc"])
        m["settle_at_utc"] = timestamp(m["settle_at_utc"]) if m.get("settle_at_utc") else None
        m["tick"], m["min_order_size"] = _number(m["tick"]), _number(m["min_order_size"])
        market = MarketDescriptor(**m)
        if type(p["horizon_days"]) is not int or not -1 <= p["horizon_days"] <= 366:
            raise BundleError("invalid_local_horizon")
        if market.condition_id != row.owner:
            raise BundleError("descriptor_identity_mismatch")
        return Descriptor(market, p["horizon_days"])
    if row.kind == "book":
        sides = []
        for side in ("yes_bids", "yes_asks", "no_bids", "no_asks"):
            levels = {}
            for price, size in p[side]:
                price, size = _number(price, maximum=D(1)), _number(size)
                if size:
                    levels[price] = levels.get(price, D(0)) + size
            sides.append(tuple(sorted(levels.items(), reverse=side.endswith("bids"))))
        available = p.get("post_only_available", True)
        if type(available) is not bool:
            raise BundleError("invalid_post_only_flag")
        return Book(_captured(p["as_of_utc"], row), *sides, available)
    if row.kind == "terms":
        return RewardTerms(_captured(p["as_of_utc"], row), _number(p["min_size"]), _number(p["max_spread_cents"]),
                           _number(p["rate_per_day"]))
    if row.kind == "outcome_view":
        value = dict(p["value"])
        value["as_of_utc"] = _captured(value["as_of_utc"], row)
        if p["available"] is False:
            return Unavailable(**value)
        if p["available"] is not True:
            raise BundleError("invalid_view_availability")
        value["valid_until_utc"] = timestamp(value["valid_until_utc"])
        return OutcomeView(**value)
    if row.kind == "info_event":
        events = []
        for raw in p["events"]:
            value = dict(raw)
            for key in ("scheduled_at_utc", "observed_at_utc", "detected_at_utc", "active_until_utc"):
                value[key] = timestamp(value[key]) if value.get(key) else None
            for key in ("observed_at_utc", "detected_at_utc"):
                if value[key] is not None and value[key] > row.captured_at:
                    raise BundleError("event_not_yet_observed")
            event = InfoEvent(**value)
            if row.owner not in event.affects:
                raise BundleError("event_identity_mismatch")
            events.append(event)
        return tuple(events)
    if row.kind == "trade":
        if (not isinstance(p["trade_id"], str) or not p["trade_id"] or p["outcome"] not in ("YES", "NO")
                or p["aggressor_side"] not in ("BUY", "SELL")):
            raise BundleError("invalid_trade_identity_or_side")
        size = _number(p["size"])
        if not size:
            raise BundleError("zero_trade_size")
        traded = timestamp(p["traded_at_utc"])
        if traded - row.captured_at > MAX_TRADE_CLOCK_SKEW:
            raise BundleError("trade_clock_skew_exceeds_bound")
        return Trade(p["trade_id"], p["outcome"], _number(p["price"], maximum=D(1)), size, traded,
                     p["aggressor_side"])
    if row.kind == "plugin_input":
        return p
    raise BundleError("unknown_payload_kind")


def decode_record(record):
    try:
        return decode(record), None
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return None, type(exc).__name__


def instants(bundle):
    """``lockstep.items``: ``(at, [(condition_id, kind, value, error)])``; groups expand to seen members."""
    seen, current, batch = set(), None, []
    for record in bundle.records():
        value, error = decode_record(record)
        if record.grouped:
            present = [cid for cid in bundle.groups[record.owner] if cid in seen]
            if not present:
                raise BundleError("coverage_group_without_seen_member")
            rows = [(cid, record.kind, value, error) for cid in present]
        else:
            if record.kind == "descriptor":
                seen.add(record.owner)
            rows = [(record.owner, record.kind, value, error)]
        if current is not None and record.captured_at != current:
            yield current, batch
            batch = []
        current = record.captured_at
        batch.extend(rows)
    if batch:
        yield current, batch


def valid_coverage(latest, at, *, max_book_gap_seconds=60):
    """``kernel.valid_coverage`` over a condition's latest decoded values (``kernel.ingest`` pops on error)."""
    for key in ("descriptor", "book", "terms", "outcome_view", "info_event", "coverage"):
        if key not in latest:
            return False, "MISSING_" + key.upper()
    if not 0 <= (at - latest["book"].as_of_utc).total_seconds() < max_book_gap_seconds:
        return False, "CAPTURE_GAP"
    if not latest["coverage"].trade_stream_ok or at >= latest["coverage"].valid_until_utc:
        return False, "TRADE_CAPTURE_GAP"
    if not 0 <= (at - latest["terms"].as_of_utc).total_seconds() <= 3600:
        return False, "TERMS_CAPTURE_GAP"
    return True, "COVERED"


def replay_states(bundle):
    """Per-instant latest state after ingest, as the kernel holds it: {(at, cid): (covered, reason, latest)}."""
    latest, out = {}, {}
    for at, rows in instants(bundle):
        touched = set()
        for cid, kind, value, error in rows:
            state = latest.setdefault(cid, {})
            touched.add(cid)
            if error is not None:
                state.pop(kind, None)
            elif kind != "plugin_input":
                state[kind] = value
        for cid in touched:
            out[(at, cid)] = (*valid_coverage(latest[cid], at), dict(latest[cid]))
    return out
