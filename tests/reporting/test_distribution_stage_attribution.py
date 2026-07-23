import csv
import gc
import json
import tempfile
import unittest
import weakref
from collections import defaultdict
from pathlib import Path
from unittest import mock

from weather.reporting.scorecards import distribution_stage_attribution as stage_attribution
from weather.reporting.scorecards.distribution_stage_attribution import (
    build_payload,
    forecast_shape_scope_summary,
    render_report,
    write_outputs,
)
from weather.schema_registry import schema_version


def _runtime_fields(source_fingerprint, *, commit="abc123"):
    return {
        "runtime_identity_schema_version": "runtime_identity_v0.1",
        "runtime_git_branch": "master",
        "runtime_git_commit": commit,
        "runtime_git_dirty": "",
        "runtime_dirty_fingerprint": "",
        "runtime_source_fingerprint": source_fingerprint,
        "runtime_code_state": "current",
    }


def _write_fixture(root):
    folder = Path(root) / "highest-temperature-in-test-on-june-1-2026"
    folder.mkdir(parents=True)
    (folder / "settlement.json").write_text(
        json.dumps({
            "event_slug": folder.name,
            "market_id": "test",
            "target_date": "2026-06-01",
            "settlement_bucket": 22,
            "settlement_unit": "F",
        }),
        encoding="utf-8",
    )
    header = [
        "snapshot_id",
        "captured_at_local",
        "event_slug",
        "cutoff_hour",
        "active_model_kind",
        "component_name",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "component_probability",
    ]
    rows = []
    for component, losing_p, winning_p in [
        ("climatology_prior", 0.20, 0.40),
        ("feature_blend", 0.10, 0.70),
        ("post_live_signals", 0.40, 0.60),
        ("final_model", 0.10, 0.80),
    ]:
        rows.append({
            "snapshot_id": "s1",
            "captured_at_local": "2026-06-01T12:00:00-04:00",
            "event_slug": folder.name,
            "cutoff_hour": "12",
            "active_model_kind": "hgb",
            "component_name": component,
            "range_label": "20 F or below",
            "bin_kind": "lte",
            "bin_value_c": "20",
            "component_probability": losing_p,
        })
        rows.append({
            "snapshot_id": "s1",
            "captured_at_local": "2026-06-01T12:00:00-04:00",
            "event_slug": folder.name,
            "cutoff_hour": "12",
            "active_model_kind": "hgb",
            "component_name": component,
            "range_label": "22-23 F",
            "bin_kind": "eq",
            "bin_value_c": "22",
            "component_probability": winning_p,
        })
    with (folder / "components_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return folder


def _write_components(folder, rows):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    header = [
        "snapshot_id",
        "captured_at_utc",
        "captured_at_local",
        "event_slug",
        "runtime_identity_schema_version",
        "runtime_git_branch",
        "runtime_git_commit",
        "runtime_git_dirty",
        "runtime_dirty_fingerprint",
        "runtime_source_fingerprint",
        "runtime_code_state",
        "cutoff_hour",
        "active_model_kind",
        "component_name",
        "range_label",
        "bin_kind",
        "bin_value_c",
        "bin_value_hi_c",
        "component_probability",
    ]
    with (folder / "components_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _legacy_aggregate_rows_by_keys(rows, group_keys=None):
    group_keys = tuple(group_keys or ())
    groups = defaultdict(list)
    for row in rows:
        if not group_keys:
            key = ("all",)
        else:
            key = tuple(
                str(row.get(item) if row.get(item) not in (None, "") else "-")
                for item in group_keys
            )
        groups[key].append(row)
    output = []
    for key, group in sorted(groups.items()):
        delta_rows = [row for row in group if row.get("delta_brier") is not None]
        output_row = {
            "group": " | ".join(key),
            "n": len(group),
            "delta_n": len(delta_rows),
            "mean_brier": stage_attribution.mean(row.get("brier") for row in group),
            "mean_logloss": stage_attribution.mean(row.get("logloss") for row in group),
            "mean_delta_brier": stage_attribution.mean(
                row.get("delta_brier") for row in delta_rows
            ),
            "mean_delta_logloss": stage_attribution.mean(
                row.get("delta_logloss") for row in delta_rows
            ),
            "mean_winner_probability_delta": stage_attribution.mean(
                row.get("winner_probability_delta") for row in delta_rows
            ),
            "mean_adjacent_winner_mass_delta": stage_attribution.mean(
                row.get("adjacent_winner_mass_delta") for row in delta_rows
            ),
            "mean_effective_band_spread_delta": stage_attribution.mean(
                row.get("effective_band_spread_delta") for row in delta_rows
            ),
            "brier_worse_rows": sum(
                1 for row in delta_rows if row.get("delta_brier", 0.0) > 0
            ),
            "brier_better_rows": sum(
                1 for row in delta_rows if row.get("delta_brier", 0.0) < 0
            ),
        }
        for index, group_key in enumerate(group_keys):
            output_row[group_key] = key[index]
        output.append(output_row)
    return output


def _legacy_materialized_payload(
    snapshots_root,
    *,
    min_stage_rows,
    now,
    current_identity,
):
    rows = []
    scope_rows = []
    folders = stage_attribution.component_folders(snapshots_root)
    settled_folders = 0
    for folder in folders:
        scope_rows.extend(stage_attribution.component_scope_rows_for_folder(folder))
        folder_rows = stage_attribution.attribution_rows_for_folder(folder)
        if folder_rows:
            settled_folders += 1
            rows.extend(folder_rows)
    by_component = _legacy_aggregate_rows_by_keys(rows, ("component_name",))
    negatives = stage_attribution.net_negative_stages(
        by_component,
        min_rows=min_stage_rows,
    )
    by_market_stage = _legacy_aggregate_rows_by_keys(
        rows,
        ("market_id", "component_name"),
    )
    by_market_stage_cutoff_regime = _legacy_aggregate_rows_by_keys(
        rows,
        ("market_id", "component_name", "cutoff_regime"),
    )
    guardrail_aggregates = _legacy_aggregate_rows_by_keys(
        rows,
        ("market_id", "target_date", "component_name", "cutoff_regime"),
    )
    bottom_guardrails = stage_attribution._bottom_location_guardrail_rows_from_aggregates(
        guardrail_aggregates
    )
    bottom_guardrail_blockers = [
        row for row in bottom_guardrails if row.get("status") == "BLOCK"
    ]
    status = "NO_DATA" if not rows else (
        "ACTIONABLE" if negatives or bottom_guardrail_blockers else "OK"
    )
    overall = _legacy_aggregate_rows_by_keys(rows)
    return {
        "schema_version": stage_attribution.SCHEMA_VERSION,
        "generated_at_utc": now,
        "snapshots_root": str(Path(snapshots_root)),
        "current_identity": current_identity,
        "current_identity_text": stage_attribution.format_runtime_identity(current_identity),
        "status": status,
        "folder_count": len(folders),
        "settled_folder_count": settled_folders,
        "attribution_row_count": len(rows),
        "min_stage_rows": min_stage_rows,
        "summary": {
            "status": status,
            "net_negative_stage_count": len(negatives),
            "top_net_negative_stage": negatives[0] if negatives else None,
            "bottom_location_winner_mass_blocker_count": len(
                bottom_guardrail_blockers
            ),
            "top_bottom_location_winner_mass_blocker": (
                bottom_guardrail_blockers[0] if bottom_guardrail_blockers else None
            ),
        },
        "overall": overall[0] if overall else {},
        "by_component": by_component,
        "by_cutoff_hour": _legacy_aggregate_rows_by_keys(rows, ("cutoff_hour",)),
        "by_regime": _legacy_aggregate_rows_by_keys(rows, ("stage_regime",)),
        "by_market": _legacy_aggregate_rows_by_keys(rows, ("market_id",)),
        "by_market_stage": by_market_stage,
        "by_market_stage_cutoff_regime": by_market_stage_cutoff_regime,
        "bottom_location_winner_mass_guardrails": bottom_guardrails,
        "forecast_shape_scope": forecast_shape_scope_summary(
            rows,
            current_identity=current_identity,
            raw_rows=scope_rows,
        ),
        "net_negative_stages": negatives,
    }


class _ReclaimableRow:
    def __init__(self, index):
        self.values = {
            "component_name": "feature_blend",
            "brier": (index % 7) / 10.0,
            "logloss": (index % 11) / 10.0,
            "delta_brier": None if index % 3 == 0 else (index % 5 - 2) / 100.0,
            "delta_logloss": None if index % 3 == 0 else (index % 9 - 4) / 100.0,
            "winner_probability_delta": None,
            "adjacent_winner_mass_delta": None,
            "effective_band_spread_delta": None,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class DistributionStageAttributionTests(unittest.TestCase):
    def test_streaming_payload_is_byte_equivalent_to_materialized_behavior(self):
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "master",
            "git_commit": "head",
            "source_fingerprint": "current",
        }
        now = "2026-06-22T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            settled = _write_fixture(tmp)
            component_path = settled / "components_long.csv"
            with component_path.open("r", encoding="utf-8", newline="") as handle:
                fieldnames = csv.DictReader(handle).fieldnames
            with component_path.open("a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writerows([
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-01T12:00:00-04:00",
                        "event_slug": settled.name,
                        "cutoff_hour": "12",
                        "active_model_kind": "hgb",
                        "component_name": "forecast_pull",
                        "range_label": "20 F or below",
                        "bin_kind": "lte",
                        "bin_value_c": "20",
                        "component_probability": "0.15",
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_local": "2026-06-01T12:00:00-04:00",
                        "event_slug": settled.name,
                        "cutoff_hour": "12",
                        "active_model_kind": "hgb",
                        "component_name": "forecast_pull",
                        "range_label": "22-23 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "component_probability": "0.65",
                    },
                ])
            unsettled = Path(tmp) / "highest-temperature-in-test-on-june-2-2026"
            _write_components(
                unsettled,
                [
                    {
                        "snapshot_id": "current",
                        "captured_at_utc": "2026-06-02T12:00:00+00:00",
                        "captured_at_local": "2026-06-02T08:00:00-04:00",
                        "event_slug": unsettled.name,
                        **_runtime_fields("current", commit="head"),
                        "cutoff_hour": "8",
                        "active_model_kind": "hgb",
                        "component_name": "hgb_feature_model",
                        "range_label": "22 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "bin_value_hi_c": "22",
                        "component_probability": "0.5",
                    },
                    {
                        "snapshot_id": "current",
                        "captured_at_utc": "2026-06-02T12:00:00+00:00",
                        "captured_at_local": "2026-06-02T08:00:00-04:00",
                        "event_slug": unsettled.name,
                        **_runtime_fields("current", commit="head"),
                        "cutoff_hour": "8",
                        "active_model_kind": "hgb",
                        "component_name": "forecast_pull",
                        "range_label": "22 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "bin_value_hi_c": "22",
                        "component_probability": "0.5",
                    },
                    {
                        "snapshot_id": "stale",
                        "captured_at_utc": "2026-06-02T11:50:00+00:00",
                        "captured_at_local": "2026-06-02T07:50:00-04:00",
                        "event_slug": unsettled.name,
                        **_runtime_fields("old", commit="old"),
                        "cutoff_hour": "7",
                        "active_model_kind": "catboost",
                        "component_name": "forecast_pull",
                        "range_label": "22 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "bin_value_hi_c": "22",
                        "component_probability": "0.4",
                    },
                ],
            )
            expected = _legacy_materialized_payload(
                tmp,
                min_stage_rows=1,
                now=now,
                current_identity=current_identity,
            )
            actual = build_payload(
                tmp,
                min_stage_rows=1,
                now=now,
                current_identity=current_identity,
            )

        expected_json = json.dumps(expected, indent=2, sort_keys=True)
        actual_json = json.dumps(actual, indent=2, sort_keys=True)
        self.assertEqual(actual_json, expected_json)
        self.assertEqual(render_report(actual), render_report(expected))
        self.assertIn("regimes: hgb", actual["forecast_shape_scope"]["reason"])

    def test_streaming_accumulator_does_not_retain_source_rows(self):
        accumulator = stage_attribution._GroupedMetricAccumulator(("component_name",))
        first_row = _ReclaimableRow(0)
        first_row_ref = weakref.ref(first_row)
        accumulator.add(first_row)
        del first_row
        for index in range(1, 10_000):
            accumulator.add(_ReclaimableRow(index))
        gc.collect()

        self.assertIsNone(first_row_ref())
        self.assertEqual(len(accumulator.groups), 1)
        self.assertEqual(accumulator.as_rows()[0]["n"], 10_000)
        self.assertFalse(any(isinstance(value, list) for value in accumulator.groups.values()))

    def test_build_payload_does_not_call_materializing_folder_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(tmp)
            with (
                mock.patch.object(
                    stage_attribution,
                    "component_scope_rows_for_folder",
                    side_effect=AssertionError("materialized scope rows"),
                ),
                mock.patch.object(
                    stage_attribution,
                    "attribution_rows_for_folder",
                    side_effect=AssertionError("materialized attribution rows"),
                ),
            ):
                payload = build_payload(
                    tmp,
                    min_stage_rows=1,
                    now="2026-06-22T00:00:00+00:00",
                )

        self.assertEqual(payload["attribution_row_count"], 8)

    def test_build_payload_scores_stage_deltas_and_flags_net_negative_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(tmp)
            payload = build_payload(tmp, min_stage_rows=1, now="2026-06-21T00:00:00+00:00")

        self.assertEqual(payload["schema_version"], schema_version("distribution_stage_attribution"))
        self.assertEqual(payload["status"], "ACTIONABLE")
        self.assertEqual(payload["settled_folder_count"], 1)
        self.assertEqual(payload["attribution_row_count"], 8)
        by_component = {row["group"]: row for row in payload["by_component"]}
        self.assertGreater(by_component["post_live_signals"]["mean_delta_brier"], 0.0)
        self.assertLess(by_component["feature_blend"]["mean_delta_brier"], 0.0)
        self.assertEqual(payload["by_regime"][0]["group"], "hgb")
        self.assertEqual(payload["net_negative_stages"][0]["group"], "post_live_signals")
        self.assertEqual(payload["forecast_shape_scope"]["status"], "PASS")
        self.assertEqual(payload["forecast_shape_scope"]["feature_model_forecast_shape_rows"], 0)

    def test_build_payload_emits_market_stage_slices_and_bottom_guardrail(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "highest-temperature-in-miami-on-june-1-2026"
            folder.mkdir(parents=True)
            (folder / "settlement.json").write_text(
                json.dumps({
                    "event_slug": folder.name,
                    "market_id": "miami",
                    "target_date": "2026-06-01",
                    "settlement_bucket": 22,
                }),
                encoding="utf-8",
            )
            rows = []
            for component, losing_p, winner_p, adjacent_p in [
                ("climatology_prior", "0.10", "0.80", "0.10"),
                ("final_model", "0.20", "0.60", "0.20"),
            ]:
                rows.extend([
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-01T16:00:00+00:00",
                        "captured_at_local": "2026-06-01T12:00:00-04:00",
                        "event_slug": folder.name,
                        "cutoff_hour": "12",
                        "active_model_kind": "hgb",
                        "component_name": component,
                        "range_label": "20-21 F",
                        "bin_kind": "eq",
                        "bin_value_c": "20",
                        "component_probability": losing_p,
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-01T16:00:00+00:00",
                        "captured_at_local": "2026-06-01T12:00:00-04:00",
                        "event_slug": folder.name,
                        "cutoff_hour": "12",
                        "active_model_kind": "hgb",
                        "component_name": component,
                        "range_label": "22-23 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "component_probability": winner_p,
                    },
                    {
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-01T16:00:00+00:00",
                        "captured_at_local": "2026-06-01T12:00:00-04:00",
                        "event_slug": folder.name,
                        "cutoff_hour": "12",
                        "active_model_kind": "hgb",
                        "component_name": component,
                        "range_label": "24-25 F",
                        "bin_kind": "eq",
                        "bin_value_c": "24",
                        "component_probability": adjacent_p,
                    },
                ])
            _write_components(folder, rows)

            payload = build_payload(tmp, min_stage_rows=1, now="2026-06-22T00:00:00+00:00")

        market_stage = {
            (row["market_id"], row["component_name"]): row
            for row in payload["by_market_stage"]
        }
        market_stage_regime = {
            (row["market_id"], row["component_name"], row["cutoff_regime"]): row
            for row in payload["by_market_stage_cutoff_regime"]
        }
        blockers = [
            row for row in payload["bottom_location_winner_mass_guardrails"]
            if row["status"] == "BLOCK"
        ]
        report = render_report(payload)

        final_stage = market_stage[("miami", "final_model")]
        self.assertEqual(payload["status"], "ACTIONABLE")
        self.assertAlmostEqual(final_stage["mean_winner_probability_delta"], -0.20)
        self.assertAlmostEqual(final_stage["mean_adjacent_winner_mass_delta"], 0.10)
        self.assertIn(("miami", "final_model", "midday"), market_stage_regime)
        self.assertEqual(blockers[0]["component_name"], "final_model")
        self.assertEqual(blockers[0]["market_id"], "miami")
        self.assertIn("winner probability reduced", blockers[0]["reason"])
        self.assertEqual(payload["summary"]["bottom_location_winner_mass_blocker_count"], 1)
        self.assertIn("Bottom-Location Winner-Mass Guardrails", report)
        self.assertIn("By Market Stage", report)
        self.assertIn("By Market Stage Cutoff Regime", report)

    def test_write_outputs_emits_json_and_markdown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(Path(tmp) / "snapshots")
            payload = build_payload(Path(tmp) / "snapshots", min_stage_rows=1)
            json_out, report_out = write_outputs(
                payload,
                Path(tmp) / "out.json",
                Path(tmp) / "out.md",
            )

            saved = json.loads(json_out.read_text(encoding="utf-8"))
            report = report_out.read_text(encoding="utf-8")

        self.assertEqual(saved["status"], "ACTIONABLE")
        self.assertIn("Distribution Stage Attribution", report)
        self.assertIn("Forecast Shape Scope", report)
        self.assertIn("post_live_signals", report)
        self.assertIn("Positive deltas", render_report(payload))

    def test_forecast_shape_scope_reports_empirical_only_application(self):
        rows = [
            {
                "component_name": "forecast_pull",
                "stage_regime": "empirical",
                "delta_brier": -0.02,
                "delta_logloss": 0.03,
                "winner_probability_delta": 0.10,
            },
            {
                "component_name": "feature_blend",
                "stage_regime": "hgb",
                "delta_brier": -0.01,
            },
        ]

        summary = forecast_shape_scope_summary(rows)

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["feature_model_forecast_shape_rows"], 0)
        self.assertEqual(summary["empirical_forecast_shape_rows"], 1)
        self.assertAlmostEqual(summary["empirical_delta_brier"], -0.02)
        self.assertIn("empirical fallback", summary["reason"])

    def test_forecast_shape_scope_blocks_feature_model_application(self):
        summary = forecast_shape_scope_summary([
            {
                "component_name": "forecast_pull",
                "stage_regime": "hgb",
                "delta_brier": 0.01,
                "delta_logloss": 0.02,
            },
        ])

        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["feature_model_forecast_shape_rows"], 1)
        self.assertEqual(summary["feature_model_regimes"], ["hgb"])

    def test_forecast_shape_scope_blocks_until_current_feature_tape_exists(self):
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "master",
            "git_commit": "head",
            "source_fingerprint": "current",
        }

        summary = forecast_shape_scope_summary(
            [
                {
                    "component_name": "forecast_pull",
                    "stage_regime": "hgb",
                    **_runtime_fields("old", commit="old"),
                },
            ],
            current_identity=current_identity,
        )

        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["current_code_feature_model_forecast_shape_rows"], 0)
        self.assertEqual(summary["stale_feature_model_forecast_shape_rows"], 1)
        self.assertIn("no current-code feature-model component tape", summary["reason"])
        self.assertEqual(
            summary["next_unblock_action"],
            "regenerate/replay a complete nonzero current-code feature-model component "
            "population and require current_code_feature_model_component_rows>0 with "
            "current_code_feature_model_forecast_shape_rows=0",
        )

    def test_forecast_shape_scope_passes_when_current_feature_tape_has_no_pull(self):
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "master",
            "git_commit": "head",
            "source_fingerprint": "current",
        }

        summary = forecast_shape_scope_summary(
            [
                {
                    "component_name": "forecast_pull",
                    "stage_regime": "hgb",
                    **_runtime_fields("old", commit="old"),
                },
                {
                    "component_name": "hgb_feature_model",
                    "stage_regime": "hgb",
                    **_runtime_fields("current", commit="head"),
                },
            ],
            current_identity=current_identity,
        )

        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["current_code_feature_model_component_rows"], 1)
        self.assertEqual(summary["current_code_feature_model_forecast_shape_rows"], 0)
        self.assertEqual(summary["stale_feature_model_forecast_shape_rows"], 1)
        self.assertIn("stale relative to current source", summary["reason"])

    def test_forecast_shape_scope_blocks_current_feature_pull(self):
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "master",
            "git_commit": "head",
            "source_fingerprint": "current",
        }

        summary = forecast_shape_scope_summary(
            [
                {
                    "component_name": "forecast_pull",
                    "stage_regime": "hgb",
                    **_runtime_fields("current", commit="head"),
                },
            ],
            current_identity=current_identity,
        )

        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["current_code_feature_model_forecast_shape_rows"], 1)
        self.assertIn("current-code forecast floor/pull rows", summary["reason"])

    def test_build_payload_uses_unsettled_current_feature_tape_for_scope(self):
        current_identity = {
            "schema_version": "runtime_identity_v0.1",
            "git_branch": "master",
            "git_commit": "head",
            "source_fingerprint": "current",
        }
        with tempfile.TemporaryDirectory() as tmp:
            settled = Path(tmp) / "highest-temperature-in-test-on-june-1-2026"
            settled.mkdir(parents=True)
            (settled / "settlement.json").write_text(
                json.dumps({
                    "event_slug": settled.name,
                    "market_id": "test",
                    "target_date": "2026-06-01",
                    "settlement_bucket": 22,
                }),
                encoding="utf-8",
            )
            _write_components(
                settled,
                [
                    {
                        "snapshot_id": "old",
                        "captured_at_utc": "2026-06-01T12:00:00+00:00",
                        "captured_at_local": "2026-06-01T08:00:00-04:00",
                        "event_slug": settled.name,
                        **_runtime_fields("old", commit="old"),
                        "cutoff_hour": "8",
                        "active_model_kind": "hgb",
                        "component_name": "forecast_pull",
                        "range_label": "22 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "bin_value_hi_c": "22",
                        "component_probability": "0.5",
                    },
                ],
            )
            unsettled = Path(tmp) / "highest-temperature-in-test-on-june-2-2026"
            _write_components(
                unsettled,
                [
                    {
                        "snapshot_id": "current",
                        "captured_at_utc": "2026-06-02T12:00:00+00:00",
                        "captured_at_local": "2026-06-02T08:00:00-04:00",
                        "event_slug": unsettled.name,
                        **_runtime_fields("current", commit="head"),
                        "cutoff_hour": "8",
                        "active_model_kind": "hgb",
                        "component_name": "hgb_feature_model",
                        "range_label": "22 F",
                        "bin_kind": "eq",
                        "bin_value_c": "22",
                        "bin_value_hi_c": "22",
                        "component_probability": "0.5",
                    },
                ],
            )

            payload = build_payload(
                tmp,
                min_stage_rows=1,
                current_identity=current_identity,
                now="2026-06-22T00:00:00+00:00",
            )

        scope = payload["forecast_shape_scope"]
        self.assertEqual(scope["status"], "PASS")
        self.assertEqual(scope["feature_model_forecast_shape_rows"], 1)
        self.assertEqual(scope["scored_feature_model_forecast_shape_rows"], 1)
        self.assertEqual(scope["current_code_feature_model_component_rows"], 1)
        self.assertEqual(scope["current_code_feature_model_forecast_shape_rows"], 0)
        self.assertEqual(scope["stale_feature_model_forecast_shape_rows"], 1)
        self.assertIn("current-code feature-model rows have none", scope["reason"])


if __name__ == "__main__":
    unittest.main()
