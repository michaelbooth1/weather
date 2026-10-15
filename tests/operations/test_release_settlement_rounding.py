import json

import pytest

from weather.operations.release_candidate_contract import (
    DEFAULT_SETTLEMENT_ROUNDING,
    CandidateContractError,
    _settlement_rules,
    settlement_band_degree,
    settlement_rounding,
)
from weather.paths import CONFIG_ROOT

# Resolved Hong Kong market-days 2026-09-20..29: HKO Absolute Daily Max and the venue's
# winning band (docs/research/foreign-settlement-desk-study-2026-10.md).
HONG_KONG_RESOLVED = [
    ("2026-09-20", 33.1, 33),
    ("2026-09-21", 33.0, 33),
    ("2026-09-22", 30.2, 30),
    ("2026-09-23", 31.9, 31),
    ("2026-09-24", 32.2, 32),
    ("2026-09-25", 32.5, 32),
    ("2026-09-26", 32.1, 32),
    ("2026-09-27", 32.7, 32),
    ("2026-09-28", 32.5, 32),
    ("2026-09-29", 33.1, 33),
]
WRH_STATIONS = {"london": "EGLC", "paris": "LFPB", "seoul": "RKSI", "shanghai": "ZSPD", "tokyo": "RJTT"}


def _checked_in_locations() -> dict:
    return json.loads((CONFIG_ROOT / "locations.json").read_text(encoding="utf-8"))


def _location(locations: dict, location_id: str) -> dict:
    return next(row for row in locations["locations"] if row["id"] == location_id)


@pytest.mark.parametrize(("local_date", "hko_max", "venue_band"), HONG_KONG_RESOLVED)
def test_hong_kong_floor_rule_reproduces_every_resolved_venue_band(local_date, hko_max, venue_band):
    assert settlement_band_degree(hko_max, "whole_degree_floor") == venue_band


def test_half_up_would_have_mislabelled_four_resolved_hong_kong_days():
    mislabelled = [
        local_date
        for local_date, hko_max, venue_band in HONG_KONG_RESOLVED
        if settlement_band_degree(hko_max, DEFAULT_SETTLEMENT_ROUNDING) != venue_band
    ]
    assert mislabelled == ["2026-09-23", "2026-09-25", "2026-09-27", "2026-09-28"]


def test_settlement_band_degree_keeps_half_up_default_and_missing_values():
    assert settlement_band_degree(32.5, DEFAULT_SETTLEMENT_ROUNDING) == 33
    assert settlement_band_degree(-0.5, DEFAULT_SETTLEMENT_ROUNDING) == 0
    assert settlement_band_degree(-0.1, "whole_degree_floor") == -1
    assert settlement_band_degree(None, "whole_degree_floor") is None
    with pytest.raises(CandidateContractError, match="unsupported settlement rounding"):
        settlement_band_degree(31.9, "whole_degree_ceiling")


def test_settlement_rounding_fails_closed_on_undeclared_or_unknown_band_mapping():
    assert settlement_rounding({"precision": "whole_degree"}) == DEFAULT_SETTLEMENT_ROUNDING
    assert (
        settlement_rounding({"precision": "tenth_degree", "band_mapping": "floor_to_whole_degree"})
        == "whole_degree_floor"
    )
    with pytest.raises(CandidateContractError, match="requires a declared band_mapping"):
        settlement_rounding({"precision": "tenth_degree"})
    with pytest.raises(CandidateContractError, match="unsupported settlement band_mapping"):
        settlement_rounding({"precision": "tenth_degree", "band_mapping": "nearest"})


def test_release_settlement_rules_declare_hong_kong_floor_and_half_up_elsewhere():
    payload = _settlement_rules(_checked_in_locations())

    band_contract = payload["band_contract"]
    assert band_contract["rounding"] == DEFAULT_SETTLEMENT_ROUNDING
    assert band_contract["location_rounding_overrides"] == {"hong-kong": "whole_degree_floor"}
    rows = {row["location_id"]: row for row in payload["locations"]}
    assert rows["hong-kong"]["rounding"] == "whole_degree_floor"
    assert rows["hong-kong"]["precision"] == "tenth_degree"
    assert all(
        row["rounding"] == DEFAULT_SETTLEMENT_ROUNDING
        for location_id, row in rows.items()
        if location_id != "hong-kong"
    )


def test_foreign_wrh_cities_resolve_on_wrh_timeseries_with_wu_fallback():
    locations = _checked_in_locations()
    for location_id, icao in WRH_STATIONS.items():
        settlement = _location(locations, location_id)["settlement"]
        assert settlement["source_type"] == "nws_wrh_timeseries"
        assert settlement["station_id"] == icao
        assert settlement["resolution_source_url"] == (
            f"https://www.weather.gov/wrh/timeseries?site={icao.lower()}"
        )
        assert settlement["resolution_view"] == "all_times_temp_column_metric"
        assert settlement["fallback_source_type"] == "wunderground_history"
        assert settlement["fallback_source_url"].startswith("https://www.wunderground.com/history/daily/")
        assert settlement["fallback_source_url"].endswith(f"/{icao}")
        assert settlement["precision"] == "whole_degree"


def test_hong_kong_settles_on_the_hko_daily_extract_at_tenth_degree_precision():
    settlement = _location(_checked_in_locations(), "hong-kong")["settlement"]

    assert settlement["source_type"] == "hong_kong_observatory_daily_extract"
    assert settlement["resolution_view"] == "daily_extract_absolute_daily_max"
    assert settlement["precision"] == "tenth_degree"
    assert settlement["band_mapping"] == "floor_to_whole_degree"
    assert settlement["finality"] == "initial_publication"
