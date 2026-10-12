"""Maker replay v2 W2: the bundle v0.2 streaming writer and its streaming validation, on fictional rows."""
from datetime import date, datetime, timedelta, timezone
import gzip
import json
import random

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError, sha256
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2.compaction import expand, row as plain_row
from maker_core.replay.v2.writer import BundleWriter, SortedStream, validate

DAY = date(2026, 9, 27)
START = datetime(2026, 9, 27, tzinfo=timezone.utc)
CIDS = ["0x" + f"{i:040x}" for i in range(1, 5)]
HASHES = {"fixture": "0" * 64}


def _row(sequence, at, cid, kind, payload):
    return dict(sequence=sequence, captured_at=at.isoformat(), condition_id=cid, kind=kind, payload=payload,
                payload_sha256=sha256(canonical_bytes(payload)), source_hashes=HASHES)


class Day:
    """Exporter-shaped fictional rows: descriptors, books, out-of-order plugin inputs, and coverage runs
    in condition order at every capture. Groups: CIDS[0:2] share one subscription, CIDS[2:4] another."""

    def __init__(self, minutes=30, flip=None):
        self.rows, sequence = [], 0
        rng = random.Random(7)
        for minute in range(minutes):
            at = START + timedelta(minutes=minute, seconds=3)
            live = CIDS if minute >= 5 else CIDS[:2]
            for cid in live:
                for kind, payload in (("descriptor", {"cid": cid}), ("book", {"bid": rng.randrange(99)})):
                    if kind == "descriptor" and any(r["condition_id"] == cid and r["kind"] == kind for r in self.rows):
                        continue
                    self.rows.append(_row(sequence, at, cid, kind, payload))
                    sequence += 1
                    if kind == "descriptor":
                        # First-sight support rows keep their original, earlier capture clock.
                        self.rows.append(_row(sequence, START + timedelta(seconds=rng.randrange(60 * (minute + 1))),
                                              cid, "plugin_input", {"n": sequence}))
                        sequence += 1
            for cid in live:
                group = 0 if cid in CIDS[:2] else 1
                ok = (minute + group) % 3 != 0
                if flip == (minute, cid):
                    ok = not ok
                self.rows.append(_row(sequence, at, cid, "coverage", {"ok": ok, "group": group}))
                sequence += 1
        self.groups = {cid: "sub-a" if cid in CIDS[:2] else "sub-b" for cid in CIDS}

    def manifest(self):
        return dict(day=DAY.isoformat(), sealed_at=(START + timedelta(days=1)).isoformat(), provenance="synthetic",
                    conditions=[dict(condition_id=c, market_id="m", domain_id="fictional",
                                     active_from=START.isoformat(), active_until=(START + timedelta(days=1)).isoformat())
                                for c in CIDS])


def _write(tmp_path, day, spill_bytes=1024**2, groups=None):
    writer = BundleWriter(tmp_path / "bundle", spill_bytes=spill_bytes)
    for value in day.rows:
        writer.add(value, canonical_bytes(value))
    return writer, writer.finish(day.manifest(), groups or day.groups)


def test_v02_expands_to_exactly_the_pushed_v01_rows_with_one_record_per_group(tmp_path):
    day = Day()
    _, written = _write(tmp_path, day, spill_bytes=256)
    v01 = b"".join(canonical_bytes(r) for r in day.rows)
    assert written["v01"]["sha256"] == sha256(v01) and written["v01"]["bytes"] == len(v01)
    assert written["coverage_groups"] == 2
    checked = validate(tmp_path / "bundle", written["v01"])
    assert checked["kinds"] == {k: v["records"] for k, v in written["v01_kinds"].items()}
    bundle = open_stream_bundle(tmp_path / "bundle")
    expanded = [canonical_bytes(plain_row(r)) for r in expand(bundle.records(), bundle.coverage_groups)]
    ordered = sorted(day.rows, key=lambda r: (datetime.fromisoformat(r["captured_at"]), r["sequence"]))
    assert expanded == [canonical_bytes(r) for r in ordered]
    coverage = written["streams"]["coverage"]["records"]
    assert coverage == 5 + 25 * 2 and written["v01_kinds"]["coverage"]["records"] == 5 * 2 + 25 * 4
    assert written["streams"]["plugin_input"]["spilled_runs"] > 0
    assert not (tmp_path / "bundle" / "_work").exists()


def test_group_disagreement_refuses_and_condition_without_group_refuses(tmp_path):
    with pytest.raises(BundleError, match="coverage_group_mismatch"):
        _write(tmp_path / "a", Day(flip=(12, CIDS[3])))
    day = Day()
    with pytest.raises(BundleError, match="coverage_condition_without_group"):
        _write(tmp_path / "b", day, groups={c: g for c, g in day.groups.items() if c != CIDS[3]})
    # One group across both subscriptions is refused: the members disagree.
    with pytest.raises(BundleError, match="coverage_group_mismatch"):
        _write(tmp_path / "c", day, groups={c: "socket-0" for c in CIDS})


def test_streaming_validation_refuses_a_changed_stream_or_a_dropped_row(tmp_path):
    day = Day()
    _, written = _write(tmp_path, day)
    path = tmp_path / "bundle" / "book.jsonl.gz"
    raw = path.read_bytes()
    path.write_bytes(gzip.compress(gzip.decompress(raw).replace(b'"bid":', b'"bie":', 1), mtime=0))
    with pytest.raises(BundleError):
        validate(tmp_path / "bundle", written["v01"])
    path.write_bytes(raw)
    with pytest.raises(BundleError, match="v02_expansion_differs"):
        validate(tmp_path / "bundle", dict(written["v01"], records=written["v01"]["records"] + 1))


def test_sorted_stream_spills_bounded_runs_and_merges_in_key_order(tmp_path):
    rng = random.Random(3)
    keys = [(START + timedelta(seconds=rng.randrange(10**4)), s) for s in range(2000)]
    stream = SortedStream(tmp_path, "plugin_input", spill_bytes=4096)
    for at, sequence in keys:
        stream.add((at, sequence), canonical_bytes(dict(captured_at=at.isoformat(), sequence=sequence)))
        assert stream.buffered < 4096 + 200  # never more than one spill's worth in memory
    result = stream.finish(tmp_path / "plugin_input.jsonl")
    lines = (tmp_path / "plugin_input.jsonl").read_bytes().splitlines()
    got = [(datetime.fromisoformat(json.loads(x)["captured_at"]), json.loads(x)["sequence"]) for x in lines]
    assert got == sorted(keys) and result["records"] == 2000 and stream.spilled_runs > 10


def test_in_order_kinds_are_written_straight_through_with_nothing_buffered(tmp_path):
    stream = SortedStream(tmp_path, "book", spill_bytes=1)
    for s in range(100):
        at = START + timedelta(seconds=s)
        stream.add((at, s), canonical_bytes(dict(captured_at=at.isoformat(), sequence=s)))
    assert not stream.buffer and not stream.runs
    assert stream.finish(tmp_path / "book.jsonl")["records"] == 100


def test_duplicate_keys_refuse_at_merge(tmp_path):
    stream = SortedStream(tmp_path, "settlement", spill_bytes=1)
    for s in (2, 1, 1):
        at = START + timedelta(seconds=s)
        stream.add((at, s), canonical_bytes(dict(captured_at=at.isoformat(), sequence=s)))
    with pytest.raises(BundleError, match="duplicate_sorted_record"):
        stream.finish(tmp_path / "settlement.jsonl")
