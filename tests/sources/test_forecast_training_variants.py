import csv
from pathlib import Path

import pytest

from weather.market.market_registry import NYC
from weather.sources.forecast_history import (
    DAILY_ISSUE_COLUMNS,
    RICH_FORECAST_COLUMNS,
    daily_issue_rows,
    historical_forecast_rows,
    previous_run_rows,
    write_csv,
)
from weather.sources.forecast_training_variants import (
    ForecastTrainingVariantError,
    ForecastTrainingVariantResolver,
)


def _write_history_root(tmp_path: Path) -> Path:
    market_root = tmp_path / "forecast_history" / NYC.icao.lower()
    market_root.mkdir(parents=True)
    times = [f"2025-07-17T{hour:02d}:00" for hour in range(24)]
    payload = {
        "hourly": {
            "time": times,
            "temperature_2m": [90.0] * 24,
            "cloud_cover": [25.0] * 24,
            "temperature_2m_previous_day1": [80.0] * 23 + [82.0],
            "temperature_2m_previous_day2": [79.0] * 24,
        }
    }
    rich = historical_forecast_rows(payload, NYC)
    pit = previous_run_rows(payload, NYC, leads=(1, 2))
    write_csv(market_root / "forecast_long.csv", RICH_FORECAST_COLUMNS, rich + pit)
    write_csv(
        market_root / "forecast_daily_by_issue.csv",
        DAILY_ISSUE_COLUMNS,
        daily_issue_rows(rich + pit),
    )
    with (market_root / "forecast_daily.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_date", "forecast_high_c"])
        writer.writerow(["2025-07-17", "90.0"])
    return tmp_path / "forecast_history"


def test_forecast_training_variants_keep_high_and_profile_sources_distinct(tmp_path):
    root = _write_history_root(tmp_path)

    honest = ForecastTrainingVariantResolver(root, NYC, variant="honest")
    rich = ForecastTrainingVariantResolver(root, NYC, variant="rich")
    hybrid = ForecastTrainingVariantResolver(root, NYC, variant="hybrid")

    honest_row = honest.resolve("2025-07-17", 9)
    rich_row = rich.resolve("2025-07-17", 9)
    hybrid_row = hybrid.resolve("2025-07-17", 9)

    assert honest_row["forecast_high"] == 82.0
    assert honest_row["profile_rows"] is None
    assert honest_row["provenance"]["uses_settled_forecast_high"] is False
    assert rich_row["forecast_high"] == 90.0
    assert rich_row["profile_rows"][0]["cloud_cover"] == 25.0
    assert rich_row["provenance"]["uses_settled_forecast_high"] is True
    assert hybrid_row["forecast_high"] == 82.0
    assert hybrid_row["profile_rows"][0]["cloud_cover"] == 25.0
    assert hybrid_row["provenance"]["profile_source"] == "open_meteo_historical_forecast"
    assert honest.target_dates == rich.target_dates == hybrid.target_dates == {
        "2025-07-17"
    }
    assert set(hybrid.file_receipt) == {"pit_daily_by_issue", "rich_profiles"}


def test_honest_variant_selects_the_declared_lead(tmp_path):
    root = _write_history_root(tmp_path)

    resolver = ForecastTrainingVariantResolver(
        root,
        NYC,
        variant="honest",
        pit_lead_days=2,
    )

    assert resolver.resolve("2025-07-17", 7)["forecast_high"] == 79.0
    assert resolver.resolve("2025-07-17", 7)["provenance"]["pit_lead_days"] == 2


def test_honest_variant_rejects_duplicate_market_day_lead(tmp_path):
    root = _write_history_root(tmp_path)
    path = root / NYC.icao.lower() / "forecast_daily_by_issue.csv"
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    duplicate = next(row for row in rows if row["lead_days"] == "1")
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_ISSUE_COLUMNS)
        writer.writerow(duplicate)

    with pytest.raises(ForecastTrainingVariantError, match="duplicate PIT"):
        ForecastTrainingVariantResolver(root, NYC, variant="honest")
