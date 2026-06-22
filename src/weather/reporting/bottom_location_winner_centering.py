"""Bottom-location early/midday winner-centering candidate gate."""

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
from weather.reporting.predawn_weak_slot_repair import weak_slots_from_report
from weather.reporting.ten_minute_model_performance import slot_label
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("bottom_location_winner_centering")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_VARIANT_ROWS = DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv"
DEFAULT_TEN_MINUTE_REPORT = DEFAULT_BACKTEST_ROOT / "ten_minute_model_performance.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "bottom_location_winner_centering.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "bottom_location_winner_centering_report.md"
DEFAULT_BOTTOM_MARKETS = ("seattle", "nyc", "miami")
DEFAULT_MARKET_TOL = 0.003
DEFAULT_LOGLOSS_TOL = 0.010
REQUIRED_SLICES = ("weak_slot", "early", "midday")
GUARDRAIL_SLICES = ("late", "lock_in")


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


def parse_time_slot(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return ((parsed.hour * 60) + parsed.minute) // 10 * 10


def inferred_regime(row: dict[str, Any]) -> str:
    regime = str(row.get("cutoff_regime") or "").strip().lower()
    if regime:
        return regime
    slot = row.get("time_slot_minute")
    if slot is None:
        return "unknown"
    hour = int(slot) // 60
    if hour <= 8:
        return "early"
    if hour <= 14:
        return "midday"
    if hour <= 19:
        return "late"
    return "lock_in"


def band_value(row: dict[str, Any]) -> float | None:
    value = safe_float(row.get("bin_value") or row.get("bin_value_c"))
    if value is not None:
        return value
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(row.get("band_key") or ""))
    return safe_float(match.group(0)) if match else None


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
                "current_probability": current,
                "market_yes": market,
                "outcome": int(outcome),
                "time_slot_minute": parse_time_slot(source.get("captured_at_local")),
                "bin_value_numeric": band_value(source),
            }
            row["slice_regime"] = inferred_regime(row)
            rows.append(row)
    return rows


def logloss(probability: float, outcome: int) -> float:
    probability = max(1e-15, min(1.0 - 1e-15, float(probability)))
    return -(int(outcome) * math.log(probability) + (1 - int(outcome)) * math.log(1.0 - probability))


def brier(probability: float, outcome: int) -> float:
    return (float(probability) - int(outcome)) ** 2


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _normalized(rows: list[dict[str, Any]], key: str) -> list[float]:
    total = sum(max(0.0, float(row.get(key) or 0.0)) for row in rows)
    if total <= 0:
        return []
    return [max(0.0, float(row.get(key) or 0.0)) / total for row in rows]


def effective_band_count(rows: list[dict[str, Any]], key: str) -> float | None:
    values = _normalized(rows, key)
    if not values:
        return None
    concentration = sum(value * value for value in values)
    return 1.0 / concentration if concentration > 0 else None


def adjacent_winner_mass(rows: list[dict[str, Any]], key: str, max_distance: float = 1.0) -> float | None:
    values = _normalized(rows, key)
    if not values:
        return None
    winners = [
        row.get("bin_value_numeric")
        for row in rows
        if int(row.get("outcome") or 0) == 1 and row.get("bin_value_numeric") is not None
    ]
    if not winners:
        return None
    total = 0.0
    for row, probability in zip(rows, values):
        value = row.get("bin_value_numeric")
        if value is not None and any(abs(float(value) - float(winner)) <= max_distance for winner in winners):
            total += probability
    return total


def partition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"), row.get("snapshot_id"))].append(row)
    candidate_eff = []
    current_eff = []
    market_eff = []
    candidate_adjacent = []
    current_adjacent = []
    market_adjacent = []
    for group in grouped.values():
        candidate_eff.append(effective_band_count(group, "probability"))
        current_eff.append(effective_band_count(group, "current_probability"))
        market_eff.append(effective_band_count(group, "market_yes"))
        candidate_adjacent.append(adjacent_winner_mass(group, "probability"))
        current_adjacent.append(adjacent_winner_mass(group, "current_probability"))
        market_adjacent.append(adjacent_winner_mass(group, "market_yes"))
    candidate_eff_mean = _mean([value for value in candidate_eff if value is not None])
    current_eff_mean = _mean([value for value in current_eff if value is not None])
    market_eff_mean = _mean([value for value in market_eff if value is not None])
    candidate_adjacent_mean = _mean([value for value in candidate_adjacent if value is not None])
    current_adjacent_mean = _mean([value for value in current_adjacent if value is not None])
    market_adjacent_mean = _mean([value for value in market_adjacent if value is not None])
    return {
        "partition_snapshots": len(grouped),
        "candidate_effective_bands": candidate_eff_mean,
        "current_effective_bands": current_eff_mean,
        "market_effective_bands": market_eff_mean,
        "effective_band_delta_vs_current": (
            candidate_eff_mean - current_eff_mean
            if candidate_eff_mean is not None and current_eff_mean is not None
            else None
        ),
        "effective_band_delta_vs_market": (
            candidate_eff_mean - market_eff_mean
            if candidate_eff_mean is not None and market_eff_mean is not None
            else None
        ),
        "candidate_adjacent_winner_mass": candidate_adjacent_mean,
        "current_adjacent_winner_mass": current_adjacent_mean,
        "market_adjacent_winner_mass": market_adjacent_mean,
        "adjacent_winner_mass_delta_vs_current": (
            candidate_adjacent_mean - current_adjacent_mean
            if candidate_adjacent_mean is not None and current_adjacent_mean is not None
            else None
        ),
        "adjacent_winner_mass_delta_vs_market": (
            candidate_adjacent_mean - market_adjacent_mean
            if candidate_adjacent_mean is not None and market_adjacent_mean is not None
            else None
        ),
    }


def score_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0}
    winners = [row for row in rows if int(row.get("outcome") or 0) == 1]
    candidate_brier = _mean([brier(row["probability"], row["outcome"]) for row in rows])
    current_brier = _mean([brier(row["current_probability"], row["outcome"]) for row in rows])
    market_brier = _mean([brier(row["market_yes"], row["outcome"]) for row in rows])
    candidate_logloss = _mean([logloss(row["probability"], row["outcome"]) for row in rows])
    current_logloss = _mean([logloss(row["current_probability"], row["outcome"]) for row in rows])
    market_logloss = _mean([logloss(row["market_yes"], row["outcome"]) for row in rows])
    return {
        "rows": len(rows),
        "markets": len({row.get("market_id") for row in rows}),
        "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
        "snapshots": len({row.get("snapshot_id") for row in rows}),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": candidate_brier - current_brier if candidate_brier is not None else None,
        "delta_vs_market": candidate_brier - market_brier if candidate_brier is not None else None,
        "candidate_logloss": candidate_logloss,
        "current_logloss": current_logloss,
        "market_logloss": market_logloss,
        "logloss_delta_vs_current": (
            candidate_logloss - current_logloss if candidate_logloss is not None else None
        ),
        "logloss_delta_vs_market": (
            candidate_logloss - market_logloss if candidate_logloss is not None else None
        ),
        "winner_candidate_probability": _mean([row["probability"] for row in winners]),
        "winner_current_probability": _mean([row["current_probability"] for row in winners]),
        "winner_market_probability": _mean([row["market_yes"] for row in winners]),
        **partition_summary(rows),
    }


def slice_rows(rows: list[dict[str, Any]], slice_name: str, weak_slots: set[int]) -> list[dict[str, Any]]:
    if slice_name == "weak_slot":
        return [row for row in rows if row.get("time_slot_minute") in weak_slots]
    return [row for row in rows if row.get("slice_regime") == slice_name]


def summarize_market_slices(
    rows: list[dict[str, Any]],
    markets: tuple[str, ...],
    weak_slots: set[int],
) -> list[dict[str, Any]]:
    output = []
    for market_id in markets:
        market_rows = [row for row in rows if row.get("market_id") == market_id]
        for slice_name in (*REQUIRED_SLICES, *GUARDRAIL_SLICES):
            summary = score_summary(slice_rows(market_rows, slice_name, weak_slots))
            output.append({
                "market_id": market_id,
                "slice": slice_name,
                **summary,
            })
    return output


def gate_status(summary: dict[str, Any], *, market_tol: float, logloss_tol: float, required: bool) -> tuple[str, str]:
    if int(summary.get("rows") or 0) <= 0:
        return ("BLOCK" if required else "SPARSE", "slice has no candidate rows")
    delta_current = summary.get("delta_vs_current")
    delta_market = summary.get("delta_vs_market")
    logloss_market = summary.get("logloss_delta_vs_market")
    if required:
        if delta_current is None or delta_current > 0.0:
            return "BLOCK", f"candidate does not improve current Brier: {fmt_signed(delta_current)}"
        if delta_market is None or delta_market > float(market_tol):
            return "BLOCK", (
                f"candidate trails market Brier by {fmt_signed(delta_market)} "
                f"> +{float(market_tol):.4f}"
            )
        if logloss_market is None or logloss_market > float(logloss_tol):
            return "BLOCK", (
                f"candidate trails market log-loss by {fmt_signed(logloss_market)} "
                f"> +{float(logloss_tol):.4f}"
            )
        return "PASS", "required slice clears current, market, and log-loss tolerances"
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


def build_payload(
    variant_rows: str | Path = DEFAULT_VARIANT_ROWS,
    ten_minute_report: str | Path = DEFAULT_TEN_MINUTE_REPORT,
    *,
    bottom_markets: tuple[str, ...] = DEFAULT_BOTTOM_MARKETS,
    market_tol: float = DEFAULT_MARKET_TOL,
    logloss_tol: float = DEFAULT_LOGLOSS_TOL,
) -> dict[str, Any]:
    markets = tuple(str(market).strip().lower() for market in bottom_markets if str(market).strip())
    weak_slots = weak_slots_from_report(ten_minute_report)
    rows = read_variant_rows(variant_rows)
    variant_ids = sorted({str(row.get("variant_id")) for row in rows if row.get("variant_id")})
    bottom_rows = [row for row in rows if row.get("market_id") in markets]
    market_slices = summarize_market_slices(bottom_rows, markets, weak_slots)
    blockers = []
    for item in market_slices:
        required = item.get("slice") in REQUIRED_SLICES
        status, detail = gate_status(
            item,
            market_tol=market_tol,
            logloss_tol=logloss_tol,
            required=required,
        )
        item["status"] = status
        item["detail"] = detail
        if status == "BLOCK":
            blockers.append({
                "category": (
                    "required_bottom_location_slice"
                    if required
                    else "bottom_location_guardrail"
                ),
                "market_id": item.get("market_id"),
                "slice": item.get("slice"),
                "detail": detail,
                "evidence": item,
            })
    by_slice = []
    for slice_name in (*REQUIRED_SLICES, *GUARDRAIL_SLICES):
        by_slice.append({
            "slice": slice_name,
            **score_summary(slice_rows(bottom_rows, slice_name, weak_slots)),
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
            "ten_minute_report": str(ten_minute_report),
            "market_tolerance": float(market_tol),
            "logloss_tolerance": float(logloss_tol),
        },
        "candidate": {
            "variant_ids": variant_ids,
            "row_export_corpus_hash": candidate_rows_corpus_hash(rows),
            "uses_market_features": False,
        },
        "bottom_markets": list(markets),
        "weak_slots": {
            "slot_minutes": sorted(weak_slots),
            "slot_labels": [slot_label(slot) for slot in sorted(weak_slots)],
        },
        "summary": {
            "row_count": len(rows),
            "bottom_row_count": len(bottom_rows),
            "bottom_markets": list(markets),
            "required_slice_count": len(markets) * len(REQUIRED_SLICES),
            "required_slice_block_count": sum(
                1 for blocker in blockers if blocker.get("category") == "required_bottom_location_slice"
            ),
            "guardrail_block_count": sum(
                1 for blocker in blockers if blocker.get("category") == "bottom_location_guardrail"
            ),
        },
        "by_slice": by_slice,
        "market_slices": market_slices,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Bottom-Location Winner-Centering Candidate Gate",
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
            ["Variant IDs", ", ".join((payload.get("candidate") or {}).get("variant_ids") or [])],
            ["Bottom markets", ", ".join(payload.get("bottom_markets") or [])],
            ["Weak slots", ", ".join((payload.get("weak_slots") or {}).get("slot_labels") or [])],
        ],
    )
    lines += ["", "## Bottom Slices", ""]
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
            "Winner Candidate P",
            "Winner Current P",
            "Adjacent Delta",
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
                fmt_num(row.get("winner_candidate_probability")),
                fmt_num(row.get("winner_current_probability")),
                fmt_signed(row.get("adjacent_winner_mass_delta_vs_current")),
            ]
            for row in payload.get("by_slice") or []
        ],
    )
    lines += ["", "## Market Gates", ""]
    lines += markdown_table(
        [
            "Market",
            "Slice",
            "Rows",
            "Days",
            "Delta Current",
            "Delta Market",
            "LogLoss Delta Market",
            "Winner Candidate P",
            "Winner Current P",
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
                fmt_signed(row.get("logloss_delta_vs_market")),
                fmt_num(row.get("winner_candidate_probability")),
                fmt_num(row.get("winner_current_probability")),
                row.get("status"),
                row.get("detail"),
            ]
            for row in payload.get("market_slices") or []
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Category", "Market", "Slice", "Detail"],
            [
                [
                    row.get("category"),
                    row.get("market_id"),
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


def parse_markets(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_BOTTOM_MARKETS
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate bottom-location early/midday winner-centering repairs.")
    parser.add_argument("--variant-rows", default=str(DEFAULT_VARIANT_ROWS))
    parser.add_argument("--ten-minute-report", default=str(DEFAULT_TEN_MINUTE_REPORT))
    parser.add_argument("--bottom-markets", default=",".join(DEFAULT_BOTTOM_MARKETS))
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--logloss-tol", type=float, default=DEFAULT_LOGLOSS_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        args.variant_rows,
        args.ten_minute_report,
        bottom_markets=parse_markets(args.bottom_markets),
        market_tol=args.market_tol,
        logloss_tol=args.logloss_tol,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Bottom-location winner-centering gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
