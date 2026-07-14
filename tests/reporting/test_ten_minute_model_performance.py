import csv
import tempfile
import tracemalloc
import unittest
from pathlib import Path

from weather.reporting.hourly.candidate_hourly_performance import candidate_rows_corpus_hash, read_variant_rows
from weather.reporting.hourly.ten_minute_model_performance import (
    TenMinuteMarketDayAggregation,
    build_replay_probes,
    build_candidate_item147,
    candidate_ten_minute_gate,
    rank_slots,
    read_candidate_checkpoint_rows,
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


def scored_market_day(day_index, *, slots=(180, 190)):
    rows = []
    target_date = f"synthetic-day-{day_index:04d}"
    for slot in slots:
        hour = slot // 60
        minute = slot % 60
        snapshot_id = f"day-{day_index:04d}-slot-{slot:04d}"
        for band, outcome, bin_value, probability, market_yes in (
            ("loser", 0, 79.0, 0.25 + (slot % 20) / 100.0, 0.35),
            ("winner", 1, 80.0, 0.75 - (slot % 20) / 100.0, 0.65),
        ):
            rows.append(
                {
                    "market_id": "toronto",
                    "target_date": target_date,
                    "snapshot_id": snapshot_id,
                    "captured_at_local": (
                        f"2026-06-07T{hour:02d}:{minute:02d}:00-04:00"
                    ),
                    "capture_minute": slot,
                    "cutoff_hour": hour,
                    "band": band,
                    "bin_type": "eq",
                    "bin_value_c": bin_value,
                    "bin_value_hi": bin_value,
                    "feature_forecast_high": 80.0,
                    "model_probability": probability,
                    "market_yes": market_yes,
                    "model_edge": probability - market_yes,
                    "outcome": outcome,
                }
            )
    return rows


def assert_nested_almost_equal(testcase, actual, expected):
    if isinstance(expected, dict):
        testcase.assertEqual(set(actual), set(expected))
        for key in expected:
            assert_nested_almost_equal(testcase, actual[key], expected[key])
        return
    if isinstance(expected, list):
        testcase.assertEqual(len(actual), len(expected))
        for actual_item, expected_item in zip(actual, expected):
            assert_nested_almost_equal(testcase, actual_item, expected_item)
        return
    if isinstance(expected, float):
        testcase.assertAlmostEqual(actual, expected, places=12)
        return
    testcase.assertEqual(actual, expected)


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

    def test_market_day_aggregation_matches_materialized_checkpoint_outputs(self):
        market_days = [scored_market_day(index) for index in range(3)]
        materialized = ten_minute_checkpoint_rows(
            [row for day_rows in market_days for row in day_rows]
        )
        expected_by_slot = summarize_by_slot(materialized)
        expected_by_regime = summarize_by_regime(materialized)
        expected_overall = summarize_rows(materialized) or {}
        weak_slots = {180}
        expected_weak = summarize_rows(
            [row for row in materialized if row.get("time_slot_minute") in weak_slots]
        ) or {}
        expected_probes = build_replay_probes(
            materialized,
            expected_by_slot,
            weak_slots,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with TenMinuteMarketDayAggregation(tmp) as aggregation:
                for day_rows in market_days:
                    aggregation.add_market_day_rows(day_rows)
                actual_by_slot = aggregation.by_slot()
                actual_by_regime = aggregation.by_regime()
                actual_overall = aggregation.summary_for_slots({180, 190}) or {}
                actual_weak = aggregation.summary_for_slots(weak_slots) or {}
                actual_probes = aggregation.replay_probes(actual_by_slot, weak_slots)
                checkpoint_row_count = aggregation.checkpoint_row_count

        self.assertEqual(checkpoint_row_count, len(materialized))
        assert_nested_almost_equal(self, actual_by_slot, expected_by_slot)
        assert_nested_almost_equal(self, actual_by_regime, expected_by_regime)
        assert_nested_almost_equal(self, actual_overall, expected_overall)
        assert_nested_almost_equal(self, actual_weak, expected_weak)
        assert_nested_almost_equal(self, actual_probes, expected_probes)

    def test_market_day_aggregation_peak_memory_stays_roughly_flat_as_days_grow(self):
        with tempfile.TemporaryDirectory() as tmp:
            with TenMinuteMarketDayAggregation(tmp) as aggregation:
                first_window_peak = 0
                second_window_peak = 0
                tracemalloc.start()
                try:
                    for day_index in range(600):
                        tracemalloc.reset_peak()
                        aggregation.add_market_day_rows(
                            scored_market_day(day_index, slots=(180,))
                        )
                        _current, peak = tracemalloc.get_traced_memory()
                        if day_index < 300:
                            first_window_peak = max(first_window_peak, peak)
                        else:
                            second_window_peak = max(second_window_peak, peak)
                finally:
                    tracemalloc.stop()

                self.assertEqual(aggregation.checkpoint_row_count, 1_200)
                # The later 300 market-days are reduced into fixed slot state;
                # only the exact distinct keys grow, and those spill to SQLite.
                self.assertLessEqual(
                    second_window_peak,
                    first_window_peak + 512 * 1024,
                )

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
                    },
                    {
                        "variant_id": "candidate_v1",
                        "market_id": "toronto",
                        "target_date": "2026-06-07",
                        "snapshot_id": "s0301",
                        "band_key": "eq:80",
                        "probability": "0.80",
                        "current_probability": "0.60",
                        "market_yes": "0.70",
                        "outcome": "1",
                        "captured_at_local": "2026-06-07T03:01:00-04:00",
                    }
                ],
            )

            candidate = build_candidate_item147(path, weak_slots={180})
            gate = candidate_ten_minute_gate(candidate, min_weak_market_days=1)
            row_export_hash = candidate_rows_corpus_hash(read_variant_rows(path))
            checkpoint_hash = candidate_rows_corpus_hash(read_candidate_checkpoint_rows(path))

        self.assertEqual(candidate["weak_slot_overlap"]["candidate_slot_overlap"], 1)
        self.assertEqual(candidate["source_rows"], 2)
        self.assertEqual(candidate["checkpoint_rows"], 1)
        self.assertEqual(candidate["corpus"]["corpus_hash"], row_export_hash)
        self.assertEqual(candidate["corpus"]["row_export_corpus_hash"], row_export_hash)
        self.assertEqual(candidate["corpus"]["checkpoint_corpus_hash"], checkpoint_hash)
        self.assertNotEqual(row_export_hash, checkpoint_hash)
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(gate["variant_ids"], ["candidate_v1"])


if __name__ == "__main__":
    unittest.main()
