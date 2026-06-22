from weather.reporting.taker_tail_casebook import build_tail_casebook, render_report


def test_tail_casebook_flags_settled_losing_low_price_tail_slice():
    row = {
        "run_id": "fixture-run",
        "target_date": "2026-06-21",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-21-2026",
        "captured_at_utc": "2026-06-21T20:00:00+00:00",
        "order_status": "FILLED",
        "range_label": "84-85 F",
        "bin_kind": "eq",
        "bin_value": "84",
        "bin_value_hi": "85",
        "clob_token_id": "token-atlanta-84",
        "fair_probability": "0.40",
        "best_ask": "0.01",
        "edge": "0.39",
        "fill_size": "10",
        "fill_notional_usdc": "0.1",
        "total_spent_usdc": "0.1",
        "low_price_tail": "True",
        "market_centered_warm_tail": "False",
        "current_high_band_distance": "4",
        "market_modal_band_distance": "4",
        "source_freshness_state": "all_fresh",
    }
    labels = {
        "by_event_slug": {
            row["event_slug"]: {
                "event_slug": row["event_slug"],
                "market_id": "atlanta",
                "target_date": "2026-06-21",
                "settlement_bucket": 80,
                "winning_band": "80-81 F",
                "quality_grade": "complete",
            }
        },
        "by_market_date": {},
    }

    payload = build_tail_casebook([row], labels=labels, source_runs=["fixture"])
    report = render_report(payload)

    assert payload["summary"]["status"] == "BLOCK_BAD_TAIL_SLICES"
    assert payload["summary"]["tail_fill_count"] == 1
    assert payload["summary"]["losing_tail_fill_count"] == 1
    assert payload["by_tail_type"][0]["tail_type"] == "low_price_tail"
    assert payload["by_tail_type"][0]["loss_count"] == 1
    assert payload["no_go_candidates"][0]["candidate_action"] == "block_until_repeated_settlement_positive_oos"
    assert "low_price_tail" in payload["no_go_candidates"][0]["slice_key"]
    assert "Taker Tail Casebook" in report
    assert "block_until_repeated_settlement_positive_oos" in report


def test_tail_casebook_infers_legacy_warm_tail_from_modal_context():
    base = {
        "run_id": "legacy-run",
        "target_date": "2026-06-20",
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-20-2026",
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-20T18:00:00+00:00",
        "bin_kind": "eq",
        "source_freshness_state": "all_fresh",
    }
    modal = {
        **base,
        "order_status": "SKIPPED",
        "range_label": "78-79 F",
        "bin_value": "78",
        "bin_value_hi": "79",
        "market_mid": "0.60",
        "best_ask": "0.61",
        "fair_probability": "0.55",
    }
    filled_warm_tail = {
        **base,
        "order_status": "FILLED",
        "range_label": "88-89 F",
        "bin_value": "88",
        "bin_value_hi": "89",
        "market_mid": "0.12",
        "best_ask": "0.13",
        "fair_probability": "0.25",
        "fill_size": "10",
        "fill_notional_usdc": "1.3",
        "total_spent_usdc": "1.3",
    }
    labels = {
        "by_event_slug": {
            base["event_slug"]: {
                "event_slug": base["event_slug"],
                "market_id": "atlanta",
                "target_date": "2026-06-20",
                "settlement_bucket": 78,
                "winning_band": "78-79 F",
                "quality_grade": "complete",
            }
        },
        "by_market_date": {},
    }

    payload = build_tail_casebook([modal, filled_warm_tail], labels=labels)

    assert payload["summary"]["warm_tail_fill_count"] == 1
    assert payload["cases"][0]["tail_type"] == "market_centered_warm_tail"
    assert payload["cases"][0]["market_modal_band_key"] == "eq:78-79"
    assert payload["cases"][0]["market_modal_band_distance"] == 9.0
    assert payload["cases"][0]["settlement_result"] == "loss"
