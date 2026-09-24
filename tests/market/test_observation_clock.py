from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import csv
import json

import pytest

from weather.market.observation_clock import (
    Observation, RemainingRiseEstimator, band_dead, clock_table, day_grid,
    historical_dead_probability, hourly_rule_minute, STATION_ROUTINE_MINUTES,
)
from weather.market.market_registry import spec_for_id
from weather.sources.metar_history import normalize_csv
from weather.units import c_to_native


def obs(hour, minute, temp, kind="routine", day="2026-06-01", offset="+00:00"):
    return Observation(datetime.fromisoformat(f"{day}T{hour:02}:{minute:02}:00{offset}"), temp, kind)


@pytest.mark.parametrize("station,minute,expected", [
    ("KLGA", 50, False), ("KLGA", 51, True), ("KLGA", 59, True),
    ("KLGA", 0, False), ("CYYZ", 55, False), ("CYYZ", 56, True),
    ("CYYZ", 4, True), ("CYYZ", 5, False), ("CYYZ", 30, False),
])
def test_hourly_minute_contract(station, minute, expected):
    assert hourly_rule_minute(station, minute) is expected


def test_clock_uses_typed_reports_and_native_change_bins():
    rows = [obs(0, 51, 20), obs(1, 1, 22, "special"), obs(5, 5, 24, "special"),
            obs(5, 51, None), obs(6, 1, 20, "special")]
    clock = clock_table(rows + rows[:1], "UTC")
    assert clock["routine_count"] == 2
    assert clock["routine_minutes"] == {51: 2}
    assert clock["special_changes"] == {"2to4": 1, "unknown": 2}
    assert clock["availability_lag_seconds"] is None


def test_grid_is_as_of_no_yesterday_or_future_and_keeps_missing_prefix():
    rows = [obs(23, 51, 99, day="2026-05-31"), obs(0, 16, 10), obs(1, 0, 12)]
    summary, grid = day_grid(rows, "KLGA", "UTC", date(2026, 6, 1))
    assert summary["final_degree"] == 12
    assert not summary["complete_hours"]
    assert grid[1]["running_max"] is None  # 00:15, future :16 withheld
    assert grid[2]["running_max"] == 10
    assert grid[4]["running_max"] == 12   # inclusive exact cutoff
    assert grid[4]["decided"] == 1


def test_rule_maxima_can_differ_and_degree_is_not_exact_temperature():
    rows = [obs(0, 51, 20.1), obs(1, 17, 21.1, "special"), obs(1, 51, 20.4)]
    a, ag = day_grid(rows, "KLGA", "UTC", date(2026, 6, 1))
    h, hg = day_grid(rows, "KLGA", "UTC", date(2026, 6, 1), hourly=True)
    assert (a["final_degree"], h["final_degree"]) == (21, 20)
    assert (hg[4]["decided"], hg[4]["decided_exact"]) == (1, 0)
    assert ag[4]["decided"] == 0


def test_local_date_and_half_hour_toronto():
    rows = [obs(3, 59, 99), obs(4, 0, 20), obs(4, 30, 21)]
    a, _ = day_grid(rows, "CYYZ", "America/Toronto", date(2026, 6, 1))
    h, _ = day_grid(rows, "CYYZ", "America/Toronto", date(2026, 6, 1), hourly=True)
    assert (a["final_degree"], h["final_degree"]) == (21, 20)


def test_missing_or_nonfinite_is_not_a_temperature():
    with pytest.raises(ValueError):
        Observation(datetime(2026, 6, 1), 20, "routine")
    with pytest.raises(ValueError):
        obs(1, 1, float("nan"))
    summary, grid = day_grid([obs(1, 1, None)], "KLGA", "UTC", date(2026, 6, 1))
    assert summary["final_max"] is None
    assert all(row["decided"] is None for row in grid)
    with pytest.raises(ValueError, match="DST"):
        day_grid([], "KLGA", "America/New_York", date(2026, 11, 1))


def training_day(day, warm):
    rows = [obs(h, 0, 20 + (warm and h >= 12), day=day) for h in range(24)]
    return day_grid(rows, "CYYZ", "UTC", date.fromisoformat(day))


def test_estimator_holdout_purity_and_probability_mass():
    days = [training_day("2026-06-01", False), training_day("2026-06-02", True)]
    model = RemainingRiseEstimator.fit(days, before=date(2026, 6, 3), minimum_days=2)
    result = model.predict(600, 20, target_date=date(2026, 6, 3), band_upper=20)
    assert result == {"n": 2, "p_decided": .5, "p_final_above": .5, "dead": 0}
    assert model.predict(600, 21, target_date=date(2026, 6, 3), band_upper=20)["p_final_above"] == 1
    assert model.predict(600, None, target_date=date(2026, 6, 3))["p_decided"] is None
    with pytest.raises(ValueError, match="holdout"):
        RemainingRiseEstimator.fit(days, before=date(2026, 6, 2))
    with pytest.raises(ValueError, match="duplicate"):
        RemainingRiseEstimator.fit(days + days[:1], before=date(2026, 6, 3))
    with pytest.raises(ValueError, match="held out"):
        model.predict(600, 20, target_date=date(2026, 6, 2))


def test_insufficient_or_incomplete_training_is_unknown():
    day = training_day("2026-06-01", False)
    day[0]["complete_hours"] = False
    model = RemainingRiseEstimator.fit([day], before=date(2026, 6, 2), minimum_days=1)
    assert model.predict(600, 20, target_date=date(2026, 6, 2))["p_decided"] is None


def test_band_upper_is_inclusive_and_open_tail_never_dead():
    assert band_dead(20, 20) == 0
    assert band_dead(21, 20) == 1
    assert band_dead(21, None) == 0
    assert band_dead(None, 20) is None
    assert historical_dead_probability({20: 3, 21: 1}, 20) == .25
    assert historical_dead_probability({}, 20) is None
    assert historical_dead_probability({20: 3}, None) == 0


def load_tool():
    path = Path(__file__).resolve().parents[2] / "tools/observation_clock_20260923.py"
    spec = importlib.util.spec_from_file_location("clock_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_native_values_match_existing_adapter():
    path = Path(__file__).resolve().parents[1] / "fixtures/observation_clock_reports.csv"
    for market, station in (("nyc", "LGA"), ("toronto", "CYYZ")):
        spec = spec_for_id(market)
        text = path.read_text()
        raw = [r for r in csv.DictReader(text.splitlines()) if r["station"] == station]
        normalized = normalize_csv("\n".join([text.splitlines()[0]] +
            [line for line in text.splitlines()[1:] if line.startswith(station + ",")]), spec)
        assert len(normalized) == len(raw)
        assert [r["temp_native"] for r in normalized] == [
            round(c_to_native(float(r["tmpc"]), spec.unit), 3) for r in raw]


def test_deadline_and_sentinel_and_endpoint_guard(tmp_path, monkeypatch):
    tool = load_tool()
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    tool.network_allowed(tool.CUTOFF - timedelta(seconds=1))
    with pytest.raises(RuntimeError, match="deadline"):
        tool.network_allowed(tool.CUTOFF)
    (tmp_path / "STOP").touch()
    with pytest.raises(RuntimeError, match="STOP"):
        tool.network_allowed(tool.CUTOFF - timedelta(seconds=1))
    with pytest.raises(ValueError, match="only"):
        tool.Cache().get("https://example.invalid", {})


def test_cached_integrity_and_no_venue_reuse(tmp_path, monkeypatch):
    tool = load_tool()
    source, dest = tmp_path / "source", tmp_path / "dest"
    (source / "cache").mkdir(parents=True)
    for key, url in (("weather", tool.IEM_ASOS_URL), ("excluded", "https://example.invalid/venue")):
        body = source / "cache" / f"{key}.body"
        body.write_bytes(b"station,valid,tmpc,metar\n")
        tool.dump(body.with_suffix(".json"), {"url": url, "status": 200, "sha256": tool.sha(body.read_bytes())})
    monkeypatch.setattr(tool, "ROOT", dest)
    tool.reuse(source)
    assert (dest / "cache/weather.body").exists()
    assert not (dest / "cache/excluded.body").exists()
    (dest / "cache/weather.body").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        list(tool.cache_metadata(dest))


def test_crossed_ci_does_not_treat_quarters_as_independent():
    tool = load_tool()
    rows = [{"market": m, "date": d, "value": float(d == "a")}
            for m in ("x", "y") for d in ("a", "b")]
    result = tool.crossed_summary(rows, "value")
    assert result["n"] == 4
    assert (result["dates"], result["markets"], result["mean"]) == (2, 2, .5)
    assert result["low"] == 0 and result["high"] == 1


def test_station_table_and_same_time_revision_handling(tmp_path, monkeypatch):
    tool = load_tool()
    spec = spec_for_id("nyc")
    assert STATION_ROUTINE_MINUTES["KLGA"] == (51,)
    assert STATION_ROUTINE_MINUTES["CYYZ"] == (0,)
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "SPECS", [spec])
    body = b"station,valid,tmpc,metar\nLGA,2026-06-01 04:51,20,x\nLGA,2026-06-01 04:51,21,y\n"
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache/typed.body").write_bytes(body)
    tool.dump(tmp_path / "cache/typed.json", {"url": tool.IEM_ASOS_URL + "?data=metar&report_type=3",
                                            "status": 200, "sha256": tool.sha(body)})
    typed, _, _, conflicts, _, ambiguous = tool.read_observations()
    assert len(typed["nyc"]) == 1
    assert next(iter(typed["nyc"].values())).temperature is None
    assert conflicts["routine_temperature_revision"] == 1
    assert ("routine", "nyc", date(2026, 6, 1)) in ambiguous
