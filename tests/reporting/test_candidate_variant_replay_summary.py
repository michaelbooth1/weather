import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.candidate_variant_replay_summary import (
    SCHEMA_VERSION,
    build_variant_replay_summary,
    write_outputs,
)
from weather.reporting.promotion_refresh_decisions import promotion_readiness
from weather.reporting.promotion_refresh_readers import _candidate_summary, load_precomputed_candidate_report


FIELDNAMES = [
    "variant_id",
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
]


def _row(market, date, band, probability, current, market_yes, outcome, hour=3):
    return {
        "variant_id": "candidate_v1",
        "market_id": market,
        "target_date": date,
        "snapshot_id": f"{market}-{date}-{hour:02d}",
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market_yes),
        "outcome": str(outcome),
        "captured_at_local": f"{date}T{hour:02d}:00:00-04:00",
        "bin_type": "eq",
    }


def _write_rows(path, rows):
    fieldnames = list(FIELDNAMES)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_source(path):
    Path(path).write_text(
        json.dumps(
            {
                "artifact": {"artifact_path": "artifacts/models/demo.pkl"},
                "corpus": {"corpus_hash": "source-corpus", "market_day_count": 2},
                "candidate_shadow_variants": {
                    "variant_id": "source_candidate",
                    "variant_family": "pooled_f_candidate",
                    "path": "data/backtest/source_rows.csv",
                    "registry_contract": True,
                },
            }
        ),
        encoding="utf-8",
    )


def _active_contract(rows_path, *, variant_id="candidate_v1"):
    return {
        "variant_id": variant_id,
        "variant_family": "candidate_variant_row_export",
        "lifecycle": "active",
        "active_for_headline": True,
        "prediction_function": "weather.calibration.pooled_candidate_replay:run_pooled_candidate_replay",
        "prediction_mode": "band_binary",
        "export_family": "candidate_variant_row_export",
        "default_export_path": str(rows_path),
        "live_runtime": "pooled_candidate_replay",
    }


def _registry_variant(rows_path, *, variant_id="candidate_v1", lifecycle="active", active_for_headline=True):
    return {
        **_active_contract(rows_path, variant_id=variant_id),
        "lifecycle": lifecycle,
        "active_for_headline": active_for_headline,
    }


def _active_registry(rows_path, *, variant_id="candidate_v1", lifecycle="active"):
    return {
        "schema_version": "model_variant_registry_v0.1",
        "exists": True,
        "path": "inline",
        "variants": [_registry_variant(rows_path, variant_id=variant_id, lifecycle=lifecycle)],
    }


def _passing_rows():
    rows = []
    for market in ["austin", "toronto"]:
        for date in ["2026-06-01", "2026-06-02"]:
            rows.extend(
                [
                    _row(market, date, "eq:70", 0.80, 0.50, 0.70, 1),
                    _row(market, date, "eq:71", 0.20, 0.50, 0.30, 0),
                ]
            )
    return rows


class CandidateVariantReplaySummaryTests(unittest.TestCase):
    def test_row_export_surrogate_scores_but_blocks_cutover(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            payload = build_variant_replay_summary(rows_path, source_path)
            json_path, report_path = write_outputs(payload, root / "summary.json", root / "summary.md")
            report = Path(report_path).read_text(encoding="utf-8")
            json_exists = Path(json_path).exists()

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["candidate_shadow_variants"]["variant_id"], "candidate_v1")
        self.assertEqual(payload["candidate_shadow_variants"]["derived_from"]["variant_id"], "source_candidate")
        self.assertEqual(payload["corpus"]["corpus_hash"], payload["corpus"]["row_export_corpus_hash"])
        self.assertEqual(payload["corpus"]["source_candidate_corpus_hash"], "source-corpus")
        self.assertTrue(payload["corpus"]["row_export_corpus_hash"])
        self.assertTrue(payload["row_export_metric_passed"])
        self.assertFalse(payload["blocked_validation"]["passed"])
        self.assertIn("row-export summary", "; ".join(payload["blocked_validation"]["reasons"]))
        self.assertEqual(payload["verdict"], "BLOCK")
        self.assertEqual(payload["candidate_market_verdict"], "PASS")
        self.assertTrue(json_exists)
        self.assertIn("Candidate Variant Replay Summary", report)

    def test_row_export_surrogate_loads_when_source_corpus_matches_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            summary_path = root / "summary.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            payload = build_variant_replay_summary(rows_path, source_path)
            write_outputs(payload, summary_path, root / "summary.md")
            loaded = load_precomputed_candidate_report(
                summary_path,
                {"corpus_hash": "source-corpus"},
            )

        self.assertEqual(loaded["corpus"]["corpus_hash"], payload["corpus"]["row_export_corpus_hash"])
        self.assertEqual(loaded["corpus"]["source_candidate_corpus_hash"], "source-corpus")

    def test_active_replay_contract_summary_can_feed_promotion_refresh_mitigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            payload = build_variant_replay_summary(
                rows_path,
                source_path,
                validation_evidence="active_replay_contract",
                active_registry_contract=_active_contract(rows_path),
                variant_registry=_active_registry(rows_path),
            )
            candidate = _candidate_summary(payload, root / "summary.json", root / "summary.md")

        readiness = promotion_readiness(
            candidate,
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            ten_minute_performance={
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {"detail": "current weak slot trails market"},
                }
            },
            candidate_ten_minute_performance={
                "variant_ids": ["candidate_v1"],
                "corpus": {"corpus_hash": payload["corpus"]["corpus_hash"]},
                "candidate_ten_minute_gate": {
                    "status": "PASS",
                    "blocker_count": 0,
                    "weak_slot_overlap": {"delta_vs_current": -0.01, "delta_vs_market": -0.01},
                },
            },
        )

        self.assertEqual(payload["blocked_validation"]["verdict"], "PASS")
        self.assertEqual(payload["verdict"], "PASS")
        self.assertTrue(payload["candidate_shadow_variants"]["registry_contract"])
        self.assertEqual(
            payload["candidate_shadow_variants"]["active_registry_contract"]["variant_id"],
            "candidate_v1",
        )
        self.assertEqual(readiness["status"], "READY")
        self.assertTrue(readiness["ten_minute_performance_mitigation"]["applied"])
        self.assertTrue(readiness["ten_minute_performance_mitigation"]["candidate_ten_minute_matches"])
        self.assertNotIn("ten_minute_performance_gate", {row["category"] for row in readiness["blockers"]})

    def test_active_replay_contract_requires_contract_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "active replay contract evidence requires"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                )

    def test_active_replay_contract_rejects_mismatched_export_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "default_export_path does not match"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=_active_contract(root / "other_rows.csv"),
                    variant_registry=_active_registry(rows_path),
                )

    def test_active_replay_contract_rejects_mismatched_variant_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "variant_id does not match"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=_active_contract(rows_path, variant_id="other_candidate"),
                    variant_registry=_active_registry(rows_path, variant_id="other_candidate"),
                )

    def test_active_replay_contract_rejects_non_active_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            _write_rows(rows_path, _passing_rows())
            _write_source(source_path)
            contract = _active_contract(rows_path)

            with self.assertRaisesRegex(ValueError, "lifecycle=active"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=contract,
                    variant_registry=_active_registry(rows_path, lifecycle="shadow"),
                )

    def test_active_replay_contract_rejects_same_corpus_repair_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            rows = _passing_rows()
            rows[0]["item224_repair_missingness_hgb"] = "same_corpus_hgb_missingness_v0_2"
            _write_rows(rows_path, rows)
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "same-corpus diagnostic markers"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=_active_contract(rows_path),
                    variant_registry=_active_registry(rows_path),
                )

    def test_active_replay_contract_rejects_non_countable_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            rows = _passing_rows()
            rows[0]["counts_toward_weather_model_promotion"] = "false"
            _write_rows(rows_path, rows)
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "counts_toward_weather_model_promotion=false"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=_active_contract(rows_path),
                    variant_registry=_active_registry(rows_path),
                )

    def test_active_replay_contract_rejects_unregistered_source_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            rows = _passing_rows()
            rows[0]["route_source_variant_id"] = "diagnostic_repair_v1"
            _write_rows(rows_path, rows)
            _write_source(source_path)

            with self.assertRaisesRegex(ValueError, "unregistered source variant"):
                build_variant_replay_summary(
                    rows_path,
                    source_path,
                    validation_evidence="active_replay_contract",
                    active_registry_contract=_active_contract(rows_path),
                    variant_registry=_active_registry(rows_path),
                )

    def test_active_replay_contract_allows_registered_active_source_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            rows = _passing_rows()
            for row in rows:
                row["route_source_variant_id"] = "source_active_v1"
            _write_rows(rows_path, rows)
            _write_source(source_path)
            registry = _active_registry(rows_path)
            registry["variants"].append(_registry_variant(root / "source_rows.csv", variant_id="source_active_v1"))

            payload = build_variant_replay_summary(
                rows_path,
                source_path,
                validation_evidence="active_replay_contract",
                active_registry_contract=_active_contract(rows_path),
                variant_registry=registry,
            )

            checks = payload["candidate_shadow_variants"]["active_registry_contract"]["validation_checks"]
            self.assertTrue(checks["source_variant_lineage_countable"])

    def test_market_regression_blocks_even_with_active_contract_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "variant_rows.csv"
            source_path = root / "source.json"
            bad_rows = []
            for date in ["2026-06-01", "2026-06-02"]:
                bad_rows.extend(
                    [
                        _row("toronto", date, "eq:70", 0.10, 0.50, 0.80, 1),
                        _row("toronto", date, "eq:71", 0.90, 0.50, 0.20, 0),
                    ]
                )
            _write_rows(rows_path, bad_rows)
            _write_source(source_path)

            payload = build_variant_replay_summary(
                rows_path,
                source_path,
                validation_evidence="active_replay_contract",
                active_registry_contract=_active_contract(rows_path),
                variant_registry=_active_registry(rows_path),
            )

        self.assertFalse(payload["blocked_validation"]["passed"])
        self.assertEqual(payload["blocked_validation"]["verdict"], "BLOCK")
        self.assertEqual(payload["market_rows"][0]["verdict"], "BLOCK")
        self.assertIn("market tolerance", "; ".join(payload["blocked_validation"]["reasons"]))


if __name__ == "__main__":
    unittest.main()
