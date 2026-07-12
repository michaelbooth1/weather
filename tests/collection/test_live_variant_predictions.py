import csv
import json
import pickle
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from weather.collection.live_variant_predictions import (
    SCHEMA_VERSION,
    active_live_variants,
    build_live_variant_prediction_rows,
)
from weather.collection.collection_health import variant_prediction_tape_health
from weather.collection.snapshot_tracker import SnapshotStore
from weather.release_artifacts import canonical_payload_sha256
from weather.release_serving import STATUS_BLOCKED, STATUS_BOUND, VerifiedServingBundle
from weather.reporting.candidate_lifecycle.variant_registry import SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION


class FakeModelClient:
    target_date = date(2026, 6, 18)

    def market_bins(self, _event):
        return [
            {
                "label": "20 C or lower",
                "kind": "lte",
                "value": 20,
                "value_hi": 20,
                "market_yes": 0.40,
                "market_no": 0.60,
                "condition_id": "cond-1",
                "clob_token_ids": "yes,no",
                "clob_yes_token_id": "yes",
                "clob_no_token_id": "no",
                "status": "active",
            }
        ]

    def bin_probability(self, distribution, bin_data, calibration_context=None):
        value = int(bin_data["value"])
        return sum(float(prob) for temp, prob in distribution.items() if int(temp) <= value)

    def source_data(self, _sources, _name):
        return {}

    def forecast_ensemble_metrics(self, *_args, **_kwargs):
        return {}

    def max_row_temp(self, _rows):
        return None


class RaisingVariantClient(FakeModelClient):
    def predict_variant_distribution(self, variant, **_kwargs):
        raise RuntimeError(f"boom {variant['variant_id']}")


class IdentityImputer:
    def transform(self, frame):
        return frame


class ConstantClassifier:
    classes_ = [0, 1]

    def __init__(self, probability):
        self.probability = float(probability)

    def predict_proba(self, rows):
        return [[1.0 - self.probability, self.probability] for _ in range(len(rows))]


def _registry(path, variants):
    payload = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "variants": variants,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_pickle(path, payload):
    with path.open("wb") as handle:
        pickle.dump(payload, handle)
    return path


def _band_rows():
    return [
        {
            "snapshot_id": "snap",
            "range_label": "20 C or lower",
            "bin_kind": "lte",
            "bin_value_c": 20,
            "bin_value_hi_c": 20,
            "model_probability": 0.44,
            "market_yes": 0.40,
            "market_no": 0.60,
            "condition_id": "cond-1",
            "clob_token_ids": "yes,no",
            "clob_yes_token_id": "yes",
            "clob_no_token_id": "no",
            "market_status": "active",
        }
    ]


def _build_rows(
    registry_path,
    *,
    model=None,
    model_client=None,
    cadence_quality=None,
    band_rows=None,
    market_id="toronto",
    event_slug="highest-temperature-in-toronto-on-june-18-2026",
):
    captured_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    return build_live_variant_prediction_rows(
        snapshot_id="snap",
        captured_at=captured_at,
        event={"slug": event_slug, "updatedAt": "u1"},
        model=model or {"distribution": {20: 1.0}},
        model_client=model_client or FakeModelClient(),
        band_rows=band_rows or _band_rows(),
        event_slug=event_slug,
        market_id=market_id,
        target_date=date(2026, 6, 18),
        serving_model_version="serving-v",
        release_lineage={
            "release_id": "release-fixture",
            "release_manifest_sha256": "a" * 64,
            "release_pointer_sha256": "b" * 64,
            "release_sequence": 7,
            "release_identity_status": "verified",
            "release_identity_reason": "",
        },
        captured_input_hash="c" * 64,
        runtime_fields={"runtime_code_state": "current"},
        snapshot_cadence="triggered",
        cadence_quality=cadence_quality,
        trigger_summary={"trigger_reason": "wu_current_temp_bucket_crossed"},
        registry_path=registry_path,
    )


class TestLiveVariantPredictions(unittest.TestCase):
    def test_active_live_variants_excludes_controls_and_inactive_rows(self):
        registry = {
            "variants": [
                {"variant_id": "active", "lifecycle": "active", "active_for_headline": True},
                {"variant_id": "control", "lifecycle": "control", "roles": ["control"]},
                {"variant_id": "archived", "lifecycle": "archived", "active_for_headline": True},
                {
                    "variant_id": "diagnostic-shadow",
                    "lifecycle": "shadow",
                    "active_for_headline": False,
                    "live_capture_enabled": True,
                },
                {
                    "variant_id": "offline-shadow",
                    "lifecycle": "shadow",
                    "active_for_headline": False,
                },
            ]
        }

        self.assertEqual(
            [row["variant_id"] for row in active_live_variants(registry)],
            ["active", "diagnostic-shadow"],
        )

    def test_missing_artifact_and_unsupported_track_emit_skip_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "missing-artifact",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
                {
                    "variant_id": "unsupported-track",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "offline_only",
                    "active_for_headline": True,
                },
            ])

            rows = _build_rows(registry_path)

        by_id = {row["variant_id"]: row for row in rows}
        self.assertEqual(by_id["missing-artifact"]["prediction_status"], "skipped")
        self.assertEqual(by_id["missing-artifact"]["failure_reason"], "missing_artifact")
        self.assertEqual(by_id["unsupported-track"]["failure_reason"], "unsupported_track")
        self.assertEqual(by_id["missing-artifact"]["serving_model_probability"], 0.44)
        self.assertEqual(by_id["missing-artifact"]["condition_id"], "cond-1")

    def test_model_supplied_variant_distribution_writes_probabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "live-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_hash": "artifact-hash",
                    "postprocess_config_hash": "post-hash",
                },
            ])
            model = {
                "live_variant_predictions": {
                    "live-v": {
                        "distribution": {19: 0.20, 20: 0.30, 21: 0.50},
                        "model_version": "variant-v",
                        "live_runtime": "model_payload",
                    }
                }
            }

            rows = _build_rows(registry_path, model=model)

        self.assertEqual(rows[0]["schema_version"], SCHEMA_VERSION)
        self.assertEqual(rows[0]["prediction_status"], "predicted")
        self.assertAlmostEqual(rows[0]["variant_probability"], 0.50)
        self.assertAlmostEqual(rows[0]["variant_edge"], 0.10)
        self.assertEqual(rows[0]["model_version"], "variant-v")
        self.assertEqual(rows[0]["artifact_hash"], "artifact-hash")
        self.assertEqual(rows[0]["postprocess_config_hash"], "post-hash")
        self.assertEqual(rows[0]["band_key"], "lte_20c")
        self.assertEqual(rows[0]["release_id"], "")
        self.assertEqual(rows[0]["release_manifest_sha256"], "")
        self.assertEqual(rows[0]["release_pointer_sha256"], "")
        self.assertIsNone(rows[0]["release_sequence"])
        self.assertEqual(rows[0]["release_identity_status"], "research_unbound_non_countable")
        self.assertEqual(rows[0]["captured_input_hash"], "c" * 64)

    def test_conservative_bridge_runtime_writes_serving_passthrough_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "bridge-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "market_informed",
                    "active_for_headline": True,
                    "artifact_required": False,
                    "live_runtime": "conservative_bridge_policy",
                },
            ])

            rows = _build_rows(registry_path)

        self.assertEqual(rows[0]["prediction_status"], "predicted")
        self.assertEqual(rows[0]["live_runtime"], "conservative_bridge_policy")
        self.assertIsNone(rows[0]["failure_reason"])
        self.assertAlmostEqual(rows[0]["variant_probability"], 0.44)
        self.assertAlmostEqual(rows[0]["serving_model_probability"], 0.44)

    def test_pooled_candidate_runtime_scores_live_feature_vector_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = _write_pickle(Path(tmp) / "pooled.pkl", {
                "prediction_mode": "band_binary",
                "models": {
                    "12": {
                        "model": ConstantClassifier(0.73),
                        "imputer": IdentityImputer(),
                        "feature_names": ["cutoff_hour", "band_value", "band_value_hi"],
                        "classes": [0, 1],
                    }
                },
                "postprocess": {
                    "partition_normalization_enabled": False,
                    "current_blend_enabled": False,
                },
            })
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "pooled-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_path": str(artifact),
                    "live_runtime": "pooled_candidate_replay",
                },
            ])
            model = {
                "distribution": {20: 1.0},
                "feature_vector": {
                    "cutoff_hour": 12,
                    "high_so_far": 19.0,
                    "forecast_high": 21.0,
                    "market_id": "toronto",
                },
            }

            rows = _build_rows(registry_path, model=model)

        self.assertEqual(rows[0]["prediction_status"], "predicted")
        self.assertIsNone(rows[0]["failure_reason"])
        self.assertEqual(rows[0]["live_runtime"], "pooled_candidate_replay")
        self.assertAlmostEqual(rows[0]["variant_probability"], 0.73)

    def test_density_runtime_matches_native_unit_partition_for_toronto_and_atlanta(self):
        fixtures = [
            {
                "market_id": "toronto",
                "event_slug": "highest-temperature-in-toronto-on-june-18-2026",
                "unit": "C",
                "high_so_far": 20.2,
                "density_f": {67.0: 0.2, 70.0: 0.3, 72.0: 0.5},
                "bands": [("lte", 20), ("eq", 21), ("gte", 22)],
            },
            {
                "market_id": "atlanta",
                "event_slug": "highest-temperature-in-atlanta-on-june-18-2026",
                "unit": "F",
                "high_so_far": 68.2,
                "density_f": {67.0: 0.2, 69.0: 0.3, 71.0: 0.5},
                "bands": [("lte", 68), ("eq", 69), ("gte", 70)],
            },
        ]
        for fixture in fixtures:
            with self.subTest(market_id=fixture["market_id"]), tempfile.TemporaryDirectory() as tmp:
                artifact = _write_pickle(Path(tmp) / "density.pkl", {
                    "prediction_mode": "continuous_density_f",
                    "density_postprocess": {"enabled": False},
                })
                registry_path = _registry(Path(tmp) / "registry.json", [
                    {
                        "variant_id": f"density-{fixture['market_id']}",
                        "variant_family": "pooled_continuous_density",
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "artifact_path": str(artifact),
                        "live_runtime": "pooled_candidate_replay",
                    },
                ])
                band_rows = [
                    {
                        "range_label": f"{kind} {value}",
                        "bin_kind": kind,
                        "bin_value_c": value,
                        "bin_value_hi_c": value,
                        "model_probability": 1.0 / 3.0,
                        "market_yes": 1.0 / 3.0,
                    }
                    for kind, value in fixture["bands"]
                ]
                model = {
                    "distribution": {},
                    "feature_vector": {
                        "cutoff_hour": 12,
                        "high_so_far": fixture["high_so_far"],
                        "forecast_high": fixture["high_so_far"] + 2.0,
                    },
                }
                predicted_features = []
                calibration_contexts = []

                def predict_density(_artifact, rows):
                    predicted_features.extend(dict(row) for row in rows)
                    return [{
                        "kind": "continuous_density_f",
                        "density_f": fixture["density_f"],
                    }]

                def calibrate(payload, _artifact, **kwargs):
                    calibration_contexts.append(dict(kwargs))
                    return payload

                with (
                    patch(
                        "weather.model.variant_prediction_runtime.predict_density_rows_for_bundle",
                        side_effect=predict_density,
                    ),
                    patch(
                        "weather.model.variant_prediction_runtime.apply_continuous_density_calibration",
                        side_effect=calibrate,
                    ),
                ):
                    rows = _build_rows(
                        registry_path,
                        model=model,
                        band_rows=band_rows,
                        market_id=fixture["market_id"],
                        event_slug=fixture["event_slug"],
                    )

            self.assertEqual([row["prediction_status"] for row in rows], ["predicted"] * 3)
            self.assertEqual([row["variant_probability"] for row in rows], [0.2, 0.3, 0.5])
            self.assertAlmostEqual(sum(row["variant_probability"] for row in rows), 1.0)
            self.assertEqual(predicted_features[0]["market_id"], fixture["market_id"])
            self.assertEqual(predicted_features[0]["display_unit"], fixture["unit"])
            self.assertEqual(predicted_features[0]["unit"], fixture["unit"])
            self.assertEqual(calibration_contexts[0]["unit"], fixture["unit"])
            self.assertEqual(
                calibration_contexts[0]["floor_bucket"],
                round(fixture["high_so_far"]),
            )

    def test_density_runtime_rejects_feature_context_unit_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = _write_pickle(Path(tmp) / "density.pkl", {
                "prediction_mode": "continuous_density_f",
            })
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "density-unit-mismatch",
                    "variant_family": "pooled_continuous_density",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_path": str(artifact),
                    "live_runtime": "pooled_candidate_replay",
                },
            ])
            rows = _build_rows(
                registry_path,
                model={
                    "distribution": {},
                    "feature_vector": {
                        "cutoff_hour": 12,
                        "market_id": "toronto",
                        "display_unit": "F",
                    },
                },
            )

        self.assertEqual(rows[0]["prediction_status"], "failed")
        self.assertEqual(rows[0]["failure_reason"], "runtime_exception")
        self.assertIn("density runtime unit mismatch", rows[0]["failure_detail"])

    def test_pooled_candidate_runtime_reports_missing_live_feature_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = _write_pickle(Path(tmp) / "pooled.pkl", {
                "prediction_mode": "band_binary",
                "models": {"12": {}},
            })
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "pooled-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_path": str(artifact),
                    "live_runtime": "pooled_candidate_replay",
                },
            ])

            rows = _build_rows(registry_path)

        self.assertEqual(rows[0]["prediction_status"], "failed")
        self.assertEqual(rows[0]["failure_reason"], "missing_feature_vector")
        self.assertEqual(rows[0]["live_runtime"], "pooled_candidate_replay")

    def test_microstructure_runtime_taxonomy_gate_skips_with_explicit_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "clob-taxonomy",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "market_informed",
                    "active_for_headline": True,
                    "artifact_required": False,
                    "postprocess_config_hash": "taxonomy_gate",
                    "live_runtime": "microstructure_shadow_report",
                },
            ])

            rows = _build_rows(registry_path)

        self.assertEqual(rows[0]["prediction_status"], "skipped")
        self.assertEqual(rows[0]["failure_reason"], "taxonomy_gate_unavailable_live")
        self.assertEqual(rows[0]["live_runtime"], "microstructure_shadow_report")

    def test_cadence_quality_haircuts_served_variant_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "live-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_hash": "artifact-hash",
                    "postprocess_config_hash": "post-hash",
                },
            ])
            model = {
                "live_variant_predictions": {
                    "live-v": {
                        "distribution": {19: 0.20, 20: 0.30, 21: 0.50},
                        "model_version": "variant-v",
                        "live_runtime": "model_payload",
                    }
                }
            }

            rows = _build_rows(
                registry_path,
                model=model,
                cadence_quality={
                    "snapshot_cadence_quality_state": "gappy",
                    "snapshot_cadence_gap_count": 2,
                    "snapshot_cadence_max_gap_seconds": 1328.4,
                },
            )

        row = rows[0]
        self.assertEqual(row["snapshot_cadence_quality_state"], "gappy")
        self.assertEqual(row["snapshot_cadence_permission"], "deny")
        self.assertLess(float(row["snapshot_cadence_confidence_multiplier"]), 1.0)
        self.assertLess(row["cadence_adjusted_variant_probability"], row["variant_probability"])
        self.assertGreater(row["cadence_adjusted_variant_probability"], float(row["market_yes"]))

    def test_runtime_exception_emits_failure_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.pkl"
            artifact.write_text("placeholder", encoding="utf-8")
            registry_path = _registry(Path(tmp) / "registry.json", [
                {
                    "variant_id": "raises",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                    "artifact_path": str(artifact),
                    "live_runtime": "model_client",
                },
            ])

            rows = _build_rows(registry_path, model_client=RaisingVariantClient())

        self.assertEqual(rows[0]["prediction_status"], "failed")
        self.assertEqual(rows[0]["failure_reason"], "runtime_exception")
        self.assertIn("boom raises", rows[0]["failure_detail"])

    def test_snapshot_store_persists_variant_tape_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-toronto-on-june-18-2026")
            captured_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
            event = {"slug": "highest-temperature-in-toronto-on-june-18-2026", "markets": []}
            model = {"distribution": {20: 1.0}, "top_temp": 20, "sources": {}}
            variant_row = {
                "schema_version": SCHEMA_VERSION,
                "snapshot_id": "snap",
                "variant_id": "live-v",
                "variant_family": "family",
                "prediction_status": "skipped",
                "failure_reason": "missing_artifact",
            }

            with patch(
                "weather.collection.snapshot_store.build_live_variant_prediction_rows",
                return_value=[variant_row],
            ):
                result = store.write(event, model, FakeModelClient(), captured_at)

            variant_rows = list(csv.DictReader((root / "variant_predictions_long.csv").open(encoding="utf-8", newline="")))
            snapshot_header = (root / "snapshots_long.csv").read_text(encoding="utf-8").splitlines()[0]
            sidecar = json.loads((root / "variant_predictions.jsonl").read_text(encoding="utf-8").strip())

        self.assertEqual(result["variant_prediction_rows"], 1)
        self.assertEqual(result["variant_predictions_path"], str(root / "variant_predictions_long.csv"))
        self.assertEqual(variant_rows[0]["variant_id"], "live-v")
        self.assertEqual(sidecar["failure_reason"], "missing_artifact")
        self.assertNotIn("variant_id", snapshot_header)

    def test_snapshot_store_hashes_replay_first_and_stamps_only_verified_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-toronto-on-june-18-2026")
            captured_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
            event = {"slug": "highest-temperature-in-toronto-on-june-18-2026", "markets": []}
            model = {
                "distribution": {20: 1.0},
                "top_temp": 20,
                "sources": {"fixture": {"ok": True, "data": {"value": 1}}},
            }
            verified_release = VerifiedServingBundle(
                status=STATUS_BOUND,
                reason="fixture verified binding",
                pointer_present=True,
                pointer_file_sha256="f" * 64,
                release_id="release-live-1",
                manifest_sha256="a" * 64,
                pointer_sha256="b" * 64,
                sequence=11,
                base_model_bound=True,
                base_model_binding_reason="fixture complete base-model binding",
            )
            model_client = FakeModelClient()
            model_client.serving_bundle = verified_release
            append_order = []
            original_append_jsonl = store.append_jsonl

            def record_append(path, payload):
                append_order.append(Path(path).name)
                return original_append_jsonl(path, payload)

            def variant_rows(**kwargs):
                return [
                    {
                        "schema_version": SCHEMA_VERSION,
                        "snapshot_id": kwargs["snapshot_id"],
                        "variant_id": "live-v",
                        "variant_family": "family",
                        "prediction_status": "predicted",
                        **kwargs["release_lineage"],
                        "captured_input_hash": kwargs["captured_input_hash"],
                    }
                ]

            SnapshotStore.clear_verified_release_lineage_cache()
            with (
                patch(
                    "weather.collection.snapshot_store.get_process_active_serving_bundle",
                    return_value=verified_release,
                ) as resolve_release,
                patch(
                    "weather.collection.snapshot_store.build_live_variant_prediction_rows",
                    side_effect=variant_rows,
                ) as build_rows,
                patch.object(store, "append_jsonl", side_effect=record_append),
            ):
                result = store.write(event, model, model_client, captured_at)
                cached_lineage = SnapshotStore.verified_release_lineage()
                self.assertEqual(resolve_release.call_count, 2)
            SnapshotStore.clear_verified_release_lineage_cache()

            replay = json.loads((root / "replay_inputs.jsonl").read_text(encoding="utf-8").strip())
            served = json.loads((root / "variant_predictions.jsonl").read_text(encoding="utf-8").strip())

        expected_hash = canonical_payload_sha256(replay, omit=("captured_input_hash",))
        self.assertEqual(replay["schema_version"], "toronto_replay_inputs_v0.2")
        self.assertEqual(replay["release_id"], "release-live-1")
        self.assertEqual(replay["release_manifest_sha256"], "a" * 64)
        self.assertEqual(replay["release_identity_status"], "verified_variant_serving_bundle")
        self.assertEqual(cached_lineage, {
            "release_id": "release-live-1",
            "release_manifest_sha256": "a" * 64,
            "release_pointer_sha256": "b" * 64,
            "release_sequence": 11,
            "release_identity_status": "verified_variant_serving_bundle",
            "release_identity_reason": replay["release_identity_reason"],
            "base_model_release_bound": True,
            "base_model_binding_reason": replay["base_model_binding_reason"],
        })
        self.assertEqual(replay["captured_input_hash"], expected_hash)
        self.assertEqual(served["release_id"], replay["release_id"])
        self.assertEqual(served["release_manifest_sha256"], replay["release_manifest_sha256"])
        self.assertEqual(served["captured_input_hash"], expected_hash)
        self.assertEqual(build_rows.call_args.kwargs["captured_input_hash"], expected_hash)
        self.assertLess(append_order.index("replay_inputs.jsonl"), append_order.index("variant_predictions.jsonl"))
        self.assertEqual(result["release_id"], "release-live-1")
        self.assertEqual(result["release_identity_status"], "verified_variant_serving_bundle")
        self.assertEqual(result["captured_input_hash"], expected_hash)

    def test_snapshot_store_release_lineage_fails_closed_without_blocking_capture(self):
        SnapshotStore.clear_verified_release_lineage_cache()
        blocked = VerifiedServingBundle(
            status=STATUS_BLOCKED,
            reason="ReleaseArtifactVerificationError: pointer hash mismatch",
            pointer_present=True,
        )
        with patch(
            "weather.collection.snapshot_store.get_process_active_serving_bundle",
            return_value=blocked,
        ):
            lineage = SnapshotStore.verified_release_lineage()
        SnapshotStore.clear_verified_release_lineage_cache()

        self.assertEqual(lineage["release_id"], "")
        self.assertEqual(lineage["release_identity_status"], "release_binding_failed")
        self.assertIn("pointer hash mismatch", lineage["release_identity_reason"])

    def test_variant_tape_failure_does_not_block_snapshot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SnapshotStore(root=root, event_slug="highest-temperature-in-toronto-on-june-18-2026")
            captured_at = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
            event = {"slug": "highest-temperature-in-toronto-on-june-18-2026", "markets": []}
            model = {"distribution": {20: 1.0}, "top_temp": 20, "sources": {}}

            with patch(
                "weather.collection.snapshot_store.build_live_variant_prediction_rows",
                side_effect=RuntimeError("variant tape unavailable"),
            ):
                result = store.write(event, model, FakeModelClient(), captured_at)
            snapshot_exists = (root / "snapshots_long.csv").exists()
            variant_tape_exists = (root / "variant_predictions_long.csv").exists()

        self.assertEqual(result["bands"], 1)
        self.assertIn("variant tape unavailable", result["variant_prediction_error"])
        self.assertTrue(snapshot_exists)
        self.assertFalse(variant_tape_exists)

    def test_variant_prediction_tape_health_requires_latest_active_variant_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-toronto-on-june-18-2026"
            folder.mkdir()
            registry_path = _registry(root / "registry.json", [
                {
                    "variant_id": "live-v",
                    "variant_family": "family",
                    "lifecycle": "active",
                    "track": "no_market",
                    "active_for_headline": True,
                },
            ])
            (folder / "snapshots_long.csv").write_text(
                "\n".join([
                    "snapshot_id,captured_at_local,range_label,bin_kind,bin_value_c",
                    "s1,2026-06-18T12:00:00+00:00,20 C,lte,20",
                ]) + "\n",
                encoding="utf-8",
            )
            (folder / "variant_predictions_long.csv").write_text(
                "\n".join([
                    "snapshot_id,captured_at_local,variant_id,prediction_status,band_key",
                    "s1,2026-06-18T12:00:00+00:00,live-v,skipped,lte_20c",
                ]) + "\n",
                encoding="utf-8",
            )

            health = variant_prediction_tape_health(folder, registry_path=registry_path)

        self.assertFalse(health["action_required"])
        self.assertEqual(health["state"], "OK")
        self.assertEqual(health["expected_latest_rows"], 1)


if __name__ == "__main__":
    unittest.main()
