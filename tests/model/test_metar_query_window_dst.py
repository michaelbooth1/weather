"""The AWC METAR look-back covers the whole local target day on DST days.

``metar_query_hours`` used to subtract two datetimes sharing one ``tzinfo``,
which Python does on the wall clock. On the 25-hour fall-back day that
under-counted the elapsed span by an hour, so a fetch late in the day requested
24 hours and lost the first local hour's reports. These tests drive the
production fetcher (``fetch_metar`` -> ``metar_query_hours`` ->
``parse_metar_payload``) with a fake AWC server that honours ``hours``.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import weather.model.model_sources as model_sources
from weather.model.model_sources import METAR_QUERY_HOURS_CAP
from weather.model.toronto_model import TorontoHighTempModel

# market_id -> (timezone family, spring-forward day, fall-back day)
DST_MARKETS = {
    "nyc": ("Eastern", "2027-03-14", "2026-11-01"),
    "chicago": ("Central", "2027-03-14", "2026-11-01"),
    "denver": ("Mountain", "2027-03-14", "2026-11-01"),
    "los-angeles": ("Pacific", "2027-03-14", "2026-11-01"),
    "toronto": ("Eastern (Canada)", "2027-03-14", "2026-11-01"),
}
NORMAL_DAY = "2026-10-04"


def _model(market_id, target_date):
    return TorontoHighTempModel(target_date=target_date, market_id=market_id)


def _local_midnight_utc(model, day):
    return datetime(day.year, day.month, day.day, tzinfo=model.spec.tz).astimezone(timezone.utc)


def _day_bounds_utc(model):
    start = _local_midnight_utc(model, model.target_date)
    end = _local_midnight_utc(model, model.target_date + timedelta(days=1))
    return start, end


def _legacy_hours(model, now):
    """The pre-fix formula, kept verbatim to pin normal-day behaviour."""

    now = now.astimezone(model.spec.tz)
    if now.date() != model.target_date:
        return 24
    start = datetime(
        model.target_date.year, model.target_date.month, model.target_date.day, tzinfo=model.spec.tz
    )
    elapsed_seconds = max(0.0, (now - start).total_seconds())
    return max(1, min(24, int(elapsed_seconds // 3600) + 2))


def _instants(model, step_minutes=5):
    start, end = _day_bounds_utc(model)
    current = start
    while current < end:
        yield current
        current += timedelta(minutes=step_minutes)


def _hourly_awc_payload(model, *, speci_minute=10):
    """One routine METAR at :51 of every true hour of the local day, plus a
    SPECI and a COR inside the first local hour, newest first like AWC."""

    start, end = _day_bounds_utc(model)
    rows = []
    instant = start + timedelta(minutes=51)
    while instant < end:
        rows.append(_awc_row(model, instant, instant.replace(minute=0) + timedelta(hours=1), 10.0))
        instant += timedelta(hours=1)
    speci = start + timedelta(minutes=speci_minute)
    rows.append(_awc_row(model, speci, speci, 9.0, metar_type="SPECI"))
    first = start + timedelta(minutes=51)
    rows.append(
        _awc_row(model, first, first.replace(minute=0) + timedelta(hours=1), 9.5, raw_suffix="COR")
    )
    rows.sort(key=lambda row: row["obsTime"], reverse=True)
    return rows


def _awc_row(model, obs_utc, report_utc, temp_c, *, metar_type="METAR", raw_suffix=""):
    stamp = obs_utc.strftime("%d%H%MZ")
    return {
        "icaoId": model.spec.icao,
        "obsTime": int(obs_utc.timestamp()),
        "reportTime": report_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "metarType": metar_type,
        "temp": temp_c,
        "dewp": 5.0,
        "wdir": 90,
        "wspd": 5,
        "rawOb": f"{metar_type} {model.spec.icao} {stamp} {raw_suffix}".strip(),
    }


class _FakeAwc:
    """Returns rows whose observation lies inside the requested look-back."""

    def __init__(self, payload, now_utc):
        self.payload = payload
        self.now_utc = now_utc
        self.requests = []

    def __call__(self, url, params):
        self.requests.append((url, dict(params)))
        oldest = self.now_utc.timestamp() - float(params["hours"]) * 3600
        return [
            row
            for row in self.payload
            if oldest <= row["obsTime"] <= self.now_utc.timestamp()
        ]


def _freeze_now(monkeypatch, now_utc):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz is not None else now_utc.replace(tzinfo=None)

    monkeypatch.setattr(model_sources, "datetime", _Frozen)


def _fetch_at(monkeypatch, model, now_utc):
    awc = _FakeAwc(_hourly_awc_payload(model), now_utc)
    model.get_json = awc
    _freeze_now(monkeypatch, now_utc)
    data = model.fetch_metar()
    return data, awc


@pytest.mark.parametrize("market_id", sorted(DST_MARKETS))
def test_fall_back_day_late_fetch_keeps_first_local_hour(monkeypatch, market_id):
    model = _model(market_id, DST_MARKETS[market_id][2])
    start, end = _day_bounds_utc(model)
    assert (end - start) == timedelta(hours=25)
    now_utc = end - timedelta(minutes=5)  # 23:55 local, standard time

    assert _legacy_hours(model, now_utc) == 24  # the defect: 24 h from 23:55 starts at 00:55 local
    data, awc = _fetch_at(monkeypatch, model, now_utc)

    assert len(awc.requests) == 1
    url, params = awc.requests[0]
    assert url == "https://aviationweather.gov/api/data/metar"
    assert params == {"ids": model.spec.icao, "format": "json", "hours": 25}
    _assert_whole_day_fetched_and_first_hour_parsed(model, data, routine_reports=25)


def _first_hour_raws(model):
    start, _ = _day_bounds_utc(model)
    return {
        row["rawOb"]
        for row in _hourly_awc_payload(model)
        if row["obsTime"] < (start + timedelta(hours=1)).timestamp()
    }


def _assert_whole_day_fetched_and_first_hour_parsed(model, data, *, routine_reports):
    # The look-back returned every report of the local day (keying-independent).
    assert data["raw_payload"] == _hourly_awc_payload(model)
    fetched = [row["rawOb"] for row in data["raw_payload"]]
    assert sum(1 for raw in fetched if raw.startswith("METAR") and not raw.endswith("COR")) == routine_reports
    # The routine 00:51 report, its COR and the 00:10 SPECI reach the parsed rows
    # as three distinct rows: nothing is merged away.
    first_hour = _first_hour_raws(model)
    assert len(first_hour) == 3
    assert any(raw.startswith("SPECI") for raw in first_hour)
    assert any(raw.endswith("COR") for raw in first_hour)
    parsed = [row["raw"] for row in data["rows"]]
    assert first_hour <= set(parsed)
    assert len(parsed) == len(set(parsed))


@pytest.mark.parametrize("market_id", sorted(DST_MARKETS))
@pytest.mark.parametrize("which", ["spring", "fall"])
def test_dst_day_window_always_reaches_local_midnight_and_stays_bounded(market_id, which):
    target = DST_MARKETS[market_id][1 if which == "spring" else 2]
    model = _model(market_id, target)
    start, end = _day_bounds_utc(model)
    expected_hours = 23 if which == "spring" else 25
    assert (end - start) == timedelta(hours=expected_hours)
    for now_utc in _instants(model):
        hours = model.metar_query_hours(now=now_utc)
        assert 1 <= hours <= METAR_QUERY_HOURS_CAP
        assert hours <= max(24, expected_hours)
        assert now_utc - timedelta(hours=hours) <= start, (market_id, which, now_utc, hours)


@pytest.mark.parametrize("market_id", sorted(DST_MARKETS))
def test_spring_forward_day_late_fetch_keeps_first_local_hour(monkeypatch, market_id):
    model = _model(market_id, DST_MARKETS[market_id][1])
    _, end = _day_bounds_utc(model)
    now_utc = end - timedelta(minutes=5)
    data, awc = _fetch_at(monkeypatch, model, now_utc)

    assert len(awc.requests) == 1
    assert awc.requests[0][1]["hours"] == 24
    _assert_whole_day_fetched_and_first_hour_parsed(model, data, routine_reports=23)


@pytest.mark.parametrize("market_id", sorted(DST_MARKETS))
def test_normal_day_requests_exactly_what_it_always_did(monkeypatch, market_id):
    model = _model(market_id, NORMAL_DAY)
    start, end = _day_bounds_utc(model)
    assert (end - start) == timedelta(hours=24)
    for now_utc in _instants(model, step_minutes=7):
        assert model.metar_query_hours(now=now_utc) == _legacy_hours(model, now_utc)

    # And through the production fetcher, the request itself is unchanged.
    now_utc = start + timedelta(hours=13, minutes=20)
    _, awc = _fetch_at(monkeypatch, model, now_utc)
    assert awc.requests[0][1] == {"ids": model.spec.icao, "format": "json", "hours": 15}


def test_non_target_day_keeps_the_24_hour_request():
    model = _model("nyc", "2026-11-01")
    for now_utc in (
        datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc),
    ):
        assert model.metar_query_hours(now=now_utc) == 24


def test_request_size_cap_is_the_longest_local_day():
    assert METAR_QUERY_HOURS_CAP == 25
    for market_id, (_family, spring, fall) in DST_MARKETS.items():
        for target in (spring, fall, NORMAL_DAY):
            model = _model(market_id, target)
            peak = max(model.metar_query_hours(now=instant) for instant in _instants(model, step_minutes=15))
            assert peak <= METAR_QUERY_HOURS_CAP
    assert date.fromisoformat(DST_MARKETS["nyc"][2]) == date(2026, 11, 1)
