"""Austin hard-slice evidence for roadmap items 248, 249, and 252."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("austin_weather_model_hardening")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "austin_weather_model_hardening.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "austin_weather_model_hardening_report.md"
DEFAULT_AUSTIN_REQUALIFICATION = DEFAULT_BACKTEST_ROOT / "austin_hgb_requalification.json"

AUDIT_TARGET_DATE = "2026-06-22"
AUDIT_MARKET_ID = "austin"
ROBUST_CLUSTER_VARIANT_ID = "item248_robust_forecast_cluster_v0_1"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _gate(item: int, name: str, status: str, detail: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "item": item,
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence,
    }


def _status_from_checks(checks: list[bool]) -> str:
    return "PASS" if all(checks) else "BLOCK"


def _tail_mass(distribution: dict[int, float], buckets: set[int]) -> float:
    return sum(float(probability) for bucket, probability in distribution.items() if int(bucket) in buckets)


def _distribution_metrics(
    distribution: dict[int, float],
    *,
    settlement_bucket: int,
    market_distribution: dict[int, float],
) -> dict[str, float]:
    support = sorted(set(distribution) | set(market_distribution) | {settlement_bucket})
    brier = 0.0
    market_l1 = 0.0
    for bucket in support:
        probability = float(distribution.get(bucket, 0.0))
        target = 1.0 if int(bucket) == int(settlement_bucket) else 0.0
        brier += (probability - target) ** 2
        market_l1 += abs(probability - float(market_distribution.get(bucket, 0.0)))
    probability_at_settlement = max(float(distribution.get(settlement_bucket, 0.0)), 1e-12)
    return {
        "exact_band_brier": brier,
        "exact_band_logloss": -math.log(probability_at_settlement),
        "market_relative_error": market_l1 / 2.0,
    }


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _sources_for_guidance_case(*, valid: bool) -> dict[str, Any]:
    rows = [
        {
            "time": "13:00",
            "temp_native": 93.0,
            "dewpoint_native": 70.0,
            "humidity": 55.0,
            "pressure": 1012.0,
        },
        {
            "time": "14:00",
            "temp_native": 94.0,
            "dewpoint_native": 70.0,
            "humidity": 55.0,
            "pressure": 1012.0,
        },
    ]
    if valid:
        percentiles = {"10": 94.0, "25": 95.0, "50": 96.0, "75": 97.0, "90": 98.0}
        mean_native = 96.0
    else:
        percentiles = {"10": 75.0, "25": 76.0, "50": 77.0, "75": 78.0, "90": 79.0}
        mean_native = 77.0
    return {
        "wu_history": {
            "ok": True,
            "status": "fresh",
            "data": {"rows": rows, "latest": rows[-1], "max_native": 94.0},
        },
        "wu_current": {
            "ok": True,
            "status": "fresh",
            "data": {"temp_native": 94.0, "max_since_7am_native": 94.0},
        },
        "metar": {"ok": True, "status": "fresh", "data": {"temp_native": 94.0}},
        "open_meteo": {
            "ok": True,
            "status": "fresh",
            "data": {"day_max_native": 95.0, "rows": []},
        },
        "nbm_probabilistic_tmax": {
            "ok": True,
            "status": "fresh",
            "data": {
                "percentiles": percentiles,
                "mean_native": mean_native,
                "stddev_native": 2.0,
            },
        },
    }


def item252_evidence(model: TorontoHighTempModel) -> dict[str, Any]:
    impossible_sources = _sources_for_guidance_case(valid=False)
    valid_sources = _sources_for_guidance_case(valid=True)
    impossible_features = model.extract_live_features(impossible_sources, cutoff_hour=14)
    valid_features = model.extract_live_features(valid_sources, cutoff_hour=14)
    diagnostics = {
        row.get("source"): row
        for row in model.source_diagnostics(impossible_sources)
    }
    nbm_diagnostics = diagnostics.get("nbm_probabilistic_tmax") or {}
    impossible_percentiles = {
        f"nbm_prob_tmax_p{percentile}": impossible_features.get(f"nbm_prob_tmax_p{percentile}")
        for percentile in (10, 25, 50, 75, 90)
    }
    valid_percentiles = {
        f"nbm_prob_tmax_p{percentile}": valid_features.get(f"nbm_prob_tmax_p{percentile}")
        for percentile in (10, 25, 50, 75, 90)
    }
    impossible_source_names = sorted(_as_list(impossible_features.get("guidance_impossible_sources")))
    impossible_feature_names = sorted(_as_list(impossible_features.get("guidance_impossible_features")))
    gates = [
        _gate(
            252,
            "austin_nbm_impossible_before_features",
            _status_from_checks([
                impossible_features.get("guidance_physical_floor") == 94.0,
                all(value is None for value in impossible_percentiles.values()),
                impossible_features.get("nbm_prob_tmax_impossible_flag") == 1.0,
                "nbm_probabilistic_tmax" in impossible_source_names,
            ]),
            "Austin NBM Tmax percentiles below the observed 94F floor are masked before feature use.",
            {
                "guidance_physical_floor": impossible_features.get("guidance_physical_floor"),
                "masked_percentiles": impossible_percentiles,
                "impossible_sources": impossible_source_names,
                "impossible_features": impossible_feature_names,
                "nbm_prob_tmax_floor_gap": impossible_features.get("nbm_prob_tmax_floor_gap"),
            },
        ),
        _gate(
            252,
            "freshness_distinct_from_physical_validity",
            _status_from_checks([
                nbm_diagnostics.get("status") == "fresh",
                nbm_diagnostics.get("physical_validity_status") == "fresh_but_impossible",
                int(nbm_diagnostics.get("impossible_feature_count") or 0) >= 1,
            ]),
            "Source diagnostics preserve timestamp freshness while marking the guidance physically impossible.",
            {
                "source_status": nbm_diagnostics.get("status"),
                "physical_validity_status": nbm_diagnostics.get("physical_validity_status"),
                "impossible_feature_count": nbm_diagnostics.get("impossible_feature_count"),
                "impossible_features": _as_list(nbm_diagnostics.get("impossible_features")),
            },
        ),
        _gate(
            252,
            "valid_guidance_not_silently_removed",
            _status_from_checks([
                valid_features.get("nbm_prob_tmax_physical_valid_flag") == 1.0,
                valid_features.get("nbm_prob_tmax_impossible_flag") == 0.0,
                valid_percentiles.get("nbm_prob_tmax_p10") == 94.0,
                valid_percentiles.get("nbm_prob_tmax_p90") == 98.0,
                valid_features.get("guidance_impossible_source_count") == 0,
            ]),
            "A physically valid NBM row at or above the observed floor remains usable.",
            {
                "valid_percentiles": valid_percentiles,
                "valid_flag": valid_features.get("nbm_prob_tmax_physical_valid_flag"),
                "impossible_flag": valid_features.get("nbm_prob_tmax_impossible_flag"),
                "impossible_source_count": valid_features.get("guidance_impossible_source_count"),
            },
        ),
    ]
    return {
        "item": 252,
        "status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "BLOCK",
        "gates": gates,
        "summary": {
            "guidance_physical_floor": impossible_features.get("guidance_physical_floor"),
            "physical_validity_status": nbm_diagnostics.get("physical_validity_status"),
            "timestamp_status": nbm_diagnostics.get("status"),
            "valid_guidance_preserved": valid_percentiles.get("nbm_prob_tmax_p90") == 98.0,
        },
    }


def _forecast(value: float) -> dict[str, Any]:
    return {"rows": [{"time": "15:00", "temp_native": value}]}


def item249_evidence(model: TorontoHighTempModel) -> dict[str, Any]:
    history = {"max_native": 93.9, "max_times": ["13:53"]}
    now = datetime(2026, 6, 22, 14, 53)
    official_context = model.high_has_stood_lockin_context(
        14,
        history,
        93.9,
        now,
        _forecast(92.5),
        _forecast(93.2),
        official_current_reading=93.0,
        official_source="metar",
    )
    stale_context = model.high_has_stood_lockin_context(
        14,
        history,
        93.9,
        now,
        _forecast(92.5),
        _forecast(93.2),
        official_current_reading=93.0,
        official_source="metar",
        official_current_stale=True,
    )
    rebound_context = model.high_has_stood_lockin_context(
        14,
        history,
        93.9,
        now,
        _forecast(96.0),
        _forecast(95.5),
        official_current_reading=93.0,
        official_source="metar",
    )
    base_scores = {92: 0.10, 93: 0.16, 94: 0.26, 95: 0.24, 96: 0.16, 97: 0.08}
    before = model.normalize_scores(dict(base_scores))
    after = model.apply_late_day_lockin(
        dict(base_scores),
        history["max_native"],
        93.0,
        14,
        strength=official_context.get("strength"),
    )
    tail_buckets = {95, 96, 97}
    tail_before = _tail_mass(before, tail_buckets)
    tail_after = _tail_mass(after, tail_buckets)
    gates = [
        _gate(
            249,
            "official_rollover_activates_when_third_party_flat",
            _status_from_checks([
                official_context.get("active") is True,
                official_context.get("official_rollover_signal") is True,
                official_context.get("current_source_for_rollover") == "metar",
                official_context.get("third_party_current_minus_high") == 0.0,
                (official_context.get("official_current_minus_high") or 0.0) < 0.0,
            ]),
            "Fresh METAR below the standing high activates lock-in even when the third-party current equals the high.",
            official_context,
        ),
        _gate(
            249,
            "stale_official_rollover_is_diagnostic_only",
            _status_from_checks([
                stale_context.get("active") is False,
                stale_context.get("reason") == "official_current_stale",
                stale_context.get("official_rollover_signal") is False,
            ]),
            "A stale official reading is exposed in diagnostics but does not trigger lock-in.",
            stale_context,
        ),
        _gate(
            249,
            "late_rebound_ceiling_not_suppressed",
            _status_from_checks([
                rebound_context.get("active") is False,
                rebound_context.get("reason") == "forecast_ceiling_above_high",
            ]),
            "High forecast ceilings still block lock-in so legitimate late rebounds keep a tail.",
            rebound_context,
        ),
        _gate(
            249,
            "rollover_replay_reduces_warm_tail",
            _status_from_checks([tail_after < tail_before]),
            "Applying the official-rollover lock-in context reduces mass above the stood high.",
            {
                "tail_buckets": sorted(tail_buckets),
                "tail_before": tail_before,
                "tail_after": tail_after,
                "tail_delta": tail_after - tail_before,
            },
        ),
    ]
    return {
        "item": 249,
        "status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "BLOCK",
        "gates": gates,
        "summary": {
            "official_current_reading": official_context.get("official_current_reading"),
            "official_current_minus_high": official_context.get("official_current_minus_high"),
            "third_party_current_minus_high": official_context.get("third_party_current_minus_high"),
            "tail_before": tail_before,
            "tail_after": tail_after,
        },
    }


def _austin_cluster_signal(model: TorontoHighTempModel) -> tuple[float | None, float, float]:
    signal = model.distribution_live_signals(
        using_feature_model=True,
        using_calibrated_empirical=False,
        hour=14,
        history_max=94.0,
        current_temp=94.0,
        current_max=94.0,
        eccc_max=None,
        metar_live_signal=None,
        weather_forecast_max=94.0,
        open_meteo_max=93.0,
        nws_forecast_max=95.0,
        global_ensemble_max=95.9,
        eccc_forecast_high=None,
        observed_bucket=94,
    )
    return signal[0]


def _warm_continuation_cases() -> list[dict[str, Any]]:
    cases = []
    for market_id, warm_signal in (
        ("austin", 96.0),
        ("houston", 96.0),
        ("nyc", 92.0),
        ("miami", 93.0),
        ("san-francisco", 78.0),
    ):
        model = TorontoHighTempModel(target_date=AUDIT_TARGET_DATE, market_id=market_id)
        signal = model.forecast_source_cluster_signal(
            14,
            weather_forecast_max=warm_signal,
            open_meteo_max=warm_signal,
            nws_forecast_max=warm_signal,
            global_ensemble_max=warm_signal,
            eccc_forecast_high=None,
        )
        settlement_bucket = int(warm_signal)
        base_scores = {
            settlement_bucket - 2: 0.10,
            settlement_bucket - 1: 0.20,
            settlement_bucket: 0.40,
            settlement_bucket + 1: 0.20,
            settlement_bucket + 2: 0.10,
        }
        market_distribution = {
            settlement_bucket - 1: 0.30,
            settlement_bucket: 0.70,
        }
        raw_distribution = model.apply_live_signals(dict(base_scores), [(warm_signal, signal[1], 1.0)])
        robust_distribution = model.apply_live_signals(dict(base_scores), [(signal[0], signal[1], 1.0)])
        raw_metrics = _distribution_metrics(
            raw_distribution,
            settlement_bucket=settlement_bucket,
            market_distribution=market_distribution,
        )
        robust_metrics = _distribution_metrics(
            robust_distribution,
            settlement_bucket=settlement_bucket,
            market_distribution=market_distribution,
        )
        cases.append({
            "market_id": market_id,
            "raw_max_signal": warm_signal,
            "robust_cluster_signal": signal[0],
            "cluster_weight": signal[1],
            "exact_band_brier_delta": robust_metrics["exact_band_brier"] - raw_metrics["exact_band_brier"],
            "exact_band_logloss_delta": robust_metrics["exact_band_logloss"] - raw_metrics["exact_band_logloss"],
            "market_relative_error_delta": (
                robust_metrics["market_relative_error"] - raw_metrics["market_relative_error"]
            ),
            "preserved": (
                signal[0] == warm_signal
                and signal[1] > 0.0
                and robust_metrics["exact_band_brier"] <= raw_metrics["exact_band_brier"] + 1e-12
                and robust_metrics["exact_band_logloss"] <= raw_metrics["exact_band_logloss"] + 1e-12
                and robust_metrics["market_relative_error"] <= raw_metrics["market_relative_error"] + 1e-12
            ),
        })
    return cases


def item248_evidence(
    model: TorontoHighTempModel,
    *,
    austin_requalification: str | Path = DEFAULT_AUSTIN_REQUALIFICATION,
) -> dict[str, Any]:
    robust_signal = _austin_cluster_signal(model)
    raw_max_signal = 96.0
    raw_values = {
        "weather_forecast": 94.0,
        "open_meteo": 93.0,
        "nws_hourly": 95.0,
        "global_ensemble": 95.9,
    }
    base_scores = {93: 0.14, 94: 0.24, 95: 0.26, 96: 0.23, 97: 0.13}
    raw_distribution = model.apply_live_signals(dict(base_scores), [(raw_max_signal, robust_signal[1], 1.0)])
    robust_distribution = model.apply_live_signals(dict(base_scores), [robust_signal])
    tail_buckets = {96, 97}
    raw_tail = _tail_mass(raw_distribution, tail_buckets)
    robust_tail = _tail_mass(robust_distribution, tail_buckets)
    variant_signals = {
        "raw_max": raw_max_signal,
        "median": 94.5,
        "trimmed_high": 94.5,
        "capped_warm_source": min(raw_max_signal, 94.5 + 1.0),
    }
    market_distribution = {94: 0.50, 95: 0.50}
    variant_comparison = {}
    for name, signal in variant_signals.items():
        distribution = model.apply_live_signals(dict(base_scores), [(signal, robust_signal[1], 1.0)])
        variant_comparison[name] = {
            "signal": signal,
            "tail_96_97": _tail_mass(distribution, tail_buckets),
            **_distribution_metrics(
                distribution,
                settlement_bucket=94,
                market_distribution=market_distribution,
            ),
        }
    warm_continuation_cases = _warm_continuation_cases()
    requalification = read_json(austin_requalification)
    serving_disposition = (requalification or {}).get("serving_disposition")
    requalification_verdict = (requalification or {}).get("requalification_verdict")
    requalification_status = (requalification or {}).get("status")
    live_candidate_allowed = serving_disposition == "LIVE_CANDIDATE"
    promotion_gate_ok = (
        requalification_status == "PASS"
        and (not live_candidate_allowed or requalification_verdict == "PASS")
    )
    gates = [
        _gate(
            248,
            "austin_raw_max_vs_robust_cluster_replay",
            _status_from_checks([
                robust_signal[0] is not None,
                robust_signal[0] < raw_max_signal,
                raw_tail - robust_tail >= 0.05,
            ]),
            "The Austin fixture isolates how much the raw max cluster adds to 96-97F versus the robust cluster.",
            {
                "raw_source_values": raw_values,
                "raw_max_signal": raw_max_signal,
                "robust_cluster_signal": robust_signal[0],
                "robust_cluster_weight": robust_signal[1],
                "raw_tail_96_97": raw_tail,
                "robust_tail_96_97": robust_tail,
                "tail_delta_robust_minus_raw": robust_tail - raw_tail,
                "variant_comparison": variant_comparison,
            },
        ),
        _gate(
            248,
            "variant_metric_comparison",
            _status_from_checks([
                set(variant_comparison) == {"raw_max", "median", "trimmed_high", "capped_warm_source"},
                variant_comparison["median"]["exact_band_brier"]
                <= variant_comparison["raw_max"]["exact_band_brier"],
                variant_comparison["median"]["exact_band_logloss"]
                <= variant_comparison["raw_max"]["exact_band_logloss"],
                variant_comparison["median"]["market_relative_error"]
                <= variant_comparison["raw_max"]["market_relative_error"],
                variant_comparison["capped_warm_source"]["tail_96_97"]
                <= variant_comparison["raw_max"]["tail_96_97"],
            ]),
            "The Austin replay compares raw max, median, trimmed-high, and capped-warm-source variants.",
            {
                "settlement_bucket": 94,
                "market_distribution": market_distribution,
                "variant_comparison": variant_comparison,
            },
        ),
        _gate(
            248,
            "warm_continuation_not_capped_when_sources_agree",
            _status_from_checks([all(case["preserved"] for case in warm_continuation_cases)]),
            "When F-family forecast clusters agree on continued warmth, the robust statistic keeps the warm signal.",
            {
                "cases": warm_continuation_cases,
            },
        ),
        _gate(
            248,
            "candidate_promotion_fail_closed",
            _status_from_checks([promotion_gate_ok]),
            "The robust-cluster candidate remains governed by the Austin hard-slice requalification packet.",
            {
                "variant_id": ROBUST_CLUSTER_VARIANT_ID,
                "austin_requalification_path": str(austin_requalification),
                "austin_requalification_status": requalification_status,
                "serving_disposition": serving_disposition,
                "requalification_verdict": requalification_verdict,
                "live_candidate_allowed": live_candidate_allowed,
            },
        ),
    ]
    return {
        "item": 248,
        "status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "BLOCK",
        "gates": gates,
        "summary": {
            "variant_id": ROBUST_CLUSTER_VARIANT_ID,
            "raw_max_signal": raw_max_signal,
            "robust_cluster_signal": robust_signal[0],
            "raw_tail_96_97": raw_tail,
            "robust_tail_96_97": robust_tail,
            "serving_disposition": serving_disposition,
            "requalification_verdict": requalification_verdict,
        },
    }


def build_payload(
    *,
    austin_requalification: str | Path = DEFAULT_AUSTIN_REQUALIFICATION,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    model = TorontoHighTempModel(target_date=AUDIT_TARGET_DATE, market_id=AUDIT_MARKET_ID)
    items = {
        "252": item252_evidence(model),
        "249": item249_evidence(model),
        "248": item248_evidence(model, austin_requalification=austin_requalification),
    }
    gates = [
        gate
        for item in items.values()
        for gate in item.get("gates") or []
    ]
    blockers = [gate for gate in gates if gate.get("status") != "PASS"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "target_date": AUDIT_TARGET_DATE,
        "market_id": AUDIT_MARKET_ID,
        "item_order": [252, 249, 248],
        "summary": {
            "items_passed": [int(number) for number, item in items.items() if item.get("status") == "PASS"],
            "items_blocked": [int(number) for number, item in items.items() if item.get("status") != "PASS"],
            "blocker_count": len(blockers),
            "austin_requalification": str(austin_requalification),
        },
        "items": items,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Austin Weather Model Hardening",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Market", payload.get("market_id")],
            ["Target date", payload.get("target_date")],
            ["Items passed", ", ".join(str(item) for item in summary.get("items_passed") or [])],
            ["Items blocked", ", ".join(str(item) for item in summary.get("items_blocked") or []) or "-"],
            ["Blockers", summary.get("blocker_count")],
            ["Austin requalification", summary.get("austin_requalification")],
        ],
    )
    lines += ["", "## Item Status", ""]
    rows = []
    for number in ("252", "249", "248"):
        item = (payload.get("items") or {}).get(number) or {}
        item_summary = item.get("summary") or {}
        if number == "252":
            detail = (
                f"NBM {item_summary.get('physical_validity_status')} "
                f"with floor {fmt_num(item_summary.get('guidance_physical_floor'))}"
            )
        elif number == "249":
            detail = (
                f"official delta {fmt_signed(item_summary.get('official_current_minus_high'))}; "
                f"tail {fmt_num(item_summary.get('tail_before'))} -> {fmt_num(item_summary.get('tail_after'))}"
            )
        else:
            detail = (
                f"cluster {fmt_num(item_summary.get('raw_max_signal'))} -> "
                f"{fmt_num(item_summary.get('robust_cluster_signal'))}; "
                f"96-97F tail {fmt_num(item_summary.get('raw_tail_96_97'))} -> "
                f"{fmt_num(item_summary.get('robust_tail_96_97'))}; "
                f"serving {item_summary.get('serving_disposition')}"
            )
        rows.append([number, item.get("status"), detail])
    lines += markdown_table(["Item", "Status", "Evidence"], rows)
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Item", "Gate", "Status", "Detail"],
        [
            [gate.get("item"), gate.get("gate"), gate.get("status"), gate.get("detail")]
            for gate in payload.get("gates") or []
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Item", "Gate", "Detail"],
            [
                [gate.get("item"), gate.get("gate"), gate.get("detail")]
                for gate in payload.get("blockers") or []
            ],
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="Build Austin hard-slice evidence for roadmap items 252, 249, and 248."
    )
    parser.add_argument("--austin-requalification", default=str(DEFAULT_AUSTIN_REQUALIFICATION))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_payload(austin_requalification=args.austin_requalification)
    out_path = write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    print(
        "Austin weather model hardening: "
        f"{payload['status']} blockers={len(payload.get('blockers') or [])}"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
