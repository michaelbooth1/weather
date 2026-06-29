import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.settlement_source_audit import (
    build_settlement_source_audit,
    settlement_label_gate_for_target_dates,
)


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestSettlementSourceAudit(unittest.TestCase):
    def test_audit_classifies_finalized_revised_and_provisional_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            daily_path = root / "daily_summary.csv"
            snapshot_path = root / "snapshots_long.csv"
            ledger_path = root / "settlements" / "atlanta" / "ledger.jsonl"
            daily_path.write_text("local_date,row_count,max_temp_bucket_c\n2026-06-19,24,84\n", encoding="utf-8")
            snapshot_path.write_text("snapshot_id,wu_history_high_c\ns1,84\n", encoding="utf-8")
            rows = [
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-19-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-19",
                    "settlement_bucket": "84",
                    "settlement_source": "daily_summary",
                    "quality_grade": "complete",
                    "reconciliation_status": "match",
                    "daily_summary_path": str(daily_path),
                    "snapshot_tape_path": str(snapshot_path),
                    "ledger_path": str(ledger_path),
                    "resolution_timezone": "America/New_York",
                    "finalized_at_utc": "2026-06-20T06:00:00+00:00",
                },
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-20-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-20",
                    "settlement_bucket": "86",
                    "settlement_source": "snapshot_high",
                    "quality_grade": "complete",
                    "reconciliation_status": "match",
                    "daily_summary_path": str(daily_path),
                    "snapshot_tape_path": str(snapshot_path),
                    "ledger_path": str(ledger_path),
                    "resolution_timezone": "America/New_York",
                    "note": "daily_summary=85 (rows=24) disagrees with snapshot high=86",
                    "finalized_at_utc": "2026-06-21T06:00:00+00:00",
                },
                {
                    "event_slug": "highest-temperature-in-atlanta-on-june-21-2026",
                    "market_id": "atlanta",
                    "target_date": "2026-06-21",
                    "settlement_bucket": "82",
                    "settlement_source": "daily_summary",
                    "quality_grade": "partial",
                    "reconciliation_status": "match",
                    "daily_summary_path": str(daily_path),
                    "snapshot_tape_path": str(snapshot_path),
                    "ledger_path": str(ledger_path),
                    "resolution_timezone": "America/New_York",
                    "finalized_at_utc": "2026-06-22T06:00:00+00:00",
                },
            ]
            ledger_path.parent.mkdir(parents=True)
            ledger_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            labels_csv = root / "labels.csv"
            _write_csv(labels_csv, rows)

            payload = build_settlement_source_audit(labels_csv=labels_csv, ledger_root=root / "settlements")

        by_date = {row["target_date"]: row for row in payload["rows"]}
        self.assertEqual(payload["schema_version"], "settlement_source_revision_audit_v0.1")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["summary"]["label_count"], 3)
        self.assertEqual(payload["summary"]["finalized_label_count"], 1)
        self.assertEqual(payload["summary"]["revised_label_count"], 1)
        self.assertEqual(payload["summary"]["provisional_label_count"], 1)
        self.assertTrue(by_date["2026-06-19"]["proof_grade_label"])
        self.assertEqual(by_date["2026-06-19"]["lineage_status"], "PASS")
        self.assertEqual(by_date["2026-06-20"]["status"], "SOURCE_REVISION")
        self.assertTrue(by_date["2026-06-20"]["alternate_label_changes_result"])
        self.assertIn("wu_final", by_date["2026-06-20"]["disagreement_sources"])

    def test_polymarket_reconciled_material_partial_label_is_proof_grade(self):
        # Settlement truth is Polymarket's resolution. A partial-coverage label
        # that reconciles with Polymarket (reconciliation_status == match) and is
        # materially complete (promotion_countable=True, item-319) is proof-grade
        # for promotion; a partial label with a decisive coverage gap
        # (promotion_countable=False) stays blocked.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            daily_path = root / "daily_summary.csv"
            snapshot_path = root / "snapshots_long.csv"
            ledger_path = root / "settlements" / "atlanta" / "ledger.jsonl"
            daily_path.write_text("local_date,row_count,max_temp_bucket_c\n2026-06-21,24,82\n", encoding="utf-8")
            snapshot_path.write_text("snapshot_id,wu_history_high_c\ns1,82\n", encoding="utf-8")
            common = {
                "market_id": "atlanta",
                "daily_summary_path": str(daily_path),
                "snapshot_tape_path": str(snapshot_path),
                "ledger_path": str(ledger_path),
                "resolution_timezone": "America/New_York",
                "reconciliation_status": "match",
                "quality_grade": "partial",
            }
            rows = [
                {
                    **common,
                    "event_slug": "highest-temperature-in-atlanta-on-june-21-2026",
                    "target_date": "2026-06-21",
                    "settlement_bucket": "82",
                    "settlement_source": "daily_summary",
                    "material_coverage_grade": "minor_gap_material",
                    "promotion_countable": "True",
                    "finalized_at_utc": "2026-06-22T06:00:00+00:00",
                },
                {
                    **common,
                    "event_slug": "highest-temperature-in-atlanta-on-june-22-2026",
                    "target_date": "2026-06-22",
                    "settlement_bucket": "82",
                    "settlement_source": "daily_summary",
                    "material_coverage_grade": "decisive_gap",
                    "promotion_countable": "False",
                    "finalized_at_utc": "2026-06-23T06:00:00+00:00",
                },
            ]
            ledger_path.parent.mkdir(parents=True)
            ledger_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            labels_csv = root / "labels.csv"
            _write_csv(labels_csv, rows)

            payload = build_settlement_source_audit(labels_csv=labels_csv, ledger_root=root / "settlements")

        by_date = {row["target_date"]: row for row in payload["rows"]}
        # Countable partial day: proof-grade via promotion_countable, status still
        # reported PROVISIONAL for transparency, not a promotion blocker.
        self.assertTrue(by_date["2026-06-21"]["proof_grade_label"])
        self.assertEqual(by_date["2026-06-21"]["proof_grade_basis"], "promotion_countable")
        self.assertFalse(by_date["2026-06-21"]["promotion_blocker"])
        self.assertEqual(by_date["2026-06-21"]["status"], "PROVISIONAL")
        # Decisive-gap partial day: not materially countable -> stays blocked.
        self.assertFalse(by_date["2026-06-22"]["proof_grade_label"])
        self.assertTrue(by_date["2026-06-22"]["promotion_blocker"])
        # The promotion gate passes for the countable date, blocks the other.
        self.assertEqual(
            settlement_label_gate_for_target_dates(payload, ["2026-06-21"])["status"], "PASS"
        )
        self.assertEqual(
            settlement_label_gate_for_target_dates(payload, ["2026-06-22"])["status"], "BLOCK"
        )

    def test_target_date_gate_blocks_uncertain_or_missing_audit_rows(self):
        payload = {
            "rows": [
                {
                    "target_date": "2026-06-19",
                    "market_id": "atlanta",
                    "status": "FINALIZED",
                    "promotion_blocker": False,
                },
                {
                    "target_date": "2026-06-20",
                    "market_id": "atlanta",
                    "status": "PROVISIONAL",
                    "promotion_blocker": True,
                },
            ]
        }

        self.assertEqual(settlement_label_gate_for_target_dates(payload, ["2026-06-19"])["status"], "PASS")
        blocked = settlement_label_gate_for_target_dates(payload, ["2026-06-20", "2026-06-21"])
        self.assertEqual(blocked["status"], "BLOCK")
        self.assertIn("2026-06-20", blocked["blocked_target_dates"])
        self.assertIn("2026-06-21", blocked["blocked_target_dates"])


if __name__ == "__main__":
    unittest.main()
