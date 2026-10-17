"""Bundle v0.2 compaction and its exact inverse (registration draft §6).

``Compactor`` turns v0.1 rows, in ``(captured_at, sequence)`` order, into v0.2 rows:

- **Coverage groups.** The v0.1 exporter writes one coverage row per condition with a descriptor at
  every capture, as one run of consecutive sequences in condition-ID order. Each run becomes one row
  per coverage group, carrying the sequence of the group's first member in the run. The day is refused
  if a group's members in the run are not exactly its members with a descriptor so far, or if they
  disagree in payload or source hashes (``coverage_group_mismatch``).
- **Duplicate elision.** A descriptor or outcome-view row whose payload is byte-identical to the
  condition's previous row of that kind is omitted. Nothing else is elided.

``expand`` is the inverse: it rebuilds the per-condition coverage rows with their original sequences,
so ``expand(compact(rows))`` equals ``elide(rows)`` byte for byte. Only elided duplicates' sequence
and capture time are lost. Both directions read a record only at or after its capture, and stream.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
import hashlib

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError, CapturedRecord, timestamp

ELIDED_KINDS = frozenset({"descriptor", "outcome_view"})
_FIELDS = ("sequence", "captured_at", "condition_id", "kind", "payload", "payload_sha256", "source_hashes")


def row(record) -> dict:
    """A v0.1 or v0.2 row as the plain dict an exporter writes, from a dict or a reader record."""
    if isinstance(record, Mapping):
        return dict(record)
    value = {"sequence": record.sequence, "captured_at": record.captured_at.isoformat(), "kind": record.kind,
             "payload": record.payload, "payload_sha256": record.payload_sha256,
             "source_hashes": record.source_hashes}
    if isinstance(record, CapturedRecord):
        value["condition_id"] = record.condition_id
    else:
        value["group_id"] = record.group_id
    return value


def _key(value):
    return timestamp(value["captured_at"]), value["sequence"]


class Elider:
    """Drops a descriptor/outcome-view row whose payload hash equals the condition's previous one."""

    def __init__(self):
        self.last = {}

    def keep(self, value) -> bool:
        if value["kind"] not in ELIDED_KINDS:
            return True
        key = value["condition_id"], value["kind"]
        previous, self.last[key] = self.last.get(key), value["payload_sha256"]
        return previous != value["payload_sha256"]


def elide(rows: Iterable) -> Iterator[dict]:
    elider = Elider()
    for value in map(row, rows):
        if elider.keep(value):
            yield value


class Compactor:
    """Push v0.1 rows in ``(captured_at, sequence)`` order; get v0.2 rows back in the same order."""

    def __init__(self, groups: Mapping[str, str]):
        self.groups = dict(groups)  # condition_id -> group_id
        self.members = {}
        for cid, gid in sorted(self.groups.items()):
            self.members.setdefault(gid, []).append(cid)
        self.seen, self.run, self.elider, self.last = set(), [], Elider(), None

    def push(self, value) -> list[dict]:
        value = row(value)
        key = _key(value)
        if self.last is not None and key <= self.last:
            raise BundleError("unsorted_compaction_input")
        self.last = key
        out = []
        if value["kind"] == "coverage":
            previous = self.run[-1] if self.run else None
            if previous is not None and (previous["captured_at"] != value["captured_at"]
                                         or previous["condition_id"] >= value["condition_id"]):
                out += self.flush()
            if self.run and self.run[-1]["sequence"] + 1 != value["sequence"]:
                raise BundleError("coverage_run_not_exporter_ordered")
            self.run.append(value)
            return out
        out += self.flush()
        if value["kind"] == "descriptor":
            self.seen.add(value["condition_id"])
        if self.elider.keep(value):
            out.append(value)
        return out

    def flush(self) -> list[dict]:
        run, self.run = self.run, []
        by_group = {}
        for value in run:
            gid = self.groups.get(value["condition_id"])
            if gid is None:
                raise BundleError("coverage_condition_without_group")
            by_group.setdefault(gid, []).append(value)
        out = []
        for gid, values in by_group.items():
            expected = [cid for cid in self.members[gid] if cid in self.seen]
            first = values[0]
            if ([v["condition_id"] for v in values] != expected
                    or any(v["payload_sha256"] != first["payload_sha256"]
                           or v["source_hashes"] != first["source_hashes"] for v in values)):
                raise BundleError("coverage_group_mismatch")
            out.append(dict(sequence=first["sequence"], captured_at=first["captured_at"], group_id=gid,
                            kind="coverage", payload=first["payload"], payload_sha256=first["payload_sha256"],
                            source_hashes=first["source_hashes"]))
        return sorted(out, key=lambda v: v["sequence"])

    def finish(self) -> list[dict]:
        return self.flush()


def compact(rows: Iterable, groups: Mapping[str, str]) -> Iterator[dict]:
    compactor = Compactor(groups)
    for value in rows:
        yield from compactor.push(value)
    yield from compactor.finish()


def expand(records: Iterable, coverage_groups) -> Iterator[CapturedRecord]:
    """v0.2 reader records -> v0.1 records; one coverage record per seen group member, original sequence."""
    members = {g.group_id: g.condition_ids for g in coverage_groups}
    seen, run = set(), []

    def flush():
        rows, firsts = [], {}
        for record in run:
            present = [cid for cid in members[record.group_id] if cid in seen]
            if not present:
                raise BundleError("coverage_group_without_seen_member")
            firsts[record.group_id] = present[0]
            rows += [(cid, record) for cid in present]
        rows.sort(key=lambda item: item[0])
        start = min(record.sequence for record in run)
        rank = {cid: index for index, (cid, _) in enumerate(rows)}
        for record in run:
            if record.sequence != start + rank[firsts[record.group_id]]:
                raise BundleError("coverage_group_sequence_mismatch")
        run.clear()
        return [CapturedRecord(start + index, record.captured_at, cid, "coverage", record.payload,
                               record.payload_sha256, record.source_hashes)
                for index, (cid, record) in enumerate(rows)]

    for record in records:
        if not isinstance(record, CapturedRecord):
            if run and (run[-1].captured_at != record.captured_at
                        or record.group_id in {r.group_id for r in run}):
                yield from flush()
            run.append(record)
            continue
        if run:
            yield from flush()
        if record.kind == "descriptor":
            seen.add(record.condition_id)
        yield record
    if run:
        yield from flush()


def stream_digest(rows: Iterable) -> dict:
    """SHA-256, bytes and count of the canonical JSONL of ``rows`` in the order given."""
    digest, size, count = hashlib.sha256(), 0, 0
    for value in rows:
        raw = canonical_bytes(row(value))
        digest.update(raw)
        size += len(raw)
        count += 1
    return dict(sha256=digest.hexdigest(), bytes=size, records=count)
