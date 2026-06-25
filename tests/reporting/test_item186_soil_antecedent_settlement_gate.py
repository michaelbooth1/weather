import csv
import json

from weather.reporting.research.item186_soil_antecedent_gate import SOIL_COLUMNS, WATER_COLUMNS
from weather.reporting.research.item186_soil_antecedent_settlement_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


FIELDNAMES = ["schema_version", "market_id", "local_date", *SOIL_COLUMNS, *WATER_COLUMNS]


def write_sidecar(root, station, market_id, *, water=True):
    path = root / station / "features" / "reanalysis_synoptic_features.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": "reanalysis_synoptic_features_v0.5",
        "market_id": market_id,
        "local_date": "2026-06-13",
    }
    row.update({column: "1.0" for column in SOIL_COLUMNS})
    row.update({column: "0.0" if water else "" for column in WATER_COLUMNS})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)
    return path


def write_feature_gate(path, market_id, delta_brier):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "item27_feature_value_gate_v0.1",
                "market": market_id,
                "promotion_decisions": [
                    {
                        "family": "reanalysis_synoptic",
                        "n": 10,
                        "full_brier": 0.20,
                        "ablated_brier": 0.20 + delta_brier,
                        "delta_brier": delta_brier,
                        "delta_logloss": delta_brier,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_settlement_gate_builds_positive_market_lane(tmp_path):
    root = tmp_path / "reanalysis"
    write_sidecar(root, "kaus", "austin", water=True)
    write_sidecar(root, "ksea", "seattle", water=True)
    gates = {
        "austin": write_feature_gate(tmp_path / "austin_gate.json", "austin", 0.02),
        "seattle": write_feature_gate(tmp_path / "seattle_gate.json", "seattle", -0.01),
    }

    payload = build_payload(
        reanalysis_root=root,
        feature_gate_paths=gates,
        required_markets=["austin", "seattle"],
        min_markets=2,
    )
    _, report = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "PASS"
    assert payload["settlement_scored"] is True
    assert payload["promotion_lane"]["policy"] == "positive_markets_only"
    assert payload["promotion_lane"]["allowed_markets"] == ["austin"]
    assert payload["promotion_lane"]["quarantined_markets"] == ["seattle"]
    assert "Item 186 Soil Antecedent-Water Settlement Gate" in report.read_text(encoding="utf-8")


def test_settlement_gate_blocks_missing_water_coverage(tmp_path):
    root = tmp_path / "reanalysis"
    write_sidecar(root, "kaus", "austin", water=False)
    write_sidecar(root, "ksea", "seattle", water=True)
    gates = {
        "austin": write_feature_gate(tmp_path / "austin_gate.json", "austin", 0.02),
        "seattle": write_feature_gate(tmp_path / "seattle_gate.json", "seattle", 0.01),
    }

    payload = build_payload(
        reanalysis_root=root,
        feature_gate_paths=gates,
        required_markets=["austin", "seattle"],
        min_markets=2,
    )

    blockers = {row["blocker"] for row in payload["blockers"]}
    assert payload["status"] == "BLOCK"
    assert "missing_soil_or_water_coverage" in blockers
    assert payload["promotion_lane"]["allowed_markets"] == ["seattle"]
