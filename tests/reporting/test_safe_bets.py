from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from weather.reporting.market.safe_bets import (
    PERMISSION_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    build_safe_bets_payload,
    load_safe_bets_payload,
)


NOW = datetime(2026, 7, 21, 16, 0, tzinfo=timezone.utc)
TARGET_DATE = "2026-07-21"


def _permission(*, generated_at=None):
    return {
        "schema_version": PERMISSION_SCHEMA_VERSION,
        "generated_at_utc": (generated_at or (NOW - timedelta(hours=3))).isoformat(),
        "summary": {
            "record_count": 14,
            "edge_allowed_count": 4,
            "observe_count": 6,
            "deny_count": 4,
            "min_independent_days": 3,
        },
    }


def _row(**updates):
    row = {
        "generated_at_utc": (NOW - timedelta(seconds=30)).isoformat(),
        "captured_at_utc": (NOW - timedelta(seconds=40)).isoformat(),
        "target_date": TARGET_DATE,
        "market_id": "nyc",
        "event_slug": "highest-temperature-in-nyc-on-july-21-2026",
        "range_label": "95°F or higher",
        "display_unit": "F",
        "side": "YES_BUY",
        "clob_token_id": "yes-token-95",
        "snapshot_id": "20260721T155920Z",
        "strategy_id": "low_price_tail_capped",
        "strategy_family": "calibrated_taker",
        "strategy_status": "control",
        "market_status": "active",
        "action": "BUY",
        "order_status": "FILLED",
        "reason_code": "BUY_EDGE",
        "source_fresh": True,
        "source_freshness_state": "all_fresh",
        "snapshot_cadence_state_present": True,
        "snapshot_cadence_quality_state": "clean",
        "snapshot_cadence_permission": "allow",
        "taker_edge_permission": "edge_allowed",
        "taker_edge_permission_sample_size": 18,
        "taker_edge_permission_independent_days": 5,
        "taker_edge_permission_market_count": 2,
        "taker_edge_permission_after_fee_skill": 0.08,
        "taker_edge_permission_hit_rate": 0.97,
        "market_benchmark_precondition": "allow",
        "adverse_selection_status": "clear",
        "book_age_seconds": 12,
        "model_age_seconds": 35,
        "best_ask": 0.94,
        "market_implied_probability": 0.94,
        "calibrated_fair_probability": 0.97,
        "after_cost_ev_per_share": 0.025,
        "fill_price": 0.94,
        "executable_fill_price": 0.94,
        "fill_size": 5,
        "fill_notional_usdc": 4.70,
        "fee_usdc": 0.01,
        "total_spent_usdc": 4.71,
    }
    row.update(updates)
    return row


def _run(*rows, generated_at=None, **updates):
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "generated_at_utc": (generated_at or (NOW - timedelta(seconds=45))).isoformat(),
        "run_id": "paper-current",
        "target_date": TARGET_DATE,
        "mode": "paper-taker-multi-arm",
        "experiment_id": "default_taker_strategy_experiment",
        "summary": {
            "budget_usdc": 100,
            "budget_spent_usdc": 4.71,
            "budget_remaining_usdc": 95.29,
        },
        "config": {
            "policy_version": "taker_bot_policy_v0.1",
            "require_active_market": True,
            "max_book_age_seconds": 120,
            "max_model_age_seconds": 900,
        },
        "pnl": {
            "summary": {
                "filled_order_count": len(rows),
                "net_pnl_usdc": 1.25,
                "mark_to_market_pnl_usdc": 0.35,
                "settled_order_count": 2,
                "unsettled_order_count": 1,
            }
        },
        "latest_orders": list(rows),
        "tape_integrity": {"status": "PASS", "actual_rows": len(rows), "expected_rows": len(rows)},
        "upstream_dependency_status": {"status": "PASS", "market_count": 1},
        "exchange_economics_gate": {"status": "PASS", "ok": True, "snapshot_id": "fees-2026-07"},
        "release_identity_status": "research_unbound",
        "base_model_release_bound": False,
    }
    payload.update(updates)
    return payload


def _build(run=None, permission=None, **kwargs):
    return build_safe_bets_payload(
        run or _run(_row()),
        permission or _permission(),
        now=NOW,
        target_date=TARGET_DATE,
        **kwargs,
    )


def _write_pretty(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_retains_a_permissioned_94_cent_favorite_and_preserves_native_label():
    payload = _build()

    assert payload["status"] == "READY"
    assert payload["paper_only"] is True
    assert payload["actionable"] is False
    assert payload["warnings"] == [
        "Research-unbound evidence is diagnostic paper output only."
    ]
    assert payload["fund"]["remaining_usdc"] == pytest.approx(95.29)
    [bet] = payload["recommendations"]
    assert bet["market_label"] == "NYC"
    assert bet["display_unit"] == "F"
    assert bet["range_label"] == "95°F or higher"
    assert bet["executable_price"] == pytest.approx(0.94)
    assert bet["conservative_probability"] == pytest.approx(0.94)
    assert bet["paper_stake_usdc"] == pytest.approx(4.71)
    assert bet["max_loss_usdc"] == pytest.approx(4.71)
    assert bet["profit_if_right_usdc"] == pytest.approx(0.29)
    assert bet["expected_profit_usdc"] == pytest.approx(0.125)
    assert bet["book_age_seconds"] == pytest.approx(42)
    assert bet["model_age_seconds"] == pytest.approx(65)
    assert bet["independent_days"] == 5
    assert bet["sample_size"] == 18


@pytest.mark.parametrize(
    ("updates", "blocker"),
    [
        ({"taker_edge_permission": "deny"}, "edge_not_permissioned"),
        ({"after_cost_ev_per_share": 0.0}, "after_cost_ev_not_positive"),
        ({"source_freshness_state": "failed:wu_history"}, "source_not_all_fresh"),
        ({"snapshot_cadence_permission": "deny"}, "snapshot_cadence_not_allowed"),
        ({"taker_edge_permission_independent_days": 2}, "insufficient_independent_days"),
        ({"market_benchmark_precondition": "no_trade"}, "market_benchmark_no_trade"),
        ({"adverse_selection_status": "warn"}, "adverse_selection_not_clear"),
        ({"book_age_seconds": 121}, "book_not_fresh"),
        ({"model_age_seconds": 901}, "model_not_fresh"),
        ({"market_status": "closed"}, "market_inactive"),
        (
            {
                "executable_fill_price": 0.65,
                "fill_price": 0.65,
                "market_implied_probability": 0.65,
            },
            "below_safety_probability_floor",
        ),
    ],
)
def test_candidate_safety_gates_fail_closed(updates, blocker):
    payload = _build(_run(_row(**updates)))

    assert payload["status"] == "NO_BETS"
    assert payload["recommendations"] == []
    assert payload["blocker_counts"][blocker] == 1


def test_canonical_fill_without_market_status_uses_persisted_active_market_policy():
    canonical_row = _row()
    canonical_row.pop("market_status")

    ready = _build(_run(canonical_row))
    assert ready["status"] == "READY"

    unproven_run = _run(canonical_row)
    unproven_run["config"]["require_active_market"] = False
    blocked = _build(unproven_run)
    assert blocked["status"] == "NO_BETS"
    assert blocked["blocker_counts"]["market_activity_not_proven"] == 1


def test_candidate_freshness_advances_after_the_persisted_evaluation():
    evaluated_at = NOW - timedelta(minutes=4)
    row = _row(
        generated_at_utc=evaluated_at.isoformat(),
        book_age_seconds=100,
        model_age_seconds=100,
    )

    payload = _build(_run(row, generated_at=evaluated_at))

    assert payload["status"] == "NO_BETS"
    assert payload["blocker_counts"]["book_not_fresh"] == 1


def test_no_side_requires_a_real_fresh_no_book():
    unsafe = _row(
        side="NO_BUY",
        event_slug="highest-temperature-in-atlanta-on-july-21-2026",
        market_id="atlanta",
        range_label="90°F or lower",
        no_book_source="synthetic_from_yes_bid",
        no_book_age_seconds=8,
        real_no_book_depth_eligible=False,
        no_book_fresh=True,
    )
    blocked = _build(_run(unsafe))
    assert blocked["status"] == "NO_BETS"
    assert blocked["blocker_counts"]["no_side_real_book_not_safe"] == 1

    safe = deepcopy(unsafe)
    safe.update({
        "no_book_source": "no_token_book",
        "real_no_book_depth_eligible": True,
        "no_book_fresh": True,
        # Canonical NO projections may retain the YES permission-map implied
        # probability; executable NO fill price remains the display bound.
        "market_implied_probability": 0.08,
    })
    ready = _build(_run(safe))
    assert ready["status"] == "READY"
    assert ready["recommendations"][0]["side_label"] == "BUY NO"
    assert ready["recommendations"][0]["conservative_probability"] == pytest.approx(0.94)
    assert ready["recommendations"][0]["book_age_seconds"] == pytest.approx(38)

    stale_no_book = deepcopy(safe)
    stale_no_book.update({
        "generated_at_utc": (NOW - timedelta(seconds=110)).isoformat(),
        "book_age_seconds": 0,
        "model_age_seconds": 0,
        "no_book_age_seconds": 20,
    })
    stale = _build(_run(stale_no_book, generated_at=NOW - timedelta(seconds=110)))
    assert stale["status"] == "NO_BETS"
    assert stale["blocker_counts"]["no_side_real_book_not_safe"] == 1


def test_ranks_safety_then_ev_and_keeps_one_bet_per_event():
    lower_safety_same_event = _row(
        range_label="94°F",
        executable_fill_price=0.91,
        fill_price=0.91,
        market_implied_probability=0.91,
        calibrated_fair_probability=0.99,
        after_cost_ev_per_share=0.07,
    )
    safest_same_event = _row(range_label="95°F or higher")
    second_event = _row(
        market_id="atlanta",
        event_slug="highest-temperature-in-atlanta-on-july-21-2026",
        range_label="98°F",
        executable_fill_price=0.93,
        fill_price=0.93,
        market_implied_probability=0.93,
        calibrated_fair_probability=0.98,
        after_cost_ev_per_share=0.04,
    )

    payload = _build(_run(lower_safety_same_event, second_event, safest_same_event))

    assert [row["range_label"] for row in payload["recommendations"]] == [
        "95°F or higher",
        "98°F",
    ]
    assert payload["blocker_counts"]["duplicate_event"] == 1


def test_equal_safety_ev_and_evidence_use_zero_age_as_the_freshest_tie_break():
    older = _row(
        market_id="atlanta",
        event_slug="highest-temperature-in-atlanta-on-july-21-2026",
        range_label="98°F",
        book_age_seconds=1,
        model_age_seconds=1,
    )
    newest = _row(
        event_slug="highest-temperature-in-nyc-on-july-21-2026",
        range_label="95°F or higher",
        book_age_seconds=0,
        model_age_seconds=0,
    )

    payload = _build(_run(older, newest))

    assert [row["market_id"] for row in payload["recommendations"]] == ["nyc", "atlanta"]


def test_conservative_probability_is_always_bounded_by_executable_price():
    payload = _build(
        _run(
            _row(
                executable_fill_price=0.91,
                fill_price=0.91,
                market_implied_probability=0.96,
                calibrated_fair_probability=0.98,
            )
        )
    )

    assert payload["recommendations"][0]["conservative_probability"] == pytest.approx(0.91)


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("tape_integrity", {"status": "BLOCK"}, "order_tape_integrity_not_pass"),
        ("upstream_dependency_status", {"status": "WARN"}, "upstream_dependencies_not_pass"),
        ("exchange_economics_gate", {"status": "BLOCK", "ok": False}, "exchange_economics_not_pass"),
    ],
)
def test_run_level_gates_block_the_whole_shortlist(field, value, blocker):
    payload = _build(_run(_row(), **{field: value}))

    assert payload["status"] == "BLOCKED"
    assert blocker in payload["run_blockers"]
    assert payload["recommendations"] == []


def test_stale_run_or_permission_map_never_falls_through_to_candidates():
    stale_run = _build(
        _run(_row(), generated_at=NOW - timedelta(minutes=6)),
    )
    assert stale_run["status"] == "STALE"
    assert "paper_run_stale" in stale_run["run_blockers"]

    stale_map = _build(
        permission=_permission(generated_at=NOW - timedelta(hours=37)),
    )
    assert stale_map["status"] == "STALE"
    assert "permission_map_stale" in stale_map["run_blockers"]


def test_future_timestamps_fail_closed_beyond_small_clock_skew():
    tolerated = _build(
        _run(
            _row(generated_at_utc=(NOW + timedelta(seconds=30)).isoformat()),
            generated_at=NOW + timedelta(seconds=30),
        ),
        permission=_permission(generated_at=NOW + timedelta(seconds=30)),
    )
    assert tolerated["status"] == "READY"

    future_run = _build(
        _run(_row(), generated_at=NOW + timedelta(minutes=2)),
    )
    assert future_run["status"] == "BLOCKED"
    assert "run_timestamp_future" in future_run["run_blockers"]

    future_map = _build(
        permission=_permission(generated_at=NOW + timedelta(minutes=2)),
    )
    assert future_map["status"] == "BLOCKED"
    assert "permission_map_timestamp_future" in future_map["run_blockers"]

    future_candidate = _build(
        _run(_row(generated_at_utc=(NOW + timedelta(minutes=2)).isoformat())),
    )
    assert future_candidate["status"] == "NO_BETS"
    assert future_candidate["blocker_counts"]["candidate_timestamp_future"] == 1


def test_no_filled_buy_is_an_explicit_no_bets_state_with_policy_reason():
    payload = _build(
        _run(_row(action="SKIP", order_status="SKIPPED", reason_code="NO_TRADE_STALE_BOOK"))
    )

    assert payload["status"] == "NO_BETS"
    assert payload["status_message"] == "No bets clear every safety gate right now."
    assert payload["blocker_counts"]["policy:NO_TRADE_STALE_BOOK"] == 1


def test_loader_reads_only_current_target_pretty_artifacts(tmp_path):
    run_path = tmp_path / "taker_runs" / TARGET_DATE / "taker-current" / "run_summary.json"
    permission_path = tmp_path / "backtest" / "taker_edge_permission_map.json"
    _write_pretty(run_path, _run(_row()))
    _write_pretty(permission_path, _permission())

    payload = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=permission_path,
    )

    assert payload["status"] == "READY"
    assert payload["provenance"]["run_path"] == str(run_path)
    assert payload["provenance"]["permission_map_path"] == str(permission_path)


def test_loader_does_not_fall_back_when_newest_run_is_partial(tmp_path):
    root = tmp_path / "taker_runs" / TARGET_DATE
    older = root / "taker-older" / "run_summary.json"
    newest = root / "taker-newest" / "run_summary.json"
    permission_path = tmp_path / "backtest" / "taker_edge_permission_map.json"
    _write_pretty(older, _run(_row(), run_id="older"))
    newest.parent.mkdir(parents=True)
    newest.write_text('{\n  "schema_version": "', encoding="utf-8")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(older.parent, ns=(9_000_000_000, 9_000_000_000))
    os.utime(newest, ns=(2_000_000_000, 2_000_000_000))
    os.utime(newest.parent, ns=(3_000_000_000, 3_000_000_000))
    _write_pretty(permission_path, _permission())

    payload = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=permission_path,
    )

    assert payload["status"] == "LOADING"
    assert payload["run_blockers"] == ["run_artifact_incomplete"]
    assert payload["provenance"]["run_path"] == str(newest)


def test_loader_treats_newest_run_directory_without_summary_as_loading(tmp_path):
    root = tmp_path / "taker_runs" / TARGET_DATE
    older = root / "taker-older" / "run_summary.json"
    incomplete = root / "taker-syncing"
    permission_path = tmp_path / "backtest" / "taker_edge_permission_map.json"
    _write_pretty(older, _run(_row(), run_id="older"))
    incomplete.mkdir(parents=True)
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(older.parent, ns=(1_000_000_000, 1_000_000_000))
    os.utime(incomplete, ns=(2_000_000_000, 2_000_000_000))
    _write_pretty(permission_path, _permission())

    payload = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=permission_path,
    )

    assert payload["status"] == "LOADING"
    assert payload["provenance"]["run_path"] == str(incomplete / "run_summary.json")


def test_fund_remaining_is_derived_when_run_summary_omits_it():
    run = _run(_row())
    run["summary"].pop("budget_remaining_usdc")

    payload = _build(run)

    assert payload["fund"]["remaining_usdc"] == pytest.approx(95.29)


def test_loader_ignores_newer_quarantine_housekeeping_directory(tmp_path):
    root = tmp_path / "taker_runs" / TARGET_DATE
    current = root / "taker-current" / "run_summary.json"
    quarantine = root / "_quarantine"
    permission_path = tmp_path / "backtest" / "taker_edge_permission_map.json"
    _write_pretty(current, _run(_row()))
    quarantine.mkdir(parents=True)
    os.utime(current, ns=(1_000_000_000, 1_000_000_000))
    os.utime(current.parent, ns=(1_000_000_000, 1_000_000_000))
    os.utime(quarantine, ns=(2_000_000_000, 2_000_000_000))
    _write_pretty(permission_path, _permission())

    payload = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=permission_path,
    )

    assert payload["status"] == "READY"
    assert payload["provenance"]["run_path"] == str(current)


def test_loader_distinguishes_no_data_missing_map_and_partial_map(tmp_path):
    no_data = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "missing-runs",
        permission_map_path=tmp_path / "missing-map.json",
    )
    assert no_data["status"] == "NO_DATA"

    run_path = tmp_path / "taker_runs" / TARGET_DATE / "taker-current" / "run_summary.json"
    _write_pretty(run_path, _run(_row()))
    missing_map = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=tmp_path / "missing-map.json",
    )
    assert missing_map["status"] == "BLOCKED"
    assert missing_map["run_blockers"] == ["permission_map_missing"]

    partial_path = tmp_path / "partial-map.json"
    partial_path.write_text("{", encoding="utf-8")
    partial_map = load_safe_bets_payload(
        now=NOW,
        target_date=TARGET_DATE,
        runs_root=tmp_path / "taker_runs",
        permission_map_path=partial_path,
    )
    assert partial_map["status"] == "LOADING"
    assert partial_map["run_blockers"] == ["permission_map_incomplete"]
