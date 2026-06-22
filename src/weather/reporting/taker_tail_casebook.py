"""Tail-loss casebook and calibration report for taker runs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.market.taker_bot import (
    DEFAULT_LABELS_CSV,
    bool_value,
    compact_float,
    current_high_band_distance,
    load_settlement_labels,
    market_local_time,
    market_modal_contexts,
    maybe_float,
    modal_context_for_row,
    read_order_rows,
    score_orders_against_labels,
    sum_field,
)
from weather.paths import data_path


SCHEMA_VERSION = "taker_tail_casebook_v0.1"
DEFAULT_DATA_ROOT = data_path()
DEFAULT_TAKER_RUNS_ROOT = DEFAULT_DATA_ROOT / "taker_runs"
DEFAULT_BACKTEST_ROOT = DEFAULT_DATA_ROOT / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "taker_tail_casebook.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "taker_tail_casebook_report.md"
DEFAULT_RUN_FOLDERS = [
    DEFAULT_TAKER_RUNS_ROOT / "2026-06-20" / "taker-20260620-3d3450f0",
    DEFAULT_TAKER_RUNS_ROOT / "2026-06-21" / "taker-20260621-bbe63642",
]


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _orders_path(path):
    path = Path(path)
    return path / "orders_long.csv" if path.is_dir() else path


def _read_order_sources(paths):
    rows = []
    for raw_path in paths or []:
        order_path = _orders_path(raw_path)
        for row in read_order_rows(order_path):
            out = dict(row)
            out["_source_orders_path"] = str(order_path)
            out["_source_run"] = str(order_path.parent)
            rows.append(out)
    return rows


def discover_run_sources(runs_root=DEFAULT_TAKER_RUNS_ROOT, *, target_date=None, max_runs=None):
    root = Path(runs_root)
    if target_date:
        candidates = sorted((root / str(target_date)).glob("*/orders_long.csv"))
    else:
        candidates = sorted(root.glob("*/*/orders_long.csv"))
    paths = [path.parent for path in candidates if path.exists()]
    paths = sorted(paths, key=lambda item: item.stat().st_mtime if item.exists() else 0)
    if max_runs:
        paths = paths[-int(max_runs):]
    return paths


def build_tail_casebook_from_paths(
    run_paths,
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    generated_at_utc=None,
):
    runs = [Path(item) for item in run_paths or []]
    labels = load_settlement_labels(labels_csv)
    return build_tail_casebook(
        _read_order_sources(runs),
        labels=labels,
        source_runs=runs,
        generated_at_utc=generated_at_utc or utc_iso(),
    )


def _tail_types(row):
    types = []
    if bool_value(row.get("low_price_tail"), False):
        types.append("low_price_tail")
    if bool_value(row.get("market_centered_warm_tail"), False):
        types.append("market_centered_warm_tail")
    return types


def _annotate_legacy_tail_fields(rows, *, tail_price_threshold=0.05):
    contexts = market_modal_contexts(rows)
    annotated = []
    for row in rows or []:
        out = dict(row)
        if out.get("low_price_tail") in (None, ""):
            best_ask = maybe_float(out.get("best_ask"))
            out["low_price_tail"] = bool(best_ask is not None and best_ask <= tail_price_threshold)
        modal = modal_context_for_row(
            out,
            contexts,
            config={"market_centered_warm_tail_min_distance": 1.0},
        )
        for key, value in modal.items():
            if out.get(key) in (None, ""):
                out[key] = value
        annotated.append(out)
    return annotated


def _settlement_result(row):
    outcome = maybe_float(row.get("settlement_outcome"))
    pnl = maybe_float(row.get("settlement_pnl_usdc"))
    if outcome == 1.0:
        return "win"
    if outcome == 0.0:
        return "loss"
    if pnl is not None:
        return "win" if pnl >= 0 else "loss"
    return "unsettled"


def _bucket_number(value, cuts, labels):
    number = maybe_float(value)
    if number is None:
        return "missing"
    for cut, label in zip(cuts, labels):
        if number <= cut:
            return label
    return labels[-1]


def _case_row(row):
    local, _zone = market_local_time(row)
    distance = maybe_float(row.get("current_high_band_distance"))
    if distance is None:
        distance = current_high_band_distance(row)
    best_ask = maybe_float(row.get("best_ask"))
    fair = maybe_float(row.get("fair_probability"))
    edge = maybe_float(row.get("edge"))
    if edge is None and best_ask is not None and fair is not None:
        edge = fair - best_ask
    tail_types = _tail_types(row)
    settlement_result = _settlement_result(row)
    fill_notional = maybe_float(row.get("fill_notional_usdc")) or 0.0
    settlement_pnl = maybe_float(row.get("settlement_pnl_usdc"))
    return {
        "run_id": row.get("run_id") or "",
        "source_run": row.get("_source_run") or "",
        "target_date": row.get("target_date") or "",
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "local_hour": local.hour if local else None,
        "range_label": row.get("range_label") or "",
        "tail_type": "+".join(tail_types),
        "low_price_tail": bool_value(row.get("low_price_tail"), False),
        "market_centered_warm_tail": bool_value(row.get("market_centered_warm_tail"), False),
        "current_high_band_distance": compact_float(distance),
        "model_probability": compact_float(fair),
        "market_price": compact_float(best_ask),
        "edge": compact_float(edge),
        "market_modal_band_key": row.get("market_modal_band_key") or "",
        "market_modal_probability": compact_float(row.get("market_modal_probability")),
        "market_modal_band_distance": compact_float(row.get("market_modal_band_distance")),
        "source_freshness_state": row.get("source_freshness_state") or "",
        "current_high_trusted": bool_value(row.get("current_high_trusted"), True),
        "settlement_result": settlement_result,
        "settlement_outcome": compact_float(row.get("settlement_outcome")),
        "settlement_pnl_usdc": compact_float(settlement_pnl),
        "mark_to_market_pnl_usdc": compact_float(row.get("mark_pnl_usdc")),
        "net_pnl_usdc": compact_float(row.get("net_pnl_usdc")),
        "fill_notional_usdc": compact_float(fill_notional),
        "slice_key": "|".join([
            "+".join(tail_types),
            row.get("market_id") or "unknown_market",
            f"hour:{local.hour if local else 'missing'}",
            f"distance:{_bucket_number(distance, [0, 1, 3], ['0', '1', '2-3', 'gt3'])}",
            f"price:{_bucket_number(best_ask, [0.01, 0.03, 0.05, 0.10], ['le_0.01', 'le_0.03', 'le_0.05', 'le_0.10', 'gt_0.10'])}",
            f"source:{row.get('source_freshness_state') or 'unknown'}",
        ]),
    }


def _aggregate_cases(cases, key_name):
    buckets = defaultdict(lambda: {
        key_name: "",
        "fill_count": 0,
        "settled_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "spent_usdc": 0.0,
        "settlement_pnl_usdc": 0.0,
        "model_probability_sum": 0.0,
        "market_price_sum": 0.0,
    })
    for case in cases:
        key = case.get(key_name) or "unknown"
        bucket = buckets[key]
        bucket[key_name] = key
        bucket["fill_count"] += 1
        bucket["spent_usdc"] += maybe_float(case.get("fill_notional_usdc")) or 0.0
        bucket["settlement_pnl_usdc"] += maybe_float(case.get("settlement_pnl_usdc")) or 0.0
        bucket["model_probability_sum"] += maybe_float(case.get("model_probability")) or 0.0
        bucket["market_price_sum"] += maybe_float(case.get("market_price")) or 0.0
        if case.get("settlement_result") in {"win", "loss"}:
            bucket["settled_count"] += 1
        if case.get("settlement_result") == "win":
            bucket["win_count"] += 1
        if case.get("settlement_result") == "loss":
            bucket["loss_count"] += 1
    rows = []
    for value in buckets.values():
        fill_count = value["fill_count"]
        settled_count = value["settled_count"]
        win_rate = value["win_count"] / settled_count if settled_count else None
        avg_model = value["model_probability_sum"] / fill_count if fill_count else None
        avg_price = value["market_price_sum"] / fill_count if fill_count else None
        rows.append({
            key_name: value[key_name],
            "fill_count": fill_count,
            "settled_count": settled_count,
            "win_count": value["win_count"],
            "loss_count": value["loss_count"],
            "settlement_win_rate": compact_float(win_rate),
            "avg_model_probability": compact_float(avg_model),
            "avg_market_price": compact_float(avg_price),
            "avg_model_minus_settlement_win_rate": compact_float(
                avg_model - win_rate if avg_model is not None and win_rate is not None else None
            ),
            "spent_usdc": round(value["spent_usdc"], 6),
            "settlement_pnl_usdc": round(value["settlement_pnl_usdc"], 6),
        })
    return sorted(rows, key=lambda item: (-item["loss_count"], item[key_name]))


def build_tail_casebook(order_rows, labels=None, *, source_runs=None, generated_at_utc=None):
    labels = labels or {"by_event_slug": {}, "by_market_date": {}}
    scored_rows, score_summary = score_orders_against_labels(order_rows, labels)
    scored_rows = _annotate_legacy_tail_fields(scored_rows)
    filled_tail_rows = [
        row for row in scored_rows
        if str(row.get("order_status") or "").upper() == "FILLED"
        and _tail_types(row)
    ]
    cases = [_case_row(row) for row in filled_tail_rows]
    losing_cases = [case for case in cases if case.get("settlement_result") == "loss"]
    by_tail_type = _aggregate_cases(cases, "tail_type")
    by_slice = _aggregate_cases(cases, "slice_key")
    no_go_candidates = [
        {
            **row,
            "candidate_action": "block_until_repeated_settlement_positive_oos",
        }
        for row in by_slice
        if row["loss_count"] > 0 and row["win_count"] == 0
    ]
    summary = {
        "status": "BLOCK_BAD_TAIL_SLICES" if no_go_candidates else "PASS",
        "source_runs": [str(item) for item in (source_runs or [])],
        "order_row_count": len(order_rows or []),
        "scored_order_row_count": len(scored_rows),
        "tail_fill_count": len(cases),
        "losing_tail_fill_count": len(losing_cases),
        "low_price_tail_fill_count": sum(1 for case in cases if case["low_price_tail"]),
        "warm_tail_fill_count": sum(1 for case in cases if case["market_centered_warm_tail"]),
        "tail_spent_usdc": sum_field(cases, "fill_notional_usdc"),
        "tail_settlement_pnl_usdc": sum_field(cases, "settlement_pnl_usdc"),
        "no_go_candidate_count": len(no_go_candidates),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "summary": summary,
        "score_summary": score_summary,
        "by_tail_type": by_tail_type,
        "by_slice": by_slice,
        "no_go_candidates": no_go_candidates,
        "cases": cases,
    }


def _fmt(value):
    if value in (None, ""):
        return "-"
    return str(value)


def _table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(row.get(header)) for header in headers) + " |")
    return "\n".join(lines)


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Taker Tail Casebook",
        "",
        f"Status: **{summary.get('status')}**",
        "",
        "## Summary",
        "",
        _table(
            ["tail_fill_count", "losing_tail_fill_count", "low_price_tail_fill_count", "warm_tail_fill_count", "tail_settlement_pnl_usdc", "no_go_candidate_count"],
            [summary],
        ),
        "",
        "## Tail Calibration",
        "",
        _table(
            ["tail_type", "fill_count", "settled_count", "win_count", "loss_count", "settlement_win_rate", "avg_model_probability", "avg_market_price", "avg_model_minus_settlement_win_rate", "settlement_pnl_usdc"],
            payload.get("by_tail_type") or [],
        ),
        "",
        "## No-Go Candidates",
        "",
        _table(
            ["slice_key", "fill_count", "settled_count", "win_count", "loss_count", "spent_usdc", "settlement_pnl_usdc", "candidate_action"],
            (payload.get("no_go_candidates") or [])[:25],
        ),
        "",
        "## Losing Tail Cases",
        "",
        _table(
            ["target_date", "market_id", "local_hour", "range_label", "tail_type", "current_high_band_distance", "model_probability", "market_price", "market_modal_band_distance", "source_freshness_state", "settlement_pnl_usdc", "slice_key"],
            [case for case in payload.get("cases") or [] if case.get("settlement_result") == "loss"][:50],
        ),
        "",
    ]
    return "\n".join(lines)


def write_outputs(payload, json_out=None, report_out=None):
    if json_out:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report_out:
        path = Path(report_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_report(payload), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", dest="runs", help="Run folder or orders_long.csv path. Repeatable.")
    parser.add_argument("--runs-root", default=str(DEFAULT_TAKER_RUNS_ROOT))
    parser.add_argument("--date", default="", help="Optional target date under --runs-root.")
    parser.add_argument("--max-runs", type=int, default=0, help="Limit to the most recent N discovered runs; 0 means all.")
    parser.add_argument("--labels", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    runs = (
        [Path(item) for item in args.runs]
        if args.runs
        else discover_run_sources(
            args.runs_root,
            target_date=args.date or None,
            max_runs=args.max_runs or None,
        )
    )
    if not runs:
        runs = [path for path in DEFAULT_RUN_FOLDERS if path.exists()]
    payload = build_tail_casebook_from_paths(
        runs,
        labels_csv=args.labels,
        generated_at_utc=utc_iso(),
    )
    write_outputs(payload, json_out=args.json_out, report_out=args.report_out)
    print(
        f"Taker tail casebook: {payload['summary']['status']} "
        f"tail_fills={payload['summary']['tail_fill_count']} "
        f"losing={payload['summary']['losing_tail_fill_count']} "
        f"no_go_candidates={payload['summary']['no_go_candidate_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
