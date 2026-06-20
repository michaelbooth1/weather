"""Casebook for early winner-underpricing repair targets.

This report is development evidence. It finds snapshots where the market ranked
the eventual winner well but the candidate either underweighted it or spread
probability across too many competing bands.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


SCHEMA_VERSION = "winner_underpricing_casebook_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "winner_underpricing_casebook.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "winner_underpricing_casebook_report.md"
DEFAULT_BLOCKED_MARKETS = ("austin", "los-angeles", "nyc", "san-francisco", "seattle")


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_csv_list(value: str | None, default: tuple[str, ...] = ()) -> list[str]:
    if not value:
        return list(default)
    return [item.strip() for item in str(value).split(",") if item.strip()]


def parse_capture_hour(row: dict[str, Any]) -> int | None:
    captured = str(row.get("captured_at_local") or "")
    if "T" in captured and len(captured.split("T", 1)[1]) >= 2:
        hour = safe_int(captured.split("T", 1)[1][:2])
        if hour is not None:
            return hour
    cutoff_hour = safe_int(row.get("cutoff_hour"))
    if hour_is_early_cutoff(row) and cutoff_hour is not None:
        return cutoff_hour
    return cutoff_hour


def hour_is_early_cutoff(row: dict[str, Any]) -> bool:
    return str(row.get("cutoff_regime") or "").lower() == "early"


def read_rows(paths: list[str | Path], markets: set[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for source in csv.DictReader(handle):
                market_id = source.get("market_id") or ""
                if markets and market_id not in markets:
                    continue
                target_date = source.get("target_date") or ""
                snapshot_id = source.get("snapshot_id") or ""
                probability = safe_float(source.get("probability"))
                current_probability = safe_float(source.get("current_probability"))
                market_probability = safe_float(source.get("market_yes"))
                outcome = safe_int(source.get("outcome"))
                if (
                    not market_id
                    or not target_date
                    or not snapshot_id
                    or probability is None
                    or current_probability is None
                    or market_probability is None
                    or outcome is None
                ):
                    continue
                row = dict(source)
                row.update({
                    "market_id": market_id,
                    "target_date": target_date,
                    "snapshot_id": snapshot_id,
                    "probability": float(probability),
                    "current_probability": float(current_probability),
                    "market_probability": float(market_probability),
                    "outcome": int(outcome),
                    "capture_hour": parse_capture_hour(source),
                })
                rows.append(row)
    return rows


def _snapshot_groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["market_id"], row["target_date"], row["snapshot_id"])].append(row)
    return grouped


def rank_of_row(rows: list[dict[str, Any]], target: dict[str, Any], key: str) -> int | None:
    sorted_rows = sorted(rows, key=lambda row: float(row.get(key) or 0.0), reverse=True)
    target_band = target.get("band_key")
    for index, row in enumerate(sorted_rows, start=1):
        if row.get("band_key") == target_band:
            return index
    return None


def _normalized_probabilities(rows: list[dict[str, Any]], key: str) -> list[float]:
    probabilities = [max(0.0, float(row.get(key) or 0.0)) for row in rows]
    total = sum(probabilities)
    if total <= 0:
        return []
    return [value / total for value in probabilities]


def effective_band_count(rows: list[dict[str, Any]], key: str) -> float | None:
    probabilities = _normalized_probabilities(rows, key)
    if not probabilities:
        return None
    concentration = sum(value * value for value in probabilities)
    return (1.0 / concentration) if concentration > 0 else None


def _distance_bucket_value(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text.endswith("+"):
        text = text[:-1]
    return safe_int(text)


def mass_within_distance(rows: list[dict[str, Any]], key: str, max_distance: int = 1) -> float | None:
    probabilities = _normalized_probabilities(rows, key)
    if not probabilities:
        return None
    total = 0.0
    for row, probability in zip(rows, probabilities):
        distance = _distance_bucket_value(row.get("settlement_distance_bucket"))
        if distance is not None and distance <= max_distance:
            total += probability
    return total


def _top_rows(rows: list[dict[str, Any]], key: str, limit: int = 3) -> list[dict[str, Any]]:
    output = []
    for row in sorted(rows, key=lambda item: float(item.get(key) or 0.0), reverse=True)[:limit]:
        output.append({
            "band_key": row.get("band_key"),
            "probability": float(row.get(key) or 0.0),
            "outcome": int(row.get("outcome") or 0),
            "bin_type": row.get("bin_type") or "",
            "bin_value": row.get("bin_value") or "",
            "settlement_distance_bucket": row.get("settlement_distance_bucket") or "",
            "forecast_bucket_pressure": row.get("forecast_bucket_pressure") or "",
        })
    return output


def build_cases(
    rows: list[dict[str, Any]],
    max_local_hour: int = 8,
    max_market_rank: int = 2,
    min_probability_gap: float = 0.05,
    min_rank_gap: int = 1,
    min_effective_band_gap: float = 0.50,
) -> list[dict[str, Any]]:
    cases = []
    for (market_id, target_date, snapshot_id), snapshot_rows in _snapshot_groups(rows).items():
        hours = [row.get("capture_hour") for row in snapshot_rows if row.get("capture_hour") is not None]
        capture_hour = min(hours) if hours else None
        if capture_hour is None or capture_hour > int(max_local_hour):
            continue

        candidate_effective = effective_band_count(snapshot_rows, "probability")
        market_effective = effective_band_count(snapshot_rows, "market_probability")
        candidate_adjacent = mass_within_distance(snapshot_rows, "probability")
        market_adjacent = mass_within_distance(snapshot_rows, "market_probability")
        spread_gap = (
            candidate_effective - market_effective
            if candidate_effective is not None and market_effective is not None
            else None
        )

        for winner in [row for row in snapshot_rows if int(row.get("outcome") or 0) == 1]:
            candidate_rank = rank_of_row(snapshot_rows, winner, "probability")
            market_rank = rank_of_row(snapshot_rows, winner, "market_probability")
            if market_rank is None or market_rank > int(max_market_rank):
                continue
            probability_gap = float(winner["market_probability"]) - float(winner["probability"])
            rank_gap = (candidate_rank - market_rank) if candidate_rank is not None else None
            qualifies = probability_gap >= float(min_probability_gap)
            qualifies = qualifies or (rank_gap is not None and rank_gap >= int(min_rank_gap))
            qualifies = qualifies or (spread_gap is not None and spread_gap >= float(min_effective_band_gap))
            if not qualifies:
                continue
            cases.append({
                "market_id": market_id,
                "target_date": target_date,
                "snapshot_id": snapshot_id,
                "captured_at_local": winner.get("captured_at_local") or "",
                "capture_hour": capture_hour,
                "winner_band_key": winner.get("band_key"),
                "winner_bin_type": winner.get("bin_type") or "",
                "winner_bin_value": winner.get("bin_value") or "",
                "winner_candidate_probability": float(winner["probability"]),
                "winner_current_probability": float(winner["current_probability"]),
                "winner_market_probability": float(winner["market_probability"]),
                "winner_probability_gap_vs_market": probability_gap,
                "winner_probability_gap_vs_current": float(winner["probability"]) - float(winner["current_probability"]),
                "winner_candidate_rank": candidate_rank,
                "winner_market_rank": market_rank,
                "winner_rank_gap_vs_market": rank_gap,
                "candidate_effective_bands": candidate_effective,
                "market_effective_bands": market_effective,
                "effective_band_gap_vs_market": spread_gap,
                "candidate_adjacent_mass": candidate_adjacent,
                "market_adjacent_mass": market_adjacent,
                "adjacent_mass_gap_vs_market": (
                    candidate_adjacent - market_adjacent
                    if candidate_adjacent is not None and market_adjacent is not None
                    else None
                ),
                "source_freshness_state": winner.get("source_freshness_state") or "",
                "forecast_bucket_pressure": winner.get("forecast_bucket_pressure") or "",
                "forecast_disagreement_bucket": winner.get("forecast_disagreement_bucket") or "",
                "forecast_source_count_bucket": winner.get("forecast_source_count_bucket") or "",
                "settlement_distance_bucket": winner.get("settlement_distance_bucket") or "",
                "top_candidate_bands": _top_rows(snapshot_rows, "probability"),
                "top_market_bands": _top_rows(snapshot_rows, "market_probability"),
            })

    cases.sort(key=lambda row: (
        row.get("winner_probability_gap_vs_market") or 0.0,
        row.get("winner_rank_gap_vs_market") or 0,
        row.get("effective_band_gap_vs_market") or 0.0,
    ), reverse=True)
    return cases


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_market[case["market_id"]].append(case)

    def average(items: list[float]) -> float | None:
        return sum(items) / len(items) if items else None

    market_rows = []
    for market_id, market_cases in sorted(by_market.items()):
        market_rows.append({
            "market_id": market_id,
            "cases": len(market_cases),
            "target_dates": sorted({case["target_date"] for case in market_cases}),
            "avg_winner_probability_gap_vs_market": average([
                float(case["winner_probability_gap_vs_market"]) for case in market_cases
            ]),
            "avg_winner_rank_gap_vs_market": average([
                float(case["winner_rank_gap_vs_market"])
                for case in market_cases
                if case.get("winner_rank_gap_vs_market") is not None
            ]),
            "avg_effective_band_gap_vs_market": average([
                float(case["effective_band_gap_vs_market"])
                for case in market_cases
                if case.get("effective_band_gap_vs_market") is not None
            ]),
        })
    return {
        "case_count": len(cases),
        "markets": sorted(by_market),
        "market_summary": market_rows,
        "pattern_summary": build_pattern_summary(by_market),
    }


def _pattern_key_value(case: dict[str, Any], field: str) -> Any:
    if field == "winner_band_key":
        return case.get("winner_band_key")
    return case.get(field)


def build_pattern_summary(
    by_market: dict[str, list[dict[str, Any]]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    fields = [
        "forecast_bucket_pressure",
        "forecast_disagreement_bucket",
        "source_freshness_state",
        "capture_hour",
        "winner_band_key",
        "winner_bin_type",
    ]

    def average(items: list[float]) -> float | None:
        return sum(items) / len(items) if items else None

    rows: list[dict[str, Any]] = []
    for market_id, market_cases in sorted(by_market.items()):
        for field in fields:
            by_value: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for case in market_cases:
                value = _pattern_key_value(case, field)
                value_text = str(value) if value not in (None, "") else "missing"
                by_value[value_text].append(case)
            ranked = sorted(
                by_value.items(),
                key=lambda item: (
                    len(item[1]),
                    average([
                        float(case["winner_probability_gap_vs_market"])
                        for case in item[1]
                        if case.get("winner_probability_gap_vs_market") is not None
                    ]) or 0.0,
                    item[0],
                ),
                reverse=True,
            )
            for value, value_cases in ranked[: max(0, int(top_n))]:
                rows.append({
                    "market_id": market_id,
                    "field": field,
                    "value": value,
                    "cases": len(value_cases),
                    "share": len(value_cases) / len(market_cases) if market_cases else None,
                    "avg_winner_probability_gap_vs_market": average([
                        float(case["winner_probability_gap_vs_market"])
                        for case in value_cases
                        if case.get("winner_probability_gap_vs_market") is not None
                    ]),
                    "avg_winner_rank_gap_vs_market": average([
                        float(case["winner_rank_gap_vs_market"])
                        for case in value_cases
                        if case.get("winner_rank_gap_vs_market") is not None
                    ]),
                    "avg_effective_band_gap_vs_market": average([
                        float(case["effective_band_gap_vs_market"])
                        for case in value_cases
                        if case.get("effective_band_gap_vs_market") is not None
                    ]),
                })
    return rows


def build_payload(
    rows_paths: list[str | Path],
    markets: list[str] | None = None,
    max_local_hour: int = 8,
    max_market_rank: int = 2,
    min_probability_gap: float = 0.05,
    min_rank_gap: int = 1,
    min_effective_band_gap: float = 0.50,
    limit: int = 40,
) -> dict[str, Any]:
    market_set = set(markets or [])
    rows = read_rows(rows_paths, markets=market_set or None)
    cases = build_cases(
        rows,
        max_local_hour=max_local_hour,
        max_market_rank=max_market_rank,
        min_probability_gap=min_probability_gap,
        min_rank_gap=min_rank_gap,
        min_effective_band_gap=min_effective_band_gap,
    )
    limited_cases = cases[: max(0, int(limit))]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "row_count": len(rows),
        "evidence_classification": "development_casebook_not_promotion_evidence",
        "filters": {
            "markets": sorted(market_set) if market_set else [],
            "max_local_hour": int(max_local_hour),
            "max_market_rank": int(max_market_rank),
            "min_probability_gap": float(min_probability_gap),
            "min_rank_gap": int(min_rank_gap),
            "min_effective_band_gap": float(min_effective_band_gap),
            "limit": int(limit),
        },
        "summary": summarize_cases(cases),
        "cases": limited_cases,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _summary_rows(summary: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in summary.get("market_summary") or []:
        rows.append([
            item.get("market_id"),
            item.get("cases"),
            ", ".join(item.get("target_dates") or []),
            fmt_signed(item.get("avg_winner_probability_gap_vs_market")),
            fmt_num(item.get("avg_winner_rank_gap_vs_market")),
            fmt_num(item.get("avg_effective_band_gap_vs_market")),
        ])
    return rows


def _case_rows(cases: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for case in cases:
        top_candidate = ", ".join(
            f"{row.get('band_key')}={fmt_num(row.get('probability'))}"
            for row in (case.get("top_candidate_bands") or [])[:3]
        )
        top_market = ", ".join(
            f"{row.get('band_key')}={fmt_num(row.get('probability'))}"
            for row in (case.get("top_market_bands") or [])[:3]
        )
        rows.append([
            case.get("market_id"),
            case.get("target_date"),
            case.get("capture_hour"),
            case.get("winner_band_key"),
            fmt_num(case.get("winner_candidate_probability")),
            fmt_num(case.get("winner_market_probability")),
            fmt_signed(case.get("winner_probability_gap_vs_market")),
            case.get("winner_candidate_rank"),
            case.get("winner_market_rank"),
            fmt_num(case.get("candidate_effective_bands")),
            fmt_num(case.get("market_effective_bands")),
            case.get("forecast_bucket_pressure"),
            case.get("forecast_disagreement_bucket"),
            case.get("source_freshness_state"),
            top_candidate,
            top_market,
        ])
    return rows


def _pattern_rows(summary: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in summary.get("pattern_summary") or []:
        rows.append([
            item.get("market_id"),
            item.get("field"),
            item.get("value"),
            item.get("cases"),
            fmt_num(item.get("share")),
            fmt_signed(item.get("avg_winner_probability_gap_vs_market")),
            fmt_num(item.get("avg_winner_rank_gap_vs_market")),
            fmt_num(item.get("avg_effective_band_gap_vs_market")),
        ])
    return rows


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    summary = payload.get("summary") or {}
    lines = [
        "# Winner Underpricing Casebook",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Evidence classification: development casebook, not promotion evidence.",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Rows scanned", payload.get("row_count")],
            ["Cases found", summary.get("case_count")],
            ["Markets", ", ".join(summary.get("markets") or []) or "-"],
            ["Filters", json.dumps(payload.get("filters") or {}, sort_keys=True)],
        ],
    )
    lines += [
        "",
        "## By Market",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Cases",
            "Target Dates",
            "Avg Winner Gap",
            "Avg Rank Gap",
            "Avg Spread Gap",
        ],
        _summary_rows(summary),
    )
    lines += [
        "",
        "## Dominant Patterns",
        "",
        "All rows in this section are computed from every detected case, not only the displayed case limit.",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Field",
            "Value",
            "Cases",
            "Share",
            "Avg Winner Gap",
            "Avg Rank Gap",
            "Avg Spread Gap",
        ],
        _pattern_rows(summary),
    )
    lines += [
        "",
        "## Cases",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Date",
            "Hour",
            "Winner",
            "Candidate P",
            "Market P",
            "Gap",
            "Candidate Rank",
            "Market Rank",
            "Candidate Eff Bands",
            "Market Eff Bands",
            "Forecast Pressure",
            "Disagreement",
            "Source State",
            "Top Candidate",
            "Top Market",
        ],
        _case_rows(payload.get("cases") or []),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a winner-underpricing casebook from variant row exports.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports.")
    parser.add_argument("--markets", default=",".join(DEFAULT_BLOCKED_MARKETS))
    parser.add_argument("--max-local-hour", type=int, default=8)
    parser.add_argument("--max-market-rank", type=int, default=2)
    parser.add_argument("--min-probability-gap", type=float, default=0.05)
    parser.add_argument("--min-rank-gap", type=int, default=1)
    parser.add_argument("--min-effective-band-gap", type=float, default=0.50)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_payload(
        rows_paths=args.rows,
        markets=parse_csv_list(args.markets),
        max_local_hour=args.max_local_hour,
        max_market_rank=args.max_market_rank,
        min_probability_gap=args.min_probability_gap,
        min_rank_gap=args.min_rank_gap,
        min_effective_band_gap=args.min_effective_band_gap,
        limit=args.limit,
    )
    out_path = write_json(args.out, payload)
    report_path = write_markdown_report(args.report, payload)
    print(
        f"Winner-underpricing casebook: "
        f"{(payload.get('summary') or {}).get('case_count', 0)} cases"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
