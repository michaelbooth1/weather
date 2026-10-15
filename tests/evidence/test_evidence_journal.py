"""PL-1 evidence journal: change-only rows, heartbeats, verified seals and the day-seal chain.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S4 verify row "seal chain across day roll"; plan
PL-1 principles: change-only bodies plus one heartbeat per poll, cap/gap rows in the journal, gzip-6
at seal verified, daily seal chained by prev_seal_sha256, first-seen state survives a restart).
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from weather.evidence.envelope import LIVE_RECEIPT, envelope
from weather.evidence.journal import (
    EvidenceJournal, JournalBusy, iter_segment_rows, read_raw, segment_dirs, verify_seal_chain,
)


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, **delta):
        self.value += timedelta(**delta)


def _item(key, body):
    return {"key": key, "body": body, "envelope": envelope(basis=LIVE_RECEIPT, parser_version="t-1")}


def _rows(root, family, day, partition):
    out = []
    for segment in segment_dirs(root / family / day):
        out += [row for name, row in iter_segment_rows(segment) if name == partition + ".jsonl"]
    return out


@pytest.fixture
def clock():
    return Clock(datetime(2026, 1, 2, 22, 30, tzinfo=timezone.utc))


def test_change_only_rows_with_one_heartbeat_per_poll(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock) as journal:
        first = journal.record_poll("obs", [_item("a", {"t": 1}), _item("b", {"t": 2})])
        clock.advance(minutes=1)
        second = journal.record_poll("obs", [_item("a", {"t": 1}), _item("b", {"t": 3})])
    assert (first["changed"], first["unchanged"]) == (2, 0)
    assert (second["changed"], second["unchanged"]) == (1, 1)
    rows = _rows(tmp_path, "fam", "2026-01-02", "rows")
    assert [(r["key"], r["body"]["t"]) for r in rows] == [("a", 1), ("b", 2), ("b", 3)]
    assert rows[-1]["first_seen_utc"] == "2026-01-02T22:31:00Z"
    beats = _rows(tmp_path, "fam", "2026-01-02", "heartbeat")
    assert [(b["items"], b["changed"], b["unchanged"]) for b in beats] == [(2, 2, 0), (2, 1, 1)]
    assert beats[0]["batch_hash"] != beats[1]["batch_hash"]


def test_hour_roll_seals_a_verified_gzip_segment(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock) as journal:
        journal.record_poll("obs", [_item("a", {"t": 1})])
        clock.advance(hours=1)
        journal.tick()
        segment = segment_dirs(tmp_path / "fam" / "2026-01-02")[0]
        manifest = json.loads((segment / "manifest.json").read_text())
        assert not list(segment.glob("*.jsonl"))
        for name, stats in manifest["files"].items():
            raw = gzip.decompress((segment / (name + ".gz")).read_bytes())
            assert stats["records"] == raw.count(b"\n") and stats["torn_tail"] is False
        assert set(manifest["files"]) == {"rows.jsonl", "heartbeat.jsonl"}


def test_seal_chain_holds_across_a_day_roll_and_detects_tampering(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock) as journal:
        for day in range(3):
            journal.record_poll("obs", [_item("a", {"day": day})])
            clock.advance(days=1)
            journal.tick()
    chain = verify_seal_chain(tmp_path / "fam", deep=True)
    assert chain["ok"], chain["problems"]
    assert chain["days"] == ["2026-01-02", "2026-01-03", "2026-01-04"]
    seals = [json.loads((tmp_path / "fam" / d / "day_seal.json").read_text()) for d in chain["days"]]
    assert seals[0]["prev_day"] is None and seals[1]["prev_day"] == "2026-01-02"
    assert seals[2]["prev_seal_sha256"] is not None
    middle = segment_dirs(tmp_path / "fam" / "2026-01-03")[0] / "manifest.json"
    middle.write_bytes(middle.read_bytes().replace(b'"records"', b'"Records"'))
    broken = verify_seal_chain(tmp_path / "fam")
    assert not broken["ok"] and any("2026-01-03" in p for p in broken["problems"])


def test_crash_recovery_seals_open_folders_and_keeps_first_seen_state(tmp_path, clock):
    journal = EvidenceJournal(tmp_path, "fam", clock=clock).open()
    journal.record_poll("obs", [_item("a", {"t": 1})])
    journal.lock.release()  # simulated crash: no seal, plain .jsonl left behind
    clock.advance(minutes=5)
    with EvidenceJournal(tmp_path, "fam", clock=clock) as again:
        assert again.seen("obs", "a")
        summary = again.record_poll("obs", [_item("a", {"t": 1})])
    assert summary["changed"] == 0
    sealed = [s for s in segment_dirs(tmp_path / "fam" / "2026-01-02") if (s / "manifest.json").exists()]
    assert len(sealed) == 2


def test_hour_byte_budget_writes_one_cap_row_and_drops_the_rest(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock, hour_byte_budget=2_000) as journal:
        result = journal.record_poll("obs", [_item(str(i), {"pad": "x" * 400}) for i in range(10)])
        journal.record_poll("obs", [_item("late", {"pad": "y"})])
        assert journal.cap_hit_hours == ["2026-01-02T22"]
    assert result["dropped"] > 0 and result["changed"] + result["dropped"] == 10
    caps = [e for e in _rows(tmp_path, "fam", "2026-01-02", "events") if e["kind"] == "cap"]
    assert len(caps) == 1 and caps[0]["reason"] == "hour_byte_budget"


def test_cas_stores_raw_bytes_once(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock) as journal:
        ref = journal.put_raw(b"kmz-bytes")
        assert journal.put_raw(b"kmz-bytes") == ref
        assert journal.counters["cas_objects"] == 1
    assert read_raw(tmp_path, ref) == b"kmz-bytes"


def test_second_writer_is_refused_and_clock_regression_raises(tmp_path, clock):
    with EvidenceJournal(tmp_path, "fam", clock=clock) as journal:
        with pytest.raises(JournalBusy):
            EvidenceJournal(tmp_path, "fam", clock=clock).open()
        journal.record_poll("obs", [])
        clock.advance(hours=-2)
        with pytest.raises(RuntimeError, match="backwards"):
            journal.tick()
        clock.advance(hours=2)
