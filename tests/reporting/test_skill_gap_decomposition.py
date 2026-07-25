import csv
import json
from pathlib import Path

import pytest

from weather.reporting.research.skill_gap_decomposition import (
    build_decomposition,
    isotonic_murphy_decomposition,
    render_report,
    write_outputs,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _partition(
    *,
    market_id: str,
    target_date: str,
    snapshot_id: str,
    captured_at_local: str,
    model_probabilities=(0.3, 0.4, 0.3),
    market_probabilities=(0.05, 0.9, 0.05),
    variant_id="candidate",
) -> list[dict]:
    bands = (
        ("lte:79.0", "lte", "79.0", 0, "cool_side"),
        ("eq:80.0-81.0", "eq", "80.0", 1, "near_forecast"),
        ("gte:82.0", "gte", "82.0", 0, "warm_side"),
    )
    return [
        {
            "variant_id": variant_id,
            "market_id": market_id,
            "target_date": target_date,
            "snapshot_id": snapshot_id,
            "captured_at_local": captured_at_local,
            "band_key": band_key,
            "bin_type": bin_type,
            "bin_value": bin_value,
            "probability": model_probability,
            "market_yes": market_probability,
            "outcome": outcome,
            "forecast_disagreement_bucket": "high_disagreement",
            "forecast_source_count_bucket": "two_sources",
            "forecast_bucket_pressure": pressure,
            "source_freshness_state": "all_fresh",
        }
        for (
            band_key,
            bin_type,
            bin_value,
            outcome,
            pressure,
        ), model_probability, market_probability in zip(
            bands,
            model_probabilities,
            market_probabilities,
        )
    ]


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    rows_path = tmp_path / "candidate_rows.csv"
    rows = []
    rows.extend(
        _partition(
            market_id="alpha",
            target_date="2026-07-01",
            snapshot_id="s03",
            captured_at_local="2026-07-01T03:10:00-04:00",
        )
    )
    rows.extend(
        _partition(
            market_id="alpha",
            target_date="2026-07-01",
            snapshot_id="s04",
            captured_at_local="2026-07-01T04:10:00-04:00",
            model_probabilities=(0.35, 0.3, 0.35),
        )
    )
    rows.extend(
        _partition(
            market_id="alpha",
            target_date="2026-07-01",
            snapshot_id="s09",
            captured_at_local="2026-07-01T09:10:00-04:00",
            model_probabilities=(0.2, 0.6, 0.2),
        )
    )
    rows.extend(
        _partition(
            market_id="beta",
            target_date="2026-07-01",
            snapshot_id="s21",
            captured_at_local="2026-07-01T21:10:00-04:00",
            model_probabilities=(0.1, 0.8, 0.1),
        )
    )
    _write_csv(rows_path, rows)

    snapshots_root = tmp_path / "snapshots"
    manifest_path = tmp_path / "corpus.json"
    entries = []
    for market_id, folder_name, snapshot_rows in (
        (
            "alpha",
            "alpha-event",
            [
                ("s03", "2026-07-01T03:10:00-04:00", 79.6, 2.5, 70.0),
                ("s04", "2026-07-01T04:10:00-04:00", 81.4, 3.0, 72.0),
                ("s09", "2026-07-01T09:10:00-04:00", 80.5, 1.0, 80.0),
            ],
        ),
        (
            "beta",
            "beta-event",
            [("s21", "2026-07-01T21:10:00-04:00", 80.5, 0.5, 75.0)],
        ),
    ):
        entries.append(
            {
                "market_id": market_id,
                "target_date": "2026-07-01",
                "folder_relative_to_snapshots_root": folder_name,
            }
        )
        _write_csv(
            snapshots_root / folder_name / "features_long.csv",
            [
                {
                    "snapshot_id": snapshot_id,
                    "target_date": "2026-07-01",
                    "captured_at_local": captured,
                    "forecast_high": forecast_high,
                    "forecast_disagreement": disagreement,
                    "forecast_source_count": 2,
                    "current_temp": current_temp,
                    "warming_rate_2h": 1.0,
                    "high_so_far": current_temp,
                }
                for snapshot_id, captured, forecast_high, disagreement, current_temp in snapshot_rows
            ],
        )
    manifest_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return rows_path, manifest_path, snapshots_root


def test_isotonic_murphy_decomposition_is_exact_and_order_invariant():
    pairs = [(0.5, 0), (0.5, 1), (0.5, 0), (0.5, 1)]

    result = isotonic_murphy_decomposition(pairs)
    reversed_result = isotonic_murphy_decomposition(reversed(pairs))

    assert result == reversed_result
    assert result["brier"] == pytest.approx(0.25)
    assert result["reliability"] == pytest.approx(0.0)
    assert result["resolution"] == pytest.approx(0.0)
    assert result["uncertainty"] == pytest.approx(0.25)
    assert result["identity_residual"] == pytest.approx(0.0, abs=1e-15)


def test_isotonic_murphy_decomposition_separates_resolution_and_miscalibration():
    perfect = isotonic_murphy_decomposition([(0.0, 0), (1.0, 1)])
    climatology = isotonic_murphy_decomposition([(0.5, 0), (0.5, 1)])
    inverted = isotonic_murphy_decomposition([(1.0, 0), (0.0, 1)])

    assert perfect["brier"] == pytest.approx(0.0)
    assert perfect["reliability"] == pytest.approx(0.0)
    assert perfect["resolution"] == pytest.approx(perfect["uncertainty"])
    assert climatology["reliability"] == pytest.approx(0.0)
    assert climatology["resolution"] == pytest.approx(0.0)
    assert inverted["reliability"] == pytest.approx(0.75)
    assert inverted["resolution"] == pytest.approx(0.0)
    assert inverted["identity_residual"] == pytest.approx(0.0, abs=1e-15)


def test_build_decomposition_reports_named_cuts_taxonomy_and_exact_gap(tmp_path):
    rows_path, manifest_path, snapshots_root = _fixture(tmp_path)

    payload = build_decomposition(
        variant_rows=rows_path,
        corpus_manifest=manifest_path,
        snapshots_root=snapshots_root,
        generated_at_utc="2026-07-25T00:00:00+00:00",
        code_identity="test",
    )
    report = render_report(payload)
    json_out, report_out, cases_out = write_outputs(
        payload,
        json_out=tmp_path / "out" / "decomposition.json",
        report_out=tmp_path / "out" / "decomposition.md",
        worst_cases_out=tmp_path / "out" / "worst.csv",
    )

    assert payload["schema_version"] == "skill_gap_decomposition_v0.1"
    assert payload["status"] == "PASS"
    assert payload["population"]["complete_partition_count"] == 4
    assert payload["population"]["scored_row_count"] == 12
    assert payload["population"]["candidate_mass_violation_count"] == 0
    assert payload["population"]["feature_context"]["feature_snapshot_count"] == 4
    assert payload["population"]["feature_context"]["feature_file_count"] == 2
    assert payload["population"]["feature_context"]["feature_input_set_sha256"]
    assert payload["population"]["matched_feature_partition_count"] == 4
    assert payload["population"]["hourly_normalized_partition_count"] == 4
    assert [row["scope"] for row in payload["decomposition"]] == [
        "pooled",
        "alpha",
        "beta",
    ]
    assert payload["global_pool_sensitivity"]["scope"] == "global_pool_sensitivity"

    pooled = payload["decomposition"][0]
    comparison = pooled["comparison"]
    assert comparison["brier_gap"] > 0
    assert comparison["gap_identity_residual"] == pytest.approx(0.0, abs=1e-12)
    assert pooled["model"]["identity_residual"] == pytest.approx(0.0, abs=1e-12)
    assert pooled["market"]["identity_residual"] == pytest.approx(0.0, abs=1e-12)

    named = {row["label"]: row for row in payload["named_hour_slices"]}
    assert set(named) == {
        "all_hours",
        "predawn_03_05",
        "primary_09_14",
        "lock_in_20_23",
    }
    assert named["predawn_03_05"]["market_days"] == 1
    assert named["primary_09_14"]["n"] == 3
    assert {row["label"] for row in payload["lead_time_slices"]} >= {
        "18-24h",
        "12-18h",
        "00-03h",
    }

    worst = payload["worst_market_day_hours"][0]
    assert worst["forecast_disagreement_bucket"] == "high_disagreement"
    assert worst["boundary_proximity_bucket"] != "unknown"
    assert worst["observation_volatility_bucket"] != "unknown"
    assert payload["taxonomy"]["regime"]
    assert payload["information_requirements"]
    assert "primary_09_14" in report
    assert json_out.exists()
    assert report_out.exists()
    assert cases_out.exists()


def test_hour_slices_use_earliest_capture_per_market_day_hour(tmp_path):
    rows_path, manifest_path, snapshots_root = _fixture(tmp_path)
    rows = list(csv.DictReader(rows_path.open("r", encoding="utf-8", newline="")))
    rows.extend(
        _partition(
            market_id="alpha",
            target_date="2026-07-01",
            snapshot_id="s09b",
            captured_at_local="2026-07-01T09:40:00-04:00",
            model_probabilities=(0.45, 0.1, 0.45),
        )
    )
    _write_csv(rows_path, rows)

    feature_path = snapshots_root / "alpha-event" / "features_long.csv"
    feature_rows = list(
        csv.DictReader(feature_path.open("r", encoding="utf-8", newline=""))
    )
    feature_rows.append(
        {
            **feature_rows[-1],
            "snapshot_id": "s09b",
            "captured_at_local": "2026-07-01T09:40:00-04:00",
        }
    )
    _write_csv(feature_path, feature_rows)

    payload = build_decomposition(
        variant_rows=rows_path,
        corpus_manifest=manifest_path,
        snapshots_root=snapshots_root,
    )
    named = {row["label"]: row for row in payload["named_hour_slices"]}

    assert payload["decomposition"][0]["model"]["n"] == 15
    assert named["all_hours"]["n"] == 15
    assert named["primary_09_14"]["n"] == 3
    assert payload["population"]["hourly_normalized_partition_count"] == 4


def test_build_decomposition_fails_closed_on_probability_mass_violation(tmp_path):
    rows_path, manifest_path, snapshots_root = _fixture(tmp_path)
    rows = list(csv.DictReader(rows_path.open("r", encoding="utf-8", newline="")))
    rows[0]["probability"] = "0.2"
    _write_csv(rows_path, rows)

    with pytest.raises(ValueError, match="probability mass violated"):
        build_decomposition(
            variant_rows=rows_path,
            corpus_manifest=manifest_path,
            snapshots_root=snapshots_root,
        )


def test_build_decomposition_requires_explicit_variant_selection(tmp_path):
    rows_path, manifest_path, snapshots_root = _fixture(tmp_path)
    rows = list(csv.DictReader(rows_path.open("r", encoding="utf-8", newline="")))
    rows[-1]["variant_id"] = "other"
    _write_csv(rows_path, rows)

    with pytest.raises(ValueError, match="multiple variant_id"):
        build_decomposition(
            variant_rows=rows_path,
            corpus_manifest=manifest_path,
            snapshots_root=snapshots_root,
        )


def test_build_decomposition_preserves_timestamp_collision_in_scoring(tmp_path):
    rows_path, manifest_path, snapshots_root = _fixture(tmp_path)
    collision = _partition(
        market_id="alpha",
        target_date="2026-07-01",
        snapshot_id="s03",
        captured_at_local="2026-07-01T03:10:00-04:00",
        model_probabilities=(0.15, 0.2, 0.15),
        market_probabilities=(0.025, 0.45, 0.025),
    )
    collision += _partition(
        market_id="alpha",
        target_date="2026-07-01",
        snapshot_id="s03",
        captured_at_local="2026-07-01T03:10:00-04:00",
        model_probabilities=(0.15, 0.2, 0.15),
        market_probabilities=(0.025, 0.45, 0.025),
    )
    _write_csv(rows_path, collision)

    payload = build_decomposition(
        variant_rows=rows_path,
        corpus_manifest=manifest_path,
        snapshots_root=snapshots_root,
    )

    assert payload["status"] == "PASS"
    assert payload["population"]["complete_partition_count"] == 1
    assert payload["population"]["scored_row_count"] == 6
    assert payload["population"]["non_single_winner_partition_count"] == 1
    assert payload["population"]["candidate_mass_violation_count"] == 0
    assert payload["decomposition"][0]["sharpness"]["partition_count"] == 0
