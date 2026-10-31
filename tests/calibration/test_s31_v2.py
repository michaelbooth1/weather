"""S31 v2 (rule_s31_v2.md, ledger row 102): k = 5 of 6 twin summary, covered-only donors, presence projection."""
from __future__ import annotations

import importlib.util
import json
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from weather import paths
from weather.calibration import s31_p0 as p0
from weather.calibration import s31_v2 as v2

_V1 = paths.REPO_ROOT / "tests" / "calibration" / "test_s31_p0.py"


def _v1_tests():
    spec = importlib.util.spec_from_file_location("_s31_p0_tests_for_v2", _V1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------- allowlist P (presence only)

def test_presence_parser_keeps_only_the_allowlist_and_never_materialises_a_float(monkeypatch):
    seen = []
    real = v2._presence_hook

    def spy(pairs):
        seen.extend(v for _, v in pairs)
        return real(pairs)

    monkeypatch.setattr(v2, "_presence_hook", spy)
    line = json.dumps({"job": "j", "run_id": "r", "ticker": "T", "end_period_ts": 1700000000,
                       "yes_bid_close": 0.37, "yes_ask_close": None, "volume": 12.5, "price": 0.4})
    got = v2.parse_presence(line)
    assert got == {"job": "j", "run_id": "r", "ticker": "T", "end_period_ts": 1700000000,
                   "yes_bid_close_present": True, "yes_ask_close_present": False}
    assert not any(isinstance(v, float) for v in seen)  # every float token became the sentinel
    assert all(v is v2.FLOAT for v in seen if not isinstance(v, (str, int, type(None))))


def _twin(tmp_path, rows):
    d = tmp_path / "twin"
    d.mkdir(exist_ok=True)
    (d / "kalshi_candles.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    jobs = sorted({r["job"] for r in rows})
    (d / "receipts.jsonl").write_text("".join(json.dumps({"job": j, "run_id": "r1", "complete": True,
                                                          "extract": "kalshi_candles.jsonl"}) + "\n"
                                              for j in jobs), encoding="utf-8")
    return d


def test_projection_is_invariant_to_every_quote_value(tmp_path):
    rng = np.random.default_rng(7)
    base = [{"job": "c:T", "run_id": "r1", "ticker": "T", "end_period_ts": 1000 + 60 * k,
             "yes_bid_close": None if k % 5 == 0 else 0.4, "yes_ask_close": None if k % 7 == 0 else 0.45}
            for k in range(50)]
    base.append({"job": "c:T", "run_id": "r0", "ticker": "T", "end_period_ts": 1, "yes_bid_close": 0.1,
                 "yes_ask_close": 0.2})  # an incomplete run: ignored
    (tmp_path / "a").mkdir()
    ref = v2.load_presence(_twin(tmp_path / "a", base), {"T"})
    for trial in range(3):
        rows = [dict(r) for r in base]
        for r in rows:
            for k in v2.CANDLE_PRESENCE:
                if r[k] is not None:
                    r[k] = float(rng.choice([5.0, -1.0, 0.0, 0.999, 123.456]))
        (tmp_path / f"b{trial}").mkdir()
        got = v2.load_presence(_twin(tmp_path / f"b{trial}", rows), {"T"})
        assert np.array_equal(got["T"][0], ref["T"][0]) and np.array_equal(got["T"][1], ref["T"][1])
    assert 1 not in set(ref["T"][0].tolist())


def test_presence_quote_matches_the_value_quote_when_values_are_valid():
    ts = np.array([0, 600, 1200, 4000], np.int64)
    bid = np.array([0.4, np.nan, 0.3, 0.2])
    ask = np.array([0.45, 0.5, 0.32, 0.25])
    q_val = v2.value_quote_at({"T": (ts, bid, ask)})
    q_pres = v2.presence_quote_at({"T": (ts, np.isfinite(bid) & np.isfinite(ask))})
    for te in (-5, 0, 300, 700, 1300, 3700, 4000, 4800, 8000):
        assert (q_val("T", te) is None) == (q_pres("T", te) is None), te
    assert q_pres("U", 100) is None


def test_read_snapshots_reads_only_the_allowlisted_columns(tmp_path):
    from weather.reporting.scorecards import dev_scorecard_data as data

    frame = pd.DataFrame({c: ["x"] for c in v2.SNAP_COLUMNS})
    frame["date"] = ["2026-08-20"]
    frame["p_market_yes"] = [0.5]
    frame["winner"] = [1]
    p = tmp_path / data.SNAPSHOTS_FILE
    frame.to_parquet(p)
    manifest = {"schema": data.LAYOUT_SCHEMA, "files": {data.SNAPSHOTS_FILE: {"sha256": p0.ls.sha256_file(p)}}}
    (tmp_path / data.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    got, _, _ = v2.read_snapshots(tmp_path)
    assert list(got.columns) == list(v2.SNAP_COLUMNS)
    manifest["files"][data.SNAPSHOTS_FILE]["sha256"] = "0" * 64
    (tmp_path / data.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(v2.V2Error, match="manifest"):
        v2.read_snapshots(tmp_path)


# ----------------------------------------------------------------------------- rule §4

def test_impute_is_the_clipped_complement():
    mids, pos = v2.impute([0.1, None, 0.2, 0.3, 0.1, 0.05])
    assert pos == 1 and math.isclose(mids[1], 0.25)
    mids, pos = v2.impute([0.3, 0.3, 0.3, 0.3, None, 0.1])
    assert mids[4] == 0.0
    assert v2.impute([0.1] * 6) == ([0.1] * 6, None)
    with pytest.raises(ValueError):
        v2.impute([None, None, 0.2, 0.2, 0.2, 0.2])


def _one_event_world():
    zs = [77.0, 79.5, 81.5, 83.5, 85.5, 88.0]
    tick = [f"KXHIGHTATL-26AUG20-B{i}" for i in range(6)]
    v0 = {"KXHIGHTATL-26AUG20": {"city": "atlanta", "date": "2026-08-20", "kept": True, "drop_reason": None,
                                 "markets": {t: {"z": z} for t, z in zip(tick, zs)}}}
    snaps = pd.DataFrame({"market": ["atlanta"] * 3, "date": ["2026-08-20"] * 3, "station": ["KATL"] * 3,
                          "captured_at_utc": ["2026-08-20T15:00:00+00:00"] * 3, "cutoff_hour": [24] * 3})
    return v0, tick, zs, snaps


def test_twin_scan_covers_five_of_six_and_refuses_four():
    v0, tick, zs, snaps = _one_event_world()
    mids = dict(zip(tick, [0.05, 0.15, 0.3, 0.3, 0.15, 0.05]))
    calls = {"i": 0}
    missing = [set(), {tick[0]}, {tick[2], tick[3]}]

    def quote_at(t, te):
        k = calls["i"] // 6
        calls["i"] += 1
        return None if t in missing[k] else mids[t]

    got = v2.twin_scan(snaps, v0, quote_at)
    assert got["covered"].tolist() == [True, True, False] and got["n_quoted"].tolist() == [6, 5, 4]
    full = p0.moments([mids[t] for t in tick], zs)
    assert math.isclose(got["mu"][0], full[0]) and math.isclose(got["sd"][0], full[1])
    imp, _ = v2.impute([None] + [mids[t] for t in tick[1:]])
    assert math.isclose(got["mu"][1], p0.moments(imp, zs)[0])
    assert np.isnan(got["mu"][2])
    assert got["missing_bin_position"] == {"lower tail": 1}
    assert got["reasons"]["fewer than five of six bins quoted at t_eff"] == 1


def test_clip_diagnostic_counts_five_bin_snapshots_clipped_to_zero():
    v0, tick, zs, snaps = _one_event_world()
    big = dict(zip(tick, [0.3, 0.3, 0.3, 0.3, 0.3, 0.05]))  # five quoted mids sum to 1.2
    small = dict(zip(tick, [0.05, 0.15, 0.3, 0.3, 0.15, 0.05]))
    calls = {"i": 0}

    def quote_at(t, te):
        k = calls["i"] // 6
        calls["i"] += 1
        if t == tick[5]:
            return None
        return (big if k == 0 else small)[t]

    scan = v2.twin_scan(snaps, v0, quote_at)
    s = v2.coverage_summary(scan)
    assert s["five_quoted"] == 3 and s["five_bin_clipped_to_zero"] == 1
    assert math.isclose(s["five_bin_clipped_share_diagnostic"], 1 / 3) and s["five_bin_share"] == 1.0


# ----------------------------------------------------------------------------- rule §5

def test_covered_donors_are_covered_other_date_same_cell_and_drop_seeds_not_snapshots():
    rows = []
    for d in ("2026-08-15", "2026-08-16", "2026-08-17"):
        for h in (9, 10):
            for k in range(3):
                rows.append((d, "atlanta", h, f"{d}T{h:02d}:{k}0", f"a|{d}|{h}|{k}", 6))
    rows.append(("2026-08-15", "atlanta", 11, "t", "lonely", 6))  # a cell with one covered date
    rows.append(("2026-08-16", "atlanta", 11, "t", "uncovered", 6))
    rows.append(("2026-08-16", "atlanta", 9, "2026-08-16T09:90", "odd-bands", 7))
    df = pd.DataFrame(rows, columns=["d", "m", "h", "t", "k", "n"])
    covered = np.array([k != "uncovered" for k in df.k])
    src, st = v2.covered_donors(df.d, df.m, df.h, df.t, df.k, df.n, covered)
    assert src.shape == (20, len(df))
    for j in range(20):
        for i in np.flatnonzero(src[j] >= 0):
            s = src[j, i]
            assert covered[s] and df.d[s] != df.d[i] and (df.m[s], df.h[s]) == (df.m[i], df.h[i])
            assert df.n[s] == df.n[i]
    lonely = int(np.flatnonzero(df.k == "lonely")[0])
    unc = int(np.flatnonzero(df.k == "uncovered")[0])
    assert (src[:, lonely] == -1).all() and (src[:, unc] == -1).all()
    assert st["cell_under_2_covered_dates_snapshots"] == 1 and st["snapshots_with_no_seed"] >= 1
    odd = int(np.flatnonzero(df.k == "odd-bands")[0])
    assert (src[:, odd] == -1).all()  # every donor has 6 bands: each seed dropped for it, counted
    assert st["dropped_pairs_band_count_mismatch"] >= 20
    src2, _ = v2.covered_donors(df.d, df.m, df.h, df.t, df.k, df.n, covered)
    assert np.array_equal(src, src2)  # fixed seeds


def test_seed_floor_drops_a_thin_seed_entirely():
    dates = np.array([f"2026-08-{15 + i % 25:02d}" for i in range(2000)])
    avail = np.ones((3, 2000), bool)
    avail[1, 500:] = False
    keep, per = v2.seed_floors(avail, dates, seeds=(1, 2, 3))
    assert keep == [0, 2] and per[1]["kept"] is False


# ----------------------------------------------------------------------------- rule §7

def test_power_at_edge_matches_clarification_1_at_planning_n():
    got = v2.power_at_edge(43, 1.0, 1.0, vif=1.7470152001888133, delta=0.04)
    assert math.isclose(got["se"], 0.019124895465067005, rel_tol=1e-9) and round(got["power"], 2) == 0.55
    assert v2.power_at_edge(0, 1.0, 1.0, vif=1.0)["power"] == 0.0


def test_rev2_vif_uses_the_circular_block_counts():
    d = np.random.default_rng(1).normal(size=43)
    got = v2.rev2_vif(d)
    assert got["n"] == 43 and got["vif"] >= 1.0 and 0.5 < got["ratio"] < 1.6


# ----------------------------------------------------------------------------- in-run power gate

def _testable(se):
    return {"candidate": "KAL-MEAN", "testable": True, "coverage": {"population_dates": 30,
                                                                    "population_snapshots": 1440},
            "p0": {"p_one_sided": 0.001, "delta": 0.3, "ci95": [0.1, 0.5]},
            "bounds": {"se_widest": se, "ci95_widest": [0.1, 0.5], "n_block_dates": 30},
            "by_block": {"x": 1}, "by_market": {"y": 1}, "diagnostic_c_deranged_placebo": {"rho": 0.1}}


def test_in_run_gate_passes_at_small_se_and_keeps_the_verdict():
    res = _testable(0.05)
    g = v2.in_run_power_gate(res)
    assert g["pass"] and g["power_at_edge"] > 0.99 and res["testable"] and res["p0"]["delta"] == 0.3


def test_in_run_gate_below_half_labels_untestable_at_edge_before_any_delta_verdict():
    se = 0.224 / 1.96 * 1.01  # power just under 0.5
    res, other = _testable(se), _testable(0.05)
    g = v2.in_run_power_gate(res)
    assert not g["pass"] and g["power_at_edge"] < 0.5
    assert res["p0"]["delta"] is None and res["p0"]["ci95"] == [None, None] and res["p0"]["p_one_sided"] == 1.0
    assert "ci95_widest" not in res["bounds"] and not set(v2.WITHHELD) & set(res)
    other["candidate"] = "KAL-WIDTH"
    v2.in_run_power_gate(other)
    out = v2.finalise_labels({"KAL-MEAN": res, "KAL-WIDTH": other})
    assert out["KAL-MEAN"]["label"] == v2.LABEL_UNTESTABLE_EDGE and out["KAL-MEAN"]["survive"] is False
    assert out["KAL-WIDTH"]["label"] != v2.LABEL_UNTESTABLE_EDGE
    missing = _testable(None)
    assert v2.in_run_power_gate(missing)["power_at_edge"] == 0.0 and missing["gated_at_edge"]


# ----------------------------------------------------------------------------- the run

def test_the_pinned_rule_and_clarification_match_the_files():
    for name, want in ((v2.RULE_FILE, v2.RULE_SHA256), (v2.CLARIFICATION1_FILE, v2.CLARIFICATION1_SHA256)):
        assert p0.ls.sha256_file(paths.docs_path(*p0.DOC_DIR, name)) == want
    assert v2.RULE_SHA256.startswith("4495b652")


def test_run_refuses_a_wrong_rule_sha(tmp_path, monkeypatch):
    monkeypatch.chdir(paths.REPO_ROOT)
    with pytest.raises(p0.P0Error, match="pinned"):
        v2.run(layout=tmp_path, out_dir=tmp_path / "out", rule_sha="0" * 64, allow_dirty=True)


def test_floors_are_gated_before_any_delta(monkeypatch):
    calls = []
    monkeypatch.setattr(v2.ms, "paired_delta", lambda *a, **k: calls.append(1) or {})
    v1 = _v1_tests()
    import tempfile
    from weather.reporting.scorecards import dev_scorecard as sc

    with tempfile.TemporaryDirectory() as td:
        lay, twin, v0_live, _ = v1._synthetic_world(pathlib.Path(td), np.random.default_rng(3))
    fit = sc.Table(lay, ["2026-08-14"] + v1.SCORED)
    score = sc.Table(lay, v1.SCORED[:10])  # 10 dates < 20: untestable on the date floor
    geo = v2.ms.band_geometry(fit)
    vals = np.where(np.arange(len(fit.snaps)) % 2 == 0, 75.0, np.nan)
    src, st = v2.covered_donors(fit.snaps.date, fit.markets, fit.local_hour, fit.snaps.captured_at_utc,
                                fit.snaps.row_key, fit.n, np.isfinite(vals))
    dates = np.array(sorted(set(score.snaps.date.astype(str))))
    res, vec = v2.p0_candidate_v2("KAL-MEAN", "C", 1, vals, fit, score, geo, v2.ms.boot_counts(len(dates), draws=10),
                                  dates, src, st)
    assert vec is None and not res["testable"] and not res["floors"]["pass"] and calls == []
    assert res["floors"]["population_dates"] == 10 and res["p0"]["p_one_sided"] == 1.0


@pytest.mark.parametrize("gated", [False, True])
def test_v2_runs_end_to_end_on_the_synthetic_world_with_k_2(tmp_path, monkeypatch, gated):
    from weather.reporting.scorecards import dev_scorecard as sc

    if gated:
        monkeypatch.setattr(v2, "POWER_MIN", 1.01)  # no realised SE can reach it: the gate must fire

    v1 = _v1_tests()
    lay, twin, v0_live, pins = v1._synthetic_world(tmp_path, np.random.default_rng(20261031))
    # Drop one bin's quotes on every third date: those snapshots are covered with five of six.
    rows = [json.loads(x) for x in (twin / "kalshi_candles.jsonl").read_text(encoding="utf-8").splitlines()]
    drop = {d for i, d in enumerate(v1.SCORED) if i % 3 == 0}
    keep = []
    for r in rows:
        d = p0.ticker_date(r["ticker"]).isoformat() if r["ticker"].startswith("KXHIGHTATL-26") else ""
        if d in drop and r["ticker"].endswith("-M2"):
            continue
        keep.append(r)
    (twin / "kalshi_candles.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
    pins["kalshi_candles.jsonl"] = p0.ls.sha256_file(twin / "kalshi_candles.jsonl")

    def build(layout):
        kal_fit = sc.Table(lay, ["2026-08-14"] + v1.SCORED)
        return "synthetic", ["2026-08-14"], v1.SCORED, kal_fit, sc.Table(lay, v1.SCORED), {"s": {"verdict": "PASS"}}

    monkeypatch.chdir(paths.REPO_ROOT)
    monkeypatch.setenv("PYTHONPATH", str(paths.REPO_ROOT / "src"))
    rule_sha = v2.RULE_SHA256
    rec = v2.run(layout=lay, out_dir=tmp_path / "out", twin_dir=twin, v0_live=v0_live, allow_dirty=True,
                 input_pins=pins, build=build, require_pythonpath=True, rule_sha=rule_sha)
    assert rec["k"] == 2 and set(rec["results"]) == {"KAL-MEAN", "KAL-WIDTH"}
    written = json.loads((tmp_path / "out" / "s31_v2.json").read_text(encoding="utf-8"))
    assert next(iter(written)) == "coverage_summary"
    head = written["coverage_summary"]
    assert head["five_quoted"] > 0 and head["five_bin_clipped_share_diagnostic"] is not None
    assert set(head["arms"]) == {"KAL-MEAN", "KAL-WIDTH"} and "dropped_pairs_band_count_mismatch" in head["donors"]
    assert rec["doc_sha256"][v2.CLARIFICATION1_FILE] == v2.CLARIFICATION1_SHA256
    assert rec["fex_outside_family"]["in_family"] is False and rec["labels"][p0.FEX_ID] == p0.LABEL_UNTESTABLE
    pop = rec["population"]
    assert pop["five_quoted"] > 0 and pop["missing_bin_position"] == {"interior": pop["five_quoted"]}
    assert pop["five_quoted"] + pop["six_quoted"] == 31 * 48
    for cid in ("KAL-MEAN", "KAL-WIDTH"):
        r = rec["results"][cid]
        assert r["donors"]["seeds_kept"] >= v2.J_MIN and len(r["donors"]["per_seed"]) == 20
        assert r["power_gate"]["realised_dates"] == r["coverage"]["population_dates"]
        if gated:
            assert rec["labels"][cid] == v2.LABEL_UNTESTABLE_EDGE and not r["power_gate"]["pass"]
            assert r["p0"]["delta"] is None and "w_gate" not in r and not set(v2.WITHHELD) & set(r)
        else:
            assert r["testable"] and r["power_gate"]["pass"], r
            assert rec["labels"][cid] in (p0.LABEL_SURVIVOR, p0.LABEL_KILL_EDGE, p0.LABEL_NULL)
