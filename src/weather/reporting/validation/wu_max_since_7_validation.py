"""Validate captured WU current max-since-7 AM against settlement labels."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.reporting.formatting import (
    fmt_num,
    fmt_pct,
    markdown_table,
)
from weather.backtesting.replay import index_records_by_snapshot, load_replay_records, source_freshness_group
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT
from weather.reporting.promotion.promotion_corpus import DEFAULT_OUT as DEFAULT_CORPUS
from weather.reporting.promotion.promotion_corpus import folders_from_manifest, load_manifest


SCHEMA_VERSION = "wu_max_since_7_validation_v0.1"
DEFAULT_JSON_OUT = data_path() / "backtest" / "wu_max_since_7_validation.json"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "wu_max_since_7_validation_report.md"
DEFAULT_GAUNTLET_REPORT = data_path() / "backtest" / "promotion_gauntlet_latest_report.md"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_hour(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.hour


def snapshot_cutoff_hour(row):
    local_hour = parse_hour(row.get("captured_at_local"))
    if local_hour is not None:
        return local_hour
    return parse_hour(row.get("captured_at_utc"))


def classify_current_max(current_max, final_wu_high, eps=1e-9):
    if current_max is None:
        return "missing_current_max"
    if final_wu_high is None:
        return "missing_final_wu_high"
    if current_max > final_wu_high + eps:
        return "above_final_wu_high"
    if current_max < final_wu_high - eps:
        return "below_final_wu_high"
    return "matches_final_wu_high"


def classify_bucket(current_max, settlement_bucket, eps=1e-9):
    if current_max is None:
        return "missing_current_max"
    if settlement_bucket is None:
        return "missing_settlement_bucket"
    if current_max > settlement_bucket + eps:
        return "above_settlement_bucket"
    if current_max < settlement_bucket - eps:
        return "below_settlement_bucket"
    return "matches_settlement_bucket"


def _market_filter(markets):
    if not markets:
        return None
    if isinstance(markets, str):
        values = [item.strip() for item in markets.split(",")]
    else:
        values = [str(item).strip() for item in markets]
    cleaned = {item.lower() for item in values if item and item not in {"*", "all"}}
    return cleaned or None


def _first_pinned_snapshot_rows(folder, snapshot_ids):
    path = Path(folder) / "snapshots_long.csv"
    if not path.exists():
        return {}, [f"{Path(folder).name}: missing snapshots_long.csv"]
    wanted = {str(item) for item in snapshot_ids}
    rows = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                snapshot_id = str(row.get("snapshot_id") or "")
                if snapshot_id in wanted and snapshot_id not in rows:
                    rows[snapshot_id] = row
    except OSError as exc:
        return {}, [f"{Path(folder).name}: unreadable snapshots_long.csv ({exc})"]
    warnings = [
        f"{Path(folder).name}: pinned snapshot {snapshot_id} missing from snapshots_long.csv"
        for snapshot_id in snapshot_ids
        if str(snapshot_id) not in rows
    ]
    return rows, warnings


def _record_freshness(record):
    if not record:
        return "missing_replay_record"
    return source_freshness_group(record)


def _validation_row(entry, tape_row, record):
    current_max = maybe_float(tape_row.get("wu_max_since_7am_native"))
    if current_max is None:
        current_max = maybe_float(tape_row.get("wu_max_since_7am_c"))
    settlement_high = maybe_float(entry.get("settlement_high"))
    settlement_bucket = maybe_float(entry.get("settlement_bucket"))
    final_wu_high = settlement_high if settlement_high is not None else settlement_bucket
    gap_to_final = None if current_max is None or final_wu_high is None else current_max - final_wu_high
    gap_to_bucket = (
        None if current_max is None or settlement_bucket is None else current_max - settlement_bucket
    )
    return {
        "market_id": entry.get("market_id"),
        "event_slug": entry.get("event_slug"),
        "target_date": entry.get("target_date"),
        "snapshot_id": str(tape_row.get("snapshot_id") or ""),
        "captured_at_local": tape_row.get("captured_at_local"),
        "captured_at_utc": tape_row.get("captured_at_utc"),
        "cutoff_hour": snapshot_cutoff_hour(tape_row),
        "wu_max_since_7am_c": current_max,
        "final_wu_high": final_wu_high,
        "settlement_high": settlement_high,
        "settlement_bucket": settlement_bucket,
        "settlement_unit": entry.get("settlement_unit"),
        "validation_state": classify_current_max(current_max, final_wu_high),
        "settlement_bucket_state": classify_bucket(current_max, settlement_bucket),
        "gap_to_final_wu_high": gap_to_final,
        "gap_to_settlement_bucket": gap_to_bucket,
        "source_freshness_state": _record_freshness(record),
    }


def collect_validation_rows(manifest, snapshots_root=None, markets=None):
    wanted_markets = _market_filter(markets)
    rows = []
    warnings = []
    folders = folders_from_manifest(manifest, snapshots_root)
    for entry, folder in zip(manifest.get("entries") or [], folders):
        market_id = str(entry.get("market_id") or "").lower()
        if wanted_markets and market_id not in wanted_markets:
            continue
        snapshot_ids = [str(item) for item in entry.get("snapshot_ids") or []]
        tape_rows, tape_warnings = _first_pinned_snapshot_rows(folder, snapshot_ids)
        warnings.extend(tape_warnings)
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id in snapshot_ids:
            tape_row = tape_rows.get(str(snapshot_id))
            if not tape_row:
                continue
            if str(snapshot_id) not in records:
                warnings.append(f"{entry.get('event_slug')}: replay input missing for snapshot {snapshot_id}")
            rows.append(_validation_row(entry, tape_row, records.get(str(snapshot_id))))
    return rows, warnings


def _mean(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _rate(numerator, denominator):
    if not denominator:
        return None
    return numerator / denominator


def summarize_validation_rows(rows):
    state_counts = Counter(row.get("validation_state") for row in rows)
    bucket_counts = Counter(row.get("settlement_bucket_state") for row in rows)
    comparable = [
        row for row in rows
        if row.get("wu_max_since_7am_c") is not None and row.get("final_wu_high") is not None
    ]
    safe_count = sum(1 for row in comparable if row.get("validation_state") != "above_final_wu_high")
    above_count = state_counts.get("above_final_wu_high", 0)
    match_count = state_counts.get("matches_final_wu_high", 0)
    gaps_to_final = [row.get("gap_to_final_wu_high") for row in rows]
    gaps_to_bucket = [row.get("gap_to_settlement_bucket") for row in rows]
    numeric_final_gaps = [value for value in gaps_to_final if value is not None]
    numeric_bucket_gaps = [value for value in gaps_to_bucket if value is not None]
    return {
        "snapshots": len(rows),
        "with_current_max": sum(1 for row in rows if row.get("wu_max_since_7am_c") is not None),
        "missing_current_max": state_counts.get("missing_current_max", 0),
        "comparable_to_final_wu_high": len(comparable),
        "safe_as_support_bound": safe_count,
        "above_final_wu_high": above_count,
        "safe_rate": _rate(safe_count, len(comparable)),
        "over_rate": _rate(above_count, len(comparable)),
        "match_rate": _rate(match_count, len(comparable)),
        "state_counts": dict(sorted(state_counts.items())),
        "settlement_bucket_state_counts": dict(sorted(bucket_counts.items())),
        "source_freshness_counts": dict(sorted(Counter(row.get("source_freshness_state") for row in rows).items())),
        "mean_gap_to_final_wu_high": _mean(gaps_to_final),
        "min_gap_to_final_wu_high": min(numeric_final_gaps) if numeric_final_gaps else None,
        "max_gap_to_final_wu_high": max(numeric_final_gaps) if numeric_final_gaps else None,
        "mean_gap_to_settlement_bucket": _mean(gaps_to_bucket),
        "min_gap_to_settlement_bucket": min(numeric_bucket_gaps) if numeric_bucket_gaps else None,
        "max_gap_to_settlement_bucket": max(numeric_bucket_gaps) if numeric_bucket_gaps else None,
    }


def grouped_summaries(rows, fields):
    if isinstance(fields, str):
        fields = (fields,)
    groups = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        groups[key].append(row)
    output = []
    for key, group_rows in groups.items():
        item = summarize_validation_rows(group_rows)
        for field, value in zip(fields, key):
            item[field] = value
        item["group"] = " / ".join(str(value) if value not in (None, "") else "-" for value in key)
        output.append(item)
    return sorted(output, key=lambda item: item.get("group") or "")


def build_validation_payload(
    corpus=DEFAULT_CORPUS,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    markets=None,
    focus_market="miami",
):
    manifest = load_manifest(corpus) if not isinstance(corpus, dict) else corpus
    rows, warnings = collect_validation_rows(manifest, snapshots_root, markets=markets)
    focus_rows = [row for row in rows if row.get("market_id") == focus_market]
    summary = manifest.get("summary") or {}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "corpus": {
            "path": manifest.get("_path") or str(corpus),
            "hash": manifest.get("corpus_hash"),
            "as_of": manifest.get("as_of"),
            "market_day_count": summary.get("market_day_count"),
            "snapshot_count": summary.get("snapshot_count"),
        },
        "filters": {
            "markets": sorted(_market_filter(markets) or []),
            "focus_market": focus_market,
        },
        "summary": summarize_validation_rows(rows),
        "by_market": grouped_summaries(rows, "market_id"),
        "by_market_day": grouped_summaries(rows, ("market_id", "target_date")),
        "by_market_hour": grouped_summaries(rows, ("market_id", "cutoff_hour")),
        "by_source_freshness": grouped_summaries(rows, "source_freshness_state"),
        "focus_market": {
            "market_id": focus_market,
            "summary": summarize_validation_rows(focus_rows),
            "by_day": grouped_summaries(focus_rows, "target_date"),
            "by_cutoff_hour": grouped_summaries(focus_rows, "cutoff_hour"),
            "by_source_freshness": grouped_summaries(focus_rows, "source_freshness_state"),
            "above_final_examples": sorted(
                [row for row in focus_rows if row.get("validation_state") == "above_final_wu_high"],
                key=lambda row: (
                    -(row.get("gap_to_final_wu_high") or 0.0),
                    row.get("target_date") or "",
                    row.get("snapshot_id") or "",
                ),
            )[:20],
        },
        "warnings": warnings,
        "rows": rows,
    }
    return payload


def _summary_table_row(label, summary):
    return [
        label,
        summary.get("snapshots", 0),
        summary.get("with_current_max", 0),
        summary.get("comparable_to_final_wu_high", 0),
        summary.get("safe_as_support_bound", 0),
        summary.get("above_final_wu_high", 0),
        fmt_pct(summary.get("safe_rate")),
        fmt_pct(summary.get("over_rate")),
        fmt_num(summary.get("mean_gap_to_final_wu_high"), 2),
        fmt_num(summary.get("max_gap_to_final_wu_high"), 2),
    ]


def _summary_table(title, items, label_field="group", limit=None):
    rows = [
        _summary_table_row(str(item.get(label_field) or "-"), item)
        for item in (items[:limit] if limit else items)
    ]
    lines = ["", f"## {title}", ""]
    lines += markdown_table(
        [
            "Group",
            "Snapshots",
            "With WU Max",
            "Comparable",
            "Safe",
            "Above Final",
            "Safe Rate",
            "Over Rate",
            "Mean Gap",
            "Max Gap",
        ],
        rows,
    )
    return lines


def _count_table(title, counts):
    lines = ["", f"## {title}", ""]
    lines += markdown_table(["State", "Snapshots"], [[key, value] for key, value in sorted(counts.items())])
    return lines


def write_report(payload, path=DEFAULT_REPORT_OUT, gauntlet_report=DEFAULT_GAUNTLET_REPORT):
    summary = payload.get("summary") or {}
    focus = payload.get("focus_market") or {}
    focus_summary = focus.get("summary") or {}
    corpus = payload.get("corpus") or {}
    lines = [
        "# WU Max Since 7 AM Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Corpus: `{corpus.get('hash') or '-'}`",
        f"Corpus path: `{corpus.get('path') or '-'}`",
        "",
        (
            "This report validates captured `wu_max_since_7am_c` as a support signal. "
            "A captured max is safe as a hard lower bound only when it does not exceed "
            "the final WU settlement high."
        ),
        "",
        "## Aggregate",
        "",
    ]
    lines += markdown_table(
        [
            "Scope",
            "Snapshots",
            "With WU Max",
            "Comparable",
            "Safe",
            "Above Final",
            "Safe Rate",
            "Over Rate",
            "Mean Gap",
            "Max Gap",
        ],
        [
            _summary_table_row("all", summary),
            _summary_table_row(focus.get("market_id") or "-", focus_summary),
        ],
    )
    lines += _count_table("Validation States", summary.get("state_counts") or {})
    lines += _count_table("Source Freshness States", summary.get("source_freshness_counts") or {})
    lines += _summary_table("By Market", payload.get("by_market") or [])
    lines += _summary_table(
        f"{focus.get('market_id') or 'focus'} By Cutoff Hour",
        focus.get("by_cutoff_hour") or [],
    )
    lines += _summary_table(
        f"{focus.get('market_id') or 'focus'} By Source Freshness",
        focus.get("by_source_freshness") or [],
    )
    examples = focus.get("above_final_examples") or []
    if examples:
        lines += ["", f"## {focus.get('market_id')} Above-Final Examples", ""]
        lines += markdown_table(
            [
                "Date",
                "Snapshot",
                "Hour",
                "WU Max",
                "Final WU High",
                "Settlement",
                "Gap",
                "Freshness",
            ],
            [
                [
                    row.get("target_date"),
                    row.get("snapshot_id"),
                    row.get("cutoff_hour"),
                    fmt_num(row.get("wu_max_since_7am_c"), 2),
                    fmt_num(row.get("final_wu_high"), 2),
                    fmt_num(row.get("settlement_bucket"), 2),
                    fmt_num(row.get("gap_to_final_wu_high"), 2),
                    row.get("source_freshness_state"),
                ]
                for row in examples
            ],
        )
    lines += [
        "",
        "## Current-Serving Failure Decomposition",
        "",
        (
            "Code-effect slices by hour, settlement distance, band type, forecast gap, "
            "and live-reading gap are generated by the promotion gauntlet. "
            f"Use `{gauntlet_report}` for the current-serving replay blocker details."
        ),
    ]
    warnings = payload.get("warnings") or []
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {warning}" for warning in warnings]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_json(payload, path=DEFAULT_JSON_OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Validate captured WU current max-since-7 AM against settlement labels."
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--markets", default=None, help="Comma-separated market ids, or all markets by default.")
    parser.add_argument("--focus-market", default="miami")
    parser.add_argument("--out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--gauntlet-report", default=str(DEFAULT_GAUNTLET_REPORT))
    args = parser.parse_args()

    payload = build_validation_payload(
        corpus=args.corpus,
        snapshots_root=args.snapshots_root,
        markets=args.markets,
        focus_market=args.focus_market,
    )
    json_path = write_json(payload, args.json_out)
    report_path = write_report(payload, args.out, gauntlet_report=args.gauntlet_report)
    print(
        f"WU max-since-7 validation written to {report_path} and {json_path}: "
        f"{payload['summary']['snapshots']} snapshots."
    )


if __name__ == "__main__":
    main()
