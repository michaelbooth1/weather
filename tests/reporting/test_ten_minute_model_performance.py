import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.ten_minute_model_performance import (
    build_candidate_item147,
    candidate_ten_minute_gate,
    rank_slots,
    summarize_by_regime,
    summarize_by_slot,
    summarize_rows,
    ten_minute_checkpoint_rows,
    ten_minute_performance_gate,
    weak_slot_set,
    write_outputs,
)


def scored_row(slot_minute, *, snapshot_id=None, probability=0.20, market_yes=0.80, outcome=1, band="winner"):
    hour = slot_minute // 60
    minute = (slot_minute % 60) + 1
    return {
        "market_id": "toronto",
        "target_date": "2026-06-07",
        "snapshot_id": snapshot_id or f"s{slot_minute}",
        "captured_at_local": f"2026-06-07T{hour:02d}:{minute:02d}:00-04:00",
        "capture_minute": slot_minute + 1,
        "band": band,
        "model_probability": probability,
        "market_yes": market_yes,
        "outcome": outcome,
    }


def write_candidate_rows(path, rows):
    fieldnames = [
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
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestTenMinuteModelPerformance(unittest.TestCase):
    def test_checkpoint_rows_keep_first_per_market_day_band_slot(self):
        rows = [
            scored_row(180, snapshot_id="late", probability=0.10),
            {
                **scored_row(180, snapshot_id="early", probability=0.90),
                "captured_at_local": "2026-06-07T03:00:30-04:00",
                "capture_minute": 180,
            },
            scored_row(190, snapshot_id="next_slot", probability=0.40),
        ]

        checkpoints = ten_minute_checkpoint_rows(rows)

        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0]["snapshot_id"], "early")
        self.assertEqual(checkpoints[0]["time_slot_label"], "03:00")
        self.assertEqual(checkpoints[1]["time_slot_label"], "03:10")

    def test_write_outputs_preserves_all_144_local_slots_in_csv(self):
        rows = [
            scored_row(slot, probability=0.20 if slot < 180 else 0.70, market_yes=0.80)
            for slot in range(0, 24 * 60, 10)
        ]
        checkpoints = ten_minute_checkpoint_rows(rows)
        by_slot = summarize_by_slot(checkpoints)
        weak_slots = weak_slot_set(by_slot, min_rows=1)
        weak_payload = {
            "slot_minutes": sorted(weak_slots),
            "slot_labels": [f"{slot // 60:02d}:{slot % 60:02d}" for slot in sorted(weak_slots)],
            "summary": summarize_rows([row for row in checkpoints if row.get("time_slot_minute") in weak_slots]) or {},
        }
        gate = ten_minute_performance_gate(weak_payload, {"scored_market_days": 1}, min_weak_market_days=1)
        payload = {
            "schema_version": "ten_minute_model_performance_v0.1",
            "generated_at_utc": "2026-06-20T00:00:00+00:00",
            "corpus": {"scored_market_days": 1, "ten_minute_checkpoint_rows": len(checkpoints)},
            "overall": summarize_rows(checkpoints) or {},
            "by_slot": by_slot,
            "by_regime": summarize_by_regime(checkpoints),
            "rankings": rank_slots(by_slot, min_rows=1, top_slots=3),
            "weak_slots": weak_payload,
            "ten_minute_performance_gate": gate,
            "candidate_ten_minute_gate": {"status": "MISSING"},
            "candidate_item147": {},
            "replay_probes": {},
        }

        with tempfile.TemporaryDirectory() as tmp:
            _json_out, _report_out, csv_out, _candidate_csv = write_outputs(
                payload,
                json_out=Path(tmp) / "ten_minute.json",
                report_out=Path(tmp) / "ten_minute.md",
                slot_csv_out=Path(tmp) / "ten_minute.csv",
                candidate_csv_out=Path(tmp) / "candidate.csv",
            )
            with Path(csv_out).open("r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))

        self.assertEqual(len(checkpoints), 144)
        self.assertEqual(len(by_slot), 144)
        self.assertEqual(len(csv_rows), 144)
        self.assertEqual(csv_rows[0]["time_slot_label"], "00:00")
        self.assertEqual(csv_rows[-1]["time_slot_label"], "23:50")

    def test_candidate_ten_minute_gate_scores_weak_slot_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate_rows.csv"
            write_candidate_rows(
                path,
                [
                    {
                        "variant_id": "candidate_v1",
                        "market_id": "toronto",
                        "target_date": "2026-06-07",
                        "snapshot_id": "s0300",
                        "band_key": "eq:80",
                        "probability": "0.90",
                        "current_probability": "0.60",
                        "market_yes": "0.70",
                        "outcome": "1",
                        "captured_at_local": "2026-06-07T03:00:00-04:00",
                    }
                ],
            )

            candidate = build_candidate_item147(path, weak_slots={180})
            gate = candidate_ten_minute_gate(candidate, min_weak_market_days=1)

        self.assertEqual(candidate["weak_slot_overlap"]["candidate_slot_overlap"], 1)
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["variant_ids"], ["candidate_v1"])


if __name__ == "__main__":
    unittest.main()
