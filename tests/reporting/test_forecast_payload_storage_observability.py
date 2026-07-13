import csv

from weather.reporting.data_quality.data_layer_audit_collectors import (
    forecast_payload_summary_for_folder,
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
