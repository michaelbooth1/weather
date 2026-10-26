"""MG-2 afternoon arm P3d_N: the frozen state contract, the serve hooks and the pin to L2's d914ae21b output.

Guards: MG-2 rule §8 C2-C5 (docs/research/mg2-composite-binding-2026-10-25/rule.md): P3d_N serve parity with
L2 d914ae21b, the bound state sha, wu_whole_f_tgroup:half_up, as-of-capture inputs, training coverage.
"""
import ast
import re
import hashlib
import json
import math
import pickle
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

p3 = import_or_skip_on_capture_host("weather.calibration.mg2_p3d_n")

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "fixtures" / "mg2_p3d_n_golden.json"

# L2 pooled_residual_model d914ae21b constants (MEAN_HGB_PARAMS, SCALE_HGB_PARAMS, MIN_SCALE), for the test refit
MEAN_HGB = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
                early_stopping=False, random_state=42)
SCALE_HGB = dict(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=40, early_stopping=False,
                 random_state=42)


class _Mean:
    """Test transcription of L2's ``MeanModel`` (raw_columns=False, doy=True, market_id=False, bias by season)."""

    def __init__(self):
        self.market_id, self.doy, self.raw_columns, self.bias_by = False, True, False, "season"

    def _anchors(self, frame):
        keys_b = list(zip(frame["market"], frame[self.bias_by]))
        keys_n = list(zip(frame["market"], frame["centre"]))
        bias = np.array([self.bias.get(k, self.bias_global) for k in keys_b])
        normal = np.array([self.normal.get(k, self.normal_by_market.get(k[0], self.normal_global)) for k in keys_n])
        fh = frame["fh"].to_numpy(dtype=float)
        mu0 = np.where(np.isfinite(fh), fh + bias, normal)
        g = frame["F"].to_numpy(dtype=float) - mu0
        return mu0, np.where(np.isfinite(g), g, 0.0), bias, normal

    def features(self, frame):
        mu0, g, bias, normal = self._anchors(frame)
        cols = [frame[c].to_numpy(dtype=float) - mu0 for c in ("x_high_so_far", "x_current_temp")]
        cols += [g, np.maximum(g, 0.0), mu0 - normal, frame["lat"].to_numpy(float), frame["lon"].to_numpy(float),
                 frame["elev"].to_numpy(float), normal, bias, frame["doy_sin"].to_numpy(float),
                 frame["doy_cos"].to_numpy(float)]
        return np.column_stack(cols), mu0, g

    def fit(self, frame):
        from sklearn.ensemble import HistGradientBoostingRegressor

        has_fh = frame["fh"].notna()
        diff = (frame["y"] - frame["fh"])[has_fh]
        self.bias = diff.groupby([frame["market"][has_fh], frame[self.bias_by][has_fh]]).mean().to_dict()
        self.bias_global = float(diff.mean())
        self.normal = frame.groupby(["market", "centre"])["y"].mean().to_dict()
        self.normal_by_market = frame.groupby("market")["y"].mean().to_dict()
        self.normal_global = float(frame["y"].mean())
        self.x_columns = []
        X, mu0, g = self.features(frame)
        r = frame["y"].to_numpy(float) - mu0
        design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
        self.ols, *_ = np.linalg.lstsq(design, r, rcond=None)
        self.hgb = HistGradientBoostingRegressor(categorical_features=None, **MEAN_HGB).fit(X, r - design @ self.ols)
        return self

    def predict(self, frame):
        X, mu0, g = self.features(frame)
        design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
        return mu0 + design @ self.ols + self.hgb.predict(X), X


def _fit_pooled(train):
    from sklearn.ensemble import HistGradientBoostingRegressor

    errors = np.full(len(train), np.nan)
    for year in sorted(train["year"].unique()):
        inner = (train["year"] != year).to_numpy()
        pred, _ = _Mean().fit(train[inner]).predict(train[~inner])
        errors[~inner] = train["y"].to_numpy(float)[~inner] - pred
    mean = _Mean().fit(train)
    X, _, _ = mean.features(train)
    floor_gap = np.nan_to_num(train["y"].to_numpy(float) - errors - train["F"].to_numpy(float), nan=0.0)
    scale = HistGradientBoostingRegressor(**SCALE_HGB).fit(np.column_stack([X, floor_gap]), np.abs(errors))
    s_train = np.maximum(0.5, scale.predict(np.column_stack([X, floor_gap])) * math.sqrt(math.pi / 2))
    return {"mean": mean, "scale": scale, "z": errors / s_train}


@pytest.fixture(scope="module")
def golden_state():
    frame = p3.golden_frame()
    fits = {}
    for hour in p3.GOLDEN_HOURS:
        train = frame[frame.hour == hour].reset_index(drop=True)
        fits[(hour, None)] = {"fit": _fit_pooled(train),
                              "train_y": {m: [int(v) for v in train.loc[train.market == m, "y"]]
                                          for m in train.market.unique()}}
    return p3.state_from_fits(
        fits, {m: list(range(60, 111)) for m in p3.GOLDEN_MARKETS}, frame_columns=set(frame.columns),
        markets=p3.GOLDEN_MARKETS, centres=p3.GOLDEN_CENTRES, season_of={f"{m:02d}": "aug_sep" for m in range(1, 13)},
        coords={m: (30.0 + i, -90.0 - 5 * i, 100.0 * i) for i, m in enumerate(p3.GOLDEN_MARKETS)}, fit_kind="dev",
        provenance={"commit": "test"})


def test_serve_copy_reproduces_l2_d914ae21b_on_the_golden_cases(golden_state):
    """Pin: L2's own code produced the golden file; the binding's serve copy must reproduce it (|dp| <= 1e-12)."""
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert payload["upstream"] == p3.UPSTREAM and payload["upstream_sha256"] == p3.UPSTREAM_SHA["pooled_residual_model"]
    assert len(payload["cases"]) == len(p3.GOLDEN_CASES)
    for case in payload["cases"]:
        expected = {int(k): v for k, v in case.pop("distribution").items()}
        got = p3.serve_distribution(golden_state, **case)
        assert set(got) == set(expected), case
        assert max(abs(got[k] - expected[k]) for k in got) <= p3.CONTROL_TOLERANCE, case
        assert abs(sum(got.values()) - 1.0) < 1e-12
        floor = math.floor(case["high_so_far"] + 0.5)
        assert min(got) >= min(floor, 60)


def test_state_round_trip_binds_the_file_sha_and_refuses_dev_forward(golden_state, tmp_path):
    sha = p3.write_state(golden_state, tmp_path / "s")
    blob = (tmp_path / "s" / p3.STATE_FILE).read_bytes()
    assert sha == hashlib.sha256(blob).hexdigest()
    assert pickle.loads(blob)["schema"] == p3.STATE_SCHEMA
    side = json.loads((tmp_path / "s" / p3.STATE_SIDECAR).read_text(encoding="utf-8"))
    assert side["state_sha256"] == sha and side["fit_kind"] == "dev"
    assert p3.load_state(tmp_path / "s" / p3.STATE_FILE, sha, forward=False)["arm"] == "P3d_N"
    with pytest.raises(p3.P3dNRefused, match="control check only"):
        p3.load_state(tmp_path / "s" / p3.STATE_FILE, sha, forward=True)
    with pytest.raises(p3.P3dNRefused, match="PENDING"):
        p3.load_state(tmp_path / "s" / p3.STATE_FILE, "PENDING", forward=False)
    with pytest.raises(p3.P3dNRefused, match="!= bound"):
        p3.load_state(tmp_path / "s" / p3.STATE_FILE, "0" * 64, forward=False)
    with pytest.raises(p3.P3dNRefused, match="overwrite"):
        p3.write_state(golden_state, tmp_path / "s")


def test_state_schema_problems_are_reported(golden_state):
    assert p3.state_problems(golden_state) == []
    bad = dict(golden_state, late_report={"rule": "receipt_by", "grace_minutes": None})
    assert "late_report.grace_minutes" in p3.state_problems(bad)
    assert "fit_kind" in p3.state_problems(dict(golden_state, fit_kind="refit"))
    assert p3.state_problems({"schema": p3.STATE_SCHEMA})[0].startswith("missing:")


FORWARD_STATE = Path(r"C:\t\l2\forward\state\p3d_n_state.pkl")
FORWARD_STATE_SHA = "c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780"  # L2 Clarification 3
CONVERSION_ON = {"enabled": True, "rule_id": "wu_whole_f_tgroup:half_up", "rule": "L2 Clarification 3 (c)"}


def _f(t):
    """temp_native as the capture stores it: T-group tenths t -> C * 1.8 + 32 in floats."""
    return (t / 10) * 1.8 + 32


def test_conversion_hook_is_off_in_the_dev_fit_and_refuses_an_unknown_rule(golden_state):
    case = dict(p3.GOLDEN_CASES[0])
    assert p3.serve_distribution(golden_state, **case)
    assert p3.convert_observation(78.24, golden_state) == 78.24
    on = dict(golden_state, conversion={"enabled": True, "rule_id": "wu_whole_f_other", "rule": None})
    with pytest.raises(p3.P3dNRefused, match="not implemented"):
        p3.serve_distribution(on, **case)
    assert set(p3.CONVERSION_RULES) == {"wu_whole_f_tgroup:half_up"}


@pytest.mark.parametrize("t, expected", [
    (25, 37),     # 2.5 C = 36.5 F exactly: a tie goes up
    (75, 46),     # 7.5 C = 45.5 F
    (325, 91),    # 32.5 C = 90.5 F
    (375, 100),   # 37.5 C = 99.5 F
    (-25, 28),    # -2.5 C = 27.5 F
    (-225, -8),   # -22.5 C = -8.5 F: half-up, not away from zero
    (256, 78),    # 25.6 C = 78.08 F
    (261, 79),    # 26.1 C = 78.98 F
    (250, 77),    # 25.0 C = 77.0 F, whole-C group (no T-group) is on the grid too
    (0, 32),
])
def test_wu_whole_f_tgroup_half_up_on_exact_ties(t, expected):
    value = _f(t)
    assert p3.tgroup_tenths(value) == t
    assert p3.wu_whole_f_tgroup_half_up(value) == expected
    assert isinstance(p3.wu_whole_f_tgroup_half_up(value), int)


def test_every_tie_on_the_tenths_grid_rounds_up_exactly():
    """All .5 F ties in -40..50 C: t = 25 (mod 50). The float C*1.8+32 can land either side of .5; the rule cannot."""
    from fractions import Fraction

    for t in range(-400, 501):
        exact = Fraction(32) + Fraction(9 * t, 50)
        got = p3.wu_whole_f_tgroup_half_up(_f(t))
        assert got == math.floor(exact + Fraction(1, 2)), t
        if exact.denominator == 2:
            assert t % 50 == 25 and got == exact + Fraction(1, 2), t


def test_conversion_refuses_a_value_off_the_tgroup_grid():
    for bad in (78.2, 80.0 + 1e-3, float("nan")):
        with pytest.raises(p3.P3dNRefused):
            p3.wu_whole_f_tgroup_half_up(bad)


def test_conversion_is_applied_before_the_floor_and_features(golden_state):
    on = dict(golden_state, conversion=CONVERSION_ON)
    case = dict(p3.GOLDEN_CASES[0], high_so_far=_f(256), current_temp=_f(250))  # 78.08 F, 77.0 F
    whole = dict(case, high_so_far=78.0, current_temp=77.0)
    assert p3.serve_distribution(on, **case) == p3.serve_distribution(golden_state, **whole)
    tie = dict(case, high_so_far=_f(325), current_temp=_f(325))  # 90.5 F -> 91, so no model mass below 91
    floor_part = p3.serve_distribution(dict(on, constants=dict(on["constants"], floor_mix_clim=0.0)), **tie)
    # p_clim keys stay present at zero mass when the mix is 0: the floor shows in the positive-mass support
    assert min(k for k, v in floor_part.items() if v > 0) == 91


@pytest.mark.skipif(not FORWARD_STATE.exists(), reason="L2's frozen forward state is local runtime evidence")
def test_forward_state_loads_by_its_bound_sha_and_serves_one_row_with_the_conversion_on():
    """Forward mode: the sha is verified before unpickling, a dev fit is refused, one fixture row serves.

    A smoke test only: no 2026 row is scored (L2 Clarification 3).
    """
    with pytest.raises(p3.P3dNRefused, match="!= bound"):
        p3.load_state(FORWARD_STATE, "0" * 64, forward=True)
    state = p3.load_state(FORWARD_STATE, FORWARD_STATE_SHA, forward=True)
    assert state["fit_kind"] == "forward" and state["conversion"]["enabled"]
    assert state["conversion"]["rule_id"] in p3.CONVERSION_RULES
    assert state["late_report"] == {"rule": "last_in_hour", "grace_minutes": None}
    dist = p3.serve_distribution(state, market="atlanta", target_date="2026-11-02", hour=15, nbm_mean=68.4,
                                 high_so_far=_f(194), current_temp=_f(189))  # 66.92 F -> 67, 66.02 F -> 66
    assert dist and abs(sum(dist.values()) - 1.0) < 1e-12 and all(v >= 0 for v in dist.values())
    no_clim = p3.serve_distribution(dict(state, constants=dict(state["constants"], floor_mix_clim=0.0)),
                                    market="atlanta", target_date="2026-11-02", hour=15, nbm_mean=68.4,
                                    high_so_far=_f(194), current_temp=_f(189))
    assert min(k for k, v in no_clim.items() if v > 0) == 67
    with pytest.raises(p3.P3dNRefused, match="grid"):
        p3.serve_distribution(state, market="atlanta", target_date="2026-11-02", hour=15, nbm_mean=68.4,
                              high_so_far=66.9, current_temp=66.0)


def test_a_dev_fit_is_refused_forward_even_with_the_conversion_on(golden_state, tmp_path):
    sha = p3.write_state(dict(golden_state, conversion=CONVERSION_ON), tmp_path / "s")
    with pytest.raises(p3.P3dNRefused, match="control check only"):
        p3.load_state(tmp_path / "s" / p3.STATE_FILE, sha, forward=True)


def test_smoothed_dist_and_nearest_centre_match_their_sources():
    from weather.calibration import feature_model as fm

    ys, support = [80, 81, 81, 85, 90], list(range(70, 95))
    assert p3.smoothed_dist(ys, support) == fm.smoothed_dist(ys, support, alpha=0.10)
    assert list(p3.smoothed_dist(ys, support)) == support
    assert p3.nearest_centre("2026-10-25", p3.GOLDEN_CENTRES) == "2026-09-22"
    assert p3.nearest_centre("2026-08-15", p3.GOLDEN_CENTRES) == "2026-08-08"


def _metar_row(obs_local, temp, tz):
    t = obs_local.astimezone(timezone.utc)
    return {"raw": f"METAR KATL {t:%d%H%M}Z 00000KT 10SM CLR {round((temp - 32) * 5 / 9):02d}/10 A3000",
            "datetime": t.isoformat(), "report_time": t.isoformat(),
            "temp_native": temp, "station_id": "KATL"}


def _replay(folder, day, tz, captures):
    """``captures``: [(capture local datetime, [(obs local datetime, temp), ...])] -> replay_inputs.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (cap, obs) in enumerate(captures):
        rows = [_metar_row(o, t, tz) for o, t in obs]
        lines.append(json.dumps({"snapshot_id": f"s{i}", "captured_at_local": cap.isoformat(),
                                 "captured_at_utc": cap.astimezone(timezone.utc).isoformat(),
                                 "target_date": day.isoformat(),
                                 "sources": {"metar": {"data": {"rows": rows, "station_id": "KATL"}}}}))
    (folder / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_late_report_rules_choose_the_snapshot_by_capture_time(tmp_path):
    """last_in_hour (dev) reads the last capture in [h:00, h+1:00); receipt_by reads the last at or before h:00+grace.

    Either way only rows observed at or before h:00 count; a report that is first captured after the receipt
    deadline is not used under receipt_by.
    """
    tz = ZoneInfo("America/New_York")
    day = date(2026, 11, 2)

    def at(h, m):
        return datetime(2026, 11, 2, h, m, tzinfo=tz)

    early = [(at(11, 52), 80.0), (at(12, 52), 82.0)]
    late = early + [(at(12, 59), 84.0)]  # observed before 13:00, first captured at 13:40
    _replay(tmp_path / "f", day, tz, [(at(13, 5), early), (at(13, 40), late)])
    dev = p3.scan_replay(tmp_path / "f", day, tz, {13}, "F", {"rule": "last_in_hour", "grace_minutes": None})
    assert dev[13]["replay_snapshot_id"] == "s1" and dev[13]["current_temp"] == 84.0
    rec = p3.scan_replay(tmp_path / "f", day, tz, {13}, "F", {"rule": "receipt_by", "grace_minutes": 10})
    assert rec[13]["replay_snapshot_id"] == "s0" and rec[13]["current_temp"] == 82.0
    wide = p3.scan_replay(tmp_path / "f", day, tz, {13}, "F", {"rule": "receipt_by", "grace_minutes": 45})
    assert wide[13]["replay_snapshot_id"] == "s1"
    with pytest.raises(p3.P3dNRefused, match="late-report"):
        p3.scan_replay(tmp_path / "f", day, tz, {13}, "F", {"rule": "whenever"})


def _event_folder(root, market, day):
    months = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
              "november", "december")
    return root / "snapshots" / f"highest-temperature-in-{market}-on-{months[day.month - 1]}-{day.day}-{day.year}"


def _snap_frame(rows, tz):
    """``rows``: [(row_key, target date, capture local datetime, cutoff hour)] -> an inputs-snapshots frame."""
    import pandas as pd

    return pd.DataFrame({
        "row_key": [r[0] for r in rows], "snapshot_id": [r[0].split("|")[1] for r in rows],
        "market": ["atlanta"] * len(rows), "target_date": [r[1].isoformat() for r in rows],
        "date": [r[1].isoformat() for r in rows], "local_hour": [r[2].hour for r in rows],
        "cutoff_hour": [str(r[3]) for r in rows], "v2_mean": [80.0] * len(rows), "v2_stddev": [2.0] * len(rows),
        "v2_available_at": [datetime.combine(r[1], datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
                            .isoformat() for r in rows],
        "captured_at_utc": [r[2].astimezone(timezone.utc).isoformat() for r in rows]})


def test_training_coverage_boundary_is_08_01_to_12_16_inclusive():
    assert p3.TRAINING_COVERAGE == ("08-01", "12-16")
    assert p3.in_training_coverage("2026-12-16") and p3.in_training_coverage("2026-08-01")
    assert not p3.in_training_coverage("2026-12-17") and not p3.in_training_coverage("2026-07-31")
    assert not p3.in_training_coverage("2027-01-05")


def test_a_date_past_12_16_falls_back_to_mg1_and_is_logged_per_row(golden_state, tmp_path):
    from weather.calibration import mg2_composite as mg2

    tz = ZoneInfo("America/New_York")
    rows = []
    for day in (date(2026, 12, 16), date(2026, 12, 17)):
        at = datetime(day.year, day.month, day.day, 15, 30, tzinfo=tz)
        _replay(_event_folder(tmp_path, "atlanta", day), day, tz,
                [(at, [(datetime(day.year, day.month, day.day, 14, 52, tzinfo=tz), 78.08)])])
        rows.append((f"atlanta|r{day.day}", day, at, 15))
    snaps = _snap_frame(rows, tz)
    out, stats = p3.emit_rows(golden_state, snaps, tmp_path, date(2026, 12, 16), date(2026, 12, 17),
                              markets=["atlanta"])
    assert [r[3] for r in out] == ["atlanta|r16"]
    assert stats["atlanta"]["outside_training_coverage"] == 1
    assert stats["atlanta"]["coverage_fallback"] == ["atlanta|r17"]
    # the afternoon slot then takes MG-1 for 12-17
    snaps = snaps.assign(guidance_physical_floor=60.0, high_so_far=float("nan"), trusted_current_max=float("nan"))
    bands = pd.DataFrame([(rk, i, k, lo, hi) for rk in snaps.row_key
                          for i, (k, lo, hi) in enumerate([("lte", np.nan, 77.0), ("between", 78.0, 79.0),
                                                           ("gte", 80.0, np.nan)])],
                         columns=["row_key", "band_index", "kind", "low", "high"])
    base = pd.DataFrame([(rk, i, 1 / 3) for rk in snaps.row_key for i in range(3)], columns=["row_key", "band_index", "p"])
    post = mg2.distribution_band_frame({r[3]: r[4] for r in out}, bands)
    _, source = mg2.compose(snaps, bands, base, post, base)
    assert source == {"atlanta|r16": mg2.POST, "atlanta|r17": "mg1"}


def test_as_of_capture_never_admits_a_row_received_after_the_rows_capture(golden_state, tmp_path):
    """A 12:59 report first received in the 13:40 capture never reaches a 13:20 row (no receipt look-ahead).

    last_in_hour (the MG-1 gate's primary) reads it for every 13:xx row; as_of_capture (primary against the
    market) reads it only for rows captured at or after 13:40.
    """
    tz = ZoneInfo("America/New_York")
    day = date(2026, 11, 2)

    def at(h, m, us=0):
        return datetime(2026, 11, 2, h, m, 0, us, tzinfo=tz)

    early = [(at(11, 52), _f(256)), (at(12, 52), _f(261))]  # 78.08 F, 78.98 F
    late = early + [(at(12, 59), _f(283))]  # 82.94 F, observed before 13:00, first received at 13:40
    folder = _event_folder(tmp_path, "atlanta", day)
    _replay(folder, day, tz, [(at(13, 5), early), (at(13, 40), late)])
    index = p3._replay_index(folder, day, tz)
    assert p3.scan_replay_as_of(folder, day, tz, 13, at(13, 20), "F", index)["current_temp"] == _f(261)
    assert p3.scan_replay_as_of(folder, day, tz, 13, at(13, 20), "F", index)["high_so_far"] == _f(261)
    assert p3.scan_replay_as_of(folder, day, tz, 13, at(13, 39, 999999), "F", index)["replay_snapshot_id"] == "s0"
    assert p3.scan_replay_as_of(folder, day, tz, 13, at(13, 40), "F", index)["current_temp"] == _f(283)
    assert p3.scan_replay_as_of(folder, day, tz, 13, at(13, 4), "F", index) is None
    snaps = _snap_frame([("atlanta|a", day, at(13, 20), 13), ("atlanta|b", day, at(13, 45), 13)], tz)
    asof, _ = p3.emit_rows(golden_state, snaps, tmp_path, day, day, markets=["atlanta"], inputs="as_of_capture")
    primary, _ = p3.emit_rows(golden_state, snaps, tmp_path, day, day, markets=["atlanta"])
    kw = dict(market="atlanta", target_date=day.isoformat(), hour=13, nbm_mean=80.0)
    no_late = p3.serve_distribution(golden_state, **kw, high_so_far=_f(261), current_temp=_f(261))
    with_late = p3.serve_distribution(golden_state, **kw, high_so_far=_f(283), current_temp=_f(283))
    assert {r[3]: r[4] for r in asof} == {"atlanta|a": no_late, "atlanta|b": with_late}
    assert {r[3]: r[4] for r in primary} == {"atlanta|a": with_late, "atlanta|b": with_late}


def test_as_of_capture_is_never_computed_on_a_dev_row(golden_state, tmp_path):
    import pandas as pd

    with pytest.raises(p3.P3dNRefused, match="never computed on a dev row"):
        p3.emit_rows(golden_state, pd.DataFrame(), tmp_path, date(2026, 9, 29), date(2026, 10, 30),
                     inputs="as_of_capture")
    with pytest.raises(p3.P3dNRefused, match="input mode"):
        p3.emit_rows(golden_state, pd.DataFrame(), tmp_path, date(2026, 11, 1), date(2026, 11, 2), inputs="later")


def test_the_forward_gate_and_the_market_arm_score_as_of_capture_vectors(tmp_path):
    """Rule §8 C7 (the forward gate) and C4 (the market arm): both read the as-of-capture vectors."""
    from weather.calibration import mg2_composite as mg2

    with pytest.raises(mg2.Mg2Refused, match="as-of-capture"):
        mg2.score(layout_root=tmp_path, vectors=tmp_path / mg2.VECTORS, rule=tmp_path / "rule.md",
                  out=tmp_path / "out", release_binding=tmp_path)
    assert "PRIMARY for the forward MG-2 vs MG-1 gate" in mg2.VECTOR_ROLES[mg2.ASOF_VECTORS]
    assert "PRIMARY for every comparison against the market" not in mg2.VECTOR_ROLES[mg2.VECTORS]
    assert "never scored by the forward MG-2 vs MG-1 gate" in mg2.VECTOR_ROLES[mg2.VECTORS]
    tree = ast.parse((ROOT / "src/weather/calibration/mg2_composite.py").read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    calls = {n.func.id for n in ast.walk(funcs["score"]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "require_gate_vectors" in calls
    # the dev control replay keeps last_in_hour (the reproduction check); the as-of path is forward only
    emit_src = ast.get_source_segment((ROOT / "src/weather/calibration/mg2_composite.py").read_text(encoding="utf-8"),
                                      funcs["emit"])
    assert "frame.to_parquet(out / VECTORS" in emit_src
    assert 'inputs="as_of_capture"' in emit_src and "if not control:" in emit_src
    assert "asof_frame.to_parquet(out / ASOF_VECTORS" in emit_src


def test_module_has_no_network_and_no_production_importer():
    tree = ast.parse((ROOT / "src/weather/calibration/mg2_p3d_n.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"requests", "urllib", "urllib3", "httpx", "http", "aiohttp", "socket"}
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "://" in n.value
                   for n in ast.walk(tree))
    assert "pooled_residual_model" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                                           for a in n.names}
    saved = sys.modules.pop("weather.calibration.mg2_p3d_n")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.mg2_p3d_n", {"__name__": "weather.serving.x"})
    finally:
        sys.modules["weather.calibration.mg2_p3d_n"] = saved
    # An importer, not a mention: L2's pooled_residual_model writes the agreed state schema string
    # ("mg2_p3d_n_state/1") without importing this module.
    importer = re.compile(r"calibration\.mg2_p3d_n\b|\bimport\s+mg2_p3d_n\b|mg2_p3d_n\s+import\b")
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py")
            if p.name not in ("mg2_composite.py", "mg2_p3d_n.py")
            and importer.search(p.read_text(encoding="utf-8"))]
    assert hits == []
