"""Shadow-only ``high_so_far`` train/serve parity variant (lane L8, 2026-10-24).

Training (``feature_store.build_historical_feature_record``) gives the HGB
``high_so_far`` = the maximum of every target-date observation with minute of
day <= the cutoff minute: the running maximum since local 00:00. Serving has had
no WU history rows since 2026-06-30, so the served value is the current
temperature (and, from cutoff 07, the max since 07:00); the overnight METAR
reports are never read. The variant ``metar_running_max_since_midnight_v1``
reads them, keyed on the observation instant so the previous day's late report
carried in as the ``00:00`` row is excluded.

Guards pinned here:
- production (variant ``None``) is byte-identical and never reaches the new code;
- train-vs-serve equality on the traced instance (Atlanta 2026-08-21 08:04, the
  captured METAR rows verbatim) and on synthetic F and C days at every cutoff;
- the floor high only gets stronger, never weaker;
- every derived feature follows the new ``high_so_far``.

Guards: train/serve feature parity (AGENTS.md model contracts) for the shadow-only high_so_far variant; the
serve default is unchanged.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest

from weather.model.feature_store import build_historical_feature_record
from weather.model.model_base import (
    HIGH_SO_FAR_SHADOW_METAR_SINCE_MIDNIGHT as VARIANT,
    HIGH_SO_FAR_SHADOW_VARIANTS,
    ModelUtilsMixin,
)
from weather.model.toronto_model import TorontoHighTempModel

# Captured station_observations rows of snapshot 20260821T080447456334-0400 (KATL,
# replay_inputs.jsonl), time / raw / report_time / temp_native verbatim. The
# "00:00" row is the 2026-08-20 23:52 report (03:52Z) carried in by AWC's nominal
# reportTime; the night cooled behind a thunderstorm outflow (03:43 SPECI).
ATL_0821_ROWS = (
    ("00:00", "METAR KATL 210352Z 14003KT 10SM FEW180 BKN250 29/23 A3001", "2026-08-21T04:00:00.000Z", 84.02),
    ("01:00", "METAR KATL 210452Z 00000KT 10SM FEW060 SCT180 BKN250 29/23 A3000", "2026-08-21T05:00:00.000Z", 84.02),
    ("02:00", "METAR KATL 210552Z 21004KT 10SM FEW060 FEW100 BKN180 28/23 A3001", "2026-08-21T06:00:00.000Z", 82.94),
    ("03:00", "METAR KATL 210652Z COR 25005KT 10SM FEW060 28/23 A3001", "2026-08-21T07:00:00.000Z", 82.94),
    ("03:43", "SPECI KATL 210743Z 32014G27KT 10SM -RA 27/21 A3002", "2026-08-21T07:43:00.000Z", 80.06),
    ("04:00", "METAR KATL 210752Z 32014G25KT 10SM -RA 27/21 A3002", "2026-08-21T08:00:00.000Z", 80.06),
    ("04:02", "SPECI KATL 210802Z COR 32011G21KT 10SM 27/21 A3002", "2026-08-21T08:02:00.000Z", 80.06),
    ("04:18", "SPECI KATL 210818Z COR 33012G20KT 10SM 26/20 A3003", "2026-08-21T08:18:00.000Z", 78.98),
    ("05:00", "METAR KATL 210852Z 33016KT 10SM 25/20 A3003", "2026-08-21T09:00:00.000Z", 77.0),
    ("06:00", "METAR KATL 210952Z 32008KT 10SM 24/19 A3004", "2026-08-21T10:00:00.000Z", 75.92),
    ("07:00", "METAR KATL 211052Z 28004KT 10SM 23/19 A3003", "2026-08-21T11:00:00.000Z", 73.94),
    ("08:00", "METAR KATL 211152Z 00000KT 10SM 24/19 A3004", "2026-08-21T12:00:00.000Z", 75.92),
)
ATL_NOW = datetime.fromisoformat("2026-08-21T08:04:47.456334-04:00")


def _row(time, raw, report_time, temp):
    return {"time": time, "raw": raw, "report_time": report_time, "temp_native": temp,
            "temp_c": temp, "station_id": raw.split()[1]}


def _sources(rows, *, current_max=None, history_rows=None):
    latest = rows[-1] if rows else None
    station = {"rows": list(rows), "latest": latest, "source": "metar",
               "station_observation_source": "metar",
               "temp_native": latest["temp_native"] if latest else None,
               "current_temp_native": latest["temp_native"] if latest else None,
               "max_since_7am_native": current_max}
    metar = dict(station)
    out = {"station_observations": {"ok": True, "data": station},
           "metar": {"ok": True, "data": metar},
           "wu_history": {"ok": True, "data": {"rows": list(history_rows or [])}},
           "wu_current": {"ok": True, "data": {}}}
    return out


def _model(market_id="atlanta", target_date="2026-08-21", variant=None):
    model = TorontoHighTempModel(market_id=market_id, target_date=target_date)
    model.high_so_far_shadow_variant = variant
    return model


def _atl_sources():
    return _sources([_row(*r) for r in ATL_0821_ROWS], current_max=75.92)


def _context(model, sources, cutoff, now):
    station = model.station_observation_data(sources)
    return model.effective_observed_high_context(
        model.source_data(sources, "wu_history"), model.source_data(sources, "wu_current"),
        station, cutoff, metar=model.source_data(sources, "metar"), now=now)


def _training_rows(model, sources, now):
    """The same observations as trainer rows: minute of day at the observation instant,
    target local date only (the trainer's WU rows are per local date)."""
    station = model.station_observation_data(sources)
    rows, _ = model.lockin_observed_rows(station=station, metar=model.source_data(sources, "metar"), now=now)
    return [{"minute_of_day": minute, "temp_native": value} for minute, _, value in rows]


def test_production_default_is_the_parity_fix_and_variants_are_closed():
    assert ModelUtilsMixin.high_so_far_shadow_variant == VARIANT
    assert TorontoHighTempModel(market_id="atlanta").high_so_far_shadow_variant == VARIANT
    assert HIGH_SO_FAR_SHADOW_VARIANTS == (None, VARIANT)
    model = _model(variant="something_else")
    with pytest.raises(ValueError, match="unknown high_so_far shadow variant"):
        _context(model, _atl_sources(), 8, ATL_NOW)


def test_production_path_is_unchanged_and_never_reads_the_shadow(monkeypatch):
    model = _model()

    def boom(*args, **kwargs):  # the production path must never reach the shadow input
        raise AssertionError("production read the shadow input")

    monkeypatch.setattr(model, "observed_running_max_since_midnight", boom)
    sources = _atl_sources()
    feats = model.extract_live_features(sources, 8, now=ATL_NOW)
    # The served value of record for this snapshot (EF trace, L5): the current temperature.
    assert feats["high_so_far"] == pytest.approx(75.92)
    assert feats["hours_at_peak"] == pytest.approx(2.0)  # first nominal "06:00" row at 75.92
    context = _context(model, sources, 8, ATL_NOW)
    legacy = model._served_observed_high_context(
        model.source_data(sources, "wu_history"), model.source_data(sources, "wu_current"),
        model.station_observation_data(sources), 8)
    assert context == legacy
    assert "shadow_variant" not in context


def test_train_serve_parity_atlanta_2026_08_21_0804():
    sources = _atl_sources()
    shadow = _model(variant=VARIANT)
    feats = shadow.extract_live_features(sources, 8, now=ATL_NOW)
    record = build_historical_feature_record(
        shadow.target_date, _training_rows(shadow, sources, ATL_NOW), {"max_temp_native": 94.0}, 8,
        forecast_high=93.0, unit="F")
    assert record["high_so_far"] == pytest.approx(84.02)
    assert feats["high_so_far"] == pytest.approx(record["high_so_far"])
    assert feats["hours_at_peak"] == pytest.approx(record["hours_at_peak"])  # 00:52 -> (480-52)/60
    assert feats["hours_at_peak"] == pytest.approx((480 - 52) / 60)


def test_previous_day_report_carried_as_0000_row_is_excluded():
    rows = [_row(*r) for r in ATL_0821_ROWS]
    rows[0] = dict(rows[0], temp_native=88.0, temp_c=88.0)  # D-1 23:52 warmer than the whole night
    shadow = _model(variant=VARIANT)
    context = _context(shadow, _sources(rows, current_max=75.92), 8, ATL_NOW)
    assert context["effective_observed_high"] == pytest.approx(84.02)
    assert context["shadow_first_reached_minute"] == 52


def _synthetic_day(unit, seed):
    """Hourly :52 reports plus a few specials over one local day, keyed like AWC (nominal hour)."""
    rng = random.Random(seed)
    tz_offset = timedelta(hours=-4)  # both fixtures' markets are on EDT in August
    base = 75.0 if unit == "F" else 22.0
    step = 1.8 if unit == "F" else 1.0
    rows = []
    # previous day's 23:52 report, carried in as "00:00"
    obs = datetime(2026, 8, 20, 23, 52, tzinfo=timezone(tz_offset))
    for k in range(0, 24 * 2):
        local = obs + timedelta(minutes=30 * k) if k else obs
        if local.minute not in (52, 22):
            continue
        if local.minute == 22 and rng.random() < 0.7:
            continue
        utc = local.astimezone(timezone.utc)
        nominal = utc.replace(minute=0) + (timedelta(hours=1) if utc.minute >= 45 else timedelta())
        nominal_local = nominal.astimezone(timezone(tz_offset))
        hour = local.hour + local.minute / 60
        temp = round(base + step * (rng.uniform(-3, 3) + 4 * max(0.0, 1 - abs(hour - 15) / 9)), 2)
        rows.append({"time": nominal_local.strftime("%H:%M") if local.minute == 52 else local.strftime("%H:%M"),
                     "raw": f"METAR XXXX {utc:%d%H%M}Z 00000KT 10SM",
                     "report_time": nominal.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                     "temp_native": temp, "temp_c": temp,
                     "_observed_local": local})
    return rows


@pytest.mark.parametrize("market_id,unit", [("atlanta", "F"), ("toronto", "C")])
@pytest.mark.parametrize("seed", range(4))
def test_train_serve_parity_every_cutoff_f_and_c(market_id, unit, seed):
    rows = _synthetic_day(unit, seed)
    shadow = _model(market_id=market_id, variant=VARIANT)
    tz = shadow.spec.tz
    for cutoff in range(7, 21):
        now = datetime(2026, 8, 21, cutoff, 5, tzinfo=tz)
        visible = [r for r in rows
                   if datetime.fromisoformat(r["report_time"].replace("Z", "+00:00"))
                   <= now.astimezone(timezone.utc) + timedelta(minutes=10)]
        sources = _sources(visible, current_max=max(r["temp_native"] for r in visible))
        feats = shadow.extract_live_features(sources, cutoff, now=now)
        # Independent of the serving parser: the trainer's rows are the target local
        # date's observations at their true instants (the D-1 23:52 report is not one).
        train = [{"minute_of_day": r["_observed_local"].hour * 60 + r["_observed_local"].minute,
                  "temp_native": r["temp_native"]}
                 for r in visible if r["_observed_local"].date() == shadow.target_date]
        record = build_historical_feature_record(shadow.target_date, train, {"max_temp_native": 99.0},
                                                 cutoff, forecast_high=30.0, unit=unit)
        assert feats["high_so_far"] == pytest.approx(record["high_so_far"]), cutoff
        assert feats["hours_at_peak"] == pytest.approx(record["hours_at_peak"]), cutoff


@pytest.mark.parametrize("seed", range(40))
def test_floor_only_gets_stronger(seed):
    rows = _synthetic_day("F", 100 + seed)
    rng = random.Random(seed)
    served = _model()
    shadow = _model(variant=VARIANT)
    tz = served.spec.tz
    for cutoff in (7, 9, 12, 15, 18, 20):
        now = datetime(2026, 8, 21, cutoff, rng.randint(0, 59), tzinfo=tz)
        visible = [r for r in rows
                   if datetime.fromisoformat(r["report_time"].replace("Z", "+00:00")) <= now.astimezone(timezone.utc)]
        current_max = rng.choice([None, max(r["temp_native"] for r in visible) + rng.choice([0.0, 1.5, -1.0])])
        sources = _sources(visible, current_max=current_max)
        base = _context(served, sources, cutoff, now)
        fix = _context(shadow, sources, cutoff, now)
        if base["effective_observed_floor_high"] is not None:
            assert fix["effective_observed_floor_high"] >= base["effective_observed_floor_high"]
        assert fix["served_effective_observed_floor_high"] == base["effective_observed_floor_high"]


def test_printed_wu_history_present_leaves_the_served_value():
    history = [{"time": "06:00", "temp_native": 70.0}, {"time": "08:00", "temp_native": 72.0}]
    sources = _sources([_row(*r) for r in ATL_0821_ROWS], current_max=75.92, history_rows=history)
    served = _context(_model(), sources, 8, ATL_NOW)
    fix = _context(_model(variant=VARIANT), sources, 8, ATL_NOW)
    for key in ("effective_observed_high", "effective_observed_floor_high", "effective_observed_high_source"):
        assert fix[key] == served[key]


def test_no_target_date_row_by_the_cutoff_keeps_the_served_value():
    rows = [_row(*ATL_0821_ROWS[0])]  # only the carried D-1 report (a 00:01 snapshot)
    now = datetime.fromisoformat("2026-08-21T00:01:25-04:00")
    sources = _sources(rows)
    served = _context(_model(), sources, 7, now)
    fix = _context(_model(variant=VARIANT), sources, 7, now)
    assert fix["effective_observed_high"] == served["effective_observed_high"] == pytest.approx(84.02)
    assert fix["shadow_first_reached_minute"] is None


def test_derived_features_move_with_high_so_far():
    sources = _atl_sources()
    base = _model().extract_live_features(sources, 8, now=ATL_NOW)
    fix = _model(variant=VARIANT).extract_live_features(sources, 8, now=ATL_NOW)
    shift = fix["high_so_far"] - base["high_so_far"]
    assert shift == pytest.approx(84.02 - 75.92)
    if base["forecast_high"] is not None:
        assert fix["forecast_gap"] == pytest.approx(base["forecast_gap"] - shift)
    assert fix["live_reading_minus_high"] == pytest.approx(base["live_reading_minus_high"] - shift)
    assert fix["live_reading_temp"] == base["live_reading_temp"]
    assert fix["current_temp"] == base["current_temp"]
    assert fix["guidance_physical_floor"] >= base["guidance_physical_floor"]
    assert fix["guidance_physical_floor"] >= fix["high_so_far"] - 1e-9
    untouched = {"rise_from_7am", "warming_rate_2h", "dewpoint_c", "wind_speed_kmh", "minutes_since_cutoff"}
    for key in untouched:
        assert fix[key] == base[key], key


# --- the single shared implementation (master ruling 2026-10-24: MG-2 arm A and arm B import it) ---

from weather.model import observed_running_max as orm  # noqa: E402


def test_shared_function_is_what_the_serve_path_calls(monkeypatch):
    calls = []
    real = orm.running_max_since_midnight

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(orm, "running_max_since_midnight", spy)
    feats = _model(variant=VARIANT).extract_live_features(_atl_sources(), 8, now=ATL_NOW)
    assert calls and calls[0]["cutoff_hour"] == 8 and calls[0]["unit"] == "F"
    assert feats["high_so_far"] == pytest.approx(84.02)


def test_shared_function_on_raw_source_data_atlanta_0821():
    model = _model()
    sources = _atl_sources()
    station = sources["station_observations"]["data"]
    high, first = orm.running_max_since_midnight(
        station, sources["metar"]["data"], target_date=model.target_date, tz=model.spec.tz, unit="F",
        cutoff_hour=8, now=ATL_NOW)
    assert (high, first) == (pytest.approx(84.02), 52)
    assert orm.running_max_since_midnight(
        station, sources["metar"]["data"], target_date=model.target_date, tz=model.spec.tz, unit="F",
        cutoff_hour=0, now=ATL_NOW) == (None, None)


@pytest.mark.parametrize("market_id,unit", [("atlanta", "F"), ("toronto", "C")])
@pytest.mark.parametrize("seed", range(6))
def test_shared_row_keying_equals_lockin_observed_rows(market_id, unit, seed):
    rows = _synthetic_day(unit, 500 + seed)
    model = _model(market_id=market_id)
    now = datetime(2026, 8, 21, 14, 5, tzinfo=model.spec.tz)
    sources = _sources([{k: v for k, v in r.items() if k != "_observed_local"} for r in rows])
    station = model.station_observation_data(sources)
    metar = model.source_data(sources, "metar")
    lockin, _ = model.lockin_observed_rows(station=station, metar=metar, now=now)
    shared = orm.observed_target_date_rows(station, metar, target_date=model.target_date, tz=model.spec.tz,
                                           unit=model.spec.display_unit, now=now)
    assert shared == [(minute, value) for minute, _, value in lockin]


# --- metar_only (master ruling 2026-10-25: MG-2 high_so_far is the METAR-only running max) ---


def _strip(rows):
    return [{k: v for k, v in r.items() if k != "_observed_local"} for r in rows]


@pytest.mark.parametrize("market_id,unit", [("atlanta", "F"), ("toronto", "C")])
@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("cutoff", [0, 6, 9, 13, 16, 23])
def test_metar_only_equals_the_serve_value_when_station_surface_is_metar(market_id, unit, seed, cutoff):
    rows = _strip(_synthetic_day(unit, 700 + seed))
    model = _model(market_id=market_id)
    now = datetime(2026, 8, 21, 23, 59, tzinfo=model.spec.tz)
    sources = _sources(rows)
    station = model.station_observation_data(sources)
    metar = model.source_data(sources, "metar")
    assert (station.get("station_observation_source") or station.get("source")) == "metar"
    kwargs = dict(target_date=model.target_date, tz=model.spec.tz, unit=model.spec.display_unit,
                  cutoff_hour=cutoff, now=now)
    serve = orm.running_max_since_midnight(station, metar, **kwargs)
    assert orm.running_max_since_midnight(station, metar, metar_only=True, **kwargs) == serve
    # MG-2's definition drops the station surface entirely; with METAR rows present it is the same value
    assert orm.running_max_since_midnight({}, metar, metar_only=True, **kwargs) == serve


@pytest.mark.parametrize("seed", range(4))
def test_metar_only_with_empty_metar_rows_uses_only_a_metar_sourced_station(seed):
    rows = _strip(_synthetic_day("F", 800 + seed))
    model = _model()
    now = datetime(2026, 8, 21, 23, 59, tzinfo=model.spec.tz)
    kwargs = dict(target_date=model.target_date, tz=model.spec.tz, unit="F", cutoff_hour=16, now=now)
    metar_station = {"rows": rows, "source": "metar", "station_observation_source": "metar"}
    serve = orm.running_max_since_midnight(metar_station, {"rows": []}, **kwargs)
    assert serve[0] is not None
    assert orm.running_max_since_midnight(metar_station, {"rows": []}, metar_only=True, **kwargs) == serve
    for source in ("wu_history", "weather_underground", "eccc_swob", None):
        other = {"rows": rows, "source": source, "station_observation_source": source}
        assert orm.running_max_since_midnight(other, {"rows": []}, metar_only=True, **kwargs) == (None, None)


def test_metar_only_ignores_a_wu_sourced_station_surface_the_default_still_merges():
    model = _model()
    sources = _atl_sources()
    metar = sources["metar"]["data"]
    hot = [_row("07:30", "METAR KATL 211130Z 00000KT 10SM 35/19 A3004", "2026-08-21T11:30:00.000Z", 95.0)]
    wu_station = {"rows": hot, "source": "wu_history", "station_observation_source": "wu_history"}
    kwargs = dict(target_date=model.target_date, tz=model.spec.tz, unit="F", cutoff_hour=8, now=ATL_NOW)
    assert orm.running_max_since_midnight(wu_station, metar, **kwargs)[0] == pytest.approx(95.0)
    assert orm.running_max_since_midnight(wu_station, metar, metar_only=True, **kwargs) == (
        pytest.approx(84.02), 52)
    assert orm.running_max_since_midnight({}, metar, metar_only=True, **kwargs) == (pytest.approx(84.02), 52)


def test_metar_only_default_is_false_and_serve_path_does_not_pass_it(monkeypatch):
    import inspect
    for fn in (orm.running_max_since_midnight, orm.observed_target_date_rows):
        assert inspect.signature(fn).parameters["metar_only"].default is False
    calls = []
    real = orm.running_max_since_midnight

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(orm, "running_max_since_midnight", spy)
    _model(variant=VARIANT).extract_live_features(_atl_sources(), 8, now=ATL_NOW)
    assert calls and all(not c.get("metar_only", False) for c in calls)
