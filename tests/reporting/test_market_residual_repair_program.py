import csv
import json
from pathlib import Path

from weather.reporting.market.market_residual_repair_program import (
    SCHEMA_VERSION,
    build_payload,
    render_report,
    write_outputs,
)


FIELDS = [
    "variant_id",
    "variant_family",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "bin_type",
    "bin_value",
    "settlement_distance_bucket",
]


def row(
    variant,
    family,
    market,
    snapshot,
    band,
    probability,
    current,
    market_yes,
    outcome,
    captured="2026-06-13T04:00:00-04:00",
):
    bin_value = band.split(":", 1)[1].split("-", 1)[0]
    return {
        "variant_id": variant,
        "variant_family": family,
        "market_id": market,
        "target_date": "2026-06-13",
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "captured_at_local": captured,
        "bin_type": "eq",
        "bin_value": bin_value,
        "settlement_distance_bucket": "0" if outcome else "1",
    }


def snapshot(
    variant,
    family,
    market,
    snapshot_id,
    *,
    winner_probability,
    current_winner_probability,
    market_winner_probability,
    one_above_probability=0.12,
    current_one_above_probability=0.20,
    market_one_above_probability=0.15,
    captured="2026-06-13T04:00:00-04:00",
):
    return [
        row(variant, family, market, snapshot_id, "eq:70.0-71.0", 0.12, 0.20, 0.15, 0, captured),
        row(
            variant,
            family,
            market,
            snapshot_id,
            "eq:72.0-73.0",
            winner_probability,
            current_winner_probability,
            market_winner_probability,
            1,
            captured,
        ),
        row(
            variant,
            family,
            market,
            snapshot_id,
            "eq:74.0-75.0",
            one_above_probability,
            current_one_above_probability,
            market_one_above_probability,
            0,
            captured,
        ),
    ]


def write_rows(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_build_payload_creates_market_manifests_and_rejected_registry(tmp_path):
    good = tmp_path / "good.csv"
    bad = tmp_path / "bad.csv"
    known_no_go = tmp_path / "known_no_go.json"
    write_rows(good, [
        *snapshot(
            "good_v1",
            "new_market_signal",
            "seattle",
            "sea-good",
            winner_probability=0.72,
            current_winner_probability=0.42,
            market_winner_probability=0.70,
        ),
        *snapshot(
            "good_v1",
            "new_market_signal",
            "seattle",
            "sea-ramp",
            winner_probability=0.50,
            current_winner_probability=0.50,
            market_winner_probability=0.52,
            captured="2026-06-13T10:00:00-04:00",
        ),
    ])
    write_rows(bad, [
        *snapshot(
            "bad_v1",
            "rejected_alpha",
            "seattle",
            "sea-bad",
            winner_probability=0.20,
            current_winner_probability=0.42,
            market_winner_probability=0.70,
            one_above_probability=0.35,
            current_one_above_probability=0.20,
            market_one_above_probability=0.15,
        ),
        *snapshot(
            "bad_v1",
            "rejected_alpha",
            "nyc",
            "nyc-bad",
            winner_probability=0.20,
            current_winner_probability=0.42,
            market_winner_probability=0.70,
            one_above_probability=0.35,
            current_one_above_probability=0.20,
            market_one_above_probability=0.15,
        ),
    ])
    known_no_go.write_text(
        json.dumps({
            "schema_version": "blocked_market_variant_basket_no_go_v0.1",
            "status": "NO_GO",
            "blocked_markets": ["nyc"],
            "blocked_market_count": 1,
            "detail": "known basket failed",
        }),
        encoding="utf-8",
    )

    payload = build_payload(
        [good, bad],
        markets=("seattle", "nyc"),
        known_no_go_paths=[known_no_go],
    )
    outputs = write_outputs(
        payload,
        tmp_path / "program.json",
        tmp_path / "program.md",
        manifest_dir=tmp_path / "manifests",
        rejected_registry_out=tmp_path / "registry.json",
    )
    report = render_report(payload)
    registry = json.loads(Path(outputs["rejected_registry"]).read_text(encoding="utf-8"))

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert len(payload["manifests"]) == 2
    recommendations = {
        row["market_id"]: row
        for row in payload["promotion_allowlist_recommendations"]
    }
    assert recommendations["seattle"]["action"] == "KEEP_SHADOW"
    assert recommendations["nyc"]["action"] == "BLOCK_CANDIDATE"
    assert recommendations["nyc"]["serving_behavior"] == "current_or_shadow"
    assert len(outputs["manifests"]) == 2
    assert all(path.exists() for path in outputs["manifests"])
    assert registry["entry_count"] >= 2
    assert "existing_variant_basket_selection" in registry["repair_family_counts"]
    assert "rejected_alpha" in registry["repair_family_counts"]
    assert "Market-Specific Early-Hour Residual Repair Program" in report
