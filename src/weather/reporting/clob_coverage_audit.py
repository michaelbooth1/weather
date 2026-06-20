"""Audit CLOB microstructure coverage root causes for snapshot folders."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table


SCHEMA_VERSION = "clob_coverage_audit_v0.2"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "clob_coverage_audit.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "clob_coverage_audit_report.md"
RAW_BOOK_FILES = (
    "order_books_summary.csv",
    "order_books.jsonl",
    "order_books_long.csv",
    "order_books_long.csv.gz",
)
TOKEN_FILES = ("clob_tokens.csv", "clob_tokens.jsonl")
EVENT_RE = re.compile(
    r"^highest-temperature-in-(?P<market>.+)-on-"
    r"(?P<month>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})$"
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
DEFAULT_MIN_TRAIN_MIDPOINT_COVERAGE = 0.05


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_csv_count(path: Path) -> tuple[int, list[dict[str, Any]]]:
    if not path.exists():
        return 0, []
    count = 0
    sample = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            count += 1
            if len(sample) < 3:
                sample.append(row)
    return count, sample


def file_info(folder: Path, names: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for name in names:
        path = folder / name
        rows.append({
            "name": name,
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        })
    return rows


def has_any_file(files: list[dict[str, Any]]) -> bool:
    return any(row.get("exists") and int(row.get("bytes") or 0) > 0 for row in files)


def parse_event_slug(slug: str) -> dict[str, Any]:
    match = EVENT_RE.match(str(slug or ""))
    if not match:
        return {
            "market_id": None,
            "target_date": None,
            "date_sort_key": None,
        }
    month = MONTHS.get(match.group("month").lower())
    if month is None:
        return {
            "market_id": match.group("market"),
            "target_date": None,
            "date_sort_key": None,
        }
    year = int(match.group("year"))
    day = int(match.group("day"))
    target_date = f"{year:04d}-{month:02d}-{day:02d}"
    return {
        "market_id": match.group("market"),
        "target_date": target_date,
        "date_sort_key": target_date,
    }


def feature_summary(folder: Path) -> dict[str, Any]:
    feature_path = folder / "clob_features_long.csv"
    rows, _sample = read_csv_count(feature_path)
    if rows == 0:
        return {
            "feature_rows": 0,
            "token_rows": 0,
            "feature_available_rows": 0,
            "midpoint_rows": 0,
            "spread_rows": 0,
            "best_bid_rows": 0,
            "best_ask_rows": 0,
            "one_sided_quote_rows": 0,
            "midpoint_coverage": 0.0,
            "feature_available_coverage": 0.0,
            "token_coverage": 0.0,
            "spread_mean": None,
            "liquidity_mean": None,
        }
    token_rows = 0
    available_rows = 0
    midpoint_rows = 0
    spread_rows = 0
    best_bid_rows = 0
    best_ask_rows = 0
    one_sided_rows = 0
    spreads = []
    liquidity = []
    with feature_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            token = row.get("clob_token_id")
            available = safe_float(row.get("clob_feature_available"))
            midpoint = safe_float(row.get("clob_midpoint"))
            spread = safe_float(row.get("clob_spread"))
            bid = safe_float(row.get("clob_best_bid"))
            ask = safe_float(row.get("clob_best_ask"))
            liq = safe_float(row.get("clob_liquidity_score"))
            token_rows += int(token not in (None, ""))
            available_rows += int(available == 1.0)
            midpoint_rows += int(midpoint is not None)
            spread_rows += int(spread is not None)
            best_bid_rows += int(bid is not None)
            best_ask_rows += int(ask is not None)
            one_sided_rows += int(midpoint is None and (bid is not None or ask is not None))
            if spread is not None:
                spreads.append(spread)
            if liq is not None:
                liquidity.append(liq)
    return {
        "feature_rows": rows,
        "token_rows": token_rows,
        "feature_available_rows": available_rows,
        "midpoint_rows": midpoint_rows,
        "spread_rows": spread_rows,
        "best_bid_rows": best_bid_rows,
        "best_ask_rows": best_ask_rows,
        "one_sided_quote_rows": one_sided_rows,
        "midpoint_coverage": midpoint_rows / rows if rows else 0.0,
        "feature_available_coverage": available_rows / rows if rows else 0.0,
        "token_coverage": token_rows / rows if rows else 0.0,
        "spread_mean": sum(spreads) / len(spreads) if spreads else None,
        "liquidity_mean": sum(liquidity) / len(liquidity) if liquidity else None,
    }


def classify_folder(summary: dict[str, Any]) -> str:
    features = summary.get("features") or {}
    raw_book_present = bool(summary.get("raw_book_present"))
    token_file_present = bool(summary.get("token_file_present"))
    feature_rows = int(features.get("feature_rows") or 0)
    token_rows = int(features.get("token_rows") or 0)
    midpoint_rows = int(features.get("midpoint_rows") or 0)
    available_rows = int(features.get("feature_available_rows") or 0)
    one_sided = int(features.get("one_sided_quote_rows") or 0)
    if feature_rows == 0:
        return "missing_clob_feature_export"
    if not raw_book_present and not token_file_present:
        return "missing_raw_clob_tape_and_token_map"
    if token_rows == 0:
        return "missing_feature_token_mapping"
    if available_rows == 0:
        return "no_fresh_book_at_snapshot"
    if midpoint_rows == 0 and one_sided > 0:
        return "one_sided_books_no_midpoint"
    if midpoint_rows == 0:
        return "books_present_no_midpoint"
    return "midpoint_available"


def audit_folder(folder: str | Path) -> dict[str, Any]:
    folder = Path(folder)
    snapshot_rows, _sample = read_csv_count(folder / "snapshots_long.csv")
    raw_book_files = file_info(folder, RAW_BOOK_FILES)
    token_files = file_info(folder, TOKEN_FILES)
    features = feature_summary(folder)
    summary = {
        "folder": str(folder),
        "event_slug": folder.name,
        **parse_event_slug(folder.name),
        "snapshot_rows": snapshot_rows,
        "raw_book_files": raw_book_files,
        "token_files": token_files,
        "raw_book_present": has_any_file(raw_book_files),
        "token_file_present": has_any_file(token_files),
        "features": features,
    }
    summary["classification"] = classify_folder(summary)
    return summary


def _coverage_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    feature_rows = sum(int((row.get("features") or {}).get("feature_rows") or 0) for row in rows)
    midpoint_rows = sum(int((row.get("features") or {}).get("midpoint_rows") or 0) for row in rows)
    token_rows = sum(int((row.get("features") or {}).get("token_rows") or 0) for row in rows)
    available_rows = sum(int((row.get("features") or {}).get("feature_available_rows") or 0) for row in rows)
    return {
        "folders": len(rows),
        "feature_rows": feature_rows,
        "midpoint_rows": midpoint_rows,
        "midpoint_coverage": midpoint_rows / feature_rows if feature_rows else 0.0,
        "token_rows": token_rows,
        "token_coverage": token_rows / feature_rows if feature_rows else 0.0,
        "feature_available_rows": available_rows,
        "feature_available_coverage": available_rows / feature_rows if feature_rows else 0.0,
        "midpoint_available_folders": sum(
            1 for row in rows
            if row.get("classification") == "midpoint_available"
        ),
        "missing_raw_tape_folders": sum(
            1 for row in rows
            if row.get("classification") == "missing_raw_clob_tape_and_token_map"
        ),
        "raw_book_present_folders": sum(1 for row in rows if row.get("raw_book_present")),
        "token_file_present_folders": sum(1 for row in rows if row.get("token_file_present")),
    }


def chronological_split_coverage(
    folder_rows: list[dict[str, Any]],
    min_train_midpoint_coverage: float = DEFAULT_MIN_TRAIN_MIDPOINT_COVERAGE,
) -> dict[str, Any]:
    """Summarize CLOB coverage on earlier-date train and later-date eval splits."""
    by_market: dict[str, list[dict[str, Any]]] = {}
    unparsable = []
    for row in folder_rows:
        market_id = row.get("market_id")
        target_date = row.get("target_date")
        if not market_id or not target_date:
            unparsable.append(row.get("event_slug"))
            continue
        by_market.setdefault(str(market_id), []).append(row)

    market_rows = []
    train_rows = []
    eval_rows = []
    for market_id, rows in sorted(by_market.items()):
        ordered = sorted(rows, key=lambda row: row.get("date_sort_key") or row.get("target_date") or "")
        if len(ordered) <= 1:
            train = ordered
            eval_ = []
        else:
            cut = max(1, len(ordered) // 2)
            train = ordered[:cut]
            eval_ = ordered[cut:]
        train_rows.extend(train)
        eval_rows.extend(eval_)
        market_rows.append({
            "market_id": market_id,
            "train_dates": [row.get("target_date") for row in train],
            "eval_dates": [row.get("target_date") for row in eval_],
            "train": _coverage_totals(train),
            "eval": _coverage_totals(eval_),
        })

    train_totals = _coverage_totals(train_rows)
    eval_totals = _coverage_totals(eval_rows)
    status = (
        "PASS"
        if (
            train_totals["feature_rows"] > 0
            and train_totals["midpoint_coverage"] >= float(min_train_midpoint_coverage)
            and train_totals["midpoint_available_folders"] > 0
        )
        else "BLOCK"
    )
    return {
        "status": status,
        "min_train_midpoint_coverage": float(min_train_midpoint_coverage),
        "reason": (
            "train-side midpoint coverage clears threshold"
            if status == "PASS"
            else (
                "train-side midpoint coverage below threshold "
                f"({train_totals['midpoint_coverage']:.4f} < {float(min_train_midpoint_coverage):.4f})"
            )
        ),
        "train": train_totals,
        "eval": eval_totals,
        "markets": market_rows,
        "unparsable_event_slugs": unparsable,
    }


def build_payload(
    folders: list[str | Path],
    min_train_midpoint_coverage: float = DEFAULT_MIN_TRAIN_MIDPOINT_COVERAGE,
) -> dict[str, Any]:
    folder_rows = [audit_folder(folder) for folder in folders]
    classifications: dict[str, int] = {}
    for row in folder_rows:
        classifications[row["classification"]] = classifications.get(row["classification"], 0) + 1
    split_coverage = chronological_split_coverage(
        folder_rows,
        min_train_midpoint_coverage=min_train_midpoint_coverage,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_classification": "diagnostic_not_promotion_evidence",
        "split_coverage_gate": split_coverage,
        "summary": {
            "folders": len(folder_rows),
            "classifications": classifications,
            "midpoint_available_folders": sum(
                1 for row in folder_rows
                if row["classification"] == "midpoint_available"
            ),
            "missing_raw_tape_folders": sum(
                1 for row in folder_rows
                if row["classification"] == "missing_raw_clob_tape_and_token_map"
            ),
        },
        "folders": folder_rows,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CLOB Coverage Audit",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Evidence classification: diagnostic, not promotion evidence.",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Folders", summary.get("folders")],
            ["Midpoint available folders", summary.get("midpoint_available_folders")],
            ["Missing raw tape/token folders", summary.get("missing_raw_tape_folders")],
            ["Classifications", json.dumps(summary.get("classifications") or {}, sort_keys=True)],
        ],
    )
    split = payload.get("split_coverage_gate") or {}
    lines += [
        "",
        "## Chronological Split Coverage",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Split coverage gate", split.get("status")],
            ["Reason", split.get("reason")],
            ["Min train midpoint coverage", fmt_num(split.get("min_train_midpoint_coverage"))],
            ["Train folders", (split.get("train") or {}).get("folders")],
            ["Train midpoint coverage", fmt_num((split.get("train") or {}).get("midpoint_coverage"))],
            ["Train midpoint folders", (split.get("train") or {}).get("midpoint_available_folders")],
            ["Eval folders", (split.get("eval") or {}).get("folders")],
            ["Eval midpoint coverage", fmt_num((split.get("eval") or {}).get("midpoint_coverage"))],
            ["Eval midpoint folders", (split.get("eval") or {}).get("midpoint_available_folders")],
        ],
    )
    lines += [
        "",
        "## Split Coverage By Market",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Train Dates",
            "Train Midpoint Cov",
            "Train Midpoint Folders",
            "Eval Dates",
            "Eval Midpoint Cov",
            "Eval Midpoint Folders",
        ],
        [
            [
                row.get("market_id"),
                ", ".join(row.get("train_dates") or []) or "-",
                fmt_num((row.get("train") or {}).get("midpoint_coverage")),
                (row.get("train") or {}).get("midpoint_available_folders"),
                ", ".join(row.get("eval_dates") or []) or "-",
                fmt_num((row.get("eval") or {}).get("midpoint_coverage")),
                (row.get("eval") or {}).get("midpoint_available_folders"),
            ]
            for row in split.get("markets") or []
        ],
    )
    lines += [
        "",
        "## Folders",
        "",
    ]
    lines += markdown_table(
        [
            "Folder",
            "Class",
            "Snapshots",
            "Feature Rows",
            "Token Cov",
            "Feature Avail",
            "Midpoint Cov",
            "One-Sided",
            "Raw Books",
            "Token File",
        ],
        [
            [
                Path(row.get("folder") or "").name,
                row.get("classification"),
                row.get("snapshot_rows"),
                (row.get("features") or {}).get("feature_rows"),
                fmt_num((row.get("features") or {}).get("token_coverage")),
                fmt_num((row.get("features") or {}).get("feature_available_coverage")),
                fmt_num((row.get("features") or {}).get("midpoint_coverage")),
                (row.get("features") or {}).get("one_sided_quote_rows"),
                row.get("raw_book_present"),
                row.get("token_file_present"),
            ]
            for row in payload.get("folders") or []
        ],
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit CLOB coverage root causes for snapshot folders.")
    parser.add_argument("folders", nargs="+", help="Snapshot folders to inspect.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--min-train-midpoint-coverage",
        type=float,
        default=DEFAULT_MIN_TRAIN_MIDPOINT_COVERAGE,
        help="Minimum train-side midpoint coverage required for the split coverage gate.",
    )
    args = parser.parse_args()
    payload = build_payload(
        args.folders,
        min_train_midpoint_coverage=args.min_train_midpoint_coverage,
    )
    out = write_json(args.out, payload)
    report = write_markdown_report(args.report, payload)
    print(f"CLOB coverage audit: {payload['summary']['folders']} folders")
    print(f"Split coverage gate: {payload['split_coverage_gate']['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


if __name__ == "__main__":
    main()
