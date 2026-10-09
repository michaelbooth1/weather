"""Late-day lock-in re-anchored on captured station evidence (v0.5.11).

Since paid WU access was disabled the printed WU history is empty, so every
late-day lock-in stage read a missing high and served strength 0 (the
2026-10-04 model-parity swarm, PR #187 ``d-defect-evening-stage.md``). The
restoration re-anchors S1-S6 on the observed same-day station high (METAR
keyed by observation time, so a D-1 report carried in by AWC's nominal
``reportTime`` is excluded) and the S7 calibration taper follows through the
same strength. Once a late-day stage acts, no mass stays below the observed
anchor bucket (lockin-anchor-v3, after production's v2 replay found 679 rows
whose new vector held more mass below a prior-day-carried anchor than old).

Inputs are built with the production writers: AWC JSON items through
``parse_metar_payload`` (the AviationWeather parser ``fetch_metar`` uses),
station rows through ``station_observation_data`` and the floor through
``guidance_physical_floor``.

Guards: never weaken the trusted observed-high floor (DELEGATION_CONTRACT section 2); the
v2 replay floor failure on PR #191 (austin 2026-08-25, M0 carried D-1 report) and the
Defender mutants M1-M4 on the lockin-anchor-v3 floor. With PR #189 (metar-parser-v4,
obsTime keying) the M0 carried-report fixtures parse explicitly under v3 ``reportTime``
keying, the capture every closed date in the replay was made under.
lockin-anchor-v4 (stacked on #189): before lock-in, no mass below the same-day METAR
high bucket at any hour; Defender mutants on B (hour >= 7 only, renormalize instead of
move, SWOB as a hard floor, sentinel readings, raw-less D-1 rows).
"""
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from weather.model.model_distribution import DistributionPipelineState
from weather.model.model_distribution_constants import LATE_DAY_LOCKIN_ANCHOR_VERSION
from weather.model.model_sources import METAR_KEYING_REPORT_TIME
from weather.model.toronto_model import TorontoHighTempModel

ATL_DATE = "2026-09-20"
# Hourly METAR temperatures (deg C) at :52 local; the 15:52 report, 31.7 C =
# 89.06 F, is the running high, so B = 89 and band 88-89 F is the high band.
ATL_METAR_C = (
    (7, 22.0), (9, 25.0), (11, 28.0), (13, 30.0), (14, 31.0), (15, 31.7),
    (16, 31.1), (17, 30.0), (18, 29.0), (19, 27.8), (20, 26.7), (21, 25.6),
    (22, 25.0), (23, 24.4),
)
# The served ATL 2026-09-20 23:55 payload after settlement_lag_adjusted /
# current_observed_floor: 0.969 on band 88-89 F and 0.031 above the high.
ATL_EVENING_VECTOR = {
    86: 0.0, 87: 0.0, 88: 0.300, 89: 0.669, 90: 0.022, 91: 0.007, 92: 0.002,
}
SETTLEMENT_LAG_MODEL = {
    "component": {"min_context_n": 20},
    "revision_contexts": {
        "hour=17": {"n": 600, "revision_up_rate": 0.08},
        "hour=19": {"n": 600, "revision_up_rate": 0.02},
        "hour=20": {"n": 600, "revision_up_rate": 0.003},
    },
}


def _model(market_id="atlanta", target_date=ATL_DATE):
    model = TorontoHighTempModel(market_id=market_id, target_date=target_date)
    model.settlement_lag_model = SETTLEMENT_LAG_MODEL
    return model


def awc_metar_item(observed_local, temp_c, icao):
    """One AviationWeather JSON item as AWC serves it: ``obsTime`` is the
    observation epoch, ``reportTime`` the NOMINAL hour (a :5x routine report
    is stamped with the next hour), ``rawOb`` carries the DDHHMMZ group."""
    observed_utc = observed_local.astimezone(timezone.utc)
    nominal = observed_utc.replace(minute=0, second=0, microsecond=0)
    if observed_utc.minute >= 45:
        nominal += timedelta(hours=1)
    return {
        "icaoId": icao,
        "obsTime": int(observed_utc.timestamp()),
        "reportTime": nominal.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "temp": temp_c,
        "rawOb": f"{icao} {observed_utc:%d%H%M}Z AUTO 00000KT 10SM CLR {temp_c:02.0f}/15 A3000",
    }


def _metar_source(model, readings, *, until_hour, day=ATL_DATE, icao="KATL", carried=()):
    """A captured ``metar`` source item exactly as a ``metar-parser-v3``
    ``fetch_metar`` shaped it (every closed date the replay reads was captured
    under v3, so the rows are keyed on ``reportTime``; ``metar-parser-v4``
    serving keys on ``obsTime`` and never admits the carried report).

    ``carried`` adds reports observed before the target day (local datetimes)
    that AWC's nominal ``reportTime`` keys into it (capture defect M0)."""
    year, month, dom = (int(part) for part in day.split("-"))
    payload = [awc_metar_item(observed, temp_c, icao) for observed, temp_c in carried]
    for hour, temp_c in readings:
        if hour > until_hour:
            continue
        local = datetime(year, month, dom, hour, 52, tzinfo=model.spec.tz)
        payload.append(awc_metar_item(local, temp_c, icao))
    rows = model.parse_metar_payload(payload, keying=METAR_KEYING_REPORT_TIME)
    latest = rows[-1]
    same_day_max = max(row["temp_native"] for row in rows)
    max_since_7am = model.station_max_since_7am_from_rows(rows)
    data = {
        "station_id": icao,
        "raw_payload": payload,
        "rows": rows,
        "latest": latest,
        "report_time": latest.get("report_time"),
        "target_date_match": True,
        "temp_native": latest["temp_native"],
        "temp_c": latest["temp_native"],
        "max_since_7am_native": max_since_7am,
        "max_since_7am_c": max_since_7am,
        "same_day_max_native": same_day_max,
        "same_day_max_c": same_day_max,
    }
    return {"ok": True, "data": data}


def _wu_history_source(model, rows):
    """A WU history item in the shape ``fetch_wu_history`` returned."""
    rows = [{"time": time, "temp_native": temp, "temp_c": temp} for time, temp in rows]
    high = max(row["temp_native"] for row in rows)
    return {"ok": True, "data": {
        "rows": rows,
        "latest": rows[-1],
        "max_native": high,
        "max_c": high,
        "max_times": [row["time"] for row in rows if row["temp_native"] == high],
    }}


def _stage_inputs(model, sources, now):
    history = model.source_data(sources, "wu_history")
    metar = model.source_data(sources, "metar")
    station = model.station_observation_data(sources)
    current_temp = model.row_temp_native(station)
    history_max = model.row_max_native(history) if history else None
    floor = model.guidance_physical_floor(
        high_so_far=history_max,
        current_temp=current_temp,
        live_reading=current_temp,
        sources=sources,
    )
    anchor = model.late_day_lockin_anchor(
        history=history,
        history_max=history_max,
        guidance_floor=floor,
        station=station,
        metar=metar,
        now=now,
    )
    return history, history_max, current_temp, model.row_temp_native(metar), floor, anchor


def _run_stage(model, scores, sources, now, *, anchored=True):
    history, history_max, current_temp, metar_temp, _, anchor = _stage_inputs(model, sources, now)
    return model.distribution_late_day_lockin_stage(
        dict(scores),
        history=history,
        current_temp=current_temp,
        metar_temp=metar_temp,
        history_max=history_max,
        now=now,
        weather_forecast={},
        open_meteo={},
        nws_hourly={},
        global_ensemble={},
        eccc_city={},
        pipeline=DistributionPipelineState(),
        lockin_anchor=anchor if anchored else None,
    )


def _above(distribution, bucket):
    return sum(p for b, p in distribution.items() if int(b) > bucket)


def _estimate(model, sources, now, *, feature_vector, legacy, continuation=None):
    model.calibrated_weights = None
    model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
        dict(feature_vector), "hgb",
    )
    model.predict_late_day_continuation = lambda sources, cutoff_hour, now: (
        None if continuation is None
        else {"active": True, "continuation_probability": continuation}
    )
    model.late_day_lockin_legacy_wu_anchor = legacy
    return model.estimate_distribution_result(sources, now=now)


# --- (1) closed evening snapshot: the ATL 2026-09-20 23:55 vector -----------

def test_atlanta_evening_vector_moves_mass_off_bands_above_the_high():
    model = _model()
    now = datetime(2026, 9, 20, 23, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, ATL_METAR_C, until_hour=23)}
    *_, floor, anchor = _stage_inputs(model, sources, now)

    assert floor == pytest.approx(89.06)
    assert anchor["source"] == "observed_station_rows"
    assert anchor["bucket"] == 89
    assert anchor["first_reached_time"] == "15:52"
    assert anchor["version"] == LATE_DAY_LOCKIN_ANCHOR_VERSION

    before_above = _above(ATL_EVENING_VECTOR, 89)
    assert before_above == pytest.approx(0.031)

    # The defect: on the WU-only anchor the stage is a no-op (strength 0).
    legacy_scores, legacy_strength, _ = _run_stage(
        model, ATL_EVENING_VECTOR, sources, now, anchored=False,
    )
    assert legacy_strength == 0.0
    assert _above(legacy_scores, 89) == pytest.approx(before_above)

    scores, strength, context = _run_stage(model, ATL_EVENING_VECTOR, sources, now)
    assert strength == pytest.approx(1.0)
    assert context["stage_attribution"]["final_stage"] == "hard_lockin"
    assert context["lockin_anchor"]["source"] == "observed_station_rows"
    after_above = _above(scores, 89)
    assert after_above < before_above / 5
    assert sum(scores.values()) == pytest.approx(1.0)
    # The 5% one-up hedge survives; nothing above is zeroed.
    assert 0.0 < scores[90] < ATL_EVENING_VECTOR[90]
    assert scores[88] + scores[89] > 0.99


def test_atlanta_evening_end_to_end_restored_strength_reaches_calibration_taper():
    model = _model()
    now = datetime(2026, 9, 20, 23, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, ATL_METAR_C, until_hour=23)}
    feature_vector = {88: 0.30, 89: 0.40, 90: 0.18, 91: 0.08, 92: 0.04}

    legacy = _estimate(model, sources, now, feature_vector=feature_vector, legacy=True)
    restored = _estimate(model, sources, now, feature_vector=feature_vector, legacy=False)

    legacy_components = legacy.component_payload["components"]
    assert legacy.component_payload["lockin_strength"] == 0.0
    assert _above(legacy_components["late_day_lockin"], 89) == pytest.approx(
        _above(legacy_components["wu_floor_residual"], 89)
    )

    components = restored.component_payload["components"]
    assert restored.component_payload["lockin_strength"] == pytest.approx(1.0)
    pre = _above(components["pre_calibration_model"], 89)
    assert pre < _above(components["wu_floor_residual"], 89)
    # At strength 1 the taper makes calibration the identity: no re-spread.
    assert _above(restored.distribution, 89) == pytest.approx(pre, abs=1e-6)
    assert _above(restored.distribution, 89) < _above(legacy.distribution, 89)
    assert sum(restored.distribution.values()) == pytest.approx(1.0)


# --- (2) a morning snapshot changes only below the same-day anchor --------

def _estimate_without_pre_lockin_floor(model, sources, now, **kwargs):
    model.pre_lockin_same_day_floor = False
    try:
        return _estimate(model, sources, now, legacy=False, **kwargs)
    finally:
        del model.pre_lockin_same_day_floor


@pytest.mark.parametrize("hour", [9, 12])
def test_morning_snapshot_moves_only_the_mass_below_the_same_day_anchor(hour):
    model = _model()
    now = datetime(2026, 9, 20, hour, 55, tzinfo=model.spec.tz)
    # A frontal morning: the day's warmest reading so far is at 03:52, before
    # 07:00 and above the current reading, so the pre-lock-in hard floor
    # (current reading, max since 07:00) sits below it.
    readings = ((1, 25.0), (3, 26.0), (5, 24.0), (7, 22.0), (9, 23.0), (11, 24.0), (12, 24.0))
    sources = {"metar": _metar_source(model, readings, until_hour=hour)}
    feature_vector = {70: 0.1, 76: 0.2, 80: 0.3, 84: 0.25, 88: 0.15}
    expected_bucket = _oracle_bucket(max(t for h, t in readings if h <= hour))
    hard_floor_bucket = _oracle_bucket(max(t for h, t in readings if 7 <= h <= hour))
    assert hard_floor_bucket < 76 < expected_bucket  # 76 is the band B newly closes

    legacy = _estimate(model, sources, now, feature_vector=feature_vector, legacy=True)
    v3 = _estimate_without_pre_lockin_floor(model, sources, now, feature_vector=feature_vector)
    restored = _estimate(model, sources, now, feature_vector=feature_vector, legacy=False)

    assert v3.distribution == legacy.distribution  # v3 behaviour, exactly
    assert restored.component_payload["lockin_strength"] == 0.0
    anchor = restored.component_payload["high_has_stood_lockin"]["lockin_anchor"]
    assert anchor["bucket"] == expected_bucket
    assert anchor["observed_floor_stage"] == "pre_lockin"
    assert legacy.distribution.get(76, 0.0) > 0.05  # v3 kept real mass below the anchor
    assert _below(restored.distribution, expected_bucket) == pytest.approx(0.0, abs=1e-12)
    assert sum(restored.distribution.values()) == pytest.approx(1.0)


def test_celsius_market_morning_floored_and_evening_anchored():
    model = _model(market_id="toronto", target_date="2026-07-20")
    readings = ((7, 19.0), (10, 23.0), (13, 26.0), (14, 27.0), (16, 26.0),
                (18, 24.0), (20, 22.0), (22, 21.0))
    morning = datetime(2026, 7, 20, 10, 55, tzinfo=model.spec.tz)
    morning_sources = {"metar": _metar_source(
        model, readings, until_hour=10, day="2026-07-20", icao="CYYZ",
    )}
    vector = {21: 0.2, 23: 0.3, 25: 0.3, 27: 0.2}
    legacy = _estimate(model, morning_sources, morning, feature_vector=vector, legacy=True)
    v3 = _estimate_without_pre_lockin_floor(model, morning_sources, morning, feature_vector=vector)
    restored = _estimate(model, morning_sources, morning, feature_vector=vector, legacy=False)
    assert v3.distribution == legacy.distribution
    assert _below(restored.distribution, 23) == pytest.approx(0.0, abs=1e-12)

    evening = datetime(2026, 7, 20, 22, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(
        model, readings, until_hour=22, day="2026-07-20", icao="CYYZ",
    )}
    scores = {26: 0.1, 27: 0.6, 28: 0.2, 29: 0.1}
    *_, anchor = _stage_inputs(model, sources, evening)
    assert anchor["bucket"] == 27 and anchor["first_reached_time"] == "14:52"
    out, strength, _ = _run_stage(model, scores, sources, evening)
    assert strength == pytest.approx(1.0)
    assert _above(out, 27) < _above(scores, 27) / 5


# --- (3) floor interaction --------------------------------------------------

def test_lockin_acts_only_above_floor_bucket_and_never_weakens_the_floor():
    model = _model()
    now = datetime(2026, 9, 20, 21, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, ATL_METAR_C, until_hour=21)}
    *_, floor, anchor = _stage_inputs(model, sources, now)
    floor_bucket = model.round_half_up(floor)
    assert anchor["bucket"] == floor_bucket == 89

    scores = {85: 0.0, 86: 0.0, 87: 0.05, 88: 0.25, 89: 0.35, 90: 0.20, 91: 0.10, 92: 0.05}
    out, strength, context = _run_stage(model, scores, sources, now)
    assert strength > 0.9
    assert context["lockin_anchor"]["observed_floor_bucket"] == floor_bucket
    for bucket, probability in scores.items():
        if bucket < floor_bucket:
            # v3: an acting late-day stage leaves no mass below the observed floor.
            assert out[bucket] == 0.0
        elif bucket == floor_bucket:
            assert out[bucket] >= probability + scores[87] + scores[88]
        else:
            assert out[bucket] < probability
    assert sum(out.values()) == pytest.approx(1.0)


def test_end_to_end_floor_mass_below_hard_floor_stays_zero():
    model = _model()
    now = datetime(2026, 9, 20, 22, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, ATL_METAR_C, until_hour=22)}
    vector = {84: 0.1, 86: 0.2, 88: 0.3, 89: 0.2, 90: 0.1, 92: 0.1}
    legacy = _estimate(model, sources, now, feature_vector=vector, legacy=True)
    restored = _estimate(model, sources, now, feature_vector=vector, legacy=False)
    floor_bucket = restored.calibration_context["observed_floor_bucket"]
    assert floor_bucket == legacy.calibration_context["observed_floor_bucket"]
    if floor_bucket is not None:
        assert sum(p for b, p in restored.distribution.items() if b < floor_bucket) <= sum(
            p for b, p in legacy.distribution.items() if b < floor_bucket
        ) + 1e-12
    # Mass at or below the guidance-floor band only grows.
    at_or_below = lambda dist: sum(p for b, p in dist.items() if b <= 89)  # noqa: E731
    assert at_or_below(restored.distribution) >= at_or_below(legacy.distribution)


def test_no_floor_and_no_history_keeps_the_stage_a_noop():
    model = _model()
    now = datetime(2026, 9, 20, 22, 0, tzinfo=model.spec.tz)
    anchor = model.late_day_lockin_anchor(
        history={}, history_max=None, guidance_floor=None, station={}, metar={}, now=now,
    )
    assert anchor["source"] is None and anchor["bucket"] is None
    assert anchor["history"] == {}


def test_first_reached_time_is_point_in_time():
    model = _model()
    now = datetime(2026, 9, 20, 15, 30, tzinfo=model.spec.tz)
    # Rows captured after ``now`` (a replay artefact) never set max_times.
    source = _metar_source(model, ATL_METAR_C, until_hour=23)
    anchor = model.late_day_lockin_anchor(
        history={}, history_max=None, guidance_floor=88.0,
        station=source["data"], metar=source["data"], now=now,
    )
    assert anchor["bucket"] == 88
    # 31.0 C = 87.8 F at 14:52 is the first PIT row whose bucket reaches 88.
    assert anchor["first_reached_time"] == "14:52"


# --- (4) WU history present: behaviour unchanged ----------------------------

@pytest.mark.parametrize("metar_peak_c", [31.1, 32.2])
def test_wu_history_present_keeps_the_wu_anchor(metar_peak_c):
    """With WU live the anchor is the WU history, untouched. 31.1 C (87.98 F)
    gives max(history_max, guidance_floor) == the WU high; 32.2 C (89.96 F) is
    a METAR reading ahead of a lagging WU print, where the guarded anchor still
    keeps the WU view rather than moving the lock-in."""
    model = _model()
    now = datetime(2026, 9, 20, 21, 55, tzinfo=model.spec.tz)
    readings = tuple(
        (hour, metar_peak_c if hour == 15 else temp) for hour, temp in ATL_METAR_C
    )
    wu_rows = [("13:52", 86.0), ("15:52", 88.0), ("17:52", 86.0), ("19:52", 82.0),
               ("21:52", 78.0)]
    sources = {
        "wu_history": _wu_history_source(model, wu_rows),
        "metar": _metar_source(model, readings, until_hour=21),
    }
    history, history_max, *_, floor, anchor = _stage_inputs(model, sources, now)
    assert history_max == 88.0
    assert anchor["source"] == "wu_history"
    assert anchor["high"] == 88.0 and anchor["bucket"] == 88
    assert anchor["history"] is history
    if metar_peak_c == 31.1:
        assert max(history_max, floor) == history_max

    scores = {86: 0.1, 87: 0.2, 88: 0.4, 89: 0.2, 90: 0.1}
    anchored = _run_stage(model, scores, sources, now)
    plain = _run_stage(model, scores, sources, now, anchored=False)
    assert anchored[0] == plain[0]
    assert anchored[1] == plain[1]

    vector = {84: 0.1, 86: 0.2, 88: 0.3, 89: 0.2, 90: 0.1, 92: 0.1}
    legacy = _estimate(model, sources, now, feature_vector=vector, legacy=True)
    restored = _estimate(model, sources, now, feature_vector=vector, legacy=False)
    assert restored.distribution == legacy.distribution


# --- production v2 replay failure: austin 2026-08-25 18:07 (M0 carry) -------

AUS_DATE = "2026-08-25"
# The day's own reports peak at 27.8 C (82.04 F); the D-1 23:53 report at
# 28.9 C (84.02 F) is stamped reportTime 00:00 D by AWC and parsed into D.
AUS_METAR_C = ((7, 24.0), (9, 25.6), (11, 26.7), (13, 27.2), (14, 27.8),
               (15, 27.8), (16, 27.2), (17, 26.7))
# v2 replay snapshot 20260825T190722129454-0400: the old (served) final vector.
AUS_OLD_FINAL = {
    79: .005, 80: .029, 81: .042, 82: .042, 83: .021, 85: .054, 86: .046, 87: .039,
    88: .124, 89: .078, 90: .112, 91: .021, 92: .026, 93: .034, 94: .028, 95: .026,
    96: .023, 97: .022, 98: .030, 99: .086, 100: .019, 101: .025, 102: .038,
    104: .009, 105: .006, 106: .008,
}


def _austin():
    model = _model(market_id="austin", target_date=AUS_DATE)
    carried = datetime(2026, 8, 24, 23, 53, tzinfo=model.spec.tz)
    now = datetime(2026, 8, 25, 18, 7, 22, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(
        model, AUS_METAR_C, until_hour=17, day=AUS_DATE, icao="KAUS",
        carried=((carried, 28.9),),
    )}
    return model, now, sources


def _below(distribution, bucket):
    return sum(p for b, p in distribution.items() if int(b) < bucket)


def test_austin_prior_day_report_is_not_the_anchor_and_nothing_lands_below_it():
    model, now, sources = _austin()
    # (a)/(c): the guidance floor is observed-only, but the D-1 23:53 report
    # keyed by its nominal reportTime enters D as a "00:00" row.
    rows = model.source_data(sources, "metar")["rows"]
    assert rows[0]["time"] == "00:00" and rows[0]["temp_native"] == pytest.approx(84.02)
    assert model.guidance_physical_floor(sources=sources) == pytest.approx(84.02)

    *_, anchor = _stage_inputs(model, sources, now)
    assert anchor["source"] == "observed_station_rows"
    assert anchor["excluded_prior_day_rows"] == 1
    assert anchor["high"] == pytest.approx(82.04)
    assert anchor["bucket"] == 82
    assert anchor["first_reached_time"] == "14:52"
    assert anchor["guidance_physical_floor"] == pytest.approx(84.02)

    out, strength, context = _run_stage(model, AUS_OLD_FINAL, sources, now)
    assert strength > 0.0
    assert context["lockin_anchor"]["observed_floor_bucket"] == 82
    assert _below(out, 82) == 0.0
    assert _below(out, 82) <= _below(AUS_OLD_FINAL, 82)

    legacy = _estimate(model, sources, now, feature_vector=AUS_OLD_FINAL, legacy=True)
    restored = _estimate(model, sources, now, feature_vector=AUS_OLD_FINAL, legacy=False)
    assert _below(restored.distribution, 82) == pytest.approx(0.0, abs=1e-12)
    assert _below(restored.distribution, 82) <= _below(legacy.distribution, 82) + 1e-12
    assert sum(restored.distribution.values()) == pytest.approx(1.0)


def test_rawob_group_keys_rows_when_obstime_is_not_retained():
    model, now, sources = _austin()
    sources["metar"]["data"].pop("raw_payload")
    *_, anchor = _stage_inputs(model, sources, now)
    assert anchor["excluded_prior_day_rows"] == 1
    assert anchor["bucket"] == 82


@pytest.mark.parametrize("seed", range(40))
def test_property_new_mass_below_anchor_never_exceeds_old(seed):
    rng = random.Random(seed)
    model = _model()
    hour = rng.randint(1, 23)
    minute = rng.choice((5, 30, 55))
    now = datetime(2026, 9, 20, hour, minute, tzinfo=model.spec.tz)
    # A third of the days peak before 07:00 (a frontal passage): there the
    # max-since-07:00 hard floor sits below the observed anchor, so the old
    # vector does carry mass below it.
    front = rng.random() < 0.35
    peak_hour = rng.randint(0, min(hour, 5)) if front or hour < 11 else rng.randint(11, min(hour, 17))
    peak = rng.uniform(26.0, 34.0)
    readings = tuple(
        (h, round(peak - abs(h - peak_hour) * rng.uniform(0.3, 1.2), 1))
        for h in range(0, hour + 1)
    )
    carried = ()
    if rng.random() < 0.5:
        carried = ((datetime(2026, 9, 19, 23, 53, tzinfo=model.spec.tz),
                    round(peak + rng.uniform(-1.0, 3.0), 1)),)
    # Reports are observed at HH:52, so the current hour's report exists only
    # from HH:52 on; before 07:00 the property also covers that edge.
    until_hour = hour - 1 if hour > 7 or minute < 52 else hour
    sources = {"metar": _metar_source(model, readings, until_hour=until_hour, carried=carried)}
    vector = {b: rng.random() ** 2 for b in range(70, 100) if rng.random() < 0.6}
    continuation = rng.choice((None, rng.random()))

    legacy = _estimate(model, sources, now, feature_vector=vector, legacy=True,
                       continuation=continuation)
    restored = _estimate(model, sources, now, feature_vector=vector, legacy=False,
                         continuation=continuation)

    # Independent oracle: the observed same-day high of this fixture, computed
    # here from the readings themselves -- the target day's reports observed
    # at HH:52 up to ``until_hour`` (all at or before ``now``), the carried
    # D-1 report excluded -- never from the code's own anchor fields.
    expected_bucket = _oracle_bucket(max(temp for h, temp in readings if h <= until_hour))
    anchor = restored.component_payload["high_has_stood_lockin"]["lockin_anchor"]
    assert anchor["bucket"] == expected_bucket
    assert anchor["excluded_prior_day_rows"] == len(carried)

    assert _below(restored.distribution, expected_bucket) <= (
        _below(legacy.distribution, expected_bucket) + 1e-9
    )
    # lockin-anchor-v4: no mass below the observed same-day high at ANY hour,
    # whether or not a late-day stage acted.
    assert _below(restored.distribution, expected_bucket) == pytest.approx(0.0, abs=1e-12)
    assert sum(restored.distribution.values()) == pytest.approx(1.0)


def _oracle_bucket(temp_c):
    """Fahrenheit market bucket of a METAR Celsius reading, computed in the
    test: F = C * 9/5 + 32, rounded half up."""
    return math.floor(temp_c * 9.0 / 5.0 + 32.0 + 0.5)


def _late_day_stage_acted(result):
    """Behavioural, not self-reported: the S6 blend ran, or the lock-in
    stage changed the vector it received."""
    components = result.component_payload["components"]
    if "late_day_continuation_blend" in components:
        return True
    before = components["wu_floor_residual"]
    after = components["late_day_lockin"]
    return any(abs(after.get(b, 0.0) - before.get(b, 0.0)) > 1e-12 for b in set(before) | set(after))


# --- Defender conditions on the v3 floor (calibration prior, S6 only) -------

# A frontal day: the 01:52 report (31.7 C = 89.06 F) is the day's observed
# high, so the anchor bucket (89) sits above the max-since-07:00 hard floor.
FRONTAL_METAR_C = ((1, 31.7), (3, 30.5), (5, 29.0), (7, 26.0), (10, 27.0),
                   (13, 28.0), (15, 28.5), (16, 28.0))
SYNTHETIC_CALIBRATION = {
    "exact_distribution": {
        "enabled": True,
        "method": "temperature",
        "temperature": 1.4,
        "temperature_by_hour": {},
        "prior_weight": 0.3,
    },
}


def test_calibration_prior_with_partial_lockin_puts_no_mass_below_the_anchor():
    """Kills "calibration floor left at the hard floor": with prior_weight > 0
    and strength < 1 the calibration prior spreads uniform mass over every
    bucket at or above its floor, so only an anchor-level floor keeps the
    buckets between the hard floor and the anchor empty."""
    model = _model()
    model.probability_calibration = SYNTHETIC_CALIBRATION
    now = datetime(2026, 9, 20, 16, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, FRONTAL_METAR_C, until_hour=16)}
    vector = {80: 0.1, 82: 0.1, 84: 0.15, 86: 0.15, 88: 0.15, 89: 0.15, 90: 0.1, 92: 0.1}
    anchor_bucket = _oracle_bucket(31.7)

    result = _estimate(model, sources, now, feature_vector=vector, legacy=False)

    strength = result.component_payload["lockin_strength"]
    assert 0.0 < strength < 1.0
    hard_floor = result.calibration_context["observed_floor_bucket"]
    assert hard_floor is not None and hard_floor < anchor_bucket
    assert _below(result.distribution, anchor_bucket) == pytest.approx(0.0, abs=1e-12)
    assert sum(result.distribution.values()) == pytest.approx(1.0)


def test_s6_blend_alone_puts_no_mass_below_the_anchor():
    """Kills "clamp skipped when only S6 acts": at 15:55 the lock-in strength
    is 0 (S1 starts after 15h, S2 at 17h, S3/S5 need remaining forecasts, the
    reading has not rolled 0.25 C below the high for S4), yet the late-day
    continuation blend reshapes the vector around the anchor bucket."""
    model = _model()
    readings = ((1, 31.4), (3, 30.5), (5, 29.0), (7, 27.0), (9, 28.0), (11, 29.5),
                (13, 30.6), (14, 31.0), (15, 31.2))
    now = datetime(2026, 9, 20, 15, 55, tzinfo=model.spec.tz)
    sources = {"metar": _metar_source(model, readings, until_hour=15)}
    vector = {84: 0.1, 86: 0.15, 87: 0.15, 88: 0.25, 89: 0.15, 90: 0.1, 92: 0.1}
    anchor_bucket = _oracle_bucket(31.4)  # 88.52 F -> 89; the 31.2 C reading is 88

    result = _estimate(model, sources, now, feature_vector=vector, legacy=False,
                       continuation=0.4)

    components = result.component_payload["components"]
    assert "late_day_continuation_blend" in components
    assert result.component_payload["lockin_strength"] == 0.0
    assert components["late_day_lockin"] != components["wu_floor_residual"]
    hard_floor = result.calibration_context["observed_floor_bucket"]
    assert hard_floor is not None and hard_floor < anchor_bucket
    assert _below(result.distribution, anchor_bucket) == pytest.approx(0.0, abs=1e-12)
    assert sum(result.distribution.values()) == pytest.approx(1.0)


# --- (5) lockin-anchor-v4: the pre-lock-in same-day floor (Defender on B) ---

def _night(model, hour=3, minute=30):
    return datetime(2026, 9, 20, hour, minute, tzinfo=model.spec.tz)


def test_pre_lockin_floor_moves_mass_onto_the_anchor_before_0700():
    """Fixed 03:30 case: a mutant applying the floor only at hour >= 7 fails here."""
    model = _model()
    now = _night(model)
    sources = {"metar": _metar_source(model, ((1, 26.0), (3, 24.0)), until_hour=3)}
    scores = {70: 0.1, 76: 0.2, 79: 0.1, 84: 0.4, 88: 0.2}
    out, strength, context = _run_stage(model, scores, sources, now)
    bucket = _oracle_bucket(26.0)
    assert strength == 0.0
    assert context["lockin_anchor"]["observed_floor_stage"] == "pre_lockin"
    assert context["lockin_anchor"]["observed_floor_bucket"] == bucket
    # Moved, not renormalized: buckets above keep their mass exactly and the
    # anchor bucket gains everything that was below it.
    assert _below(out, bucket) == 0.0
    assert out[bucket] == pytest.approx(0.1 + 0.2 + 0.1)
    assert out[84] == pytest.approx(0.4) and out[88] == pytest.approx(0.2)


def test_pre_lockin_floor_switch_off_restores_v3():
    model = _model()
    sources = {"metar": _metar_source(model, ((1, 26.0), (3, 24.0)), until_hour=3)}
    scores = {70: 0.1, 76: 0.2, 79: 0.1, 84: 0.4, 88: 0.2}
    model.pre_lockin_same_day_floor = False
    out, _, context = _run_stage(model, scores, sources, _night(model))
    assert context["lockin_anchor"]["observed_floor_stage"] is None
    assert out == pytest.approx(scores)


def test_implausible_reading_is_never_the_anchor():
    model = _model()
    sources = {"metar": _metar_source(model, ((1, 26.0), (2, 60.0), (3, 24.0)), until_hour=3)}
    *_, anchor = _stage_inputs(model, sources, _night(model))
    assert anchor["bucket"] == _oracle_bucket(26.0)  # 60 C (140 F) is a sentinel, not a high


def test_pre_lockin_floor_reads_metar_not_swob():
    """SWOB keeps its warm-bias hedge before lock-in; only METAR is a hard floor there."""
    model = _model()
    metar = _metar_source(model, ((1, 24.0), (3, 23.0)), until_hour=3)
    swob = {"ok": True, "data": {"station_observation_source": "eccc_swob", "rows": [
        {"time": "02:00", "local_time": "02:00", "temp_native": 82.0},
    ]}}
    scores = {70: 0.1, 76: 0.2, 79: 0.1, 84: 0.4, 88: 0.2}
    out, _, context = _run_stage(model, scores, {"metar": metar, "station_observations": swob},
                                 _night(model))
    anchor = context["lockin_anchor"]
    assert anchor["bucket"] == 82  # the anchor itself still sees SWOB
    assert anchor["metar_bucket"] == _oracle_bucket(24.0)
    assert anchor["observed_floor_bucket"] == _oracle_bucket(24.0)
    assert out[79] == pytest.approx(0.1)  # below SWOB's 82, above METAR's 75: untouched

    swob_only = {"station_observations": swob}
    out, _, context = _run_stage(model, scores, swob_only, _night(model))
    assert context["lockin_anchor"]["observed_floor_stage"] is None
    assert out == pytest.approx(scores)


def test_stored_row_without_raw_keyed_to_the_prior_day_is_excluded():
    """A stored row with no raw report but its own D-1 obs_time never anchors day D."""
    model = _model()
    metar = _metar_source(model, ((1, 22.0),), until_hour=1)
    rows = [dict(row) for row in metar["data"]["rows"]]
    for row in rows:
        row.pop("raw", None)
    carried = {"time": "00:00", "local_time": "00:00", "temp_native": 90.0,
               "obs_time": "2026-09-20T03:53:00Z"}  # 23:53 EDT on 09-19
    metar = {"ok": True, "data": {**metar["data"], "raw_payload": [], "rows": [carried, *rows]}}
    *_, anchor = _stage_inputs(model, {"metar": metar}, _night(model, 2, 0))
    assert anchor["excluded_prior_day_rows"] == 1
    assert anchor["bucket"] == _oracle_bucket(22.0)
