import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.reanalysis_sidecar_coverage_audit import (
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
