"""Plan and apply gzip tiering for large CLOB order-book long tapes."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.operations.cleanup_preflight import build_cleanup_preflight, cleanup_manifest_for_paths
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("clob_order_book_tiering")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "clob_order_book_tiering.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "clob_order_book_tiering_report.md"
DEFAULT_MIN_FREE_BYTES = 1024 * 1024 * 1024
ORDER_BOOK_LONG = "order_books_long.csv"
ORDER_BOOK_LONG_GZIP = "order_books_long.csv.gz"
EVENT_DATE_RE = re.compile(r"\bon-([a-z]+)-(\d{1,2})-(\d{4})$")
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if not str(value).strip():
        return None
    return date.fromisoformat(str(value))


def default_settled_before() -> date:
    return datetime.now(timezone.utc).date()


def event_date_from_slug(slug: str) -> date | None:
    match = EVENT_DATE_RE.search(str(slug).lower())
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _path_text(path: Path) -> str:
    return str(path)


def _relative_text(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _assert_under_root(path: Path, root: Path) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes snapshots root: {path_resolved}") from exc


def sha256_and_line_count(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    line_count = 0
    last = b""
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            line_count += chunk.count(b"\n")
            if chunk:
                last = chunk[-1:]
    if last and last != b"\n":
        line_count += 1
    return digest.hexdigest(), line_count


def gzip_payload_sha256_and_line_count(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    line_count = 0
    last = b""
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            line_count += chunk.count(b"\n")
            if chunk:
                last = chunk[-1:]
    if last and last != b"\n":
        line_count += 1
    return digest.hexdigest(), line_count


def discover_rows(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    settled_before: str | date | None = None,
) -> list[dict[str, Any]]:
    root = Path(snapshots_root)
    cutoff = parse_date(settled_before) or default_settled_before()
    if not root.exists():
        return []
    rows = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        source = folder / ORDER_BOOK_LONG
        gzip_path = folder / ORDER_BOOK_LONG_GZIP
        if not source.exists() and not gzip_path.exists():
            continue
        event_date = event_date_from_slug(folder.name)
        settled = bool(event_date and event_date < cutoff)
        if source.exists() and gzip_path.exists():
            status = "already_tiered_source_present"
            action = "review_delete_uncompressed_after_manifest_backup"
        elif gzip_path.exists():
            status = "already_tiered"
            action = "none"
        elif event_date is None:
            status = "blocked_unknown_event_date"
            action = "review_slug_or_pass_settled_before"
        elif not settled:
            status = "blocked_active_or_unsettled"
            action = "wait_for_settlement_cutoff"
        else:
            status = "candidate"
            action = "compress_to_order_books_long_csv_gz"
        rows.append({
            "folder": _path_text(folder),
            "folder_rel": _relative_text(folder, root),
            "event_slug": folder.name,
            "event_date": event_date.isoformat() if event_date else None,
            "settled_before": cutoff.isoformat(),
            "settled": settled,
            "source_path": _path_text(source),
            "source_rel": _relative_text(source, root),
            "source_exists": source.exists(),
            "source_bytes": source.stat().st_size if source.exists() else 0,
            "gzip_path": _path_text(gzip_path),
            "gzip_rel": _relative_text(gzip_path, root),
            "gzip_exists": gzip_path.exists(),
            "gzip_bytes": gzip_path.stat().st_size if gzip_path.exists() else 0,
            "summary_present": (folder / "order_books_summary.csv").exists(),
            "raw_jsonl_present": (folder / "order_books.jsonl").exists(),
            "token_map_present": (folder / "clob_tokens.csv").exists()
            or (folder / "clob_tokens.jsonl").exists(),
            "status": status,
            "recommended_action": action,
        })
    return rows


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_payload(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    settled_before: str | date | None = None,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
) -> dict[str, Any]:
    root = Path(snapshots_root)
    cutoff = parse_date(settled_before) or default_settled_before()
    rows = discover_rows(root, settled_before=cutoff)
    candidate_rows = [row for row in rows if row.get("status") == "candidate"]
    status = "PASS" if not candidate_rows else "WARN"
    if not root.exists():
        status = "SKIPPED"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "snapshots_root": str(root),
        "snapshots_root_exists": root.exists(),
        "settled_before": cutoff.isoformat(),
        "min_free_bytes": int(min_free_bytes),
        "summary": {
            "folders_with_long_tape": len(rows),
            "candidate_files": len(candidate_rows),
            "candidate_bytes": sum(int(row.get("source_bytes") or 0) for row in candidate_rows),
            "uncompressed_files": sum(1 for row in rows if row.get("source_exists")),
            "uncompressed_bytes": sum(int(row.get("source_bytes") or 0) for row in rows),
            "gzip_files": sum(1 for row in rows if row.get("gzip_exists")),
            "gzip_bytes": sum(int(row.get("gzip_bytes") or 0) for row in rows),
            "status_counts": _status_counts(rows),
        },
        "rows": rows,
    }


def _gzip_source(source: Path, gzip_path: Path) -> dict[str, Any]:
    source_sha256, source_lines = sha256_and_line_count(source)
    tmp_path = gzip_path.with_name(gzip_path.name + ".tmp")
    if tmp_path.exists():
        raise FileExistsError(f"temporary gzip path already exists: {tmp_path}")
    try:
        with source.open("rb") as src, tmp_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                shutil.copyfileobj(src, gz, length=1024 * 1024)
        payload_sha256, payload_lines = gzip_payload_sha256_and_line_count(tmp_path)
        if payload_sha256 != source_sha256 or payload_lines != source_lines:
            raise ValueError("gzip verification failed against source bytes")
        tmp_path.replace(gzip_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return {
        "source_sha256": source_sha256,
        "source_line_count": source_lines,
        "gzip_payload_sha256": payload_sha256,
        "gzip_line_count": payload_lines,
        "gzip_bytes": gzip_path.stat().st_size,
    }


def apply_tiering(
    payload: dict[str, Any],
    *,
    delete_source: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    root = Path(payload.get("snapshots_root") or DEFAULT_SNAPSHOTS_ROOT)
    candidates = [row for row in payload.get("rows") or [] if row.get("status") == "candidate"]
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]
    actions = []
    for row in candidates:
        source = Path(row["source_path"])
        gzip_path = Path(row["gzip_path"])
        _assert_under_root(source, root)
        _assert_under_root(gzip_path, root)
        source_bytes = int(row.get("source_bytes") or 0)
        usage = shutil.disk_usage(source.parent)
        required_free = source_bytes + int(payload.get("min_free_bytes") or 0)
        action = {
            "source_path": str(source),
            "gzip_path": str(gzip_path),
            "source_bytes": source_bytes,
            "free_bytes": int(usage.free),
            "required_free_bytes": required_free,
            "delete_source": bool(delete_source),
        }
        if not source.exists():
            action["status"] = "skipped_missing_source"
        elif gzip_path.exists():
            action["status"] = "skipped_gzip_exists"
        elif int(usage.free) < required_free:
            action["status"] = "skipped_insufficient_headroom"
            action["insufficient_bytes"] = required_free - int(usage.free)
        else:
            try:
                result = _gzip_source(source, gzip_path)
                action.update(result)
                if delete_source:
                    _assert_under_root(source, root)
                    cleanup_manifest = cleanup_manifest_for_paths(
                        [source],
                        root=root,
                        classification_prefix="snapshots",
                        deletion_reason="delete verified gzip-tiered CLOB order_books_long.csv projection",
                        operator_review={
                            "approved": True,
                            "approved_by": "weather.operations.clob_order_book_tiering",
                            "approved_at_utc": utc_iso(),
                            "note": "Projection cleanup after deterministic gzip verification; raw order_books.jsonl remains canonical evidence.",
                        },
                        backup_status={},
                    )
                    preflight = build_cleanup_preflight(cleanup_manifest, root=root, backup_status={})
                    action["cleanup_preflight"] = preflight
                    if preflight.get("status") == "PASS":
                        source.unlink()
                        action["source_deleted"] = True
                    else:
                        action["source_deleted"] = False
                        action["status"] = "skipped_cleanup_preflight_block"
                else:
                    action["source_deleted"] = False
                if action.get("status") != "skipped_cleanup_preflight_block":
                    action["status"] = "compressed"
            except Exception as exc:  # noqa: BLE001 - report and continue with other candidates
                action["status"] = "failed"
                action["error"] = f"{type(exc).__name__}: {exc}"
        actions.append(action)
    blocked = [row for row in actions if row.get("status") == "skipped_insufficient_headroom"]
    failed = [row for row in actions if str(row.get("status") or "").startswith("failed")]
    if blocked:
        status = "BLOCKED"
    elif failed:
        status = "FAIL"
    else:
        status = "PASS"
    return {
        "enabled": True,
        "delete_source": bool(delete_source),
        "limit": limit,
        "status": status,
        "actions": actions,
        "summary": {
            "candidate_actions": len(actions),
            "compressed_files": sum(1 for row in actions if row.get("status") == "compressed"),
            "deleted_sources": sum(1 for row in actions if row.get("source_deleted")),
            "insufficient_headroom": len(blocked),
            "skipped_files": sum(1 for row in actions if str(row.get("status") or "").startswith("skipped")),
        },
    }


def run(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    settled_before: str | date | None = None,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    apply: bool = False,
    delete_source: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    payload = build_payload(
        snapshots_root,
        settled_before=settled_before,
        min_free_bytes=min_free_bytes,
    )
    if apply:
        apply_payload = apply_tiering(payload, delete_source=delete_source, limit=limit)
        payload["apply"] = apply_payload
        payload["status"] = apply_payload["status"]
    else:
        payload["apply"] = {"enabled": False}
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _mb(value: Any) -> str:
    return f"{int(value or 0) / (1024 * 1024):.1f}"


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# CLOB Order-Book Tiering",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Snapshots root: `{payload.get('snapshots_root')}`",
        f"Settled before: `{payload.get('settled_before')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Folders with long tape", summary.get("folders_with_long_tape")],
            ["Candidate files", summary.get("candidate_files")],
            ["Candidate MiB", _mb(summary.get("candidate_bytes"))],
            ["Uncompressed files", summary.get("uncompressed_files")],
            ["Uncompressed MiB", _mb(summary.get("uncompressed_bytes"))],
            ["Gzip files", summary.get("gzip_files")],
            ["Gzip MiB", _mb(summary.get("gzip_bytes"))],
            ["Status counts", json.dumps(summary.get("status_counts") or {}, sort_keys=True)],
        ],
    )
    rows = payload.get("rows") or []
    if rows:
        lines += ["", "## Largest Candidates", ""]
        candidates = [row for row in rows if row.get("status") == "candidate"]
        candidates.sort(key=lambda row: int(row.get("source_bytes") or 0), reverse=True)
        lines += markdown_table(
            ["Folder", "Event Date", "Source MiB", "Summary", "Raw JSONL", "Action"],
            [
                [
                    row.get("event_slug"),
                    row.get("event_date"),
                    _mb(row.get("source_bytes")),
                    row.get("summary_present"),
                    row.get("raw_jsonl_present"),
                    row.get("recommended_action"),
                ]
                for row in candidates[:20]
            ],
        )
    apply_payload = payload.get("apply") or {}
    if apply_payload.get("enabled"):
        lines += ["", "## Apply", ""]
        apply_summary = apply_payload.get("summary") or {}
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Status", apply_payload.get("status")],
                ["Compressed files", apply_summary.get("compressed_files")],
                ["Deleted sources", apply_summary.get("deleted_sources")],
                ["Insufficient headroom", apply_summary.get("insufficient_headroom")],
                ["Skipped files", apply_summary.get("skipped_files")],
            ],
        )
        actions = apply_payload.get("actions") or []
        if actions:
            lines += ["", "## Apply Actions", ""]
            lines += markdown_table(
                ["Status", "Source", "Source MiB", "Free MiB", "Required Free MiB"],
                [
                    [
                        row.get("status"),
                        Path(row.get("source_path") or "").name,
                        _mb(row.get("source_bytes")),
                        _mb(row.get("free_bytes")),
                        _mb(row.get("required_free_bytes")),
                    ]
                    for row in actions[:50]
                ],
            )
    lines.append("")
    return "\n".join(lines)


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def write_outputs(payload: dict[str, Any], out: str | Path, report: str | Path) -> tuple[Path, Path]:
    return write_json(out, payload), write_report(report, payload)


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--settled-before", default="")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def cmd_plan(args: argparse.Namespace) -> int:
    payload = run(
        snapshots_root=args.snapshots_root,
        settled_before=args.settled_before or None,
        min_free_bytes=args.min_free_bytes,
        apply=False,
    )
    out, report = write_outputs(payload, args.out, args.report)
    print(f"CLOB order-book tiering: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] in {"PASS", "WARN", "SKIPPED"} else 2


def cmd_apply(args: argparse.Namespace) -> int:
    payload = run(
        snapshots_root=args.snapshots_root,
        settled_before=args.settled_before or None,
        min_free_bytes=args.min_free_bytes,
        apply=True,
        delete_source=args.delete_source,
        limit=args.limit,
    )
    out, report = write_outputs(payload, args.out, args.report)
    print(f"CLOB order-book tiering: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] == "PASS" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or apply CLOB order-book long-table gzip tiering.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = add_common_args(sub.add_parser("plan"))
    plan.set_defaults(func=cmd_plan)
    apply_parser = add_common_args(sub.add_parser("apply"))
    apply_parser.add_argument("--delete-source", action="store_true")
    apply_parser.add_argument("--limit", type=int, default=None)
    apply_parser.set_defaults(func=cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
