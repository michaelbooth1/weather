"""Audit and quarantine malformed loop JSONL/log lines."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.operations.supervisor import classify_malformed_jsonl_line, jsonl_integrity, pid_is_python, read_writer_lock
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


def managed_loop_specs():
    """Return known supervised loops without making imports mandatory for audits."""
    specs = []
    for module_name, attr_name in (
        ("weather.collection.snapshot_tracker", "SNAPSHOT_SUPERVISOR"),
        ("weather.market.market_microstructure", "CLOB_SUPERVISOR"),
        ("weather.operations.observation_trigger", "OBSERVATION_SUPERVISOR"),
    ):
        try:
            module = __import__(module_name, fromlist=[attr_name])
            specs.append(getattr(module, attr_name))
        except (ImportError, AttributeError):
            continue
    return tuple(specs)


def _same_path(left, right):
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return Path(left) == Path(right)


def active_writer_for_console_log(path) -> dict[str, Any] | None:
    path = Path(path)
    for spec in managed_loop_specs():
        if not _same_path(path, spec.console_log_path):
            continue
        lock = read_writer_lock(spec.status_path)
        pid = lock.get("pid")
        return {
            "loop": spec.name,
            "status_path": str(spec.status_path),
            "console_log_path": str(spec.console_log_path),
            "writer_lock_path": lock.get("path"),
            "writer_lock_exists": bool(lock.get("exists")),
            "pid": pid,
            "pid_alive": pid_is_python(pid),
        }
    return None


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


def repair_path(path, *, backup=True, allow_active=False):
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
    active_writer = active_writer_for_console_log(path)
    backup_path = None
    quarantine_path = None
    if malformed:
        if active_writer and active_writer.get("pid_alive") and not allow_active:
            return {
                "path": str(path),
                "valid_json_lines": len(valid_lines),
                "malformed_lines": len(malformed),
                "backup_path": None,
                "quarantine_path": None,
                "skipped": True,
                "reason": "active_writer_lock",
                "active_writer": active_writer,
            }
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
        "skipped": False,
        "reason": None,
        "active_writer": active_writer,
    }


def repair_paths(paths, *, backup=True, allow_active=False):
    repairs = [repair_path(path, backup=backup, allow_active=allow_active) for path in paths]
    after = audit_paths(paths)
    if any(row.get("skipped") for row in repairs):
        after["status"] = "BLOCK"
    after["repair"] = {
        "enabled": True,
        "repaired": repairs,
        "backup": bool(backup),
        "allow_active": bool(allow_active),
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
            ["Path", "Malformed Quarantined", "Skipped", "Reason", "Backup", "Quarantine"],
            [
                [
                    row.get("path"),
                    row.get("malformed_lines"),
                    row.get("skipped"),
                    row.get("reason") or "-",
                    row.get("backup_path") or "-",
                    row.get("quarantine_path") or "-",
                ]
                for row in repair.get("repaired") or []
            ],
        )
        skipped = [row for row in repair.get("repaired") or [] if row.get("skipped")]
        if skipped:
            lines += ["", "### Active Writers", ""]
            lines += markdown_table(
                ["Path", "Loop", "PID", "Lock", "Override"],
                [
                    [
                        row.get("path"),
                        (row.get("active_writer") or {}).get("loop"),
                        (row.get("active_writer") or {}).get("pid"),
                        (row.get("active_writer") or {}).get("writer_lock_path"),
                        "rerun with --allow-active only after stopping the writer",
                    ]
                    for row in skipped
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
    payload = repair_paths(args.paths, backup=not args.no_backup, allow_active=args.allow_active)
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
    repair.add_argument(
        "--allow-active",
        action="store_true",
        help="Allow rewriting a managed console log even if its writer lock belongs to a live process.",
    )
    repair.set_defaults(func=cmd_repair)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
