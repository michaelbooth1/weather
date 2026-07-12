import hashlib
import json
import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch

from weather.operations.density_live_replay_parity import (
    SCHEMA_VERSION,
    build_diagnostic,
    render_markdown,
)


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_bounded_density_diagnostic_reproduces_legacy_unit_bug_and_repair_parity():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact_path = root / "density.pkl"
        with artifact_path.open("wb") as handle:
            pickle.dump(
                {
                    "prediction_mode": "continuous_density_f",
                    "schema_version": "fixture_density",
                    "feature_schema_version": "fixture_features",
                    "models": {},
                },
                handle,
            )
        artifact_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        folder = root / "highest-temperature-in-toronto-on-july-10-2026"
        folder.mkdir()
        snapshot_id = "fixture-snapshot"
        bands = [
            {"bin_kind": "lte", "bin_value_c": 20, "bin_value_hi_c": 20},
            {"bin_kind": "eq", "bin_value_c": 21, "bin_value_hi_c": 21},
            {"bin_kind": "gte", "bin_value_c": 22, "bin_value_hi_c": 22},
        ]
        _write_jsonl(
            folder / "snapshots.jsonl",
            [
                {
                    "snapshot_id": snapshot_id,
                    "event_slug": folder.name,
                    "captured_at_utc": "2026-07-10T12:00:00+00:00",
                    "feature_schema_version": "fixture_features",
                    "feature_vector": {
                        "feature_schema_version": "fixture_features",
                        "cutoff_hour": 12,
                        "high_so_far": 20.0,
                        "forecast_high": 21.0,
                    },
                    "bands": bands,
                },
            ],
        )
        _write_jsonl(
            folder / "replay_inputs.jsonl",
            [
                {
                    "schema_version": "legacy_replay_fixture",
                    "snapshot_id": snapshot_id,
                },
            ],
        )
        tape_rows = []
        for key, probability in (
            ("lte_20c", 0.0),
            ("eq_21c", 0.0),
            ("gte_22c", 1.0),
        ):
            tape_rows.append(
                {
                    "schema_version": "legacy_live_fixture",
                    "snapshot_id": snapshot_id,
                    "variant_id": "density-fixture",
                    "band_key": key,
                    "prediction_status": "predicted",
                    "variant_probability": probability,
                    "artifact_hash": artifact_hash,
                    "live_runtime": "pooled_candidate_replay",
                    "postprocess_config_hash": "fixture",
                },
            )
        _write_jsonl(folder / "variant_predictions.jsonl", tape_rows)

        def predict_density(_artifact, rows):
            return [
                {
                    "kind": "continuous_density_f",
                    "density_f": {67.0: 0.2, 70.0: 0.3, 72.0: 0.5},
                }
                for _row in rows
            ]

        with (
            patch(
                "weather.operations.density_live_replay_parity.predict_density_rows_for_bundle",
                side_effect=predict_density,
            ),
            patch(
                "weather.model.variant_prediction_runtime.predict_density_rows_for_bundle",
                side_effect=predict_density,
            ),
        ):
            payload = build_diagnostic(
                event_folders=[folder],
                artifact_path=artifact_path,
                variant_id="density-fixture",
                max_snapshots_per_event=1,
                max_variant_lines_per_event=10,
            )

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["summary"]["legacy_route_reproduction_status"] == "PASS"
    assert payload["summary"]["max_recorded_vs_legacy_abs_delta"] == 0.0
    assert payload["summary"]["historical_live_parity_status"] == "FAIL"
    assert payload["summary"]["repaired_code_parity_status"] == "PASS"
    assert payload["summary"]["max_repaired_live_vs_canonical_abs_delta"] == 0.0
    assert payload["execution_bounds"]["snapshot_lines_read"] == 1
    assert payload["execution_bounds"]["variant_lines_read"] == 3
    assert payload["execution_bounds"]["capture_or_training_invoked"] is False
    assert payload["samples"][0]["top_bands"]["recorded"]["band_key"] == "gte_22c"
    assert payload["samples"][0]["top_bands"]["canonical_replay"]["band_key"] == "gte_22c"
    assert "missing_explicit_projection_unit" in {
        row["id"] for row in payload["proven_root_causes"]
    }
    report = render_markdown(payload)
    assert "Historical recorded live vs canonical replay | FAIL" in report
    assert "Repaired live code vs canonical replay | PASS" in report
