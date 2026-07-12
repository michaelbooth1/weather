from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.calibration.residual_distribution_corpus import (
    ResidualCorpusError,
    collapse_to_predeclared_checkpoints,
    materialize_residual_training_corpus,
    validate_residual_training_row,
    verify_residual_corpus_manifest,
)


def _replay(snapshot_id: str, local_time: str, *, target_date: str = "2026-07-01"):
    return {
        "schema_version": "toronto_replay_inputs_v0.1",
        "snapshot_id": snapshot_id,
        "target_date": target_date,
        "captured_at_local": local_time,
        "captured_at_utc": datetime.fromisoformat(local_time).astimezone(timezone.utc).isoformat(),
        "built_at": local_time,
        "sources": {
            "open_meteo": {
                "status": "fresh",
                "ok": True,
                "stale": False,
                "source_family": "open_meteo",
                "fetched_at": local_time,
            }
        },
    }


def test_checkpoint_selection_is_first_nonnegative_and_never_substitutes():
    rows = [
        _replay("before", "2026-07-01T07:59:00-04:00"),
        _replay("chosen", "2026-07-01T08:03:00-04:00"),
        _replay("later", "2026-07-01T08:09:00-04:00"),
    ]
    selected, excluded = collapse_to_predeclared_checkpoints(
        rows,
        target_date="2026-07-01",
        cutoff_hours=(8, 9),
        max_lateness_minutes=10,
    )
    assert [row["snapshot_id"] for row in selected] == ["chosen"]
    assert selected[0]["checkpoint_lateness_minutes"] == 3.0
    assert excluded[0]["cutoff_hour"] == 9
    assert excluded[0]["reason"] == "checkpoint_missing"


def _write_market_day(folder: Path) -> None:
    folder.mkdir(parents=True)
    settlement = {
        "market_id": "atlanta",
        "target_date": "2026-07-01",
        "settlement_unit": "F",
        "settlement_high": 95.0,
        "promotion_countable": True,
        "quality_grade": "complete",
        "winning_band_kind": "gte",
        "winning_band_value": 94,
        "winning_band_value_hi": 94,
    }
    (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    replay_rows = [
        _replay("s1", "2026-07-01T08:02:00-04:00"),
        _replay("s2", "2026-07-01T08:08:00-04:00"),
    ]
    (folder / "replay_inputs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in replay_rows),
        encoding="utf-8",
    )
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "snapshot_id",
                "bin_kind",
                "bin_value_c",
                "bin_value_hi_c",
                "range_label",
            ),
        )
        writer.writeheader()
        writer.writerows([
            {
                "snapshot_id": "s1",
                "bin_kind": "lte",
                "bin_value_c": 90,
                "bin_value_hi_c": 90,
                "range_label": "90 or below",
            },
            {
                "snapshot_id": "s1",
                "bin_kind": "gte",
                "bin_value_c": 91,
                "bin_value_hi_c": 91,
                "range_label": "91 or above",
            },
            {
                "snapshot_id": "s2",
                "bin_kind": "lte",
                "bin_value_c": 90,
                "bin_value_hi_c": 90,
                "range_label": "90 or below",
            },
        ])


def test_materializer_hashes_corpus_and_joins_label_after_features(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)

    def feature_builder(_row, **_context):
        return {
            "forecast_high_f": 93.0,
            "forecast_disagreement_f": 2.0,
            "source_failed_count": 0.0,
        }

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=feature_builder,
        generated_at_utc="2026-07-12T12:00:00+00:00",
    )
    assert len(rows) == 1
    assert rows[0]["snapshot_id"] == "s1"
    assert rows[0]["residual_target_f"] == 2.0
    assert "settlement_high_f" not in rows[0]["features"]
    assert manifest["counts"]["accepted_rows"] == 1
    assert manifest["selection_policy"]["substitution_allowed"] is False
    assert verify_residual_corpus_manifest(rows, manifest)["manifest_sha256"]


def test_outcome_or_market_fields_are_forbidden_from_features(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)

    def leaking_builder(_row, **_context):
        return {"forecast_high_f": 93.0, "settlement_distance": 2.0}

    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=leaking_builder,
    )
    assert rows == []
    assert manifest["counts"]["excluded_rows"] == 1
    assert "outcome/market-derived" in manifest["exclusions"][0]["detail"]


def test_model_nan_sentinels_are_serialized_as_explicit_null(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)
    rows, manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {
            "forecast_high_f": 93.0,
            "optional_context": float("nan"),
            "optional_context_missing": 1.0,
        },
    )
    assert rows[0]["features"]["optional_context"] is None
    assert manifest["counts"]["accepted_rows"] == 1


def test_feature_hash_tampering_fails(tmp_path):
    folder = tmp_path / "day"
    _write_market_day(folder)
    rows, _manifest = materialize_residual_training_corpus(
        [folder],
        cutoff_hours=(8,),
        feature_builder=lambda _row, **_kwargs: {"forecast_high_f": 93.0},
    )
    rows[0]["features"]["forecast_high_f"] = 99.0
    with pytest.raises(ResidualCorpusError, match="feature_sha256"):
        validate_residual_training_row(rows[0])
