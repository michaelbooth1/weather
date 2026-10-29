"""C1: every function in ``weather.model.mg_serve_core`` equals its research source exactly.

Guards: L2's MG-3 design prerequisite b.0 (C:\\t\\l2\\drafts\\mg3_design_DRAFT.md, sha 863ec65c...), plan
C:\\t\\l3\\neutral\\plan.md (sha 83707862...) section (c) C1, and master ruling D1 of 2026-10-26: the research
modules are not rewired until MG-2/B's forward window closes, so these tests carry train/serve parity until then.
Equality is exact. Floats are compared bitwise, with no tolerance.

The research modules refuse the capture host by design, so this module skips there
(``import_or_skip_on_capture_host``). The host-side check is ``tests/operations/test_mg_serve_core_host_import.py``.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host
from weather.model import mg_serve_core as core

l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")
prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")
la = import_or_skip_on_capture_host("weather.reporting.scorecards.loss_atlas")
mb = import_or_skip_on_capture_host("weather.calibration.market_blend")
mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
mg2_inputs = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
devfit = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_devfit")
hsfp = import_or_skip_on_capture_host("weather.calibration.high_so_far_parity_shadow")

from weather.calibration import feature_model as fm  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402
from weather.reporting.scorecards.free_source_candidates import mg1 as mg1_mod  # noqa: E402

NY = ZoneInfo("America/New_York")
LA = ZoneInfo("America/Los_Angeles")

RAWS = (
    "KATL 261452Z 18008KT 10SM FEW040 SCT250 29/21 A3002 RMK AO2 SLP160 T02940206",
    "KATL 261552Z 20010G18KT 10SM BKN045 OVC200 30/20 A3001 RMK AO2 T03000200",
    "KATL 261600Z VRB03KT 10SM CLR 31/19 A3000 RMK AO2 T03061194",
    "KATL 261652Z 00000KT 10SM SKC M01/M05 A3000",
    "KATL 261752Z COR 21012KT 10SM VV004 31/21 A2999 RMK AO2 T03110211",
    "KATL 261852Z 21012KT 10SM SCT035 BKN100 32/",
    "KDEN 010052Z 36005KT 10SM FEW120 25/05 A3010",
    "garbage without a time group",
    "",
)


def _same(a, b):
    """Exact structural equality; NaN equals NaN; floats bitwise."""
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return type(a) is type(b) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=np.asarray(a).dtype.kind == "f")
    return type(a) is type(b) and a == b


# ----------------------------------------------------------------------------- constants


def test_constants_equal_their_sources():
    assert core.R0_MARKETS == prm.R0_MARKETS
    assert core.AUG_SEP_CENTRES == prm.AUG_SEP_CENTRES
    assert (core.FLOOR_MIX_CLIM, core.KERNEL_BANDWIDTH, core.MIN_SCALE) == (
        prm.FLOOR_MIX_CLIM, prm.KERNEL_BANDWIDTH, prm.MIN_SCALE)
    assert core.WU_ROUNDING_CANDIDATES == prm.WU_ROUNDING_CANDIDATES
    assert (core.L6_MARKET_LAT_MIN, core.L6_MAX_AGE_MIN, core._COVER) == (
        l3.L6_MARKET_LAT_MIN, l3.L6_MAX_AGE_MIN, l3._COVER)
    assert (core.SWITCH_HOUR, core.POST) == (mg2.SWITCH_HOUR, mg2.POST)
    assert core.EPS == mb.EPS
    assert core.V2_LOOKBACK == mg2_inputs.LOOKBACK
    assert tuple(data.FLOOR_FIELDS) == tuple(mg2_inputs.FLOOR_FIELDS)  # the floor_fields callers pass


# ----------------------------------------------------------------------------- captured METAR


def _metar_rows():
    rows = []
    for i, raw in enumerate(RAWS):
        nominal = datetime(2026, 9, 26, 15 + i % 6, 0, tzinfo=timezone.utc)
        rows.append({"raw": raw, "datetime": nominal.isoformat(), "temp_native": 70.0 + i})
    rows.append({"raw": "KATL 261452Z 18008KT", "datetime": None, "temp_native": 71.5})
    rows.append({"raw": None, "datetime": "2026-09-26T13:00:00+00:00", "temp_native": None})
    rows.append({"raw": "KATL 302352Z 18008KT", "datetime": "2026-10-01T00:00:00+00:00", "temp_native": 66.0})
    rows.append({"raw": "KATL 010052Z 18008KT", "datetime": "2026-09-30T23:00:00+00:00", "temp_native": 65.0})
    return rows


def test_metar_observation_instant_and_observations_at_cutoff():
    rows = _metar_rows()
    for tz in (NY, LA, timezone.utc):
        for row in rows:
            assert core.metar_observation_instant(row, tz) == l3.metar_observation_instant(row, tz)
        for day in (date(2026, 9, 26), date(2026, 9, 30), date(2026, 10, 1)):
            for hour in range(0, 24):
                assert _same(core.observations_at_cutoff(rows, day, hour, tz),
                             l3.observations_at_cutoff(rows, day, hour, tz))
    assert core.observations_at_cutoff(None, date(2026, 9, 26), 12, NY) == l3.observations_at_cutoff(
        None, date(2026, 9, 26), 12, NY)


@pytest.mark.parametrize("anchor", [datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc),
                                    datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc),
                                    datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)])
def test_parse_captured_metar(anchor):
    for raw in RAWS + (None, "KATL 302352Z 00000KT 10SM OVC008 12/11 A2990 RMK T01220114"):
        assert _same(core.parse_captured_metar(raw, anchor), l3.parse_captured_metar(raw, anchor))


def _replay_line(station="KATL"):
    rows = [{"station_id": station, "raw": RAWS[0]}, {"station_id": "KPDK", "raw": RAWS[1]}, {"raw": RAWS[2]}]
    return json.dumps({"snapshot_id": "s1", "captured_at_utc": "2026-09-26T19:05:00+00:00",
                       "sources": {"station": {"data": {}}, "metar": {"data": {"rows": rows}}}})


def test_json_value_after_and_captured_rows():
    line = _replay_line()
    for key in ("snapshot_id", "captured_at_utc", "sources", "metar", "missing"):
        assert _same(core.json_value_after(line, key), l3._json_value_after(line, key))
    assert _same(core.json_value_after(line, "metar", line.find('"sources":')),
                 l3._json_value_after(line, "metar", line.find('"sources":')))
    for station in ("KATL", "KPDK", "KXXX"):
        assert core.captured_rows(line, station) == l3._captured_rows(line, station)
    for bare in ('{"snapshot_id": "x"}', '{"sources": {"station": {}}}'):
        assert core.captured_rows(bare, "KATL") == l3._captured_rows(bare, "KATL")


def _parsed_day():
    base = datetime(2026, 9, 26, 4, 52, tzinfo=timezone.utc)
    parsed = []
    for i in range(30):
        valid = base + timedelta(hours=i)
        t = 20.0 + 10 * math.sin(i / 4.0)
        parsed.append({"valid": valid, "temp": t * 9 / 5 + 32, "dwpf": (t - 5) * 9 / 5 + 32 if i % 7 else None,
                       "drct": None if i % 5 == 0 else float(10 * i % 360), "sknt": float(i % 4),
                       "cover": None if i % 6 == 0 else 0.25 * (i % 5), "ceiling_ft": None if i % 3 else 2500.0,
                       "is_cor": i == 11})
    return parsed


def test_l6_captured_features_and_routine_dmax():
    parsed = _parsed_day()
    caps = [datetime(2026, 9, 26, h, 7, tzinfo=timezone.utc) for h in (8, 12, 16, 19, 23)]
    snapshot_rows = [(f"atlanta|s{i}", cap, "2026-09-26") for i, cap in enumerate(caps)]
    captured = {key: parsed[: 4 + 5 * i] for i, (key, _, _) in enumerate(snapshot_rows)}
    captured["atlanta|s4"] = []
    prev = {"2026-09-26": 88.0}
    pd.testing.assert_frame_equal(core.l6_captured_features(snapshot_rows, captured, NY, 3, prev),
                                  l3.l6_captured_features(snapshot_rows, captured, NY, 3, prev), check_exact=True)
    for day in ("2026-09-26", "2026-09-27", "2026-09-25"):
        for n in (1, 5, 20):
            assert _same(core.routine_dmax(parsed, NY, day, n), l3.routine_dmax(parsed, NY, day, n))


def test_event_folders(tmp_path):
    snaps = tmp_path / "snapshots"
    for name in ("highest-temperature-in-atlanta-on-september-26-2026", "highest-temperature-in-nyc-on-august-1-2026",
                 "highest-temperature-in-los-angeles-on-october-3-2026", "not-an-event", "README"):
        (snaps / name).mkdir(parents=True)
    assert list(core.event_folders(tmp_path)) == list(l3._event_folders(tmp_path))


# ----------------------------------------------------------------------------- v2 selection


def test_v2_helpers():
    for value in ("2026-09-26T07:00:00Z", "2026-09-26T07:00:00+00:00", "2026-09-26T07:00:00", "bad", None, ""):
        assert core.parse_time(value) == mg2_inputs.parse_time(value)
    for value in (1, "2.5", float("nan"), float("inf"), None, "x"):
        assert _same(core.finite(value), mg2_inputs.finite(value))
    for key in ("nbm:20260926T07Z", "nbm:2026-09-26", "bad", None):
        assert core.cycle_time(key) == mg2_inputs.cycle_time(key)
    for row in ({"fetched_at": "2026-09-26T08:00:00Z", "captured_at_utc": "2026-09-26T09:00:00Z"},
                {"response_received_at": "bad", "first_seen_at": "2026-09-26T08:30:00+00:00"}, {}):
        assert core.availability(row) == mg2_inputs.availability(row)
    assert core.iso(None) == mg2_inputs.iso(None)


def _bulletins():
    t = lambda h: datetime(2026, 9, 26, h, 0, tzinfo=timezone.utc)  # noqa: E731
    b = {
        "d01": {"issue": t(1), "available_at": t(2), "available_basis": "fetched_at", "cycle_key": "nbm:20260926T01Z",
                "status": "parsed"},
        "d07": {"issue": t(7), "available_at": t(8), "available_basis": "fetched_at", "cycle_key": "nbm:20260926T07Z",
                "status": "parsed"},
        "d13": {"issue": t(13), "available_at": t(14), "available_basis": "first_seen_at",
                "cycle_key": "nbm:20260926T13Z", "status": "parsed"},
        "dbad": {"issue": t(5), "available_at": t(6), "available_basis": "fetched_at", "cycle_key": "nbm:x",
                 "status": "bytes_missing"},
        "dold": {"issue": t(1) - timedelta(days=2), "available_at": t(1), "available_basis": "fetched_at",
                 "cycle_key": "nbm:old", "status": "parsed"},
        "dnone": {"issue": None, "available_at": None, "available_basis": None, "cycle_key": None, "status": None},
    }
    ok = {"available": True, "percentiles": {"10": 80.1, "25": 82, "50": 84.5, "75": 86, "90": "nan"},
          "valid_time_utc": "2026-09-27T00:00:00Z", "forecast_hour": 17, "period_kind": "max",
          "mean_native": 84.2, "stddev_native": 2.1}
    parsed = {("d01", "KATL", "2026-09-26"): dict(ok, mean_native=83.0),
              ("d07", "KATL", "2026-09-26"): dict(ok, issued_at="2026-09-26T07:05:00Z"),
              ("d13", "KATL", "2026-09-26"): {"available": False, "reason": "no_max_period"},
              ("dold", "KATL", "2026-09-26"): ok}
    return b, parsed


@pytest.mark.parametrize("hour", [0, 2, 3, 7, 8, 9, 14, 15, 23])
def test_select_v2(hour):
    bulletins, parsed = _bulletins()
    captured = datetime(2026, 9, 26, hour, 30, tzinfo=timezone.utc)
    for station, target in (("KATL", "2026-09-26"), ("KDEN", "2026-09-26")):
        assert _same(core.select_v2(bulletins, parsed, station, target, captured),
                     mg2_inputs.select_v2(bulletins, parsed, station, target, captured))


def test_usable_v2_mean():
    snaps = pd.DataFrame({
        "v2_available_at": ["2026-09-26T08:00:00Z", "2026-09-26T20:00:00Z", None, "bad", "2026-09-26T08:00:00+00:00"],
        "captured_at_utc": ["2026-09-26T09:00:00Z"] * 4 + [None],
        "v2_mean": [84.2, 84.2, 84.2, "x", 80.0], "v2_stddev": [2.0, 2.0, 2.0, 1.0, float("nan")]})
    assert np.array_equal(core.usable_v2_mean(snaps), devfit.usable_v2_mean(snaps), equal_nan=True)


# ----------------------------------------------------------------------------- P3d_N arm


def test_prm_scalars():
    for centre in prm.AUG_SEP_CENTRES + ("2026-10-10", "2026-01-15", "2026-12-24"):
        assert core.season_of(centre) == prm.season_of(centre)
    assert core.station_coordinates() == prm.station_coordinates()
    day = date(2026, 1, 1)
    while day < date(2027, 1, 1):
        if not core.in_serve_coverage(day.isoformat()):  # item 341 Jan no-wrap fix: refused, prm still snaps
            with pytest.raises(core.ServeCoreError):
                core.nearest_centre(day)
        else:
            assert core.nearest_centre(day) == prm.nearest_centre(day)
            assert core.nearest_centre(day.isoformat(), ("2026-10-10", "2026-11-24")) == prm.nearest_centre(
                day.isoformat(), ("2026-10-10", "2026-11-24"))
        day += timedelta(days=5)


def test_smoothed_dist():
    rng = np.random.default_rng(20261026)
    for _ in range(20):
        ys = [int(v) for v in rng.integers(60, 100, size=int(rng.integers(1, 300)))]
        support = list(range(int(rng.integers(50, 70)), int(rng.integers(95, 115))))
        for alpha in (0.10, 0.05, 1.0):
            assert core.smoothed_dist(ys, support, alpha) == fm.smoothed_dist(ys, support, alpha=alpha)


def test_predictive_distribution():
    rng = np.random.default_rng(20261027)
    for _ in range(200):
        z = rng.standard_normal(int(rng.integers(5, 400))) * rng.uniform(0.5, 2)
        yhat, s = float(rng.uniform(40, 110)), float(rng.uniform(0.5, 6))
        floor = [None, float("nan"), float(yhat - rng.uniform(-3, 8)), float(round(yhat) - 0.5)][int(rng.integers(4))]
        support = list(range(int(yhat) - 25, int(yhat) + 25))
        p_clim = core.smoothed_dist([int(v) for v in rng.integers(int(yhat) - 8, int(yhat) + 8, 50)], support)
        assert core.predictive_distribution(yhat, s, floor, z, support, p_clim) == prm.predictive_distribution(
            yhat, s, floor, z, support, p_clim)


def test_wu_rounding():
    for tenths in range(-500, 501):
        value = 32 + 9 * tenths / 50
        assert core.exact_tgroup_f(value) == prm.exact_tgroup_f(value)
        for rule in core.WU_ROUNDING_CANDIDATES:
            assert core.round_candidate(core.exact_tgroup_f(value), rule) == prm.round_candidate(
                prm.exact_tgroup_f(value), rule)
            assert _same(core.wu_whole_f(value, rule), prm.wu_whole_f(value, rule))
    for bad in (None, float("nan"), "x", float("inf")):
        assert core.wu_whole_f(bad) == prm.wu_whole_f(bad)
    with pytest.raises(core.ServeCoreError):
        core.round_candidate(core.exact_tgroup_f(36.5), "bogus")  # a tie (t = 25)
    with pytest.raises(prm.PooledModelError):
        prm.round_candidate(prm.exact_tgroup_f(36.5), "bogus")


# ----------------------------------------------------------------------------- bands, floor, MG-1, compose


def _layout(seed=20261028, n=60):
    rng = np.random.default_rng(seed)
    snaps, bands = [], []
    for i in range(n):
        rk = f"{['atlanta', 'denver', 'nyc'][i % 3]}|s{i}"
        cap = datetime(2026, 9, 26, 4, 0, tzinfo=timezone.utc) + timedelta(minutes=37 * i)
        avail = cap + timedelta(hours=float(rng.choice([-3, -1, 1])))
        mu = float(rng.uniform(70, 95))
        snaps.append({"row_key": rk, "local_hour": int(i % 24), "captured_at_utc": cap.isoformat(),
                      "v2_available_at": None if i % 11 == 0 else avail.isoformat(),
                      "v2_mean": None if i % 13 == 0 else mu, "v2_stddev": float(rng.uniform(0.3, 3)),
                      "guidance_physical_floor": None if i % 4 else float(mu - rng.uniform(0, 6)),
                      "high_so_far": None if i % 5 == 0 else float(mu - rng.uniform(-2, 10)),
                      "trusted_current_max": None if i % 3 else float(mu - rng.uniform(0, 12))})
        lo = int(mu) - 4
        bands.append({"row_key": rk, "band_index": 0, "kind": "lte", "low": lo, "high": lo})
        for j in range(1, 7):
            bands.append({"row_key": rk, "band_index": j, "kind": "eq", "low": lo + 2 * j - 1, "high": lo + 2 * j})
        bands.append({"row_key": rk, "band_index": 7, "kind": "gte", "low": lo + 13, "high": lo + 13})
    snaps, bands = pd.DataFrame(snaps), pd.DataFrame(bands)
    n_per = bands.groupby("row_key", sort=False).size().reindex(snaps.row_key).to_numpy()
    return snaps, bands, np.repeat(np.arange(len(snaps)), n_per)


def test_mg1_band_frame_and_probs():
    snaps, bands, band_snap = _layout()
    with_floor = snaps.assign(floor=snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1))
    for s in (snaps, with_floor):
        table = SimpleNamespace(snaps=s, bands=bands, band_snap=band_snap)
        pd.testing.assert_frame_equal(core.mg1_band_frame(s, bands, band_snap, data.FLOOR_FIELDS),
                                      la.mg1_frame(table), check_exact=True)
    rng = np.random.default_rng(1)
    kind = bands.kind.to_numpy()
    B, mu, sig = rng.uniform(60, 100, len(bands)), rng.uniform(60, 100, len(bands)), rng.uniform(1, 4, len(bands))
    args = (kind, bands.low.to_numpy(), bands.high.to_numpy(), B, mu, sig)
    assert np.array_equal(core.mg1_band_probs(*args), hsfp.mg1_band_probs(*args))
    assert np.array_equal(core.mg1_band_probs(*args), mg1_mod.band_probs(*args))


def _dists(snaps, rng, drop=0.2):
    out = {}
    for rk in snaps.row_key:
        if rng.uniform() < drop:
            continue
        centre = int(rng.integers(68, 96))
        keys = range(centre - 6, centre + 7)
        w = rng.uniform(0, 1, len(keys))
        out[rk] = {k: float(v) for k, v in zip(keys, w / w.sum())}
    return out


def test_floor_band_frame_and_compose():
    snaps, bands, _ = _layout()
    assert np.array_equal(core.floor_B(snaps, data.FLOOR_FIELDS), mg2.floor_B(snaps))
    rng = np.random.default_rng(7)
    post_d, pre_d = _dists(snaps, rng), _dists(snaps, rng, 0.4)
    post = core.distribution_band_frame(post_d, bands)
    pd.testing.assert_frame_equal(post, mg2.distribution_band_frame(post_d, bands), check_exact=True)
    pre = mg2.distribution_band_frame(pre_d, bands)
    mg1 = core.mg1_band_frame(snaps, bands, _layout()[2], data.FLOOR_FIELDS)
    for post_frame in (post, post.iloc[:0], post.assign(p=0.0)):
        got, got_src = core.compose(snaps, bands, pre, post_frame, mg1, data.FLOOR_FIELDS)
        want, want_src = mg2.compose(snaps, bands, pre, post_frame, mg1)
        pd.testing.assert_frame_equal(got, want, check_exact=True)
        assert got_src == want_src


def test_log_pool():
    snaps, bands, band_snap = _layout()
    rng = np.random.default_rng(11)
    m = rng.dirichlet(np.ones(8), len(snaps)).ravel()
    c = rng.dirichlet(np.ones(8), len(snaps)).ravel()
    impossible = rng.uniform(size=len(m)) < 0.15
    for w in (0.0, 0.3, 1.0, rng.uniform(0, 1, len(m))):
        for force in (False, True):
            assert np.array_equal(core.pool(m, c, w, impossible, band_snap, len(snaps), force_floor=force),
                                  mb.pool(m, c, w, impossible, band_snap, len(snaps), force_floor=force))
    with pytest.raises(core.ServeCoreError, match="w must be >= 0"):
        core.pool(m, c, -0.1, impossible, band_snap, len(snaps))


# ----------------------------------------------------------------------------- frozen L6 own model


def test_l6_own_columns_and_frozen_state_round_trip(tmp_path):
    import hashlib
    import pickle

    up = import_or_skip_on_capture_host("weather.calibration.upstream_obs_screen")
    assert core.L6_OWN_COLUMNS == tuple(up.OWN)
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(rng.normal(size=(400, len(up.OWN))), columns=list(up.OWN))
    frame["station_code"] = rng.integers(0, 4, len(frame)).astype(float)
    y = rng.normal(size=len(frame))
    model = up.make_model(up.OWN).fit(frame[list(up.OWN)].to_numpy(float), y)
    path = tmp_path / "l6_own_state.pkl"
    path.write_bytes(pickle.dumps({"schema": core.L6_STATE_SCHEMA, "columns": list(up.OWN), "model": model}))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(core.ServeCoreError, match="!= bound"):
        core.load_l6_own_state(path, "0" * 64)
    state = core.load_l6_own_state(path, sha)
    want = frame.r.to_numpy(float) + model.predict(frame[list(up.OWN)].to_numpy(float))
    assert np.array_equal(core.l6_own_nowcast(state, frame), want)
    bad = tmp_path / "bad.pkl"
    bad.write_bytes(pickle.dumps({"schema": core.L6_STATE_SCHEMA, "columns": ["t"], "model": model}))
    with pytest.raises(core.ServeCoreError, match="schema or columns"):
        core.load_l6_own_state(bad, hashlib.sha256(bad.read_bytes()).hexdigest())
