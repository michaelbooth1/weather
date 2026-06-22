"""Exact-band and settlement-distance-0 early-hour candidate gate."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.candidate_hourly_performance import candidate_rows_corpus_hash
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("exact_band_distance_zero_calibration")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_VARIANT_ROWS = DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration_report.md"
DEFAULT_MARKET_TOL = 0.003
DEFAULT_LOGLOSS_TOL = 0.010
TARGET_SLICES = (
    "exact_band_early",
    "settlement_distance_0_early",
)
GUARDRAIL_SLICES = (
    "one_above_early",
    "one_below_early",
    "adjacent_early",
    "broad_early",
    "ramp",
    "late",
    "lock_in",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_int(value: Any) -> int | None:
    value = safe_float(value)
    return int(value) if value is not None else None


def clamp_probability(value: Any) -> float | None:
    probability = safe_float(value)
    if probability is None:
        return None
    return max(1e-15, min(1.0 - 1e-15, probability))


def parse_capture_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def capture_hour(row: dict[str, Any]) -> int | None:
    parsed = parse_capture_time(row.get("captured_at_local"))
    if parsed is not None:
        return parsed.hour
    return safe_int(row.get("cutoff_hour"))


def inferred_regime(row: dict[str, Any]) -> str:
    raw_regime = str(row.get("cutoff_regime") or "").strip().lower()
    if raw_regime in {"early", "late", "lock_in"}:
        return raw_regime
    if raw_regime in {"midday", "ramp"}:
        return "ramp"
    hour = row.get("capture_hour")
    if hour is None:
        return "unknown"
    hour = int(hour)
    if hour <= 8:
        return "early"
    if hour <= 14:
        return "ramp"
    if hour <= 19:
        return "late"
    return "lock_in"


def band_value(row: dict[str, Any]) -> float | None:
    value = safe_float(row.get("bin_value") or row.get("bin_value_c"))
    if value is not None:
        return value
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(row.get("band_key") or ""))
    return safe_float(match.group(0)) if match else None


def distance_bucket_value(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.endswith("+"):
        text = text[:-1]
    return safe_int(text)


def read_variant_rows(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            probability = clamp_probability(source.get("probability"))
            current = clamp_probability(source.get("current_probability"))
            market = clamp_probability(source.get("market_yes"))
            outcome = safe_int(source.get("outcome"))
            if (
                probability is None
                or current is None
                or market is None
                or outcome is None
                or not source.get("market_id")
                or not source.get("target_date")
                or not source.get("snapshot_id")
                or not source.get("band_key")
            ):
                continue
            row = {
                **source,
                "market_id": str(source.get("market_id") or "").lower(),
                "target_date": source.get("target_date"),
                "snapshot_id": source.get("snapshot_id"),
                "band_key": source.get("band_key"),
                "probability": probability,
                "variant_probability": probability,
                "current_probability": current,
                "market_yes": market,
                "outcome": int(outcome),
                "bin_type": str(source.get("bin_type") or "").lower(),
                "settlement_distance_bucket": str(source.get("settlement_distance_bucket") or "").lower(),
                "bin_value_numeric": band_value(source),
                "capture_hour": None,
                "slice_regime": "unknown",
                "signed_band_offset": None,
            }
            row["capture_hour"] = capture_hour(row)
            row["slice_regime"] = inferred_regime(row)
            rows.append(row)
    return enrich_signed_band_offsets(rows)


def enrich_signed_band_offsets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    grouped: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(output):
        grouped[(row.get("market_id"), row.get("target_date"), row.get("snapshot_id"))].append(index)

    for indexes in grouped.values():
        eq_indexes = [
            index for index in indexes
            if output[index].get("bin_type") == "eq" and output[index].get("bin_value_numeric") is not None
        ]
        eq_indexes.sort(key=lambda index: float(output[index]["bin_value_numeric"]))
        winner_positions = [
            position for position, index in enumerate(eq_indexes)
            if int(output[index].get("outcome") or 0) == 1
        ]
        if not winner_positions:
            continue
        winner_position = winner_positions[0]
        for position, index in enumerate(eq_indexes):
            output[index]["signed_band_offset"] = position - winner_position
    return output


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def logloss(probability: float, outcome: int) -> float:
    probability = max(1e-15, min(1.0 - 1e-15, float(probability)))
    return -(int(outcome) * math.log(probability) + (1 - int(outcome)) * math.log(1.0 - probability))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _loss_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "candidate_logloss": None,
            "current_logloss": None,
            "market_logloss": None,
        }
    candidate_brier = _mean([brier(row["variant_probability"], row["outcome"]) for row in rows])
    current_brier = _mean([brier(row["current_probability"], row["outcome"]) for row in rows])
    market_brier = _mean([brier(row["market_yes"], row["outcome"]) for row in rows])
    candidate_logloss = _mean([logloss(row["variant_probability"], row["outcome"]) for row in rows])
    current_logloss = _mean([logloss(row["current_probability"], row["outcome"]) for row in rows])
    market_logloss = _mean([logloss(row["market_yes"], row["outcome"]) for row in rows])
    return {
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "candidate_logloss": candidate_logloss,
        "current_logloss": current_logloss,
        "market_logloss": market_logloss,
    }


def _with_deltas(score: dict[str, Any]) -> dict[str, Any]:
    candidate_brier = score.get("candidate_brier")
    current_brier = score.get("current_brier")
    market_brier = score.get("market_brier")
    candidate_logloss = score.get("candidate_logloss")
    current_logloss = score.get("current_logloss")
    market_logloss = score.get("market_logloss")
    return {
        **score,
        "delta_vs_current": (
            candidate_brier - current_brier
            if candidate_brier is not None and current_brier is not None
            else None
        ),
        "delta_vs_market": (
            candidate_brier - market_brier
            if candidate_brier is not None and market_brier is not None
            else None
        ),
        "logloss_delta_vs_current": (
            candidate_logloss - current_logloss
            if candidate_logloss is not None and current_logloss is not None
            else None
        ),
        "logloss_delta_vs_market": (
            candidate_logloss - market_logloss
            if candidate_logloss is not None and market_logloss is not None
            else None
        ),
    }


def _daily_first_loss(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"))].append(row)
    if not grouped:
        return _with_deltas(_loss_summary([]))
    scores = [_loss_summary(group_rows) for group_rows in grouped.values()]
    keys = (
        "candidate_brier",
        "current_brier",
        "market_brier",
        "candidate_logloss",
        "current_logloss",
        "market_logloss",
    )
    averaged = {
        key: _mean([score[key] for score in scores if score.get(key) is not None])
        for key in keys
    }
    return _with_deltas(averaged)


def score_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "market_days": 0, "snapshots": 0, "markets": 0}
    winners = [row for row in rows if int(row.get("outcome") or 0) == 1]
    daily = _daily_first_loss(rows)
    row_average = _with_deltas(_loss_summary(rows))
    return {
        "rows": len(rows),
        "markets": len({row.get("market_id") for row in rows}),
        "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
        "snapshots": len({row.get("snapshot_id") for row in rows}),
        **daily,
        "winner_candidate_probability": _mean([float(row["variant_probability"]) for row in winners]),
        "winner_current_probability": _mean([float(row["current_probability"]) for row in winners]),
        "winner_market_probability": _mean([float(row["market_yes"]) for row in winners]),
        "row_average": row_average,
    }


def rows_for_slice(rows: list[dict[str, Any]], slice_name: str) -> list[dict[str, Any]]:
    if slice_name == "exact_band_early":
        return [
            row for row in rows
            if row.get("slice_regime") == "early" and row.get("bin_type") == "eq"
        ]
    if slice_name == "settlement_distance_0_early":
        return [
            row for row in rows
            if row.get("slice_regime") == "early"
            and distance_bucket_value(row.get("settlement_distance_bucket")) == 0
        ]
    if slice_name == "one_above_early":
        return [
            row for row in rows
            if row.get("slice_regime") == "early" and row.get("signed_band_offset") == 1
        ]
    if slice_name == "one_below_early":
        return [
            row for row in rows
            if row.get("slice_regime") == "early" and row.get("signed_band_offset") == -1
        ]
    if slice_name == "adjacent_early":
        return [
            row for row in rows
            if row.get("slice_regime") == "early"
            and (
                abs(int(row.get("signed_band_offset"))) == 1
                if row.get("signed_band_offset") is not None
                else distance_bucket_value(row.get("settlement_distance_bucket")) == 1
            )
        ]
    if slice_name == "broad_early":
        return [row for row in rows if row.get("slice_regime") == "early"]
    if slice_name in {"ramp", "late", "lock_in"}:
        return [row for row in rows if row.get("slice_regime") == slice_name]
    raise ValueError(f"Unknown exact-band calibration slice: {slice_name}")


def target_status(summary: dict[str, Any], *, market_tol: float, logloss_tol: float) -> tuple[str, str]:
    if int(summary.get("rows") or 0) <= 0:
        return "BLOCK", "target slice has no candidate rows"
    delta_current = summary.get("delta_vs_current")
    delta_market = summary.get("delta_vs_market")
    logloss_current = summary.get("logloss_delta_vs_current")
    logloss_market = summary.get("logloss_delta_vs_market")
    if delta_current is None or delta_current > 0.0:
        return "BLOCK", f"target Brier does not improve current: {fmt_signed(delta_current)}"
    if delta_market is None or delta_market > float(market_tol):
        return "BLOCK", (
            f"target Brier trails market by {fmt_signed(delta_market)} "
            f"> +{float(market_tol):.4f}"
        )
    if logloss_current is None or logloss_current > 0.0:
        return "BLOCK", f"target log-loss does not improve current: {fmt_signed(logloss_current)}"
    if logloss_market is None or logloss_market > float(logloss_tol):
        return "BLOCK", (
            f"target log-loss trails market by {fmt_signed(logloss_market)} "
            f"> +{float(logloss_tol):.4f}"
        )
    return "PASS", "target clears current lift and market tolerances"


def guardrail_status(summary: dict[str, Any], *, market_tol: float, logloss_tol: float) -> tuple[str, str]:
    if int(summary.get("rows") or 0) <= 0:
        return "SPARSE", "guardrail slice has no candidate rows"
    delta_current = summary.get("delta_vs_current")
    logloss_current = summary.get("logloss_delta_vs_current")
    if delta_current is not None and delta_current > float(market_tol):
        return "BLOCK", (
            f"guardrail Brier regresses current by {fmt_signed(delta_current)} "
            f"> +{float(market_tol):.4f}"
        )
    if logloss_current is not None and logloss_current > float(logloss_tol):
        return "BLOCK", (
            f"guardrail log-loss regresses current by {fmt_signed(logloss_current)} "
            f"> +{float(logloss_tol):.4f}"
        )
    return "PASS", "guardrail does not materially regress current"


def summarize_slices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for slice_name in (*TARGET_SLICES, *GUARDRAIL_SLICES):
        output.append({
            "slice": slice_name,
            **score_summary(rows_for_slice(rows, slice_name)),
        })
    return output


def summarize_market_slices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for market_id in sorted({row.get("market_id") for row in rows if row.get("market_id")}):
        market_rows = [row for row in rows if row.get("market_id") == market_id]
        for slice_name in (*TARGET_SLICES, *GUARDRAIL_SLICES):
            output.append({
                "market_id": market_id,
                "slice": slice_name,
                **score_summary(rows_for_slice(market_rows, slice_name)),
            })
    return output


def parse_markets(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def build_payload(
    variant_rows: str | Path = DEFAULT_VARIANT_ROWS,
    *,
    required_markets: tuple[str, ...] = (),
    market_tol: float = DEFAULT_MARKET_TOL,
    logloss_tol: float = DEFAULT_LOGLOSS_TOL,
) -> dict[str, Any]:
    rows = read_variant_rows(variant_rows)
    variant_ids = sorted({str(row.get("variant_id")) for row in rows if row.get("variant_id")})
    aggregate_slices = summarize_slices(rows)
    market_slices = summarize_market_slices(rows)
    required_market_set = {market.strip().lower() for market in required_markets if market.strip()}
    blockers = []

    for item in aggregate_slices:
        is_target = item.get("slice") in TARGET_SLICES
        status, detail = (
            target_status(item, market_tol=market_tol, logloss_tol=logloss_tol)
            if is_target
            else guardrail_status(item, market_tol=market_tol, logloss_tol=logloss_tol)
        )
        item["status"] = status
        item["detail"] = detail
        if status == "BLOCK":
            blockers.append({
                "category": "target_slice" if is_target else "guardrail_slice",
                "scope": "aggregate",
                "slice": item.get("slice"),
                "detail": detail,
                "evidence": item,
            })

    for item in market_slices:
        is_target = item.get("slice") in TARGET_SLICES
        status, detail = (
            target_status(item, market_tol=market_tol, logloss_tol=logloss_tol)
            if is_target
            else guardrail_status(item, market_tol=market_tol, logloss_tol=logloss_tol)
        )
        item["status"] = status
        item["detail"] = detail
        required_market = item.get("market_id") in required_market_set
        if status == "BLOCK" and required_market:
            blockers.append({
                "category": "required_market_target_slice" if is_target else "required_market_guardrail_slice",
                "scope": "market",
                "market_id": item.get("market_id"),
                "slice": item.get("slice"),
                "detail": detail,
                "evidence": item,
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "inputs": {
            "variant_rows": str(variant_rows),
            "market_tolerance": float(market_tol),
            "logloss_tolerance": float(logloss_tol),
            "required_markets": sorted(required_market_set),
        },
        "candidate": {
            "variant_ids": variant_ids,
            "row_export_corpus_hash": candidate_rows_corpus_hash(rows),
            "uses_market_features": False,
        },
        "summary": {
            "row_count": len(rows),
            "market_count": len({row.get("market_id") for row in rows if row.get("market_id")}),
            "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
            "target_slice_block_count": sum(
                1 for blocker in blockers if "target" in str(blocker.get("category"))
            ),
            "guardrail_block_count": sum(
                1 for blocker in blockers if "guardrail" in str(blocker.get("category"))
            ),
        },
        "target_slices": list(TARGET_SLICES),
        "guardrail_slices": list(GUARDRAIL_SLICES),
        "by_slice": aggregate_slices,
        "market_slices": market_slices,
    }


def render_report(payload: dict[str, Any]) -> str:
    candidate = payload.get("candidate") or {}
    lines = [
        "# Exact-Band And Settlement-Distance-0 Candidate Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Blockers", payload.get("blocker_count", 0)],
            ["First blocker", (payload.get("first_blocker") or {}).get("detail") or "-"],
            ["Variant IDs", ", ".join(candidate.get("variant_ids") or [])],
            ["Row corpus hash", candidate.get("row_export_corpus_hash") or "-"],
            ["Required markets", ", ".join((payload.get("inputs") or {}).get("required_markets") or []) or "-"],
        ],
    )
    lines += ["", "## Aggregate Slices", ""]
    lines += markdown_table(
        [
            "Slice",
            "Rows",
            "Days",
            "Candidate",
            "Current",
            "Market",
            "Delta Current",
            "Delta Market",
            "LogLoss Delta Current",
            "LogLoss Delta Market",
            "Winner Candidate P",
            "Status",
        ],
        [
            [
                row.get("slice"),
                row.get("rows"),
                row.get("market_days"),
                fmt_num(row.get("candidate_brier")),
                fmt_num(row.get("current_brier")),
                fmt_num(row.get("market_brier")),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                fmt_signed(row.get("logloss_delta_vs_current")),
                fmt_signed(row.get("logloss_delta_vs_market")),
                fmt_num(row.get("winner_candidate_probability")),
                row.get("status"),
            ]
            for row in payload.get("by_slice") or []
        ],
    )
    lines += ["", "## Market Slices", ""]
    lines += markdown_table(
        [
            "Market",
            "Slice",
            "Rows",
            "Days",
            "Delta Current",
            "Delta Market",
            "LogLoss Delta Current",
            "LogLoss Delta Market",
            "Status",
            "Detail",
        ],
        [
            [
                row.get("market_id"),
                row.get("slice"),
                row.get("rows"),
                row.get("market_days"),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
                fmt_signed(row.get("logloss_delta_vs_current")),
                fmt_signed(row.get("logloss_delta_vs_market")),
                row.get("status"),
                row.get("detail"),
            ]
            for row in payload.get("market_slices") or []
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Category", "Scope", "Market", "Slice", "Detail"],
            [
                [
                    row.get("category"),
                    row.get("scope"),
                    row.get("market_id") or "-",
                    row.get("slice"),
                    row.get("detail"),
                ]
                for row in payload.get("blockers") or []
            ],
        )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate exact-band and settlement-distance-0 early-hour repairs.")
    parser.add_argument("--variant-rows", default=str(DEFAULT_VARIANT_ROWS))
    parser.add_argument("--required-markets", default="")
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--logloss-tol", type=float, default=DEFAULT_LOGLOSS_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        args.variant_rows,
        required_markets=parse_markets(args.required_markets),
        market_tol=args.market_tol,
        logloss_tol=args.logloss_tol,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Exact-band distance-zero gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
