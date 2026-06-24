from weather.reporting.june23_location_bias_repair import build_payload, render_report


def _snapshot_rows(
    *,
    market_id,
    snapshot_id,
    winner_band,
    wrong_band,
    winner_model,
    winner_market,
    wrong_model,
    wrong_market,
    hour=10,
):
    common = {
        "source": "served_snapshots",
        "variant_id": "served_current",
        "lane": "weather_only_core_model",
        "variant_family": "served_current",
        "uses_market_features": False,
        "counts_toward_weather_model_promotion": True,
        "market_id": market_id,
        "target_date": "2026-06-23",
        "snapshot_id": snapshot_id,
        "local_hour": hour,
        "cutoff_regime": "ramp",
        "source_health_state": "served",
        "forecast_disagreement_bucket": "low_disagreement",
        "forecast_source_count_bucket": "two_sources",
        "forecast_bucket_pressure": "unknown",
        "band_type": "eq",
        "current_max_trust_state": "unknown",
        "runtime_identity": "test-runtime",
    }
    return [
        {
            **common,
            "band_key": f"{snapshot_id}:winner",
            "range_label": winner_band,
            "model_probability": winner_model,
            "market_yes": winner_market,
            "outcome": 1,
            "settlement_distance_bucket": "0",
        },
        {
            **common,
            "band_key": f"{snapshot_id}:wrong",
            "range_label": wrong_band,
            "model_probability": wrong_model,
            "market_yes": wrong_market,
            "outcome": 0,
            "settlement_distance_bucket": "1",
        },
    ]


def test_june23_packet_classifies_bias_and_preserves_protected_markets():
    rows = []
    rows += _snapshot_rows(
        market_id="seattle",
        snapshot_id="sea-cold",
        winner_band="74-75 F",
        wrong_band="70-71 F",
        winner_model=0.25,
        winner_market=0.70,
        wrong_model=0.62,
        wrong_market=0.15,
        hour=9,
    )
    rows += _snapshot_rows(
        market_id="san-francisco",
        snapshot_id="sf-cold",
        winner_band="68-69 F",
        wrong_band="64-65 F",
        winner_model=0.30,
        winner_market=0.65,
        wrong_model=0.55,
        wrong_market=0.20,
        hour=11,
    )
    rows += _snapshot_rows(
        market_id="austin",
        snapshot_id="aus-warm",
        winner_band="90-91 F",
        wrong_band="94-95 F",
        winner_model=0.28,
        winner_market=0.68,
        wrong_model=0.64,
        wrong_market=0.12,
        hour=13,
    )
    rows += _snapshot_rows(
        market_id="chicago",
        snapshot_id="chi-protected",
        winner_band="82-83 F",
        wrong_band="80-81 F",
        winner_model=0.72,
        winner_market=0.58,
        wrong_model=0.12,
        wrong_market=0.30,
        hour=12,
    )

    payload = build_payload(
        source_rows=rows,
        generated_at_utc="2026-06-24T12:00:00+00:00",
        artifact_path="data/backtest/june23_location_bias_repair_packet.json",
    )
    by_market = {
        row["market_id"]: row
        for row in payload["case_packet"]["locations"]
    }
    manifests = {
        row["market_id"]: row
        for row in payload["repair_manifests"]
    }
    replay_rows = {
        row["market_id"]: row
        for row in payload["repair_replay"]["market_rows"]
    }
    report = render_report(payload)

    assert payload["schema_version"] == "june23_location_bias_repair_v0.1"
    assert payload["status"] == "ACTIONABLE"
    assert by_market["seattle"]["directional_error"] == "cold_miss"
    assert by_market["san-francisco"]["directional_error"] == "cold_miss"
    assert by_market["austin"]["directional_error"] == "warm_miss"
    assert by_market["chicago"]["status"] == "PROTECTED_PASS"
    assert manifests["seattle"]["status"] == "eligible"
    assert manifests["austin"]["repair_family"] == "warm_side_adjacent_confidence_dampener"
    assert payload["repair_replay"]["status"] == "PASS"
    assert replay_rows["seattle"]["improvement_vs_current"] > 0
    assert replay_rows["chicago"]["delta_vs_current"] == 0
    assert payload["repair_replay"]["protected_regression_count"] == 0
    assert "June 23 Location-Bias Repair Packet" in report
