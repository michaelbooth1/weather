import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.predawn_weak_slot_repair import (
    SCHEMA_VERSION,
    build_payload,
    build_repair_result,
    write_candidate_rows,
    write_candidate_gate_outputs,
    write_outputs,
)


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
]


def write_rows(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def row(date, snapshot, band, probability, current, market, outcome, captured="2026-06-07T03:00:00-04:00"):
    return {
        "variant_id": "candidate_v1",
        "market_id": "toronto",
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": band,
        "probability": str(probability),
        "current_probability": str(current),
        "market_yes": str(market),
        "outcome": str(outcome),
        "captured_at_local": captured,
    }


class PredawnWeakSlotRepairTests(unittest.TestCase):
    def test_build_payload_scores_scoped_predawn_candidate_and_guardrails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows_path = root / "candidate_rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.75, 0.45, 0.70, 1),
                    row(date, f"{date}-weak", "eq:71", 0.25, 0.55, 0.30, 0),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:70",
                        0.01,
                        0.60,
                        0.55,
                        1,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:71",
                        0.99,
                        0.40,
                        0.45,
                        0,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                ])
            write_rows(rows_path, rows)

            payload = build_payload(rows_path, ten_minute, market_tol=0.10)
            json_out, report_out = write_outputs(
                payload,
                json_out=root / "predawn.json",
                report_out=root / "predawn.md",
            )
            report = Path(report_out).read_text(encoding="utf-8")
            json_exists = Path(json_out).exists()

        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["status"], "PASS")
        self.assertLessEqual(payload["weak_slot_summary"]["delta_vs_current"], -0.003)
        self.assertGreater(
            payload["weak_slot_summary"]["winner_variant_probability"],
            payload["weak_slot_summary"]["winner_current_probability"],
        )
        self.assertLess(payload["weak_slot_summary"]["effective_band_delta_vs_current"], 0)
        self.assertTrue(all(row["status"] == "PASS" for row in payload["guardrails"]))
        self.assertTrue(json_exists)
        self.assertIn("Predawn Weak-Slot Repair Validation", report)

    def test_write_candidate_rows_exports_distinct_repair_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            rows_path = root / "candidate_rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.75, 0.45, 0.70, 1),
                    row(date, f"{date}-weak", "eq:71", 0.25, 0.55, 0.30, 0),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:70",
                        0.01,
                        0.60,
                        0.55,
                        1,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                    row(
                        date,
                        f"{date}-ramp",
                        "eq:71",
                        0.99,
                        0.40,
                        0.45,
                        0,
                        captured="2026-06-07T10:00:00-04:00",
                    ),
                ])
            write_rows(rows_path, rows)

            payload, repaired_rows = build_repair_result(
                rows_path,
                ten_minute,
                market_tol=0.10,
                blend=0.25,
                extrapolation=2.0,
                partition_power=3.0,
                output_variant_id="repair_v1",
            )
            csv_out = write_candidate_rows(repaired_rows, root / "repair_rows.csv")
            with Path(csv_out).open("r", encoding="utf-8", newline="") as handle:
                exported = list(csv.DictReader(handle))

        self.assertEqual(payload["candidate_policy"]["variant_id"], "repair_v1")
        self.assertEqual({row["variant_id"] for row in exported}, {"repair_v1"})
        ramp_winner = next(row for row in exported if row["snapshot_id"].endswith("-ramp") and row["band_key"] == "eq:70")
        self.assertEqual(ramp_winner["probability"], "0.6")

    def test_candidate_gate_outputs_share_variant_and_corpus_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ten_minute = root / "ten_minute.json"
            ten_minute.write_text(json.dumps({"weak_slots": {"slot_minutes": [180]}}), encoding="utf-8")
            source_candidate = root / "source_candidate.json"
            source_candidate.write_text(
                json.dumps({
                    "corpus": {"corpus_hash": "source-corpus"},
                    "candidate_shadow_variants": {
                        "variant_id": "source_candidate",
                        "variant_family": "pooled_f_candidate",
                        "registry_contract": True,
                    },
                }),
                encoding="utf-8",
            )
            rows_path = root / "candidate_rows.csv"
            rows = []
            for date in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]:
                rows.extend([
                    row(date, f"{date}-weak", "eq:70", 0.75, 0.45, 0.70, 1),
                    row(date, f"{date}-weak", "eq:71", 0.25, 0.55, 0.30, 0),
                ])
            write_rows(rows_path, rows)
            _payload, repaired_rows = build_repair_result(
                rows_path,
                ten_minute,
                market_tol=0.10,
                output_variant_id="repair_v1",
            )
            repaired_path = write_candidate_rows(repaired_rows, root / "repair_rows.csv")

            outputs = write_candidate_gate_outputs(
                candidate_rows=repaired_path,
                weak_slots={180},
                source_candidate_json=source_candidate,
                replay_summary_json_out=root / "replay.json",
                replay_summary_report_out=root / "replay.md",
                hourly_json_out=root / "hourly.json",
                hourly_report_out=root / "hourly.md",
                ten_minute_json_out=root / "ten.json",
                ten_minute_report_out=root / "ten.md",
                min_hourly_market_days=1,
                candidate_min_weak_market_days=1,
                weak_market_regression_tolerance=0.10,
            )
            replay_json_exists = Path(outputs["paths"]["replay_summary_json"]).exists()
            hourly_json_exists = Path(outputs["paths"]["hourly_json"]).exists()
            ten_json_exists = Path(outputs["paths"]["ten_minute_json"]).exists()

        self.assertEqual(outputs["status"], "PASS")
        self.assertTrue(outputs["corpus_hash_match"])
        self.assertTrue(outputs["row_export_corpus_hash_match"])
        self.assertEqual(outputs["corpus_hashes"]["replay_summary"], outputs["corpus_hashes"]["hourly"])
        self.assertEqual(outputs["corpus_hashes"]["hourly"], outputs["corpus_hashes"]["ten_minute"])
        self.assertEqual(
            outputs["row_export_corpus_hashes"]["replay_summary"],
            outputs["row_export_corpus_hashes"]["hourly"],
        )
        self.assertEqual(
            outputs["row_export_corpus_hashes"]["hourly"],
            outputs["row_export_corpus_hashes"]["ten_minute"],
        )
        self.assertEqual(outputs["variant_ids"]["replay_summary"], ["repair_v1"])
        self.assertEqual(outputs["variant_ids"]["hourly"], ["repair_v1"])
        self.assertEqual(outputs["variant_ids"]["ten_minute"], ["repair_v1"])
        self.assertEqual(outputs["candidate_hourly_performance"]["candidate_hourly_gate"]["status"], "PASS")
        self.assertEqual(outputs["candidate_ten_minute_performance"]["candidate_ten_minute_gate"]["status"], "PASS")
        self.assertTrue(replay_json_exists)
        self.assertTrue(hourly_json_exists)
        self.assertTrue(ten_json_exists)


if __name__ == "__main__":
    unittest.main()
