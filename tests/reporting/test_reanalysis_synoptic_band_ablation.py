import copy
import hashlib
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weather.reporting.research.reanalysis_synoptic_band_ablation import (
    DEFAULT_JSON_OUT,
    DEFAULT_REPORT_OUT,
    DEFAULT_SOURCE_FAMILY_ABLATION,
    EVIDENCE_SOURCE,
    _candidate_rows_from_captured,
    _capture_candidate_inputs,
    _load_bound_artifact,
    _preflight_output_paths,
    _score_captured_ablation_arms,
    build_ablation_payload,
    merge_source_family_ablation,
    masked_reanalysis_artifact,
    paired_ablation_rows,
    run_report,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_ablation_operational_contract,
)
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import corpus_hash
from tests.reporting.source_family_contract_fixtures import (
    operational_ablation_payload,
    synthetic_receipt,
)


def _row(
    snapshot_id,
    distance,
    base_p,
    *,
    market_id="atlanta",
    outcome=1,
    target_date="2026-06-07",
):
    return {
        "market_id": market_id,
        "snapshot_id": snapshot_id,
        "target_date": target_date,
        "bin_type": "eq",
        "bin_value": "84",
        "bin_value_hi": "84",
        "candidate_cutoff_hour": 8,
        "candidate_cutoff_regime": "early",
        "settlement_distance_bucket": distance,
        "candidate_p": base_p,
        "market_yes": 0.40,
        "outcome": outcome,
        "settlement_source": "daily_summary",
    }


def _candidate_supplemental(*, row_count=30, delta=0.2):
    payload = operational_ablation_payload(
        [{"variant": "reanalysis_synoptic", "n": row_count, "delta": delta}]
    )
    receipt = synthetic_receipt("C:/synthetic/candidate.pkl", "a")
    payload.update(
        {
            "evidence_source": EVIDENCE_SOURCE,
            "artifact": {
                "path": receipt["path"],
                "sha256": receipt["sha256"],
                "size_bytes": receipt["size_bytes"],
                "prediction_mode": "band_binary",
            },
            "model_binding": {
                "status": "BOUND_CANDIDATE_ARTIFACT",
                "binding_kind": "candidate_artifact",
                "promotion_evidence_binding": True,
                "artifact_path": receipt["path"],
                "artifact_sha256": receipt["sha256"],
                "prediction_mode": "band_binary",
                "serving_or_release_authorization": False,
            },
        }
    )
    payload["input_receipts"]["artifact"] = receipt
    payload["variants"][0]["evidence_source"] = EVIDENCE_SOURCE
    return payload


class TestReanalysisSynopticBandAblation(unittest.TestCase):
    def test_default_research_outputs_live_outside_the_mirrored_data_tree(self):
        self.assertIn("scratch", DEFAULT_JSON_OUT.parts)
        self.assertIn("scratch", DEFAULT_REPORT_OUT.parts)

    def test_candidate_artifact_correct_hash_is_not_an_independent_trust_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.pkl"
            raw = pickle.dumps({"models": {"atlanta": object()}})
            path.write_bytes(raw)

            with (
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation.pickle.loads"
                ) as loads,
                self.assertRaisesRegex(ValueError, "independently anchored"),
            ):
                _load_bound_artifact(
                    path,
                    expected_sha256=hashlib.sha256(raw).hexdigest(),
                )

            loads.assert_not_called()

    def test_candidate_artifact_is_authenticated_before_pickle_deserialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.pkl"
            path.write_bytes(pickle.dumps({"models": {"atlanta": object()}}))

            with (
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation.pickle.loads"
                ) as loads,
                self.assertRaisesRegex(ValueError, "caller-supplied"),
            ):
                _load_bound_artifact(path, expected_sha256="0" * 64)

            loads.assert_not_called()

    def test_base_and_masked_arms_share_one_captured_input_generation(self):
        artifact = {
            "models": {"8": {}},
            "prediction_mode": "band_binary",
            "family_unit": "F",
        }
        feature_rows = {
            ("atlanta", "s1"): {
                "market_id": "atlanta",
                "reanalysis_prev_day_max_temp": 82.0,
            }
        }
        replay_results = {"all_rows": []}
        seen = []

        def attach(_replay, features, *_args, **_kwargs):
            seen.append(features[("atlanta", "s1")]["reanalysis_prev_day_max_temp"])
            return ([{"candidate_cutoff_hour": 8}], {"candidate_rows": 1})

        with (
            mock.patch(
                "weather.reporting.research.reanalysis_synoptic_band_ablation.build_candidate_features",
                return_value=(feature_rows, {"feature_reads": 1}),
            ) as build_features,
            mock.patch(
                "weather.reporting.research.reanalysis_synoptic_band_ablation.build_clob_feature_index",
                return_value=({}, {"clob_reads": 1}),
            ) as build_clob,
            mock.patch(
                "weather.reporting.research.reanalysis_synoptic_band_ablation.build_source_freshness_index",
                return_value=({}, {"freshness_reads": 1}),
            ) as build_freshness,
            mock.patch(
                "weather.reporting.research.reanalysis_synoptic_band_ablation.attach_band_candidate_probabilities",
                side_effect=attach,
            ),
        ):
            captured = _capture_candidate_inputs("manifest", "snapshots", artifact)
            _candidate_rows_from_captured(captured, artifact, replay_results)
            masked = masked_reanalysis_artifact(artifact)
            _candidate_rows_from_captured(
                captured,
                masked,
                replay_results,
                reanalysis_lane=masked["reanalysis_promotion_lane"],
            )

        self.assertEqual(seen, [82.0, None])
        self.assertEqual(
            captured["feature_rows"][("atlanta", "s1")][
                "reanalysis_prev_day_max_temp"
            ],
            82.0,
        )
        build_features.assert_called_once()
        build_clob.assert_called_once()
        build_freshness.assert_called_once()

    def test_base_and_masked_artifacts_are_cloned_before_either_scores(self):
        artifact = {
            "models": {"8": {"state": []}},
            "prediction_mode": "band_binary",
            "family_unit": "F",
        }
        captured = {
            "family_unit": "F",
            "feature_rows": {},
            "clob_features": {},
            "source_freshness": {},
            "diagnostics": {},
        }
        states_before_scoring = []
        artifact_ids = []

        def stateful_score(
            _captured,
            scoring_artifact,
            _replay,
            *,
            reanalysis_lane=None,
        ):
            state = scoring_artifact["models"]["8"]["state"]
            states_before_scoring.append(list(state))
            artifact_ids.append(id(scoring_artifact))
            state.append("mutated-by-score")
            return [], {"masked": bool(reanalysis_lane)}

        with mock.patch(
            "weather.reporting.research.reanalysis_synoptic_band_ablation."
            "_candidate_rows_from_captured",
            side_effect=stateful_score,
        ):
            _score_captured_ablation_arms(captured, artifact, {"all_rows": []})

        self.assertEqual(states_before_scoring, [[], []])
        self.assertEqual(len(set(artifact_ids)), 2)
        self.assertEqual(artifact["models"]["8"]["state"], [])

    def test_pairs_full_and_masked_artifact_rows_for_source_family_payload(self):
        base = [
            _row("s1", "0", 0.70, outcome=1),
            _row("s2", "1", 0.20, outcome=0),
            _row("s3", "3+", 0.10, outcome=0, market_id="toronto"),
        ]
        masked = [
            _row("s1", "0", 0.55, outcome=1),
            _row("s2", "1", 0.30, outcome=0),
            _row("s3", "3+", 0.25, outcome=0, market_id="toronto"),
        ]

        rows = paired_ablation_rows(base, masked)
        payload = build_ablation_payload(rows, artifact_path="candidate.pkl", artifact_hash="abc")

        self.assertEqual(len(rows), 3)
        self.assertEqual(payload["schema_version"], "source_family_ablation_v0.2")
        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["promotion_preflight_evidence_authorization"])
        self.assertEqual(payload["evidence_mode"], "research")
        self.assertEqual(payload["model_binding"]["status"], "RESEARCH_UNBOUND")
        self.assertEqual(rows[0]["settlement_distance"], "exact")
        self.assertEqual(rows[1]["settlement_distance"], "adjacent")
        self.assertEqual(rows[2]["settlement_distance"], "far")
        [variant] = payload["variants"]
        self.assertEqual(variant["variant"], "reanalysis_synoptic")
        self.assertEqual(variant["evidence_source"], "candidate_artifact_band_ablation")
        self.assertTrue(any(row["slice"] == "settlement_distance" for row in payload["slice_effects"]))

    def test_operational_payload_is_disabled_without_sealed_execution_closure(self):
        base = [_row("s1", "0", 0.70)]
        masked = [_row("s1", "0", 0.55)]
        rows = paired_ablation_rows(base, masked)
        with self.assertRaisesRegex(ValueError, "sealed captured-input generation"):
            build_ablation_payload(rows, evidence_mode="operational")

    def test_merge_is_disabled_even_when_inputs_appear_authorized(self):
        base_payload = operational_ablation_payload(
            [{"variant": "open_meteo", "n": 10, "delta": 0.1}]
        )
        supplemental = _candidate_supplemental()

        with self.assertRaisesRegex(ValueError, "sealed captured-input generation"):
            merge_source_family_ablation(base_payload, supplemental)

    def test_merge_rejects_empty_destination_without_execution_closure(self):
        supplemental = _candidate_supplemental()

        with self.assertRaisesRegex(ValueError, "sealed captured-input generation"):
            merge_source_family_ablation({}, supplemental)

    def test_merge_rejects_unbound_supplement_before_publication(self):
        supplemental = _candidate_supplemental()
        unbound = copy.deepcopy(supplemental)
        unbound["schema_version"] = "source_family_ablation_v0.2"
        unbound["evidence_mode"] = "research"
        unbound["research_only"] = True
        unbound["promotion_preflight_evidence_authorization"] = False
        unbound["model_binding"]["status"] = "RESEARCH_UNBOUND"
        unbound["model_binding"]["promotion_evidence_binding"] = False
        with self.assertRaisesRegex(ValueError, "sealed captured-input generation"):
            merge_source_family_ablation({}, unbound)

    def test_pairing_rejects_duplicates_missing_rows_and_provenance_mismatch(self):
        base = [_row("s1", "0", 0.70)]
        masked = [_row("s1", "0", 0.55)]
        with self.assertRaisesRegex(ValueError, "duplicate pairing key"):
            paired_ablation_rows(base + [copy.deepcopy(base[0])], masked)
        with self.assertRaisesRegex(ValueError, "row keys differ"):
            paired_ablation_rows(base, [])
        mismatched = copy.deepcopy(masked)
        mismatched[0]["settlement_source"] = "other"
        with self.assertRaisesRegex(ValueError, "labels/provenance differ"):
            paired_ablation_rows(base, mismatched)

    def test_pairing_rejects_non_binary_outcomes(self):
        base = [_row("s1", "0", 0.70, outcome=2)]
        masked = [_row("s1", "0", 0.55, outcome=2)]
        with self.assertRaisesRegex(ValueError, "finite binary"):
            paired_ablation_rows(base, masked)

    def test_preflight_rejects_output_input_aliases_and_data_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "corpus.json"
            corpus.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "aliases input corpus"):
                _preflight_output_paths(
                    corpus,
                    root / "report.md",
                    input_paths={"corpus": corpus},
                )
        with self.assertRaisesRegex(ValueError, "mirrored/read-only data tree"):
            _preflight_output_paths(
                DEFAULT_SOURCE_FAMILY_ABLATION,
                DEFAULT_REPORT_OUT,
            )

    def test_preflight_rejects_stale_single_leaf_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_json = root / "result.json"
            stale_json.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already exists"):
                _preflight_output_paths(stale_json, root / "result.md")

    def test_corpus_warnings_fail_before_any_output_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "candidate.pkl"
            artifact_raw = pickle.dumps(
                {
                    "models": {"atlanta": object()},
                    "prediction_mode": "band_binary",
                }
            )
            artifact.write_bytes(artifact_raw)
            json_out = root / "out.json"
            report_out = root / "out.md"
            snapshots_root = root / "snapshots"
            snapshots_root.mkdir()
            with (
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation.load_manifest",
                    return_value={"include_reconstructed": False},
                ),
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation.folders_from_manifest_strict",
                    return_value=[],
                ),
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation._load_bound_artifact",
                    return_value=(
                        {
                            "models": {"atlanta": object()},
                            "prediction_mode": "band_binary",
                        },
                        {
                            "status": "PASS",
                            "path": str(artifact.resolve()),
                            "sha256": hashlib.sha256(artifact_raw).hexdigest(),
                            "size_bytes": len(artifact_raw),
                            "blockers": [],
                        },
                    ),
                ),
                mock.patch(
                    "weather.reporting.research.reanalysis_synoptic_band_ablation.run_replay_backtest",
                    return_value={"corpus_warnings": ["changed row"]},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "corpus warnings"):
                    run_report(
                        corpus=root / "corpus.json",
                        snapshots_root=snapshots_root,
                        artifact=artifact,
                        artifact_sha256=hashlib.sha256(artifact_raw).hexdigest(),
                        json_out=json_out,
                        report_out=report_out,
                    )
            self.assertFalse(json_out.exists())
            self.assertFalse(report_out.exists())

    def test_operational_cli_path_fails_before_any_output_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_out = root / "out.json"
            report_out = root / "out.md"
            with self.assertRaisesRegex(ValueError, "sealed captured-input generation"):
                run_report(
                    corpus=root / "missing-corpus.json",
                    snapshots_root=root / "snapshots",
                    artifact=root / "missing.pkl",
                    json_out=json_out,
                    report_out=report_out,
                    operational_evidence=True,
                )
            self.assertFalse(json_out.exists())
            self.assertFalse(report_out.exists())


if __name__ == "__main__":
    unittest.main()
