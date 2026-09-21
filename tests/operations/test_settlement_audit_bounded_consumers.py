"""Daily retry rebuilds a fresh index; trading gates never load the full audit."""

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.operations import daily_refresh_trading_steps as daily
from weather.reporting.market import trading_evidence
from weather.reporting.source_gates import settlement_source_audit as audit


def test_daily_retry_releases_old_index_and_rebuilds_corrected_truth(tmp_path, monkeypatch):
    ledger = tmp_path / "settlements/atlanta/ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    row = {"event_slug": "today", "market_id": "atlanta", "target_date": "2026-06-19",
           "settlement_bucket": 80, "settlement_source": "daily_summary",
           "quality_grade": "partial", "reconciliation_status": "fetch_error"}
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    args = SimpleNamespace(labels_csv=str(tmp_path / "absent.csv"),
                           ledger_root=str(ledger.parent.parent),
                           backtest_root=str(tmp_path / "backtest"),
                           settled_analysis_target_date="2026-06-19")
    active = 0
    openings = 0
    real_open = audit.open_settlement_source_audit

    @contextmanager
    def observed_open(**kwargs):
        nonlocal active, openings
        assert active == 0, "Retry retained the complete old index"
        openings += 1
        active += 1
        try:
            with real_open(**kwargs) as payload:
                yield payload
        finally:
            active -= 1

    def retry(retry_args, slugs):
        assert retry_args is args
        assert slugs == ["today"]
        revised = {**row, "quality_grade": "complete", "reconciliation_status": "match"}
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(revised) + "\n")
        return {"refinalized_count": 1}

    def materialization_forbidden(**_):
        raise AssertionError("Daily audit used materialized compatibility API")

    monkeypatch.setattr(audit, "open_settlement_source_audit", observed_open)
    monkeypatch.setattr(audit, "build_settlement_source_audit", materialization_forbidden)
    monkeypatch.setattr(daily, "_retry_provisional_reconciliation", retry)
    result = daily.run_settlement_source_audit_step(args)
    assert openings == 2 and active == 0
    assert result["status"] == "PASS"
    assert result["label_count"] == 1
    assert result["reconciliation_retry"]["refinalized_count"] == 1
    assert list((tmp_path / "backtest/settlement_source_audit_work").iterdir()) == []
    assert json.loads(Path(result["json_out"]).read_text())["rows"][0]["status"] == "FINALIZED"


@pytest.mark.parametrize("truncated", [False, True])
def test_trading_consumer_uses_bounded_reader_and_checks_tail(tmp_path, monkeypatch, truncated):
    path = tmp_path / "audit.json"
    contents = json.dumps({"status": "PASS", "rows": [
        {"target_date": "2026-06-19", "promotion_blocker": False}]})
    path.write_text(contents[:-1] if truncated else contents)

    def no_materialized_json(*_):
        raise AssertionError("Trading evidence loaded the complete audit")

    monkeypatch.setattr(trading_evidence, "_read_json", no_materialized_json)
    taker = {"target_date": "2026-06-19", "summary": {"settled_order_count": 1}}
    gate = trading_evidence._settlement_source_audit_gate(path, [(taker, None)])
    assert gate["status"] == ("BLOCK" if truncated else "PASS")
