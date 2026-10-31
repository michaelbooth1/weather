"""Defect fix 11: from the venue's 2026-10-23 cutover a SPECI never raises the served floor.

From the 2026-10-23 events the built-in markets settle on routine METARs only (EF 10x, 10ai;
``weather.backtesting.venue_rule_labels``). The served hard floor (``effective_observed_floor_high``)
and the lock-in floor rows used every METAR, so a SPECI-only maximum could zero the settling band.

Guards: the synthetic controls of master's fix-11 brief. A SPECI-only maximum is excluded and its
negation, the same maximum in a routine report, is kept. Dates before the cutover and payloads
without a SPECI are unchanged. Features keep every observation. Synthetic payloads only; no
captured, outcome or settlement data is read.
"""
from datetime import date, datetime, timezone

from weather.backtesting.venue_rule_labels import VENUE_RULE_CUTOVER_DATE
from weather.model.model_distribution import VENUE_ROUTINE_FLOOR_FROM, VENUE_ROUTINE_FLOOR_MARKETS
from weather.model.toronto_model import TorontoHighTempModel

ROUTINE_C = ((11, 25.0), (12, 26.0), (13, 27.0), (14, 27.0), (15, 28.0), (16, 28.0), (17, 27.0))
SPECI_C = 31.0
CUTOFF = 14


def _epoch(day, hour_utc, minute):
    return int(datetime(day.year, day.month, day.day, hour_utc, minute, tzinfo=timezone.utc).timestamp())


def _report(day, hour_utc, minute, temp_c, metar_type, *, prefix=True):
    body = f"KMIA {day.day:02d}{hour_utc:02d}{minute:02d}Z 09005KT 10SM {int(temp_c):02d}/20 A3001"
    return {
        "icaoId": "KMIA",
        "obsTime": _epoch(day, hour_utc, minute),
        "reportTime": datetime(day.year, day.month, day.day, hour_utc, minute,
                               tzinfo=timezone.utc).isoformat().replace("+00:00", ".000Z"),
        "metarType": metar_type,
        "temp": temp_c,
        "dewp": 20.0,
        "wdir": 90,
        "wspd": 5,
        "rawOb": f"{metar_type} {body}" if prefix else body,
    }


def _payload(day, *, peak_type="SPECI", prefix=True, peak_at=(18, 20)):
    rows = [_report(day, hour, 53, temp, "METAR") for hour, temp in ROUTINE_C]
    if peak_type is not None:
        rows.append(_report(day, *peak_at, SPECI_C, peak_type, prefix=prefix))
    return rows


def _floor(day, payload, market="miami"):
    model = TorontoHighTempModel(market_id=market, target_date=day.isoformat())
    model.high_so_far_shadow_variant = None
    metar = model.metar_data_from_payload(payload)
    sources = {"metar": {"ok": True, "data": metar}}
    station = model.station_observation_data(sources)
    context = model.effective_observed_high_context({}, {}, station, CUTOFF)
    fixed = model.venue_routine_observed_floor_high(context, {}, {}, station, metar, CUTOFF)
    return model, metar, station, context["effective_observed_floor_high"], fixed


def _f(celsius):
    return celsius * 9.0 / 5.0 + 32.0


def test_cutover_matches_the_venue_label_rule_and_covers_the_built_ins():
    assert VENUE_ROUTINE_FLOOR_FROM == VENUE_RULE_CUTOVER_DATE == date(2026, 10, 23)
    assert "miami" in VENUE_ROUTINE_FLOOR_MARKETS and len(VENUE_ROUTINE_FLOOR_MARKETS) == 12


def test_a_speci_only_maximum_is_excluded_from_the_floor():
    _, _, _, served, fixed = _floor(date(2026, 10, 25), _payload(date(2026, 10, 25)))
    assert abs(served - _f(SPECI_C)) < 1e-9
    assert abs(fixed - _f(28.0)) < 1e-9


def test_the_negation_a_routine_maximum_is_kept():
    _, _, _, served, fixed = _floor(date(2026, 10, 25), _payload(date(2026, 10, 25), peak_type="METAR"))
    assert abs(served - _f(SPECI_C)) < 1e-9
    assert fixed == served


def test_a_speci_known_only_from_the_payload_type_is_excluded():
    _, _, _, served, fixed = _floor(date(2026, 10, 25), _payload(date(2026, 10, 25), prefix=False))
    assert abs(served - _f(SPECI_C)) < 1e-9
    assert abs(fixed - _f(28.0)) < 1e-9


def test_a_speci_latest_reading_is_not_the_floor():
    day = date(2026, 10, 25)
    _, _, station, served, fixed = _floor(day, _payload(day, peak_at=(21, 40)))
    assert station["latest"]["raw"].startswith("SPECI")
    assert abs(served - _f(SPECI_C)) < 1e-9
    assert abs(fixed - _f(28.0)) < 1e-9


def test_before_the_cutover_and_without_a_speci_the_floor_is_unchanged():
    _, _, _, served, fixed = _floor(date(2026, 10, 20), _payload(date(2026, 10, 20)))
    assert fixed == served and abs(served - _f(SPECI_C)) < 1e-9
    _, _, _, served, fixed = _floor(date(2026, 10, 25), _payload(date(2026, 10, 25), peak_type=None))
    assert fixed == served and abs(served - _f(28.0)) < 1e-9


def test_lock_in_rows_drop_the_speci_only_from_the_cutover():
    for day, kept in ((date(2026, 10, 25), False), (date(2026, 10, 20), True)):
        model, metar, station, _, _ = _floor(day, _payload(day))
        now = datetime(day.year, day.month, day.day, 23, 0, tzinfo=timezone.utc).astimezone(model.spec.tz)
        rows, _ = model.lockin_observed_rows(station=station, metar=metar, now=now)
        values = [value for _, _, value in rows]
        assert (max(values) > _f(30.0)) is kept
        assert len(values) == len(ROUTINE_C) + (1 if kept else 0)


def test_features_keep_every_observation():
    day = date(2026, 10, 25)
    _, metar, station, _, _ = _floor(day, _payload(day))
    assert any(row["raw"].startswith("SPECI") for row in station["rows"])
    assert abs(metar["same_day_max_native"] - _f(SPECI_C)) < 1e-9


# --- the fix 10 + 11 stack: the running max since 00:00 is taken on routine rows ---

def _floor_parity(day, payload, market="miami"):
    """As ``_floor`` on the production default arm (fix 10's running max since 00:00)."""
    model = TorontoHighTempModel(market_id=market, target_date=day.isoformat())
    assert model.high_so_far_shadow_variant == "metar_running_max_since_midnight_v1"
    metar = model.metar_data_from_payload(payload)
    sources = {"metar": {"ok": True, "data": metar}}
    station = model.station_observation_data(sources)
    now = datetime(day.year, day.month, day.day, CUTOFF, 55, tzinfo=model.spec.tz)
    context = model.effective_observed_high_context({}, {}, station, CUTOFF, metar=metar, now=now)
    fixed = model.venue_routine_observed_floor_high(context, {}, {}, station, metar, CUTOFF, now=now)
    return context, fixed


def test_stack_an_overnight_speci_only_maximum_does_not_reenter_through_the_running_max():
    day = date(2026, 10, 25)  # 10:20Z = 06:20 EDT, before 07:00: only the running max sees it
    context, fixed = _floor_parity(day, _payload(day, peak_at=(10, 20)))
    assert context["effective_observed_high_source"] == "metar_running_max_since_midnight"
    assert abs(context["effective_observed_floor_high"] - _f(SPECI_C)) < 1e-9
    assert abs(fixed - _f(28.0)) < 1e-9


def test_stack_the_negation_an_overnight_routine_maximum_keeps_the_running_max_floor():
    day = date(2026, 10, 25)
    context, fixed = _floor_parity(day, _payload(day, peak_type="METAR", peak_at=(10, 20)))
    assert abs(context["effective_observed_floor_high"] - _f(SPECI_C)) < 1e-9
    assert fixed == context["effective_observed_floor_high"]


def test_stack_before_the_cutover_the_running_max_floor_keeps_the_speci():
    day = date(2026, 10, 20)
    context, fixed = _floor_parity(day, _payload(day, peak_at=(10, 20)))
    assert fixed == context["effective_observed_floor_high"]
    assert abs(fixed - _f(SPECI_C)) < 1e-9
