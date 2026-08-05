import json
import csv
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.mm_day_countability import (
    build_day_countability,
    confirmation_reservation_gate,
)
from weather.market.market_microstructure_capture import payload_sha1
from weather.market.mm_paper_constants import DEFAULT_CONFIG
from weather.market.mm_paper_scoring import simulate_conservative_fills
from weather.market.mm_reward_q_share import build_sampled_reward_q_share


UTC = timezone.utc


def _clear_reservation_gate(target_date="2026-08-04"):
    return {
        "status": "PASS",
        "state": "ARMED_UNDATED",
        "target_date": target_date,
        "blockers": [],
    }


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _constructive_inputs(root):
    event_slug = "highest-temperature-in-testville-on-august-4-2026"
    folder = root / event_slug
    quote_time = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    leg = {
        "leg_id": "leg-1",
        "quote_id": "quote-1",
        "run_id": "run-1",
        "run_folder": "retained/run-1",
        "run_mode": "paper-live-forward",
        "policy_hash": "locked-policy",
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": 80,
        "bin_value_hi": 81,
        "clob_token_id": "yes-1",
        "side": "YES_BID",
        "direction": 1.0,
        "quote_price": 0.50,
        "quote_size": 10.0,
        "quote_time": quote_time,
        "quote_expires_at": quote_time + timedelta(seconds=60),
        "tick_size": 0.01,
        "min_order_size": 1.0,
        "market_mid": 0.51,
        "fair_probability": 0.55,
        "edge": 0.04,
        "regime": "harvest",
        "source_fresh": True,
        "book_imbalance_bucket": "balanced",
        "band_distance_bucket": "near",
        "reward_estimate_usdc": 0.0,
    }
    quote = {
        "target_date": "2026-08-04",
        "event_slug": event_slug,
        "market_id": "testville",
        "generated_at_utc": quote_time.isoformat(),
    }
    _write_jsonl(folder / "order_books.jsonl", [{
        "capture_id": "book-1",
        "captured_at_utc": (quote_time - timedelta(seconds=10)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "clob_token_id": "yes-1",
        "book": {
            "asset_id": "yes-1",
            "tick_size": "0.01",
            "min_order_size": "1",
            "bids": [{"price": "0.49", "size": "20"}, {"price": "0.48", "size": "10"}],
            "asks": [{"price": "0.52", "size": "25"}],
        },
    }])
    execution_payload = {
        "event_type": "last_trade_price",
        "asset_id": "yes-1",
        "market": "condition-1",
        "price": "0.49",
        "size": "2",
        "side": "SELL",
        "transaction_hash": "0xstrictthrough1",
        "trade_time_utc": (quote_time + timedelta(seconds=20)).isoformat(),
    }
    execution_sha1 = payload_sha1(execution_payload)
    _write_jsonl(folder / "market_ws.jsonl", [{
        "received_at_utc": (quote_time + timedelta(seconds=21)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "session_id": "session-1",
        "raw_sha1": execution_sha1,
        "event_rows": 1,
        "payload": execution_payload,
    }])
    _write_csv(folder / "market_ws_events.csv", [{
        "received_at_utc": (quote_time + timedelta(seconds=21)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "event_type": "last_trade_price",
        "asset_id": "yes-1",
        "market": "condition-1",
        "price": "0.49",
        "size": "2",
        "trade_time_utc": (quote_time + timedelta(seconds=20)).isoformat(),
        "side": "SELL",
        "raw_sha1": execution_sha1,
    }])
    _write_jsonl(folder / "market_ws_sessions.jsonl", [{
        "schema_version": "mm_execution_capture_session_v0.1",
        "session_id": "session-1",
        "coverage_start_utc": (quote_time - timedelta(minutes=5)).isoformat(),
        "coverage_end_utc": (quote_time + timedelta(minutes=5)).isoformat(),
        "status": "COMPLETE",
        "continuous_coverage": True,
    }])
    _write_csv(folder / "order_books_summary.csv", [{
        "captured_at_utc": (quote_time - timedelta(seconds=10)).isoformat(),
        "event_slug": event_slug,
        "market_id": "testville",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "yes-1",
        "best_bid": "0.50",
        "best_ask": "0.52",
        "midpoint": "0.51",
        "bid_size_at_best": "5",
        "ask_size_at_best": "5",
        "tick_size": "0.01",
    }])
    _write_csv(folder / "price_history.csv", [
        {
            "point_time_utc": (quote_time + timedelta(seconds=50)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.52",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=1, seconds=20)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.53",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=5, seconds=20)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.54",
        },
        {
            "point_time_utc": (quote_time + timedelta(minutes=30, seconds=30)).isoformat(),
            "clob_token_id": "yes-1",
            "price": "0.55",
        },
    ])
    (folder / "settlement.json").write_text(json.dumps({
        "event_slug": event_slug,
        "market_id": "testville",
        "settlement_bucket": 80,
        "winning_band": "80-81 F",
    }), encoding="utf-8")
    return quote, leg


def test_constructive_day_shaped_proof_is_countable(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    assert diagnostics[leg["event_slug"]]["trade_rows"] == 1
    assert len(fills) == 1
    assert "market_ws" in fills[0]["execution_source_representations"]
    assert fills[0]["conservative_fill_rule"] == "strict_trade_through_price_and_recorded_size"
    assert fills[0]["acceptance_pnl_status"] == "COUNTABLE_SETTLEMENT"
    reward = build_sampled_reward_q_share(
        [leg],
        tmp_path,
        discount_factor=0.3,
        default_tick_size=0.01,
        default_min_order_size=1.0,
    )
    assert reward["status"] == "PASS"
    assert reward["competitor_q"] == pytest.approx(6.9)
    assert reward["own_q"] == pytest.approx(10.0)
    assert reward["sampled_q_share"] == pytest.approx(10.0 / 16.9)
    assert reward["samples"][0]["capture_id"] == "book-1"

    countability = build_day_countability(
        [quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence={"status": "PASS", "blockers": []},
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    assert countability["status"] == "COUNTABLE"
    assert countability["counts_toward_maker_day_target"] is True
    assert all(countability["checklist"].values())


def test_explicit_target_date_isolated_from_multi_day_paper_corpus(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    config = {**DEFAULT_CONFIG, "fill_evidence_require_clob_recon_coverage": False}
    fills, _queues, _diagnostics, _ = simulate_conservative_fills(
        [leg],
        tmp_path,
        {},
        config,
    )
    reward = build_sampled_reward_q_share([leg], tmp_path, discount_factor=0.3)
    other_quote = {
        "target_date": "2026-08-03",
        "event_slug": "highest-temperature-in-elsewhere-on-august-3-2026",
        "market_id": "elsewhere",
        "generated_at_utc": "2026-08-03T14:00:00+00:00",
    }
    multi_day_fill_evidence = {
        "status": "BLOCK",
        "blockers": ["rejected_execution_evidence_rows"],
        "by_target_date": {
            "2026-08-03": {
                "status": "BLOCK",
                "blockers": ["rejected_execution_evidence_rows"],
            },
            "2026-08-04": {"status": "PASS", "blockers": []},
        },
    }

    aggregate = build_day_countability(
        [other_quote, quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence=multi_day_fill_evidence,
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    selected = build_day_countability(
        [other_quote, quote],
        [leg],
        fills,
        snapshots_root=tmp_path,
        fill_evidence=multi_day_fill_evidence,
        reward_q_share=reward,
        target_date="2026-08-04",
        reservation_gate=_clear_reservation_gate(),
    )

    assert aggregate["status"] == "NOT_COUNTABLE"
    assert "expected_exactly_one_target_date" in aggregate["blockers"]
    assert selected["status"] == "COUNTABLE"
    assert selected["target_dates"] == ["2026-08-04"]
    assert selected["reward_q_share"]["status"] == "PASS"
    assert selected["fill_evidence"]["status"] == "PASS"
    assert not any(
        blocker.startswith("fill_evidence:") for blocker in selected["blockers"]
    )


def test_missing_execution_tape_never_counts_even_for_valid_abstention(tmp_path):
    quote = {
        "target_date": "2026-08-04",
        "event_slug": "highest-temperature-in-testville-on-august-4-2026",
        "market_id": "testville",
    }
    result = build_day_countability(
        [quote],
        [],
        [],
        snapshots_root=tmp_path,
        fill_evidence={"status": "BLOCK", "blockers": ["no_quote_legs"]},
        reward_q_share={"status": "NOT_APPLICABLE", "exact_sampled": True},
        reservation_gate=_clear_reservation_gate(),
    )
    assert result["status"] == "NOT_COUNTABLE"
    assert any(blocker.startswith("execution_tape_missing:") for blocker in result["blockers"])
    assert "fill_evidence:no_quote_legs" not in result["blockers"]


def test_missing_settlement_cannot_fall_back_to_30m_for_countability(tmp_path):
    quote, leg = _constructive_inputs(tmp_path)
    reward = build_sampled_reward_q_share([leg], tmp_path, discount_factor=0.3)
    result = build_day_countability(
        [quote],
        [leg],
        [{
            "fill_id": "fill-1",
            "target_date": "2026-08-04",
            "acceptance_pnl_status": "NOT_COUNTABLE_SETTLEMENT_MISSING",
            "conservative_fill_rule": "strict_trade_through_price_and_recorded_size",
            "provisional_net_30m_usdc": 1.25,
        }],
        snapshots_root=tmp_path,
        fill_evidence={"status": "PASS", "blockers": []},
        reward_q_share=reward,
        reservation_gate=_clear_reservation_gate(),
    )
    assert result["status"] == "NOT_COUNTABLE"
    assert "settlement_horizon_missing=1" in result["blockers"]


def test_confirmation_reservation_gate_stops_declared_dates(tmp_path):
    undated = tmp_path / "undated.md"
    undated.write_text(
        "| **Reserved dates** | **NONE ARE CURRENTLY RESERVED.** |\n",
        encoding="utf-8",
    )
    declared = tmp_path / "declared.md"
    declared.write_text(
        "| **Reserved dates** | **2026-08-06 through 2026-11-03** |\n",
        encoding="utf-8",
    )

    assert confirmation_reservation_gate("2026-08-07", path=undated)["status"] == "PASS"
    blocked = confirmation_reservation_gate("2026-08-07", path=declared)
    outside = confirmation_reservation_gate("2026-08-05", path=declared)
    missing_target = confirmation_reservation_gate(path=declared)

    assert blocked["status"] == "BLOCK"
    assert blocked["blockers"] == ["target_date_reserved_for_confirmation"]
    assert outside["status"] == "PASS"
    assert missing_target["status"] == "BLOCK"
    assert missing_target["blockers"] == [
        "explicit_target_required_while_confirmation_reserved"
    ]
