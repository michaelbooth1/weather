"""MG-2 pre-13 arm served from the frozen, sha-bound L6 own-model state (no per-run refit).

Guards: MG-2 clarification season-L6 2026-10-26 (docs/research/mg2-composite-binding-2026-10-25/
mg2-clarification-season-l6-2026-10-26.md at 4c89815c3, section 3): the 07-12 arm's nowcast N is
``mg_serve_core.l6_own_nowcast`` on the state loaded by ``mg_serve_core.load_l6_own_state(path, sha)``; a
mismatched, empty or FILL sha refuses; no carve-out by date; the state path and sha are binding inputs.
The fixture state is a tiny HGB fitted in-test; no local data file is read. Master's review of de422aa59: R2
(every rule section 7 condition is computed true or false by ``check``: nowcast replay, P3d_N replay, window
leakage) and R4 (``bind-release`` writes ``l6_state_sha256`` from the verified load; no hand edit).
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


# ----------------------------------------------------------------------------- forward emit binds the nowcasts

def _nowcasts(folder, *, source=None, state="7" * 64, sha_override=None):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "nowcasts.parquet"
    pd.DataFrame({"row_key": ["atlanta|s0"], "n_own": [70.0], "n_up": [np.nan],
                  "n_ring": [np.nan]}).to_parquet(path)
    manifest = {"prev_day_source": mg2.FORWARD_PREV_DAY_SOURCE if source is None else source,
                "nowcasts_sha256": sha_override or mg2.sha256_file(path), "l6_state_sha256": state,
                "first": "2026-10-28", "last": "2026-10-28"}
    (folder / mg2.NOWCASTS_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_forward_nowcasts_need_the_bundle_source_their_sha_and_the_bound_state(tmp_path):
    binding = {"l6_state_sha256": "7" * 64}
    good = _nowcasts(tmp_path / "ok")
    assert mg2.forward_nowcasts(good, binding)["l6_state_sha256"] == "7" * 64
    cases = [(_nowcasts(tmp_path / "dev", source="D-1 replay folder, last line"), binding, "prev_day_source"),
             (_nowcasts(tmp_path / "sha", sha_override="0" * 64), binding, "not the one its manifest records"),
             (_nowcasts(tmp_path / "state", state="8" * 64), binding, "not the bound"),
             (good, {}, "records no l6_state_sha256"),
             (good, {"l6_state_sha256": "<FILL@BINDING>"}, "records no l6_state_sha256")]
    for path, bind, message in cases:
        with pytest.raises(mg2.Mg2Refused, match=message):
            mg2.forward_nowcasts(path, bind)
    bare = tmp_path / "bare" / "nowcasts.parquet"  # the IEM ``nowcast`` output writes no manifest
    bare.parent.mkdir()
    bare.write_bytes(good.read_bytes())
    with pytest.raises(mg2.Mg2Refused, match="needs nowcasts_manifest.json"):
        mg2.forward_nowcasts(bare, binding)
    iem = tmp_path / "iem"  # a manifest without prev_day_source or an L6 state
    iem.mkdir()
    (iem / "nowcasts.parquet").write_bytes(good.read_bytes())
    (iem / mg2.NOWCASTS_MANIFEST).write_text(json.dumps({"nowcasts_sha256": mg2.sha256_file(good)}))
    with pytest.raises(mg2.Mg2Refused, match="prev_day_source"):
        mg2.forward_nowcasts(iem / "nowcasts.parquet", binding)


def _emit_world(tmp_path, monkeypatch, calls):
    from weather.calibration import mg2_p3d_n
    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    rule = tmp_path / "rule.md"
    body = {"switch_hour": "13", "d0": "2026-10-28", "n_forward_dates": "45", "owner_decision_id": "NONE",
            "l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64,
            "forecast_high_source": "captured_nbm_v2_mean_07z", "own_obs_source": "captured_metar_l6_own",
            "function_sha256": "6" * 64}
    rule.write_text(f"```{mg2.RULE_BLOCK}\n" + "\n".join(f"{k}: {v}" for k, v in body.items()) + "\n```\n",
                    encoding="utf-8")
    nowcasts = _nowcasts(tmp_path / "now")
    snaps = pd.DataFrame({"row_key": ["atlanta|s0", "atlanta|s1"], "date": ["2026-10-28", "2026-09-28"],
                          "market": ["atlanta"] * 2, "local_hour": [9, 9]})
    bands = pd.DataFrame({"row_key": ["atlanta|s0", "atlanta|s1"], "band_index": [0, 0]})
    frame = pd.DataFrame({"row_key": ["atlanta|s0"], "band_index": [0], "p": [1.0]})

    def post(state, s, replay, first, last, inputs="last_in_hour"):
        calls.append(inputs)
        return {}, {}

    monkeypatch.setenv("L6_NOWCASTS", "unset")
    monkeypatch.setattr(mg2, "require_forward_parity", lambda fields: {})
    monkeypatch.setattr(mg2, "input_parity", lambda fields: {})
    monkeypatch.setattr(mg2, "verify_release", lambda *a, **k: {"l6_state_sha256": "7" * 64})
    monkeypatch.setattr(mg2, "verify_function", lambda fields: "6" * 64)
    monkeypatch.setattr(mg2, "load_part", lambda *a: {"column": "n_own", "coef": {},
                                                     "nowcasts_sha256": mg2.sha256_file(nowcasts)})
    monkeypatch.setattr(mg2_p3d_n, "load_state", lambda *a, **k: {"fit_kind": "forward", "conversion": None,
                                                                   "late_report": None})
    monkeypatch.setattr(mg2, "read_inputs", lambda root: (snaps, bands))
    monkeypatch.setattr(l6_stack, "predict", lambda *a: frame)
    monkeypatch.setattr(mg1, "predict", lambda *a: frame)
    monkeypatch.setattr(mg2, "post_records", post)
    monkeypatch.setattr(mg2, "distribution_band_frame", lambda dists, b: frame)
    monkeypatch.setattr(mg2, "compose", lambda *a: (frame, {"atlanta|s0": "pre"}))
    return dict(layout_root=tmp_path, replay_root=tmp_path, nowcasts=nowcasts, coefficients=tmp_path / "c.json",
                rule=rule, p3d_n_state=tmp_path / "p.pkl", release_binding=tmp_path / "rb.json")


def test_emit_writes_as_of_capture_vectors_forward_only(tmp_path, monkeypatch):
    calls = []
    kw = _emit_world(tmp_path, monkeypatch, calls)
    audit = mg2.emit(out=tmp_path / "fwd", first="2026-10-28", last="2026-10-28", **kw)
    assert calls == ["last_in_hour", "as_of_capture"]
    assert (tmp_path / "fwd" / mg2.ASOF_VECTORS).is_file() and audit["gate_vectors"] == mg2.ASOF_VECTORS
    assert audit["asof_capture"]["vectors_sha256"] == mg2.sha256_file(tmp_path / "fwd" / mg2.ASOF_VECTORS)
    assert audit["nowcasts_manifest"]["prev_day_source"] == mg2.FORWARD_PREV_DAY_SOURCE
    assert audit["l6_state_sha256"] == "7" * 64 and audit["outcome_files_opened"] == []
    calls.clear()
    audit = mg2.emit(out=tmp_path / "ctl", first="2026-09-28", last="2026-09-28", control=True, **kw)
    assert calls == ["last_in_hour"] and not (tmp_path / "ctl" / mg2.ASOF_VECTORS).exists()
    assert audit["gate_vectors"] is None and audit["asof_capture"] is None
    assert audit["nowcasts_manifest"] is None and audit["l6_state_sha256"] is None


def test_forward_emit_refuses_nowcasts_from_another_state_before_emitting(tmp_path, monkeypatch):
    calls = []
    kw = _emit_world(tmp_path, monkeypatch, calls)
    other = _nowcasts(tmp_path / "other", state="8" * 64)
    with pytest.raises(mg2.Mg2Refused, match="not the bound"):
        mg2.emit(out=tmp_path / "fwd", first="2026-10-28", last="2026-10-28", **dict(kw, nowcasts=other))
    assert calls == [] and not (tmp_path / "fwd").exists()


# ----------------------------------------------------------------------------- score records section 7

def test_section7_conditions_recompute_coverage_and_read_the_bound_checks():
    snaps = pd.DataFrame({"row_key": [f"k{i}" for i in range(11)], "local_hour": [8] * 10 + [20]})
    vec = pd.DataFrame({"row_key": [f"k{i}" for i in range(9)]})
    checks = {"pit_pass": True, "parser_pass": True, "replay_pass": True, "nowcast_replay_pass": True,
              "p3d_n_replay_pass": True, "window_leakage_pass": True}
    got = mg2.section7_conditions(snaps, vec, checks)  # 9 of the ten 00-16 snapshots = 0.90
    assert tuple(got) == mg2.SECTION7_CONDITIONS and all(got[k]["pass"] is True for k in got)
    for key in ("nowcast_replay_pass", "p3d_n_replay_pass", "window_leakage_pass"):  # never left unevaluated
        missing = mg2.section7_conditions(snaps, vec, {k: v for k, v in checks.items() if k != key})
        assert missing[key.replace("_pass", "")]["pass"] is False
    assert mg2.section7_conditions(snaps, vec.iloc[:8], checks)["coverage"]["pass"] is False
    for key in checks:
        bad = mg2.section7_conditions(snaps, vec, dict(checks, **{key: False}))
        assert bad[key.replace("_pass", "")]["pass"] is False
    assert mg2.section7_conditions(snaps, vec, {})["replay"]["pass"] is False
    assert mg2.section7_conditions(snaps, vec, dict(checks, pit_pass="true"))["pit"]["pass"] is False


def test_emission_checks_and_pre_look_reads_are_bound_to_the_emission(tmp_path):
    vectors = tmp_path / mg2.ASOF_VECTORS
    vectors.write_bytes(b"v")
    with pytest.raises(mg2.Mg2Refused, match="needs mg2_checks.json"):
        mg2.emission_checks(vectors, {"vectors_sha256": "a" * 64})
    (tmp_path / mg2.CHECKS).write_text(json.dumps({"emit_audit_vectors_sha256": ["b" * 64, "b" * 64]}))
    with pytest.raises(mg2.Mg2Refused, match="does not check this emission"):
        mg2.emission_checks(vectors, {"vectors_sha256": "a" * 64})
    assert mg2.emission_checks(vectors, {"vectors_sha256": "b" * 64})["emit_audit_vectors_sha256"][0] == "b" * 64
    assert mg2.pre_look_reads({"outcome_files_opened": []}) == []
    assert mg2.pre_look_reads({"outcome_files_opened": ["labels.parquet"]}) == ["labels.parquet"]
    assert mg2.pre_look_reads({}) == ["the forward emission audit does not record its outcome reads"]


def test_score_refuses_without_the_check_before_opening_any_label(tmp_path, monkeypatch):
    from weather.reporting.scorecards import dev_scorecard_data as data

    emit = tmp_path / "emit"
    emit.mkdir()
    vectors = emit / mg2.ASOF_VECTORS
    pd.DataFrame({"row_key": ["a|1"], "band_index": [0], "p": [1.0]}).to_parquet(vectors, index=False)
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps({"mode": "forward", "vectors_sha256": "c" * 64,
                                                   "asof_capture": {"vectors_sha256": mg2.sha256_file(vectors)}}),
                                       encoding="utf-8")
    layout = tmp_path / "layout"
    layout.mkdir()  # no labels or market file: score must refuse before it would open them
    pd.DataFrame({"row_key": ["a|1"], "date": ["2026-12-01"]}).to_parquet(layout / data.SNAPSHOTS_FILE, index=False)
    body = {"switch_hour": "13", "d0": "2026-12-01", "n_forward_dates": "1", "owner_decision_id": "NONE",
            "l6_coefficients_sha256": "x", "p3d_n_state_sha256": "x", "function_sha256": "x",
            "forecast_high_source": "x", "own_obs_source": "x"}
    rule = tmp_path / "rule.md"
    rule.write_text(f"```{mg2.RULE_BLOCK}\n" + "\n".join(f"{k}: {v}" for k, v in body.items()) + "\n```\n",
                    encoding="utf-8")
    monkeypatch.setattr(mg2, "require_forward_parity", lambda fields: {})
    monkeypatch.setattr(mg2, "verify_release", lambda *a, **k: {})
    monkeypatch.setattr(mg2, "verify_function", lambda fields: "x")
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), date(2026, 11, 28)))
    with pytest.raises(mg2.Mg2Refused, match="needs mg2_checks.json"):
        mg2.score(layout_root=layout, vectors=vectors, rule=rule, out=tmp_path / "out", release_binding=tmp_path,
                  today=date(2027, 6, 1))
    assert not (tmp_path / "out").exists()


# ----------------------------------------------------------------------------- prev_dmax capture order

def test_prev_dmax_from_a_capture_after_the_snapshot_is_never_served(tmp_path, monkeypatch):
    path, sha, _ = _state_file(tmp_path)
    feat = _features(4, seed=6)
    days = ("2026-10-28", "2026-10-29")
    hours = [h for h in l6.HOURS if 7 <= h <= 12][:2]
    rows = [{"row_key": feat.row_key[i], "station": "KATL", "market": "atlanta", "date": days[i // 2],
             "local_hour": hours[i % 2], "snapshot_id": f"s{i}"} for i in range(4)]
    layout = tmp_path / "layout"
    layout.mkdir()
    pd.DataFrame(rows).to_parquet(layout / "inputs_snapshots.parquet", index=False)

    def build(late):
        folders = []
        for day in days:
            folder = tmp_path / f"replay-{late}" / day
            folder.mkdir(parents=True)
            lines = [json.dumps({"snapshot_id": r["snapshot_id"],
                                 "captured_at_utc": f"{day}T{r['local_hour'] + 4:02d}:05:00+00:00", "sources": {}})
                     for r in rows if r["date"] == day]
            # D-1's last line, captured after D's first snapshot (late) or on the evening of D-1
            tail = "2026-10-29T20:00:00+00:00" if late else f"{day}T23:00:00+00:00"
            lines.append(json.dumps({"snapshot_id": "tail", "captured_at_utc": tail, "sources": {}}))
            (folder / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            folders.append(("atlanta", date.fromisoformat(day), folder))
        return folders

    seen = {}
    by_key = feat.set_index("row_key")

    def features(snapshot_rows, captured, tz, station_code, prev):
        seen.update(prev)
        return by_key.loc[[k for k, _, _ in snapshot_rows]].reset_index()

    monkeypatch.setattr(l3, "l6_captured_features", features)
    monkeypatch.setattr(l3, "routine_dmax", lambda rows, tz, day, *a, **k: 80.0)
    monkeypatch.setattr(l6, "load", lambda root: (None, {"KATL": {"timezone": "America/New_York"}}, {}))
    monkeypatch.setattr(l6, "stations", lambda sel: ["KATL"])
    for late, expected in ((True, {"2026-10-28"}), (False, {"2026-10-28", "2026-10-29"})):
        folders = build(late)
        monkeypatch.setattr(l3, "_event_folders", lambda root, f=folders: iter(f))
        seen.clear()
        manifest = mg2.captured_nowcast(layout_root=layout, replay_root=tmp_path, research_root=tmp_path,
                                        first=days[0], last=days[1], out=tmp_path / f"out-{late}",
                                        l6_state=path, l6_state_sha256=sha)
        assert set(seen) == expected
        assert manifest["stats"].get("prev_dmax_after_snapshot_days", 0) == (1 if late else 0)


def test_the_l6_state_schema_literal_is_registered_in_its_family():
    from weather.schema_families import schema_version
    from weather.schema_registry_families import installed_families

    registry = installed_families()
    assert not registry.errors
    assert schema_version("l6_own_state") == core.L6_STATE_SCHEMA
    assert registry.family_of("l6_own_state") == "l6_own_state"


# ----------------------------------------------------------------------------- R2: section 7 replays in check

def _replay_run(tmp_path, monkeypatch, sha, path, name="replay"):
    """A captured-nowcast dev-window run at the bound state, its serve features standing in for L3's."""
    feat = _features(6, seed=8)
    out = tmp_path / name
    out.mkdir()
    feat.to_parquet(out / "serve_features.parquet", index=False)
    monkeypatch.setattr(mg2, "DEV_SERVE_FEATURES_SHA256", mg2.sha256_file(out / "serve_features.parquet"))
    frame = mg2.l6_nowcast_frame(mg2.load_l6_state(path, sha), feat)
    frame.to_parquet(out / "nowcasts.parquet", index=False)
    manifest = {"first": mg2.DEV_NOWCAST_WINDOW[0], "last": mg2.DEV_NOWCAST_WINDOW[1], "l6_state_sha256": sha,
                "serve_features_sha256": mg2.sha256_file(out / "serve_features.parquet"),
                "nowcasts_sha256": mg2.sha256_file(out / "nowcasts.parquet")}
    (out / mg2.NOWCASTS_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    pin = tmp_path / f"{name}_pin.parquet"
    frame.iloc[::-1].to_parquet(pin, index=False)  # row order does not matter, values must
    return out, pin, frame


def test_nowcast_replay_must_reproduce_the_pin_at_the_bound_state(tmp_path, monkeypatch):
    path, sha, _ = _state_file(tmp_path)
    out, pin, frame = _replay_run(tmp_path, monkeypatch, sha, path)
    pin_sha = mg2.sha256_file(pin)
    assert mg2.nowcast_replay_check(out, pin, pin_sha, sha)["pass"] is True
    assert "pin does not hash" in mg2.nowcast_replay_check(out, pin, "0" * 64, sha)["problems"][0]
    assert "not '" in mg2.nowcast_replay_check(out, pin, pin_sha, "8" * 64)["problems"][0]
    moved = frame.assign(n_own=frame.n_own + np.r_[0.0, 1e-9, [0.0] * (len(frame) - 2)])
    moved.to_parquet(pin, index=False)
    assert mg2.nowcast_replay_check(out, pin, mg2.sha256_file(pin), sha)["problems"] == [
        "the replay n_own differs from the pin"]
    monkeypatch.setattr(mg2, "DEV_SERVE_FEATURES_SHA256", "f" * 64)
    assert "not L3's captured dev features" in mg2.nowcast_replay_check(out, pin, mg2.sha256_file(pin), sha)[
        "problems"][0]
    assert mg2.nowcast_replay_check(tmp_path / "absent", pin, pin_sha, sha)["pass"] is False


@pytest.mark.parametrize("change,ok", [({}, True), ({"max_abs": 2e-12}, False), ({"pass": False}, False),
                                       ({"missing": 3}, False), ({"rows": 10}, False),
                                       ({"reference": "0" * 64}, False)])
def test_p3d_n_replay_reads_the_control_comparison(tmp_path, change, ok):
    comparison = {"pass": True, "max_abs": 0.0, "missing": 0, "extra": 0, "bucket_set_mismatch": 0,
                  "rows": 12, "reference_rows": 12, "tolerance": 1e-12}
    comparison.update({k: v for k, v in change.items() if k != "reference"})
    record = {"reference_sha256": change.get("reference", mg2.P3D_N_DEV_REFERENCE_SHA256), "comparison": comparison}
    path = tmp_path / "control.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert mg2.p3d_n_replay_check(path)["pass"] is ok
    assert mg2.p3d_n_replay_check(tmp_path / "absent.json")["pass"] is False


def test_window_leakage_needs_no_outcome_read_and_an_unmodified_mg1(tmp_path):
    root = tmp_path / "repo"
    (root / mg2.MG1_FILE).parent.mkdir(parents=True)
    (root / mg2.MG1_FILE).write_text("mg1\n", encoding="utf-8")
    binding = tmp_path / "release-binding.json"
    binding.write_text(json.dumps({"files": {mg2.MG1_FILE: mg2.sha256_file(root / mg2.MG1_FILE)}}))
    clean = [{"vectors_sha256": "a", "outcome_files_opened": []}] * 2
    assert mg2.window_leakage_check(clean, binding, root=root)["pass"] is True
    assert mg2.window_leakage_check([{"outcome_files_opened": ["labels.parquet"]}], binding, root=root)["pass"] \
        is False
    assert mg2.window_leakage_check([{}], binding, root=root)["pass"] is False  # unrecorded reads fail
    (root / mg2.MG1_FILE).write_text("mg1 edited\n", encoding="utf-8")
    assert "differs from release binding" in mg2.window_leakage_check(clean, binding, root=root)["problems"][0]


@pytest.mark.spawns
def test_window_leakage_without_a_binding_compares_mg1_to_head(tmp_path):
    from tests.git_template import commit_fixture_tree

    root = tmp_path / "repo"
    (root / mg2.MG1_FILE).parent.mkdir(parents=True)
    (root / mg2.MG1_FILE).write_bytes(b"mg1\n")  # LF bytes, as the repo pins (write_text would add CR)
    commit_fixture_tree(root, cache_root=tmp_path / "git-templates", message="mg1",
                        config=("user.name=Fixture", "user.email=fixture@example.invalid", "commit.gpgSign=false"),
                        quiet=True)
    clean = [{"outcome_files_opened": []}]
    assert mg2.window_leakage_check(clean, None, root=root)["pass"] is True
    (root / mg2.MG1_FILE).write_bytes(b"mg1 edited\n")
    assert "differs from HEAD" in mg2.window_leakage_check(clean, None, root=root)["problems"][0]


def test_check_records_all_three_replays_as_booleans(tmp_path, monkeypatch):
    path, sha, _ = _state_file(tmp_path)
    replay, pin, _ = _replay_run(tmp_path, monkeypatch, sha, path)
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"reference_sha256": mg2.P3D_N_DEV_REFERENCE_SHA256, "comparison": {
        "pass": True, "max_abs": 0.0, "missing": 0, "extra": 0, "bucket_set_mismatch": 0, "rows": 3,
        "reference_rows": 3}}), encoding="utf-8")
    calls = []
    kw = _emit_world(tmp_path, monkeypatch, calls)
    snaps = pd.DataFrame({"row_key": ["atlanta|s0"], "date": ["2026-09-28"], "market": ["atlanta"],
                          "local_hour": [9], "v2_available_at": ["2026-09-28T10:00:00Z"],
                          "captured_at_utc": ["2026-09-28T13:00:00Z"], "v2_period_kind": ["maximum"]})
    bands = pd.DataFrame({"row_key": ["atlanta|s0"], "band_index": [0]})
    monkeypatch.setattr(mg2, "read_inputs", lambda root: (snaps, bands))
    monkeypatch.setattr(mg2, "window_leakage_check", lambda audits, binding=None, root=None: {
        "pass": all(a.get("outcome_files_opened") == [] for a in audits), "problems": []})
    out = tmp_path / "chk"
    result = mg2.run_check(out=out, nowcast_replay=replay, nowcast_pin=pin, nowcast_pin_sha256=mg2.sha256_file(pin),
                           l6_state_sha256=sha, p3d_n_control=control, first="2026-09-28", last="2026-09-28",
                           control=True, **kw)
    written = json.loads((out / mg2.CHECKS).read_text(encoding="utf-8"))
    for key in ("nowcast_replay_pass", "p3d_n_replay_pass", "window_leakage_pass"):
        assert written[key] is True and result[key] is True
    assert written["emit_audit_vectors_sha256"][0] == json.loads((out / mg2.EMIT_AUDIT).read_text())["vectors_sha256"]


def test_check_cli_requires_the_replay_inputs():
    base = ["check", "--layout", "l", "--replay-root", "r", "--nowcasts", "n", "--coefficients", "c",
            "--p3d-n-state", "p", "--rule", "r.md", "--out", "o", "--first", "2026-09-28", "--last", "2026-09-28"]
    extra = ["--nowcast-replay", "d", "--nowcast-pin", "p.parquet", "--nowcast-pin-sha256", "a" * 64,
             "--l6-state-sha256", "b" * 64, "--p3d-n-control", "c.json"]
    for cut in range(0, len(extra), 2):
        with pytest.raises(SystemExit):
            mg2.build_parser().parse_args(base + extra[:cut] + extra[cut + 2:])
    assert mg2.build_parser().parse_args(base + extra).p3d_n_control == "c.json"


# ----------------------------------------------------------------------------- R4: bind-release

def _bind_world(tmp_path, monkeypatch):
    from weather.calibration import mg2_p3d_n

    path, sha, _ = _state_file(tmp_path)
    part = {"column": "n_own", "coef": {"9": [0.1, 0.9, 10]}, "nowcasts_sha256": "3" * 64}
    coefficients = tmp_path / "mg2_coefficients.json"
    coefficients.write_bytes(mg2.canonical({"schema": mg2.SCHEMA, "l6_stack": part}))
    rule = tmp_path / "rule.md"
    body = {"switch_hour": "13", "d0": "2026-10-29", "n_forward_dates": "45", "owner_decision_id": "NONE",
            "l6_coefficients_sha256": mg2.part_sha(part), "p3d_n_state_sha256": "5" * 64,
            "forecast_high_source": "captured_nbm_v2_mean_07z", "own_obs_source": "captured_metar_l6_own",
            "function_sha256": "6" * 64}
    rule.write_text(f"```{mg2.RULE_BLOCK}\n" + "\n".join(f"{k}: {v}" for k, v in body.items()) + "\n```\n",
                    encoding="utf-8")
    loads = []
    monkeypatch.setattr(mg2_p3d_n, "load_state", lambda p, s, forward: loads.append((s, forward)) or {})
    monkeypatch.setattr(mg2, "verify_function", lambda fields: fields["function_sha256"])
    return dict(rule=rule, coefficients=coefficients, p3d_n_state=tmp_path / "p.pkl", l6_state=path,
                l6_state_sha256=sha), loads


@pytest.mark.spawns
def test_bind_release_records_the_verified_l6_state_and_verify_release_accepts_it(tmp_path, monkeypatch):
    kw, loads = _bind_world(tmp_path, monkeypatch)
    out = tmp_path / "bind" / "release-binding.json"
    got = mg2.bind_release(out=out, **kw)
    binding = json.loads(out.read_text(encoding="utf-8"))
    assert binding["schema"] == mg2.RELEASE_BINDING_SCHEMA
    assert binding["l6_state_sha256"] == kw["l6_state_sha256"] == got["l6_state_sha256"]
    assert loads == [("5" * 64, True)] and set(binding["files"]) == set(mg2.RELEASE_FILES)
    rule_sha, fields = mg2.read_rule(kw["rule"])
    assert mg2.verify_release(out, rule_sha, fields)["l6_state_sha256"] == kw["l6_state_sha256"]
    assert mg2.forward_nowcasts(_nowcasts(tmp_path / "now", state=kw["l6_state_sha256"]), binding)
    with pytest.raises(mg2.Mg2Refused, match="refusing to overwrite"):
        mg2.bind_release(out=out, **kw)


def test_bind_release_refuses_a_state_that_does_not_load_at_its_sha(tmp_path, monkeypatch):
    kw, _ = _bind_world(tmp_path, monkeypatch)
    out = tmp_path / "release-binding.json"
    for bad in ("0" * 64, "", "<FILL@BINDING>"):
        with pytest.raises(mg2.Mg2Refused):
            mg2.bind_release(out=out, **dict(kw, l6_state_sha256=bad))
    kw["rule"].write_text(kw["rule"].read_text(encoding="utf-8").replace("5" * 64, "PENDING"), encoding="utf-8")
    with pytest.raises(mg2.Mg2Refused, match="p3d_n_state_sha256 is not set"):
        mg2.bind_release(out=out, **kw)
    assert not out.exists()
