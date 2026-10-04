"""Maker paper-score freshness fails closed (owner decision 2026-10-04, test-suite review K freshness#3).

Only PASS leaves maker evidence countable: STALE and NO_ACTIVE_DAY both block it.
"""
import json
from pathlib import Path

from weather.market.mm_paper_scoring import maker_paper_score_freshness


def _run(root, run_id, target_date, *, active):
    folder = Path(root) / "mm_runs" / target_date / run_id
    folder.mkdir(parents=True)
    summary = {
        "schema_version": "mm_run_v0.2",
        "run_id": run_id,
        "mode": "paper-live-forward",
        "target_date": target_date,
        "generated_at_utc": f"{target_date}T20:00:00+00:00",
    }
    if active:
        summary["evidence_mode"] = "active_day_live_forward"
        summary["counts_toward_live_forward_gate"] = True
    (folder / "run_config.json").write_text(json.dumps({"run_id": run_id, "target_date": target_date}), encoding="utf-8")
    (folder / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    # A quote_intents_long.csv next to the summary marks the run completed.
    (folder / "quote_intents_long.csv").write_text(f"run_id\n{run_id}\n", encoding="utf-8")
    return folder


def test_no_active_day_blocks_maker_evidence_countability(tmp_path):
    not_active = _run(tmp_path, "not-active", "2026-06-18", active=False)
    freshness = maker_paper_score_freshness([not_active], [])
    assert freshness["status"] == "NO_ACTIVE_DAY"
    assert freshness["blocks_maker_evidence_countability"] is True
    assert maker_paper_score_freshness([], [])["blocks_maker_evidence_countability"] is True


def test_stale_still_blocks_and_pass_does_not(tmp_path):
    old = _run(tmp_path, "old-active", "2026-06-18", active=True)
    new = _run(tmp_path, "new-active", "2026-06-19", active=True)
    stale = maker_paper_score_freshness([old, new], [old])
    assert stale["status"] == "STALE"
    assert stale["blocks_maker_evidence_countability"] is True
    current = maker_paper_score_freshness([old, new], [old, new])
    assert current["status"] == "PASS"
    assert current["blocks_maker_evidence_countability"] is False
