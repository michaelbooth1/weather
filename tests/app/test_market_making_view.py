from datetime import date

from app.table_utils import arrow_safe_records
from app.views.market_making import (
    _df,
    _blocker_rows,
    _budget_lifecycle_rows,
    _event_gate_rows,
    _gate_progress_rows,
    _latest_readiness,
    _market_health_rows,
    _readiness_action_rows,
    _readiness_summary_rows,
    _runtime_identity_rows,
)
from weather.reporting.market.market_making_dashboard import (
    latest_run,
    read_csv,
    read_json,
    read_jsonl,
    read_jsonl_tail,
    run_folders,
)


def test_market_making_dashboard_service_reads_artifacts(tmp_path):
    run_folder = tmp_path / "2026-06-15" / "run-1"
    run_folder.mkdir(parents=True)
    (run_folder / "run_summary.json").write_text('{"run_id": "run-1"}\n', encoding="utf-8")
    (run_folder / "quote_intents_long.csv").write_text("market_id,quote_permission\natlanta,True\n", encoding="utf-8")
    (run_folder / "events.jsonl").write_text('{"event": "one"}\nnot-json\n{"event": "two"}\n', encoding="utf-8")

    folders = run_folders(tmp_path)
    latest_folder, summary = latest_run(tmp_path)

    assert folders == [run_folder]
    assert latest_folder == run_folder
    assert summary["run_id"] == "run-1"
    assert read_json(run_folder / "run_summary.json")["run_id"] == "run-1"
    assert read_csv(run_folder / "quote_intents_long.csv")[0]["market_id"] == "atlanta"
    assert read_jsonl(run_folder / "events.jsonl")[1]["raw"] == "not-json"
    assert read_jsonl_tail(run_folder / "events.jsonl", limit=1)[0]["event"] == "two"


def test_market_making_cockpit_helpers_render_artifact_drilldowns():
    markets = [
        {
            "market_id": "atlanta",
            "status": "BLOCK",
            "source_status_rows": 0,
            "model_age_seconds": 90.0,
            "book_audit": {
                "trailing_age_seconds": 15.0,
                "gaps_over_threshold": 0,
            },
            "promotion_state": "SHADOW",
            "blocking_reasons": ["missing current source-status rows"],
            "gates": [
                {"name": "observation_trigger", "ok": True},
            ],
        }
    ]
    quote_rows = [
        {
            "generated_at_utc": "2026-06-15T15:00:00+00:00",
            "market_id": "atlanta",
            "quote_permission": "True",
            "reason_code": "QUOTE_HARVEST_MID",
            "known_edge_permission": "harvest_only",
            "source_freshness_state": "all_fresh",
            "event_gate_status": "CLEAR",
            "event_gate_next_event_at_utc": "2026-06-15T15:52:00+00:00",
        },
        {
            "generated_at_utc": "2026-06-15T15:01:00+00:00",
            "market_id": "atlanta",
            "quote_permission": "False",
            "reason_code": "NO_QUOTE_MISSING_PREFLIGHT",
            "known_edge_permission": "harvest_only",
            "source_freshness_state": "failed:wu_history",
            "event_gate_status": "PULL",
            "event_gate_next_event_at_utc": "2026-06-15T16:52:00+00:00",
        },
    ]
    lifecycle_rows = [
        {
            "transition": "paper_posted",
            "lifecycle_key": "k1",
            "market_id": "atlanta",
            "remaining_risk_usdc": "4.9",
        }
    ]
    remediation = {
        "incident_count": 1,
        "counts_toward_live_forward_gate": False,
        "incidents": [
            {
                "market_id": "atlanta",
                "root_cause": "missing_source_status_row",
                "owner": "snapshot source-status writer",
                "recoverable_same_day": True,
                "suggested_command": "python -m weather.collection.snapshot_tracker --status",
            }
        ],
    }
    run_summary = {
        "order_lifecycle": {
            "current_reserved_usdc": 4.9,
            "current_open_order_count": 1,
            "released_this_tick_usdc": 2.0,
            "posted_this_tick_count": 0,
            "stale_open_order_count": 0,
            "platform_balance_semantics": {
                "operator_run_budget_is_binding": True,
                "polymarket_cross_market_open_orders_may_exceed_wallet_balance": True,
            },
        },
        "preflight_remediation": remediation,
        "information_event_gate": {
            "pull_rows": 1,
            "widen_rows": 0,
            "exception_rows": 0,
            "active_events": [
                {
                    "event_id": "atlanta:metar_print_window:20260615T160000Z",
                    "market_id": "atlanta",
                    "event_class": "metar_print_window",
                    "action": "suppress",
                    "starts_at_utc": "2026-06-15T15:47:00+00:00",
                    "ends_at_utc": "2026-06-15T15:59:00+00:00",
                }
            ],
            "next_events": [
                {
                    "event_id": "atlanta:metar_print_window:20260615T170000Z",
                    "market_id": "atlanta",
                    "event_class": "metar_print_window",
                    "starts_at_utc": "2026-06-15T16:47:00+00:00",
                }
            ],
        },
    }
    paper = {
        "summary": {
            "gate_status": "OPEN",
            "anti_overfit": {"live_forward_days": ["2026-06-14"]},
            "event_gate_score": {"narrowing_gate": "NEEDS_MARKOUT_EVIDENCE"},
        }
    }

    health = _market_health_rows(markets, quote_rows, lifecycle_rows, remediation)
    blockers = _blocker_rows(quote_rows, remediation)
    budget = _budget_lifecycle_rows(run_summary)
    gate = _gate_progress_rows(run_summary, paper)
    event_gate = _event_gate_rows(run_summary, paper)

    assert health[0]["Top blocker"] == "missing_source_status_row"
    assert health[0]["Open orders"] == 1
    assert health[0]["Reserved USDC"] == 4.9
    assert health[0]["Event gate"] == "PULL"
    assert blockers[0]["Owner"] == "snapshot source-status writer"
    assert blockers[0]["Rows"] == 1
    assert any(row["Metric"] == "Cross-market gross can exceed wallet" and row["Value"] is True for row in budget)
    assert any(row["Metric"] == "Current run counts" and row["Value"] is False for row in gate)
    assert any(row["Metric"] == "Locked paper days" and row["Value"] == 1 for row in gate)
    assert any(row["Kind"] == "Active" and row["Class"] == "metar_print_window" for row in event_gate)
    assert any(row["Event"] == "Narrowing gate" and row["Ends"] == "NEEDS_MARKOUT_EVIDENCE" for row in event_gate)


def test_market_making_value_tables_are_arrow_safe_and_runtime_identity_rows_render():
    frame = _df([
        {"Metric": "Target date", "Value": "2026-06-15"},
        {"Metric": "Open orders", "Value": 2},
        {"Metric": "Current run counts", "Value": False},
        {"Metric": "Generated", "Value": date(2026, 6, 15)},
        {"Metric": "Payload", "Value": {"ok": True}},
    ])

    assert frame["Value"].tolist() == ["2026-06-15", "2", "False", "2026-06-15", '{"ok": true}']

    rows = _runtime_identity_rows({
        "loops": [
            {
                "name": "clob_books",
                "runtime_code_state": "different",
                "pid": 123,
                "consecutive_errors": 0,
                "last_heartbeat": "2026-06-15T23:00:00+00:00",
                "process_identity_text": "old",
                "current_identity_text": "new",
                "status_path": "data/snapshots/clob_loop_status.json",
            }
        ]
    })

    assert rows[0]["Loop"] == "clob_books"
    assert rows[0]["Code state"] == "different"
    assert rows[0]["Running code"] == "old"


def test_market_making_cockpit_surfaces_latest_live_readiness_no_go(tmp_path):
    older = tmp_path / "mm_live_readiness_old.json"
    older.write_text(
        '{"target_date": "2026-06-26", "status": "PASS", "summary": {}}\n',
        encoding="utf-8",
    )
    latest = tmp_path / "mm_live_readiness_current.json"
    latest.write_text(
        """
{
  "status": "BLOCK",
  "live_capital_permission": false,
  "requires_explicit_operator_approval": true,
  "blocker_count": 11,
  "target_date": "2026-06-27",
  "summary": {
    "evidence_mode": "active_day_live_forward",
    "current_counts_toward_live_forward_gate": false,
    "live_forward_gate_status": "BLOCK",
    "preflight_status": "BLOCK",
    "latest_tick_first_failing_gate": "source_status_degradation",
    "latest_tick_quote_permission_rows": 0,
    "latest_tick_live_trade_permission_rows": 0,
    "source_status_blocker_root_cause_class": "settlement_source_auth_failure",
    "source_status_blocked_market_count": 12,
    "source_status_settlement_auth_failures": 12
  },
  "next_actions": [
    {
      "priority": 10,
      "gate_id": "latest_preflight_passes",
      "category": "data_preflight",
      "safe_next_step": "verify free-source replacement coverage and rebuild source status",
      "detail": "latest selected run preflight is stale or blocked",
      "evidence": {"status": "BLOCK"}
    }
  ]
}
""",
        encoding="utf-8",
    )

    path, readiness = _latest_readiness(tmp_path, target_date="2026-06-27")
    summary_rows = _readiness_summary_rows(readiness)
    action_rows = _readiness_action_rows(readiness)

    assert path == latest
    assert readiness["status"] == "BLOCK"
    assert any(
        row["Metric"] == "Source-status root cause"
        and row["Value"] == "settlement_source_auth_failure"
        for row in summary_rows
    )
    assert not any("credential present" in str(row["Metric"]).lower() for row in summary_rows)
    assert action_rows[0]["Gate"] == "latest_preflight_passes"
    assert "free-source replacement" in action_rows[0]["Step"]


def test_market_making_mixed_display_columns_are_arrow_safe():
    frame = _df([
        {"Market": "atlanta", "Recoverable today": True, "Rows": 2},
        {"Market": "nyc", "Recoverable today": "-", "Rows": 1},
    ])

    assert frame["Recoverable today"].tolist() == ["True", "-"]
    assert frame["Rows"].tolist() == [2, 1]


def test_arrow_safe_records_normalizes_mixed_operation_rows():
    rows = arrow_safe_records([
        {"Task": "one", "Registered": True, "Last Run": date(2026, 6, 15), "Result": 0},
        {"Task": "two", "Registered": "-", "Last Run": "-", "Result": "missing"},
    ])

    assert rows[0]["Registered"] == "True"
    assert rows[0]["Last Run"] == "2026-06-15"
    assert rows[0]["Result"] == "0"
