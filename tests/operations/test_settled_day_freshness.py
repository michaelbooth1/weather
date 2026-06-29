import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.backtesting.settlement_ledger import (
    read_jsonl,
    upsert_ledger_record,
    write_labels_csv,
)
from weather.market.market_config import event_slug_for_date
from weather.operations.settled_day_freshness import (
    build_freshness_payload,
    read_labels_csv,
    repair_missing_settlements,
)


def _write_snapshot_tape(root, target_date, *, market_id="nyc", high=77):
    slug = event_slug_for_date(target_date, market_id)
    folder = Path(root) / slug
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_slug",
                "snapshot_id",
                "captured_at_local",
                "range_label",
                "bin_kind",
                "bin_value_c",
                "model_probability",
                "market_yes",
                "wu_history_high_c",
            ],
        )
        writer.writeheader()
        for value in (high - 1, high):
            writer.writerow({
                "event_slug": slug,
                "snapshot_id": "s1",
                "captured_at_local": f"{target_date}T12:00:00-04:00",
                "range_label": f"{value} F",
                "bin_kind": "eq",
                "bin_value_c": value,
                "model_probability": "0.50",
                "market_yes": "0.50",
                "wu_history_high_c": high,
            })
    return folder


def _write_replay_artifacts(folder):
    (folder / "replay_inputs.jsonl").write_text('{"snapshot_id": "s1"}\n', encoding="utf-8")
    (folder / "source_status_long.csv").write_text("snapshot_id,source,ok,status\ns1,wu_history,True,fresh\n", encoding="utf-8")
    (folder / "replay_input_status_long.csv").write_text(
        "snapshot_id,replay_input_status,replay_input_source\ns1,captured,replay_inputs.jsonl\n",
        encoding="utf-8",
    )


def _label(slug, target_date, *, bucket=77, source="daily_summary", status="match"):
    return {
        "schema_version": "settlement_ledger_v0.1",
        "event_slug": slug,
        "market_id": "nyc",
        "city": "NYC",
        "target_date": str(target_date),
        "settlement_high": bucket,
        "settlement_bucket": bucket,
        "settlement_unit": "F",
        "winning_band": f"{bucket} F",
        "winning_band_kind": "eq",
        "winning_band_value": bucket,
        "winning_band_value_hi": bucket,
        "settlement_source": source,
        "quality_grade": "complete",
        "quality_reason": "test label",
        "snapshot_count": 1,
        "band_count": 2,
        "row_count": 2,
        "coverage_clean": False,
        "capture_ratio": 0.01,
        "max_gap_minutes": None,
        "coverage_reason": "test",
        "resolution_source_type": "wunderground_history",
        "resolution_wu_history_id": "KLGA:9:US",
        "resolution_station": "KLGA",
        "resolution_timezone": "America/New_York",
        "daily_max_window": "00:00:00-23:59:59 local",
        "rounding": "round_half_up whole degree",
        "daily_summary_path": "",
        "snapshot_tape_path": "",
        "ledger_path": "",
        "polymarket_url": "",
        "gamma_event_url": "",
        "reconciliation_status": status,
        "polymarket_winning_band": f"{bucket} F",
        "note": "test",
        "finalized_at_utc": "2026-06-18T00:00:00+00:00",
    }


class TestSettledDayFreshness(unittest.TestCase):
    def test_report_identifies_missing_canonical_artifacts_for_existing_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_date = "2026-06-17"
            _write_snapshot_tape(root / "snapshots", target_date)

            payload = build_freshness_payload(
                snapshots_root=root / "snapshots",
                labels_csv=root / "backtest" / "market_day_labels.csv",
                ledger_root=root / "settlements",
                target_date=target_date,
                market_ids=["nyc"],
            )

        self.assertEqual(payload["status"], "FAIL")
        row = payload["markets"][0]
        self.assertTrue(row["needs_finalization"])
        self.assertTrue(row["needs_replay_status_repair"])
        self.assertNotIn(row["daily_summary"]["status"], {"current", "sparse"})
        self.assertEqual(
            row["missing_requirements"],
            [
                "labels_csv",
                "ledger",
                "settlement_json",
                "replay_input_status_long.csv",
                "replay_inputs.jsonl",
                "source_status_long.csv",
            ],
        )

    def test_repair_finalizes_missing_tape_and_merges_labels_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_date = "2026-06-17"
            old_date = "2026-06-16"
            folder = _write_snapshot_tape(root / "snapshots", target_date)
            _write_replay_artifacts(folder)
            labels_csv = root / "backtest" / "market_day_labels.csv"
            old_slug = event_slug_for_date(old_date, "nyc")
            write_labels_csv(labels_csv, [_label(old_slug, old_date, bucket=76)])

            payload = repair_missing_settlements(
                snapshots_root=root / "snapshots",
                labels_csv=labels_csv,
                ledger_root=root / "settlements",
                target_date=target_date,
                market_ids=["nyc"],
                reconcile_polymarket=False,
            )
            labels = read_labels_csv(labels_csv)
            ledger_rows = read_jsonl(root / "settlements" / "nyc" / "ledger.jsonl")
            settlement = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "WARN")
        self.assertEqual({row["event_slug"] for row in labels}, {old_slug, event_slug_for_date(target_date, "nyc")})
        self.assertEqual(ledger_rows[0]["event_slug"], event_slug_for_date(target_date, "nyc"))
        self.assertEqual(settlement["settlement_source"], "snapshot_high")
        self.assertEqual(payload["repair"]["finalized_event_slugs"], [event_slug_for_date(target_date, "nyc")])
        self.assertTrue(payload["markets"][0]["source_lag_warning"])

    def test_repair_restores_from_existing_ledger_without_recomputing_reconciled_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_date = "2026-06-17"
            folder = _write_snapshot_tape(root / "snapshots", target_date, high=80)
            _write_replay_artifacts(folder)
            slug = event_slug_for_date(target_date, "nyc")
            existing = _label(slug, target_date, bucket=77, source="daily_summary", status="match")
            upsert_ledger_record(existing, root / "settlements")

            payload = repair_missing_settlements(
                snapshots_root=root / "snapshots",
                labels_csv=root / "backtest" / "market_day_labels.csv",
                ledger_root=root / "settlements",
                target_date=target_date,
                market_ids=["nyc"],
                reconcile_polymarket=False,
            )
            labels = read_labels_csv(root / "backtest" / "market_day_labels.csv")
            settlement = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["repair"]["restored_from_existing_event_slugs"], [slug])
        self.assertEqual(labels[0]["settlement_bucket"], "77")
        self.assertEqual(settlement["settlement_bucket"], 77)
        self.assertEqual(settlement["reconciliation_status"], "match")

    def test_report_surfaces_polymarket_only_repair_candidate_without_promotion_countability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_date = "2026-06-17"
            folder = _write_snapshot_tape(root / "snapshots", target_date, high=80)
            _write_replay_artifacts(folder)
            slug = event_slug_for_date(target_date, "nyc")
            label = _label(slug, target_date, bucket=80, source="none", status="mismatch")
            label.update({
                "settlement_high": None,
                "settlement_bucket": None,
                "winning_band": None,
                "quality_grade": "missing_settlement",
                "material_coverage_grade": "missing_settlement",
                "promotion_countable": False,
                "promotion_countable_reason": "no settlement bucket available",
                "polymarket_winning_band": "88-89 F",
                "polymarket_reconciliation": {
                    "status": "mismatch",
                    "event_closed": True,
                    "winning_markets": [
                        {
                            "label": "88-89 F",
                            "kind": "eq",
                            "value": 88,
                            "value_hi": 89,
                            "yes_price": 1.0,
                            "no_price": 0.0,
                            "condition_id": "0xabc",
                        }
                    ],
                },
            })
            upsert_ledger_record(label, root / "settlements")
            write_labels_csv(root / "backtest" / "market_day_labels.csv", [label])
            (folder / "settlement.json").write_text(json.dumps(label), encoding="utf-8")

            payload = build_freshness_payload(
                snapshots_root=root / "snapshots",
                labels_csv=root / "backtest" / "market_day_labels.csv",
                ledger_root=root / "settlements",
                target_date=target_date,
                market_ids=["nyc"],
            )

        row = payload["markets"][0]
        self.assertEqual(row["raw_reconciliation_status"], "mismatch")
        self.assertEqual(row["reconciliation_status"], "local_missing")
        self.assertEqual(row["polymarket_winning_band"], "88-89 F")
        self.assertTrue(row["local_settlement_missing_with_polymarket_winner"])
        self.assertEqual(row["polymarket_repair_candidate"]["status"], "available")
        self.assertFalse(row["polymarket_repair_candidate"]["promotion_countable"])
        self.assertFalse(row["promotion_countable"])
        self.assertEqual(payload["summary"]["local_missing_polymarket_winner_count"], 1)
        self.assertEqual(payload["summary"]["reconciliation_counts"], {"local_missing": 1})


if __name__ == "__main__":
    unittest.main()
