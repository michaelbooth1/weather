"""The additional archive scope requires its exact reviewed plan and retained inputs."""
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from weather.operations import cold_archive_campaign_review as review
from test_cold_archive_campaign_review import evidence, put, run


PLAN = "c" * 64


def bind_next_selection(evidence, monkeypatch):
    monkeypatch.setattr(review, "NEXT50_APPROVED_PLAN_SHA256", PLAN)
    evidence[1]["plan_sha256"] = PLAN


def change_event(evidence, target_date):
    root, entry, old_event, folder, backtest = evidence
    parsed = datetime.fromisoformat(target_date)
    event = f"highest-temperature-in-atlanta-on-{parsed.strftime('%B').lower()}-{parsed.day}-{parsed.year}"
    new_folder = folder.with_name(event)
    folder.rename(new_folder)
    entry["files"][0]["path"] = f"snapshots/{event}/clob_tokens.jsonl"
    settlement = json.loads((new_folder / "settlement.json").read_bytes())
    settlement["target_date"] = target_date
    put(new_folder / "settlement.json", settlement)
    put(backtest / "active_variant_shadow_window_corpus.json", {
        "entries": [{"event_slug": event, "snapshot_tape_path": str(new_folder / "snapshots_long.csv")}]})
    return root, entry, event, new_folder, backtest


@pytest.mark.parametrize("target_date", ["2026-06-01", "2026-08-01", "2026-08-14"])
def test_next_selection_accepts_only_cold_dates_in_reviewed_range(evidence, monkeypatch, target_date):
    bind_next_selection(evidence, monkeypatch)
    root, entry, *_ = change_event(evidence, target_date)
    result = review.review_sources(
        production_root=root, entry=entry, entry_sha256="b" * 64,
        output_root=root / "review", now=datetime(2026, 9, 14, tzinfo=timezone.utc))
    checked = json.loads(Path(result["path"]).read_bytes())
    assert checked["market_days"][0]["target_date"] == target_date
    observed = json.loads((root / "review/observations.json").read_bytes())
    assert observed["approved_plan_sha256"] == PLAN


@pytest.mark.parametrize("plan", [None, "", "d" * 64])
def test_old_or_unknown_plan_cannot_extend_dates(evidence, monkeypatch, plan):
    bind_next_selection(evidence, monkeypatch)
    root, entry, *_ = change_event(evidence, "2026-08-01")
    entry["plan_sha256"] = plan
    with pytest.raises(ValueError, match="outside approved"):
        run((root, entry))
    assert not (root / "review").exists()


@pytest.mark.parametrize("target_date", ["2026-05-31", "2026-08-15"])
def test_next_selection_cannot_extend_its_bound_date_range(evidence, monkeypatch, target_date):
    bind_next_selection(evidence, monkeypatch)
    changed = change_event(evidence, target_date)
    with pytest.raises(ValueError, match="outside approved"):
        run(changed)


def test_next_selection_keeps_the_thirty_day_hot_window(evidence, monkeypatch):
    bind_next_selection(evidence, monkeypatch)
    changed = change_event(evidence, "2026-08-14")
    with pytest.raises(ValueError, match="thirty-day"):
        run(changed)


@pytest.mark.parametrize("family", [
    "clob_tokens.csv", "variant_predictions_long.csv", "snapshots_long.csv",
    "replay_inputs.jsonl", "settlement.json", "forecast_payloads.jsonl",
    "snapshot_explanations_long.csv"])
def test_next_selection_cannot_archive_routine_or_weather_inputs(evidence, monkeypatch, family):
    bind_next_selection(evidence, monkeypatch)
    evidence[1]["files"][0]["path"] = f"snapshots/{evidence[2]}/{family}"
    with pytest.raises(ValueError, match="unreviewed detail"):
        run(evidence)


def test_canonical_gzip_book_requires_the_new_exact_plan(evidence, monkeypatch):
    root, entry, event, *_ = evidence
    entry["files"][0]["path"] = f"snapshots/{event}/order_books.jsonl.gz"
    with pytest.raises(ValueError, match="unreviewed detail"):
        run(evidence)
    assert not (root / "review").exists()
    bind_next_selection(evidence, monkeypatch)
    checked, _, _ = run(evidence)
    assert checked["selection_kind"] == "primary"
