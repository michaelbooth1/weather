"""Audit and repair legacy-encoded market-making/CLOB CSV tapes."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from weather.io import csv_encoding_issue, read_csv_rows_with_diagnostics, write_csv_rows
from weather.market.market_making_run_constants import DEFAULT_RUNS_ROOT
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_making_tape_encoding")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "market_making_tape_encoding.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "market_making_tape_encoding.md"
DEFAULT_FILENAMES = (
    "order_books_summary.csv",
    "order_books_long.csv",
    "clob_tokens.csv",
    "clob_features_long.csv",
    "price_history.csv",
    "market_ws_events.csv",
    "quote_intents_long.csv",
    "fills_long.csv",
)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def discover_files(paths=None, roots=None, filenames=None, all_csv=False):
    explicit = [Path(path) for path in paths or []]
    if explicit:
        return sorted(path for path in explicit if path.exists())
    filenames = tuple(filenames or DEFAULT_FILENAMES)
    discovered = set()
    for root in roots or []:
        root = Path(root)
        if not root.exists():
            continue
        if all_csv:
            discovered.update(path for path in root.rglob("*.csv") if path.is_file())
        else:
            for filename in filenames:
                discovered.update(path for path in root.rglob(filename) if path.is_file())
    return sorted(discovered)


def status_for_diagnostics(rows):
    issues = [row for row in rows if csv_encoding_issue(row)]
    hard = [row for row in issues if row.get("status") not in {"legacy_encoding"}]
    if hard:
        return "FAIL"
    if issues:
        return "WARN"
    return "PASS"


def audit_paths(paths):
    files = []
    for path in paths:
        _rows, diagnostics = read_csv_rows_with_diagnostics(path, attach_diagnostics=False)
        files.append(diagnostics)
    summary = {
        "file_count": len(files),
        "issue_count": sum(1 for row in files if csv_encoding_issue(row)),
        "legacy_encoding_count": sum(1 for row in files if row.get("status") == "legacy_encoding"),
        "hard_error_count": sum(1 for row in files if row.get("status") not in {"ok", "missing", "legacy_encoding"}),
        "quarantined_row_count": sum(int(row.get("quarantined_row_count") or 0) for row in files),
    }
    summary["status"] = status_for_diagnostics(files)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": summary["status"],
        "summary": summary,
        "files": files,
    }


def repair_paths(paths, *, backup=True):
    repaired = []
    skipped = []
    for path in paths:
        rows, diagnostics = read_csv_rows_with_diagnostics(path, attach_diagnostics=True)
        if diagnostics.get("status") != "legacy_encoding":
            if csv_encoding_issue(diagnostics):
                skipped.append({
                    "path": str(path),
                    "status": diagnostics.get("status"),
                    "reason": diagnostics.get("error") or diagnostics.get("utf8_decode_error"),
                })
            continue
        path = Path(path)
        backup_path = None
        if backup:
            backup_path = path.with_suffix(path.suffix + ".legacy-encoding.bak")
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
        columns = diagnostics.get("fieldnames") or (list(rows[0].keys()) if rows else [])
        write_csv_rows(path, columns, rows)
        repaired.append({
            "path": str(path),
            "source_encoding": diagnostics.get("encoding"),
            "row_count": len(rows),
            "backup_path": str(backup_path) if backup_path else None,
        })
    return repaired, skipped


def build_payload(paths, *, repair=False, backup=True):
    before = audit_paths(paths)
    repaired = []
    skipped = []
    after = before
    if repair:
        repaired, skipped = repair_paths(paths, backup=backup)
        after = audit_paths(paths)
    payload = after
    payload["repair"] = {
        "enabled": bool(repair),
        "repaired": repaired,
        "skipped": skipped,
        "before_summary": before["summary"],
        "after_summary": after["summary"],
    }
    return payload


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Market-Making Tape Encoding",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Files", summary.get("file_count")],
            ["Issues", summary.get("issue_count")],
            ["Legacy encodings", summary.get("legacy_encoding_count")],
            ["Hard errors", summary.get("hard_error_count")],
            ["Quarantined rows", summary.get("quarantined_row_count")],
        ],
    )
    issue_rows = [row for row in payload.get("files") or [] if csv_encoding_issue(row)]
    if issue_rows:
        lines += ["", "## Issues", ""]
        lines += markdown_table(
            ["Path", "Status", "Encoding", "Rows", "Decode Error"],
            [
                [
                    row.get("path"),
                    row.get("status"),
                    row.get("encoding"),
                    row.get("quarantined_row_count") or row.get("row_count"),
                    row.get("utf8_decode_error") or row.get("error") or "-",
                ]
                for row in issue_rows
            ],
        )
    repair = payload.get("repair") or {}
    if repair.get("enabled"):
        lines += ["", "## Repair", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Repaired files", len(repair.get("repaired") or [])],
                ["Skipped files", len(repair.get("skipped") or [])],
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out, report_out):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def parse_filenames(value):
    if not value:
        return DEFAULT_FILENAMES
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def files_from_args(args):
    roots = [args.root, args.runs_root]
    return discover_files(
        paths=args.paths,
        roots=roots,
        filenames=parse_filenames(args.filenames),
        all_csv=args.all_csv,
    )


def add_common_args(parser):
    parser.add_argument("paths", nargs="*", help="Specific CSV files to audit or repair.")
    parser.add_argument("--root", default=str(DEFAULT_SNAPSHOTS_ROOT), help="Snapshot root to scan when no paths are supplied.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT), help="MM runs root to scan when no paths are supplied.")
    parser.add_argument("--filenames", default=",".join(DEFAULT_FILENAMES))
    parser.add_argument("--all-csv", action="store_true")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def cmd_audit(args):
    payload = build_payload(files_from_args(args), repair=False)
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Market-making tape encoding: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 2 if payload["status"] == "FAIL" else 0


def cmd_repair(args):
    payload = build_payload(files_from_args(args), repair=True, backup=not args.no_backup)
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Market-making tape encoding: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 2 if payload["status"] == "FAIL" else 0


def build_parser():
    parser = argparse.ArgumentParser(description="Audit and repair market-making CSV tape encodings.")
    sub = parser.add_subparsers(dest="command", required=True)
    audit = add_common_args(sub.add_parser("audit"))
    audit.set_defaults(func=cmd_audit)
    repair = add_common_args(sub.add_parser("repair"))
    repair.add_argument("--no-backup", action="store_true")
    repair.set_defaults(func=cmd_repair)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
