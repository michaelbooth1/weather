"""Lane L6 upstream-observation screen: fetch windows, point-in-time features, stacking, fail-closed import.

Guards: AGENT_CONTEXT cutoff semantics (observation instant, station-local date, nothing after emission);
lane rules 2026-10-24 (no row after 2026-09-29, research module fails closed on a production import).
"""
from __future__ import annotations

import gzip
import json
from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from weather.calibration import upstream_obs_screen as scr
from weather.sources.free_screens import common, iem_upstream as up

TZ = "America/Chicago"


def test_windows_never_pass_local_midnight_ending_dev_last():
    wins = up.windows(TZ)
    assert [a.year for a, _ in wins[:5]] == list(up.TRAIN_YEARS)
    assert wins[-1][1] == common.local_day_end_utc(TZ)
    assert all(b <= common.local_day_end_utc(TZ) for _, b in wins)
    url = up.request_url("ATL", *wins[-1])
    assert "report_type=3" in url and "report_type=4" in url and "ets=2026-09-30T05%3A00Z" in url


def test_geometry_and_angle_helpers():
    assert up.ang_diff(350, 10) == pytest.approx(20)
    assert up.bearing_deg((30.0, -97.0), (31.0, -97.0)) == pytest.approx(0, abs=1e-6)
    assert up.bearing_deg((30.0, -97.0), (30.0, -96.0)) == pytest.approx(90, abs=0.5)
    assert up.haversine_km((30.0, -97.0), (31.0, -97.0)) == pytest.approx(111.2, abs=0.5)


def _csv(rows):
    head = "station,valid," + ",".join(up.FIELDS)
    lines = [head] + [",".join(str(x) for x in r) for r in rows]
    return ("\n".join(lines) + "\n").encode()


def _row(sid, valid, t, td=60, d=180, s=10, sky="CLR", lvl="M", metar=None):
    return [sid, valid, t, td, d, s, sky, "M", "M", lvl, "M", "M", metar or f"K{sid} 000000Z RMK AO2"]


def _write_source(root, files):
    src = root / up.SOURCE
    receipts = common.ReceiptLog(src)
    for i, (sid, role, market, body) in enumerate(files):
        rel, sha = common.store_gzip(src, f"{sid}_{i}.csv.gz", body)
        receipts.record({"key": f"{sid}|{i}", "file": rel, "sha256": sha, "status": 200, "bytes": len(body),
                         "rows": 0, "station": sid, "role": role, "market": market})
    return src


def _fixture(tmp_path):
    # Market KAUS reports at :53 (routine) plus one special; ring station RND 90 km south (bearing 180).
    m_rows, r_rows = [], []
    for day in ("2026-08-10", "2026-08-11"):
        for h in range(0, 24):
            valid = pd.Timestamp(f"{day} {h:02d}:53", tz=TZ).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")
            m_rows.append(_row("AUS", valid, 70 + h * 0.5, metar=f"KAUS 000000Z RMK AO2 T0{int(round((70 + h * .5 - 32) / 1.8 * 10)):03d}0150"))
            rv = pd.Timestamp(f"{day} {h:02d}:55", tz=TZ).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")
            r_rows.append(_row("RND", rv, 75 + h * 0.5, sky="OVC", lvl="1500"))
    # a special after the 09:30 cutoff carrying a huge value must never enter the 09:30 features
    late = pd.Timestamp("2026-08-11 09:35", tz=TZ).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")
    m_rows.append(_row("AUS", late, 120, metar="KAUS 000000Z RMK AO2"))
    _write_source(tmp_path, [("AUS", "market", "austin", _csv(m_rows)), ("RND", "ring", "austin", _csv(r_rows))])
    sel = {"markets": {"KAUS": {"market": "austin", "lat": 30.18, "lon": -97.68, "timezone": TZ,
                                "selected": [{"sid": "RND", "bearing_deg": 180.0, "dist_km": 90.0,
                                              "upwind_prevailing": True}]}}}
    (tmp_path / up.SOURCE / "selection.json").write_text(json.dumps(sel), encoding="utf-8")
    up.build(tmp_path)
    return tmp_path


def test_build_parses_cover_ceiling_tgroup_and_refuses_late_rows(tmp_path):
    root = _fixture(tmp_path)
    obs = pd.read_parquet(root / up.SOURCE / "obs.parquet")
    ring = obs[obs.role == "ring"]
    assert (ring.cover == 1.0).all() and (ring.ceiling_ft == 1500).all()
    mk = obs[(obs.role == "market") & obs.tgroup_f.notna()]
    assert np.allclose(mk.tgroup_f, mk.tmpf, atol=0.2)
    bad = [_row("AUS", "2026-09-30 06:00", 70)]
    _write_source(tmp_path, [("AUS", "market", "austin", _csv(bad))])
    with pytest.raises(AssertionError):
        up.build(tmp_path)


def test_features_are_point_in_time(tmp_path):
    root = _fixture(tmp_path)
    obs, sel, _ = scr.load(root)
    m = sel["markets"]["KAUS"] if "markets" in sel else sel["KAUS"]
    g, dmax = scr.market_series(obs, "KAUS", TZ)
    q = pd.DataFrame({"t_utc": [pd.Timestamp("2026-08-11 09:30", tz=TZ).tz_convert("UTC")],
                      "local_date": ["2026-08-11"]})
    f = scr.features(q, obs, m, "KAUS", TZ, 0, g, dmax).iloc[0]
    # latest usable market row: 08:53 (09:53 not yet valid; 09:35 special valid but not until 09:45)
    assert f.t == pytest.approx(74.0, abs=0.2)
    assert f.r == pytest.approx(74.0, abs=0.2)          # running max of the same local date only
    assert f.tend3 == pytest.approx(1.5, abs=0.2)       # 05:53 value 72.5
    # ring row 08:55 is usable at 09:15 (valid + 20 min) -> dT = 79.0 - 74.0
    assert f.ring_dt == pytest.approx(5.0, abs=0.2)
    assert f.prev_dmax == pytest.approx(scr.half_up(81.5))
    # wind from 180 at both sites: the south ring station is fully upwind
    assert f.uw_dt == pytest.approx(5.0, abs=0.2) and f.adv > 0


def test_cluster_ci_is_deterministic():
    d = np.r_[np.ones(10), -np.ones(10)]
    c = np.repeat(np.arange(10), 2)
    assert scr.cluster_ci(d, c) == scr.cluster_ci(d, c)
    assert scr.cluster_ci(d, c)[0] == pytest.approx(0.0)


def test_stack_fits_per_hour_and_keeps_mg1_elsewhere(tmp_path, monkeypatch):
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    rng = np.random.default_rng(0)
    n = 600
    snaps = pd.DataFrame({"row_key": [f"k{i}" for i in range(n)], "local_hour": np.where(np.arange(n) < 300, 8, 14),
                          "v2_mean": 90.0, "v2_stddev": 2.0, "v2_available_at": "2026-08-01T00:00:00Z",
                          "captured_at_utc": "2026-08-01T13:00:00Z", "floor": 70.0})
    truth = 90 + rng.normal(0, 2, n)
    nowc = pd.DataFrame({"row_key": snaps.row_key, "n_own": truth, "n_up": truth})
    path = tmp_path / "nowcasts.parquet"
    nowc.to_parquet(path, index=False)
    monkeypatch.setenv("L6_NOWCASTS", str(path))
    l6_stack._CACHE.clear()
    bands = pd.DataFrame({"row_key": np.repeat(snaps.row_key, 2), "band_index": np.tile([0, 1], n),
                          "kind": np.tile(["lte", "gte"], n), "low": np.tile([np.nan, 91.0], n),
                          "high": np.tile([90.0, np.nan], n)})
    winner = (truth >= 90.5).astype(int)
    labels = pd.DataFrame({"row_key": snaps.row_key, "winner": winner})
    state = l6_stack.fit({"snapshots": snaps, "bands": bands, "labels": labels}, "n_up", "t")
    assert set(state["coef"]) == {8}
    a, b, cnt = state["coef"][8]
    assert 0.0 <= b <= 1.0 and cnt == 300
    pred = l6_stack.predict(state, snaps, bands)
    from weather.reporting.scorecards.free_source_candidates import mg1

    base = mg1.predict(snaps, bands, None)
    late = pred.row_key.isin(snaps.row_key[snaps.local_hour == 14])
    assert np.allclose(pred.p[late].to_numpy(), base.p[late].to_numpy())


def test_production_import_fails_closed(monkeypatch):
    import importlib
    import sys

    sys.modules.pop("weather.calibration.upstream_obs_screen", None)
    code = "import weather.calibration.upstream_obs_screen"
    with pytest.raises(ImportError):
        exec(compile(code, "<prod>", "exec"), {"__name__": "weather.operations.fake_loop"})
    sys.modules.pop("weather.calibration.upstream_obs_screen", None)
    importlib.import_module("weather.calibration.upstream_obs_screen")
