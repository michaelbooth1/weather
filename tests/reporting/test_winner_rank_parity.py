from weather.reporting.scorecards.winner_rank_parity import build_payload, render_report


def _snapshot_rows(
    *,
    source="served_snapshots",
    variant_id="served_current",
    market_id="miami",
    target_date="2026-06-22",
    snapshot_id="s1",
    winner_model=0.2,
    winner_market=0.7,
    loser_model=0.6,
    loser_market=0.2,
    hour=7,
    cutoff_regime="early",
    uses_market_features=False,
):
    common = {
        "source": source,
        "variant_id": variant_id,
        "lane": "weather_only_core_model",
        "variant_family": "candidate",
        "uses_market_features": uses_market_features,
        "counts_toward_weather_model_promotion": True,
        "market_id": market_id,
        "target_date": target_date,
        "snapshot_id": snapshot_id,
        "local_hour": hour,
        "cutoff_regime": cutoff_regime,
        "source_health_state": "all_fresh",
        "forecast_disagreement_bucket": "high_disagreement",
        "forecast_source_count_bucket": "two_sources",
        "forecast_bucket_pressure": "warm_side",
        "band_type": "eq",
        "current_max_trust_state": "current_max_guarded",
        "runtime_identity": "test-runtime",
    }
    return [
        {
            **common,
            "band_key": f"{snapshot_id}:winner",
            "range_label": "90-91 F",
            "model_probability": winner_model,
            "market_yes": winner_market,
            "outcome": 1,
            "settlement_distance_bucket": "0",
        },
        {
            **common,
            "band_key": f"{snapshot_id}:loser",
            "range_label": "92-93 F",
            "model_probability": loser_model,
            "market_yes": loser_market,
            "outcome": 0,
            "settlement_distance_bucket": "1",
        },
    ]


def test_winner_rank_parity_reports_case_counts_routes_and_guardrails():
    served_rows = []
    served_rows += _snapshot_rows(snapshot_id="served-1")
    served_rows += _snapshot_rows(snapshot_id="served-2", winner_model=0.7, winner_market=0.2, loser_model=0.2, loser_market=0.6)
    served_rows += _snapshot_rows(snapshot_id="served-3")

    candidate_rows = []
    for index in range(3):
        candidate_rows += _snapshot_rows(
            source="active_variant_shadow",
            variant_id="no_market_candidate",
            snapshot_id=f"candidate-early-{index}",
            hour=7,
            cutoff_regime="early",
        )
        candidate_rows += _snapshot_rows(
            source="active_variant_shadow",
            variant_id="no_market_candidate",
            snapshot_id=f"candidate-ramp-{index}",
            hour=12,
            cutoff_regime="ramp",
        )
        candidate_rows += _snapshot_rows(
            source="active_variant_shadow",
            variant_id="no_market_candidate",
            snapshot_id=f"candidate-late-{index}",
            hour=17,
            cutoff_regime="late",
        )

    payload = build_payload(
        source_rows=served_rows,
        candidate_rows=candidate_rows,
        dates=[],
        min_snapshots=1,
        generated_at_utc="2026-06-23T00:00:00+00:00",
    )
    report = render_report(payload)
    primary = payload["primary_weather_only"]
    guardrails = {
        row["guardrail"]: row
        for row in payload["candidate_guardrails"]
        if row["variant_id"] == "no_market_candidate"
    }
    owner_items = {
        item
        for row in payload["top_owner_routes"]
        for item in row["owner_items"]
    }

    assert payload["schema_version"] == "winner_rank_parity_v0.1"
    assert payload["status"] == "BLOCK"
    assert primary["model_top_miss_market_top_hit_count"] == 2
    assert primary["model_top_hit_market_top_miss_count"] == 1
    assert primary["market_top_model_miss_excess"] == 1
    assert primary["top_hit_gap_market_minus_model"] > 0
    assert payload["parity_gate"]["status"] == "BLOCK"
    assert {"broad", "early", "exact_band", "bottom_location", "ramp", "late"} <= set(guardrails)
    assert guardrails["broad"]["status"] == "BLOCK"
    assert {219, 230, 233} <= owner_items
    assert payload["diagnostic_policy"]["scalar_calibration"].startswith("diagnostic_only")
    assert "Winner-Rank Parity Gate" in report
