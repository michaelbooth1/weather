"""Forecast source-state reliability report for roadmap item 136."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.scoring.metrics import expected_calibration_error, score_rows


SCHEMA_VERSION = "forecast_source_state_reliability_v0.1"
VARIANT_ID = "item136_source_state_reliability_v0_1"
VARIANT_FAMILY = "forecast_source_state_reliability"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SHADOW_VARIANTS = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_shadow_variants.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item136_source_state_reliability.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item136_source_state_reliability_report.md"
DEFAULT_VARIANT_OUT = DEFAULT_BACKTEST_ROOT / "item136_reliability_calibrated_shadow_variants.csv"
OUTPUT_COLUMNS = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "artifact_hash",
    "postprocess_config_hash",
    "experiment_start_date",
    "captured_at_local",
    "range_label",
    "bin_type",
    "bin_value",
    "cutoff_hour",
    "cutoff_regime",
    "source_freshness_state",
    "forecast_source_count_bucket",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
    "source_state_risk",
    "source_state_risk_bucket",
    "forecast_profile_probability",
    "source_state_reliability_alpha",
    "source_state_reliability_reason",
    "source_variant_id",
]


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def source_state_risk(row: dict[str, Any]) -> dict[str, Any]:
    risk = 0.0
    reasons = []
    freshness = str(row.get("source_freshness_state") or "unknown")
    source_count = str(row.get("forecast_source_count_bucket") or "unknown")
    disagreement = str(row.get("forecast_disagreement_bucket") or "unknown")

    if "failed" in freshness:
        risk += 0.35
        reasons.append("failed source")
    elif "stale" in freshness:
        risk += 0.20
        reasons.append("stale source")
    elif freshness in {"missing_source_status", "unknown", ""}:
        risk += 0.15
        reasons.append("missing source status")

    if source_count == "low_count":
        risk += 0.25
        reasons.append("low forecast source count")
    elif source_count == "two_sources":
        risk += 0.08
        reasons.append("limited forecast source count")
    elif source_count == "unknown":
        risk += 0.10
        reasons.append("unknown forecast source count")

    if disagreement == "high_disagreement":
        risk += 0.25
        reasons.append("high forecast disagreement")
    elif disagreement == "moderate_disagreement":
        risk += 0.10
        reasons.append("moderate forecast disagreement")
    elif disagreement == "unknown":
        risk += 0.05
        reasons.append("unknown forecast disagreement")

    risk = min(0.85, risk)
    if risk >= 0.50:
        bucket = "high_risk"
    elif risk >= 0.25:
        bucket = "moderate_risk"
    else:
        bucket = "low_risk"
    return {
        "risk": risk,
        "bucket": bucket,
        "alpha": 1.0 - risk,
        "reason": "; ".join(reasons) or "all-fresh source state",
    }


def _scored_row(row: dict[str, Any], probability_field: str) -> dict[str, Any] | None:
    probability = _safe_float(row.get(probability_field))
    market = _safe_float(row.get("market_yes"))
    outcome = _safe_int(row.get("outcome"))
    if probability is None or market is None or outcome not in {0, 1}:
        return None
    return {
        **row,
        "model_probability": _clamp_probability(probability),
        "market_yes": _clamp_probability(market),
        "outcome": int(outcome),
    }


def comparison(rows: list[dict[str, Any]], probability_field: str = "reliability_probability") -> dict[str, Any] | None:
    model_rows = [
        scored
        for row in rows
        if (scored := _scored_row(row, probability_field)) is not None
    ]
    raw_rows = [
        scored
        for row in rows
        if (scored := _scored_row(row, "forecast_profile_probability")) is not None
    ]
    current_rows = [
        scored
        for row in rows
        if (scored := _scored_row(row, "current_probability")) is not None
    ]
    if not model_rows or not raw_rows or not current_rows:
        return None
    model = score_rows(model_rows)
    raw = score_rows(raw_rows)
    current = score_rows(current_rows)
    if not model or not raw or not current:
        return None
    return {
        "n": model["n"],
        "candidate_brier": model["model_brier"],
        "raw_forecast_brier": raw["model_brier"],
        "current_brier": current["model_brier"],
        "market_brier": model["market_brier"],
        "candidate_logloss": model["model_logloss"],
        "raw_forecast_logloss": raw["model_logloss"],
        "current_logloss": current["model_logloss"],
        "market_logloss": model["market_logloss"],
        "candidate_ece": expected_calibration_error(model_rows, "model_probability"),
        "delta_vs_raw_forecast": model["model_brier"] - raw["model_brier"],
        "delta_vs_current": model["model_brier"] - current["model_brier"],
        "delta_vs_market": model["model_brier"] - model["market_brier"],
        "candidate_skill": model["brier_skill_score"],
        "base_rate": model["base_rate"],
    }


def daily_first_comparison(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row.get("market_id") or ""), str(row.get("target_date") or ""))
        if key[0] and key[1]:
            grouped[key].append(row)
    scores = [comparison(day_rows) for day_rows in grouped.values()]
    scores = [score for score in scores if score]
    if not scores:
        return None

    def avg(key: str) -> float | None:
        values = [score.get(key) for score in scores if score.get(key) is not None]
        return sum(values) / len(values) if values else None

    return {
        "n_days": len(scores),
        "n": sum(int(score.get("n") or 0) for score in scores),
        "candidate_brier": avg("candidate_brier"),
        "raw_forecast_brier": avg("raw_forecast_brier"),
        "current_brier": avg("current_brier"),
        "market_brier": avg("market_brier"),
        "candidate_ece": avg("candidate_ece"),
        "delta_vs_raw_forecast": avg("candidate_brier") - avg("raw_forecast_brier"),
        "delta_vs_current": avg("candidate_brier") - avg("current_brier"),
        "delta_vs_market": avg("candidate_brier") - avg("market_brier"),
        "base_rate": avg("base_rate"),
    }


def grouped_comparison(rows: list[dict[str, Any]], group_key: str, *, daily_first: bool = False) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key) or "unknown"].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        comp = daily_first_comparison(group_rows) if daily_first else comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def source_state_slice(row: dict[str, Any]) -> str:
    state = str(row.get("source_freshness_state") or "unknown")
    if state == "all_fresh":
        return "all_fresh"
    if state in {"unknown", "", "missing_source_status"}:
        return "unknown_source_state"
    return "degraded_source"


def build_reliability_rows(shadow_variant_path: str | Path = DEFAULT_SHADOW_VARIANTS) -> list[dict[str, Any]]:
    rows = []
    for row in _read_csv(shadow_variant_path):
        forecast_probability = _safe_float(row.get("probability"))
        current_probability = _safe_float(row.get("current_probability"))
        if forecast_probability is None or current_probability is None:
            continue
        risk = source_state_risk(row)
        adjusted = (risk["alpha"] * forecast_probability) + ((1.0 - risk["alpha"]) * current_probability)
        rows.append({
            **row,
            "source_variant_id": row.get("variant_id") or "",
            "variant_id": VARIANT_ID,
            "variant_family": VARIANT_FAMILY,
            "uses_market_features": "False",
            "is_control": "False",
            "forecast_profile_probability": forecast_probability,
            "probability": _clamp_probability(adjusted),
            "reliability_probability": _clamp_probability(adjusted),
            "current_probability": current_probability,
            "market_yes": _safe_float(row.get("market_yes")),
            "outcome": _safe_int(row.get("outcome")),
            "source_state_risk": risk["risk"],
            "source_state_risk_bucket": risk["bucket"],
            "source_state_slice": source_state_slice(row),
            "source_state_reliability_alpha": risk["alpha"],
            "source_state_reliability_reason": risk["reason"],
        })
    return rows


def calibration_curve(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("source_state_risk_bucket") or "unknown"].append(row)
    output = []
    for bucket, bucket_rows in sorted(grouped.items()):
        comp = comparison(bucket_rows)
        if not comp:
            continue
        output.append({
            "risk_bucket": bucket,
            "mean_source_state_risk": sum(float(row.get("source_state_risk") or 0.0) for row in bucket_rows) / len(bucket_rows),
            **comp,
        })
    return output


def market_thresholds(rows: list[dict[str, Any]], *, min_rows: int = 50, tolerance: float = 0.001) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("market_id") or "unknown")].append(row)
    output = []
    for market, market_rows in sorted(grouped.items()):
        risky = [row for row in market_rows if row.get("source_state_risk_bucket") in {"moderate_risk", "high_risk"}]
        comp = comparison(risky) if risky else None
        if not comp or (comp.get("n") or 0) < min_rows:
            status = "insufficient_rows"
            reasons = [f"risk rows {(comp or {}).get('n') or 0} < {min_rows}"]
        else:
            reasons = []
            if comp.get("delta_vs_raw_forecast") is None or comp["delta_vs_raw_forecast"] > tolerance:
                reasons.append(f"reliability adjustment harms raw forecast by {fmt_signed(comp.get('delta_vs_raw_forecast'), 4)}")
            status = "pass" if not reasons else "blocked"
        output.append({
            "market_id": market,
            "status": status,
            "risk_rows": (comp or {}).get("n", 0),
            "max_recommended_shrinkage": max((float(row.get("source_state_risk") or 0.0) for row in risky), default=0.0),
            "comparison": comp or {},
            "reasons": reasons,
        })
    return output


def quote_risk_reporting(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts = Counter(str(row.get("source_state_reliability_reason") or "unknown") for row in rows)
    risky_rows = [
        row
        for row in rows
        if row.get("source_state_risk_bucket") in {"moderate_risk", "high_risk"}
    ]
    return {
        "status": "shadow_only",
        "claim_lane": "weather_only_quote_risk_diagnostic",
        "rows": len(rows),
        "risky_rows": len(risky_rows),
        "reason_field": "source_state_reliability_reason",
        "alpha_field": "source_state_reliability_alpha",
        "risk_bucket_field": "source_state_risk_bucket",
        "top_reasons": [
            {"reason": reason, "rows": count}
            for reason, count in reason_counts.most_common(8)
        ],
        "usage": (
            "Source-state reliability reason is available for quote-width/risk diagnostics, "
            "but this no-market shadow lane cannot grant promotion or quote-risk permission until "
            "reliability acceptance gates pass."
        ),
    }


def acceptance(payload: dict[str, Any]) -> dict[str, Any]:
    by_slice = {row.get("group"): row for row in payload.get("by_source_state_slice") or []}
    by_disagreement = {row.get("group"): row for row in payload.get("by_forecast_disagreement") or []}
    reasons = []
    all_fresh = by_slice.get("all_fresh")
    degraded = by_slice.get("degraded_source")
    high_disagreement = by_disagreement.get("high_disagreement")
    if not all_fresh:
        reasons.append("all-fresh slice missing")
    elif all_fresh.get("delta_vs_raw_forecast") is None or all_fresh["delta_vs_raw_forecast"] > 0.001:
        reasons.append("all-fresh slice harmed by reliability adjustment")
    if not degraded:
        reasons.append("degraded-source slice missing")
    elif degraded.get("delta_vs_raw_forecast") is None or degraded["delta_vs_raw_forecast"] > 0.0:
        reasons.append("degraded-source slice does not improve raw forecast-profile skill")
    if not high_disagreement:
        reasons.append("high-disagreement slice missing")
    elif high_disagreement.get("delta_vs_raw_forecast") is None or high_disagreement["delta_vs_raw_forecast"] > 0.0:
        reasons.append("high-disagreement slice does not improve raw forecast-profile skill")
    blocked_markets = [
        row["market_id"]
        for row in payload.get("market_thresholds") or []
        if row.get("status") == "blocked"
    ]
    if blocked_markets:
        reasons.append("market reliability thresholds blocked " + ", ".join(blocked_markets[:8]))
    return {
        "status": "pass" if not reasons else "blocked",
        "reasons": reasons,
        "blocked_markets": blocked_markets,
    }


def write_variant_csv(path: str | Path | None, rows: list[dict[str, Any]]) -> str | None:
    if not path:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(path)


def build_report_payload(
    shadow_variants: str | Path = DEFAULT_SHADOW_VARIANTS,
    *,
    variant_out: str | Path | None = DEFAULT_VARIANT_OUT,
) -> dict[str, Any]:
    rows = build_reliability_rows(shadow_variants)
    variant_path = write_variant_csv(variant_out, rows)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {"source_shadow_variants": str(shadow_variants)},
        "variant": {
            "variant_id": VARIANT_ID,
            "variant_family": VARIANT_FAMILY,
            "path": variant_path,
            "rows": len(rows),
            "uses_market_features": False,
            "is_control": False,
        },
        "aggregate": comparison(rows) or {},
        "daily_first": daily_first_comparison(rows) or {},
        "by_source_state_slice": grouped_comparison(rows, "source_state_slice"),
        "by_source_freshness": grouped_comparison(rows, "source_freshness_state"),
        "by_forecast_source_count": grouped_comparison(rows, "forecast_source_count_bucket"),
        "by_forecast_disagreement": grouped_comparison(rows, "forecast_disagreement_bucket"),
        "calibration_curve": calibration_curve(rows),
        "market_thresholds": market_thresholds(rows),
        "quote_risk_reporting": quote_risk_reporting(rows),
    }
    payload["acceptance"] = acceptance(payload)
    return payload


def _slice_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("group") or row.get("risk_bucket") or "-",
            row.get("n", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("raw_forecast_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_raw_forecast"), 4),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
        ]
        for row in rows
    ]


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    acceptance_payload = payload.get("acceptance") or {}
    lines = [
        "# Forecast Source-State Reliability Calibrator",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Acceptance: `{acceptance_payload.get('status')}`",
        "",
        "## Variant",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variant", (payload.get("variant") or {}).get("variant_id") or "-"],
            ["Family", (payload.get("variant") or {}).get("variant_family") or "-"],
            ["Rows", (payload.get("variant") or {}).get("rows", 0)],
            ["Shadow CSV", (payload.get("variant") or {}).get("path") or "-"],
            ["Acceptance reasons", "; ".join(acceptance_payload.get("reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Reliability Slices", ""]
    for title, key in [
        ("Source State", "by_source_state_slice"),
        ("Source Freshness", "by_source_freshness"),
        ("Forecast Source Count", "by_forecast_source_count"),
        ("Forecast Disagreement", "by_forecast_disagreement"),
    ]:
        lines += ["", f"### {title}", ""]
        lines += markdown_table(
            [
                "Group",
                "Rows",
                "Reliability Brier",
                "Raw Forecast Brier",
                "Current Brier",
                "Market Brier",
                "Delta Raw",
                "Delta Current",
                "Delta Market",
            ],
            _slice_rows(payload.get(key) or []),
        )
    lines += ["", "## Calibration Curve", ""]
    lines += markdown_table(
        [
            "Risk Bucket",
            "Rows",
            "Mean Risk",
            "Reliability Brier",
            "Raw Forecast Brier",
            "Delta Raw",
            "Delta Current",
        ],
        [
            [
                row.get("risk_bucket"),
                row.get("n", 0),
                fmt_num(row.get("mean_source_state_risk")),
                fmt_num(row.get("candidate_brier")),
                fmt_num(row.get("raw_forecast_brier")),
                fmt_signed(row.get("delta_vs_raw_forecast"), 4),
                fmt_signed(row.get("delta_vs_current"), 4),
            ]
            for row in payload.get("calibration_curve") or []
        ],
    )
    lines += ["", "## Per-Market Reliability Thresholds", ""]
    lines += markdown_table(
        ["Market", "Status", "Risk Rows", "Max Shrinkage", "Delta Raw", "Reasons"],
        [
            [
                row.get("market_id"),
                row.get("status"),
                row.get("risk_rows", 0),
                fmt_num(row.get("max_recommended_shrinkage")),
                fmt_signed((row.get("comparison") or {}).get("delta_vs_raw_forecast"), 4),
                "; ".join(row.get("reasons") or []) or "-",
            ]
            for row in payload.get("market_thresholds") or []
        ],
    )
    quote_risk = payload.get("quote_risk_reporting") or {}
    lines += ["", "## Quote-Risk Reporting", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", quote_risk.get("status") or "-"],
            ["Claim lane", quote_risk.get("claim_lane") or "-"],
            ["Rows", quote_risk.get("rows", 0)],
            ["Risky rows", quote_risk.get("risky_rows", 0)],
            ["Reason field", quote_risk.get("reason_field") or "-"],
            ["Alpha field", quote_risk.get("alpha_field") or "-"],
            ["Risk bucket field", quote_risk.get("risk_bucket_field") or "-"],
            ["Usage", quote_risk.get("usage") or "-"],
        ],
    )
    lines += ["", "### Top Reliability Reasons", ""]
    lines += markdown_table(
        ["Reason", "Rows"],
        [
            [row.get("reason") or "-", row.get("rows", 0)]
            for row in quote_risk.get("top_reasons") or []
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_report_payload(
        args.shadow_variants,
        variant_out=None if args.variant_out == "" else args.variant_out,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown_report(args.report, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build roadmap item 136 forecast source-state reliability report.")
    parser.add_argument("--shadow-variants", default=str(DEFAULT_SHADOW_VARIANTS))
    parser.add_argument("--variant-out", default=str(DEFAULT_VARIANT_OUT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(f"Forecast source-state reliability: {payload['acceptance']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
