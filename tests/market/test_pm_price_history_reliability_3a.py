"""tools.research.pm_price_history.reliability_3a: synthetic data only (no sealed run, no labels, no network)."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.research.pm_price_history import extract_bounded_v1 as ex
from tools.research.pm_price_history import l21_stats_e541ad401 as l21
from tools.research.pm_price_history import reliability_3a as r3

F_LABELS = ["59°F or below", "60-61°F", "62-63°F", "64-65°F", "66-67°F", "68-69°F", "70°F or higher"]
C_LABELS = ["10°C or below", "11°C", "12°C", "13°C", "14°C", "15°C or higher"]


def test_vendored_statistic_is_l21_byte_identical():
    assert l21.sha256_file(Path(l21.__file__)) == r3.L21_STATS_SHA256
    r3._check_vendored()


def test_local_epoch_handles_dst():
    # 2026-03-08 is the US spring-forward day: 07:00 EDT = 11:00Z; the day before 07:00 EST = 12:00Z.
    assert r3.local_epoch(date(2026, 3, 8), 7, "America/New_York") == 1772967600
    assert r3.local_epoch(date(2026, 3, 7), 7, "America/New_York") == 1772884800


def test_pick_after_and_before_within_tolerance():
    st, pr = [1000, 1100, 1300], [0.1, 0.2, 0.3]
    assert r3.pick(st, pr, 1050, "after") == 0.2
    assert r3.pick(st, pr, 1050, "before") == 0.1
    assert r3.pick(st, pr, 1100, "after") == 0.2 and r3.pick(st, pr, 1100, "before") == 0.2
    assert r3.pick(st, pr, 1150, "after") is None          # 150 s > 120 s
    assert r3.pick(st, pr, 1400, "after") is None
    assert r3.pick(st, pr, 900, "before") is None


def test_band_parse_and_tiling():
    f = [r3.band_parse(x, "F") for x in F_LABELS]
    c = [r3.band_parse(x, "C") for x in C_LABELS]
    assert r3.tiles(f) and r3.tiles(c)
    assert f[0]["kind"] == "lte" and f[0]["high"] == 59 and f[1]["high"] == 61 and f[-1]["kind"] == "gte"
    assert not r3.tiles([f[0], f[2], f[-1]])               # gap
    assert not r3.tiles(f[1:])                              # no lower tail
    assert r3.band_parse("60-61°C", "F") is None


def test_require_hist_date_refuses_without_echo():
    assert r3.require_hist_date(date(2026, 5, 26)) == date(2026, 5, 26)
    with pytest.raises(r3.Refusal) as e:
        r3.require_hist_date(date(2026, 5, 27))
    assert "05-27" not in str(e.value)


# ----------------------------------------------------------------------------- synthetic sealed run

def _ladder_prices(rng, n):
    p = rng.dirichlet(np.full(n, 0.6))
    return np.clip(p, 0.001, 0.999)


def make_run(root: Path, markets=("nyc", "chicago", "toronto", "miami"), first=date(2026, 1, 1), days=90,
             extra=None, seed=7):
    """A sealed-run lookalike: events.jsonl, tokens.jsonl, raw/*.f1.json.gz, SHA256SUMS."""
    rng = np.random.default_rng(seed)
    names = sorted(set(markets) | {m for m, _ in (extra or [])})
    # R1R2 markets are not in the registry; 3a drops them before any spec lookup, so a stub is enough here
    all_specs = {**{m: {"tz": "Europe/London", "unit": "C", "icao": "egll"} for m in names if m in r3.R1R2},
                 **r3.specs_for([m for m in names if m not in r3.R1R2])}
    specs = {m: all_specs[m] for m in markets}
    root.mkdir(parents=True)
    events, tokens = [], []
    plan = [(m, first + timedelta(days=i)) for m in markets for i in range(days)] + list(extra or [])
    for k, (market, d) in enumerate(plan):
        labels = C_LABELS if all_specs[market]["unit"] == "C" else F_LABELS
        slug = f"highest-temperature-in-{market}-on-{d.isoformat()}-{k}"
        bands = []
        prices = {h: _ladder_prices(rng, len(labels)) for h in (7, 10, 13)}
        for i, lab in enumerate(labels):
            tok = f"{k:05d}{i:02d}"
            bands.append({"yes_token": tok, "condition_id": f"c{tok}", "band_label": lab, "question": lab})
            rel = f"raw/{market}/{d.isoformat()}/{slug}/{tok}.f1.json.gz"
            hist = []
            for h in (7, 10, 13):
                ts = r3.local_epoch(d, h, all_specs[market]["tz"])
                hist.append({"t": ts - 30, "p": round(float(prices[h][i]) * 0.9, 4)})
                hist.append({"t": ts + 30, "p": round(float(prices[h][i]), 4)})
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps({"history": hist}).encode()))
            tokens.append({"market": market, "event_slug": slug, "yes_token": tok, "path": rel,
                           "event_date": d.isoformat()})
        events.append({"market": market, "event_date": d.isoformat(), "slug": slug, "bands": bands})
    (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    (root / "tokens.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tokens), encoding="utf-8")
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256((root / "SHA256SUMS").read_bytes()).hexdigest(), specs


def test_sealed_run_refuses_wrong_sums_and_tampering(tmp_path):
    sums_sha, _ = make_run(tmp_path / "run", markets=("nyc",), days=2)
    with pytest.raises(r3.Refusal):
        r3.SealedRun(tmp_path / "run", "0" * 64)
    run = r3.SealedRun(tmp_path / "run", sums_sha)
    assert run.read("events.jsonl")
    with pytest.raises(r3.Refusal):
        run.read("not-listed.json")
    (tmp_path / "run" / "tokens.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(r3.Refusal):
        run.read("tokens.jsonl")


def test_load_population_excludes_duplicates_late_dates_and_incomplete(tmp_path):
    late = date(2026, 6, 2)
    sums_sha, specs = make_run(tmp_path / "run", markets=("nyc", "toronto"), days=3,
                               extra=[("nyc", date(2026, 1, 2)), ("nyc", late), ("london", date(2026, 1, 1))])
    # the late event's raw files are deleted: loading must never try to read them
    for p in (tmp_path / "run" / "raw" / "nyc" / late.isoformat()).rglob("*.gz"):
        p.unlink()
    run = r3.SealedRun(tmp_path / "run", sums_sha)
    ladders, info = r3.load_population(run, specs)
    assert not any("after" in k or "2026-06" in k for k in info)           # later events skipped silently
    assert info["duplicate_market_date_excluded:D"] == 1
    assert info["r1r2_excluded_no_venue_rule_label_extract:london"] == 1
    assert {(x["market"], x["date"]) for x in ladders} == {
        ("nyc", "2026-01-01"), ("nyc", "2026-01-03"), ("toronto", "2026-01-01"), ("toronto", "2026-01-02"),
        ("toronto", "2026-01-03")}
    assert all(x["tiles"] for x in ladders)
    lad = ladders[0]
    lad["mids"][(0, "after", 7)] = None
    rows, binfo = r3.build_rows(ladders, "D", "after", (7, 10))
    assert binfo["incomplete:nyc:07"] == 1 and binfo["ladders"] == 9
    # after side reads the +30 s point, before side the -30 s point
    after, _ = r3.build_rows(ladders[1:2], "D", "after", (10,))
    before, _ = r3.build_rows(ladders[1:2], "D", "before", (10,))
    assert np.allclose(before["p_market_yes"].to_numpy(), np.round(after["p_market_yes"].to_numpy() * 0.9, 4),
                       atol=1e-4)


def test_deciding_population_headline_table_and_folds_use_prices_only(tmp_path):
    sums_sha, specs = make_run(tmp_path / "run", markets=("nyc", "toronto"), first=date(2026, 1, 30), days=4)
    ladders, info = r3.load_population(r3.SealedRun(tmp_path / "run", sums_sha), specs)
    dropped = info.pop("_dropped_D_keys")
    assert dropped == []
    # nyc 01-30: incomplete at 07 only (still kept via 10:00); toronto 02-01: incomplete at both (excluded)
    by = {(x["market"], x["date"]): x for x in ladders}
    by[("nyc", "2026-01-30")]["mids"][(0, "after", 7)] = None
    for hr in (7, 10):
        by[("toronto", "2026-02-01")]["mids"][(1, "after", hr)] = None
    got = r3.deciding_population(ladders, [("nyc", "2026-02-03")])
    assert got["market_dates_kept"] == 7 and got["D_market_dates_universe"] == 9
    assert got["D_market_dates_loaded"] == 8 and got["D_dropped_at_load"] == 1 and got["ladder_hours"] == 13
    assert got["headline"].startswith("HEADLINE: deciding population 7 of 9 D market-dates (13 ladder-hours")
    assert "outcome-blind" in got["headline"]
    assert got["exclusions_by_market_hour"] == {"nyc": {"incomplete_07h": 1},
                                                "toronto": {"incomplete_07h": 1, "incomplete_10h": 1}}
    assert got["kept_vs_excluded_by_month_fold"] == {
        "2026-01": {"kept": 4, "excluded_price_incomplete": 0, "dropped_at_load": 0},
        "2026-02": {"kept": 3, "excluded_price_incomplete": 1, "dropped_at_load": 1}}
    keys = set(got) | {k for v in got["kept_vs_excluded_by_month_fold"].values() for k in v}
    assert not any("winner" in k or "label" in k for k in keys)


def test_nyc_2025_is_its_own_segment(tmp_path):
    sums_sha, specs = make_run(tmp_path / "run", markets=("nyc", "chicago"), first=date(2025, 11, 29), days=4)
    ladders, _ = r3.load_population(r3.SealedRun(tmp_path / "run", sums_sha), specs)
    seg = {(x["market"], x["date"]): x["segment"] for x in ladders}
    assert seg[("nyc", "2025-11-30")] == "NYC25" and seg[("nyc", "2025-12-01")] == "D"
    assert ("chicago", "2025-11-30") not in seg


# ----------------------------------------------------------------------------- LOMO over L21

def _toy_pop(seed=3, dates=60):
    rng = np.random.default_rng(seed)
    out, key = [], 0
    d0 = date(2026, 1, 15)
    for i in range(dates):
        d = (d0 + timedelta(days=i)).isoformat()
        for market in ("a", "b"):
            key += 1
            p = rng.dirichlet(np.full(5, 0.7))
            for j, v in enumerate(p):
                out.append({"row_key": key, "band_index": j, "date": d, "market": market, "local_hour": 7,
                            "p_market_yes": float(v), "impossible": False})
    rows = pd.DataFrame(out)
    pop = l21.Pop(rows)
    y = pop.synthetic_y(1.3, np.random.default_rng(seed))
    return pop, y


def test_month_starts():
    pop, _ = _toy_pop()
    starts, labels = r3.month_starts(pop)
    assert labels == ["2026-01", "2026-02", "2026-03"]
    assert pop.dates[starts[1]] == "2026-02-01" and pop.dates[starts[2]] == "2026-03-01"


def test_lomo_a2_matches_brute_force_leave_month_out():
    pop, y = _toy_pop()
    res = r3.deciding_lomo(pop, y, {"date_clustered": np.ones((3, pop.D), int)})
    r = y - pop.mt
    month = np.array([d[:7] for d in pop.dates])[pop.date_idx]
    g = np.zeros_like(r)
    for i in range(len(r)):
        sel = (month != month[i]) & (pop.bin == pop.bin[i])
        g[i] = r[sel].mean() if sel.any() else 0.0
    brute = (g * r).sum() / np.sqrt((g * g).sum() * (r * r).sum())
    assert res["A2_binned_lodo"]["point"] == pytest.approx(brute, rel=1e-9)
    assert set(res["_lomo_beta_by_month"]) == {"2026-01", "2026-02", "2026-03"}
    # A1 has no fold: identical to L21's own deciding
    lodo = l21.deciding(pop, y, {"date_clustered": np.ones((3, pop.D), int)})
    assert res["A1_linear"]["point"] == pytest.approx(lodo["A1_linear"]["point"], rel=1e-12)


def test_lomo_a3_point_matches_brute_force():
    pop, y = _toy_pop()
    res = r3.deciding_lomo(pop, y, {"date_clustered": np.ones((2, pop.D), int)})
    r = y - pop.mt
    month = np.array([d[:7] for d in pop.dates])[pop.date_idx]
    g3 = np.zeros_like(r)
    order = l21.BETA_ORDER
    for mo in sorted(set(month)):
        out = month != mo
        brier = [((y[out] - pop.q[out, k].astype(float)) ** 2).sum() for k in order]
        k = order[int(np.argmin(brier))]
        assert res["_lomo_beta_by_month"][mo] == pytest.approx(float(l21.BETA_GRID[k]))
        g3[month == mo] = pop.q[month == mo, k].astype(float) - pop.mt[month == mo]
    brute = (g3 * r).sum() / np.sqrt((g3 * g3).sum() * (r * r).sum())
    assert res["A3_power_lodo"]["point"] == pytest.approx(brute, rel=1e-6)
    pear = r3.pearson_point_lomo(pop, y, res)
    assert set(pear) == set(r3.ARMS)


def test_verdict_labels():
    def res(lo, hi):
        return {a: {"widest": [lo, hi]} for a in r3.ARMS}
    v = r3.verdict_3a(res(-0.1, 0.1), floor_unadjusted=True)
    assert v["verdict"].startswith("B12-HIST: KILL") and "floor-unadjusted; conservative toward KILL" in v["verdict"]
    assert "floor-unadjusted" not in r3.verdict_3a(res(-0.1, 0.1), floor_unadjusted=False)["verdict"]
    assert r3.verdict_3a(res(0.05, 0.4), floor_unadjusted=False)["verdict"].startswith("B12-HIST: NOT KILLED")


# ----------------------------------------------------------------------------- labels, floors, extracts

def _write_source(src: Path, specs, plan, buckets, late=True, partial=()):
    """A WU source tree: daily_summary.csv plus hourly partitions, including rows after 2026-05-26."""
    by_icao = {}
    for market, d in plan:
        by_icao.setdefault(specs[market]["icao"], []).append((market, d))
    for icao, items in by_icao.items():
        daily = src / icao / "daily"
        daily.mkdir(parents=True, exist_ok=True)
        lines = ["local_date,row_count,max_temp,max_temp_bucket"]
        for market, d in items:
            b = buckets[(market, d.isoformat())]
            rc = 5 if (market, d.isoformat()) in set(partial) else 24
            lines.append(f"{d.isoformat()},{rc},{b}.2,{b}")
        if late:
            lines.append("2026-06-01,24,99.0,99")
        (daily / "daily_summary.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for market, d in items:
            part = src / icao / "hourly" / f"year={d.year:04d}" / f"month={d.month:02d}"
            part.mkdir(parents=True, exist_ok=True)
            with open(part / "observations.jsonl", "a", encoding="utf-8") as h:
                for hh, t in ((6, buckets[(market, d.isoformat())] - 1), (9, 75.0)):
                    h.write(json.dumps({"local_date": d.isoformat(), "local_time": f"{hh:02d}:00",
                                        "temp_native": t}) + "\n")
        if late:
            part = src / icao / "hourly" / "year=2026" / "month=06"
            part.mkdir(parents=True, exist_ok=True)
            (part / "observations.jsonl").write_text(
                json.dumps({"local_date": "2026-06-01", "local_time": "06:00", "temp_native": 99}) + "\n",
                encoding="utf-8")


def _extract(src, out_root, kind):
    sha = ex.sha256_file(Path(ex.__file__))
    rc = ex.main(["--kind", kind, "--source-root", str(src), "--out-root", str(out_root), "--expect-sha", sha])
    assert rc == 0
    return next(Path(out_root).glob(f"extract-{kind}-*"))


def test_labels_winners_and_floor_from_extracts(tmp_path):
    sums_sha, specs = make_run(tmp_path / "run", markets=("nyc", "toronto"), days=3)
    ladders, _ = r3.load_population(r3.SealedRun(tmp_path / "run", sums_sha), specs)
    plan = [(x["market"], date.fromisoformat(x["date"])) for x in ladders]
    buckets = {("nyc", "2026-01-01"): 62, ("nyc", "2026-01-02"): 59, ("nyc", "2026-01-03"): 70,
               ("toronto", "2026-01-01"): 12, ("toronto", "2026-01-02"): 15, ("toronto", "2026-01-03"): 9}
    _write_source(tmp_path / "src", specs, plan, buckets)
    daily = _extract(tmp_path / "src", tmp_path / "ex", "daily")
    hourly = _extract(tmp_path / "src", tmp_path / "ex", "hourly")
    dext = r3.verify_extract(daily, "daily")
    hext = r3.verify_extract(hourly, "hourly")
    with pytest.raises(r3.Refusal):
        r3.verify_extract(daily, "hourly")
    with pytest.raises(r3.Refusal):                                     # not the pinned extractor
        r3.Extract(daily, "daily", expect_extractor_sha="0" * 64)
    with pytest.raises(r3.Refusal):
        dext.read("klga/not_listed.csv")
    wanted = set(buckets)
    got, info = r3.load_labels(dext, specs, wanted)
    assert got == buckets and info["unusable"] == {}
    assert info["native_high"] == {k: v + 0.2 for k, v in buckets.items()}
    win, counts = r3.winners(ladders, got)
    assert counts == {"exactly_one": 6}
    assert win[("nyc", "2026-01-01")] == 2 and win[("nyc", "2026-01-02")] == 0 and win[("nyc", "2026-01-03")] == 6
    assert win[("toronto", "2026-01-03")] == 0 and win[("toronto", "2026-01-02")] == 5
    floors = r3.load_floors(hext, specs, wanted)
    assert hext.summary()["files_read_and_verified"] >= 2
    assert floors[("nyc", "2026-01-01", 7)] == 61 and floors[("nyc", "2026-01-01", 10)] == 75.0
    rows, info = r3.build_rows(ladders, "D", "after", (7,), win, floors)
    nyc1 = rows[(rows["market"] == "nyc") & (rows["date"] == "2026-01-01")]
    # floor 61 at 07:00: "59 or below" (high 59) and nothing else is impossible
    assert nyc1["impossible"].tolist() == [True, False, False, False, False, False, False]


def _fake_extract(root: Path, files: dict, kind="daily", last="2026-05-26", script_sha=None):
    """A hand-made extract (manifest + SHA256SUMS) to test 3a's own defences past the extractor."""
    root.mkdir(parents=True)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    manifest = {"kind": kind, "last": last, "script_sha256": script_sha or r3.EXTRACTOR_SHA256}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lines = [f"{hashlib.sha256((root / r).read_bytes()).hexdigest()}  {r}" for r in [*files, "manifest.json"]]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return r3.Extract(root, kind)


def test_extractor_pin_matches_the_extractor_file():
    assert r3.EXTRACTOR_SHA256 == ex.sha256_file(Path(ex.__file__))


def test_extract_reader_refuses_unlisted_tampered_and_late(tmp_path):
    ext = _fake_extract(tmp_path / "a", {"klga/daily_summary.csv": "local_date,row_count,max_temp_bucket\n"})
    (tmp_path / "a" / "klga" / "extra.csv").write_text("x", encoding="utf-8")
    with pytest.raises(r3.Refusal):
        ext.read("klga/extra.csv")
    (tmp_path / "a" / "klga" / "daily_summary.csv").write_text("tampered", encoding="utf-8")
    with pytest.raises(r3.Refusal):
        ext.read("klga/daily_summary.csv")
    with pytest.raises(r3.Refusal):
        _fake_extract(tmp_path / "b", {}, last="2026-05-27")
    with pytest.raises(r3.Refusal):
        _fake_extract(tmp_path / "c", {}, script_sha="1" * 64)


def test_labels_refuse_a_late_row(tmp_path):
    ext = _fake_extract(tmp_path / "ex", {
        "klga/daily_summary.csv": "local_date,row_count,max_temp_bucket\n2026-05-27,24,70\n"})
    with pytest.raises(r3.Refusal):
        r3.load_labels(ext, r3.specs_for(("nyc",)), {("nyc", "2026-05-27")})


def test_labels_refuse_a_duplicate_station_date_without_echo(tmp_path):
    ext = _fake_extract(tmp_path / "ex", {
        "klga/daily_summary.csv": "local_date,row_count,max_temp_bucket\n2026-01-01,24,70\n2026-01-01,24,71\n"})
    with pytest.raises(r3.Refusal) as err:
        r3.load_labels(ext, r3.specs_for(("nyc",)), {("nyc", "2026-01-01")})
    assert "2026-01-01" not in str(err.value) and "71" not in str(err.value)


def test_sparse_and_missing_labels_are_counted(tmp_path):
    ext = _fake_extract(tmp_path / "ex", {
        "klga/daily_summary.csv": "local_date,row_count,max_temp_bucket\n2026-01-01,24,70\n2026-01-02,5,71\n"})
    got, info = r3.load_labels(ext, r3.specs_for(("nyc",)),
                               {("nyc", "2026-01-01"), ("nyc", "2026-01-02"), ("nyc", "2026-01-03")})
    assert got == {("nyc", "2026-01-01"): 70}
    assert info.pop("native_high") == {("nyc", "2026-01-01"): None}
    assert info == {"sparse_wu_day": 1, "missing_wu_day": 1,
                    "unusable": {("nyc", "2026-01-02"): "sparse", ("nyc", "2026-01-03"): "missing"}}


def test_combined_cap_and_restate_boundaries_are_exact():
    assert r3.within_unusable_cap(10, 500) and not r3.within_unusable_cap(11, 500)     # 2.0% passes, 2.2% fails
    assert r3.within_unusable_cap(0, 500) and not r3.within_unusable_cap(0, 0)
    assert not r3.restate_needed(5, 500) and r3.restate_needed(6, 500)                 # 1.0% no, 1.2% restates
    assert r3.within_unusable_cap(2, 100) and not r3.within_unusable_cap(3, 100)
    assert not r3.restate_needed(1, 100) and r3.restate_needed(2, 100)


# ----------------------------------------------------------------------------- end to end (reduced draws)

@pytest.fixture
def small_draws(monkeypatch):
    monkeypatch.setattr(l21, "B_DATE", 300)
    monkeypatch.setattr(l21, "B_BLOCK", 300)
    monkeypatch.setattr(l21, "B_CIRC", 200)
    monkeypatch.setattr(l21, "B_CROSSED", 100)


def test_synthetic_only_end_to_end(tmp_path, small_draws, capsys):
    sums_sha, _ = make_run(tmp_path / "run", markets=("nyc", "chicago", "toronto", "miami", "seattle", "denver"),
                           days=90)
    out = tmp_path / "receipt.json"
    rc = r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out),
                  "--synthetic-only"])
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0, rec.get("exception")
    assert rec["mode"] == "synthetic_only" and rec["steps"]["1_price_integrity"]["status"] == "PASS"
    assert rec["steps"]["2_label_integrity"]["status"].startswith("NOT RUN")
    assert rec["steps"]["2_label_integrity"]["tiling_outcome_free"]["tile"] == 540
    assert rec["population"]["months"] == ["2026-01", "2026-02", "2026-03"]
    dp = rec["deciding_population"]
    assert dp["headline"].startswith("HEADLINE: deciding population 540 of 540 D market-dates (1080 ladder-hours")
    assert dp["market_dates_kept"] == rec["population"]["market_dates"]
    assert "_dropped_D_keys" not in rec["population_load"]
    assert dp["MDE80_T2_at_kept"] == pytest.approx(0.105 * np.sqrt(1419 / 540))
    assert b"\r\n" not in out.read_bytes()                      # LF receipt: platform-stable sha
    assert "3_synthetic_controls" in rec["steps"]
    assert rec["verdict"]["verdict"].startswith(("NONE", "B12-HIST: UNTESTABLE"))
    assert "deciding" not in rec and "descriptive" not in rec
    assert rec["l21_stats_sha256"] == r3.L21_STATS_SHA256
    with pytest.raises(FileExistsError):                    # receipts are never overwritten
        r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out),
                 "--synthetic-only"])


def test_l21_step_names_are_mapped_to_3a_order(tmp_path, small_draws, monkeypatch):
    sums_sha, _ = make_run(tmp_path / "run", markets=("nyc", "chicago", "toronto", "miami"), days=40)

    def fail(ins, label):
        raise l21.Untestable("3_training_score_check", {"why": "test"})

    monkeypatch.setattr(r3, "step_synthetic_lomo", lambda pop, schemes: ({"status": "PASS"}, (None, None, None)))
    monkeypatch.setattr(l21, "step_training", fail)
    out = tmp_path / "r.json"
    r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out), "--synthetic-only"])
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["steps"]["4_training_score_check"] == {"status": "FAILED", "why": "test",
                                                      "l21_step_name": "3_training_score_check"}
    assert "3_training_score_check" not in rec["steps"]
    assert rec["verdict"]["verdict"] == "B12-HIST: UNTESTABLE (failed at 4_training_score_check)"


def test_unparseable_d_ladder_counts_as_non_tiling(tmp_path, small_draws):
    sums_sha, _ = make_run(tmp_path / "run", markets=("nyc", "chicago", "toronto", "miami"), days=40)
    run = tmp_path / "run"
    events = [json.loads(x) for x in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    events[3]["bands"][2]["band_label"] = "not a band"
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    lines = [f"{hashlib.sha256(q.read_bytes()).hexdigest()}  {q.relative_to(run).as_posix()}"
             for q in sorted(run.rglob("*")) if q.is_file() and q.name != "SHA256SUMS"]
    (run / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sums_sha = hashlib.sha256((run / "SHA256SUMS").read_bytes()).hexdigest()
    out = tmp_path / "r.json"
    r3.main(["--run", str(run), "--expect-run-sums", sums_sha, "--out", str(out), "--synthetic-only"])
    rec = json.loads(out.read_text(encoding="utf-8"))
    tiling = rec["steps"]["2_label_integrity"]["tiling_outcome_free"]
    assert tiling == {"ladders": 160, "tile": 159, "of_which_band_unparseable": 1}


def test_mode_refusals(tmp_path):
    with pytest.raises(SystemExit):
        r3.main(["--run", str(tmp_path), "--out", str(tmp_path / "o.json"), "--synthetic-only",
                 "--labels-extract", str(tmp_path)])
    with pytest.raises(SystemExit):
        r3.main(["--run", str(tmp_path), "--out", str(tmp_path / "o.json"), "--real-run",
                 "--labels-extract", str(tmp_path), "--expect-sha", "0" * 64])
    with pytest.raises(SystemExit):
        sha = l21.sha256_file(Path(r3.__file__))
        r3.main(["--run", str(tmp_path), "--out", str(tmp_path / "o.json"), "--real-run", "--expect-sha", sha])


def test_real_run_on_synthetic_extract(tmp_path, small_draws, monkeypatch):
    markets = ("nyc", "chicago", "toronto", "miami", "seattle", "denver")
    sums_sha, specs = make_run(tmp_path / "run", markets=markets, days=90)
    ladders, _ = r3.load_population(r3.SealedRun(tmp_path / "run", sums_sha), specs)
    rng = np.random.default_rng(11)
    buckets = {}
    for x in ladders:
        b = x["bands"][int(rng.integers(len(x["bands"])))]
        buckets[(x["market"], x["date"])] = b["value"] if b["kind"] != "eq" else b["value_hi"]
    plan = [(x["market"], date.fromisoformat(x["date"])) for x in ladders]
    _write_source(tmp_path / "src", specs, plan, buckets)
    daily = _extract(tmp_path / "src", tmp_path / "ex", "daily")
    monkeypatch.setattr(l21, "preflight", lambda: {"ok": True})
    sha = l21.sha256_file(Path(r3.__file__))
    out = tmp_path / "real.json"
    rc = r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out), "--real-run",
                  "--labels-extract", str(daily), "--expect-sha", sha])
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0, rec.get("exception")
    assert rec["steps"]["2_label_integrity"]["status"] == "PASS"
    assert rec["steps"]["2_label_integrity"]["D_exactly_one_share"] == 1.0
    assert rec["floor_unadjusted"] is True
    assert rec["verdict"]["verdict"].startswith("B12-HIST")
    lab = rec["steps"]["2_label_integrity"]
    assert lab["completeness_threshold"]["min_rows"] == 18
    assert "settlement_ledger.py:34" in lab["completeness_threshold"]["source"]
    assert lab["D_unusable_share"] == 0 and "power_restated" not in lab
    # ruling 1: containment of the raw high (bucket + 0.2) differs from the bucket for every lte/eq pick
    expect = sum(1 for x in ladders if x["segment"] == "D"
                 and buckets[(x["market"], x["date"])] != x["bands"][-1]["value"])
    assert lab["containment_diagnostic"]["containment_vs_bucket_differ"] == expect
    assert lab["containment_diagnostic"]["D_labelled_market_dates"] == 540

    # rulings 2-3: 3 partial + 4 missing = 7 of 540 (1.3%): excluded and counted, step 2 passes, N restated
    partial = [(m, d.isoformat()) for m, d in plan[10:13]]
    missing = plan[20:24]
    plan2 = [x for x in plan if x not in missing]
    _write_source(tmp_path / "src2", specs, plan2, buckets, partial=partial)
    daily2 = _extract(tmp_path / "src2", tmp_path / "ex2", "daily")
    out2 = tmp_path / "real2.json"
    rc = r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out2), "--real-run",
                  "--labels-extract", str(daily2), "--expect-sha", sha])
    rec2 = json.loads(out2.read_text(encoding="utf-8"))
    lab2 = rec2["steps"]["2_label_integrity"]
    assert rc == 0 and lab2["status"] == "PASS", rec2.get("exception")
    assert lab2["D_missing_wu"] == 4 and lab2["D_partial_wu"] == 3
    m0 = plan[20][0]
    assert lab2["D_missing_dates_by_market_fold"] == {m0: {"2026-01": [d.isoformat() for _, d in missing]}}
    assert lab2["D_partial_counts_by_market_fold"] == {plan[10][0]: {"2026-01": 3}}
    assert lab2["D_scored_market_dates"] == 533
    assert lab2["power_restated"]["N"] == 533
    assert lab2["power_restated"]["N_basis"].startswith("label-based")
    assert lab2["N_final_scored_market_dates"] == 533
    assert lab2["MDE80_T2_at_N_final_scored"] == pytest.approx(0.105 * np.sqrt(1419 / 533))
    assert lab2["D_market_dates_incl_dropped_at_load"] == 540
    assert lab2["power_restated"]["MDE80_T2"] == pytest.approx(0.105 * np.sqrt(1419 / 533))
    assert rec2["population"]["market_dates"] == 533

    # combined cap: 6 partial + 6 missing = 12 of 540 (2.2%) > 2%: step 2 fails closed, no Delta written
    partial = [(m, d.isoformat()) for m, d in plan[30:36]]
    missing = plan[40:46]
    plan3 = [x for x in plan if x not in missing]
    _write_source(tmp_path / "src3", specs, plan3, buckets, partial=partial)
    daily3 = _extract(tmp_path / "src3", tmp_path / "ex3", "daily")
    out3 = tmp_path / "real3.json"
    rc = r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out3), "--real-run",
                  "--labels-extract", str(daily3), "--expect-sha", sha])
    rec3 = json.loads(out3.read_text(encoding="utf-8"))
    assert rc == 0 and rec3["verdict"]["verdict"] == "B12-HIST: UNTESTABLE (failed at 2_label_integrity)"
    assert rec3["steps"]["2_label_integrity"]["D_unusable_share"] == pytest.approx(12 / 540)
    assert "deciding" not in rec3 and "3_synthetic_controls" not in rec3["steps"]
    lab3 = rec3["steps"]["2_label_integrity"]
    # the cap is checked before winners, floors and the diagnostic: none of them was computed
    assert "winner_counts_all_segments" not in lab3 and "containment_diagnostic" not in lab3

    # an L21 "labels" Untestable raised after step 2 PASSED never overwrites the PASS record
    def late_labels(*a, **k):
        raise l21.Untestable("labels", {"snapshots_without_label": 1})

    monkeypatch.setattr(l21, "step_training", late_labels)
    out4 = tmp_path / "real4.json"
    r3.main(["--run", str(tmp_path / "run"), "--expect-run-sums", sums_sha, "--out", str(out4), "--real-run",
             "--labels-extract", str(daily), "--expect-sha", sha])
    rec4 = json.loads(out4.read_text(encoding="utf-8"))
    assert rec4["steps"]["2_label_integrity"]["status"] == "PASS"
    assert rec4["steps"]["2_label_integrity__l21_labels"]["status"] == "FAILED"


def test_containment_pick():
    bands = [r3.band_parse(x, "F") for x in F_LABELS]
    for i, b in enumerate(bands):
        b["band_index"] = i
    assert r3.containment_pick(bands, 59.0) == 0 and r3.containment_pick(bands, 59.4) is None
    assert r3.containment_pick(bands, 61.0) == 1 and r3.containment_pick(bands, 61.5) is None
    assert r3.containment_pick(bands, 70.0) == 6 and r3.containment_pick(bands, 95.3) == 6
    assert r3.containment_pick(bands, None) is None
