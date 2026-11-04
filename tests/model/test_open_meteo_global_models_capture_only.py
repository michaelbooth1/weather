"""Open-Meteo global models: the AIFS rename is captured, never served (master ruling 2026-10-30).

Open-Meteo renamed the AIFS id (ecmwf_aifs025 now returns an all-null column; the
current id is ecmwf_aifs025_single) and stopped serving gfs_graphcast025. The fix is
capture-only and record-first: the new id is requested in addition and stored under
``capture_only_models``; GraphCast is no longer requested but still parsed when a
response carries it. ``_reference_v1_fetch`` below is a verbatim, frozen copy of the
parser before the change (origin/master 1a78e1ba0), so every case replays the same
provider response through the old and the new parser.

Guards: train/serve feature parity and probability mass (AGENTS.md) - for any
  provider response, the served payload keys, every live feature and the estimated
  distribution are byte-identical to the v1 parser; the capture-only member never
  reaches day_model_highs, day_max_native, rows or the served features.
"""
import json
import statistics
from datetime import datetime

import pytest

from weather.model import model_sources
from weather.model.toronto_model import TorontoHighTempModel
from weather.time import provider_hourly_local_times

_V1_MEMBERS = ("ecmwf_ifs025", "ecmwf_aifs025", "ncep_aigfs025", "gfs_graphcast025")
ADDED_KEYS = {"capture_only_models", "retired_model_members"}


# Frozen copy of the v1 parser. Do not edit: it is the parity reference.
def _reference_v1_fetch(self):
    url = "https://api.open-meteo.com/v1/forecast"
    payload = self.get_json(url, {
        "latitude": self.spec.lat,
        "longitude": self.spec.lon,
        "hourly": "temperature_2m",
        "temperature_unit": self.spec.om_temperature_unit,
        "timezone": self.spec.timezone,
        "forecast_days": 2,
        "models": ",".join(_V1_MEMBERS),
    })
    hourly = payload.get("hourly", {}) or {}
    rows = []
    day_rows = []
    model_day_temps = {model: [] for model in _V1_MEMBERS}
    now = datetime.now(self.spec.tz)
    # Aware market-local valid times: Open-Meteo labels carry one fixed
    # response offset, so they are read as UTC instants (DST-safe).
    local_times = provider_hourly_local_times(
        hourly.get("time", []) or [],
        self.spec.tz,
        payload.get("utc_offset_seconds"),
    )
    for index, dt in enumerate(local_times):
        if dt is None or dt.date() != self.target_date:
            continue
        model_payloads = {}
        model_temps = []
        for model in _V1_MEMBERS:
            value = self.to_number(self.array_get(hourly, f"temperature_2m_{model}", index))
            values = {"temp_native": value, "temp_c": value}
            if value is not None:
                model_temps.append(value)
                model_day_temps[model].append(value)
            model_payloads[model] = values
        row = {
            "time": dt.strftime("%H:%M"),
            "valid_time": dt.isoformat(),
            "models": model_payloads,
            "model_temp_spread": max(model_temps) - min(model_temps) if len(model_temps) >= 2 else None,
        }
        day_rows.append(row)
        if dt < now:
            continue
        rows.append(row)
    day_model_highs = {
        model: max(values) if values else None
        for model, values in model_day_temps.items()
    }
    high_values = [value for value in day_model_highs.values() if value is not None]
    day_max_native = statistics.median(high_values) if high_values else None
    return {
        "available": True,
        "url": url,
        "rows": rows[:12],
        "day_rows": day_rows,
        "day_model_highs": day_model_highs,
        "day_max_native": day_max_native,
        "day_max_c": day_max_native,
        "day_high_spread": max(high_values) - min(high_values) if len(high_values) >= 2 else None,
        "row_count": len(day_rows),
        "payload_hash": self.payload_hash(payload),
        "model_members": list(_V1_MEMBERS),
        "model_run_age_hours": None,
        "model_run_age_status": "not_exposed_by_open_meteo_forecast",
        "run_to_run_high_change": None,
        "run_to_run_change_status": "requires_previous_run_archive",
        "historical_archive_available": False,
        "live_only_fields": [
            "open_meteo_global_models_high_spread",
            "open_meteo_ecmwf_ifs_high_delta",
            "open_meteo_ecmwf_aifs_high_delta",
            "open_meteo_ncep_aigfs_high_delta",
            "open_meteo_gfs_graphcast_high_delta",
            "open_meteo_ecmwf_ifs_aifs_disagreement",
            "open_meteo_global_models_next_3h_spread",
            "open_meteo_global_models_run_to_run_high_change",
        ],
        "generation_time_ms": payload.get("generationtime_ms"),
        "raw_payload": payload,
    }



TIMES = ["2026-05-30T%02d:00" % hour for hour in range(24)]


def _series(base, *, null=False):
    return [None if null else round(base + 6.0 * (1 - abs(hour - 15) / 15.0), 1) for hour in range(24)]


# Provider responses: the request the new code makes today (aifs null, no
# graphcast column, aifs_single present), the v1 request today (graphcast null
# column), a historical response with every member live, an outlier capture-only
# value, partial nulls and an empty response.
RESPONSES = {
    "today_new_request": {
        "temperature_2m_ecmwf_ifs025": _series(20.0),
        "temperature_2m_ecmwf_aifs025": _series(0, null=True),
        "temperature_2m_ncep_aigfs025": _series(19.0),
        "temperature_2m_ecmwf_aifs025_single": _series(21.5),
    },
    "today_v1_request": {
        "temperature_2m_ecmwf_ifs025": _series(20.0),
        "temperature_2m_ecmwf_aifs025": _series(0, null=True),
        "temperature_2m_ncep_aigfs025": _series(19.0),
        "temperature_2m_gfs_graphcast025": _series(0, null=True),
    },
    "historical_all_live": {
        "temperature_2m_ecmwf_ifs025": _series(20.0),
        "temperature_2m_ecmwf_aifs025": _series(22.0),
        "temperature_2m_ncep_aigfs025": _series(19.0),
        "temperature_2m_gfs_graphcast025": _series(23.0),
        "temperature_2m_ecmwf_aifs025_single": _series(22.0),
    },
    "capture_only_outlier": {
        "temperature_2m_ecmwf_ifs025": _series(20.0),
        "temperature_2m_ncep_aigfs025": _series(19.0),
        "temperature_2m_ecmwf_aifs025_single": _series(45.0),
    },
    "partial_nulls": {
        "temperature_2m_ecmwf_ifs025": _series(20.0)[:12] + [None] * 12,
        "temperature_2m_ecmwf_aifs025_single": [None] * 12 + _series(21.0)[12:],
    },
    "empty": {},
}


def _model():
    return TorontoHighTempModel(target_date="2026-05-30")


def _parse(parser, hourly):
    model = _model()
    payload = {"generationtime_ms": 1.0, "hourly": {"time": list(TIMES), **hourly}} if hourly else {}
    model.get_json = lambda url, params: json.loads(json.dumps(payload))
    return parser(model)


def _canonical(value):
    return json.dumps(value, sort_keys=True, default=str).encode("utf-8")


def _sources(global_data):
    rows = [{"time": "07:00", "temp_c": 18.0, "temp_native": 18.0},
            {"time": "12:00", "temp_c": 22.0, "temp_native": 22.0}]
    return {
        "wu_history": {"ok": True, "data": {"rows": rows}},
        "wu_current": {"ok": True, "data": {"temp_c": 22.0}},
        "open_meteo": {"ok": True, "data": {"rows": [], "day_max_c": 25.0}},
        "open_meteo_global_models": {"ok": True, "data": global_data},
    }


@pytest.mark.parametrize("case", sorted(RESPONSES))
def test_served_payload_is_byte_identical_to_the_v1_parser(case):
    old = _parse(_reference_v1_fetch, RESPONSES[case])
    new = _parse(type(_model()).fetch_open_meteo_global_models, RESPONSES[case])

    assert set(new) - set(old) == ADDED_KEYS
    assert _canonical({k: v for k, v in new.items() if k not in ADDED_KEYS}) == _canonical(old)
    assert new["retired_model_members"] == ["gfs_graphcast025"]
    assert new["capture_only_models"]["status"] == "capture_only_not_served"


@pytest.mark.parametrize("case", sorted(RESPONSES))
def test_served_features_and_distribution_are_byte_identical(case):
    old = _parse(_reference_v1_fetch, RESPONSES[case])
    new = _parse(type(_model()).fetch_open_meteo_global_models, RESPONSES[case])
    now = datetime(2026, 5, 30, 12, 30, tzinfo=_model().spec.tz)

    old_features = _model().extract_live_features(_sources(old), cutoff_hour=12, now=now)
    new_features = _model().extract_live_features(_sources(new), cutoff_hour=12, now=now)
    assert _canonical(new_features) == _canonical(old_features)

    old_distribution = _model().estimate_distribution(_sources(old), now=now)
    new_distribution = _model().estimate_distribution(_sources(new), now=now)
    assert _canonical(new_distribution) == _canonical(old_distribution)


def test_distribution_comparison_is_not_vacuous():
    # Control: serving the capture-only AIFS high through day_max_native (what
    # the rejected first version did) must move the distribution.
    new = _parse(type(_model()).fetch_open_meteo_global_models, RESPONSES["capture_only_outlier"])
    leaked_high = new["capture_only_models"]["day_model_highs"]["ecmwf_aifs025_single"]
    leaked = dict(new, day_max_native=leaked_high, day_max_c=leaked_high)
    now = datetime(2026, 5, 30, 12, 30, tzinfo=_model().spec.tz)

    served = _model().estimate_distribution(_sources(new), now=now)
    assert _canonical(_model().estimate_distribution(_sources(leaked), now=now)) != _canonical(served)


def test_capture_only_member_is_recorded_and_requested_without_graphcast():
    captured = {}
    model = _model()

    def fake_get_json(url, params):
        captured.update(params)
        return {"hourly": {"time": list(TIMES), **RESPONSES["today_new_request"]}}

    model.get_json = fake_get_json
    data = model.fetch_open_meteo_global_models()

    assert captured["models"].split(",") == [
        "ecmwf_ifs025", "ecmwf_aifs025", "ncep_aigfs025", "ecmwf_aifs025_single"]
    assert data["day_model_highs"]["ecmwf_aifs025"] is None
    assert data["day_model_highs"]["gfs_graphcast025"] is None
    assert "ecmwf_aifs025_single" not in data["day_model_highs"]
    assert all("ecmwf_aifs025_single" not in row["models"] for row in data["day_rows"])
    captured_only = data["capture_only_models"]
    assert captured_only["day_model_highs"] == {"ecmwf_aifs025_single": max(RESPONSES["today_new_request"][
        "temperature_2m_ecmwf_aifs025_single"])}
    assert len(captured_only["day_rows"]) == 24
    assert model_sources.SOURCE_PAYLOAD_CONTRACTS["open_meteo_global_models"][0] == (
        "open-meteo-global-models-parser-v2")
