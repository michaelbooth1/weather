from unittest import mock

from streamlit.testing.v1 import AppTest

from app.views.overview import _candidate_link


_PROVIDER = (
    "weather.reporting.market.capital_canary_dashboard."
    "load_capital_canary_dashboard"
)


def _visible_text(app_test):
    elements = [
        *app_test.title,
        *app_test.markdown,
        *app_test.caption,
        *app_test.info,
        *app_test.success,
        *app_test.warning,
        *app_test.error,
    ]
    return "\n".join(str(element.value) for element in elements)


def _base_payload():
    return {
        "schema_version": "capital_canary_dashboard_v0.1",
        "generated_at_utc": "2026-07-21T20:00:00+00:00",
        "source_status": "FRESH",
        "display_state": "LOCKED",
        "status_message": "Production readiness is NOT_READY; capital remains locked.",
        "as_of_utc": "2026-07-21T19:59:58+00:00",
        "heartbeat": {
            "at_utc": "2026-07-21T19:59:58+00:00",
            "age_seconds": 2,
            "freshness": "FRESH",
        },
        "freshness": {
            "stale": False,
            "status_data_stale": False,
            "position_data_stale": False,
            "portfolio_data_stale": False,
            "not_assumed_flat": False,
        },
        "safety": {
            "authority_state": "LOCKED",
            "campaign_stage": "LIFECYCLE_PROBE",
            "capital_locked": True,
            "kill_switch_engaged": True,
            "reconciliation_state": "NOT_STARTED",
            "activation_status": "MISSING",
            "activation_expires_at_utc": None,
            "order_submission_enabled": False,
            "classification_only": True,
        },
        "readiness": {
            "classification": "NOT_READY",
            "classification_only": True,
            "grants_authority": False,
        },
        "account": {
            "platform": "polymarket",
            "redacted_account_id": "sha256:0123456789ab...",
            "net_liquidation_value_usdc": None,
            "cash_usdc": None,
            "reserve_usdc": None,
            "unresolved_worst_case_loss_usdc": None,
            "capital_ceiling_usdc": 75.0,
            "cap_utilization": None,
        },
        "performance": {
            "settled_realized_pnl_usdc": None,
            "unrealized_executable_bid_pnl_usdc": None,
            "fees_usdc": None,
            "drawdown_usdc": None,
            "market_following_pnl_usdc": None,
            "no_trade_pnl_usdc": None,
        },
        "positions": [],
        "targets": [],
        "activity": [],
        "blockers": [
            {
                "code": "production_readiness_not_ready",
                "detail": "The exact production release has not passed the capital gate.",
            }
        ],
        "warnings": ["Credentials are not resolved while capital is locked."],
        "provenance": {
            "release_id": "research-unbound",
            "platform": "polymarket",
            "redacted_account_id": "sha256:0123456789ab...",
            "policy_id": "capital-canary-v1",
            "schema_version": "capital_canary_dashboard_v0.1",
            "sequence": 0,
        },
    }


def _probe_payload():
    payload = _base_payload()
    payload.update(
        {
            "display_state": "PROBE",
            "status_message": "Supervised lifecycle probe is reconciled and scanning.",
        }
    )
    payload["safety"].update(
        {
            "authority_state": "ARMED",
            "capital_locked": False,
            "kill_switch_engaged": False,
            "reconciliation_state": "RECONCILED",
            "activation_status": "ACTIVE",
            "activation_expires_at_utc": "2026-07-22T20:00:00+00:00",
            "order_submission_enabled": True,
        }
    )
    payload["readiness"]["classification"] = "CAPITAL_CANARY"
    payload["account"].update(
        {
            "net_liquidation_value_usdc": 75.12,
            "cash_usdc": 74.62,
            "reserve_usdc": 71.62,
            "unresolved_worst_case_loss_usdc": 0.50,
            "cap_utilization": 0.0066666667,
        }
    )
    payload["performance"].update(
        {
            "settled_realized_pnl_usdc": 0.16,
            "unrealized_executable_bid_pnl_usdc": -0.04,
            "fees_usdc": 0.01,
            "drawdown_usdc": 0.08,
            "market_following_pnl_usdc": 0.09,
            "no_trade_pnl_usdc": 0.0,
        }
    )
    payload["targets"] = [
        {
            "decision_id": "decision-4",
            "event_id": "nyc-2026-07-22",
            "market_id": "nyc-high-2026-07-22",
            "event_slug": "highest-temperature-in-nyc-on-july-22",
            "target_date": "2026-07-22",
            "range_label": "88–89 °F",
            "side": "BUY_YES",
            "executable_ask": 0.93,
            "max_price": 0.94,
            "spread": 0.01,
            "quantity": 0.5376,
            "max_loss_usdc": 0.50,
            "fair_value_lower_bound": 0.97,
            "after_cost_edge_per_share": 0.025,
            "expected_after_cost_roi": 0.0269,
            "decision": "HOLD",
            "hold_reason": "Waiting for the final two-second book refresh.",
            "evaluated_at_utc": "2026-07-21T19:59:57+00:00",
        }
    ]
    payload["positions"] = [
        {
            "position_id": "position-2",
            "event_id": "toronto-2026-07-21",
            "market_id": "toronto-high-2026-07-21",
            "event_slug": "highest-temperature-in-toronto-on-july-21",
            "target_date": "2026-07-21",
            "range_label": "29–30 °C",
            "side": "YES",
            "quantity": 0.53,
            "average_entry_price": 0.94,
            "entry_notional_usdc": 0.50,
            "fees_usdc": 0.01,
            "worst_case_loss_usdc": 0.50,
            "executable_bid": 0.92,
            "unrealized_executable_bid_pnl_usdc": -0.02,
            "settled": False,
            "settlement_state": "UNSETTLED",
            "updated_at_utc": "2026-07-21T19:59:50+00:00",
        }
    ]
    payload["activity"] = [
        {
            "sequence": 12,
            "event_type": "RECONCILIATION",
            "state": "RECONCILED",
            "code": "ACCOUNT_MATCH",
            "detail": "Ledger and account agree to one cent and one lot.",
            "event_id": "toronto-2026-07-21",
            "occurred_at_utc": "2026-07-21T19:59:55+00:00",
        }
    ]
    payload["provenance"].update(
        {
            "release_manifest_sha256": "release-hash",
            "activation_sha256": "activation-hash",
            "policy_sha256": "policy-hash",
            "economics_snapshot_id": "fees-20260721",
            "economics_sha256": "economics-hash",
            "permission_snapshot_id": "permission-20260721",
            "permission_sha256": "permission-hash",
            "input_snapshot_id": "input-20260721T195900Z",
            "input_snapshot_sha256": "input-hash",
            "code_sha256": "code-hash",
            "status_sha256": "status-hash",
            "ledger_high_water_marks": {"fills": 2, "risk_events": 4},
        }
    )
    payload["blockers"] = []
    payload["warnings"] = []
    return payload


@mock.patch(_PROVIDER)
def test_home_renders_capital_locked_read_only_tracker(mock_load):
    mock_load.return_value = _base_payload()

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    assert mock_load.called
    assert app_test.selectbox[0].value == "Home"
    assert app_test.title[0].value == "Safest bets right now"
    text = _visible_text(app_test)
    assert "$75 CAPITAL CANARY / READ ONLY" in text
    assert 'class="canary-status-stop">LOCKED</strong>' in text
    assert "Production readiness is NOT_READY; capital remains locked." in text
    assert "ENGAGED" in text
    assert "DISABLED" in text
    assert "Classification never grants authority" in text
    assert "No capital-qualified target is visible" in text
    assert "Production Readiness Not Ready" in text
    assert "Audit lineage and provenance" in [item.label for item in app_test.expander]
    assert [metric.label for metric in app_test.metric[:6]] == [
        "Campaign ceiling",
        "Net liquidation",
        "Cash",
        "Reserve",
        "Unresolved max loss",
        "Cap utilization",
    ]
    assert app_test.metric[0].value == "$75.00"
    assert all(metric.value == "Unknown" for metric in app_test.metric[1:6])
    assert len(app_test.button) == 0
    assert len(app_test.number_input) == 0
    assert len(app_test.text_input) == 0
    assert "Place order" not in text
    assert "Private key" not in text
    assert 'role="status" aria-live="polite"' in text


@mock.patch(_PROVIDER)
def test_home_tracks_fresh_probe_targets_positions_activity_and_performance(mock_load):
    mock_load.return_value = _probe_payload()

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert 'class="canary-status-live">PROBE</strong>' in text
    assert "ENABLED FOR WORKER" in text
    assert "This page cannot place, cancel, size, or modify an order" in text
    assert "88–89 °F" in text
    assert "Worker Decision: Hold".upper() in text.upper()
    assert "Waiting for the final two-second book refresh." in text
    assert "93.0%" in text
    assert "$0.50" in text
    assert "29–30 °C" in text
    assert "Executable-bid unrealized P&amp;L" in text
    assert "Ledger and account agree to one cent and one lot." in text
    assert "Release manifest hash" in text
    assert "release-hash" in text
    assert "Ledger high-water marks" in text
    assert [metric.label for metric in app_test.metric[6:12]] == [
        "Settled realized P&L",
        "Executable-bid unrealized P&L",
        "Fees paid",
        "Drawdown",
        "Market-following counterfactual",
        "No-trade counterfactual",
    ]
    assert app_test.metric[6].value == "$0.16"
    assert app_test.metric[7].value == "-$0.04"
    assert app_test.metric[11].value == "$0.00"
    assert len(app_test.button) == 0
    assert len(app_test.number_input) == 0
    assert len(app_test.text_input) == 0


@mock.patch(_PROVIDER)
def test_home_treats_utilization_as_fraction_and_shows_latest_activity(mock_load):
    payload = _probe_payload()
    payload["account"]["cap_utilization"] = 1.2
    payload["activity"] = [
        {
            "sequence": index,
            "event_type": "RISK_EVENT",
            "code": f"EVENT_{index}",
            "detail": f"activity-{index}",
            "occurred_at_utc": "2026-07-21T19:59:55+00:00",
        }
        for index in range(20)
    ]
    mock_load.return_value = payload

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert app_test.metric[5].value == "120.0%"
    assert "activity-19" in text
    assert "activity-0" not in text


@mock.patch(_PROVIDER)
def test_home_hides_stale_targets_but_preserves_last_known_position_risk(mock_load):
    payload = _probe_payload()
    payload.update({"source_status": "STALE", "display_state": "LIVE"})
    payload["freshness"].update(
        {
            "stale": True,
            "status_data_stale": True,
            "position_data_stale": True,
            "portfolio_data_stale": True,
            "not_assumed_flat": True,
        }
    )
    payload["targets"][0]["range_label"] = "SHOULD-NOT-RENDER"
    mock_load.return_value = payload

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert "targets and worker-submission claims are hidden" in text
    assert "Targets are hidden because authority or status data is stale" in text
    assert "HIDDEN (STALE)" in text
    assert "ENABLED FOR WORKER" not in text
    assert "SHOULD-NOT-RENDER" not in text
    assert "29–30 °C" in text
    assert "LAST KNOWN" in text
    assert "Last-known exposure is not assumed flat" in text
    assert "No reconciled open positions" not in text


@mock.patch(_PROVIDER)
def test_home_stale_empty_position_projection_is_not_assumed_flat(mock_load):
    payload = _base_payload()
    payload["source_status"] = "NO_DATA"
    payload["freshness"].update(
        {"stale": True, "position_data_stale": True, "not_assumed_flat": True}
    )
    payload["positions"] = []
    mock_load.return_value = payload

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert "including when no position rows are available" in text
    assert "No reconciled open positions" not in text


@mock.patch(_PROVIDER)
def test_home_adapter_failure_fails_closed_and_preserves_unknown_position_risk(mock_load):
    mock_load.side_effect = ValueError("partial projection")

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert 'class="canary-status-stop">LOCKED</strong>' in text
    assert "adapter failed safely" in text
    assert "Worker submission state is unknown" in text
    assert "Homepage Adapter Error" in text
    assert "not assumed flat" in text
    assert len(app_test.button) == 0
    assert len(app_test.number_input) == 0
    assert len(app_test.text_input) == 0


@mock.patch(_PROVIDER)
def test_home_escapes_untrusted_display_values_and_omits_secret_shaped_provenance(mock_load):
    payload = _probe_payload()
    payload["targets"][0]["range_label"] = '<script id="xss">alert(1)</script>'
    payload["targets"][0]["hold_reason"] = '<img src=x onerror="alert(2)">'
    payload["targets"][0]["market_url"] = "https://example.com/phish"
    payload["provenance"]["api_secret"] = "must-never-render"
    mock_load.return_value = payload

    app_test = AppTest.from_file("app/streamlit_app.py").run()

    assert not app_test.exception
    text = _visible_text(app_test)
    assert '<script id="xss">' not in text
    assert "&lt;script id=&quot;xss&quot;&gt;" in text
    assert '<img src=x onerror="alert(2)">' not in text
    assert "must-never-render" not in text
    assert "https://example.com/phish" not in text


def test_candidate_link_only_allows_canonical_internal_or_polymarket_routes():
    assert _candidate_link({"market_url": "/?market=nyc"}) == "/?market=nyc"
    assert _candidate_link({"market_url": "/?history=1"}) == "/?market=overview"
    assert (
        _candidate_link(
            {"market_url": "https://polymarket.com/event/highest-temperature-in-nyc"}
        )
        == "https://polymarket.com/event/highest-temperature-in-nyc"
    )
    assert (
        _candidate_link({"event_slug": "highest-temperature-in-toronto"})
        == "https://polymarket.com/event/highest-temperature-in-toronto"
    )
    assert (
        _candidate_link({"market_url": "https://example.com/phish", "market_id": "nyc high"})
        == "/?market=nyc+high"
    )
    assert (
        _candidate_link({"market_url": "http://polymarket.com/event/test"})
        == "/?market=overview"
    )
