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
INDEX_HEADING_RE = re.compile(r"^(?P<level>#{2,6})\s+(?P<title>.+?)\s*$")
INDEX_ROW_RE = re.compile(
    r"^\|\s*(?P<number>\d+)\s*\|\s*\[(?P<label>.+)\]\((?P<link>[^)]+)\)\s*\|\s*$"
)
INDEX_LABEL_RE = re.compile(r"^(?P<title>.+) \[(?P<status_text>[^\]]+)\]$")
STATUS_RE = re.compile(
    r"^(?P<status>OPEN|PARTIAL|COMPLETE)"
    r"(?: (?P<date>\d{4}-\d{2}-\d{2}))?"
    r"(?: - (?P<disposition>.*))?$"
)
OWNER_PACKAGE_RE = re.compile(
    r"^(?:Owner/package|Owner|Package):\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
CHECKLIST_RE = re.compile(r"^- \[[ xX]\] ", re.MULTILINE)
BLOCKED_MARKER_RE = re.compile(r"\bBLOCK(?:ED|S|ING)?\b", re.IGNORECASE)
COMPLETION_NOTES_RE = re.compile(
    r"^(?:##\s+.*completion notes|completion notes:)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
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


def _is_non_primary_index_section(section: str) -> bool:
    normalized = section.lower().replace("-", " ")
    return "cross" in normalized and ("link" in normalized or "reference" in normalized)


def parse_roadmap_index(root: str | Path = DEFAULT_ROADMAP_ROOT) -> dict[str, Any]:
    root = Path(root)
    path = root / "ROADMAP.md"
    if not path.exists():
        return {
            "path": _relative(path),
            "exists": False,
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    section = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        heading = INDEX_HEADING_RE.match(line)
        if heading:
            section = heading.group("title")
            continue

        parsed = INDEX_ROW_RE.match(line)
        if not parsed:
            continue

        link = parsed.group("link").strip()
        label = parsed.group("label").strip()
        row: dict[str, Any] = {
            "number": int(parsed.group("number")),
            "label": label,
            "title": None,
            "status_text": None,
            "link": link,
            "target_path": _relative(root / link),
            "line": line_number,
            "section": section,
            "primary": not _is_non_primary_index_section(section),
            "parse_errors": [],
        }
        label_match = INDEX_LABEL_RE.match(label)
        if not label_match:
            row["parse_errors"].append("index row label does not match 'Title [STATUS...]'")
        else:
            row["title"] = label_match.group("title")
            row["status_text"] = label_match.group("status_text").strip()
        rows.append(row)

    return {
        "path": _relative(path),
        "exists": True,
        "rows": rows,
    }


def _owner_package(text: str) -> str:
    match = OWNER_PACKAGE_RE.search(text)
    return match.group("value").strip() if match else ""


def parse_item(path: str | Path, *, root: str | Path = DEFAULT_ROADMAP_ROOT) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
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
        "owner_package": _owner_package(text),
        "status_text": None,
        "active": False,
        "parse_errors": [],
        "section_presence": {},
        "completion_notes_present": bool(COMPLETION_NOTES_RE.search(text)),
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


def item_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("number"),
        "title": item.get("title"),
        "status": item.get("status"),
        "date": item.get("date"),
        "disposition": item.get("disposition") or "",
        "owner_package": item.get("owner_package") or "",
        "path": item.get("path"),
    }


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
    if item.get("status") == "COMPLETE" and not item.get("parse_errors"):
        if not item.get("completion_notes_present"):
            issues.append({
                "severity": "error",
                "category": "complete_item_missing_completion_notes",
                "item": item.get("number"),
                "path": item.get("path"),
                "detail": "complete roadmap item is missing a completion notes section",
            })
    return issues


def lint_roadmap_index(items: list[dict[str, Any]], index: dict[str, Any]) -> list[dict[str, Any]]:
    if not index.get("exists"):
        return []

    issues: list[dict[str, Any]] = []
    rows = index.get("rows") or []
    item_by_path = {item.get("path"): item for item in items if item.get("path")}
    items_by_number: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        number = item.get("number")
        if number is not None:
            items_by_number.setdefault(number, []).append(item)

    primary_rows_by_number: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        number = row.get("number")
        if row.get("primary") and number is not None:
            primary_rows_by_number.setdefault(number, []).append(row)

        for error in row.get("parse_errors") or []:
            issues.append({
                "severity": "error",
                "category": "roadmap_index_row_parse",
                "item": number,
                "path": index.get("path"),
                "detail": f"line {row.get('line')}: {error}",
            })

        target = item_by_path.get(row.get("target_path"))
        if target is None:
            issues.append({
                "severity": "error",
                "category": "roadmap_index_orphan_link",
                "item": number,
                "path": index.get("path"),
                "detail": f"line {row.get('line')}: index link {row.get('link')} does not resolve to an item file",
            })
            continue

        if target.get("number") != number:
            issues.append({
                "severity": "error",
                "category": "roadmap_index_number_link_mismatch",
                "item": number,
                "path": index.get("path"),
                "detail": (
                    f"line {row.get('line')}: row number {number} links to item "
                    f"{target.get('number')} at {row.get('link')}"
                ),
            })

        if row.get("title") is not None and target.get("title") is not None and row.get("title") != target.get("title"):
            issues.append({
                "severity": "error",
                "category": "roadmap_index_title_mismatch",
                "item": number,
                "path": index.get("path"),
                "detail": (
                    f"line {row.get('line')}: index title {row.get('title')!r} "
                    f"does not match item heading {target.get('title')!r}"
                ),
            })

        if (
            row.get("status_text") is not None
            and target.get("status_text") is not None
            and row.get("status_text") != target.get("status_text")
        ):
            issues.append({
                "severity": "error",
                "category": "roadmap_index_status_mismatch",
                "item": number,
                "path": index.get("path"),
                "detail": (
                    f"line {row.get('line')}: index status {row.get('status_text')!r} "
                    f"does not match item heading {target.get('status_text')!r}"
                ),
            })

    for number, matching_items in sorted(items_by_number.items()):
        if len(matching_items) > 1:
            issues.append({
                "severity": "error",
                "category": "duplicate_item_number",
                "item": number,
                "path": ", ".join(str(item.get("path")) for item in matching_items),
                "detail": f"item number {number} appears in multiple item files",
            })

        rows_for_item = primary_rows_by_number.get(number, [])
        if not rows_for_item:
            issues.append({
                "severity": "error",
                "category": "roadmap_index_missing_primary_row",
                "item": number,
                "path": index.get("path"),
                "detail": f"item {number} has no primary row in ROADMAP.md",
            })
        elif len(rows_for_item) > 1:
            locations = ", ".join(
                f"line {row.get('line')} ({row.get('section') or 'unsectioned'})"
                for row in rows_for_item
            )
            issues.append({
                "severity": "error",
                "category": "roadmap_index_duplicate_primary_row",
                "item": number,
                "path": index.get("path"),
                "detail": f"item {number} has {len(rows_for_item)} primary ROADMAP.md rows: {locations}",
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
    roadmap_index = parse_roadmap_index(roadmap_root)
    issues = [issue for item in items for issue in lint_item(item)]
    issues.extend(lint_roadmap_index(items, roadmap_index))
    status_counts = Counter(row.get("status") or "UNPARSED" for row in items)
    active_status_counts = Counter(row.get("status") for row in active_items)
    roadmap_index_rows = roadmap_index.get("rows") or []
    metadata_manifest = [item_metadata(item) for item in items]
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
            "roadmap_index_row_count": len(roadmap_index_rows),
            "roadmap_index_primary_row_count": sum(1 for row in roadmap_index_rows if row.get("primary")),
            "metadata_manifest_count": len(metadata_manifest),
            "lint_error_count": sum(1 for issue in issues if issue.get("severity") == "error"),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "active_items": active_items,
        "metadata_manifest": metadata_manifest,
        "items": items,
        "roadmap_index": roadmap_index,
        "lint_issues": issues,
        "status": "OK" if not issues else "ERROR",
    }


def item_has_blocked_marker(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("status_text", "disposition")
    )
    return bool(BLOCKED_MARKER_RE.search(text))


def summarize_roadmap_status(
    roadmap_root: str | Path = DEFAULT_ROADMAP_ROOT,
    *,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    payload = build_payload(roadmap_root, generated_at_utc=generated_at_utc)
    active_items = payload.get("active_items") or []
    active_item_rows = [
        {
            "number": item.get("number"),
            "title": item.get("title"),
            "status": item.get("status"),
            "date": item.get("date"),
            "disposition": item.get("disposition") or "",
            "blocked": item_has_blocked_marker(item),
            "owner_package": item.get("owner_package") or "",
            "open_checklist_count": item.get("open_checklist_count") or 0,
            "checked_checklist_count": item.get("checked_checklist_count") or 0,
            "path": item.get("path"),
        }
        for item in active_items
    ]
    open_item_rows = [row for row in active_item_rows if row["status"] == "OPEN"]
    active_blocked_count = sum(1 for item in active_item_rows if item["blocked"])
    open_blocked_count = sum(1 for item in open_item_rows if item["blocked"])
    summary = payload.get("summary") or {}
    return {
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "roadmap_root": payload.get("roadmap_root"),
        "status": payload.get("status"),
        "total_item_count": summary.get("item_count", 0),
        "closed_item_count": summary.get("complete_item_count", 0),
        "active_item_count": len(active_item_rows),
        "partial_item_count": summary.get("partial_item_count", 0),
        "open_item_count": len(open_item_rows),
        "active_blocked_item_count": active_blocked_count,
        "active_unblocked_item_count": len(active_item_rows) - active_blocked_count,
        "open_blocked_item_count": open_blocked_count,
        "open_unblocked_item_count": len(open_item_rows) - open_blocked_count,
        "lint_error_count": summary.get("lint_error_count", 0),
        "active_items": active_item_rows,
        "open_items": open_item_rows,
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
                ["ROADMAP rows", summary.get("roadmap_index_row_count")],
                ["ROADMAP primary rows", summary.get("roadmap_index_primary_row_count")],
                ["Metadata manifest rows", summary.get("metadata_manifest_count")],
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
