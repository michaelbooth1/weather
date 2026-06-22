"""Local-hour performance audit for candidate variant row exports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.hourly_model_performance import HOUR_REGIME_LABELS, hour_regime
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("candidate_hourly_performance")
GATE_SCHEMA_VERSION = "candidate_hourly_performance_gate_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_VARIANT_ROWS = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_variant_rows.csv"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_hourly_candidate_performance.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_hourly_candidate_performance_report.md"
DEFAULT_MIN_MARKET_DAYS = 10
DEFAULT_EARLY_BRIER_TOLERANCE = 0.003
DEFAULT_EARLY_LOGLOSS_TOLERANCE = 0.010
DEFAULT_EARLY_ECE_MAX = 0.120
CANDIDATE_ROW_CORPUS_HASH_FIELDS = [
    "variant_id",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "captured_at_local",
    "variant_probability",
    "current_probability",
    "market_yes",
    "outcome",
    "bin_type",
    "bin_value",
    "settlement_distance_bucket",
    "forecast_bucket_pressure",
    "forecast_disagreement_bucket",
    "forecast_source_count_bucket",
    "source_freshness_state",
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def parse_capture_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def brier(probability: float, outcome: int) -> float:
    return (probability - outcome) ** 2


def binary_logloss(probability: float, outcome: int) -> float:
    probability = max(1e-15, min(1.0 - 1e-15, float(probability)))
    return -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))


def expected_calibration_error(rows: list[dict[str, Any]], probability_key: str, n_bins: int = 5) -> float | None:
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for row in rows:
        probability = safe_float(row.get(probability_key))
        outcome = safe_int(row.get("outcome"))
        if probability is None or outcome is None:
            continue
        index = min(n_bins - 1, int(max(0.0, min(0.999999, probability)) * n_bins))
        bins[index].append((probability, outcome))
    total = sum(len(bucket) for bucket in bins)
    if total <= 0:
        return None
    error = 0.0
    for bucket in bins:
        if not bucket:
            continue
        predicted = sum(probability for probability, _ in bucket) / len(bucket)
        actual = sum(outcome for _, outcome in bucket) / len(bucket)
        error += (len(bucket) / total) * abs(predicted - actual)
    return error


def normalize_variant_row(row: dict[str, Any]) -> dict[str, Any] | None:
    captured_at = parse_capture_time(row.get("captured_at_local"))
    outcome = safe_int(row.get("outcome"))
    variant_probability = safe_float(row.get("probability"))
    current_probability = safe_float(row.get("current_probability"))
    market_probability = safe_float(row.get("market_yes"))
    if (
        captured_at is None
        or outcome is None
        or variant_probability is None
        or current_probability is None
        or market_probability is None
        or not row.get("market_id")
        or not row.get("target_date")
        or not row.get("snapshot_id")
        or not row.get("band_key")
    ):
        return None
    return {
        **row,
        "capture_hour": captured_at.hour,
        "_capture_timestamp": captured_at.timestamp(),
        "variant_probability": variant_probability,
        "current_probability": current_probability,
        "market_yes": market_probability,
        "outcome": outcome,
    }


def read_variant_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            normalized = normalize_variant_row(row)
            if normalized is not None:
                rows.append(normalized)
        return rows


def _hash_value(row: dict[str, Any], field: str) -> Any:
    if field == "variant_probability":
        value = safe_float(row.get("variant_probability", row.get("probability")))
        return round(float(value), 12) if value is not None else None
    if field in {"current_probability", "market_yes"}:
        value = safe_float(row.get(field))
        return round(float(value), 12) if value is not None else None
    if field == "outcome":
        value = safe_int(row.get(field))
        return int(value) if value is not None else None
    value = row.get(field)
    return "" if value in (None, "") else str(value)


def candidate_rows_corpus_hash(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    canonical = [
        {field: _hash_value(row, field) for field in CANDIDATE_ROW_CORPUS_HASH_FIELDS}
        for row in rows
    ]
    canonical.sort(key=lambda row: tuple(row.get(field) for field in CANDIDATE_ROW_CORPUS_HASH_FIELDS))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def hourly_checkpoint_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the first available variant row per market-day-band-local-hour."""
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("market_id"),
            row.get("target_date"),
            row.get("band_key"),
            row.get("capture_hour"),
        )
        if key not in selected or float(row["_capture_timestamp"]) < float(selected[key]["_capture_timestamp"]):
            selected[key] = row
    return [
        selected[key]
        for key in sorted(key for key in selected if key[3] is not None)
    ]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def score_probability(rows: list[dict[str, Any]], probability_key: str) -> dict[str, Any]:
    scored = [
        (safe_float(row.get(probability_key)), safe_int(row.get("outcome")))
        for row in rows
    ]
    scored = [(p, y) for p, y in scored if p is not None and y is not None]
    if not scored:
        return {"brier": None, "logloss": None, "ece": None}
    return {
        "brier": sum(brier(p, y) for p, y in scored) / len(scored),
        "logloss": sum(binary_logloss(p, y) for p, y in scored) / len(scored),
        "ece": expected_calibration_error(rows, probability_key),
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    variant = score_probability(rows, "variant_probability")
    current = score_probability(rows, "current_probability")
    market = score_probability(rows, "market_yes")
    winners = [row for row in rows if safe_int(row.get("outcome")) == 1]
    losers = [row for row in rows if safe_int(row.get("outcome")) == 0]
    variant_brier = variant["brier"]
    current_brier = current["brier"]
    market_brier = market["brier"]
    variant_logloss = variant["logloss"]
    current_logloss = current["logloss"]
    market_logloss = market["logloss"]
    return {
        "n": len(rows),
        "markets": len({row.get("market_id") for row in rows if row.get("market_id")}),
        "market_days": len({
            (row.get("market_id"), row.get("target_date"))
            for row in rows
            if row.get("market_id") and row.get("target_date")
        }),
        "snapshots": len({row.get("snapshot_id") for row in rows if row.get("snapshot_id")}),
        "variant_brier": variant_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": (
            variant_brier - current_brier
            if variant_brier is not None and current_brier is not None
            else None
        ),
        "delta_vs_market": (
            variant_brier - market_brier
            if variant_brier is not None and market_brier is not None
            else None
        ),
        "variant_logloss": variant_logloss,
        "current_logloss": current_logloss,
        "market_logloss": market_logloss,
        "logloss_delta_vs_current": (
            variant_logloss - current_logloss
            if variant_logloss is not None and current_logloss is not None
            else None
        ),
        "logloss_delta_vs_market": (
            variant_logloss - market_logloss
            if variant_logloss is not None and market_logloss is not None
            else None
        ),
        "variant_ece": variant["ece"],
        "current_ece": current["ece"],
        "market_ece": market["ece"],
        "base_rate": _mean([float(row["outcome"]) for row in rows]),
        "winner_variant_probability": _mean([
            float(row["variant_probability"]) for row in winners
        ]),
        "winner_current_probability": _mean([
            float(row["current_probability"]) for row in winners
        ]),
        "winner_market_probability": _mean([
            float(row["market_yes"]) for row in winners
        ]),
        "loser_variant_probability": _mean([
            float(row["variant_probability"]) for row in losers
        ]),
        "loser_current_probability": _mean([
            float(row["current_probability"]) for row in losers
        ]),
        "loser_market_probability": _mean([
            float(row["market_yes"]) for row in losers
        ]),
    }


def group_rows(rows: list[dict[str, Any]], key_fn) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key_fn(row)].append(row)
    return grouped


def summarize_by_hour(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for hour, hour_rows in sorted(group_rows(rows, lambda row: row.get("capture_hour")).items()):
        if hour is None:
            continue
        summary = summarize_rows(hour_rows)
        if summary:
            output.append({
                "hour": int(hour),
                "hour_label": f"{int(hour):02d}:00",
                **summary,
            })
    return output


def summarize_by_regime(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    grouped = group_rows(rows, lambda row: hour_regime(row.get("capture_hour")))
    for regime in HOUR_REGIME_LABELS:
        regime_rows = grouped.get(regime, [])
        summary = summarize_rows(regime_rows)
        if summary:
            output.append({
                "regime": regime,
                "regime_label": HOUR_REGIME_LABELS[regime],
                **summary,
            })
    return output


def candidate_hourly_gate(
    by_regime: list[dict[str, Any]],
    min_market_days: int = DEFAULT_MIN_MARKET_DAYS,
    early_brier_tolerance: float = DEFAULT_EARLY_BRIER_TOLERANCE,
    early_logloss_tolerance: float = DEFAULT_EARLY_LOGLOSS_TOLERANCE,
    early_ece_max: float = DEFAULT_EARLY_ECE_MAX,
) -> dict[str, Any]:
    regimes = {row.get("regime"): row for row in by_regime}
    early = regimes.get("early_morning")
    blockers = []
    if not early:
        blockers.append({
            "gate": "early_hour_regime_missing",
            "detail": "no 00:00-08:00 candidate variant rows are available",
        })
    else:
        if int(early.get("market_days") or 0) < int(min_market_days):
            blockers.append({
                "gate": "early_hour_min_market_days",
                "detail": f"early-hour candidate evidence has {early.get('market_days', 0)} market-days; need {int(min_market_days)}",
            })
        delta_market = early.get("delta_vs_market")
        if delta_market is None or float(delta_market) > float(early_brier_tolerance):
            blockers.append({
                "gate": "early_hour_brier_regression",
                "detail": (
                    "early-hour candidate Brier trails market by "
                    f"{float(delta_market or 0.0):.4f} > {float(early_brier_tolerance):.4f}"
                ),
            })
        logloss_delta = early.get("logloss_delta_vs_market")
        if logloss_delta is None or float(logloss_delta) > float(early_logloss_tolerance):
            blockers.append({
                "gate": "early_hour_logloss_regression",
                "detail": (
                    "early-hour candidate log-loss trails market by "
                    f"{float(logloss_delta or 0.0):.4f} > {float(early_logloss_tolerance):.4f}"
                ),
            })
        ece = early.get("variant_ece")
        if ece is not None and float(ece) > float(early_ece_max):
            blockers.append({
                "gate": "early_hour_calibration_error",
                "detail": f"early-hour candidate ECE {float(ece):.4f} exceeds {float(early_ece_max):.4f}",
            })
    return {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "first_blocker": blockers[0] if blockers else None,
        "thresholds": {
            "min_market_days": int(min_market_days),
            "early_brier_regression_tolerance": float(early_brier_tolerance),
            "early_logloss_regression_tolerance": float(early_logloss_tolerance),
            "early_ece_max": float(early_ece_max),
        },
        "early_morning": early,
    }


def build_candidate_hourly_performance(
    variant_rows: str | Path = DEFAULT_VARIANT_ROWS,
    min_market_days: int = DEFAULT_MIN_MARKET_DAYS,
) -> dict[str, Any]:
    source_rows = read_variant_rows(variant_rows)
    checkpoint_rows = hourly_checkpoint_rows(source_rows)
    by_hour = summarize_by_hour(checkpoint_rows)
    by_regime = summarize_by_regime(checkpoint_rows)
    gate = candidate_hourly_gate(by_regime, min_market_days=min_market_days)
    variant_ids = sorted({str(row.get("variant_id")) for row in source_rows if row.get("variant_id")})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "variant_rows_path": str(variant_rows),
        "variant_ids": variant_ids,
        "corpus": {
            "source_rows": len(source_rows),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "markets": len({row.get("market_id") for row in source_rows if row.get("market_id")}),
            "market_days": len({
                (row.get("market_id"), row.get("target_date"))
                for row in source_rows
                if row.get("market_id") and row.get("target_date")
            }),
            "snapshots": len({row.get("snapshot_id") for row in source_rows if row.get("snapshot_id")}),
            "corpus_hash": candidate_rows_corpus_hash(source_rows),
        },
        "by_hour": by_hour,
        "by_hour_regime": by_regime,
        "candidate_hourly_gate": gate,
    }


def _summary_table(row: dict[str, Any] | None) -> list[list[Any]]:
    row = row or {}
    return [
        ["Rows", row.get("n", 0)],
        ["Market-days", row.get("market_days", 0)],
        ["Variant Brier", fmt_num(row.get("variant_brier"))],
        ["Current Brier", fmt_num(row.get("current_brier"))],
        ["Market Brier", fmt_num(row.get("market_brier"))],
        ["Delta vs current", fmt_signed(row.get("delta_vs_current"))],
        ["Delta vs market", fmt_signed(row.get("delta_vs_market"))],
        ["Variant log-loss", fmt_num(row.get("variant_logloss"))],
        ["Market log-loss", fmt_num(row.get("market_logloss"))],
        ["Log-loss delta vs market", fmt_signed(row.get("logloss_delta_vs_market"))],
        ["Variant ECE", fmt_num(row.get("variant_ece"))],
        ["Winner variant P", fmt_num(row.get("winner_variant_probability"))],
        ["Winner market P", fmt_num(row.get("winner_market_probability"))],
    ]


def render_report(payload: dict[str, Any]) -> str:
    gate = payload.get("candidate_hourly_gate") or {}
    early = gate.get("early_morning") or {}
    lines = [
        "# Candidate Hourly Performance Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Scope",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Schema", payload.get("schema_version")],
                ["Variant rows", payload.get("variant_rows_path")],
                ["Variant IDs", ", ".join(payload.get("variant_ids") or []) or "-"],
                ["Source rows", (payload.get("corpus") or {}).get("source_rows", 0)],
                ["Hourly checkpoint rows", (payload.get("corpus") or {}).get("hourly_checkpoint_rows", 0)],
                ["Market-days", (payload.get("corpus") or {}).get("market_days", 0)],
            ],
        ),
        "",
        "## Candidate Hourly Gate",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Status", gate.get("status")],
                ["Blockers", gate.get("blocker_count", 0)],
                ["First blocker", (gate.get("first_blocker") or {}).get("gate") or "-"],
            ],
        ),
        "",
        "## Early Morning 00:00-08:00",
        "",
        *markdown_table(["Metric", "Value"], _summary_table(early)),
        "",
        "## Hour Regimes",
        "",
        *markdown_table(
            [
                "Regime",
                "Rows",
                "Days",
                "Variant Brier",
                "Current Brier",
                "Market Brier",
                "Delta Market",
                "LogLoss Delta Market",
            ],
            [
                [
                    row.get("regime_label"),
                    row.get("n", 0),
                    row.get("market_days", 0),
                    fmt_num(row.get("variant_brier")),
                    fmt_num(row.get("current_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_market")),
                    fmt_signed(row.get("logloss_delta_vs_market")),
                ]
                for row in payload.get("by_hour_regime") or []
            ],
        ),
        "",
        "## Hour By Hour",
        "",
        *markdown_table(
            [
                "Hour",
                "Rows",
                "Days",
                "Variant Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
            ],
            [
                [
                    row.get("hour_label"),
                    row.get("n", 0),
                    row.get("market_days", 0),
                    fmt_num(row.get("variant_brier")),
                    fmt_num(row.get("current_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_current")),
                    fmt_signed(row.get("delta_vs_market")),
                ]
                for row in payload.get("by_hour") or []
            ],
        ),
        "",
        "Note: this audit scores a candidate variant export. It does not replace the production current-serving hourly gate until the candidate is promoted.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[str, str]:
    json_path = Path(json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return str(json_path), str(report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a candidate variant export by local capture hour.")
    parser.add_argument("--variant-rows", default=str(DEFAULT_VARIANT_ROWS))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--min-market-days", type=int, default=DEFAULT_MIN_MARKET_DAYS)
    args = parser.parse_args()

    payload = build_candidate_hourly_performance(
        variant_rows=args.variant_rows,
        min_market_days=args.min_market_days,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    gate = payload.get("candidate_hourly_gate") or {}
    print(f"Candidate hourly gate: {gate.get('status')} ({gate.get('blocker_count', 0)} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
