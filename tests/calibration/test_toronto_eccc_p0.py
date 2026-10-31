"""Toronto ECCC GEM / citypage market P0 (lane L8, 2026-10-30; rule b8718b46, dev-window ledger row 90).

Guards: the record reader (a non-``ok`` source or an out-of-range value gives no value); capture-time coverage
(a receipt after capture, a missing receipt, hours outside 07..12); the replay scan (sha-pinned, capture date ==
target date, last complete record wins, a truncated line skipped); the tape rule (native °C only, book_time <=
capture, a partition, the displayed-price rule); the pinned WU labels; the outcome-free selection check (reads no
label or price, never overwrites); the constants; and the whole run on a synthetic Toronto table (a planted
type C signal survives and reaches the w gate, a null one is a KILL, no overwrite); and amendment 1's
--controls-only mode (w = 0 identity, row 77 reproduction, synthetic SYN+ / SYN-, KILL STANDS vs VOID).
"""
import hashlib
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    te = importlib.import_module("weather.calibration.toronto_eccc_p0")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [-999, 20, 22, 24, 26], [19, 21, 23, 25, 999]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _rec(sid, cap="2026-08-20T13:00:00+00:00", gem=24.5, city=25.0, fetched="2026-08-20T12:50:00+00:00",
         gem_ok=True, city_ok=True):
    return {"snapshot_id": sid, "captured_at_utc": cap, "recorded_distribution": {"24": 0.5, "25": 0.5},
            "sources": {
                "eccc_gem": {"ok": gem_ok, "fetched_at": fetched,
                             "data": {"day_model_highs": {"gem_seamless": gem, "gem_global": 99.0},
                                      "day_max_native": 98.0}},
                "eccc_citypage": {"ok": city_ok, "fetched_at": fetched,
                                  "data": {"forecast_high_native": city, "current_temp_native": 97.0}},
                "metar": {"ok": True, "data": {"rows": [
                    {"report_time": "2026-08-20T12:00:00Z", "raw": "CYYZ 201200Z T02110150", "temp_c": 21},
                    {"report_time": "2026-08-20T14:00:00Z", "raw": "CYYZ 201400Z T02610150", "temp_c": 26}]}}}}


def test_record_values_reads_the_pinned_fields_only():
    v = te.record_values(_rec("a"))
    assert v == {"gem": 24.5, "rc_gem": "2026-08-20T12:50:00+00:00", "city": 25.0,
                 "rc_city": "2026-08-20T12:50:00+00:00"}
    v = te.record_values(_rec("a", gem_ok=False, city=75.0))
    assert np.isnan(v["gem"]) and v["rc_gem"] is None and np.isnan(v["city"])  # 75 is outside [-40, 50] °C
    assert np.isnan(te.record_values({"sources": {}})["city"])


def test_metar_floor_uses_reports_up_to_capture_only():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tc = datetime.fromisoformat("2026-08-20T13:00:00+00:00")
    assert te.metar_floor(_rec("a"), tc, tc.date(), ZoneInfo(te.TZ)) == 21.1


def test_candidate_values_coverage_rules():
    snaps = pd.DataFrame({"row_key": ["t|a", "t|b", "t|c", "t|d"], "local_hour": [9, 9, 9, 13],
                          "captured_at_utc": ["2026-08-20T13:00:00+00:00"] * 4})
    feats = pd.DataFrame({"row_key": ["t|a", "t|b", "t|c", "t|d"], "gem": [24.0] * 4, "city": [25.0] * 4,
                          "rc_gem": ["2026-08-20T12:00:00+00:00", "2026-08-20T13:30:00+00:00", None,
                                     "2026-08-20T12:00:00+00:00"],
                          "rc_city": ["2026-08-20T12:00:00+00:00"] * 4})
    v = te.candidate_values(snaps, feats)
    g, c = v["GEM-SEAMLESS"], v["CITYPAGE-FH"]
    assert g[0] == 24.0 and np.isnan(g[1]) and np.isnan(g[2]) and np.isnan(g[3])  # after capture, none, 13h
    assert c[:3].tolist() == [25.0, 25.0, 25.0] and np.isnan(c[3])


def _replay(tmp_path, monkeypatch, lines_by_slug):
    root = tmp_path / "replay"
    sums = []
    for slug, lines in lines_by_slug.items():
        d = root / "snapshots" / slug
        d.mkdir(parents=True)
        body = ("\n".join(lines) + "\n").encode("utf-8")
        (d / "replay_inputs.jsonl").write_bytes(body)
        sums.append(f"{_sha(body)}  snapshots/{slug}/replay_inputs.jsonl")
    s = ("\n".join(sums) + "\n").encode()
    (root / "SHA256SUMS").write_bytes(s)
    monkeypatch.setattr(te, "REPLAY_SUMS_SHA256", _sha(s))
    return root


def test_extract_filters_dates_hours_and_dedupes(tmp_path, monkeypatch):
    slug = "highest-temperature-in-toronto-on-august-20-2026"
    lines = [json.dumps(_rec("s1", gem=20.0)), json.dumps(_rec("s2", cap="2026-08-20T20:00:00+00:00")),
             json.dumps(_rec("s3", cap="2026-08-21T05:00:00+00:00")), '{"snapshot_id": "s1", "trunc',
             json.dumps(_rec("s1", gem=21.0))]
    root = _replay(tmp_path, monkeypatch, {slug: lines,
                                           "highest-temperature-in-toronto-on-september-30-2026": lines[:1]})
    frame, malformed, stats = te.extract(root)
    assert frame.row_key.tolist() == ["toronto|s1"] and frame.gem.tolist() == [21.0]  # last record wins
    assert frame.local_hour.tolist() == [9] and frame.F.tolist() == [21.1]
    assert len(malformed) == 1 and stats["capture_not_target_date"] == 1  # s3 is local 08-21 01h
    assert stats["duplicate_records_dropped"] == 1  # s2 is 16h local, outside 07..12
    (root / "snapshots" / slug / "replay_inputs.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(te.TorontoEcccError, match="does not match SHA256SUMS"):
        te.extract(root)
    monkeypatch.setattr(te, "REPLAY_SUMS_SHA256", "0" * 64)
    with pytest.raises(te.TorontoEcccError, match="not the pinned"):
        te.extract(root)


def test_selection_check_is_outcome_free_and_never_overwrites(tmp_path, monkeypatch):
    slug = "highest-temperature-in-toronto-on-august-20-2026"
    lines = [json.dumps(_rec("s1")), json.dumps(_rec("s2", cap="2026-08-20T20:00:00+00:00", city=None)),
             json.dumps(_rec("s3", cap="2026-08-20T05:00:00+00:00", fetched="2026-08-20T06:00:00+00:00"))]
    root = _replay(tmp_path, monkeypatch, {slug: lines})

    def boom(*a, **k):
        raise AssertionError("selection check read a label or a price")

    monkeypatch.setattr(te, "load_labels", boom)
    monkeypatch.setattr(te, "market_vectors", boom)
    rec = te.selection_check(replay_root=root, out_dir=tmp_path / "sel")
    assert rec["snapshots"] == 3 and rec["n_dates"] == 1
    assert rec["per_block"]["07-12"] == {"snapshots": 1, "covered_GEM-SEAMLESS": 1, "covered_CITYPAGE-FH": 1}
    assert rec["per_block"]["13-16"] == {"snapshots": 1, "covered_GEM-SEAMLESS": 1, "covered_CITYPAGE-FH": 0}
    assert rec["per_block"]["00-06"]["covered_GEM-SEAMLESS"] == 0  # receipt after capture
    with pytest.raises(te.TorontoEcccError, match="overwrite"):
        te.selection_check(replay_root=root, out_dir=tmp_path / "sel")


def _tape_row(cap, book, label, kind, lo, hi, outcome, bid, ask, last="", mid="", unit="C"):
    return {"captured_at_utc": cap, "book_time_utc": book, "range_label": label, "bin_kind": kind,
            "bin_value": lo, "bin_value_hi": hi, "unit": unit, "outcome": outcome, "best_bid": bid,
            "best_ask": ask, "midpoint": mid, "gamma_last_trade_price": last}


def _group(cap="2026-08-20T12:58:00+00:00", book="2026-08-20T12:57:00+00:00", unit="C"):
    rows = [_tape_row(cap, book, "19°C or below", "lte", "19", "19", "yes", "0.08", "0.12", unit=unit),
            _tape_row(cap, book, "20°C", "eq", "20", "20", "yes", "0.30", "0.36", unit=unit),
            _tape_row(cap, book, "21°C or higher", "gte", "21", "21", "yes", "0.20", "0.60", last="0.55",
                      unit=unit)]
    return pd.DataFrame(rows)


def test_tape_rule_units_partition_and_price():
    from datetime import datetime

    tc = datetime.fromisoformat("2026-08-20T13:00:00+00:00")
    (keys, p), why = te.group_vector(_group(), tc)
    assert why is None and keys == [("lte", -999, 19), ("eq", 20, 20), ("gte", 21, 999)]
    assert p == pytest.approx([0.10, 0.33, 0.55])  # wide spread -> gamma last trade
    assert te.group_vector(_group(book="2026-08-20T13:05:00+00:00"), tc) == (None, "book_after_capture")
    assert te.group_vector(_group().iloc[[0, 2]], tc) == (None, "not_partition")
    with pytest.raises(te.TorontoEcccError, match="not native C"):
        te.group_vector(_group(unit="F"), tc)
    assert te.displayed({"best_bid": "", "best_ask": "0.05", "gamma_last_trade_price": "", "midpoint": ""}) \
        == pytest.approx(0.025)  # a missing bid counts as 0


def test_market_vectors_pinned_and_capture_time(tmp_path, monkeypatch):
    root = tmp_path / "tapes"
    name = "highest-temperature-in-toronto-on-august-20-2026/order_books_summary.csv"
    (root / name).parent.mkdir(parents=True)
    g = pd.concat([_group(), _group(cap="2026-08-20T13:10:00+00:00", book="2026-08-20T13:09:00+00:00")])
    g.to_csv(root / name, index=False)
    s = f"{_sha((root / name).read_bytes())}  {name}\n".encode()
    (root / "SHA256SUMS").write_bytes(s)
    monkeypatch.setattr(te, "TAPE_SUMS_SHA256", _sha(s))
    snaps = pd.DataFrame({"row_key": ["toronto|a", "toronto|b"], "date": ["2026-08-20"] * 2,
                          "captured_at_utc": ["2026-08-20T13:00:00+00:00", "2026-08-20T12:00:00+00:00"]})
    mk, reasons = te.market_vectors(root, snaps)
    assert list(mk) == ["toronto|a"] and reasons == {"drop:no_group_within_10min": 1}
    late = snaps.assign(date="2026-09-30")
    with pytest.raises(te.TorontoEcccError, match="after 2026-09-29"):
        te.market_vectors(root, late)


def test_load_labels_pinned_native_c(tmp_path):
    f = tmp_path / "wu.csv"
    f.write_text("local_date,temperature_unit,max_temp_native\n2026-08-20,C,24\n2026-09-30,C,99\n"
                 "2026-07-01,C,30\n", encoding="utf-8")
    files = (("wu.csv", _sha(f.read_bytes())),)
    assert te.load_labels(tmp_path, files) == {"2026-08-20": 24}
    with pytest.raises(te.TorontoEcccError, match="not the pinned"):
        te.load_labels(tmp_path, (("wu.csv", "0" * 64),))
    f.write_text("local_date,temperature_unit,max_temp_native\n2026-08-20,F,75\n", encoding="utf-8")
    with pytest.raises(te.TorontoEcccError, match="label unit"):
        te.load_labels(tmp_path, (("wu.csv", _sha(f.read_bytes())),))


def test_constants_and_block():
    assert te.RULE_SHA256.startswith("b8718b46") and te.LEDGER_ROW == 90
    assert [c[:3] for c in te.CANDIDATES] == [("GEM-SEAMLESS", "C", 1), ("CITYPAGE-FH", "C", 1)]
    assert te.mg.BLOCKS["07-12"] == (7, 12) == te.HOURS and te.W_BLOCK == "07-12"
    assert (te.FIRST.isoformat(), te.BURN_LAST.isoformat(), te.LAST.isoformat()) == \
        ("2026-08-01", "2026-08-14", "2026-09-29")


class FakeTable:
    brier = sc.Table.brier
    log_score = sc.Table.log_score
    cells = sc.Table.cells

    def __init__(self, frame, dates):
        f = frame[frame.date.isin(dates)].reset_index(drop=True)
        self.snaps = f[["row_key", "date", "captured_at_utc", "market", "local_hour"]].copy()
        k = len(f)
        self.n = np.full(k, 5)
        self.offsets = np.arange(k) * 5
        self.band_snap = np.repeat(np.arange(k), 5)
        self.snap_pos = pd.Series(np.arange(k), index=f.row_key.to_numpy())
        self.bands = pd.DataFrame({"band_index": np.tile(np.arange(5), k), "kind": KINDS * k,
                                   "low": LOWS * k, "high": HIGHS * k})
        self.p_market = np.concatenate(f.pm.to_list())
        self.y = np.concatenate([np.eye(5)[w] for w in f.winner])
        self.local_hour = f.local_hour.to_numpy(int)
        self.markets = f.market.to_numpy()
        self.x_info = f.x_info.to_numpy(float)
        self.impossible = np.zeros(len(self.y), bool)
        keys = sorted(set(zip(f.date, f.market)))
        index = {key: i for i, key in enumerate(keys)}
        self.keys = keys
        self.cell = np.array([index[key] for key in zip(f.date, f.market)], int)
        self.w = sc.crossed_weights([key[0] for key in keys], [key[1] for key in keys])
        self.w_date = sc.crossed_weights([key[0] for key in keys], ["all"] * len(keys))


CENTRES = np.array([19.0, 20.5, 22.5, 24.5, 26.0])


def _frame(seed=11, n_dates=40):
    """Flat-ish markets; the winner is near a value the candidate sees (a type C centre signal)."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in (str(x.date()) for x in pd.date_range("2026-08-01", periods=n_dates)):
        for hour in range(7, 13):
            for j in range(6):
                pm = np.array([0.15, 0.2, 0.3, 0.2, 0.15]) * rng.uniform(0.9, 1.1, 5)
                pm /= pm.sum()
                winner = int(rng.integers(0, 5))
                rows.append({"row_key": f"toronto|{day}T{hour:02d}{j}", "date": day, "market": "toronto",
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour + 4:02d}:{j * 9:02d}:00+00:00",
                             "pm": pm, "winner": winner, "x_info": CENTRES[winner] + rng.normal(0, 0.7)})
    return pd.DataFrame(rows)


def _run(tmp_path, monkeypatch, column, out):
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(te.ls, "code_state", lambda *a: clean)
    vals = column(fit_t)
    snaps = pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy(), "gem": vals, "city": vals[::-1].copy(),
                          "rc_gem": fit_t.snaps.captured_at_utc.to_numpy(),
                          "rc_city": fit_t.snaps.captured_at_utc.to_numpy()})
    meta = {"extract_stats": {}, "malformed": [], "market_reasons": {}, "table_drops": {}}
    monkeypatch.setattr(te, "build_tables", lambda *a: (snaps, fit_t, score_t, dates[:7], dates[7:], meta))
    monkeypatch.setattr(te.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    return te.run(out_dir=tmp_path / out, replay_root=tmp_path, tapes_root=tmp_path, repo_root=tmp_path), fit_t


def test_run_planted_centre_survives_and_null_is_killed(tmp_path, monkeypatch):
    rec, fit_t = _run(tmp_path, monkeypatch, lambda t: t.x_info, "out")
    r = rec["results"]["GEM-SEAMLESS"]
    assert r["verdict"] == "SURVIVE" and "w_gate" in r
    assert rec["controls"]["w0_identity_GEM-SEAMLESS"]["verdict"] == "PASS"
    assert rec["results"]["CITYPAGE-FH"]["verdict"] == "KILL"  # reversed values carry no signal
    assert r["coverage"]["fit_covered_snapshots"] == len(fit_t.snaps)
    assert rec["units"].startswith("native C") and rec["ledger_row"] == 90
    rows = [json.loads(x) for x in (tmp_path / "out" / "toronto_eccc_p0_rows.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert {x["candidate"] for x in rows} == {"GEM-SEAMLESS", "CITYPAGE-FH"}
    with pytest.raises(te.TorontoEcccError, match="overwrite"):
        te.run(out_dir=tmp_path / "out", replay_root=tmp_path, tapes_root=tmp_path, repo_root=tmp_path)
    null, _ = _run(tmp_path, monkeypatch, lambda t: np.random.default_rng(5).normal(22.5, 2, len(t.snaps)), "out2")
    assert {v["verdict"] for v in null["results"].values()} == {"KILL"}
    assert all("w_gate" not in v for v in null["results"].values())


def test_loyo_screen_dispatches_selection_only(tmp_path, monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"snapshots": 0, "n_dates": 0, "per_block": {}}

    monkeypatch.setattr(te, "selection_check", fake)
    monkeypatch.setattr(te, "run", lambda **kw: pytest.fail("run must not be called with --selection-only"))
    assert te.ls.main(["toronto-eccc-p0", "--replay-root", "r", "--tapes-root", "t", "--labels-root", "l",
                       "--out", str(tmp_path / "o"), "--selection-only"]) == 0
    assert seen == {"replay_root": "r", "out_dir": str(tmp_path / "o")}


# ----------------------------------------------------------------------------- amendment 1: controls only

LABEL_OF = [18, 21, 23, 25, 27]  # one integer label inside each of the five bins


def _daily_frame(seed=13, n_dates=40):
    """Winner fixed per date (as a real label is); flat-ish markets."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in (str(x.date()) for x in pd.date_range("2026-08-01", periods=n_dates)):
        winner = int(rng.integers(0, 5))
        for hour in range(7, 13):
            for j in range(6):
                pm = np.array([0.15, 0.2, 0.3, 0.2, 0.15]) * rng.uniform(0.9, 1.1, 5)
                pm /= pm.sum()
                rows.append({"row_key": f"toronto|{day}T{hour:02d}{j}", "date": day, "market": "toronto",
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour + 4:02d}:{j * 9:02d}:00+00:00",
                             "pm": pm, "winner": winner, "x_info": 22.5})
    return pd.DataFrame(rows)


def _controls(tmp_path, monkeypatch, out, row77_verdict="PASS"):
    frame = _daily_frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(te.ls, "code_state", lambda *a: clean)
    rng = np.random.default_rng(3)
    vals = rng.normal(22.5, 2, len(fit_t.snaps))
    snaps = pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy(), "gem": vals, "city": vals[::-1].copy(),
                          "rc_gem": fit_t.snaps.captured_at_utc.to_numpy(),
                          "rc_city": fit_t.snaps.captured_at_utc.to_numpy()})
    meta = {"extract_stats": {}, "malformed": [], "market_reasons": {}, "table_drops": {}}
    monkeypatch.setattr(te, "build_tables", lambda *a, **k: (snaps, fit_t, score_t, dates[:7], dates[7:], meta))
    labels = {d: LABEL_OF[int(w)] for d, w in zip(frame.date, frame.winner)}
    monkeypatch.setattr(te, "load_labels", lambda *a, **k: labels)
    monkeypatch.setattr(te.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    monkeypatch.setattr(te, "row77_reproduction", lambda *a, **k: {"verdict": row77_verdict, "max_abs_diff": 0.0})
    return te.controls_only(out_dir=tmp_path / out, row77_dir=tmp_path, replay_root=tmp_path, tapes_root=tmp_path,
                            repo_root=tmp_path), fit_t, labels


def test_controls_only_synthetic_passes_and_negation_reads_negative(tmp_path, monkeypatch):
    rec, fit_t, _ = _controls(tmp_path, monkeypatch, "c1")
    c = rec["controls"]
    assert c["1_w0_identity"]["verdict"] == "PASS"
    assert set(c["1_w0_identity"]["by_candidate"]) == {"GEM-SEAMLESS", "CITYPAGE-FH", "SYN+"}
    plus, minus = c["3_synthetic_positive"]["results"]["SYN+"], c["3_synthetic_positive"]["results"]["SYN-"]
    assert plus["verdict"] == "SURVIVE" and plus["p0"]["ci95"][0] > 0 and plus["w_gate"]["verdict"] == "PASS (w)"
    assert minus["p0"]["delta"] < 0 and minus["verdict"] == "KILL"
    assert c["3_synthetic_positive"]["verdict"] == "PASS"
    assert rec["outcome"] == "ROW 90 KILL STANDS" and rec["amendment_1_sha256"] == te.AMENDMENT_1_SHA256
    assert (tmp_path / "c1" / "toronto_eccc_p0_controls.json").exists()
    with pytest.raises(te.TorontoEcccError, match="overwrite"):
        te.controls_only(out_dir=tmp_path / "c1", row77_dir=tmp_path, replay_root=tmp_path, tapes_root=tmp_path,
                         repo_root=tmp_path)


def test_controls_only_any_failed_control_voids_row_90(tmp_path, monkeypatch):
    rec, _, _ = _controls(tmp_path, monkeypatch, "c2", row77_verdict="FAIL")
    assert rec["outcome"] == "ROW 90 VOID"


def test_synthetic_values_are_seeded_and_mirror_about_mu():
    frame = _daily_frame()
    t = FakeTable(frame, sorted(frame.date.unique()))
    labels = {d: LABEL_OF[int(w)] for d, w in zip(frame.date, frame.winner)}
    geo = te.sw.band_geometry(t)
    a, meta = te.synthetic_values(t, labels, geo)
    b, _ = te.synthetic_values(t, labels, geo)
    assert np.array_equal(a["SYN+"], b["SYN+"]) and meta["seed"] == te.SYN_SEED == 20261031
    assert np.allclose(a["SYN+"] + a["SYN-"], 2 * geo["mu"])
    r = np.array([labels[d] for d in t.snaps.date]) - geo["mu"]
    assert meta["sigma_r"] == pytest.approx(float(np.std(r)))


def test_inject_vectors_floor_mask_and_renormalise():
    frame = _daily_frame(n_dates=2)
    t = FakeTable(frame, sorted(frame.date.unique()))
    t.impossible = np.zeros(len(t.y), bool)
    t.impossible[0] = True  # band 0 of snapshot 0 is floor-impossible
    rk0, rk1 = t.snaps.row_key[0], t.snaps.row_key[1]
    c, cov = te.inject_vectors(t, {rk0: [0.2, 0.2, 0.2, 0.2, 0.2], rk1: [0.1, 0.1, 0.1, 0.1, 0.6]})
    assert cov[:3].tolist() == [True, True, False]
    assert c[:5].tolist() == pytest.approx([0.0, 0.25, 0.25, 0.25, 0.25])
    assert c[5:10].tolist() == pytest.approx([0.1, 0.1, 0.1, 0.1, 0.6])
    assert np.array_equal(c[10:15], t.p_market[10:15])
    with pytest.raises(te.TorontoEcccError, match="band count"):
        te.inject_vectors(t, {rk0: [0.5, 0.5]})


def _row77_files(tmp_path, monkeypatch, fit_t, score_t, scored, perturb=0.0):
    rng = np.random.default_rng(9)
    arms = {"c": {rk: {"A": list(rng.dirichlet(np.ones(5))), "B": list(rng.dirichlet(np.ones(5)))}
                  for rk in fit_t.snaps.row_key}, "meta": {}}
    counts = te.sw.boot_counts(len(scored))
    donors = {s: te.sw.donor_positions(fit_t, s) for s in te.sw.PLACEBO_SEEDS}
    results = {}
    for a in ("A", "B"):
        c_fit, cov = te.inject_vectors(fit_t, {rk: v[a] for rk, v in arms["c"].items()})
        got = te.vector_p0(fit_t, score_t, c_fit, cov, np.array(scored), counts, donors)
        p0 = dict(got["p0"])
        p0["delta"] += perturb
        results[a] = {"coverage": got["coverage"], "p0": p0, "diagnostic_c_deranged": {"rho": got["diagnostic_rho"]}}
    receipt = {"n_fit_snapshots": len(fit_t.snaps), "n_score_snapshots": len(score_t.snaps),
               "scored_dates": [scored[0], scored[-1], len(scored)], "results": results}
    d = tmp_path / f"r77_{perturb}"
    d.mkdir()
    (d / "arms.json").write_text(json.dumps(arms), encoding="utf-8")
    (d / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(te, "ROW77_ARMS_SHA256", _sha((d / "arms.json").read_bytes()))
    monkeypatch.setattr(te, "ROW77_RECEIPT_SHA256", _sha((d / "receipt.json").read_bytes()))
    return d


def test_row77_reproduction_matches_counts_and_stats_and_fails_on_a_miss(tmp_path, monkeypatch):
    frame = _daily_frame()
    dates = sorted(frame.date.unique())
    scored = [d for d in dates if d >= "2026-08-08"]
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, scored)
    seen = {}

    def fake_build(*a, **k):
        seen.update(k)
        return None, fit_t, score_t, dates[:7], scored, {}

    monkeypatch.setattr(te, "build_tables", fake_build)
    monkeypatch.setattr(te.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=300))
    ok = te.row77_reproduction(tmp_path, tmp_path, tmp_path,
                               _row77_files(tmp_path, monkeypatch, fit_t, score_t, scored))
    assert seen["hours"] == te.ROW77_HOURS == (7, 16)
    assert ok["verdict"] == "PASS" and ok["max_abs_diff"] < 1e-12
    bad = te.row77_reproduction(tmp_path, tmp_path, tmp_path,
                                _row77_files(tmp_path, monkeypatch, fit_t, score_t, scored, perturb=1e-3))
    assert bad["verdict"] == "FAIL" and not bad["stats"]["A.delta"]["ok"]
    monkeypatch.setattr(te, "ROW77_ARMS_SHA256", "0" * 64)
    with pytest.raises(te.TorontoEcccError, match="pinned"):
        te.row77_reproduction(tmp_path, tmp_path, tmp_path, tmp_path / "r77_0.001")


def test_loyo_screen_dispatches_controls_only(tmp_path, monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"lines": [], "outcome": "ROW 90 KILL STANDS"}

    monkeypatch.setattr(te, "controls_only", fake)
    monkeypatch.setattr(te, "run", lambda **kw: pytest.fail("run must not be called with --controls-only"))
    base = ["toronto-eccc-p0", "--replay-root", "r", "--tapes-root", "t", "--labels-root", "l",
            "--out", str(tmp_path / "o"), "--controls-only"]
    with pytest.raises(SystemExit, match="row77-dir"):
        te.ls.main(base)
    assert te.ls.main(base + ["--row77-dir", "p"]) == 0
    assert seen == {"out_dir": str(tmp_path / "o"), "row77_dir": "p", "replay_root": "r", "tapes_root": "t",
                    "repo_root": "l", "allow_dirty": False}
    assert te.AMENDMENT_1_SHA256.startswith("40b90e72")
