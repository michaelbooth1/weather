import os
import sys
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import weather.calibration.family_secondary_artifacts as family_secondary  # noqa: E402
from weather.calibration.family_secondary_artifacts import (  # noqa: E402
    build_parser,
    cmd_train,
    feature_model_allowed,
    forecast_error_training_rows,
    gate_for_market,
    market_gate,
    probability_training_rows,
    settlement_lag_training_rows,
)
from weather.model.model_features import FeatureModelMixin  # noqa: E402


class _DummyModel(FeatureModelMixin):
    def __init__(self, manifest, market_id="denver", unit="F"):
        self.family_secondary_artifacts = manifest
        self.market_id = market_id
        self.spec = SimpleNamespace(display_unit=unit)
        self._last_family_secondary_gate = {}


class TestFamilySecondaryArtifacts(unittest.TestCase):
    def _artifact_statuses(self, status="ok"):
        return {
            "probability_calibration": {"status": status},
            "forecast_error": {"status": status},
            "settlement_lag": {"status": status},
        }

    def _build_production_manifest_fixture(
        self,
        root,
        *,
        omitted_source_key=None,
        empty_source_key=None,
    ):
        root = Path(root)
        locked_dates = [f"2026-01-{day:02d}" for day in range(1, 15)]
        unlocked_date = "2025-12-01"
        preselection = {
            "preselection_hash": "a" * 64,
            "selection_universe": {
                "sha256": "c" * 64,
                "fleet_dates": [unlocked_date, *locked_dates],
            },
            "window_lock": {
                "window_lock_id": "b" * 64,
                "target_dates": locked_dates,
            },
        }
        spec = SimpleNamespace(
            id="denver",
            city_label="Denver",
            display_unit="F",
            artifact_suffix="_denver",
        )
        artifact_root = root / "candidate-artifacts"
        artifact_root.mkdir()

        def result_for(artifact_kind, fit_scope, market_id):
            name = f"{fit_scope.replace(':', '-')}-{market_id or 'family'}-{artifact_kind}.json"
            path = artifact_root / name
            path.write_text(
                json.dumps(
                    {
                        "artifact_kind": artifact_kind,
                        "fit_scope": fit_scope,
                        "market_id": market_id,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            return {"status": "ok", "artifact": path.as_posix()}

        def record_source(selection_inventory, artifact_kind, fit_scope, market_id):
            key = (artifact_kind, fit_scope, market_id)
            if key == omitted_source_key:
                return
            row_count = 0 if key == empty_source_key else 1
            selection_inventory.append(
                {
                    "artifact_kind": artifact_kind,
                    "fit_scope": fit_scope,
                    "market_id": market_id,
                    "folder_count": 1,
                    "folders": [
                        {
                            "path": f"snapshots/{market_id}-{unlocked_date}",
                            "target_date": unlocked_date,
                        }
                    ],
                    "row_count": row_count,
                    "row_target_dates": (
                        [{"target_date": unlocked_date, "row_count": row_count}]
                        if row_count
                        else []
                    ),
                }
            )

        def family_trainer(artifact_kind):
            def train(specs, family_unit, *_args, **kwargs):
                fit_scope = f"family:{family_unit}"
                for item in specs:
                    record_source(
                        kwargs["selection_inventory"],
                        artifact_kind,
                        fit_scope,
                        item.id,
                    )
                return result_for(artifact_kind, fit_scope, "")

            return train

        def market_trainer(artifact_kind):
            def train(item, *_args, **kwargs):
                record_source(
                    kwargs["selection_inventory"],
                    artifact_kind,
                    "market",
                    item.id,
                )
                return result_for(artifact_kind, "market", item.id)

            return train

        with (
            patch.object(
                family_secondary,
                "_verified_preselection",
                return_value=preselection,
            ),
            patch.object(family_secondary, "family_specs", return_value=[spec]),
            patch.object(
                family_secondary,
                "train_family_probability_artifact",
                side_effect=family_trainer("probability_calibration"),
            ),
            patch.object(
                family_secondary,
                "train_family_forecast_error_artifact",
                side_effect=family_trainer("forecast_error"),
            ),
            patch.object(
                family_secondary,
                "train_family_settlement_lag_artifact",
                side_effect=family_trainer("settlement_lag"),
            ),
            patch.object(
                family_secondary,
                "train_probability_artifact",
                side_effect=market_trainer("probability_calibration"),
            ),
            patch.object(
                family_secondary,
                "train_forecast_error_artifact",
                side_effect=market_trainer("forecast_error"),
            ),
            patch.object(
                family_secondary,
                "train_settlement_lag_artifact",
                side_effect=market_trainer("settlement_lag"),
            ),
            patch.object(
                family_secondary,
                "score_all_markets",
                return_value=[
                    {
                        "market": spec.id,
                        "trust_score": 100,
                        "settled_days": 100,
                    }
                ],
            ) as score_all,
        ):
            manifest = family_secondary.build_family_manifest(
                snapshots_root=Path("snapshots"),
                preselection=preselection,
                artifact_root=artifact_root,
            )
        return manifest, preselection, score_all

    def test_gate_allows_ml_only_when_trust_days_and_artifacts_clear(self):
        gate = gate_for_market(
            {"trust_score": 50, "settled_days": 3},
            self._artifact_statuses(),
            min_trust=25,
            min_settled_days=2,
        )

        self.assertEqual(gate["mode"], "ml")

    def test_gate_falls_back_empirical_for_unproven_market(self):
        gate = gate_for_market(
            {"trust_score": 15, "settled_days": 1},
            self._artifact_statuses(),
            min_trust=25,
            min_settled_days=2,
        )

        self.assertEqual(gate["mode"], "empirical")
        self.assertIn("trust 15 < 25", gate["reason"])
        self.assertIn("settled_days 1 < 2", gate["reason"])

    def test_feature_model_allowed_reads_market_gate_from_manifest(self):
        manifest = {
            "family_unit": "F",
            "markets": {
                "denver": {
                    "serving_gate": {
                        "mode": "empirical",
                        "reason": "trust 15 < 25",
                    },
                },
            },
        }

        self.assertFalse(feature_model_allowed(manifest, "denver"))
        self.assertEqual(market_gate(manifest, "toronto")["mode"], "ml")

    def test_feature_mixin_short_circuits_governed_unproven_market(self):
        manifest = {
            "family_unit": "F",
            "markets": {
                "denver": {
                    "serving_gate": {
                        "mode": "empirical",
                        "reason": "trust 15 < 25",
                    },
                },
            },
        }
        model = _DummyModel(manifest)

        self.assertFalse(model.family_secondary_feature_model_allowed())
        self.assertEqual(model._last_family_secondary_gate["reason"], "trust 15 < 25")

    def test_feature_mixin_ignores_non_family_units(self):
        manifest = {"family_unit": "F", "markets": {}}
        model = _DummyModel(manifest, market_id="toronto", unit="C")

        self.assertTrue(model.family_secondary_feature_model_allowed())

    def test_only_preselection_training_universe_reaches_secondary_selection(self):
        allowed_date = "2025-12-01"
        older_outside_date = "2025-11-30"
        locked_date = "2026-01-01"
        newer_outside_date = "2026-01-15"
        folders_by_date = {
            older_outside_date: Path(
                "highest-temperature-in-denver-on-november-30-2025"
            ),
            allowed_date: Path(
                "highest-temperature-in-denver-on-december-1-2025"
            ),
            locked_date: Path(
                "highest-temperature-in-denver-on-january-1-2026"
            ),
            newer_outside_date: Path(
                "highest-temperature-in-denver-on-january-15-2026"
            ),
        }
        allowed_folder = folders_by_date[allowed_date]
        discovered_folders = list(folders_by_date.values())
        spec = SimpleNamespace(
            id="denver",
            data_root=Path("weather-data"),
            icao="KDEN",
        )

        selections = []
        for changed_value in (1, 999_999):
            def probability_rows(folders, **_kwargs):
                self.assertEqual(folders, [allowed_folder])
                return [
                    {"target_date": allowed_date, "value": 7},
                    {
                        "target_date": older_outside_date,
                        "value": changed_value,
                    },
                    {"target_date": locked_date, "value": changed_value},
                    {
                        "target_date": newer_outside_date,
                        "value": changed_value,
                    },
                ]

            def history_rows(*_args, **_kwargs):
                return [
                    {"target_date": allowed_date, "value": 7},
                    {
                        "target_date": older_outside_date,
                        "value": changed_value,
                    },
                    {"target_date": locked_date, "value": changed_value},
                    {
                        "target_date": newer_outside_date,
                        "value": changed_value,
                    },
                ]

            inventory = []
            with (
                patch.object(
                    family_secondary.probability_calibration,
                    "discover_default_folders",
                    return_value=discovered_folders,
                ),
                patch.object(
                    family_secondary.probability_calibration,
                    "read_scored_rows",
                    side_effect=probability_rows,
                ),
                patch.object(
                    family_secondary.forecast_error,
                    "discover_default_folders",
                    return_value=discovered_folders,
                ),
                patch.object(
                    family_secondary.forecast_error,
                    "read_training_rows",
                    side_effect=history_rows,
                ),
                patch.object(
                    family_secondary.forecast_error,
                    "regime_for_spec",
                    return_value="test-regime",
                ),
                patch.object(
                    family_secondary.settlement_lag,
                    "discover_default_folders",
                    return_value=discovered_folders,
                ),
                patch.object(
                    family_secondary.settlement_lag,
                    "read_training_rows",
                    side_effect=history_rows,
                ),
                patch.object(
                    family_secondary,
                    "daily_path_for",
                    return_value=Path("forecast-history.csv"),
                ),
            ):
                probability, folders, _ = probability_training_rows(
                    spec,
                    Path("snapshots"),
                    ["all"],
                    locked_dates=[locked_date],
                    included_target_dates=[allowed_date],
                    selection_inventory=inventory,
                )
                forecast, forecast_folders = forecast_error_training_rows(
                    spec,
                    Path("snapshots"),
                    locked_dates=[locked_date],
                    included_target_dates=[allowed_date],
                    selection_inventory=inventory,
                )
                lag, lag_folders = settlement_lag_training_rows(
                    spec,
                    Path("snapshots"),
                    locked_dates=[locked_date],
                    included_target_dates=[allowed_date],
                    selection_inventory=inventory,
                )

            self.assertEqual(folders, [allowed_folder])
            self.assertEqual(forecast_folders, [allowed_folder])
            self.assertEqual(lag_folders, [allowed_folder])
            selections.append((probability, forecast, lag, inventory))

        self.assertEqual(selections[0], selections[1])
        serialized = json.dumps(selections[0], default=str)
        for disallowed_date in (
            older_outside_date,
            locked_date,
            newer_outside_date,
        ):
            self.assertNotIn(disallowed_date, serialized)
            self.assertNotIn(str(folders_by_date[disallowed_date]), serialized)

    def test_malformed_production_preselection_lock_fails_before_training(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock_path = root / "malformed-preselection.json"
            lock_path.write_text("{}", encoding="utf-8")
            args = build_parser().parse_args(
                [
                    "train",
                    "--point-in-time-preselection-lock",
                    str(lock_path),
                    "--out",
                    str(root / "manifest.json"),
                    "--report",
                    str(root / "report.md"),
                ]
            )

            with self.assertRaisesRegex(
                SystemExit,
                "Invalid production point-in-time preselection lock",
            ):
                cmd_train(args)

    def test_selection_binding_is_self_contained_and_hashes_used_inventory(self):
        locked_dates = [f"2026-01-{day:02d}" for day in range(1, 15)]
        preselection = {
            "preselection_hash": "a" * 64,
            "selection_universe": {
                "sha256": "c" * 64,
                "fleet_dates": ["2025-12-01", *locked_dates],
            },
            "window_lock": {
                "window_lock_id": "b" * 64,
                "target_dates": locked_dates,
            },
        }
        inventory = [
            {
                "artifact_kind": "forecast_error",
                "fit_scope": "market",
                "market_id": "denver",
                "folder_count": 1,
                "folders": [
                    {
                        "path": "snapshot-december-1",
                        "target_date": "2025-12-01",
                    }
                ],
                "row_count": 2,
                "row_target_dates": [
                    {"target_date": "2025-12-01", "row_count": 2}
                ],
            }
        ]

        output_inventory = family_secondary._hashed_inventory(
            [
                {
                    "artifact_kind": "forecast_error",
                    "fit_scope": "market",
                    "market_id": "denver",
                    "path": "candidate/forecast-error.json",
                    "sha256": "c" * 64,
                    "bytes": 123,
                }
            ]
        )
        binding = family_secondary._selection_binding(
            preselection,
            inventory,
            output_inventory,
        )

        self.assertEqual(binding["preselection_hash"], "a" * 64)
        self.assertEqual(binding["window_lock_id"], "b" * 64)
        self.assertEqual(binding["selection_universe_sha256"], "c" * 64)
        self.assertEqual(
            binding["selection_universe_dates"],
            ["2025-12-01", *locked_dates],
        )
        self.assertEqual(binding["training_universe_dates"], ["2025-12-01"])
        self.assertEqual(
            binding["training_universe_sha256"],
            family_secondary._sha256_json(["2025-12-01"]),
        )
        self.assertEqual(binding["locked_dates"], locked_dates)
        self.assertIs(binding["used_for_selection"], False)
        self.assertEqual(binding["trust_as_of_exclusive"], locked_dates[0])
        self.assertEqual(
            binding["trust_date_scope"],
            "exact_preselection_training_universe",
        )
        self.assertEqual(
            binding["trust_included_target_dates_sha256"],
            binding["training_universe_sha256"],
        )
        self.assertEqual(
            binding["source_folder_date_inventory_sha256"],
            binding["source_inventory"]["sha256"],
        )
        self.assertEqual(
            binding["output_artifact_inventory_sha256"],
            output_inventory["sha256"],
        )
        unhashed = dict(binding)
        unhashed.pop("binding_sha256")
        self.assertEqual(
            binding["binding_sha256"],
            family_secondary._sha256_json(unhashed),
        )

    def test_production_manifest_hashes_every_output_and_cuts_off_trust(self):
        with TemporaryDirectory() as temp_dir:
            manifest, preselection, score_all = (
                self._build_production_manifest_fixture(temp_dir)
            )

            binding = manifest["point_in_time_selection_binding"]
            output_inventory = manifest["output_artifact_inventory"]
            self.assertEqual(binding["preselection_hash"], "a" * 64)
            self.assertEqual(
                binding["locked_dates"],
                preselection["window_lock"]["target_dates"],
            )
            self.assertEqual(output_inventory["entry_count"], 6)
            self.assertEqual(binding["output_artifacts"], output_inventory)
            self.assertTrue(
                all(
                    len(result["artifact_sha256"]) == 64
                    and result["artifact_bytes"] > 0
                    for result in [
                        *manifest["family_artifacts"].values(),
                        *manifest["markets"]["denver"]["artifacts"].values(),
                    ]
                )
            )
            with patch.object(
                family_secondary,
                "_verified_preselection",
                return_value=preselection,
            ):
                family_secondary.verify_production_family_manifest(
                    manifest,
                    preselection=preselection,
                )
            score_all.assert_called_once_with(
                root=Path("snapshots"),
                as_of=preselection["window_lock"]["target_dates"][0],
                included_target_dates=["2025-12-01"],
            )

    def test_production_manifest_rejects_incomplete_selection_coverage(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                ValueError,
                "source inventory coverage is incomplete",
            ):
                self._build_production_manifest_fixture(
                    temp_dir,
                    omitted_source_key=(
                        "forecast_error",
                        "family:F",
                        "denver",
                    ),
                )

    def test_production_manifest_rejects_empty_selection_stage(self):
        with TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                ValueError,
                "empty selection stage",
            ):
                self._build_production_manifest_fixture(
                    temp_dir,
                    empty_source_key=(
                        "settlement_lag",
                        "market",
                        "denver",
                    ),
                )

    def test_production_manifest_rejects_outside_universe_selection_date(self):
        with TemporaryDirectory() as temp_dir:
            manifest, preselection, _score_all = (
                self._build_production_manifest_fixture(temp_dir)
            )
            binding = manifest["point_in_time_selection_binding"]
            inventory = binding["source_inventory"]
            first_entry = inventory["entries"][0]
            first_entry["folders"][0]["target_date"] = "2025-11-30"
            first_entry["row_target_dates"][0]["target_date"] = "2025-11-30"
            unhashed_inventory = dict(inventory)
            unhashed_inventory.pop("sha256")
            inventory["sha256"] = family_secondary._sha256_json(
                unhashed_inventory
            )
            binding["source_folder_date_inventory_sha256"] = inventory["sha256"]
            unhashed_binding = dict(binding)
            unhashed_binding.pop("binding_sha256")
            binding["binding_sha256"] = family_secondary._sha256_json(
                unhashed_binding
            )

            with (
                patch.object(
                    family_secondary,
                    "_verified_preselection",
                    return_value=preselection,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "escaped the immutable preselection training universe",
                ),
            ):
                family_secondary.verify_production_family_manifest(
                    manifest,
                    preselection=preselection,
                )

    def test_production_manifest_rejects_output_mutation(self):
        with TemporaryDirectory() as temp_dir:
            manifest, preselection, _score_all = (
                self._build_production_manifest_fixture(temp_dir)
            )
            artifact_path = Path(
                manifest["output_artifact_inventory"]["entries"][0]["path"]
            )
            artifact_path.write_text('{"tampered":true}', encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "output artifact hash changed",
            ):
                family_secondary.verify_production_family_manifest(
                    manifest,
                    preselection=preselection,
                )

    def test_production_manifest_rejects_missing_output_identity(self):
        with TemporaryDirectory() as temp_dir:
            manifest, preselection, _score_all = (
                self._build_production_manifest_fixture(temp_dir)
            )
            manifest["family_artifacts"]["forecast_error"].pop(
                "artifact_sha256"
            )

            with self.assertRaisesRegex(
                ValueError,
                "output artifact identity is missing",
            ):
                family_secondary.verify_production_family_manifest(
                    manifest,
                    preselection=preselection,
                )

    def test_production_manifest_rejects_empty_market_scope(self):
        locked_dates = [f"2026-01-{day:02d}" for day in range(1, 15)]
        preselection = {
            "preselection_hash": "a" * 64,
            "selection_universe": {
                "sha256": "c" * 64,
                "fleet_dates": ["2025-12-01", *locked_dates],
            },
            "window_lock": {
                "window_lock_id": "b" * 64,
                "target_dates": locked_dates,
            },
        }
        skipped = {"status": "skipped"}
        with (
            patch.object(
                family_secondary,
                "_verified_preselection",
                return_value=preselection,
            ),
            patch.object(family_secondary, "family_specs", return_value=[]),
            patch.object(
                family_secondary,
                "train_family_probability_artifact",
                return_value=skipped,
            ),
            patch.object(
                family_secondary,
                "train_family_forecast_error_artifact",
                return_value=skipped,
            ),
            patch.object(
                family_secondary,
                "train_family_settlement_lag_artifact",
                return_value=skipped,
            ),
            patch.object(
                family_secondary,
                "score_all_markets",
                return_value=[],
            ),
            self.assertRaisesRegex(
                ValueError,
                "requires at least one market",
            ),
        ):
            family_secondary.build_family_manifest(
                snapshots_root=Path("snapshots"),
                preselection=preselection,
                artifact_root=Path("candidate-artifacts"),
            )


if __name__ == "__main__":
    unittest.main()
