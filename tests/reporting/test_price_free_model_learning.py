import csv
import json
import tempfile
import tracemalloc
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from weather.reporting.candidate_lifecycle.price_free_model_learning import (
    bounded_daily_refresh_corpus,
    build_price_free_learning,
    build_current_max_payload,
    classify_current_max_state,
    hourly_checkpoint_rows,
    model_score_rows,
    render_report,
    score_folder,
    snapshot_partition_stats,
    summarize_by_hour,
    summarize_by_market,
    write_csv_dicts,
    write_outputs,
    CURRENT_MAX_CSV_COLUMNS,
    HOURLY_CSV_COLUMNS,
    SCHEMA_VERSION,
)
from weather.reporting.hourly.hourly_model_performance import (
    discover_labeled_folders,
)
from weather.reporting.serving_gates.model_scoring_liveness import (
    attach_scoring_liveness,
    build_rerun_command,
)


SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def write_snapshot_folder(root):
    folder = Path(root) / "snapshots" / SLUG
    folder.mkdir(parents=True)
    rows = [
        {
            "snapshot_id": "s6",
            "captured_at_utc": "2026-06-03T10:15:00+00:00",
            "captured_at_local": "2026-06-03T06:15:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.10",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "70",
            "wu_current_c": "68",
            "wu_max_since_7am_c": "90",
        },
        {
            "snapshot_id": "s6",
            "captured_at_utc": "2026-06-03T10:15:00+00:00",
            "captured_at_local": "2026-06-03T06:15:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.80",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "70",
            "wu_current_c": "68",
            "wu_max_since_7am_c": "90",
        },
        {
            "snapshot_id": "s8",
            "captured_at_utc": "2026-06-03T12:05:00+00:00",
            "captured_at_local": "2026-06-03T08:05:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "9 C or below",
            "bin_kind": "lte",
            "bin_value_c": "9",
            "model_probability": "0.05",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "72",
            "wu_current_c": "73",
            "wu_max_since_7am_c": "88",
        },
        {
            "snapshot_id": "s8",
            "captured_at_utc": "2026-06-03T12:05:00+00:00",
            "captured_at_local": "2026-06-03T08:05:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "10 C",
            "bin_kind": "eq",
            "bin_value_c": "10",
            "model_probability": "0.90",
            "market_yes": "",
            "market_no": "",
            "market_status": "inactive",
            "wu_history_high_c": "72",
            "wu_current_c": "73",
            "wu_max_since_7am_c": "88",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return folder


def write_labels_csv(root, folder):
    path = Path(root) / "labels.csv"
    row = {
        "event_slug": SLUG,
        "market_id": "toronto",
        "city": "Toronto",
        "target_date": "2026-06-03",
        "settlement_bucket": "10",
        "settlement_high": "95",
        "settlement_unit": "C",
        "settlement_source": "test",
        "quality_grade": "complete",
        "snapshot_count": "2",
        "band_count": "2",
        "snapshot_tape_path": str(folder / "snapshots_long.csv"),
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def legacy_materialized_payload(labels_csv, snapshots_root, generated_at):
    """The pre-streaming v0.1 assembly retained as a fixture oracle."""

    quality_grades = ("complete",)
    labels, skipped = discover_labeled_folders(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        include_promotion_countable_labels=True,
        markets=(),
        start_date=None,
        end_date=None,
    )
    all_rows = []
    all_current_max_rows = []
    days = []
    score_errors = []
    reason_counts = Counter()
    for item in labels:
        try:
            rows, current_max_rows, day = score_folder(item["folder"], item["label"])
        except Exception as exc:
            score_errors.append({"folder": str(item["folder"]), "error": str(exc)})
            continue
        all_rows.extend(rows)
        all_current_max_rows.extend(current_max_rows)
        days.append(day)
        reason_counts.update(day.get("price_free_reasons") or [])

    checkpoint_rows = hourly_checkpoint_rows(all_rows)
    overall_checkpoint = model_score_rows(checkpoint_rows) or {}
    current_max = build_current_max_payload(all_current_max_rows)
    status = "OK" if all_rows else "NO_SCORED_ROWS"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "status": status,
        "evidence_classification": {
            "lane": "diagnostic_price_free_not_promotion_evidence",
            "uses_market_prices": False,
            "counts_toward_polymarket_benchmark": False,
            "counts_toward_retrain_input": bool(all_rows),
        },
        "inputs": {
            "labels_csv": str(Path(labels_csv)),
            "snapshots_root": str(Path(snapshots_root)),
            "quality_grades": list(quality_grades),
            "include_promotion_countable_labels": True,
            "markets": [],
            "start_date": None,
            "end_date": None,
        },
        "corpus": {
            "selected_label_count": len(labels),
            "scored_market_days": sum(1 for day_row in days if day_row.get("rows")),
            "markets": sorted(
                {day_row.get("market_id") for day_row in days if day_row.get("market_id")}
            ),
            "date_min": min(
                (day_row.get("target_date") for day_row in days if day_row.get("target_date")),
                default=None,
            ),
            "date_max": max(
                (day_row.get("target_date") for day_row in days if day_row.get("target_date")),
                default=None,
            ),
            "all_snapshot_rows": len(all_rows),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "price_free_reason_counts": dict(sorted(reason_counts.items())),
            "skipped_labels": skipped,
            "score_errors": score_errors,
        },
        "days": days,
        "overall": {
            "hourly_checkpoint": overall_checkpoint,
            "all_snapshots": model_score_rows(all_rows) or {},
        },
        "by_hour": summarize_by_hour(checkpoint_rows),
        "by_market": summarize_by_market(checkpoint_rows),
        "all_snapshot_by_hour": summarize_by_hour(all_rows),
        "snapshot_partitions": snapshot_partition_stats(checkpoint_rows),
        "current_max_carryover": current_max,
        "daily_summary": {
            "status": status,
            "scored_market_days": sum(1 for day_row in days if day_row.get("rows")),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "final_top_hit_rate": overall_checkpoint.get(
                "partition_model_top_is_winner_rate"
            ),
            "final_winner_probability": overall_checkpoint.get(
                "partition_model_winner_probability"
            ),
            "current_max_guarded_count": (current_max.get("summary") or {}).get(
                "risky_or_guarded_count",
                0,
            ),
        },
    }
    return attach_scoring_liveness(
        payload,
        artifact_name="price_free_model_learning",
        labels_csv=labels_csv,
        quality_grades=quality_grades,
        include_promotion_countable_labels=True,
        last_scored_target_date=(payload.get("corpus") or {}).get("date_max"),
        rerun_command=build_rerun_command(
            "weather.reporting.candidate_lifecycle.price_free_model_learning",
            labels_csv=labels_csv,
            snapshots_root=snapshots_root,
            quality_grades=quality_grades,
            include_promotion_countable_labels=True,
            markets=(),
            start_date=None,
            end_date=None,
        ),
    )


def write_synthetic_corpus(root, market_days):
    root = Path(root)
    snapshots_root = root / "snapshots"
    labels = []
    start = date(2026, 1, 1)
    for index in range(market_days):
        target = start + timedelta(days=index)
        slug = f"synthetic-price-free-{index:03d}"
        folder = snapshots_root / slug
        folder.mkdir(parents=True)
        tape = folder / "snapshots_long.csv"
        rows = [
            {
                "snapshot_id": f"snapshot-{index:03d}",
                "captured_at_utc": f"{target.isoformat()}T13:00:00+00:00",
                "captured_at_local": f"{target.isoformat()}T09:00:00-04:00",
                "event_slug": slug,
                "model_version": "bounded-test",
                "range_label": "9 C or below",
                "bin_kind": "lte",
                "bin_value_c": "9",
                "model_probability": "0.25",
                "market_yes": "",
                "market_no": "",
                "market_status": "inactive",
                "wu_history_high_c": "9",
                "wu_current_c": "8",
                "wu_max_since_7am_c": "8",
            },
            {
                "snapshot_id": f"snapshot-{index:03d}",
                "captured_at_utc": f"{target.isoformat()}T13:00:00+00:00",
                "captured_at_local": f"{target.isoformat()}T09:00:00-04:00",
                "event_slug": slug,
                "model_version": "bounded-test",
                "range_label": "10 C",
                "bin_kind": "eq",
                "bin_value_c": "10",
                "model_probability": "0.75",
                "market_yes": "",
                "market_no": "",
                "market_status": "inactive",
                "wu_history_high_c": "9",
                "wu_current_c": "8",
                "wu_max_since_7am_c": "8",
            },
        ]
        with tape.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        labels.append(
            {
                "event_slug": slug,
                "market_id": "synthetic",
                "city": "Synthetic",
                "target_date": target.isoformat(),
                "settlement_bucket": "10",
                "settlement_high": "10",
                "settlement_unit": "C",
                "settlement_source": "test",
                "quality_grade": "complete",
                "snapshot_count": "1",
                "band_count": "2",
                "snapshot_tape_path": str(tape),
            }
        )
    labels_csv = root / "labels.csv"
    with labels_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]))
        writer.writeheader()
        writer.writerows(labels)
    return labels_csv, snapshots_root


class TestPriceFreeModelLearning(unittest.TestCase):
    def test_scores_inactive_market_without_market_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_labels_csv(tmp, folder)

            payload = build_price_free_learning(
                labels_csv=labels_csv,
                snapshots_root=Path(tmp) / "snapshots",
                quality_grades=("complete",),
            )
            self.addCleanup(payload.close)
            out_dir = Path(tmp) / "out"
            json_out, report_out, hourly_csv, current_max_csv = write_outputs(
                payload,
                json_out=out_dir / "price_free.json",
                report_out=out_dir / "price_free.md",
                hourly_csv_out=out_dir / "price_free_by_hour.csv",
                current_max_csv_out=out_dir / "price_free_current_max.csv",
            )
            report = Path(report_out).read_text(encoding="utf-8")
            json_exists = Path(json_out).exists()
            hourly_csv_exists = Path(hourly_csv).exists()
            current_max_csv_exists = Path(current_max_csv).exists()

        self.assertEqual(payload["schema_version"], "price_free_model_learning_v0.1")
        self.assertEqual(payload["status"], "OK")
        self.assertFalse(payload["evidence_classification"]["uses_market_prices"])
        self.assertEqual(payload["corpus"]["scored_market_days"], 1)
        self.assertEqual(payload["corpus"]["hourly_checkpoint_rows"], 4)
        self.assertIn("absent_market_prices", payload["corpus"]["price_free_reason_counts"])
        self.assertIn("inactive_market", payload["corpus"]["price_free_reason_counts"])
        self.assertEqual(payload["overall"]["hourly_checkpoint"]["partition_model_top_is_winner_rate"], 1.0)
        current = payload["current_max_carryover"]
        self.assertEqual(current["summary"]["risky_or_guarded_count"], 2)
        self.assertEqual(current["summary"]["pre_reset_null_count"], 1)
        self.assertEqual(current["summary"]["support_only_count"], 1)
        self.assertEqual(current["summary"]["early_large_gap_count"], 1)
        states = {row["snapshot_id"]: row["current_max_state"] for row in current["rows"]}
        self.assertEqual(states["s6"], "pre_reset_current_max_null")
        self.assertEqual(states["s8"], "early_current_max_history_gap")
        self.assertIn("Price-Free Model Learning Audit", report)
        self.assertIn("Current-Max Carryover Guard", report)
        self.assertTrue(json_exists)
        self.assertTrue(hourly_csv_exists)
        self.assertTrue(current_max_csv_exists)

    def test_current_max_classifier_nulls_pre_reset_and_validates_history(self):
        pre_reset = classify_current_max_state(
            current_max=90,
            wu_history_high=70,
            current_temp=68,
            cutoff_hour=6,
            final_high=95,
        )
        validated = classify_current_max_state(
            current_max=72,
            wu_history_high=72,
            current_temp=72,
            cutoff_hour=9,
            final_high=80,
        )

        self.assertEqual(pre_reset["feature_disposition"], "null_before_reset")
        self.assertEqual(pre_reset["current_max_state"], "pre_reset_current_max_null")
        self.assertEqual(validated["feature_disposition"], "validated")
        self.assertEqual(validated["current_max_state"], "wu_history_validated_current_max")

    def test_streaming_payload_and_all_outputs_match_materialized_v01_fixture(self):
        generated_at = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_labels_csv(tmp, folder)
            snapshots_root = Path(tmp) / "snapshots"
            expected = legacy_materialized_payload(labels_csv, snapshots_root, generated_at)
            with patch(
                "weather.reporting.candidate_lifecycle.price_free_model_learning.utc_now",
                return_value=generated_at,
            ):
                payload = build_price_free_learning(
                    labels_csv=labels_csv,
                    snapshots_root=snapshots_root,
                    quality_grades=("complete",),
                )
            try:
                self.assertEqual(payload.materialize(), expected)
                actual_dir = Path(tmp) / "actual"
                expected_dir = Path(tmp) / "expected"
                actual_paths = write_outputs(
                    payload,
                    json_out=actual_dir / "price_free.json",
                    report_out=actual_dir / "price_free.md",
                    hourly_csv_out=actual_dir / "price_free_by_hour.csv",
                    current_max_csv_out=actual_dir / "price_free_current_max.csv",
                )
                expected_dir.mkdir()
                expected_paths = (
                    expected_dir / "price_free.json",
                    expected_dir / "price_free.md",
                    expected_dir / "price_free_by_hour.csv",
                    expected_dir / "price_free_current_max.csv",
                )
                expected_paths[0].write_text(
                    json.dumps(expected, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8",
                )
                expected_paths[1].write_text(render_report(expected), encoding="utf-8")
                write_csv_dicts(expected_paths[2], expected["by_hour"], HOURLY_CSV_COLUMNS)
                write_csv_dicts(
                    expected_paths[3],
                    expected["current_max_carryover"]["rows"],
                    CURRENT_MAX_CSV_COLUMNS,
                )
                for actual, reference in zip(actual_paths, expected_paths):
                    self.assertEqual(Path(actual).read_bytes(), Path(reference).read_bytes())
            finally:
                payload.close()

    def test_duplicate_market_day_tapes_preserve_global_v01_reduction(self):
        generated_at = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_snapshot_folder(tmp)
            labels_csv = write_labels_csv(tmp, folder)
            snapshots_root = Path(tmp) / "snapshots"
            duplicate_slug = f"{SLUG}-duplicate"
            duplicate_folder = snapshots_root / duplicate_slug
            duplicate_folder.mkdir()
            with (folder / "snapshots_long.csv").open(
                "r",
                encoding="utf-8",
                newline="",
            ) as source:
                duplicate_rows = [dict(row) for row in csv.DictReader(source)]
            for row in duplicate_rows:
                row["event_slug"] = duplicate_slug
            with (duplicate_folder / "snapshots_long.csv").open(
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(duplicate_rows[0]))
                writer.writeheader()
                writer.writerows(duplicate_rows)
            with labels_csv.open("r", encoding="utf-8", newline="") as handle:
                label_rows = [dict(row) for row in csv.DictReader(handle)]
            duplicate_label = dict(label_rows[0])
            duplicate_label["event_slug"] = duplicate_slug
            duplicate_label["snapshot_tape_path"] = str(
                duplicate_folder / "snapshots_long.csv"
            )
            label_rows.append(duplicate_label)
            with labels_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(label_rows[0]))
                writer.writeheader()
                writer.writerows(label_rows)

            expected = legacy_materialized_payload(
                labels_csv,
                snapshots_root,
                generated_at,
            )
            with patch(
                "weather.reporting.candidate_lifecycle.price_free_model_learning.utc_now",
                return_value=generated_at,
            ):
                payload = build_price_free_learning(
                    labels_csv=labels_csv,
                    snapshots_root=snapshots_root,
                    quality_grades=("complete",),
                )
            try:
                actual = payload.materialize()
            finally:
                payload.close()

        self.assertEqual(actual, expected)
        self.assertEqual(actual["corpus"]["selected_label_count"], 2)
        self.assertEqual(actual["corpus"]["all_snapshot_rows"], 8)
        self.assertEqual(actual["corpus"]["hourly_checkpoint_rows"], 4)

    def test_daily_refresh_corpus_projection_caps_score_error_details(self):
        corpus = {
            "selected_label_count": 100,
            "scored_market_days": 0,
            "markets": [],
            "score_errors": (
                {"folder": f"folder-{index}", "error": "bad tape"}
                for index in range(100)
            ),
        }

        projected = bounded_daily_refresh_corpus(
            corpus,
            score_error_example_limit=3,
        )

        self.assertEqual(projected["score_error_count"], 100)
        self.assertEqual(
            [row["folder"] for row in projected["score_error_examples"]],
            ["folder-0", "folder-1", "folder-2"],
        )
        self.assertNotIn("score_errors", projected)

    def test_peak_python_memory_is_bounded_from_five_to_fifty_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            five_labels, five_snapshots = write_synthetic_corpus(Path(tmp) / "five", 5)
            fifty_labels, fifty_snapshots = write_synthetic_corpus(Path(tmp) / "fifty", 50)

            def peak_for(labels_csv, snapshots_root):
                tracemalloc.start()
                payload = build_price_free_learning(
                    labels_csv=labels_csv,
                    snapshots_root=snapshots_root,
                    quality_grades=("complete",),
                )
                try:
                    _current, peak = tracemalloc.get_traced_memory()
                    return peak
                finally:
                    payload.close()
                    tracemalloc.stop()

            peak_five = peak_for(five_labels, five_snapshots)
            peak_fifty = peak_for(fifty_labels, fifty_snapshots)

        self.assertLessEqual(
            peak_fifty,
            peak_five + 1_000_000,
            f"50-day peak {peak_fifty} exceeded 5-day peak {peak_five} by more than 1 MB",
        )


if __name__ == "__main__":
    unittest.main()
