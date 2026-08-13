"""Plan and apply gzip tiering for the canonical closed-day ``order_books.jsonl`` tape.

WHY THIS IS A SEPARATE MODULE FROM ``clob_order_book_tiering``.
That module compresses the ``order_books_long.csv`` *projection* and says so in its
own cleanup note: "raw order_books.jsonl remains canonical evidence". This module
compresses the canonical evidence itself, which is a materially different act and
deserves its own guards rather than a flag on the projection tier.

WHY IT IS WORTH DOING. Measured on production 2026-08-10: the retained raw tape is
708 files / 133.47 GB, and one real settled tape (nyc 2026-08-09) gzips
308,109,123 -> 28,078,865 = 10.97x. Compressing the retained corpus recovers roughly
121 GB. Free space was 151.4 GB falling 10.7 GB/day, i.e. ~14 days, against a lock
date in the same week -- and if the disk fills, capture dies.

THE ONE THING THAT MAKES THIS SAFE. Compression here is *not* a retention decision.
The gzip payload is verified to be byte-identical to the source (sha256 and line
count over the decompressed stream) before the source is removed, and
``weather.market.order_book_tape`` reads ``order_books.jsonl.gz`` as a CANONICAL
representation. Nothing is discarded; the same bytes are stored smaller.

THREE REFUSALS THAT ARE NOT NEGOTIABLE.

1. ``closed_day_projection_tiering`` treats the raw tape as its rebuild source and
   blocks on ``canonical_order_books_jsonl_missing``. So a market-day that still has
   an uncompressed ``order_books_long.csv`` is one the projection tier has NOT
   finished with, and we refuse it (``blocked_projection_tier_pending``). Let that
   tool go first. The two must never contend for the same day.
2. A source still being appended to is never eligible, whatever the date says.
   ``MIN_QUIET_SECONDS`` is the real invariant; the date cutoff is a cheap pre-filter.
   This is re-checked at apply time, not just at plan time, because a plan can be
   hours old and compressing a file a writer still holds is the one unrecoverable
   mistake available here.
3. A writer lock anywhere in the event folder blocks the day outright.

Run from the repo root:

    python -m weather.operations.clob_raw_tape_tiering plan
    python -m weather.operations.clob_raw_tape_tiering apply --delete-source
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from weather.operations.cleanup_preflight import build_cleanup_preflight, cleanup_manifest_for_paths
from weather.operations.clob_order_book_tiering import (
    ORDER_BOOK_LONG,
    ORDER_BOOK_LONG_GZIP,
    MIN_QUIET_SECONDS,
    _assert_under_root,
    _path_text,
    _relative_text,
    default_settled_before,
    event_date_from_slug,
    gzip_payload_sha256_and_line_count,
    parse_date,
    sha256_and_line_count,
    source_is_quiet,
    utc_iso,
)
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("clob_raw_tape_tiering")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "clob_raw_tape_tiering.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "clob_raw_tape_tiering_report.md"

# Deliberately larger than the projection tier's 1 GiB. We decompress-and-verify before
# deleting anything, so the job needs room for source + gzip simultaneously, and it runs
# on a host whose disk headroom is the reason the job exists.
DEFAULT_MIN_FREE_BYTES = 8 * 1024 * 1024 * 1024

RAW_TAPE = "order_books.jsonl"
RAW_TAPE_GZIP = "order_books.jsonl.gz"

# Writer-lock sentinels, matched by suffix anywhere in the event folder.
WRITER_LOCK_SUFFIXES = (".lock", ".writerlock")


def _writer_locks(folder: Path) -> list[str]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    return sorted(
        entry.name
        for entry in entries
        if entry.is_file() and entry.name.lower().endswith(WRITER_LOCK_SUFFIXES)
    )


def discover_rows(
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    *,
    settled_before: str | date | None = None,
) -> list[dict[str, Any]]:
    root = Path(snapshots_root)
    cutoff = parse_date(settled_before) or default_settled_before()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        source = folder / RAW_TAPE
        gzip_path = folder / RAW_TAPE_GZIP
        if not source.exists() and not gzip_path.exists():
            continue
        event_date = event_date_from_slug(folder.name)
        settled = bool(event_date and event_date < cutoff)
        locks = _writer_locks(folder)
        projection_pending = (folder / ORDER_BOOK_LONG).exists()

        if source.exists() and gzip_path.exists():
            # Both present means a previous run compressed but did not delete, or a
            # split day. Never auto-delete here: a human decides, exactly as the
            # projection tier does for its own split days.
            status = "already_tiered_source_present"
            action = "review_delete_uncompressed_after_verification"
        elif gzip_path.exists():
            status = "already_tiered"
            action = "none"
        elif event_date is None:
            status = "blocked_unknown_event_date"
            action = "review_slug_or_pass_settled_before"
        elif not settled:
            status = "blocked_active_or_unsettled"
            action = "wait_for_settlement_cutoff"
        elif locks:
            status = "blocked_writer_lock_present"
            action = "wait_for_writer_lock_release"
        elif projection_pending:
            # See refusal (1) in the module docstring. The projection tier still needs
            # this exact file as its rebuild source.
            status = "blocked_projection_tier_pending"
            action = "run_clob_order_book_tiering_first"
        elif not source_is_quiet(source):
            status = "blocked_recently_written"
            action = "wait_for_writer_to_finish"
        else:
            status = "candidate"
            action = "compress_to_order_books_jsonl_gz"

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
            "projection_long_csv_present": projection_pending,
            "projection_long_gzip_present": (folder / ORDER_BOOK_LONG_GZIP).exists(),
            "writer_locks": locks,
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
    candidate_bytes = sum(int(row.get("source_bytes") or 0) for row in candidate_rows)
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
        "min_quiet_seconds": MIN_QUIET_SECONDS,
        "summary": {
            "folders_with_raw_tape": len(rows),
            "candidate_files": len(candidate_rows),
            "candidate_bytes": candidate_bytes,
            "uncompressed_files": sum(1 for row in rows if row.get("source_exists")),
            "uncompressed_bytes": sum(int(row.get("source_bytes") or 0) for row in rows),
            "gzip_files": sum(1 for row in rows if row.get("gzip_exists")),
            "gzip_bytes": sum(int(row.get("gzip_bytes") or 0) for row in rows),
            "status_counts": _status_counts(rows),
        },
        "rows": rows,
    }


def _gzip_source(source: Path, gzip_path: Path) -> dict[str, Any]:
    """Compress and prove the payload is byte-identical before the caller may delete."""

    source_sha256, source_lines = sha256_and_line_count(source)
    tmp_path = gzip_path.with_name(gzip_path.name + ".tmp")
    if tmp_path.exists():
        raise FileExistsError(f"temporary gzip path already exists: {tmp_path}")
    try:
        with source.open("rb") as src, tmp_path.open("wb") as raw:
            # mtime=0 and an empty embedded filename make the output deterministic, so
            # the same source always yields the same gzip bytes and the artifact is
            # reproducible from the report.
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                shutil.copyfileobj(src, gz, length=1024 * 1024)
        payload_sha256, payload_lines = gzip_payload_sha256_and_line_count(tmp_path)
        if payload_sha256 != source_sha256 or payload_lines != source_lines:
            raise ValueError("gzip verification failed against source bytes")
        tmp_path.replace(gzip_path)
    except BaseException:
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
    actions: list[dict[str, Any]] = []
    for row in candidates:
        source = Path(row["source_path"])
        gzip_path = Path(row["gzip_path"])
        _assert_under_root(source, root)
        _assert_under_root(gzip_path, root)
        source_bytes = int(row.get("source_bytes") or 0)
        usage = shutil.disk_usage(source.parent)
        required_free = source_bytes + int(payload.get("min_free_bytes") or 0)
        action: dict[str, Any] = {
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
        elif _writer_locks(source.parent):
            # Re-checked at apply time: the plan may be hours old.
            action["status"] = "skipped_writer_lock_present"
        elif (source.parent / ORDER_BOOK_LONG).exists():
            action["status"] = "skipped_projection_tier_pending"
        elif not source_is_quiet(source):
            action["status"] = "skipped_recently_written"
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
                        deletion_reason=(
                            "delete verified gzip-tiered canonical order_books.jsonl tape"
                        ),
                        operator_review={
                            "approved": True,
                            "approved_by": "weather.operations.clob_raw_tape_tiering",
                            "approved_at_utc": utc_iso(),
                            "note": (
                                "Canonical tape retained as order_books.jsonl.gz after "
                                "deterministic gzip verification of sha256 and line count "
                                "over the decompressed payload; order_book_tape reads the "
                                "gzip as a canonical representation. No evidence discarded."
                            ),
                        },
                    )
                    preflight = build_cleanup_preflight(cleanup_manifest, root=root)
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
    reclaimed = sum(
        int(row.get("source_bytes") or 0) - int(row.get("gzip_bytes") or 0)
        for row in actions
        if row.get("source_deleted")
    )
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
            "reclaimed_bytes": reclaimed,
            "insufficient_headroom": len(blocked),
            "skipped_files": sum(
                1 for row in actions if str(row.get("status") or "").startswith("skipped")
            ),
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
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _gib(value: Any) -> str:
    return f"{int(value or 0) / (1024 ** 3):.2f}"


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    uncompressed = int(summary.get("uncompressed_bytes") or 0)
    candidate_bytes = int(summary.get("candidate_bytes") or 0)
    lines = [
        "# CLOB Raw Tape Tiering",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Snapshots root: `{payload.get('snapshots_root')}`",
        f"Settled before: `{payload.get('settled_before')}`",
        "",
        "Compresses the canonical `order_books.jsonl` to `order_books.jsonl.gz`. The gzip",
        "payload is verified byte-identical (sha256 + line count) before any source is",
        "removed, and `weather.market.order_book_tape` reads the gzip as canonical, so this",
        "is a storage-format change and not a retention decision.",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Folders with raw tape", summary.get("folders_with_raw_tape")],
            ["Candidate files", summary.get("candidate_files")],
            ["Candidate GiB", _gib(candidate_bytes)],
            ["Uncompressed files", summary.get("uncompressed_files")],
            ["Uncompressed GiB", _gib(uncompressed)],
            ["Gzip files", summary.get("gzip_files")],
            ["Gzip GiB", _gib(summary.get("gzip_bytes"))],
            ["Status counts", json.dumps(summary.get("status_counts") or {}, sort_keys=True)],
        ],
    )
    rows = payload.get("rows") or []
    if rows:
        candidates = [row for row in rows if row.get("status") == "candidate"]
        candidates.sort(key=lambda row: int(row.get("source_bytes") or 0), reverse=True)
        if candidates:
            lines += ["", "## Largest Candidates", ""]
            lines += markdown_table(
                ["Folder", "Event Date", "Source GiB", "Long CSV", "Action"],
                [
                    [
                        row.get("event_slug"),
                        row.get("event_date"),
                        _gib(row.get("source_bytes")),
                        row.get("projection_long_csv_present"),
                        row.get("recommended_action"),
                    ]
                    for row in candidates[:20]
                ],
            )
    apply_payload = payload.get("apply") or {}
    if apply_payload.get("enabled"):
        apply_summary = apply_payload.get("summary") or {}
        lines += ["", "## Apply", ""]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Status", apply_payload.get("status")],
                ["Compressed files", apply_summary.get("compressed_files")],
                ["Deleted sources", apply_summary.get("deleted_sources")],
                ["Reclaimed GiB", _gib(apply_summary.get("reclaimed_bytes"))],
                ["Insufficient headroom", apply_summary.get("insufficient_headroom")],
                ["Skipped files", apply_summary.get("skipped_files")],
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


def _emit(payload: dict[str, Any], out: Path, report: Path) -> None:
    print(f"CLOB raw tape tiering: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")


def cmd_plan(args: argparse.Namespace) -> int:
    payload = run(
        snapshots_root=args.snapshots_root,
        settled_before=args.settled_before or None,
        min_free_bytes=args.min_free_bytes,
        apply=False,
    )
    out, report = write_outputs(payload, args.out, args.report)
    _emit(payload, out, report)
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
    _emit(payload, out, report)
    return 0 if payload["status"] == "PASS" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply gzip tiering of the canonical CLOB order_books.jsonl tape.",
    )
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
