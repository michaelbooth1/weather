import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from weather.reporting.promotion.promotion_corpus import build_promotion_corpus, load_manifest, write_manifest
from weather.reporting.promotion.promotion_gauntlet import _baseline_gate_status, _decomposition, _overall_verdict, run_promotion_gauntlet
from weather.backtesting.replay_backtest import run_replay_backtest
from tests.backtesting.test_replay import SLUG, _build_corpus_day


def _write_label(folder, bucket=25):
    label = {
        "schema_version": "settlement_ledger_v1",
        "event_slug": SLUG,
        "market_id": "toronto",
        "city": "Toronto",
        "target_date": "2026-06-03",
        "settlement_high": bucket,
        "settlement_bucket": bucket,
        "settlement_unit": "C",
        "winning_band": f"{bucket} C",
        "winning_band_kind": "eq",
        "winning_band_value": bucket,
        "settlement_source": "test",
        "quality_grade": "complete",
        "quality_reason": "test label",
        "coverage_clean": True,
        "capture_ratio": 1.0,
        "max_gap_minutes": 10.0,
        "snapshot_tape_path": str(Path(folder) / "snapshots_long.csv"),
        "polymarket_url": f"https://polymarket.com/event/{SLUG}",
        "finalized_at_utc": "2026-06-04T00:00:00+00:00",
    }
    (Path(folder) / "settlement.json").write_text(json.dumps(label, sort_keys=True), encoding="utf-8")


def _append_unpinned_snapshot(folder):
    tape = Path(folder) / "snapshots_long.csv"
    with tape.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    extra = []
    for row in rows:
        copy = dict(row)
        copy["snapshot_id"] = "snap2"
        copy["captured_at_local"] = "2026-06-03T15:30:00-04:00"
        extra.append(copy)
    with tape.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writerows(extra)


def _append_replay_snapshot(folder, snapshot_id="snap2"):
    path = Path(folder) / "replay_inputs.jsonl"
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    first["snapshot_id"] = snapshot_id
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(first, sort_keys=True, default=str) + "\n")


def _write_feature_quality_bad_snapshot(folder, snapshot_id="snap1"):
    with (Path(folder) / "features_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "snapshot_id",
                "captured_at_local",
                "event_slug",
                "target_date",
                "high_so_far",
                "current_temp",
                "trusted_current_max",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "snapshot_id": snapshot_id,
            "captured_at_local": "2026-06-03T12:00:00-04:00",
            "event_slug": SLUG,
            "target_date": "2026-06-03",
            "high_so_far": "24.0",
            "current_temp": "24.0",
            "trusted_current_max": "45.0",
        })


def _write_raw_observation_payload(folder, snapshot_id="snap1"):
    path = Path(folder) / "observation_payloads_long.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["snapshot_id", "source", "status"])
        writer.writeheader()
        writer.writerow({"snapshot_id": snapshot_id, "source": "wu_current", "status": "fresh"})


class TestPromotionCorpus(unittest.TestCase):
    def test_manifest_pins_settlement_snapshot_ids_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            _write_label(folder)

            manifest = build_promotion_corpus(
                [folder],
                snapshots_root=tmp,
                as_of="2026-06-04",
            )

            self.assertEqual(manifest["summary"]["market_day_count"], 1)
            self.assertEqual(manifest["summary"]["snapshot_count"], 1)
            entry = manifest["entries"][0]
            self.assertEqual(entry["settlement_bucket"], 25)
            self.assertEqual(entry["quality_grade"], "complete")
            self.assertEqual(entry["snapshot_ids"], ["snap1"])
            self.assertIn("snap1", entry["replay_record_hashes"])
            self.assertIn("snap1", entry["tape_row_hashes"])

            path = Path(tmp) / "promotion_corpus.json"
            write_manifest(manifest, path)
            loaded = load_manifest(path)
            self.assertEqual(loaded["corpus_hash"], manifest["corpus_hash"])

    def test_manifest_excludes_feature_quality_quarantined_snapshots_before_hashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            _append_unpinned_snapshot(folder)
            _append_replay_snapshot(folder)
            _write_label(folder)
            _write_feature_quality_bad_snapshot(folder, snapshot_id="snap1")

            manifest = build_promotion_corpus(
                [folder],
                snapshots_root=tmp,
                as_of="2026-06-04",
            )

        self.assertEqual(manifest["summary"]["market_day_count"], 1)
        self.assertEqual(manifest["summary"]["feature_quality_excluded_snapshot_count"], 1)
        self.assertEqual(manifest["summary"]["feature_quality_excluded_band_row_count"], 3)
        entry = manifest["entries"][0]
        self.assertEqual(entry["snapshot_ids"], ["snap2"])
        self.assertEqual(entry["feature_quality_excluded_snapshot_ids"], ["snap1"])

    def test_manifest_recovers_feature_quality_snapshot_when_replay_input_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            _write_label(folder)
            _write_feature_quality_bad_snapshot(folder, snapshot_id="snap1")
            _write_raw_observation_payload(folder, snapshot_id="snap1")

            manifest = build_promotion_corpus(
                [folder],
                snapshots_root=tmp,
                as_of="2026-06-04",
            )

        self.assertEqual(manifest["summary"]["market_day_count"], 1)
        self.assertEqual(manifest["summary"]["feature_quality_excluded_snapshot_count"], 0)
        entry = manifest["entries"][0]
        self.assertEqual(entry["snapshot_ids"], ["snap1"])
        self.assertEqual(entry["feature_quality_excluded_snapshot_ids"], [])
        self.assertEqual(entry["feature_quality_quarantine"]["recovered_row_count"], 1)
        self.assertEqual(entry["feature_quality_quarantine"]["training_excluded_row_count"], 0)

    def test_replay_with_manifest_ignores_later_folder_growth(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            _write_label(folder)
            manifest = build_promotion_corpus([folder], snapshots_root=tmp, as_of="2026-06-04")
            _append_unpinned_snapshot(folder)

            results = run_replay_backtest(
                [str(folder)],
                daily_summary_path=str(Path(tmp) / "missing.csv"),
                overrides={},
                out_path=str(Path(tmp) / "report.md"),
                write=False,
                corpus_manifest=manifest,
            )

            self.assertEqual(results["snaps_scored"], 1)
            self.assertEqual(results["total_rows"], 3)
            self.assertEqual(results["days"][0]["source"], "promotion_corpus:test")

    def test_gauntlet_passes_single_clean_exact_identity_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / SLUG
            _build_corpus_day(folder)
            _write_label(folder)
            manifest = build_promotion_corpus([folder], snapshots_root=tmp, as_of="2026-06-04")
            corpus_path = write_manifest(manifest, Path(tmp) / "promotion_corpus.json")
            forecast_tracker = Path(tmp) / "forecast_vs_realized.json"
            forecast_tracker.write_text("[]", encoding="utf-8")

            args = SimpleNamespace(
                corpus=str(corpus_path),
                snapshots_root=str(tmp),
                baseline=None,
                no_baseline=True,
                forecast_tracker=str(forecast_tracker),
                out=str(Path(tmp) / "gauntlet.md"),
                replay_report=str(Path(tmp) / "replay.md"),
                tol=0.003,
                market_tol=1.0,
                min_days=1,
                min_trust=0,
                max_fidelity_l1=0.01,
                require_exact_identity=True,
                require_all_markets=False,
            )

            report = run_promotion_gauntlet(args)

            self.assertEqual(report["verdict"], "PASS")
            self.assertTrue(Path(args.out).exists())
            self.assertTrue(Path(args.replay_report).exists())

    def test_gauntlet_supports_partial_per_market_promotion(self):
        rows = [
            {"market_id": "nyc", "verdict": "PASS"},
            {"market_id": "atlanta", "verdict": "BLOCK"},
            {"market_id": "seattle", "verdict": "SHADOW"},
        ]
        self.assertEqual(_overall_verdict(True, True, True, rows), "PARTIAL_PASS")
        self.assertEqual(_overall_verdict(False, True, True, rows), "BLOCK")

    def test_gauntlet_decomposition_includes_source_freshness_for_blockers(self):
        results = {
            "all_rows": [
                {
                    "market_id": "miami",
                    "source_freshness_state": "failed:wu_history",
                    "replayed_p": 0.9,
                    "recorded_p": 0.1,
                    "market_yes": 0.2,
                    "outcome": 0,
                },
                {
                    "market_id": "miami",
                    "source_freshness_state": "all_fresh",
                    "replayed_p": 0.1,
                    "recorded_p": 0.1,
                    "market_yes": 0.2,
                    "outcome": 0,
                },
            ]
        }
        market_rows = [{"market_id": "miami", "verdict": "BLOCK"}]

        decomp = _decomposition(results, market_rows)

        blocking = decomp["blocking_markets"]["miami"]["by_source_freshness"]
        self.assertEqual(blocking[0]["group"], "failed:wu_history")
        self.assertIn("by_source_freshness", decomp["overall"])

    def test_gauntlet_falls_back_when_saved_baseline_lacks_current_corpus_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = Path(tmp) / "baseline.json"
            baseline_path.write_text(
                json.dumps({
                    "aggregate_replayed_brier": 0.010,
                    "corpus_hash": None,
                }),
                encoding="utf-8",
            )
            results = {
                "aggregate": {
                    "replayed_brier": 0.050,
                    "recorded_brier": 0.049,
                    "code_effect": 0.001,
                },
                "promotion_corpus": {"corpus_hash": "current-hash"},
            }

            passed, message = _baseline_gate_status(results, baseline_path, tol=0.003)

            self.assertTrue(passed, message)
            self.assertIn("falling back to recorded incumbent", message)
            self.assertIn("saved baseline corpus hash is missing", message)


if __name__ == "__main__":
    unittest.main()
