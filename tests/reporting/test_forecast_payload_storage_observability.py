import csv

from weather.forecast_payload_contracts import (
    forecast_fanout_coordination_id,
    forecast_fanout_receipt_ref,
)
from weather.reporting.data_quality.data_layer_audit_collectors import (
    forecast_payload_summary_for_folder,
    snapshot_audit,
)


def test_forecast_payload_inventory_separates_logical_physical_and_avoided_bytes(tmp_path):
    path = tmp_path / "forecast_payloads_long.csv"
    rows = [
        {
            "source": "nbm_probabilistic_tmax",
            "payload_hash": "a" * 64,
            "payload_bytes": 100,
            "logical_referenced_bytes": 100,
            "physical_bytes_written": 100,
            "avoided_bytes": 0,
            "payload_blob_created": True,
            "payload_blob_reused": False,
            "payload_storage_scope": "shared_market_invariant",
        },
        {
            "source": "nbm_probabilistic_tmax",
            "payload_hash": "a" * 64,
            "payload_bytes": 100,
            "logical_referenced_bytes": 100,
            "physical_bytes_written": 0,
            "avoided_bytes": 100,
            "payload_blob_created": False,
            "payload_blob_reused": True,
            "payload_storage_scope": "shared_market_invariant",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = forecast_payload_summary_for_folder(tmp_path)

    assert summary["row_count"] == 2
    assert summary["unique_payload_count"] == 1
    assert summary["logical_referenced_bytes"] == 200
    assert summary["physical_bytes_written"] == 100
    assert summary["avoided_bytes"] == 100
    assert summary["created_blob_count"] == 1
    assert summary["reused_blob_count"] == 1
    assert summary["shared_manifest_row_count"] == 2


def test_forecast_payload_inventory_deduplicates_follower_only_receipt_evidence(
    tmp_path,
):
    path = tmp_path / "forecast_payloads_long.csv"
    identity = {
        "source": "nbm_probabilistic_tmax",
        "request_key": "request-key",
        "cycle_key": "nbm-nbp:20260713T00Z",
        "scope_key": "fleet-pass",
    }
    evidence_id = forecast_fanout_coordination_id(**identity)
    rows = []
    for market_id in ("boston", "nyc"):
        rows.append(
            {
                "market_id": market_id,
                "source": identity["source"],
                "request_key": identity["request_key"],
                "cycle_key": identity["cycle_key"],
                "single_fetch_scope": identity["scope_key"],
                "single_fetch_fetched": False,
                "single_fetch_reused": True,
                "single_fetch_coordination_status": (
                    "cross_process_receipt_reused"
                ),
                "payload_hash": "b" * 64,
                "payload_bytes": 100,
                "logical_referenced_bytes": 100,
                "physical_bytes_written": 0,
                "avoided_bytes": 100,
                "payload_blob_created": False,
                "payload_blob_reused": True,
                "payload_storage_scope": "shared_market_invariant",
                "coordinator_evidence_id": evidence_id,
                "coordinator_receipt_ref": forecast_fanout_receipt_ref(
                    evidence_id
                ),
                "coordinator_receipt_sha256": "c" * 64,
                "coordinator_attribution_status": "available",
                "coordinator_network_fetch_count": 1,
                "coordinator_payload_blob_created": True,
                "coordinator_payload_blob_reused": False,
                "coordinator_physical_bytes_written": 100,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = forecast_payload_summary_for_folder(tmp_path)

    assert summary["logical_referenced_bytes"] == 200
    assert summary["physical_bytes_written"] == 100
    assert summary["avoided_bytes"] == 100
    assert summary["coordinator_evidence_count"] == 1


def test_snapshot_audit_deduplicates_follower_receipt_across_market_folders(
    tmp_path,
):
    identity = {
        "source": "nbm_probabilistic_tmax",
        "request_key": "request-key",
        "cycle_key": "nbm-nbp:20260713T00Z",
        "scope_key": "fleet-pass",
    }
    evidence_id = forecast_fanout_coordination_id(**identity)
    for market_id, slug in (
        ("atlanta", "highest-temperature-in-atlanta-on-july-13-2026"),
        ("nyc", "highest-temperature-in-nyc-on-july-13-2026"),
    ):
        folder = tmp_path / slug
        folder.mkdir()
        with (folder / "snapshots_long.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "snapshot_id",
                    "captured_at_local",
                    "event_slug",
                    "market_yes",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "snapshot_id": f"{market_id}-snapshot",
                    "captured_at_local": "2026-07-13T14:00:00-04:00",
                    "event_slug": slug,
                    "market_yes": "0.5",
                }
            )
        row = {
            "market_id": market_id,
            "source": identity["source"],
            "request_key": identity["request_key"],
            "cycle_key": identity["cycle_key"],
            "single_fetch_scope": identity["scope_key"],
            "single_fetch_fetched": False,
            "single_fetch_reused": True,
            "single_fetch_coordination_status": "cross_process_receipt_reused",
            "payload_hash": "b" * 64,
            "payload_bytes": 100,
            "logical_referenced_bytes": 100,
            "physical_bytes_written": 0,
            "avoided_bytes": 100,
            "payload_blob_created": False,
            "payload_blob_reused": True,
            "payload_storage_scope": "shared_market_invariant",
            "coordinator_evidence_id": evidence_id,
            "coordinator_receipt_ref": forecast_fanout_receipt_ref(evidence_id),
            "coordinator_receipt_sha256": "c" * 64,
            "coordinator_attribution_status": "available",
            "coordinator_network_fetch_count": 1,
            "coordinator_payload_blob_created": True,
            "coordinator_payload_blob_reused": False,
            "coordinator_physical_bytes_written": 100,
        }
        with (folder / "forecast_payloads_long.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

    audit = snapshot_audit(snapshots_root=tmp_path)
    summary = audit["forecast_payloads"]

    assert summary["logical_referenced_bytes"] == 200
    assert summary["physical_bytes_written"] == 100
    assert summary["avoided_bytes"] == 100
    assert summary["network_fetch_count"] == 1
    assert summary["coordinator_evidence_count"] == 1
    assert all(
        not any(key.startswith("_") for key in row["forecast_payloads"])
        for row in audit["folders"]
    )


def test_forecast_payload_inventory_supports_more_than_live_status_bound(tmp_path):
    path = tmp_path / "forecast_payloads_long.csv"
    rows = []
    for index in range(33):
        identity = {
            "source": "nbm_probabilistic_tmax",
            "request_key": "request-key",
            "cycle_key": "nbm-nbp:20260713T00Z",
            "scope_key": f"fleet-pass-{index}",
        }
        evidence_id = forecast_fanout_coordination_id(**identity)
        created = index == 0
        rows.append(
            {
                "source": identity["source"],
                "request_key": identity["request_key"],
                "cycle_key": identity["cycle_key"],
                "single_fetch_scope": identity["scope_key"],
                "single_fetch_fetched": True,
                "single_fetch_reused": False,
                "single_fetch_coordination_status": (
                    "cross_process_holder_published"
                ),
                "payload_hash": "b" * 64,
                "payload_bytes": 100,
                "logical_referenced_bytes": 100,
                "physical_bytes_written": 100 if created else 0,
                "avoided_bytes": 0 if created else 100,
                "payload_blob_created": created,
                "payload_blob_reused": not created,
                "payload_storage_scope": "shared_market_invariant",
                "coordinator_evidence_id": evidence_id,
                "coordinator_receipt_ref": forecast_fanout_receipt_ref(
                    evidence_id
                ),
                "coordinator_receipt_sha256": "c" * 64,
                "coordinator_attribution_status": "available",
                "coordinator_network_fetch_count": 1,
                "coordinator_payload_blob_created": created,
                "coordinator_payload_blob_reused": not created,
                "coordinator_physical_bytes_written": 100 if created else 0,
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = forecast_payload_summary_for_folder(tmp_path)

    assert summary["coordinator_evidence_count"] == 33
    assert summary["network_fetch_count"] == 33
    assert summary["physical_bytes_written"] == 100
    assert summary["avoided_bytes"] == 3200
