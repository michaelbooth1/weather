"""Audit-only adversarial witnesses for source 06979f4a5; no network or live state.

These assertions describe CURRENT defects, not the behavior a repair should retain.
"""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import runpy

import pytest
from weather.paths import REPO_ROOT
from weather.reporting.market.operator_control_room import evaluate_control_room, latest_run
from weather.reporting.market.operator_trading import collect_trading_snapshot
from weather.market.mm_exchange_reports import actual_fee_reconciliation
from weather.operations import location_config_refresh as refresh

CONTROL = runpy.run_path(str(REPO_ROOT / "tests/reporting/test_operator_control_room.py"))
MONITOR = runpy.run_path(str(REPO_ROOT / "tests/reporting/test_operator_monitor.py"))

def test_economics_pass_ignores_mismatched_evidence_hashes():
    control = CONTROL["_control_fixture"]()
    control["economics_snapshot"]["payload"]["exchange_economics_hash"] = "a" * 64
    control["economics_accepted"]["payload"]["exchange_economics_hash"] = "b" * 64
    control["economics_drift"]["payload"].update(current_snapshot_hash="c" * 64,
                                                 accepted_snapshot_hash="d" * 64)
    result = evaluate_control_room(control, CONTROL["_operations_fixture"]())
    assert result["states"]["Economics"]["status"] == "PASS"
    assert result["software_ready"] is True

def test_unknown_readiness_schema_and_conflicting_blockers_pass_display():
    control = CONTROL["_control_fixture"]()
    control["readiness"]["payload"].update(schema_version="unrecognized", blocker_count=3,
                                            blockers=["test-blocker"])
    result = evaluate_control_room(control, CONTROL["_operations_fixture"]())
    assert result["states"]["Readiness"]["status"] == "PASS"
    assert result["software_ready"] is True

def test_legacy_wrong_cash_asset_is_reported_as_complete():
    run, exchange, report = MONITOR["trading_reports"](
        Path(pytest.audit_tmp), complete=True, paid=False)
    report["cash_asset"] = {"symbol": "USDC", "chain_id": 1, "decimals": 6}
    report["financial_reconciliation"]["cash_asset"] = deepcopy(report["cash_asset"])
    MONITOR["write"](Path(pytest.audit_tmp) / "mm2_pilot_report.json", report)
    result = collect_trading_snapshot(run, now=MONITOR["NOW"])
    assert result["accounting"]["status"] == "CURRENT"
    assert result["accounting_complete"] is True
    assert result["amounts"]["Net reconciled P&L"] == 1.25

def test_malformed_nested_host_evidence_raises_instead_of_independent_panel():
    operations = CONTROL["_operations_fixture"]()
    operations["host_status"]["payload"]["streak"] = ["unexpected", "shape"]
    with pytest.raises(AttributeError):
        evaluate_control_room(CONTROL["_control_fixture"](), operations)

def test_1025_historical_runs_hide_all_runs(tmp_path):
    for number in range(1025):
        path = tmp_path / "2026-09-06" / str(number) / "run_summary.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"run_id":str(number),"target_date":"2026-09-06",
                                     "generated_at_utc":"2026-09-06T14:00:00+00:00"}))
    assert latest_run(tmp_path) == (None, {})

def test_resolution_rule_change_does_not_change_normalized_metadata():
    event = {"id":"1", "slug":"highest-temperature-in-nyc-on-september-6-2026",
             "resolutionSource":"https://www.weather.gov/wrh/timeseries?site=klga",
             "description":"Hourly only; revisions freeze at first next-day reading.",
             "markets":[{"id":"2","description":"Hourly only","resolutionSource":"NOAA",
                         "conditionId":"0x"+"b"*64,"outcomes":["Yes","No"],
                         "clobTokenIds":["1","2"]}]}
    changed = deepcopy(event)
    changed["description"] = "All observations; revisions allowed for a further day."
    changed["markets"][0]["description"] = "All observations"
    changed["markets"][0]["resolutionSource"] = "Different authority"
    assert refresh.normalized_event(event) == refresh.normalized_event(changed)

def test_resolution_spec_ignores_configured_resolution_source():
    from dataclasses import replace
    from weather.market.market_registry import spec_for_id
    from weather.backtesting.settlement_ledger import resolution_spec_for
    market = replace(spec_for_id("nyc"), resolution_source="noaa_hourly")
    assert resolution_spec_for(market)["resolution_source_type"] == "wunderground_history"

def test_full_final_pagination_page_is_returned_as_success(monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()
    calls = []
    def opened(*args, **kwargs):
        calls.append(args[0].full_url)
        return Response(b'[{"id":"first"}]')
    monkeypatch.setattr(refresh.urllib.request, "urlopen", opened)
    rows, offsets = refresh.fetch_gamma_events(limit=1, max_pages=1)
    assert rows == [{"id":"first"}] and offsets == [0] and len(calls) == 1

def test_nonfinite_fee_count_is_a_rejected_suspicion_and_fails_closed():
    result = actual_fee_reconciliation({"actual_fee_evidence": {"observed_fill_count": "nan"}}, [])
    assert result["complete"] is False
    assert "actual_fee_fill_count_mismatch" in result["blockers"]

@pytest.fixture(autouse=True)
def _scratch(tmp_path):
    pytest.audit_tmp = str(tmp_path)

def test_stale_unknown_recon_schema_changes_policy_parameters(tmp_path):
    from weather.market.clob_recon import policy_overrides_from_recon
    path = tmp_path / "old-recon.json"
    path.write_text(json.dumps({"schema_version":"unknown", "generated_at_utc":"2020-01-01T00:00:00Z",
                                "policy_parameter_suggestions":{"quote_size":25.0,"harvest_half_spread":0.001}}))
    overrides, diagnostic = policy_overrides_from_recon(path)
    assert overrides == {"quote_size":25.0,"harvest_half_spread":0.001}
    assert diagnostic["applied_keys"] == ["harvest_half_spread","quote_size"]

def test_future_model_and_negative_book_watcher_ages_can_quote_in_paper():
    from weather.market.mm_policy import decide_quote
    policy = runpy.run_path(str(REPO_ROOT / "tests/market/test_mm_policy.py"))
    row = policy["fresh_row"](captured_at_utc="2027-06-14T15:59:30+00:00",
                              clob_book_age_seconds=-3600.0, watcher_age_seconds=-3600.0)
    result = decide_quote(row, now=policy["NOW"])
    assert result["quote_permission"] is True
    assert result["live_trade_permission"] is False
    assert result["model_age_seconds"] == 0.0

def test_signed_temperature_label_is_changed_in_serving_and_settlement():
    from weather.model.model_presentation import PresentationMixin
    from weather.model.model_base import ModelUtilsMixin
    from weather.market.market_registry import spec_for_id
    from weather.backtesting.settlement_ledger import parse_band_label, resolve_outcome
    class Model(PresentationMixin, ModelUtilsMixin):
        spec = spec_for_id("toronto")
    event = {"markets":[{"groupItemTitle":"-5 C or below","outcomes":["Yes","No"],
                        "outcomePrices":["0.5","0.5"]}]}
    assert Model().market_bins(event)[0]["value"] == 5
    parsed = parse_band_label("-5 C or below")
    assert parsed["value"] == 5
    assert resolve_outcome(parsed["kind"], parsed["value"], 0, parsed["value_hi"]) is True

def test_hyphenated_positive_band_fallback_scores_a_winning_bucket_as_loss():
    from weather.market.mm_paper_scoring import band_key, settlement_outcome_for_leg
    leg = {"range_label":"80-81 F"}
    assert band_key(leg) == ("eq",80,-81)
    assert settlement_outcome_for_leg(leg, {"settlement_bucket":80}) == 0.0
