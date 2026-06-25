"""Fail-closed runtime-identity reconciliation report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.reporting.serving_gates.runtime_identity_evidence import DEFAULT_SNAPSHOTS_ROOT, snapshot_runtime_segments
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("runtime_identity_reconciliation")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "runtime_identity_reconciliation.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "runtime_identity_reconciliation.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_segments(segments: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(
        segments,
        key=lambda row: (-int(row.get("row_count") or 0), str(row.get("runtime_key") or "")),
    )[:limit]


def _commit_counts(segments: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in segments:
        key = str(row.get("runtime_git_commit") or "unknown_commit")
        counts[key] = counts.get(key, 0) + int(row.get("row_count") or 0)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    target_date: str | None = None,
    segment_limit: int = 25,
) -> dict[str, Any]:
    snapshots = snapshot_runtime_segments(snapshots_root=snapshots_root, target_date=target_date)
    segments = snapshots.get("segments") or []
    mixed = bool(snapshots.get("mixed_runtime_identity"))
    status = "BLOCK" if mixed else "PASS"
    blockers = []
    if mixed:
        blockers.append({
            "category": "mixed_runtime_identity",
            "detail": (
                f"{snapshots.get('runtime_identity_count')} runtime identities cover "
                f"{snapshots.get('snapshot_row_count')} snapshot rows for {target_date or 'selected snapshots'}; "
                "automatic mixed-runtime aggregation is not reconciled"
            ),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "target_date": str(target_date) if target_date else None,
        "status": status,
        "allow_mixed_runtime_aggregation": False,
        "reconciliation_mode": "diagnostic_fail_closed",
        "mixed_runtime_identity": mixed,
        "runtime_identity_count": snapshots.get("runtime_identity_count"),
        "snapshot_row_count": snapshots.get("snapshot_row_count"),
        "commit_row_counts": _commit_counts(segments),
        "top_segments": _top_segments(segments, max(1, int(segment_limit))),
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "pass_requirements": [
            "Provide a reviewed reconciliation that sets allow_mixed_runtime_aggregation=true.",
            "Show the mixed runtime segments are behaviorally equivalent for the scored model outputs.",
            "Or regenerate countable evidence under one runtime identity.",
        ],
        "inputs": {
            "snapshots_root": str(snapshots_root),
            "target_date": str(target_date) if target_date else None,
            "segment_limit": int(segment_limit),
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Runtime Identity Reconciliation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Target date", payload.get("target_date") or "-"],
            ["Allow mixed runtime aggregation", payload.get("allow_mixed_runtime_aggregation")],
            ["Mode", payload.get("reconciliation_mode")],
            ["Mixed runtime identity", payload.get("mixed_runtime_identity")],
            ["Runtime identities", payload.get("runtime_identity_count")],
            ["Snapshot rows", payload.get("snapshot_row_count")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", ((payload.get("first_blocker") or {}).get("detail")) or "-"],
        ],
    )
    lines += ["", "## Commit Row Counts", ""]
    lines += markdown_table(
        ["Commit", "Rows"],
        [[commit, rows] for commit, rows in (payload.get("commit_row_counts") or {}).items()],
    )
    lines += ["", "## Top Runtime Segments", ""]
    lines += markdown_table(
        ["Runtime", "Rows", "Snapshots", "Markets", "Target Dates", "Code States"],
        [
            [
                row.get("runtime_key"),
                row.get("row_count"),
                row.get("snapshot_count"),
                row.get("market_count"),
                row.get("target_date_count"),
                row.get("runtime_code_states") or {},
            ]
            for row in payload.get("top_segments") or []
        ],
    )
    lines += ["", "## Pass Requirements", ""]
    lines += [f"- {item}" for item in payload.get("pass_requirements") or []]
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed runtime identity reconciliation report.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--target-date")
    parser.add_argument("--segment-limit", type=int, default=25)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        snapshots_root=args.snapshots_root,
        target_date=args.target_date,
        segment_limit=args.segment_limit,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(
        "Runtime identity reconciliation: "
        f"{payload['status']} ({payload['blocker_count']} blocker(s))"
    )
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
