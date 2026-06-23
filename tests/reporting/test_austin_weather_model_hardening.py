import json
from pathlib import Path

from weather.reporting.austin_weather_model_hardening import build_payload, render_report


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def requalification_payload(*, status="PASS", serving="SHADOW", verdict="BLOCK"):
    return {
        "schema_version": "austin_hgb_requalification_v0.1",
        "status": status,
        "serving_disposition": serving,
        "requalification_verdict": verdict,
    }


def test_hardening_report_proves_all_four_item_gates(tmp_path):
    requalification = write_json(
        tmp_path / "austin_hgb_requalification.json",
        requalification_payload(),
    )

    payload = build_payload(
        austin_requalification=requalification,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )
    report = render_report(payload)

    assert payload["status"] == "PASS"
    assert payload["summary"]["items_passed"] == [252, 249, 248, 251]
    assert not payload["blockers"]
    item252 = payload["items"]["252"]
    item249 = payload["items"]["249"]
    item248 = payload["items"]["248"]
    item251 = payload["items"]["251"]
    assert item252["summary"]["physical_validity_status"] == "fresh_but_impossible"
    assert item252["summary"]["valid_guidance_preserved"] is True
    first_gate = item252["gates"][0]
    assert first_gate["evidence"]["impossible_sources"] == ["nbm_probabilistic_tmax"]
    assert "nbm_prob_tmax_p90" in first_gate["evidence"]["impossible_features"]
    assert item249["summary"]["official_current_minus_high"] < 0
    assert item249["summary"]["tail_after"] < item249["summary"]["tail_before"]
    assert item248["summary"]["robust_cluster_signal"] < item248["summary"]["raw_max_signal"]
    assert item248["summary"]["robust_tail_96_97"] < item248["summary"]["raw_tail_96_97"]
    assert item251["summary"]["tail_after"] < item251["summary"]["tail_before"]
    assert item251["summary"]["moved_probability"] > 0.0
    assert item251["summary"]["revision_up_brier_delta"] <= 0.0
    partial_gate = [
        gate for gate in item251["gates"]
        if gate["gate"] == "austin_partial_dampener_activates_after_official_rollover"
    ][0]
    assert partial_gate["evidence"]["hard_lockin_context"]["reason"] == "forecast_ceiling_above_high"
    assert partial_gate["evidence"]["partial_context"]["stage"] == "partial_dampening"
    metric_gate = [
        gate for gate in item248["gates"]
        if gate["gate"] == "variant_metric_comparison"
    ][0]
    comparison = metric_gate["evidence"]["variant_comparison"]
    assert set(comparison) == {"raw_max", "median", "trimmed_high", "capped_warm_source"}
    assert comparison["median"]["exact_band_brier"] <= comparison["raw_max"]["exact_band_brier"]
    assert comparison["median"]["exact_band_logloss"] <= comparison["raw_max"]["exact_band_logloss"]
    assert comparison["median"]["market_relative_error"] <= comparison["raw_max"]["market_relative_error"]
    continuation_gate = [
        gate for gate in item248["gates"]
        if gate["gate"] == "warm_continuation_not_capped_when_sources_agree"
    ][0]
    assert len(continuation_gate["evidence"]["cases"]) >= 5
    assert all(case["preserved"] for case in continuation_gate["evidence"]["cases"])
    assert all(
        case["exact_band_brier_delta"] <= 0.0
        and case["exact_band_logloss_delta"] <= 0.0
        and case["market_relative_error_delta"] <= 0.0
        for case in continuation_gate["evidence"]["cases"]
    )
    assert "Austin Weather Model Hardening" in report
    assert "austin_raw_max_vs_robust_cluster_replay" in report


def test_hardening_report_blocks_when_promotion_gate_missing(tmp_path):
    missing = tmp_path / "missing_austin_hgb_requalification.json"

    payload = build_payload(
        austin_requalification=missing,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )

    assert payload["status"] == "BLOCK"
    assert payload["items"]["248"]["status"] == "BLOCK"
    assert any(
        blocker["gate"] == "candidate_promotion_fail_closed"
        for blocker in payload["blockers"]
    )


def test_hardening_report_allows_live_candidate_only_with_passed_requalification(tmp_path):
    requalification = write_json(
        tmp_path / "austin_hgb_requalification.json",
        requalification_payload(serving="LIVE_CANDIDATE", verdict="PASS"),
    )

    payload = build_payload(
        austin_requalification=requalification,
        generated_at_utc="2026-06-22T00:00:00+00:00",
    )

    assert payload["status"] == "PASS"
    assert payload["items"]["248"]["summary"]["serving_disposition"] == "LIVE_CANDIDATE"
    promotion_gate = [
        gate for gate in payload["items"]["248"]["gates"]
        if gate["gate"] == "candidate_promotion_fail_closed"
    ][0]
    assert promotion_gate["evidence"]["requalification_verdict"] == "PASS"
