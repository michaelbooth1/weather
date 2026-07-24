import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.calibration.pooled_candidate_replay import (
    _write_sentinel_forensics,
)
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    corpus_hash,
)
from weather.reporting.promotion.promotion_refresh import (
    build_parser,
    run_promotion_refresh,
)


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sandbox_state(root, excluded):
    root = Path(root).resolve()
    excluded = Path(excluded).resolve()
    state = {}
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if resolved == excluded or excluded in resolved.parents:
            continue
        relative = resolved.relative_to(root).as_posix()
        state[relative] = (
            ("dir", None)
            if resolved.is_dir()
            else ("file", hashlib.sha256(resolved.read_bytes()).hexdigest())
        )
    return state


def _frozen_manifest(path, snapshots_root):
    entries = [
        {
            "event_slug": "highest-temperature-in-nyc-on-july-1-2026",
            "market_id": "nyc",
            "target_date": "2026-07-01",
            "folder": str(Path(snapshots_root) / "immutable-input"),
            "folder_name": "immutable-input",
            "folder_relative_to_snapshots_root": "immutable-input",
            "settlement_bucket": 80,
            "settlement_unit": "F",
            "settlement_source": "fixture",
            "winning_band": "80-81",
            "quality_grade": "complete",
            "admitted_by": "quality_grade",
            "snapshot_ids": ["08:00"],
            "snapshot_count": 1,
            "row_count": 2,
            "replay_record_hashes": {"08:00": "1" * 64},
            "tape_row_hashes": {"08:00": "2" * 64},
            "label_hash": "3" * 64,
        }
    ]
    payload = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": "2026-07-24T00:00:00+00:00",
        "as_of": "2026-07-24",
        "snapshots_root": str(snapshots_root),
        "quality_grades": ["complete", "manual_override"],
        "include_reconstructed": False,
        "allow_unsettled": False,
        "admit_promotion_countable": False,
        "min_snapshots": 1,
        "market_filter": None,
        "entries": entries,
        "summary": {"market_count": 1, "market_day_count": 1},
        "skipped": [],
        "corpus_hash": corpus_hash(entries),
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


class TestPromotionOutputContainment(unittest.TestCase):
    def test_frozen_promotion_tree_writes_only_below_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            inputs = sandbox / "inputs"
            snapshots = inputs / "snapshots"
            snapshots.mkdir(parents=True)
            frozen_path = inputs / "frozen-corpus.json"
            frozen = _frozen_manifest(frozen_path, snapshots)
            (inputs / "sentinel.txt").write_text("unchanged", encoding="utf-8")
            artifact = inputs / "candidate.pkl"
            artifact.write_bytes(b"immutable candidate")
            run_root = sandbox / "candidate" / "qualification" / "promotion"
            run_root.mkdir(parents=True)
            before = _sandbox_state(sandbox, run_root)

            args = build_parser().parse_args(
                [
                    "--output-root",
                    str(run_root),
                    "--frozen-corpus",
                    str(frozen_path),
                    "--frozen-corpus-sha256",
                    _sha256_file(frozen_path),
                    "--frozen-corpus-hash",
                    frozen["corpus_hash"],
                    "--snapshots-root",
                    str(snapshots),
                    "--artifact",
                    str(artifact),
                    "--disable-long-job-guard",
                ]
            )

            def fake_candidate(candidate_args):
                self.assertEqual(
                    candidate_args.expected_corpus_sha256,
                    _sha256_file(candidate_args.corpus),
                )
                self.assertEqual(
                    candidate_args.expected_corpus_hash,
                    frozen["corpus_hash"],
                )
                for attribute in (
                    "out",
                    "json_out",
                    "replay_report",
                    "replay_cache_root",
                    "candidate_variant_out",
                    "microstructure_artifact",
                    "microstructure_variant_out",
                    "source_state_ablation_variant_out",
                    "bridge_variant_out",
                    "sentinel_forensics_root",
                ):
                    value = getattr(candidate_args, attribute)
                    Path(value).resolve().relative_to(run_root.resolve())
                for path, text in (
                    (candidate_args.out, "candidate report\n"),
                    (candidate_args.replay_report, "candidate replay\n"),
                ):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(text, encoding="utf-8")
                Path(candidate_args.json_out).parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                Path(candidate_args.json_out).write_text(
                    '{"verdict":"PASS"}',
                    encoding="utf-8",
                )
                cache_marker = Path(candidate_args.replay_cache_root) / "marker"
                cache_marker.parent.mkdir(parents=True, exist_ok=True)
                cache_marker.write_text("cache", encoding="utf-8")
                _write_sentinel_forensics(
                    consumer="containment-regression",
                    key=SimpleNamespace(
                        metadata=lambda: {"event_slug": "fixture"}
                    ),
                    cached_rows=[{"candidate_p": 0.4}],
                    fresh_rows=[{"candidate_p": 0.6}],
                    cached_path=str(cache_marker),
                    output_root=candidate_args.sentinel_forensics_root,
                )
                return {
                    "verdict": "PASS",
                    "artifact": {"artifact_hash": "a" * 64},
                    "corpus": {
                        "corpus_hash": frozen["corpus_hash"],
                        "file_sha256": candidate_args.expected_corpus_sha256,
                    },
                    "market_rows": [
                        {
                            "market_id": "nyc",
                            "trust": {
                                "trust_score": 91,
                                "grade": "A",
                                "settled_days": 12,
                            },
                        }
                    ],
                }

            def fake_gauntlet(gauntlet_args):
                self.assertEqual(
                    gauntlet_args.expected_corpus_sha256,
                    _sha256_file(gauntlet_args.corpus),
                )
                self.assertEqual(
                    gauntlet_args.expected_corpus_hash,
                    frozen["corpus_hash"],
                )
                for path in (gauntlet_args.out, gauntlet_args.replay_report):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text("gauntlet\n", encoding="utf-8")
                return {
                    "verdict": "PASS_WITH_SHADOWS",
                    "corpus_ok": True,
                    "fidelity_ok": True,
                    "results": {
                        "promotion_corpus": {
                            "corpus_hash": frozen["corpus_hash"]
                        }
                    },
                }

            def fake_runtime_identity(**kwargs):
                path = Path(kwargs["reconciliation_path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"status":"PASS"}', encoding="utf-8")
                return {"status": "PASS", "path": str(path)}

            decisions = {
                "promote_markets": [],
                "shadow_markets": ["nyc"],
                "blocked_markets": [],
                "markets": [{"market_id": "nyc", "action": "KEEP_SHADOW"}],
            }
            gap_rows = [
                {
                    "owner": "exact-band calibration",
                    "roadmap_owner": "Item 48",
                    "slice": "band_type",
                    "group": "eq",
                    "excess_brier_rows": 1.0,
                    "affected_markets": ["nyc"],
                    "claim_lane": "weather_only_core_model",
                    "counts_toward_core_skill_claim": True,
                    "next_experiment": "exact_band_calibration_daily_first",
                    "experiment_artifact": (
                        "data/backtest/experiments/"
                        "exact_band_calibration_daily_first.json"
                    ),
                    "clearance_rule": "delta_vs_market must be <= 0",
                }
            ]

            patches = (
                patch(
                    "weather.reporting.promotion.orchestration.build_promotion_corpus",
                    side_effect=AssertionError("live corpus rebuild is forbidden"),
                ),
                patch(
                    "weather.reporting.promotion.orchestration.score_all_markets",
                    side_effect=AssertionError(
                        "outer live trust discovery is forbidden"
                    ),
                ),
                patch(
                    "weather.reporting.promotion.orchestration.run_pooled_candidate_replay",
                    side_effect=fake_candidate,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.run_promotion_gauntlet",
                    side_effect=fake_gauntlet,
                ),
                patch(
                    "weather.reporting.promotion.orchestration._family_specs",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration._candidate_summary",
                    return_value={
                        "verdict": "PASS",
                        "aggregate": {},
                        "slices": {},
                    },
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_family_decisions",
                    return_value=decisions,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_promotion_allowlist",
                    return_value={"schema_version": "fixture", "markets": []},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_runtime_identity_evidence",
                    side_effect=fake_runtime_identity,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_gap_owner_table",
                    return_value=gap_rows,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.model_skill_claims",
                    return_value={},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.market_skill_diagnostics",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration.promotion_readiness",
                    return_value={"status": "OPEN", "blockers": []},
                ),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    patches[5], patches[6], patches[7], patches[8], patches[9], \
                    patches[10], patches[11], patches[12]:
                payload, out_path, report_path = run_promotion_refresh(args)

            after = _sandbox_state(sandbox, run_root)
            self.assertEqual(after, before)
            self.assertEqual(Path(out_path), run_root / "promotion_refresh.json")
            self.assertEqual(
                Path(report_path),
                run_root / "promotion_refresh_report.md",
            )
            self.assertTrue(
                (
                    run_root
                    / "experiments"
                    / "exact_band_calibration_daily_first.json"
                ).is_file()
            )
            self.assertTrue(payload["output_containment"]["enabled"])
            self.assertEqual(
                json.loads(
                    (run_root / "trust" / "location_trust.json").read_text(
                        encoding="utf-8"
                    )
                ),
                [
                    {
                        "grade": "A",
                        "market": "nyc",
                        "settled_days": 12,
                        "trust_score": 91,
                    }
                ],
            )
            for row in payload["output_containment"]["outputs"]:
                Path(row["path"]).resolve().relative_to(run_root.resolve())

    def test_missing_output_root_fails_before_guard_or_heavy_work(self):
        args = build_parser().parse_args(["--disable-long-job-guard"])
        with patch(
            "weather.reporting.promotion.orchestration.long_job_guard"
        ) as guard, patch(
            "weather.reporting.promotion.orchestration.build_promotion_corpus"
        ) as live_build, patch(
            "weather.reporting.promotion.orchestration.run_pooled_candidate_replay"
        ) as heavy_work:
            with self.assertRaisesRegex(ValueError, "requires --output-root"):
                run_promotion_refresh(args)
        guard.assert_not_called()
        live_build.assert_not_called()
        heavy_work.assert_not_called()

    def test_live_promotion_tree_writes_only_below_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            inputs = sandbox / "inputs"
            snapshots = inputs / "snapshots"
            snapshots.mkdir(parents=True)
            fixture_path = inputs / "fixture-corpus.json"
            manifest = _frozen_manifest(fixture_path, snapshots)
            (inputs / "sentinel.txt").write_text("unchanged", encoding="utf-8")
            run_root = sandbox / "candidate" / "qualification" / "promotion"
            run_root.mkdir(parents=True)
            before = _sandbox_state(sandbox, run_root)
            args = build_parser().parse_args(
                [
                    "--output-root",
                    str(run_root),
                    "--snapshots-root",
                    str(snapshots),
                    "--skip-serving-gauntlet",
                    "--disable-long-job-guard",
                ]
            )
            candidate_report = {
                "verdict": "PASS",
                "artifact": {"artifact_hash": "b" * 64},
                "corpus": {
                    "corpus_hash": manifest["corpus_hash"],
                    "file_sha256": _sha256_file(fixture_path),
                },
                "market_rows": [
                    {
                        "market_id": "nyc",
                        "trust": {
                            "trust_score": 88,
                            "grade": "A",
                            "settled_days": 11,
                        },
                    }
                ],
            }
            decisions = {
                "promote_markets": [],
                "shadow_markets": ["nyc"],
                "blocked_markets": [],
                "markets": [{"market_id": "nyc", "action": "KEEP_SHADOW"}],
            }
            with (
                patch(
                    "weather.reporting.promotion.orchestration.build_promotion_corpus",
                    return_value=manifest,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.score_all_markets",
                    side_effect=AssertionError(
                        "outer live trust discovery is forbidden"
                    ),
                ),
                patch(
                    "weather.reporting.promotion.orchestration.run_pooled_candidate_replay",
                    return_value=candidate_report,
                ),
                patch(
                    "weather.reporting.promotion.orchestration._family_specs",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration._candidate_summary",
                    return_value={"verdict": "PASS", "aggregate": {}, "slices": {}},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_family_decisions",
                    return_value=decisions,
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_promotion_allowlist",
                    return_value={"schema_version": "fixture", "markets": []},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_runtime_identity_evidence",
                    return_value={"status": "PASS"},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.build_gap_owner_table",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration.write_gap_experiment_artifacts",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration.model_skill_claims",
                    return_value={},
                ),
                patch(
                    "weather.reporting.promotion.orchestration.market_skill_diagnostics",
                    return_value=[],
                ),
                patch(
                    "weather.reporting.promotion.orchestration.promotion_readiness",
                    return_value={"status": "OPEN", "blockers": []},
                ),
            ):
                payload, out_path, report_path = run_promotion_refresh(args)

            self.assertEqual(_sandbox_state(sandbox, run_root), before)
            self.assertEqual(Path(out_path), run_root / "promotion_refresh.json")
            self.assertEqual(
                Path(report_path), run_root / "promotion_refresh_report.md"
            )
            self.assertEqual(
                json.loads(
                    (run_root / "trust" / "location_trust.json").read_text(
                        encoding="utf-8"
                    )
                )[0]["trust_score"],
                88,
            )
            for row in payload["output_containment"]["outputs"]:
                Path(row["path"]).resolve().relative_to(run_root.resolve())

    def test_frozen_identity_mismatch_fails_before_live_or_heavy_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_path = root / "frozen.json"
            frozen = _frozen_manifest(frozen_path, root / "snapshots")
            output_root = root / "run"
            args = build_parser().parse_args(
                [
                    "--output-root",
                    str(output_root),
                    "--frozen-corpus",
                    str(frozen_path),
                    "--frozen-corpus-sha256",
                    "0" * 64,
                    "--frozen-corpus-hash",
                    frozen["corpus_hash"],
                    "--disable-long-job-guard",
                ]
            )
            with patch(
                "weather.reporting.promotion.orchestration.build_promotion_corpus"
            ) as live_build, patch(
                "weather.reporting.promotion.orchestration.run_pooled_candidate_replay"
            ) as heavy_work:
                with self.assertRaisesRegex(ValueError, "file identity mismatch"):
                    run_promotion_refresh(args)
            live_build.assert_not_called()
            heavy_work.assert_not_called()

    def test_frozen_semantic_identity_mismatch_fails_before_heavy_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_path = root / "frozen.json"
            _frozen_manifest(frozen_path, root / "snapshots")
            args = build_parser().parse_args(
                [
                    "--output-root",
                    str(root / "run"),
                    "--frozen-corpus",
                    str(frozen_path),
                    "--frozen-corpus-sha256",
                    _sha256_file(frozen_path),
                    "--frozen-corpus-hash",
                    "f" * 64,
                    "--disable-long-job-guard",
                ]
            )
            with patch(
                "weather.reporting.promotion.orchestration.run_pooled_candidate_replay"
            ) as heavy_work:
                with self.assertRaisesRegex(
                    ValueError,
                    "semantic identity mismatch",
                ):
                    run_promotion_refresh(args)
            heavy_work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
