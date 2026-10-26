"""MG-2 pre-13 arm served from the frozen, sha-bound L6 own-model state (no per-run refit).

Guards: MG-2 clarification season-L6 2026-10-26 (docs/research/mg2-composite-binding-2026-10-25/
mg2-clarification-season-l6-2026-10-26.md at 4c89815c3, section 3): the 07-12 arm's nowcast N is
``mg_serve_core.l6_own_nowcast`` on the state loaded by ``mg_serve_core.load_l6_own_state(path, sha)``; a
mismatched, empty or FILL sha refuses; no carve-out by date; the state path and sha are binding inputs.
The fixture state is a tiny HGB fitted in-test; no local data file is read.
"""
import hashlib
import json
import pickle
from datetime import date

import numpy as np
import pandas as pd
import pytest

from weather.model import mg_serve_core as core

from tests.host_guard import import_or_skip_on_capture_host

mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")
l6 = import_or_skip_on_capture_host("weather.calibration.upstream_obs_screen")

COLUMNS = core.L6_OWN_COLUMNS


def _features(n, seed, prefix="atlanta|s"):
    rng = np.random.default_rng(seed)
    t = rng.uniform(40.0, 75.0, n)
    r = t + rng.uniform(0.0, 4.0, n)
    frame = pd.DataFrame({
        "row_key": [f"{prefix}{i}" for i in range(n)], "hour_f": rng.uniform(7.0, 12.9, n),
        "doy": rng.integers(274, 350, n).astype(float), "station_code": rng.integers(0, 11, n).astype(float),
        "t": t, "td": t - rng.uniform(2.0, 15.0, n), "r": r, "t_minus_r": t - r, "tend3": rng.normal(0, 3, n),
        "td_tend3": rng.normal(0, 2, n), "u": rng.normal(0, 5, n), "v": rng.normal(0, 5, n),
        "spd": rng.uniform(0, 15, n), "cover": rng.choice([0.0, .25, .5, .75, 1.0], n),
        "log_ceiling": rng.uniform(2.0, 4.5, n), "prev_dmax": t + rng.normal(5, 3, n)})
    frame["prev_minus_t"] = frame.prev_dmax - frame.t
    frame.loc[0, "tend3"] = np.nan  # the HGB's missing-value path, as in captured features
    return frame


def _state_file(tmp_path):
    """L3's ``season_matched_l6.fit_state`` shape: schema, OWN columns, a fitted HGB, provenance."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    train = _features(80, seed=1, prefix="train|")
    y = np.random.default_rng(2).normal(2.0, 1.5, len(train))
    model = HistGradientBoostingRegressor(max_iter=15, random_state=0).fit(train[list(COLUMNS)].to_numpy(float), y)
    state = {"schema": core.L6_STATE_SCHEMA, "columns": list(COLUMNS), "model": model,
             "provenance": {"commit": "test", "train_months": [10, 11, 12]}}
    path = tmp_path / "l6_own_state_octdec.pkl"
    path.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), model


def test_pre13_nowcast_equals_l6_own_nowcast_on_the_bound_state(tmp_path):
    path, sha, model = _state_file(tmp_path)
    feat = _features(12, seed=3)
    served = mg2.l6_nowcast_frame(mg2.load_l6_state(path, sha), feat)
    direct = core.l6_own_nowcast(core.load_l6_own_state(path, sha), feat)  # L3's LOYO / final-state emission
    independent = feat.r.to_numpy(float) + model.predict(feat[list(COLUMNS)].to_numpy(float))
    assert served.row_key.tolist() == feat.row_key.tolist()
    assert np.array_equal(served.n_own.to_numpy(float), direct)
    assert np.array_equal(direct, independent)
    assert served.n_up.isna().all() and served.n_ring.isna().all()


def _captured_layout(tmp_path, monkeypatch, feat):
    """A one-market captured window: snapshots at 07-12 on B dates, features fixed by the fixture."""
    days = ("2026-10-28", "2026-11-15")  # 10-28..10-31 and from 11-01 alike: no carve-out
    hours = [h for h in (7, 9, 10, 12) if h in l6.HOURS]
    rows, keys = [], iter(feat.row_key)
    for day in days:
        for h in hours:
            rows.append({"row_key": next(keys), "station": "KATL", "market": "atlanta", "date": day,
                         "local_hour": h, "snapshot_id": f"{day}-{h}"})
    snaps = pd.DataFrame(rows)
    layout = tmp_path / "layout"
    layout.mkdir()
    snaps.to_parquet(layout / "inputs_snapshots.parquet", index=False)
    replay = tmp_path / "replay"
    folders = []
    for day in days:
        folder = replay / day
        folder.mkdir(parents=True)
        lines = [json.dumps({"snapshot_id": r["snapshot_id"], "captured_at_utc": f"{day}T{r['local_hour'] + 4:02d}:05:00+00:00",
                             "sources": {}}) for r in rows if r["date"] == day]
        (folder / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        folders.append(("atlanta", date.fromisoformat(day), folder))
    by_key = feat.set_index("row_key")

    def features(snapshot_rows, captured, tz, station_code, prev):
        return by_key.loc[[key for key, _, _ in snapshot_rows]].reset_index()

    def no_refit(*a, **k):
        raise AssertionError("the pre-13 arm must not refit the L6 HGB")

    monkeypatch.setattr(l3, "_event_folders", lambda root: iter(folders))
    monkeypatch.setattr(l3, "l6_captured_features", features)
    monkeypatch.setattr(l6, "load", lambda root: (None, {"KATL": {"timezone": "America/New_York"}}, {}))
    monkeypatch.setattr(l6, "stations", lambda sel: ["KATL"])
    monkeypatch.setattr(l6, "build_history", no_refit)
    monkeypatch.setattr(l6, "make_model", no_refit)
    return layout, replay, len(rows)


def test_captured_nowcast_serves_the_frozen_state_on_every_b_date(tmp_path, monkeypatch):
    path, sha, _ = _state_file(tmp_path)
    feat = _features(8, seed=4)
    layout, replay, n = _captured_layout(tmp_path, monkeypatch, feat)
    out = tmp_path / "now"
    manifest = mg2.captured_nowcast(layout_root=layout, replay_root=replay, research_root=tmp_path / "research",
                                    first="2026-10-28", last="2026-11-15", out=out, l6_state=path,
                                    l6_state_sha256=sha)
    got = pd.read_parquet(out / "nowcasts.parquet").set_index("row_key")
    expected = core.l6_own_nowcast(core.load_l6_own_state(path, sha), feat.iloc[:n])
    assert manifest["rows"] == n == len(got)
    assert np.array_equal(got.loc[feat.row_key.iloc[:n], "n_own"].to_numpy(float), expected)
    assert manifest["l6_state_sha256"] == sha and manifest["l6_state_provenance"]["train_months"] == [10, 11, 12]
    assert manifest["serve_core_sha256"] == mg2.sha256_file(core.__file__)


def test_sha_mismatch_refuses_before_serving(tmp_path, monkeypatch):
    path, sha, _ = _state_file(tmp_path)
    wrong = ("0" if sha[0] != "0" else "1") + sha[1:]
    with pytest.raises(mg2.Mg2Refused, match="!= bound"):
        mg2.load_l6_state(path, wrong)
    with pytest.raises(core.ServeCoreError):
        core.load_l6_own_state(path, wrong)
    layout, replay, _ = _captured_layout(tmp_path, monkeypatch, _features(8, seed=5))
    out = tmp_path / "now"
    with pytest.raises(mg2.Mg2Refused, match="!= bound"):
        mg2.captured_nowcast(layout_root=layout, replay_root=replay, research_root=tmp_path, first="2026-10-28",
                             last="2026-11-15", out=out, l6_state=path, l6_state_sha256=wrong)
    assert not (out / "nowcasts.parquet").exists()
    path.write_bytes(path.read_bytes() + b"\0")  # the bytes changed under the bound sha
    with pytest.raises(mg2.Mg2Refused, match="!= bound"):
        mg2.load_l6_state(path, sha)


@pytest.mark.parametrize("bad", ["", None, "<FILL@BINDING>", "FILL", "PENDING", "A" * 64, "a" * 63, " " + "a" * 64])
def test_empty_fill_or_malformed_sha_refuses(tmp_path, bad):
    path, sha, _ = _state_file(tmp_path)
    with pytest.raises(mg2.Mg2Refused, match="64 lowercase hex"):
        mg2.load_l6_state(path, bad)
    assert mg2.load_l6_state(path, sha)["schema"] == core.L6_STATE_SCHEMA


def test_core_loader_itself_refuses_a_missing_sha(tmp_path):
    path, _, _ = _state_file(tmp_path)
    for missing in ("", None):
        with pytest.raises(core.ServeCoreError):
            core.load_l6_own_state(path, missing)


def test_state_path_is_required_and_schema_checked(tmp_path):
    with pytest.raises(mg2.Mg2Refused, match="state path"):
        mg2.load_l6_state("", "a" * 64)
    with pytest.raises(mg2.Mg2Refused):
        mg2.load_l6_state(tmp_path / "absent.pkl", "a" * 64)
    other = tmp_path / "other.pkl"
    other.write_bytes(pickle.dumps({"schema": "l6_own_state/0", "columns": list(COLUMNS), "model": None}))
    with pytest.raises(mg2.Mg2Refused, match="schema or columns"):
        mg2.load_l6_state(other, hashlib.sha256(other.read_bytes()).hexdigest())


def test_cli_takes_the_state_and_sha_as_explicit_inputs():
    base = ["captured-nowcast", "--layout", "l", "--replay-root", "r", "--research-root", "x", "--first",
            "2026-10-28", "--last", "2026-10-28", "--out", "o"]
    for missing in ([], ["--l6-state", "s.pkl"], ["--l6-state-sha256", "a" * 64]):
        with pytest.raises(SystemExit):
            mg2.build_parser().parse_args(base + missing)
    args = mg2.build_parser().parse_args(base + ["--l6-state", "s.pkl", "--l6-state-sha256", "a" * 64])
    assert (args.l6_state, args.l6_state_sha256) == ("s.pkl", "a" * 64)


def test_mg_serve_core_is_in_the_release_files():
    assert "src/weather/model/mg_serve_core.py" in mg2.RELEASE_FILES
