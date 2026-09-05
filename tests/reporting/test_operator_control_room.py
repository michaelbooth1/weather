from datetime import datetime, timedelta, timezone

from weather.reporting.market.operator_control_room import (
    attention_rows,
    collect_control_room_snapshot,
    evaluate_control_room,
    latest_readiness,
)


TARGET_DATE = datetime.now(timezone.utc).date().isoformat()


def _artifact(payload, name):
    return {
        "available": True,
        "path": f"fixture://{name}.json",
        "recorded_at": "2026-08-15T14:05:00+00:00",
        "payload": {**payload, "generated_at_utc": datetime.now(timezone.utc).isoformat()},
    }


def _control_fixture():
    return {
        "target_date": TARGET_DATE,
        "run": _artifact(
            {
                "run_id": "pilot-1",
                "target_date": TARGET_DATE,
                "mode": "live-pilot",
                "markets": [{"market_id": "toronto"}],
                "budget_usdc": 100,
            },
            "run",
        ),
        "readiness": _artifact(
            {
                "generated_at_utc": "2026-08-15T14:05:00+00:00",
                "target_date": TARGET_DATE,
                "status": "PASS",
                "live_capital_permission": True,
                "requires_explicit_operator_approval": True,
                "blocker_count": 0,
                "next_actions": [],
            },
            "readiness",
        ),
        "platform_verification": _artifact(
            {
                "platform": "polymarket_global",
                "status": "PASS",
                "verified_for_target_date": TARGET_DATE,
            },
            "platform",
        ),
        "economics_snapshot": _artifact(
            {"platform": "polymarket_global", "target_date": TARGET_DATE},
            "economics-current",
        ),
        "economics_drift": _artifact(
            {
                "platform": "polymarket_global",
                "target_date": TARGET_DATE,
                "status": "PASS",
            },
            "economics-drift",
        ),
        "economics_accepted": _artifact(
            {"platform": "polymarket_global", "target_date": TARGET_DATE},
            "economics-accepted",
        ),
    }


def _operations_fixture():
    return {
        "host_status": {
            "available": True,
            "path": "fixture://status.ps1",
            "payload": {
                "ts": datetime.now(timezone.utc).isoformat(),
                "verdict": "OK",
                "flags": [],
                "streak": {"today": "ON_TRACK (100 caps, 0.0min max gap)"},
                "execution_tape": {
                    "process_healthy": True,
                    "capture_state": "CONNECTED",
                    "evidence_integrity": "PASS",
                    "price_path_usable": True,
                },
            },
        }
    }


def test_readiness_lookup_never_falls_back_to_a_different_target_date(tmp_path):
    receipt = tmp_path / "mm_live_readiness_old.json"
    receipt.write_text(
        '{"target_date": "2026-06-26", "status": "PASS"}\n',
        encoding="utf-8",
    )

    path, payload = latest_readiness(tmp_path, target_date=TARGET_DATE)

    assert path is None
    assert payload == {}


def test_collector_binds_readiness_to_latest_run_target(tmp_path):
    runs_root = tmp_path / "runs"
    backtest_root = tmp_path / "backtest"
    run_folder = runs_root / TARGET_DATE / "run-1"
    run_folder.mkdir(parents=True)
    backtest_root.mkdir()
    (run_folder / "run_summary.json").write_text(
        f'{{"run_id": "run-1", "target_date": "{TARGET_DATE}"}}\n',
        encoding="utf-8",
    )
    (backtest_root / "mm_live_readiness_current.json").write_text(
        f'{{"target_date": "{TARGET_DATE}", "status": "BLOCK"}}\n',
        encoding="utf-8",
    )
    for name in (
        "mm_platform_verification.json",
        "exchange_economics_snapshot.json",
        "exchange_economics_drift.json",
        "exchange_economics_accepted_snapshot.json",
    ):
        (backtest_root / name).write_text('{"status": "fixture"}\n', encoding="utf-8")

    snapshot = collect_control_room_snapshot(runs_root, backtest_root)

    assert snapshot["target_date"] == TARGET_DATE
    assert snapshot["run"]["payload"]["run_id"] == "run-1"
    assert snapshot["readiness"]["payload"]["target_date"] == TARGET_DATE
    assert snapshot["platform_verification"]["available"] is True
    assert snapshot["economics_accepted"]["available"] is True


def test_collector_does_not_adopt_legacy_readiness_without_a_current_run(tmp_path):
    runs_root = tmp_path / "runs"
    backtest_root = tmp_path / "backtest"
    backtest_root.mkdir()
    (backtest_root / "mm_live_readiness_legacy.json").write_text(
        '{"target_date": "2026-06-26", "status": "PASS"}\n',
        encoding="utf-8",
    )

    snapshot = collect_control_room_snapshot(runs_root, backtest_root)

    assert snapshot["target_date"] is None
    assert snapshot["readiness"]["available"] is False
    assert snapshot["readiness"]["payload"] == {}
    assert snapshot["readiness"]["error"] == "no current run target date is available"


def test_every_software_gate_only_reaches_ready_for_explicit_approval():
    evaluation = evaluate_control_room(_control_fixture(), _operations_fixture())

    assert evaluation["software_ready"] is True
    assert evaluation["verdict"] == "READY FOR EXPLICIT APPROVAL"
    assert all(state["status"] == "PASS" for state in evaluation["states"].values())


def test_stale_receipt_and_polymarket_us_identity_block():
    control = _control_fixture()
    control["readiness"]["available"] = False
    control["readiness"]["error"] = f"no readiness receipt for target date {TARGET_DATE}"
    control["platform_verification"]["payload"]["platform"] = "polymarket_us"

    evaluation = evaluate_control_room(control, _operations_fixture())
    rows = attention_rows(evaluation)

    assert evaluation["verdict"] == "HOLD"
    assert evaluation["states"]["Readiness"]["status"] == "UNAVAILABLE"
    assert "Polymarket US evidence is ineligible" in evaluation["states"]["International"]["detail"]
    assert any(row["Area"] == "International" for row in rows)


def test_unusable_authoritative_price_path_blocks():
    operations = _operations_fixture()
    operations["host_status"]["payload"]["execution_tape"]["price_path_usable"] = False

    evaluation = evaluate_control_room(_control_fixture(), operations)

    assert evaluation["verdict"] == "HOLD"
    assert evaluation["states"]["Execution tape"]["status"] == "BLOCK"
    assert "price path not usable" in evaluation["states"]["Execution tape"]["detail"]


def test_matching_old_dates_never_renew_current_readiness():
    control = _control_fixture()
    now = datetime.now(timezone.utc)
    for artifact in control.values():
        if isinstance(artifact, dict) and "payload" in artifact:
            artifact["payload"]["generated_at_utc"] = (now - timedelta(days=1)).isoformat()
            artifact["recorded_at"] = now.isoformat()
    evaluation = evaluate_control_room(control, _operations_fixture(), now=now)
    assert evaluation["software_ready"] is False
    assert evaluation["states"]["Readiness"]["status"] == "STALE"


def test_future_or_expired_observations_are_not_current():
    control = _control_fixture()
    now = datetime.now(timezone.utc)
    control["readiness"]["payload"]["generated_at_utc"] = (now + timedelta(hours=1)).isoformat()
    control["platform_verification"]["payload"]["expires_at_utc"] = now.isoformat()
    evaluation = evaluate_control_room(control, _operations_fixture(), now=now)
    assert evaluation["states"]["Readiness"]["status"] == "CLOCK ERROR"
    assert evaluation["states"]["International"]["status"] == "STALE"


def test_missing_host_and_run_identity_conflict_are_explicit():
    control = _control_fixture()
    control["readiness"]["payload"]["run_id"] = "different-run"
    evaluation = evaluate_control_room(control, {"host_status": {"available": False, "error": "collector failed"}})
    assert evaluation["states"]["Host"]["status"] == "UNAVAILABLE"
    assert evaluation["states"]["Host"]["detail"] == "collector failed"
    assert evaluation["states"]["Readiness"]["status"] == "BLOCK"


def test_closed_clean_capture_day_is_recognized():
    operations = _operations_fixture()
    operations["host_status"]["payload"]["streak"]["today"] = "CLEAN (142 caps, 0.0min max gap)"
    assert evaluate_control_room(_control_fixture(), operations)["states"]["Capture"]["status"] == "PASS"


def test_regenerating_receipts_does_not_make_an_old_market_current():
    control = _control_fixture()
    control["target_date"] = "2020-01-01"
    result = evaluate_control_room(control, _operations_fixture())
    assert result["states"]["Pilot envelope"]["status"] == "HISTORICAL"
    assert result["software_ready"] is False
