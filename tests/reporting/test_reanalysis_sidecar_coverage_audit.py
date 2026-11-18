import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.data_quality.reanalysis_sidecar_coverage_audit import (
    FEATURE_GROUPS,
    audit_sidecar,
    build_payload,
    group_coverage,
    render_markdown,
)


FIELDNAMES = [
    "schema_version",
    "source",
    "market_id",
    "city",
    "station",
    "local_date",
    "antecedent_date",
    "temperature_unit",
]
for group in FEATURE_GROUPS:
    for column in group.columns:
        if column not in FIELDNAMES:
            FIELDNAMES.append(column)
    if group.availability_column and group.availability_column not in FIELDNAMES:
        FIELDNAMES.append(group.availability_column)


def row_for(day, **overrides):
    row = {field: "" for field in FIELDNAMES}
    row.update({
        "schema_version": "reanalysis_synoptic_features_v0.3",
        "source": "open_meteo_era5_reanalysis_synoptic",
        "market_id": "nyc",
        "city": "New York",
        "station": "KLGA",
        "local_date": day,
        "antecedent_date": day,
        "temperature_unit": "F",
    })
    for group in FEATURE_GROUPS:
        for column in group.columns:
            row[column] = "1.0"
        if group.availability_column:
            row[group.availability_column] = "1.0"
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def write_sidecar(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class ReanalysisSidecarCoverageAuditTests(unittest.TestCase):
    def test_numeric_group_counts_only_finite_features(self):
        group = next(item for item in FEATURE_GROUPS if item.name == "pressure_level")
        field = "reanalysis_prev_day_temperature_850hpa_c"
        invalid = ["sensor error", "false", "TRUE", False, True, "nan", "inf", "-inf", "1e999"]
        values = [0, "-2.5e1", *invalid]
        rows = []
        for index, value in enumerate(values, 1):
            row = row_for(f"2026-06-{index:02d}")
            row[field] = value
            rows.append(row)

        result = group_coverage(rows, group)

        self.assertEqual(result["row_count"], len(values))
        self.assertEqual(result["complete_rows"], 2)
        self.assertEqual(result["coverage"], 2 / len(values))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["present_by_column"][field], 2)
        self.assertEqual(result["last_complete_date"], "2026-06-02")
        self.assertEqual(result["partial_columns"], [field])

    def test_availability_count_matches_group_gate(self):
        for name in ("base_sidecar", "pressure_level", "teleconnection"):
            group = next(item for item in FEATURE_GROUPS if item.name == name)
            rows = [row_for("2026-06-01", **{group.availability_column: flag})
                    for flag in ("0.0", "1", "broken", "true")]
            with self.subTest(group=name):
                result = group_coverage(rows, group)
                self.assertEqual(result["complete_rows"], 1)
                self.assertEqual(result["present_by_column"][group.availability_column], 1)
                self.assertIn(group.availability_column, result["partial_columns"])

    def test_documented_binary_feature_requires_zero_or_one(self):
        group = next(item for item in FEATURE_GROUPS if item.name == "static_context")
        field = "reanalysis_coastal_flag"
        rows = [row_for("2026-06-01", **{field: value}) for value in ("0", "1.0", "-1", ".5", "2", "false")]
        result = group_coverage(rows, group)
        self.assertEqual(result["complete_rows"], 2)
        self.assertEqual(result["present_by_column"][field], 2)

    def test_garbage_in_required_csv_field_blocks_bounded_replay_window(self):
        field = "reanalysis_prev_day_soil_temperature_0_to_7cm_mean"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "reanalysis"
            sidecar = root / "klga" / "features" / "reanalysis_synoptic_features.csv"
            write_sidecar(sidecar, [row_for("2026-06-07", **{field: "sensor error"})])
            payload = build_payload(reanalysis_root=root, target_start="2026-06-07", target_end="2026-06-07")

        self.assertEqual(payload["status"], "BLOCK")
        market = payload["markets"][0]
        self.assertEqual(market["blockers"], ["rich_surface:MISSING"])
        self.assertEqual(market["target_window_groups"]["rich_surface"]["missing_columns"], [field])
        self.assertEqual(market["target_window_groups"]["pressure_level"]["status"], "PASS")

    def test_duplicate_observed_dates_cannot_hide_a_missing_calendar_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "reanalysis"
            write_sidecar(root / "klga" / "features" / "reanalysis_synoptic_features.csv",
                          [row_for("2026-06-07"), row_for("2026-06-07")])
            payload = build_payload(reanalysis_root=root, target_start="2026-06-07", target_end="2026-06-08")

        market = payload["markets"][0]
        self.assertEqual(market["target_rows"], 2)
        self.assertEqual(market["target_distinct_dates"], 1)
        self.assertEqual(market["target_expected_dates"], 2)
        self.assertEqual(market["target_window_groups"]["rich_surface"]["complete_rows"], 2)
        self.assertEqual(market["blockers"], ["target_window_missing_dates"])
        self.assertEqual(payload["status"], "BLOCK")

    def test_requested_window_without_sidecars_has_a_visible_root_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_payload(reanalysis_root=tmp, target_start="2026-06-07")
        self.assertEqual(payload["summary"]["markets"], 0)
        self.assertEqual(payload["status"], "BLOCK")
        self.assertIn("target_window_no_sidecars", render_markdown(payload))

    def test_invalid_requested_dates_cannot_disable_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for start, end in (("bad", None), (None, "bad"), ("2026-06-08", "2026-06-07")):
                with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                    build_payload(reanalysis_root=tmp, target_start=start, target_end=end)

    def test_group_coverage_treats_zero_flags_as_present(self):
        group = next(item for item in FEATURE_GROUPS if item.name == "static_context")
        rows = [
            row_for(
                "2026-06-07",
                reanalysis_coastal_flag="0.0",
                reanalysis_sea_breeze_context_flag="0.0",
                reanalysis_lake_breeze_context_flag="0.0",
            )
        ]

        payload = group_coverage(rows, group)

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["complete_rows"], 1)

    def test_target_window_blocks_missing_pressure_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = Path(tmp) / "reanalysis" / "klga" / "features" / "reanalysis_synoptic_features.csv"
            write_sidecar(
                sidecar,
                [
                    row_for(
                        "2026-06-07",
                        reanalysis_pressure_level_available="0.0",
                        reanalysis_prev_day_temperature_850hpa_c="",
                        reanalysis_prev_day_geopotential_height_500hpa_m="",
                        reanalysis_prev_day_thickness_1000_500hpa_m="",
                    ),
                    row_for(
                        "2026-06-08",
                        reanalysis_pressure_level_available="0.0",
                        reanalysis_prev_day_temperature_850hpa_c="",
                        reanalysis_prev_day_geopotential_height_500hpa_m="",
                        reanalysis_prev_day_thickness_1000_500hpa_m="",
                    ),
                ],
            )

            payload = audit_sidecar(
                sidecar,
                target_start=None,
                target_end=None,
                required_groups=("rich_surface", "pressure_level"),
            )
            window_payload = build_payload(
                reanalysis_root=Path(tmp) / "reanalysis",
                target_start="2026-06-07",
                target_end="2026-06-08",
                required_groups=("rich_surface", "pressure_level"),
                generated_at_utc="2026-06-20T00:00:00+00:00",
            )

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(window_payload["status"], "BLOCK")
        self.assertEqual(window_payload["summary"]["blocking_markets"], 1)
        market = window_payload["markets"][0]
        self.assertIn("pressure_level:MISSING", market["blockers"])
        self.assertEqual(market["target_window_groups"]["rich_surface"]["status"], "PASS")
        self.assertEqual(market["target_window_groups"]["pressure_level"]["status"], "MISSING")

    def test_render_markdown_includes_blocking_market_table(self):
        payload = {
            "generated_at_utc": "2026-06-20T00:00:00+00:00",
            "status": "BLOCK",
            "reanalysis_root": "data/reanalysis",
            "target_start": "2026-06-07",
            "target_end": "2026-06-13",
            "required_groups": ["pressure_level"],
            "summary": {
                "markets": 1,
                "blocking_markets": 1,
                "feature_groups": [{"name": "pressure_level", "label": "Pressure", "columns": ["x"]}],
            },
            "markets": [
                {
                    "market_id": "nyc",
                    "rows": 2,
                    "target_rows": 2,
                    "status": "BLOCK",
                    "blockers": ["pressure_level:MISSING"],
                    "path": "sidecar.csv",
                    "groups": {
                        "rich_surface": {"last_complete_date": "2026-06-08"},
                        "pressure_level": {"last_complete_date": "2026-03-17"},
                    },
                    "target_window_groups": {
                        "core_antecedent": {"status": "PASS", "coverage": 1.0},
                        "rich_surface": {"status": "PASS", "coverage": 1.0},
                        "pressure_level": {"status": "MISSING", "coverage": 0.0},
                        "teleconnection": {"status": "PASS", "coverage": 1.0},
                    },
                }
            ],
        }

        text = render_markdown(payload)

        self.assertIn("Reanalysis Sidecar Coverage Audit", text)
        self.assertIn("Target Window Coverage", text)
        self.assertIn("pressure_level:MISSING", text)


if __name__ == "__main__":
    unittest.main()
