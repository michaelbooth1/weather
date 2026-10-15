"""88a S9: reward records by change trigger, the VR-4 sweep, change-only rows and grouped fsync.

Guards: docs/operations/DATA_LAYER_V2_PLAN.md S2+S9 (REST <=0.4 req/s; rewards change-trigger;
VR-4 sweep stored change-only; 1 s grouped fsync) and DATA_LAYER_V2_CONTRACT.md "Recorder-only
rows" (sweep isolation, kill switch); docs/operations/passive-maker-evidence-capture.md; the 88a
hold to UTC 10-30 (a journal sync never creates or rewrites a file).
"""
from datetime import datetime, timezone
import json

import pytest

from weather.market import maker_evidence_store as store_module
from weather.market.maker_evidence_inspect import inspect_capture
from weather.market.maker_evidence_public import CLOB, PublicReader
from weather.market.maker_evidence_rewards import (
    BACKSTOP_SECONDS, MAX_TRIGGERED_READS_PER_CYCLE, REQUEST_BUDGET_PER_HOUR, STALE_RECHECK_SECONDS,
    SWEEP_SECONDS, SWEEP_STALE_SECONDS, RewardSweep, RewardTrigger, page_projection, sweep_row,
)
from weather.market.maker_evidence_store import (
    MAX_CONSECUTIVE_FSYNC_FAILURES, SCHEMA, EvidenceStore, JournalSyncFailure, digest, encoded,
)

NOW = datetime(2026, 10, 16, 15, tzinfo=timezone.utc)


def cid(n):
    return "0x" + f"{n:064x}"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SweepReader:
    """Public-shape fake of /rewards/markets/current and /rewards/markets/<condition>."""

    def __init__(self, store, rows, *, page_size=3, fail_on=None):
        self.store, self.rows, self.page_size, self.fail_on = store, rows, page_size, fail_on
        self.calls = []

    def read(self, url, *, params=None, body=None, kind="discovery", change_key=None, partition=None,
             projection=None):
        self.calls.append((url.rsplit("/", 1)[-1], kind, partition))
        if url.endswith("/rewards/markets/current"):
            start = int((params or {}).get("next_cursor") or 0)
            if self.fail_on is not None and start == self.fail_on:
                raise TimeoutError("public reply exceeded wall deadline")
            page = self.rows[start:start + self.page_size]
            end = start + self.page_size
            reply = {"data": page, "next_cursor": str(end) if end < len(self.rows) else "LTE="}
        else:
            condition = url.rsplit("/", 1)[1]
            reply = {"data": [row for row in self.rows if row["condition_id"] == condition], "next_cursor": "LTE="}
        raw = json.dumps(reply).encode()
        stored = encoded(projection(reply)) if projection else None
        self.store.record(kind, raw, change_key=change_key, partition=partition, stored_body=stored)
        return json.loads(raw)


def reward(n, rate=1.0):
    return {"condition_id": cid(n), "rewards_max_spread": 4.5, "rewards_min_size": 20, "total_daily_rate": rate,
            "rewards_config": [{"rate_per_day": rate, "start_date": "2026-10-01", "end_date": "2500-12-31"}],
            "market_competitiveness": n}  # Undocumented volatile field: never triggers a read.


def selected(n):
    return {"condition_id": cid(n), "reward": {"rewards_min_size": 20, "rewards_max_spread": 4.5,
                                               "rewards_config": [{"rate_per_day": 1.0}]}}


@pytest.fixture
def store(tmp_path):
    return EvidenceStore(tmp_path / "root", clock=lambda: NOW)


def journal(store, name):
    path = store.folder / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_budget_constants_meet_the_plan_acceptance_bound():
    assert REQUEST_BUDGET_PER_HOUR / 3600 <= 0.4
    # Backstop alone for the P1 universe (120 built-in + 50 pilot bands) stays far below the budget.
    assert 170 * 3600 / BACKSTOP_SECONDS + 3600 / SWEEP_SECONDS * 40 < REQUEST_BUDGET_PER_HOUR / 4
    assert SWEEP_SECONDS < SWEEP_STALE_SECONDS and STALE_RECHECK_SECONDS <= BACKSTOP_SECONDS


def test_sweep_pages_incrementally_and_commits_only_at_the_terminal_cursor(store):
    clock = Clock()
    reader = SweepReader(store, [reward(n) for n in range(7)])
    sweep = RewardSweep(reader, clock=clock)
    assert sweep.step(max_pages=2) is None and sweep.state == {} and not sweep.fresh()
    rows = sweep.step(max_pages=2)
    assert set(rows) == {cid(n) for n in range(7)} and sweep.generation == 1 and sweep.fresh()
    assert sweep.rows[cid(3)] == sweep_row(reward(3)) and "market_competitiveness" not in sweep.rows[cid(3)]
    assert not sweep.due() and sweep.step() is None
    pages = journal(store, "rewards_sweep_page.jsonl")
    assert len(pages) == 3 and all(row["representation"] == "selection_projection" for row in pages)
    assert json.loads(pages[0]["body_utf8"])["rows"] == 3  # A bounded projection, not the 6.7 MB sweep.
    event = json.loads(journal(store, "rewards_sweep.jsonl")[0]["body_utf8"])
    assert (event["conditions"], event["changed_count"], event["removed_count"]) == (7, 7, 0)
    clock.now += SWEEP_SECONDS
    reader.rows = [reward(n, rate=2.0 if n == 4 else 1.0) for n in range(6)]
    sweep.step()
    event = json.loads(journal(store, "rewards_sweep.jsonl")[1]["body_utf8"])
    assert (event["changed"], event["removed"]) == ([cid(4)], [cid(6)])


def test_sweep_failure_is_isolated_backs_off_and_goes_stale(store):
    clock = Clock()
    reader = SweepReader(store, [reward(n) for n in range(7)], fail_on=3)
    sweep = RewardSweep(reader, clock=clock)
    assert sweep.step() is None  # Never raises.
    assert sweep.errors == 1 and sweep.state == {} and not sweep.due()
    assert json.loads(journal(store, "rewards_sweep_error.jsonl")[0]["body_utf8"])["pages"] == 1
    clock.now += SWEEP_SECONDS
    reader.fail_on = None
    assert sweep.step() is not None and sweep.fresh()
    clock.now += SWEEP_STALE_SECONDS + 1
    assert not sweep.fresh()


def test_trigger_reads_first_then_only_on_change_recheck_or_backstop(store):
    clock = Clock()
    reader = SweepReader(store, [reward(n) for n in range(3)])
    trigger = RewardTrigger(reader, clock=clock)
    sweep = {cid(n): digest(encoded(sweep_row(reward(n)))) for n in range(3)}
    rows = [selected(n) for n in range(3)]
    trigger.begin_cycle()
    trigger.refresh([(None, rows)], sweep, True, today="2026-10-16")
    assert trigger.reasons["first"] == 3 and all(row["clob_reward_content_sha256"] for row in rows)
    for minute in range(1, 59):  # A quiet hour: no per-condition read at all.
        clock.now += 60
        trigger.begin_cycle()
        trigger.refresh([(None, [selected(n) for n in range(3)])], sweep, True, today="2026-10-16")
    assert trigger.reads == 3
    sweep[cid(1)] = "changed"
    changed_terms = selected(2)
    changed_terms["reward"]["rewards_min_size"] = 50
    trigger.begin_cycle()
    trigger.refresh([(None, [selected(0), selected(1), changed_terms])], sweep, True, today="2026-10-16")
    assert (trigger.reasons["sweep_changed"], trigger.reasons["terms_changed"]) == (1, 1)
    clock.now += BACKSTOP_SECONDS
    trigger.begin_cycle()
    trigger.refresh([(None, [selected(0)])], sweep, True, today="2026-10-16")
    assert trigger.reasons["backstop"] == 1


def test_stale_or_disabled_sweep_falls_back_to_the_recheck_cadence(store):
    clock = Clock()
    trigger = RewardTrigger(SweepReader(store, [reward(0)]), clock=clock)
    trigger.begin_cycle()
    trigger.refresh([(None, [selected(0)])], {}, False, today="2026-10-16")
    clock.now += STALE_RECHECK_SECONDS - 1
    assert trigger.due(selected(0), {}, False) is None
    clock.now += 1
    assert trigger.due(selected(0), {}, False) == "sweep_stale"


def test_per_cycle_cap_serves_core_before_pilot_and_carries_the_rest(store):
    clock = Clock()
    reader = SweepReader(store, [reward(n) for n in range(60)])
    trigger = RewardTrigger(reader, clock=clock)
    core, pilot = [selected(n) for n in range(15)], [selected(n) for n in range(15, 30)]
    trigger.begin_cycle()
    trigger.refresh([(None, core)], {}, False, today="2026-10-16")
    trigger.refresh([("pilot", pilot)], {}, False, today="2026-10-16")
    partitions = [call[2] for call in reader.calls]
    assert partitions == [None] * 15 + ["pilot"] * (MAX_TRIGGERED_READS_PER_CYCLE - 15)
    assert sum(row["clob_reward_content_sha256"] is None for row in pilot) == 30 - MAX_TRIGGERED_READS_PER_CYCLE
    clock.now += 60
    trigger.begin_cycle()
    trigger.refresh([(None, core)], {}, False, today="2026-10-16")
    trigger.refresh([("pilot", pilot)], {}, False, today="2026-10-16")
    assert all(row["clob_reward_content_sha256"] for row in pilot)


def test_record_changed_writes_a_baseline_per_segment_then_changes_only(tmp_path):
    now = [NOW]
    store = EvidenceStore(tmp_path, clock=lambda: now[0])
    values = {cid(n): sweep_row(reward(n)) for n in range(3)}
    assert store.record_changed("rewards_current", values) == 3
    assert store.record_changed("rewards_current", values) == 0
    values[cid(1)] = sweep_row(reward(1, rate=3.0))
    assert store.record_changed("rewards_current", values) == 1
    assert store.record_changed("rewards_current", values, partition="pilot") == 3  # Lanes never share a baseline.
    now[0] = NOW.replace(hour=16)
    assert store.record_changed("rewards_current", values) == 3  # A sealed hour is self-contained.
    rows = journal(store, "rewards_current.jsonl")
    assert {row["key"] for row in rows} == set(values) and all(row["body_stored"] for row in rows)


def test_grouped_fsync_batches_syncs_and_seals_only_durable_journals(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(store_module.os, "fsync", lambda fd: synced.append(fd))
    store = EvidenceStore(tmp_path, clock=lambda: NOW, group_fsync=True)
    synced.clear()
    for n in range(5):
        store.record("books", encoded([{"asset_id": str(n), "bids": []}]))
    assert synced == [] and len(store.dirty) == 6  # books.jsonl plus five per-token journals.
    assert store.sync() and len(synced) == 6 and not store.dirty
    store.event("note", {"n": 1})
    store.seal()
    assert not store.dirty and len(synced) == 8  # The dirty journal, then the manifest itself.
    metrics = store.sync_metrics()
    assert metrics["group_fsync"] and metrics["appends"] == 11 and metrics["fsync_failures"] == 0


def test_three_consecutive_failed_sync_passes_latch_the_writer(tmp_path, monkeypatch):
    store = EvidenceStore(tmp_path, clock=lambda: NOW, group_fsync=True)
    store.event("note", {"n": 1})

    def fail(fd):
        raise OSError("disk")
    monkeypatch.setattr(store_module.os, "fsync", fail)
    for _ in range(MAX_CONSECUTIVE_FSYNC_FAILURES - 1):
        assert store.sync() is False and store.failure is None
    with pytest.raises(JournalSyncFailure):
        store.sync()
    assert store.failure == "journal fsync failed"


def test_a_sync_never_creates_or_changes_a_journal(tmp_path):
    """88a hold (add files only): syncing a journal that is gone fails the pass; nothing is created."""
    store = EvidenceStore(tmp_path, clock=lambda: NOW, group_fsync=True)
    store.event("note", {"n": 1})
    (journal,) = store.dirty
    before = journal.read_bytes(), journal.stat().st_mtime_ns
    assert store.sync() and (journal.read_bytes(), journal.stat().st_mtime_ns) == before
    gone = store.folder / "held-elsewhere.jsonl"
    store.dirty.add(gone)
    assert store.sync() is False and not gone.exists()


def test_family_store_default_keeps_per_record_fsync(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(store_module.os, "fsync", lambda fd: synced.append(fd))
    store = EvidenceStore(tmp_path, clock=lambda: NOW)
    store.event("note", {"n": 1})
    assert len(synced) == 1 and not store.dirty


def test_reader_allowlists_the_sweep_and_journals_its_projection(store, monkeypatch):
    class Response:
        status_code, url = 200, CLOB + "/rewards/markets/current"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_content(self, size):
            yield json.dumps({"data": [reward(1), reward(2)], "next_cursor": "LTE="}).encode()

        def raise_for_status(self):
            return None
    reader = PublicReader(store)
    try:
        monkeypatch.setattr(reader.session, "request", lambda *a, **k: Response())
        payload = reader.read(CLOB + "/rewards/markets/current", kind="rewards_sweep_page", projection=page_projection)
        assert len(payload["data"]) == 2
        with pytest.raises(ValueError, match="allowlisted"):
            reader.read(CLOB + "/rewards/markets/current", body=[])
    finally:
        reader.close()
    row = journal(store, "rewards_sweep_page.jsonl")[0]
    assert row["representation"] == "selection_projection"
    assert json.loads(row["body_utf8"])["rows_sha256"] == digest(encoded([sweep_row(reward(1)), sweep_row(reward(2))]))


def test_inspector_verifies_sweep_pages_and_change_only_rows(store):
    reader = SweepReader(store, [reward(n) for n in range(4)])
    sweep = RewardSweep(reader, clock=Clock())
    rows = sweep.step()
    store.record_changed("rewards_current", rows)
    store.seal()
    status = {"schema_version": SCHEMA, "started_at_utc": NOW.isoformat(),
              "finished_at_utc": NOW.replace(minute=30).isoformat(),
              "cycles": 1, "failed_cycles": 0, "http": {}, "stream": {}, "trades": {},
              "peak_raw_working_bytes": store.peak_raw_bytes, "raw_working_bytes": store.raw_bytes}
    (store.root / "status.json").write_bytes(encoded(status))
    result = inspect_capture(store.root, NOW.date().isoformat())
    assert result["response_records_verified"] >= 2 + 4
