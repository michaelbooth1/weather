from app.views.market_making import (
    _df,
    _blocker_rows,
    _budget_lifecycle_rows,
    _gate_progress_rows,
    _market_health_rows,
    _runtime_identity_rows,
)


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
        },
        {
            "generated_at_utc": "2026-06-15T15:01:00+00:00",
            "market_id": "atlanta",
            "quote_permission": "False",
            "reason_code": "NO_QUOTE_MISSING_PREFLIGHT",
            "known_edge_permission": "harvest_only",
            "source_freshness_state": "failed:wu_history",
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
                "suggested_command": "python -m src.snapshot_tracker status",
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
    }
    paper = {
        "summary": {
            "gate_status": "OPEN",
            "anti_overfit": {"live_forward_days": ["2026-06-14"]},
        }
    }

    health = _market_health_rows(markets, quote_rows, lifecycle_rows, remediation)
    blockers = _blocker_rows(quote_rows, remediation)
    budget = _budget_lifecycle_rows(run_summary)
    gate = _gate_progress_rows(run_summary, paper)

    assert health[0]["Top blocker"] == "missing_source_status_row"
    assert health[0]["Open orders"] == 1
    assert health[0]["Reserved USDC"] == 4.9
    assert blockers[0]["Owner"] == "snapshot source-status writer"
    assert blockers[0]["Rows"] == 1
    assert any(row["Metric"] == "Cross-market gross can exceed wallet" and row["Value"] is True for row in budget)
    assert any(row["Metric"] == "Current run counts" and row["Value"] is False for row in gate)
    assert any(row["Metric"] == "Locked paper days" and row["Value"] == 1 for row in gate)


def test_market_making_value_tables_are_arrow_safe_and_runtime_identity_rows_render():
    frame = _df([
        {"Metric": "Target date", "Value": "2026-06-15"},
        {"Metric": "Open orders", "Value": 2},
        {"Metric": "Current run counts", "Value": False},
    ])

    assert frame["Value"].tolist() == ["2026-06-15", "2", "False"]

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
