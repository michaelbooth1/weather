"""Runtime-identity segmentation for model and trading evidence."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from weather.market.market_config import date_from_event_slug
from weather.paths import data_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("runtime_identity_evidence")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_MM_RUNS_ROOT = data_path("mm_runs")
DEFAULT_TAKER_RUNS_ROOT = data_path("taker_runs")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "runtime_identity_evidence.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "runtime_identity_evidence_report.md"
DEFAULT_RECONCILIATION = DEFAULT_BACKTEST_ROOT / "runtime_identity_reconciliation.json"


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def runtime_key_from_fields(fields):
    fields = fields or {}
    commit = (
        fields.get("runtime_git_commit")
        or fields.get("git_commit")
        or fields.get("commit")
        or "unknown_commit"
    )
    dirty = (
        fields.get("runtime_dirty_fingerprint")
        or fields.get("dirty_fingerprint")
        or ("dirty" if str(fields.get("runtime_git_dirty") or fields.get("git_dirty")).lower() == "true" else "clean")
    )
    source = (
        fields.get("runtime_source_fingerprint")
        or fields.get("source_fingerprint")
        or "unknown_source"
    )
    return f"{commit}|dirty:{dirty}|src:{source}"


def runtime_fields_from_snapshot_row(row):
    return {
        "runtime_identity_schema_version": row.get("runtime_identity_schema_version"),
        "runtime_git_branch": row.get("runtime_git_branch"),
        "runtime_git_commit": row.get("runtime_git_commit"),
        "runtime_git_dirty": row.get("runtime_git_dirty"),
        "runtime_dirty_fingerprint": row.get("runtime_dirty_fingerprint"),
        "runtime_source_fingerprint": row.get("runtime_source_fingerprint"),
        "runtime_code_state": row.get("runtime_code_state"),
    }


def runtime_fields_from_run_payload(payload):
    runtime = (payload or {}).get("runtime_identity") or {}
    if runtime.get("current_identity"):
        runtime = runtime.get("current_identity") or {}
    if runtime.get("process_identity"):
        runtime = runtime.get("process_identity") or {}
    return {
        "runtime_identity_schema_version": runtime.get("schema_version"),
        "runtime_git_branch": runtime.get("git_branch"),
        "runtime_git_commit": runtime.get("git_commit"),
        "runtime_git_dirty": runtime.get("git_dirty"),
        "runtime_dirty_fingerprint": runtime.get("dirty_fingerprint"),
        "runtime_source_fingerprint": runtime.get("source_fingerprint"),
        "runtime_code_state": (payload or {}).get("runtime_code_state") or "run_level",
    }


def _segment_rows(counter):
    rows = []
    for key, item in sorted(counter.items(), key=lambda pair: (-pair[1]["row_count"], pair[0])):
        rows.append({
            "runtime_key": key,
            "row_count": item["row_count"],
            "snapshot_count": len(item.get("snapshot_ids") or set()),
            "market_count": len(item.get("markets") or set()),
            "markets": sorted(item.get("markets") or []),
            "target_date_count": len(item.get("target_dates") or set()),
            "target_dates": sorted(item.get("target_dates") or []),
            "runtime_git_commit": item.get("runtime_git_commit") or "",
            "runtime_git_dirty": item.get("runtime_git_dirty") or "",
            "runtime_dirty_fingerprint": item.get("runtime_dirty_fingerprint") or "",
            "runtime_source_fingerprint": item.get("runtime_source_fingerprint") or "",
            "runtime_code_states": dict(sorted((item.get("runtime_code_states") or Counter()).items())),
        })
    return rows


def _snapshot_target_date_scope(row, *, folder_target_date, target_date):
    """Return whether a snapshot row belongs to an exact target-date scope.

    Current tapes do not necessarily carry a ``target_date`` column.  For those
    legacy rows, the registered event folder is the only trustworthy fallback:
    an unparseable or differently dated enclosing folder must not leak the row
    into the requested day's runtime evidence.
    """
    row_target_date = str(row.get("target_date") or "").strip()
    requested = str(target_date).strip() if target_date not in (None, "") else ""
    if not requested:
        return True, "unscoped", row_target_date or None

    if row_target_date:
        if row_target_date == requested:
            return True, "row_target_date", row_target_date
        return False, "row_target_date_mismatch", None

    if folder_target_date is None:
        return False, "missing_target_date_unproven_enclosing_event_date", None

    folder_target_date_text = folder_target_date.isoformat()
    if folder_target_date_text != requested:
        return False, "missing_target_date_enclosing_event_date_mismatch", None

    # A parseable row event slug is corroborating metadata.  If it conflicts
    # with the folder, fail closed instead of trusting either provenance source.
    event_slug = str(row.get("event_slug") or "").strip()
    event_target_date = date_from_event_slug(event_slug) if event_slug else None
    if event_target_date is not None and event_target_date != folder_target_date:
        return False, "missing_target_date_event_folder_conflict", None

    return True, "enclosing_event_folder", folder_target_date_text


def snapshot_runtime_segments(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, target_date=None):
    root = Path(snapshots_root)
    counter = defaultdict(lambda: {
        "row_count": 0,
        "snapshot_ids": set(),
        "markets": set(),
        "target_dates": set(),
        "runtime_code_states": Counter(),
    })
    total = 0
    scanned_total = 0
    included_by_provenance = Counter()
    excluded_by_reason = Counter()
    for path in sorted(root.glob("*/snapshots_long.csv")):
        folder_target_date = date_from_event_slug(path.parent.name)
        for row in read_csv_rows(path):
            scanned_total += 1
            included, scope_reason, effective_target_date = _snapshot_target_date_scope(
                row,
                folder_target_date=folder_target_date,
                target_date=target_date,
            )
            if not included:
                excluded_by_reason[scope_reason] += 1
                continue
            included_by_provenance[scope_reason] += 1
            fields = runtime_fields_from_snapshot_row(row)
            key = runtime_key_from_fields(fields)
            item = counter[key]
            item["row_count"] += 1
            total += 1
            if row.get("snapshot_id"):
                item["snapshot_ids"].add(row.get("snapshot_id"))
            if row.get("market_id"):
                item["markets"].add(row.get("market_id"))
            if effective_target_date:
                item["target_dates"].add(effective_target_date)
            item["runtime_git_commit"] = fields.get("runtime_git_commit") or item.get("runtime_git_commit")
            item["runtime_git_dirty"] = fields.get("runtime_git_dirty") or item.get("runtime_git_dirty")
            item["runtime_dirty_fingerprint"] = fields.get("runtime_dirty_fingerprint") or item.get("runtime_dirty_fingerprint")
            item["runtime_source_fingerprint"] = fields.get("runtime_source_fingerprint") or item.get("runtime_source_fingerprint")
            item["runtime_code_states"][fields.get("runtime_code_state") or "unknown"] += 1
    segments = _segment_rows(counter)
    return {
        "target_date": str(target_date) if target_date else None,
        "snapshot_row_count": total,
        "target_date_scope": {
            "mode": "exact_target_date" if target_date else "all_rows",
            "requested_target_date": str(target_date) if target_date else None,
            "scanned_snapshot_row_count": scanned_total,
            "included_snapshot_row_count": total,
            "excluded_snapshot_row_count": scanned_total - total,
            "included_by_provenance": dict(sorted(included_by_provenance.items())),
            "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        },
        "runtime_identity_count": len(segments),
        "mixed_runtime_identity": len(segments) > 1,
        "segments": segments,
    }


def snapshot_runtime_segments_from_manifest(manifest):
    counter = defaultdict(lambda: {
        "row_count": 0,
        "snapshot_ids": set(),
        "markets": set(),
        "target_dates": set(),
        "runtime_code_states": Counter(),
    })
    total = 0
    for entry in (manifest or {}).get("entries") or []:
        path = entry.get("snapshot_tape_path")
        if not path:
            continue
        pinned_ids = {str(item) for item in entry.get("snapshot_ids") or []}
        for row in read_csv_rows(path):
            snapshot_id = str(row.get("snapshot_id") or "")
            if pinned_ids and snapshot_id not in pinned_ids:
                continue
            fields = runtime_fields_from_snapshot_row(row)
            key = runtime_key_from_fields(fields)
            item = counter[key]
            item["row_count"] += 1
            total += 1
            if snapshot_id:
                item["snapshot_ids"].add(snapshot_id)
            market_id = row.get("market_id") or entry.get("market_id")
            if market_id:
                item["markets"].add(market_id)
            target_date = row.get("target_date") or entry.get("target_date")
            if target_date:
                item["target_dates"].add(target_date)
            item["runtime_git_commit"] = fields.get("runtime_git_commit") or item.get("runtime_git_commit")
            item["runtime_git_dirty"] = fields.get("runtime_git_dirty") or item.get("runtime_git_dirty")
            item["runtime_dirty_fingerprint"] = fields.get("runtime_dirty_fingerprint") or item.get("runtime_dirty_fingerprint")
            item["runtime_source_fingerprint"] = fields.get("runtime_source_fingerprint") or item.get("runtime_source_fingerprint")
            item["runtime_code_states"][fields.get("runtime_code_state") or "unknown"] += 1
    segments = _segment_rows(counter)
    return {
        "target_date": None,
        "scope": "promotion_manifest",
        "snapshot_row_count": total,
        "runtime_identity_count": len(segments),
        "mixed_runtime_identity": len(segments) > 1,
        "segments": segments,
    }


def run_runtime_segments(root, target_date=None):
    counter = defaultdict(lambda: {"run_count": 0, "rows": []})
    for path in sorted(Path(root).glob("*/*/run_summary.json")):
        payload = read_json(path, {}) or {}
        if target_date and str(payload.get("target_date") or "") != str(target_date):
            continue
        fields = runtime_fields_from_run_payload(payload)
        key = runtime_key_from_fields(fields)
        counter[key]["run_count"] += 1
        counter[key]["rows"].append({
            "run_id": payload.get("run_id") or path.parent.name,
            "target_date": payload.get("target_date"),
            "path": str(path),
            "runtime_git_commit": fields.get("runtime_git_commit") or "",
            "runtime_source_fingerprint": fields.get("runtime_source_fingerprint") or "",
        })
    return [
        {"runtime_key": key, "run_count": item["run_count"], "runs": item["rows"]}
        for key, item in sorted(counter.items(), key=lambda pair: (-pair[1]["run_count"], pair[0]))
    ]


def reconciliation_allows_mixed_runtime(path=DEFAULT_RECONCILIATION, target_date=None):
    payload = read_json(path, {}) or {}
    if not payload:
        return False, "missing"
    if target_date and payload.get("target_date") not in {None, "", str(target_date)}:
        return False, "target_date_mismatch"
    allowed = bool(payload.get("allow_mixed_runtime_aggregation")) and str(payload.get("status") or "").upper() == "PASS"
    return allowed, payload.get("status") or "unknown"


def build_runtime_identity_evidence(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    target_date=None,
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    taker_runs_root=DEFAULT_TAKER_RUNS_ROOT,
    reconciliation_path=DEFAULT_RECONCILIATION,
    snapshot_manifest=None,
):
    snapshots = (
        snapshot_runtime_segments_from_manifest(snapshot_manifest)
        if snapshot_manifest is not None
        else snapshot_runtime_segments(snapshots_root=snapshots_root, target_date=target_date)
    )
    reconciliation_allowed, reconciliation_status = reconciliation_allows_mixed_runtime(
        reconciliation_path,
        target_date=target_date,
    )
    mixed = bool(snapshots.get("mixed_runtime_identity"))
    blocking = mixed and not reconciliation_allowed
    warnings = []
    if mixed:
        warnings.append({
            "code": "mixed_runtime_identity",
            "detail": (
                f"{snapshots.get('runtime_identity_count')} runtime identities found for "
                f"{target_date or 'selected snapshots'}"
            ),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "target_date": str(target_date) if target_date else None,
        "status": "BLOCK" if blocking else "PASS",
        "broad_claim_allowed": not blocking,
        "promotion_claim_allowed": not blocking,
        "mixed_runtime_identity": mixed,
        "runtime_identity_count": snapshots.get("runtime_identity_count"),
        "snapshot_row_count": snapshots.get("snapshot_row_count"),
        "blocking_reason": "mixed_runtime_identity_unsegmented" if blocking else None,
        "reconciliation_status": reconciliation_status,
        "reconciliation_allowed": reconciliation_allowed,
        "warnings": warnings,
        "snapshots": snapshots,
        "trading_runs": {
            "market_making": run_runtime_segments(mm_runs_root, target_date=target_date),
            "taker": run_runtime_segments(taker_runs_root, target_date=target_date),
        },
    }


def render_report(payload):
    snapshots = payload.get("snapshots") or {}
    target_date_scope = snapshots.get("target_date_scope") or {}
    trading_runs = payload.get("trading_runs") or {}
    lines = [
        "# Runtime Identity Evidence",
        "",
        f"Target date: `{payload.get('target_date') or '-'}`",
        f"Status: **{payload.get('status')}**",
        f"Mixed runtime identity: `{payload.get('mixed_runtime_identity')}`",
        f"Runtime identities: `{payload.get('runtime_identity_count')}`",
        f"Snapshot rows: `{payload.get('snapshot_row_count')}`",
        f"Snapshot rows scanned: `{target_date_scope.get('scanned_snapshot_row_count', payload.get('snapshot_row_count'))}`",
        f"Snapshot rows excluded by target-date scope: `{target_date_scope.get('excluded_snapshot_row_count', 0)}`",
        f"Legacy rows admitted by enclosing event folder: `{(target_date_scope.get('included_by_provenance') or {}).get('enclosing_event_folder', 0)}`",
        f"Blocking reason: `{payload.get('blocking_reason') or '-'}`",
        "",
        "## Snapshot Segments",
        "",
    ]
    lines += markdown_table(
        ["Commit", "Rows", "Snapshots", "Markets", "Source Fingerprint", "Code States"],
        [
            [
                row.get("runtime_git_commit") or row.get("runtime_key"),
                row.get("row_count"),
                row.get("snapshot_count"),
                row.get("market_count"),
                row.get("runtime_source_fingerprint") or "-",
                row.get("runtime_code_states") or {},
            ]
            for row in snapshots.get("segments") or []
        ],
    )
    lines += [
        "",
        "## Trading Run Segments",
        "",
    ]
    for name, rows in sorted(trading_runs.items()):
        lines += [
            f"### {name.replace('_', ' ').title()}",
            "",
        ]
        lines += markdown_table(
            ["Runtime", "Runs"],
            [[row.get("runtime_key"), row.get("run_count")] for row in rows],
        )
        lines.append("")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Segment evidence by runtime identity.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--target-date")
    parser.add_argument("--mm-runs-root", default=str(DEFAULT_MM_RUNS_ROOT))
    parser.add_argument("--taker-runs-root", default=str(DEFAULT_TAKER_RUNS_ROOT))
    parser.add_argument("--reconciliation", default=str(DEFAULT_RECONCILIATION))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fail-on-block", action="store_true")
    args = parser.parse_args(argv)
    payload = build_runtime_identity_evidence(
        snapshots_root=args.snapshots_root,
        target_date=args.target_date,
        mm_runs_root=args.mm_runs_root,
        taker_runs_root=args.taker_runs_root,
        reconciliation_path=args.reconciliation,
    )
    write_json(args.json_out, payload)
    Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report_out).write_text(render_report(payload), encoding="utf-8")
    print(f"Runtime identity evidence: {payload['status']}")
    print(f"JSON written to {args.json_out}")
    print(f"Report written to {args.report_out}")
    return 1 if args.fail_on_block and payload["status"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
