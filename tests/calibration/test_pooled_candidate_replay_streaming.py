import argparse
import hashlib
import json
import pickle
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from weather.calibration.pooled_candidate_replay import (
    BoundedCandidateReplayError,
    _compute_pooled_candidate_day,
    build_candidate_features,
    iter_bounded_pooled_band_candidate_replay,
    iter_bounded_pooled_band_candidate_replay_market_days,
    write_bounded_pooled_band_candidate_replay_jsonl,
)
from weather.calibration.pooled_feature_model import (
    add_city_features,
    band_prediction_record,
    MARINE_WATER_CONTRAST_COLUMNS,
    predict_band_rows_for_bundle,
    REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    SOURCE_RELIABILITY_COLUMNS,
    train_pooled_band_models,
)
from weather.market.market_registry import NYC
from weather.reporting.promotion.promotion_corpus import corpus_hash
from weather.reporting.validation.point_in_time_evaluation import (
    _candidate_replay_input_row,
    _materialize_bounded_candidate_replay,
)


class TestBoundedPooledCandidateReplay(unittest.TestCase):
    def test_production_replay_uses_frozen_context_and_disables_unpinned_sidecars(self):
        market_context = {
            "climate_normal": 81.5,
            "climate_std": 4.25,
            **{
                field: float(index + 1)
                for index, field in enumerate(SOURCE_RELIABILITY_COLUMNS)
            },
        }
        context = {
            "artifact_type": "pooled_production_static_feature_context",
            "preselection_hash": "a" * 64,
            "window_lock_id": "b" * 64,
            "prior_as_of_exclusive": "2026-01-01",
            "context_fields": [
                "climate_normal",
                "climate_std",
                *SOURCE_RELIABILITY_COLUMNS,
            ],
            "markets": {"nyc": market_context},
            "external_sidecar_policy": {
                "reanalysis_synoptic": "disabled_unpinned",
                "marine_water_contrast": "disabled_unpinned",
            },
        }
        context["context_sha256"] = hashlib.sha256(
            json.dumps(
                context,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        artifact = {
            "point_in_time_training": {
                "preselection_lock": {
                    "preselection_hash": "a" * 64,
                    "window_lock_id": "b" * 64,
                }
            },
            "production_static_context": context,
            "models": {
                "12": {
                    "feature_names": [
                        "climate_normal",
                        *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
                        *MARINE_WATER_CONTRAST_COLUMNS,
                    ]
                }
            },
        }
        captured = {}

        def record_feature(_model, _spec, climate, _record, **kwargs):
            captured["climate"] = climate
            captured["reliability"] = kwargs["source_reliability"]
            return {
                "cutoff_hour": 12,
                **{
                    field: 999.0
                    for field in (
                        *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
                        *MARINE_WATER_CONTRAST_COLUMNS,
                    )
                },
            }

        folder = Path("nyc-high-2026-07-01")
        with (
            patch(
                "weather.calibration.pooled_candidate_replay.folders_from_manifest",
                return_value=[folder],
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.folder_market_id",
                return_value="nyc",
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.entry_for_folder",
                return_value={"snapshot_ids": ["snapshot-1"]},
            ),
            patch(
                "weather.calibration.pooled_candidate_replay._model_for_market",
                return_value=object(),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.load_replay_records",
                return_value=[{"snapshot_id": "snapshot-1"}],
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.record_target_date",
                return_value=date(2026, 7, 1),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay._record_feature_row",
                side_effect=record_feature,
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.load_reanalysis_synoptic_features",
                side_effect=AssertionError("unpinned reanalysis sidecar loaded"),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.load_marine_water_contrast_features",
                side_effect=AssertionError("unpinned marine sidecar loaded"),
            ),
        ):
            features, diagnostics = build_candidate_features(
                {"include_reconstructed": False},
                "snapshots",
                "F",
                artifact=artifact,
            )

        row = features[("nyc", "snapshot-1")]
        self.assertEqual(
            captured["climate"],
            {"climate_normal": 81.5, "climate_std": 4.25},
        )
        self.assertEqual(captured["reliability"][SOURCE_RELIABILITY_COLUMNS[0]], 1.0)
        self.assertTrue(
            all(
                row[field] is None
                for field in (
                    *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
                    *MARINE_WATER_CONTRAST_COLUMNS,
                )
            )
        )
        self.assertEqual(
            diagnostics["production_static_context_sha256"],
            context["context_sha256"],
        )

    def test_day_scorer_uses_the_fitted_hgb_bundle_for_probability(self):
        records = []
        for index in range(80):
            final_bucket = 79 + (index % 4)
            records.append(
                add_city_features(
                    {
                        "market_id": "nyc",
                        "target_date": f"2026-05-{1 + (index % 28):02d}",
                        "snapshot_id": f"train-{index}",
                        "high_so_far": 76.0 + (index % 3),
                        "current_temp": 77.0 + (index % 3),
                        "forecast_high": 79.0 + (index % 5),
                        "final_bucket": final_bucket,
                        "cutoff_hour": 12,
                        "year": 2026,
                    },
                    NYC,
                    {"climate_normal": 82.0, "climate_std": 5.0},
                )
            )
        artifact, _ = train_pooled_band_models(records, holdout_year=None)
        artifact["postprocess"].update(
            {
                "hard_floor_enabled": False,
                "support_floor_enabled": False,
                "late_lockin_enabled": False,
                "partition_normalization_enabled": False,
                "current_blend_enabled": False,
            }
        )
        feature_row = add_city_features(
            {
                "market_id": "nyc",
                "target_date": "2026-07-01",
                "snapshot_id": "snapshot-1",
                "high_so_far": 77.0,
                "current_temp": 78.0,
                "forecast_high": 81.0,
                "cutoff_hour": 12,
                "year": 2026,
            },
            NYC,
            {"climate_normal": 82.0, "climate_std": 5.0},
        )
        expected_band_row = band_prediction_record(
            feature_row, "range", 80.0, value_hi=81.0
        )
        expected_probability = predict_band_rows_for_bundle(
            artifact["models"]["12"],
            [expected_band_row],
            postprocess=False,
        )[0]
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "target_date": "2026-07-01",
                    "snapshot_id": "snapshot-1",
                    "band": "80-81",
                    "bin_type": "range",
                    "bin_value_c": 80.0,
                    "bin_value_hi": 81.0,
                    "outcome": 1,
                    "settlement_bucket": 80,
                }
            ]
        }
        args = argparse.Namespace(
            snapshots_root="snapshots",
            clob_max_age_seconds=180,
            long_job_guard_info=None,
        )
        with (
            patch(
                "weather.calibration.pooled_candidate_replay._single_entry_manifest",
                return_value={"include_reconstructed": False},
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.run_replay_backtest",
                return_value=replay_results,
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_candidate_features",
                return_value=({("nyc", "snapshot-1"): feature_row}, {}),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_clob_feature_index",
                return_value=({}, {}),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_source_freshness_index",
                return_value=({("nyc", "snapshot-1"): "all_fresh"}, {}),
            ),
        ):
            result = _compute_pooled_candidate_day(
                args,
                {},
                "folder",
                artifact,
                family_unit="F",
                prediction_mode="band_binary",
                defer_settlement_join=True,
            )

        self.assertEqual(result["coverage"]["missing_candidate_rows"], 0)
        self.assertAlmostEqual(
            result["candidate_rows"][0]["candidate_p"],
            expected_probability,
            places=12,
        )

    def test_day_scorer_hides_settlement_until_after_band_prediction(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "target_date": "2026-07-01",
                    "snapshot_id": "snapshot-1",
                    "band": "80-81",
                    "bin_type": "range",
                    "bin_value_c": 80.0,
                    "bin_value_hi": 81.0,
                    "outcome": 1,
                    "settlement_bucket": 80,
                    "settlement_distance": 0,
                    "settlement_distance_bucket": "0",
                }
            ]
        }

        def score_without_labels(results, *_args, **_kwargs):
            prediction_row = results["all_rows"][0]
            self.assertNotIn("outcome", prediction_row)
            self.assertNotIn("settlement_bucket", prediction_row)
            self.assertNotIn("settlement_distance", prediction_row)
            return [dict(prediction_row, candidate_p=0.7)], {
                "family_rows": 1,
                "candidate_rows": 1,
                "missing_candidate_rows": 0,
            }

        args = argparse.Namespace(
            snapshots_root="snapshots",
            clob_max_age_seconds=180,
            long_job_guard_info=None,
        )
        with (
            patch(
                "weather.calibration.pooled_candidate_replay._single_entry_manifest",
                return_value={"include_reconstructed": False},
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.run_replay_backtest",
                return_value=replay_results,
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_candidate_features",
                return_value=({}, {}),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_clob_feature_index",
                return_value=({}, {}),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.build_source_freshness_index",
                return_value=({}, {}),
            ),
            patch(
                "weather.calibration.pooled_candidate_replay.attach_band_candidate_probabilities",
                side_effect=score_without_labels,
            ) as scorer,
        ):
            result = _compute_pooled_candidate_day(
                args,
                {},
                "folder",
                {"models": {"0": {}}},
                family_unit="F",
                prediction_mode="band_binary",
                defer_settlement_join=True,
            )

        scorer.assert_called_once()
        self.assertEqual(result["candidate_rows"][0]["candidate_p"], 0.7)
        self.assertEqual(result["candidate_rows"][0]["outcome"], 1)
        self.assertEqual(result["candidate_rows"][0]["settlement_bucket"], 80)

    def _fixture(self, root, *, embedded_candidate_id="candidate-1"):
        root = Path(root)
        snapshots_root = root / "snapshots"
        snapshots_root.mkdir()
        entries = []
        for index, target_date in enumerate(("2026-07-01", "2026-07-02"), 1):
            slug = f"nyc-high-{target_date}"
            folder = snapshots_root / slug
            folder.mkdir()
            snapshot_id = f"snapshot-{index}"
            entries.append(
                {
                    "event_slug": slug,
                    "market_id": "nyc",
                    "target_date": target_date,
                    "folder": str(folder),
                    "folder_name": slug,
                    "folder_relative_to_snapshots_root": slug,
                    "settlement_bucket": 80 + index,
                    "settlement_unit": "F",
                    "settlement_source": "wu_history",
                    "quality_grade": "complete",
                    "snapshot_ids": [snapshot_id],
                    "snapshot_count": 1,
                    "row_count": 1,
                    "replay_record_hashes": {snapshot_id: f"{index}" * 64},
                    "tape_row_hashes": {snapshot_id: f"{index + 2}" * 64},
                    "label_hash": f"{index + 4}" * 64,
                }
            )
        manifest = {
            "schema_version": "promotion_corpus_v0.1",
            "as_of": "2026-07-03",
            "snapshots_root": str(snapshots_root),
            "include_reconstructed": False,
            "entries": entries,
            "summary": {"market_day_count": 2},
        }
        manifest["corpus_hash"] = corpus_hash(entries)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        artifact = {
            "prediction_mode": "band_binary",
            "family_unit": "F",
            "candidate_id": embedded_candidate_id,
            "trained_at": "2026-07-03T01:00:00+00:00",
            "models": {"0": {"model": "test-model"}},
        }
        artifact_path = root / "candidate.pkl"
        artifact_path.write_bytes(pickle.dumps(artifact))
        artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        preselection = {
            "preselection_hash": "a" * 64,
            "window_lock": {
                "window_lock_id": "b" * 64,
                "target_dates": ["2026-07-01", "2026-07-02"],
            },
            "selection_universe": {
                "sha256": "c" * 64,
                "fleet_dates": ["2026-07-01", "2026-07-02"],
            },
            "source": {
                "replay_manifest_sha256": manifest_sha256,
                "replay_corpus_hash": manifest["corpus_hash"],
            },
        }
        training = {
            "preselection_lock": {
                "preselection_hash": "a" * 64,
                "window_lock_id": "b" * 64,
                "selection_universe_sha256": "c" * 64,
                "locked_dates": ["2026-07-01", "2026-07-02"],
                "locked_dates_used_for_selection": False,
            }
        }
        return {
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
            "snapshots_root": snapshots_root,
            "entries": entries,
            "preselection": preselection,
            "training": training,
        }

    @staticmethod
    def _computed_day(folder):
        target_date = Path(folder).name[-10:]
        index = 1 if target_date.endswith("01") else 2
        return {
            "candidate_rows": [
                {
                    "market_id": "nyc",
                    "target_date": target_date,
                    "snapshot_id": f"snapshot-{index}",
                    "band": f"{80 + index}-{81 + index}",
                    "bin_type": "range",
                    "bin_value_c": float(80 + index),
                    "bin_value_hi": float(81 + index),
                    "captured_at_local": f"{target_date}T12:00:00-04:00",
                    "candidate_cutoff_hour": 12,
                    "candidate_p": 0.7,
                    "outcome": 1,
                    "settlement_bucket": 80 + index,
                    "market_yes": 0.5,
                    "recorded_p": 0.55,
                    "replayed_p": 0.6,
                }
            ],
            "coverage": {"missing_candidate_rows": 0},
            "replay_results": {"corpus_warnings": []},
        }

    @staticmethod
    def _materializer_row(target_date, band):
        digest_char = "1" if band == "a" else "2"
        lineage = {
            "source_mode": "promotion_manifest_pinned_captured_replay",
            "market_day_folder": f"nyc-high-{target_date}",
            "replay_record_sha256": digest_char * 64,
            "snapshot_tape_rows_sha256": "3" * 64,
            "settlement_label_sha256": "4" * 64,
        }
        return {
            "target_date": target_date,
            "market_id": "nyc",
            "cutoff_or_snapshot": "08:00",
            "snapshot_id": "08:00",
            "band": band,
            "range_label": band,
            "variant_id": "candidate-1",
            "release_id": "candidate-1",
            "feature_available_at_utc": f"{target_date}T12:00:00+00:00",
            "prediction_made_at_utc": f"{target_date}T12:00:00+00:00",
            "label_quality": "complete",
            "countable": True,
            "claim_lane": "weather_only",
            "replay_serve_parity": "pass",
            "source_quality": "healthy",
            "prediction_probability": 0.7 if band == "a" else 0.3,
            "label": 1 if band == "a" else 0,
            "runtime_identity": "pooled-band-test",
            "source_lineage": lineage,
            "source_corpus_hash": "5" * 64,
            "candidate_artifact_sha256": "6" * 64,
            "source_manifest_sha256": "7" * 64,
        }

    def test_iterator_is_market_day_lazy_and_atomic_writer_binds_lineage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self._fixture(temp_dir)
            kwargs = {
                "artifact_path": fixture["artifact_path"],
                "expected_artifact_sha256": fixture["artifact_sha256"],
                "candidate_id": "candidate-1",
                "corpus_manifest_path": fixture["manifest_path"],
                "expected_manifest_sha256": fixture["manifest_sha256"],
                "preselection_lock_path": Path(temp_dir) / "preselection.json",
                "expected_preselection_hash": "a" * 64,
                "expected_window_lock_id": "b" * 64,
                "snapshots_root": fixture["snapshots_root"],
                "locked_dates": ["2026-07-01", "2026-07-02"],
                "max_market_days": 2,
                "max_rows_per_market_day": 2,
            }
            with (
                patch(
                    "weather.calibration.pooled_training.load_production_point_in_time_preselection",
                    return_value=fixture["preselection"],
                ),
                patch(
                    "weather.calibration.pooled_training.verify_pooled_point_in_time_training_evidence",
                    return_value=fixture["training"],
                ),
                patch(
                    "weather.calibration.pooled_candidate_replay._compute_pooled_candidate_day",
                    side_effect=lambda _args, _manifest, folder, _artifact, **_kwargs: self._computed_day(folder),
                ) as compute,
            ):
                batches = iter_bounded_pooled_band_candidate_replay_market_days(
                    **kwargs
                )
                first_batch = next(batches)
                self.assertEqual(compute.call_count, 1)
                self.assertEqual(
                    {row["target_date"] for row in first_batch},
                    {"2026-07-01"},
                )
                second_batch = next(batches)
                self.assertEqual(compute.call_count, 2)
                with self.assertRaises(StopIteration):
                    next(batches)

            first = first_batch[0]
            second = second_batch[0]

            self.assertEqual(first["candidate_id"], "candidate-1")
            self.assertEqual(
                first["candidate_artifact_sha256"], fixture["artifact_sha256"]
            )
            self.assertEqual(first["prediction_probability"], 0.7)
            self.assertEqual(first["label"], 1.0)
            self.assertEqual(first["captured_at_utc"], "2026-07-01T16:00:00+00:00")
            self.assertEqual(
                first["source_lineage"]["replay_record_sha256"], "1" * 64
            )
            self.assertEqual(second["target_date"], "2026-07-02")

            out_path = Path(temp_dir) / "candidate_replay.jsonl"
            with (
                patch(
                    "weather.calibration.pooled_training.load_production_point_in_time_preselection",
                    return_value=fixture["preselection"],
                ),
                patch(
                    "weather.calibration.pooled_training.verify_pooled_point_in_time_training_evidence",
                    return_value=fixture["training"],
                ),
                patch(
                    "weather.calibration.pooled_candidate_replay._compute_pooled_candidate_day",
                    side_effect=lambda _args, _manifest, folder, _artifact, **_kwargs: self._computed_day(folder),
                ),
            ):
                summary = write_bounded_pooled_band_candidate_replay_jsonl(
                    out_path, **kwargs
                )
            persisted = [
                json.loads(line)
                for line in out_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(summary["row_count"], 2)
            self.assertEqual(summary["market_day_count"], 2)
            self.assertEqual(len(persisted), 2)
            self.assertEqual(
                hashlib.sha256(out_path.read_bytes()).hexdigest(), summary["sha256"]
            )

    def test_candidate_materializer_flushes_before_next_day_and_chunks_arrow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            replay_manifest = root / "replay-manifest.json"
            replay_manifest.write_text("{}", encoding="utf-8")
            events = []

            def day_batches():
                for target_date in ("2026-07-01", "2026-07-02"):
                    events.append(f"produce:{target_date}")
                    yield [
                        self._materializer_row(target_date, band)
                        for band in ("a", "b")
                    ]
                    self.assertEqual(events[-1], f"flush:{target_date}")

            def observed_input_row(rows):
                payload = _candidate_replay_input_row(rows)
                canonical_lines = "".join(
                    json.dumps(
                        row,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n"
                    for row in rows
                )
                self.assertEqual(
                    payload["parquet_file_hash"],
                    hashlib.sha256(canonical_lines.encode("utf-8")).hexdigest(),
                )
                replay_hashes = sorted(
                    row["source_lineage"]["replay_record_sha256"] for row in rows
                )
                self.assertEqual(
                    payload["replay_record_set_sha256"],
                    hashlib.sha256(
                        json.dumps(
                            replay_hashes,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        ).encode("utf-8")
                    ).hexdigest(),
                )
                events.append(f"flush:{rows[0]['target_date']}")
                return payload

            corpus = root / "candidate.parquet"
            manifest_path = root / "candidate-manifest.json"
            training_graph = {
                "graph_hash": "8" * 64,
                "preselection_hash": "9" * 64,
                "window_lock_id": "a" * 64,
                "candidate_artifacts": {"model_sha256": "6" * 64},
            }
            with (
                patch(
                    "weather.reporting.validation.point_in_time_evaluation."
                    "iter_bounded_pooled_band_candidate_replay_market_days",
                    side_effect=lambda **_kwargs: day_batches(),
                ),
                patch(
                    "weather.reporting.validation.point_in_time_evaluation."
                    "_candidate_replay_input_row",
                    side_effect=observed_input_row,
                ),
            ):
                manifest = _materialize_bounded_candidate_replay(
                    candidate_id="candidate-1",
                    release_id="candidate-1",
                    corpus_out=corpus,
                    manifest_out=manifest_path,
                    model_artifact=root / "model.pkl",
                    preselection_lock=root / "preselection.json",
                    replay_manifest=replay_manifest,
                    snapshots_root=root / "snapshots",
                    fleet_dates=["2026-07-01", "2026-07-02"],
                    training_graph=training_graph,
                    max_market_days=2,
                    max_rows_per_market_day=4,
                    batch_rows=1,
                )

            self.assertEqual(
                events,
                [
                    "produce:2026-07-01",
                    "flush:2026-07-01",
                    "produce:2026-07-02",
                    "flush:2026-07-02",
                ],
            )
            self.assertEqual(manifest["derived_artifact"]["row_count"], 4)
            self.assertEqual(
                manifest["streaming_bounds"]["market_day_batch_handoff"],
                "flush_before_next_compute",
            )
            self.assertEqual(
                manifest["streaming_bounds"]["raw_market_days_retained_at_once"],
                1,
            )
            self.assertEqual(
                manifest["streaming_bounds"]["observed_peak_arrow_rows"],
                1,
            )

    def test_hash_identity_and_day_bounds_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self._fixture(temp_dir)
            base = {
                "artifact_path": fixture["artifact_path"],
                "expected_artifact_sha256": fixture["artifact_sha256"],
                "candidate_id": "candidate-1",
                "corpus_manifest_path": fixture["manifest_path"],
                "expected_manifest_sha256": fixture["manifest_sha256"],
                "preselection_lock_path": Path(temp_dir) / "preselection.json",
                "expected_preselection_hash": "a" * 64,
                "expected_window_lock_id": "b" * 64,
                "snapshots_root": fixture["snapshots_root"],
                "locked_dates": ["2026-07-01", "2026-07-02"],
                "max_market_days": 2,
                "max_rows_per_market_day": 2,
            }
            cases = (
                {"expected_artifact_sha256": "0" * 64},
                {"candidate_id": "different-candidate"},
                {"max_market_days": 1},
            )
            for override in cases:
                with self.subTest(override=override):
                    kwargs = dict(base)
                    kwargs.update(override)
                    with (
                        patch(
                            "weather.calibration.pooled_training.load_production_point_in_time_preselection",
                            return_value=fixture["preselection"],
                        ),
                        patch(
                            "weather.calibration.pooled_training.verify_pooled_point_in_time_training_evidence",
                            return_value=fixture["training"],
                        ),
                        self.assertRaises(BoundedCandidateReplayError),
                    ):
                        list(iter_bounded_pooled_band_candidate_replay(**kwargs))


if __name__ == "__main__":
    unittest.main()
