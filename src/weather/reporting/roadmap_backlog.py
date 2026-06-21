"""Roadmap item parser, active backlog report, and docs lint."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path, docs_path, relative_to_repo
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("roadmap_backlog")
DEFAULT_ROADMAP_ROOT = docs_path("roadmap")
DEFAULT_JSON_OUT = data_path("backtest", "roadmap_backlog.json")
DEFAULT_REPORT_OUT = docs_path("roadmap", "active-backlog.md")

HEADING_RE = re.compile(r"^# (?P<number>\d+)\. (?P<title>.+?) \[(?P<status_text>[^\]]+)\]\s*$")
STATUS_RE = re.compile(
    r"^(?P<status>OPEN|PARTIAL|COMPLETE)"
    r"(?: (?P<date>\d{4}-\d{2}-\d{2}))?"
    r"(?: - (?P<disposition>.*))?$"
)
CHECKLIST_RE = re.compile(r"^- \[[ xX]\] ", re.MULTILINE)
REQUIRED_ACTIVE_MARKERS = {
    "goal": re.compile(r"^Goal:", re.MULTILINE),
    "source": re.compile(r"^Source:", re.MULTILINE),
    "why": re.compile(r"^Why this matters", re.MULTILINE),
    "acceptance": re.compile(r"^Acceptance:", re.MULTILINE),
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def item_files(root: str | Path = DEFAULT_ROADMAP_ROOT) -> list[Path]:
    root = Path(root)
    items_root = root / "items" if (root / "items").exists() else root
    return sorted(items_root.glob("item-*.md"))


def _relative(path: Path) -> str:
    return relative_to_repo(path)


def parse_item(path: str | Path, *, root: str | Path = DEFAULT_ROADMAP_ROOT) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    heading = lines[0] if lines else ""
    parsed = HEADING_RE.match(heading)
    item: dict[str, Any] = {
        "path": _relative(path),
        "heading": heading,
        "number": None,
        "title": None,
        "status": None,
        "date": None,
        "disposition": None,
        "status_text": None,
        "active": False,
        "parse_errors": [],
        "section_presence": {},
        "checklist_count": len(CHECKLIST_RE.findall(text)),
        "open_checklist_count": len(re.findall(r"^- \[ \] ", text, flags=re.MULTILINE)),
        "checked_checklist_count": len(re.findall(r"^- \[[xX]\] ", text, flags=re.MULTILINE)),
    }
    if not parsed:
        item["parse_errors"].append("heading does not match '# N. Title [STATUS...]'")
        return item

    item["number"] = int(parsed.group("number"))
    item["title"] = parsed.group("title")
    status_text = parsed.group("status_text").strip()
    item["status_text"] = status_text
    status = STATUS_RE.match(status_text)
    if not status:
        item["parse_errors"].append("status block does not parse into status, optional date, and disposition")
        return item

    item["status"] = status.group("status")
    item["date"] = status.group("date")
    item["disposition"] = status.group("disposition") or ""
    item["active"] = item["status"] in {"OPEN", "PARTIAL"}
    item["section_presence"] = {
        key: bool(pattern.search(text))
        for key, pattern in REQUIRED_ACTIVE_MARKERS.items()
    }
    item["section_presence"]["checklist"] = item["checklist_count"] > 0
    return item


def lint_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for error in item.get("parse_errors") or []:
        issues.append({
            "severity": "error",
            "category": "roadmap_heading_parse",
            "item": item.get("number"),
            "path": item.get("path"),
            "detail": error,
        })
    if item.get("active") and not item.get("parse_errors"):
        presence = item.get("section_presence") or {}
        for key in ("goal", "source", "why", "checklist", "acceptance"):
            if not presence.get(key):
                issues.append({
                    "severity": "error",
                    "category": "active_item_missing_required_section",
                    "item": item.get("number"),
                    "path": item.get("path"),
                    "detail": f"active roadmap item is missing required {key} section",
                })
    return issues


def build_payload(
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    items = [parse_item(path, root=roadmap_root) for path in item_files(roadmap_root)]
    items.sort(key=lambda row: (row.get("number") is None, row.get("number") or 0, row.get("path") or ""))
    active_items = [row for row in items if row.get("active")]
    issues = [issue for item in items for issue in lint_item(item)]
    status_counts = Counter(row.get("status") or "UNPARSED" for row in items)
    active_status_counts = Counter(row.get("status") for row in active_items)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "roadmap_root": _relative(Path(roadmap_root)),
        "summary": {
            "item_count": len(items),
            "active_item_count": len(active_items),
            "open_item_count": active_status_counts.get("OPEN", 0),
            "partial_item_count": active_status_counts.get("PARTIAL", 0),
            "complete_item_count": status_counts.get("COMPLETE", 0),
            "lint_error_count": sum(1 for issue in issues if issue.get("severity") == "error"),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "active_items": active_items,
        "items": items,
        "lint_issues": issues,
        "status": "OK" if not issues else "ERROR",
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _item_link(item: dict[str, Any]) -> str:
    path = item.get("path") or ""
    if path.startswith("docs/roadmap/"):
        path = path.removeprefix("docs/roadmap/")
    return f"[{item.get('title')}]({path})"


def write_markdown(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    summary = payload.get("summary") or {}
    lines = [
        "# Active Roadmap Backlog",
        "",
        "Generated from numbered roadmap item files. Completed historical items",
        "remain searchable in `docs/roadmap/items/` but are intentionally omitted",
        "from this default active backlog scan.",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Items", summary.get("item_count")],
                ["Active items", summary.get("active_item_count")],
                ["OPEN", summary.get("open_item_count")],
                ["PARTIAL", summary.get("partial_item_count")],
                ["COMPLETE", summary.get("complete_item_count")],
                ["Lint errors", summary.get("lint_error_count")],
            ],
        ),
        "",
        "## Active Items",
        "",
        *markdown_table(
            ["Item", "Status", "Date", "Disposition", "File"],
            [
                [
                    item.get("number"),
                    item.get("status"),
                    item.get("date") or "-",
                    item.get("disposition") or "-",
                    _item_link(item),
                ]
                for item in payload.get("active_items") or []
            ],
        ),
        "",
        "## Lint Issues",
        "",
    ]
    issues = payload.get("lint_issues") or []
    if issues:
        lines.extend(markdown_table(
            ["Severity", "Category", "Item", "Path", "Detail"],
            [
                [
                    issue.get("severity"),
                    issue.get("category"),
                    issue.get("item") or "-",
                    issue.get("path"),
                    issue.get("detail"),
                ]
                for issue in issues
            ],
        ))
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Generate the active roadmap backlog and lint item files.")
    parser.add_argument("--roadmap-root", default=str(DEFAULT_ROADMAP_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fail-on-lint", action="store_true")
    args = parser.parse_args(argv)

    payload = build_payload(args.roadmap_root)
    json_path = write_json(args.json_out, payload)
    report_path = write_markdown(args.report_out, payload)
    print(f"Roadmap backlog: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    if args.fail_on_lint and payload["status"] != "OK":
        raise SystemExit(1)
    return payload


if __name__ == "__main__":
    main()
