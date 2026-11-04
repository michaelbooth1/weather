"""Lane L2: the L6_G forward frame builder (MG-2 forward layout -> emitter input), on fabricated data only.

Guards: the builder and the emission path raise on an injected label, outcome, final/settled observed-high or
price/market-quote column in the layout snapshots, layout bands, nowcasts or the emitter's input frame (positive
refusals, not mere absence); the layout is accepted only for its date, re-hashed against its manifest and
stamped v2 parser version 2 (fixture manifest shaped as the receiver's ``mg2_inputs_layout/1``); the nowcasts
only under ``mg2_composite.forward_nowcasts``'s rules at the season-matched L6 state and covering the date; the
L6 part only at its canonical sha256; the builder imports neither the binding nor the receiver, and its local
re-checks accept and refuse exactly as the binding does; no date before 2026-10-29 and no rewrite. The
frame's L6 arm reproduces ``l6_stack.predict`` (the bound pre-13 arm) band for band, and MG-1's usability mask is
carried as ``covered_l6``.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
mg2_inputs = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
frame = import_or_skip_on_capture_host("weather.calibration.l6g_forward_frame")
from weather.calibration import l6g_forward_emit as emit  # noqa: E402
from weather.calibration import l6g_forward_look as look  # noqa: E402
from weather.reporting.scorecards.free_source_candidates import l6_stack  # noqa: E402

DAY = "2026-10-31"
TODAY = dt.date(2026, 11, 1)
EDGES = [("lte", 0, 70), ("range", 71, 72), ("range", 73, 74), ("range", 75, 76), ("gte", 77, 0)]
MARKETS = ("atlanta", "seattle")
COEF = {str(h): [0.3 * (h - 9), 0.4, 300] for h in (7, 8, 9, 10, 11, 12)}
INJECT = ("winner", "settlement_high", "observed_high", "final_high", "daily_max", "settled_bucket", "p_market_yes",
          "best_bid", "market_mid", "label_source", "y", "outcome")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _layout(root, *, extra=None, extra_band=None, day=DAY):
    rng = np.random.default_rng(11)
    snaps, bands = [], []
    for mk in MARKETS:
        for h in (6, 7, 8, 9, 10, 11, 12, 13):
            rk = f"{mk}|{mk}-{h}"
            cap = pd.Timestamp(f"{day} {h:02d}:20", tz="UTC")
            late = (mk, h) == ("seattle", 9)  # guidance available after capture: MG-1 unusable
            snaps.append({"row_key": rk, "snapshot_id": f"{mk}-{h}", "market": mk, "date": day, "target_date": day,
                          "local_hour": h, "captured_at_utc": cap.isoformat(),
                          "v2_available_at": (cap + pd.Timedelta(hours=1 if late else -2)).isoformat(),
                          "v2_mean": 73 + rng.normal(), "v2_stddev": 0.8 + rng.random() * 2,
                          "v2_parser_version": 2, "high_so_far": 60.0 + h, "trusted_current_max": np.nan, "guidance_physical_floor": np.nan,
                          "floor": 60.0 + h})
            bands += [{"row_key": rk, "band_index": i, "kind": k, "low": lo, "high": hi, "p_served": 0.2,
                       "date": day, "market": mk, "local_hour": h} for i, (k, lo, hi) in enumerate(EDGES)]
    s, b = pd.DataFrame(snaps), pd.DataFrame(bands)
    if extra:
        s[extra] = 1.0
    if extra_band:
        b[extra_band] = 1.0
    root.mkdir(parents=True, exist_ok=True)
    s.to_parquet(root / "inputs_snapshots.parquet", index=False)
    b.to_parquet(root / "inputs_bands.parquet", index=False)
    manifest = {"schema": mg2_inputs.LAYOUT_SCHEMA, "target_date": day, "snapshots": len(s),
                "files": {n: {"sha256": _sha(root / n), "rows": r}
                          for n, r in (("inputs_snapshots.parquet", len(s)), ("inputs_bands.parquet", len(b)))}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return s, b


def _nowcasts(root, snaps, *, extra=None, state=None, source=None, first=DAY, last=DAY):
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(12)
    n = pd.DataFrame({"row_key": snaps.row_key, "n_own": 74 + rng.normal(size=len(snaps)), "n_up": np.nan,
                      "n_ring": np.nan})
    n.loc[n.row_key == "atlanta|atlanta-10", "n_own"] = np.nan  # no nowcast: the L6 arm is MG-1 there
    if extra:
        n[extra] = 1.0
    path = root / "nowcasts.parquet"
    n.to_parquet(path, index=False)
    (root / mg2.NOWCASTS_MANIFEST).write_text(json.dumps({
        "prev_day_source": source or mg2.FORWARD_PREV_DAY_SOURCE, "nowcasts_sha256": _sha(path),
        "l6_state_sha256": state or frame.L6_STATE_SHA256, "first": first, "last": last}))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    coef = tmp_path / "coefficients.json"
    part = {"column": "n_own", "coef": COEF}
    coef.write_text(json.dumps({"l6_stack": part}))
    monkeypatch.setattr(frame, "L6_PART_SHA256", mg2.part_sha(part))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"state": {f"h{h:02d}": {"a": 0.1, "b": 0.2} for h in look.HOURS}}))
    monkeypatch.setattr(look, "STATE_SHA256", _sha(state))
    snaps, bands = _layout(tmp_path / "layout")
    now = _nowcasts(tmp_path / "now", snaps)
    rec = tmp_path / "gefs" / DAY
    rec.mkdir(parents=True)
    lm = {mk: {f"h{h:02d}": 75.0 for h in look.HOURS} for mk in look.MARKETS}
    (rec / "manifest.json").write_text(json.dumps({
        "schema": look.RECORDER_SCHEMA, "date": DAY, "recorder_sha256": emit.RECORDER_SHA256,
        "module_sha256": emit.FETCH_MODULE_SHA256, "ok": 217, look.DECIDING_TABLE: lm, look.REPORTED_TABLE: lm}))
    return {"tmp": tmp_path, "coef": coef, "state": state, "snaps": snaps, "bands": bands, "now": now,
            "layout": tmp_path / "layout", "recorder": tmp_path / "gefs"}


def _build(env, **over):
    kw = dict(day=DAY, layout_root=env["layout"], nowcasts=env["now"], coefficients=env["coef"],
              out_dir=env["tmp"] / "frames")
    kw.update(over)
    return frame.build(**kw)


def _run(env, **over):
    kw = dict(day=DAY, layout_root=env["layout"], nowcasts=env["now"], coefficients=env["coef"],
              frame_root=env["tmp"] / "frames", state=env["state"], recorder_root=env["recorder"],
              out_root=env["tmp"] / "ledger", today=TODAY)
    kw.update(over)
    return frame.run(**kw)


def test_frame_reproduces_the_bound_l6_arm(env, monkeypatch):
    m = _build(env)
    assert m["snapshots"] == 16 and m["covered_l6"] == 15 and m["outcome_files_opened"] == []
    s = pd.read_parquet(env["tmp"] / "frames" / DAY / frame.SNAPSHOTS_OUT)
    assert tuple(s.columns) == emit.SNAPSHOT_COLUMNS and not s.set_index("snapshot_id").covered_l6["seattle|seattle-9"]
    monkeypatch.setenv("L6_NOWCASTS", str(env["now"]))
    l6_stack._CACHE.clear()
    want = l6_stack.predict({"column": "n_own", "coef": {int(h): tuple(v) for h, v in COEF.items()}},
                            env["snaps"], env["bands"])
    l6_stack._CACHE.clear()
    rec = _run(env, frame_root=env["tmp"] / "frames2")
    assert rec["snapshots"] == 12  # h07-h12 x 2 markets
    got = pd.read_parquet(env["tmp"] / "ledger" / "vectors" / f"{DAY}.parquet")
    both = got[got.covered_l6].merge(want, left_on=["snapshot_id", "band_index"], right_on=["row_key", "band_index"],
                                     how="left", validate="one_to_one")
    assert len(both) == 55 and both.p.notna().all()
    assert np.max(np.abs(both.p_l6.to_numpy() - both.p.to_numpy())) <= 1e-12
    assert "seattle|seattle-9" not in set(want.row_key)


@pytest.mark.parametrize("col", INJECT)
def test_builder_refuses_injected_snapshot_columns(env, col):
    _layout(env["layout"], extra=col)
    with pytest.raises(frame.FrameError, match="outcome-blind"):
        _build(env)
    assert not (env["tmp"] / "frames").exists()


@pytest.mark.parametrize("where", ["bands", "nowcasts"])
def test_builder_refuses_injected_band_and_nowcast_columns(env, where):
    if where == "bands":
        _layout(env["layout"], extra_band="settlement_bucket")
    else:
        _nowcasts(env["tmp"] / "now", env["snaps"], extra="observed_high")
    with pytest.raises(frame.FrameError, match="outcome-blind"):
        _build(env)


@pytest.mark.parametrize("col", INJECT)
def test_emission_path_refuses_injected_columns(env, col):
    _build(env)
    d = env["tmp"] / "frames" / DAY
    s = pd.read_parquet(d / frame.SNAPSHOTS_OUT)
    s[col] = 1.0
    s.to_parquet(d / frame.SNAPSHOTS_OUT, index=False)
    with pytest.raises(frame.FrameError, match="outcome-blind"):
        frame.emit_frame_files(day=DAY, frame_dir=d, state=env["state"], recorder_root=env["recorder"],
                               out_root=env["tmp"] / "ledger", today=TODAY)
    assert not (env["tmp"] / "ledger").exists()


@pytest.mark.parametrize("col", ["winner", "settlement_high", "settled_bucket", "p_market_yes", "best_bid",
                                 "market_mid", "label_source", "y", "outcome"])
def test_emitter_itself_refuses_injected_columns(env, col):
    _build(env)
    d = env["tmp"] / "frames" / DAY
    s = pd.read_parquet(d / frame.SNAPSHOTS_OUT)
    s[col] = 1.0
    s.to_parquet(d / frame.SNAPSHOTS_OUT, index=False)
    with pytest.raises(emit.EmitError, match="outcome-blind"):
        emit.emit_day(day=DAY, snapshots=d / frame.SNAPSHOTS_OUT, bands=d / frame.BANDS_OUT, state=env["state"],
                      recorder_root=env["recorder"], out_root=env["tmp"] / "ledger", today=TODAY)


@pytest.mark.parametrize("over, match", [({"state": "0" * 64}, "L6 state"), ({"source": "iem"}, "prev_day_source"),
                                         ({"first": "2026-11-01", "last": "2026-11-01"}, "cover")])
def test_nowcasts_refused_off_the_bound_state_source_or_date(env, over, match):
    _nowcasts(env["tmp"] / "now", env["snaps"], **over)
    with pytest.raises(frame.FrameError, match=match):
        _build(env)


def test_nowcasts_file_must_be_its_manifests(env):
    pd.DataFrame({"row_key": ["x"], "n_own": [1.0]}).to_parquet(env["now"], index=False)
    with pytest.raises(frame.FrameError, match="manifest"):
        _build(env)


def test_coefficients_and_layout_pins(env, monkeypatch):
    monkeypatch.setattr(frame, "L6_PART_SHA256", "0" * 64)
    with pytest.raises(frame.FrameError, match="sha"):
        _build(env)
    monkeypatch.undo()
    monkeypatch.setattr(look, "STATE_SHA256", _sha(env["state"]))
    part = {"column": "n_own", "coef": COEF}
    monkeypatch.setattr(frame, "L6_PART_SHA256", mg2.part_sha(part))
    pd.read_parquet(env["layout"] / "inputs_bands.parquet").head(3).to_parquet(env["layout"] / "inputs_bands.parquet")
    with pytest.raises(frame.FrameError, match="manifest"):
        _build(env)
    _layout(env["layout"], day="2026-11-01")
    with pytest.raises(frame.FrameError, match="layout"):
        _build(env)
    s, _ = _layout(env["layout"])
    s.assign(v2_parser_version=1).to_parquet(env["layout"] / "inputs_snapshots.parquet", index=False)
    m = json.loads((env["layout"] / "manifest.json").read_text())
    m["files"]["inputs_snapshots.parquet"]["sha256"] = _sha(env["layout"] / "inputs_snapshots.parquet")
    (env["layout"] / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(frame.FrameError, match="parser version"):
        _build(env)


def test_local_checks_agree_with_the_binding(env, monkeypatch):
    """The builder may not import the MG-2 binding; its two re-checks must accept and refuse exactly as it does."""
    assert frame.NOWCASTS_MANIFEST == mg2.NOWCASTS_MANIFEST
    assert frame.FORWARD_PREV_DAY_SOURCE == mg2.FORWARD_PREV_DAY_SOURCE
    assert frame.L6_PART_KEY == mg2.COEF_PARTS["l6"]
    for part in ({"column": "n_own", "coef": COEF}, {"b": [1, 2.5], "a": {"x": None}}):
        assert frame.part_sha256(part) == mg2.part_sha(part)
    part = mg2.load_part(env["coef"], "l6", frame.L6_PART_SHA256)
    assert frame.load_l6_part(env["coef"]) == (part["column"], {int(h): (v[0], v[1]) for h, v in part["coef"].items()})
    binding = {"l6_state_sha256": frame.L6_STATE_SHA256}
    assert frame.nowcasts_info(env["now"]) == mg2.forward_nowcasts(env["now"], binding)
    for over in ({"state": "0" * 64}, {"source": "iem"}):
        _nowcasts(env["tmp"] / "now", env["snaps"], **over)
        with pytest.raises(mg2.Mg2Refused):
            mg2.forward_nowcasts(env["now"], binding)
        with pytest.raises(frame.FrameError):
            frame.nowcasts_info(env["now"])
    monkeypatch.setattr(frame, "L6_PART_SHA256", "0" * 64)
    with pytest.raises(mg2.Mg2Refused):
        mg2.load_part(env["coef"], "l6", "0" * 64)
    with pytest.raises(frame.FrameError):
        frame.load_l6_part(env["coef"])


def test_builder_imports_neither_the_binding_nor_the_receiver():
    import ast

    tree = ast.parse(Path(frame.__file__).read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert not any("mg2_composite" in m or "mg2_inputs" in m for m in mods)


def test_no_backfill_and_no_rewrite(env):
    with pytest.raises(frame.FrameError, match="never backfilled"):
        _build(env, day="2026-10-28")
    _build(env)
    with pytest.raises(frame.FrameError, match="never rewritten"):
        _build(env)
