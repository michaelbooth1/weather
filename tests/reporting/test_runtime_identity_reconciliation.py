import csv
import tempfile
from pathlib import Path

from weather.reporting.runtime_identity_reconciliation import build_payload, render_report


def write_snapshot_rows(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "snapshot_id",
        "market_id",
        "target_date",
        "runtime_git_commit",
        "runtime_git_dirty",
        "runtime_source_fingerprint",
        "runtime_code_state",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row(snapshot_id, commit, source):
    return {
        "snapshot_id": snapshot_id,
        "market_id": "toronto",
        "target_date": "2026-06-24",
        "runtime_git_commit": commit,
        "runtime_git_dirty": "False",
        "runtime_source_fingerprint": source,
        "runtime_code_state": "current",
    }


def test_runtime_identity_reconciliation_blocks_mixed_runtime_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        snapshots = Path(tmp) / "snapshots"
        write_snapshot_rows(
            snapshots / "highest-temperature-in-toronto-on-june-24-2026" / "snapshots_long.csv",
            [
                row("s1", "commit-a", "source-a"),
                row("s2", "commit-a", "source-a"),
                row("s3", "commit-b", "source-b"),
            ],
        )

        payload = build_payload(snapshots_root=snapshots, target_date="2026-06-24")
        report = render_report(payload)

    assert payload["schema_version"] == "runtime_identity_reconciliation_v0.1"
    assert payload["status"] == "BLOCK"
    assert payload["allow_mixed_runtime_aggregation"] is False
    assert payload["mixed_runtime_identity"] is True
    assert payload["runtime_identity_count"] == 2
    assert payload["commit_row_counts"] == {"commit-a": 2, "commit-b": 1}
    assert "automatic mixed-runtime aggregation is not reconciled" in payload["first_blocker"]["detail"]
    assert "Runtime Identity Reconciliation" in report
    assert "Provide a reviewed reconciliation" in report


def test_runtime_identity_reconciliation_passes_when_single_runtime_needs_no_mixed_allowance():
    with tempfile.TemporaryDirectory() as tmp:
        snapshots = Path(tmp) / "snapshots"
        write_snapshot_rows(
            snapshots / "highest-temperature-in-toronto-on-june-24-2026" / "snapshots_long.csv",
            [
                row("s1", "commit-a", "source-a"),
                row("s2", "commit-a", "source-a"),
            ],
        )

        payload = build_payload(snapshots_root=snapshots, target_date="2026-06-24")

    assert payload["status"] == "PASS"
    assert payload["allow_mixed_runtime_aggregation"] is False
    assert payload["mixed_runtime_identity"] is False
    assert payload["blocker_count"] == 0
