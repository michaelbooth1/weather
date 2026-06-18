"""Audit and quarantine malformed loop JSONL/log lines."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from weather.operations.supervisor import classify_malformed_jsonl_line, jsonl_integrity
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("loop_jsonl_repair")


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_lines(path):
    path = Path(path)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def audit_paths(paths):
    files = [jsonl_integrity(path) for path in paths]
    summary = {
        "file_count": len(files),
        "malformed_lines": sum(int(row.get("malformed_lines") or 0) for row in files),
        "valid_json_lines": sum(int(row.get("valid_json_lines") or 0) for row in files),
        "ok": all(row.get("ok") for row in files),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if summary["ok"] else "WARN",
        "summary": summary,
        "files": files,
    }


def repair_path(path, *, backup=True):
    path = Path(path)
    valid_lines = []
    malformed = []
    for line_number, raw in enumerate(read_lines(path), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            json.loads(line)
            valid_lines.append(line)
        except json.JSONDecodeError as exc:
            malformed.append({
                "line": line_number,
                "classification": classify_malformed_jsonl_line(line, exc),
                "error": str(exc),
                "text": line,
            })
    backup_path = None
    quarantine_path = None
    if malformed:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".malformed.bak")
            if not backup_path.exists():
                shutil.copy2(path, backup_path)
        quarantine_path = path.with_suffix(path.suffix + ".malformed.quarantine.jsonl")
        with quarantine_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in malformed:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for line in valid_lines:
                handle.write(line + "\n")
    return {
        "path": str(path),
        "valid_json_lines": len(valid_lines),
        "malformed_lines": len(malformed),
        "backup_path": str(backup_path) if backup_path else None,
        "quarantine_path": str(quarantine_path) if quarantine_path else None,
    }


def repair_paths(paths, *, backup=True):
    repairs = [repair_path(path, backup=backup) for path in paths]
    after = audit_paths(paths)
    after["repair"] = {
        "enabled": True,
        "repaired": repairs,
        "backup": bool(backup),
    }
    return after


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Loop JSONL Repair",
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
            ["Valid JSON lines", summary.get("valid_json_lines")],
            ["Malformed lines", summary.get("malformed_lines")],
        ],
    )
    issue_rows = [row for row in payload.get("files") or [] if int(row.get("malformed_lines") or 0)]
    if issue_rows:
        lines += ["", "## Issues", ""]
        lines += markdown_table(
            ["Path", "Malformed", "Classifications", "First Sample"],
            [
                [
                    row.get("path"),
                    row.get("malformed_lines"),
                    row.get("classification_counts"),
                    (row.get("examples") or [{}])[0].get("text") or "-",
                ]
                for row in issue_rows
            ],
        )
    repair = payload.get("repair") or {}
    if repair.get("enabled"):
        lines += ["", "## Repair", ""]
        lines += markdown_table(
            ["Path", "Malformed Quarantined", "Backup", "Quarantine"],
            [
                [
                    row.get("path"),
                    row.get("malformed_lines"),
                    row.get("backup_path") or "-",
                    row.get("quarantine_path") or "-",
                ]
                for row in repair.get("repaired") or []
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


def add_common_args(parser):
    parser.add_argument("paths", nargs="+", help="JSONL/log files to audit or repair.")
    parser.add_argument("--json-out", default="data/backtest/loop_jsonl_repair.json")
    parser.add_argument("--report-out", default="data/backtest/loop_jsonl_repair.md")
    return parser


def cmd_audit(args):
    payload = audit_paths(args.paths)
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Loop JSONL repair audit: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


def cmd_repair(args):
    payload = repair_paths(args.paths, backup=not args.no_backup)
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Loop JSONL repair: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Audit and quarantine malformed loop JSONL/log lines.")
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
