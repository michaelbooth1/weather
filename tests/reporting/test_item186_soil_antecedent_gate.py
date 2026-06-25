import csv
import json

from weather.reporting.research.item186_soil_antecedent_gate import (
    SCHEMA_VERSION,
    SOIL_COLUMNS,
    WATER_COLUMNS,
    build_payload,
    write_outputs,
)


FIELDNAMES = ["schema_version", "market_id", "local_date", *SOIL_COLUMNS, *WATER_COLUMNS]


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def sidecar_row(market_id, *, water=False):
    row = {
        "schema_version": "reanalysis_synoptic_features_v0.5",
        "market_id": market_id,
        "local_date": "2026-06-01",
    }
    row.update({column: "1.0" for column in SOIL_COLUMNS})
    row.update({column: "0.0" if water else "" for column in WATER_COLUMNS})
    return row


def write_sidecar(root, station, market_id, *, water=False):
    path = root / station / "features" / "reanalysis_synoptic_features.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(sidecar_row(market_id, water=water))
    return path


def write_source_inventory(path):
    write_json(
        path,
        {
            "schema_version": "source_family_inventory_v0.1",
            "inventory": [
                {
                    "family_id": "reanalysis_synoptic",
                    "train_serve_parity_status": "PASS",
                    "promotion_decision": {"status": "PROMOTION_CANDIDATE"},
                    "promotion_lane": {
                        "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
                        "policy": "positive_markets_only",
                        "allowed_markets": ["nyc"],
                        "quarantined_markets": ["seattle"],
                    },
                    "feature_columns": [*SOIL_COLUMNS, *WATER_COLUMNS],
                }
            ],
        },
    )


def test_item186_gate_blocks_missing_water_backfill_and_settlement_gate(tmp_path):
    root = tmp_path / "reanalysis"
    write_sidecar(root, "klga", "nyc", water=False)
    write_sidecar(root, "ksea", "seattle", water=False)
    inventory = tmp_path / "source_family_inventory.json"
    write_source_inventory(inventory)

    payload = build_payload(
        reanalysis_root=root,
        source_family_inventory=inventory,
        settlement_gate=tmp_path / "missing_settlement.json",
        min_markets=2,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    blockers = {gate["gate"] for gate in payload["blockers"]}
    passes = {gate["gate"] for gate in payload["gates"] if gate["status"] == "PASS"}
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["disposition"] == "KEEP_SHADOW_DIAGNOSTIC"
    assert "sidecar_file_inventory" in passes
    assert "soil_anomaly_feature_coverage" in passes
    assert "source_family_inventory" in passes
    assert "antecedent_water_balance_backfill" in blockers
    assert "settlement_scored_family_gate" in blockers
    assert "positive_market_promotion_policy" in blockers
    assert payload["coverage"]["water_complete_rows"] == 0
    assert "Item 186 Soil Antecedent-Water Gate" in report.read_text(encoding="utf-8")


def test_item186_gate_can_pass_with_water_coverage_and_positive_market_lane(tmp_path):
    root = tmp_path / "reanalysis"
    write_sidecar(root, "klga", "nyc", water=True)
    write_sidecar(root, "ksea", "seattle", water=True)
    inventory = tmp_path / "source_family_inventory.json"
    settlement = tmp_path / "item186_settlement.json"
    write_source_inventory(inventory)
    write_json(
        settlement,
        {
            "status": "PASS",
            "settlement_scored": True,
            "promotion_lane": {
                "status": "PARTIAL_POSITIVE_MARKET_SHADOW_LANE",
                "policy": "positive_markets_only",
                "allowed_markets": ["nyc"],
                "quarantined_markets": ["seattle"],
            },
            "markets": [
                {"market_id": "nyc", "decision": "promote"},
                {"market_id": "seattle", "decision": "block"},
            ],
        },
    )

    payload = build_payload(
        reanalysis_root=root,
        source_family_inventory=inventory,
        settlement_gate=settlement,
        min_markets=2,
    )

    assert payload["status"] == "PASS"
    assert payload["promotion_allowed"] is True
    assert payload["disposition"] == "PROMOTION_READY"
    assert payload["coverage"]["water_complete_rows"] == 2
