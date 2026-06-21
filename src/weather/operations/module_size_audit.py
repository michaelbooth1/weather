"""Audit large Python modules and document ownership boundaries."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT, data_path, relative_to_repo
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("module_size_audit")
DEFAULT_SOURCE_ROOT = REPO_ROOT / "src" / "weather"
DEFAULT_OUT = data_path() / "backtest" / "module_size_audit.json"
DEFAULT_REPORT = data_path() / "backtest" / "module_size_audit_report.md"
DEFAULT_WARNING_LINES = 2_000

OWNERSHIP_NOTES = {
    "src/weather/calibration/pooled_feature_model.py": {
        "owner": "calibration",
        "boundary": "Compatibility facade for pooled feature model implementation slices.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/market/taker_bot.py": {
        "owner": "market",
        "boundary": "Compatibility facade for taker strategy, risk, tape, scoring, bakeoff, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/promotion_refresh.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for promotion readers, decisions, gap analysis, reports, orchestration, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/fleet_observability.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for fleet inventory, loop health, SLO gates, payload, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/hourly_model_performance.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for hourly scoring, slots, gates, context, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/operations/daily_refresh.py": {
        "owner": "operations",
        "boundary": "Daily refresh orchestration facade.",
        "next_split": "step runner registry, status/report rendering, preflight gates, and CLI.",
    },
}


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _line in handle)
    except UnicodeDecodeError:
        return 0


def module_owner(path: Path) -> str:
    try:
        relative = path.relative_to(REPO_ROOT / "src" / "weather")
    except ValueError:
        return "unknown"
    return relative.parts[0] if len(relative.parts) > 1 else "shared"


def build_module_size_audit(
    source_root: str | Path = DEFAULT_SOURCE_ROOT,
    *,
    warning_lines: int = DEFAULT_WARNING_LINES,
    generated_at_utc: str | None = None,
) -> dict:
    source_root = Path(source_root)
    rows = []
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = relative_to_repo(path)
        lines = count_lines(path)
        note = OWNERSHIP_NOTES.get(rel, {})
        rows.append({
            "path": rel,
            "owner": note.get("owner") or module_owner(path),
            "lines": lines,
            "status": "WARN" if lines >= warning_lines else "OK",
            "boundary": note.get("boundary"),
            "next_split": note.get("next_split"),
        })
    over_threshold = [row for row in rows if row["status"] == "WARN"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "source_root": relative_to_repo(source_root),
        "warning_lines": int(warning_lines),
        "module_count": len(rows),
        "warning_count": len(over_threshold),
        "largest_modules": sorted(rows, key=lambda row: row["lines"], reverse=True)[:25],
        "ownership_map": [
            {"path": path, **note}
            for path, note in sorted(OWNERSHIP_NOTES.items())
        ],
    }


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict) -> str:
    lines = [
        "# Module Size Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Warning threshold: `{payload.get('warning_lines')}` lines",
        f"Warnings: `{payload.get('warning_count')}`",
        "",
        "## Largest Modules",
        "",
        "| Module | Owner | Lines | Status | Boundary | Next split |",
        "| :--- | :--- | ---: | :--- | :--- | :--- |",
    ]
    for row in payload.get("largest_modules") or []:
        lines.append(
            "| {path} | {owner} | {lines} | {status} | {boundary} | {next_split} |".format(
                path=row.get("path"),
                owner=row.get("owner"),
                lines=row.get("lines"),
                status=row.get("status"),
                boundary=row.get("boundary") or "-",
                next_split=row.get("next_split") or "-",
            )
        )
    lines.extend([
        "",
        "## Ownership Map",
        "",
        "| Module | Owner | Boundary | Next split |",
        "| :--- | :--- | :--- | :--- |",
    ])
    for row in payload.get("ownership_map") or []:
        lines.append(
            "| {path} | {owner} | {boundary} | {next_split} |".format(
                path=row.get("path"),
                owner=row.get("owner"),
                boundary=row.get("boundary"),
                next_split=row.get("next_split"),
            )
        )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit Python module sizes and ownership split targets.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--warning-lines", type=int, default=DEFAULT_WARNING_LINES)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_module_size_audit(args.source_root, warning_lines=args.warning_lines)
    write_json(args.out, payload)
    write_report(args.report, payload)
    print(
        "Module size audit: modules={module_count} warnings={warning_count} threshold={warning_lines}".format(
            **payload
        )
    )
    return payload


if __name__ == "__main__":
    main()
