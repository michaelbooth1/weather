from datetime import datetime, timedelta, timezone
import hashlib
import json

from weather.reporting.market.operator_evidence import freshness, read_artifact
from weather.reporting.market.operator_session import collect_portable_session, portable_host_observation
from weather.reporting.market.operator_trading import collect_trading_snapshot
from weather.schema_registry import schema_version
from weather.market.mm_exchange_reports import INCENTIVE_CASH_ASSET


NOW = datetime(2026, 9, 6, 14, 2, tzinfo=timezone.utc)


def write(path, payload, *, sidecar=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if sidecar:
        path.with_suffix(".json.sha256").write_text(f"{digest}  {path.name}\n")
    return digest


def session_intent(root, stage="stage1_cancel_all"):
    payload = {
        "schema_version": schema_version("international_live_session_run_intent"),
        "stage": stage, "status": "ARMED",
        "candidate_sha256": "a" * 64,
        "created_at_local": (NOW - timedelta(seconds=30)).isoformat(),
        "run_not_after_local": (NOW + timedelta(seconds=210)).isoformat(),
    }
    digest = write(root / "session" / f"{stage}-run-intent.json", payload, sidecar=True)
    return payload, digest


def test_undated_file_cannot_be_renewed_by_its_mtime(tmp_path):
    path = tmp_path / "report.json"
    write(path, {"status": "PASS"})
    assert freshness(read_artifact(path), now=NOW)["status"] == "UNDATED"
    path.write_text("[]")
    assert read_artifact(path)["available"] is False
    path.write_bytes(b" " * 200)
    assert read_artifact(path, max_bytes=100)["available"] is False


def test_launch_intent_is_not_process_liveness_and_expires_unknown(tmp_path):
    session_intent(tmp_path)
    current = collect_portable_session(tmp_path, now=NOW)
    expired = collect_portable_session(tmp_path, now=NOW + timedelta(minutes=5))
    assert current["stages"][1]["state"] == "LAUNCH RECORDED"
    assert expired["stages"][1]["state"] == "OUTCOME UNKNOWN"
    assert expired["stages"][1]["result"] == {}


def test_terminal_receipt_is_historical_and_must_bind_to_intent(tmp_path):
    _, digest = session_intent(tmp_path)
    payload = {
        "schema_version": schema_version("international_live_session_run"),
        "stage": "stage1_cancel_all", "status": "PASS",
        "execution_host_profile": "portable_execution_v1",
        "candidate_sha256": "a" * 64, "run_intent": {"sha256": digest},
        "finished_at_local": NOW.isoformat(),
    }
    path = tmp_path / "session/stage1_cancel_all-run-receipt.json"
    write(path, payload, sidecar=True)
    snapshot = collect_portable_session(tmp_path, now=NOW + timedelta(days=1))
    assert snapshot["stages"][1]["state"] == "FINISHED · PASS"
    assert "historical" in snapshot["stages"][1]["detail"]
    payload["run_intent"]["sha256"] = "b" * 64
    write(path, payload, sidecar=True)
    assert collect_portable_session(tmp_path, now=NOW)["stages"][1]["state"] == "INVALID"
    path.write_text("{}")
    assert "FINISHED" not in collect_portable_session(tmp_path, now=NOW)["stages"][1]["state"]


def test_journal_is_bounded_and_does_not_expose_arbitrary_fields(tmp_path):
    session_intent(tmp_path)
    path = tmp_path / "stage1-cancel-all/lifecycle.jsonl"
    path.parent.mkdir()
    event = {"schema_version": schema_version("mm_live_lifecycle_probe_journal"),
             "recorded_at_utc": NOW.isoformat(), "event_type": "order_submitted",
             "order_id": "order-1", "credential": "DO-NOT-EXPOSE"}
    path.write_text((json.dumps(event) + "\n") * 110 + '{"event_type":')
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/credential-reference-manifest.json").write_text('{"secret":"DO-NOT-READ"}')
    snapshot = collect_portable_session(tmp_path, now=NOW)
    assert len(snapshot["events"]) == 100
    assert "DO-NOT-" not in json.dumps(snapshot)


def test_portable_host_receipt_is_schema_checked_and_aged(tmp_path):
    path = tmp_path / "host.json"
    write(path, {"schema_version": schema_version("international_live_execution_host_status"),
                 "checked_at_utc": (NOW - timedelta(hours=1)).isoformat(),
                 "status": "PASS", "flags": []})
    result = portable_host_observation(path, now=NOW)
    assert result["status"] == "STALE"
    assert result["recorded_status"] == "PASS"
    write(path, {"schema_version": "unknown", "checked_at_utc": NOW.isoformat()})
    assert portable_host_observation(path, now=NOW)["status"] == "INVALID"


def trading_reports(root, *, complete=False, paid=False):
    run = {"available": True, "path": str(root / "run_summary.json"),
           "payload": {"run_id": "run-1", "target_date": "2026-09-06", "mode": "live-pilot"}}
    exchange = {
        "schema_version": schema_version("mm_exchange_adapter"),
        "run_id": "run-1", "target_date": "2026-09-06", "generated_at_utc": NOW.isoformat(),
        "status": "PASS", "exchange_open_order_count": 0,
        "matched_orders": [], "positions": [],
        "user_stream_lifecycle_events": [
            {"transition": "filled", "exchange_order_id": "order-1", "fill_size": 5,
             "fill_price": 0.5, "credential": "DO-NOT-EXPOSE"}
        ],
    }
    financial = {
        "complete": complete, "financial_identity_inputs_verified": complete,
        "missing_evidence": [] if complete else ["wallet_credit"],
        "actual_total_pnl_after_fees_incentives_usdc": 1.25,
        "actual_maker_rebate_usdc": 0.2, "actual_liquidity_reward_usdc": 0.3,
        "actual_fees_usdc": 0, "expected_live_fill_rebate_usdc": 0.9,
    }
    if paid:
        financial.update(
            cash_asset=dict(INCENTIVE_CASH_ASSET),
            paid_cash_basis_verified=True,
            paid_incentive_reconciliation={
                "schema_version": schema_version("mm_paid_incentive_reconciliation"), "complete": True,
            },
        )
    report = {
        "schema_version": schema_version("mm_paid_incentive_pilot_report" if paid else "mm_exchange_adapter"),
        "run_id": "run-1", "target_date": "2026-09-06", "generated_at_utc": NOW.isoformat(),
        "financial_reconciliation_complete": complete, "financial_reconciliation": financial,
    }
    if paid:
        report["cash_asset"] = dict(INCENTIVE_CASH_ASSET)
    write(root / "exchange_reconciliation.json", exchange)
    write(root / "mm2_pilot_report.json", report)
    return run, exchange, report


def test_incomplete_accounting_cannot_become_profit_or_paid_incentives(tmp_path):
    run, _, _ = trading_reports(tmp_path)
    result = collect_trading_snapshot(run, now=NOW)
    assert result["amounts"]["Net reconciled P&L"] is None
    assert result["amounts"]["Paid maker rebates"] is None
    assert result["amounts"]["Paid liquidity rewards"] is None
    assert result["amounts"]["Estimated fill rebates"] == 0.9
    assert result["amounts"]["Actual fees"] == 0
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


def test_paid_amounts_are_reported_separately_from_estimates(tmp_path):
    run, _, _ = trading_reports(tmp_path, complete=True, paid=True)
    result = collect_trading_snapshot(run, now=NOW + timedelta(hours=1))
    assert result["amounts"]["Paid maker rebates"] == 0.2
    assert result["amounts"]["Paid liquidity rewards"] == 0.3
    assert result["amounts"]["Net reconciled P&L"] == 1.25
    assert result["reconciliation"]["status"] == "STALE"


def test_different_run_and_mixed_timestamp_reports_are_rejected(tmp_path):
    run, exchange, report = trading_reports(tmp_path, complete=True, paid=True)
    report["run_id"] = "another-run"
    write(tmp_path / "mm2_pilot_report.json", report)
    result = collect_trading_snapshot(run, now=NOW)
    assert result["accounting"]["status"] == "UNAVAILABLE"
    assert result["amounts"]["Net reconciled P&L"] is None
    report["run_id"] = "run-1"
    report["generated_at_utc"] = (NOW - timedelta(seconds=1)).isoformat()
    write(tmp_path / "mm2_pilot_report.json", report)
    assert collect_trading_snapshot(run, now=NOW)["accounting"]["status"] == "UNAVAILABLE"
    exchange["run_id"] = "another-run"
    write(tmp_path / "exchange_reconciliation.json", exchange)
    result = collect_trading_snapshot(run, now=NOW)
    assert result["orders"] == [] and result["fills"] == []
    assert result["open_orders"] is None


def test_wrong_cash_asset_is_not_labeled_as_pusd(tmp_path):
    run, _, report = trading_reports(tmp_path, complete=True, paid=True)
    report["cash_asset"]["symbol"] = "USDC"
    write(tmp_path / "mm2_pilot_report.json", report)
    result = collect_trading_snapshot(run, now=NOW)
    assert result["amounts"]["Paid maker rebates"] is None
    assert result["amounts"]["Net reconciled P&L"] is None
    assert result["accounting"]["status"] == "UNAVAILABLE"
