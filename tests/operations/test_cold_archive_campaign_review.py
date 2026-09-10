"""Protected-input review uses actual queue, corpus and settlement dependencies."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
from weather.operations import cold_archive_campaign_review as review
from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import production_cold_archive_stage as archive
from test_production_cold_archive_transfer import FixturePin


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return path


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    class ReviewPin(FixturePin):
        # A review deliberately opens the same read-only settlement proof from
        # several checks; real shared read handles permit this.
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(reclaim.bridge, "_file_pin", ReviewPin)
    event = "highest-temperature-in-atlanta-on-july-1-2026"
    folder = tmp_path / "data/snapshots" / event
    put(folder / "settlement.json", {
        "target_date": "2026-07-01", "quality_grade": "complete",
        "polymarket_reconciliation": {"event_closed": True, "status": "match",
                                     "winning_markets": [{"closed": True, "resolved": True}]}})
    put(folder / "snapshots_long.csv", "retained snapshot fixture")
    put(folder / "replay_inputs.jsonl", "retained replay fixture")
    backtest = tmp_path / "data/backtest"
    put(backtest / "settled_day_analysis_barrier.json", {"target_date": "2026-09-01", "status": "PASS"})
    audit = put(backtest / "model_market_disagreement_audit.jsonl", "")
    put(backtest / "model_market_disagreement_review_queue.json", {"source_audit_log_path": str(audit), "rows": []})
    put(backtest / "daily_learning.json", {"experiment_queue": {
        "status": "EMPTY", "summary": {"eligible_count": 0, "materialized_executable_count": 0}, "items": []}})
    for name in ("pending", "inflight"):
        (tmp_path / "data/snapshots/triggered_snapshot_queue" / name).mkdir(parents=True)
    put(backtest / "active_variant_shadow_window_corpus.json", {
        "entries": [{"event_slug": event, "snapshot_tape_path": str(folder / "snapshots_long.csv")}]})
    put(backtest / "point_in_time_validation_plan.json", {"status": "PASS", "fleet_dates": ["2026-07-01"]})
    put(tmp_path / "docs/operations/reserved-confirmation-window.md", "NONE ARE CURRENTLY RESERVED.")
    for relative in ("src/weather/reporting/promotion/promotion_corpus.py",
                     "src/weather/reporting/validation/point_in_time_evaluation.py",
                     "src/weather/backtesting/replay.py", "src/weather/operations/closed_market_day_archive.py"):
        put(tmp_path / relative, "# synthetic dependency contract")
    entry = {"archive_id": "test-a1", "source_root": str(tmp_path / "data"),
             "files": [{"path": "snapshots/" + event + "/clob_tokens.jsonl", "sha256": "a" * 64}]}
    return tmp_path, entry, event, folder, backtest


def run(evidence):
    root, entry, *_ = evidence
    now = datetime(2026, 9, 10, 20, tzinfo=timezone.utc)
    result = review.review_sources(production_root=root, entry=entry, entry_sha256="b" * 64,
                                   output_root=root / "review", now=now)
    with ExitStack() as stack:
        checked, digest, expires = reclaim._review(result, stack, entry, "b" * 64, now)
    return checked, expires, now


def test_review_is_accepted_by_existing_reclaim_validator(evidence):
    checked, expires, now = run(evidence)
    assert (expires - now).total_seconds() == 300
    assert checked["checks"]["queues_clear"]["open_references"] == []
    assert len(checked["market_days"]) == 1


@pytest.mark.parametrize("kind", ["settlement", "barrier", "queue", "experiments", "trigger", "corpus", "reserved", "release"])
def test_actual_dependency_changes_refuse_review(evidence, kind):
    root, entry, event, folder, backtest = evidence
    if kind == "settlement":
        put(folder / "settlement.json", {
            "target_date": "2026-07-01", "quality_grade": "complete",
            "polymarket_reconciliation": {"event_closed": False, "status": "match", "winning_markets": []}})
    elif kind == "barrier":
        put(backtest / "settled_day_analysis_barrier.json", {"target_date": "2026-07-01"})
    elif kind == "queue":
        audit = put(backtest / "model_market_disagreement_audit.jsonl", json.dumps({"audit_key": "k1", "event_slug": event}) + "\n")
        put(backtest / "model_market_disagreement_review_queue.json",
            {"source_audit_log_path": str(audit), "rows": [{"sample_audit_keys": ["k1"], "case_count": 1}]})
    elif kind == "experiments":
        put(backtest / "daily_learning.json", {"experiment_queue": {
            "status": "NONEMPTY", "summary": {"eligible_count": 1}, "items": []}})
    elif kind == "trigger":
        put(root / "data/snapshots/triggered_snapshot_queue/pending/new.json", {})
    elif kind == "corpus":
        put(backtest / "active_variant_shadow_window_corpus.json",
            {"entries": [{"event_slug": event, "snapshot_tape_path": str(folder / "clob_tokens.jsonl")}]})
    elif kind == "reserved":
        put(root / "docs/operations/reserved-confirmation-window.md", "A date is now reserved.")
    else:
        (root / "artifacts/releases").mkdir(parents=True)
    with pytest.raises(ValueError):
        run(evidence)
    assert not (root / "review").exists()
