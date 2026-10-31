"""S31 P0 (amendment 1): pins, event range, t_eff, quotes, moments, block-3 and labels on synthetic inputs."""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from weather import paths
from weather.calibration import s31_p0 as p0


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _ts(iso):
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp())


# ----------------------------------------------------------------------------- pins

def test_governing_documents_match_their_pins():
    got = p0.check_docs()
    assert got == p0.DOC_SHA256
    assert got[p0.AMENDMENT_FILE] == p0.AMENDMENT_SHA256


def test_doc_mismatch_refuses(tmp_path):
    (tmp_path / "rule_s31_p0.md").write_bytes(b"edited")
    with pytest.raises(p0.P0Error, match="not the pinned"):
        p0.check_docs(tmp_path, {"rule_s31_p0.md": p0.DOC_SHA256["rule_s31_p0.md"]})
    with pytest.raises(p0.P0Error, match="missing"):
        p0.check_docs(tmp_path, {"absent.md": "0" * 64})


def test_amendment_copy_is_byte_identical_and_refuses_tampering(tmp_path):
    src = paths.docs_path(*p0.DOC_DIR, p0.AMENDMENT_FILE)
    dst, sha = p0.pin_amendment_copy(src, tmp_path)
    assert sha == p0.AMENDMENT_SHA256 and dst.read_bytes() == src.read_bytes()
    assert p0.pin_amendment_copy(src, tmp_path)[1] == sha  # an identical existing copy is accepted
    dst.write_bytes(dst.read_bytes() + b"\n")
    with pytest.raises(p0.P0Error, match="pinned copy"):
        p0.pin_amendment_copy(src, tmp_path)
    bad = tmp_path / "other.md"
    bad.write_bytes(b"not the amendment")
    with pytest.raises(p0.P0Error, match="not the pinned amendment"):
        p0.pin_amendment_copy(bad, tmp_path / "o2")


def test_input_sha_mismatch_refuses(tmp_path):
    live = tmp_path / "live.jsonl"
    live.write_bytes(b"{}\n")
    pins = {"v0_live": _sha(b"{}\n"), "kalshi_candles.jsonl": "0" * 64}
    (tmp_path / "kalshi_candles.jsonl").write_bytes(b"x")
    with pytest.raises(p0.P0Error, match="kalshi_candles.jsonl"):
        p0.check_inputs(tmp_path, live, pins)
    pins["kalshi_candles.jsonl"] = _sha(b"x")
    assert set(p0.check_inputs(tmp_path, live, pins)) == {"v0_live", "kalshi_candles.jsonl"}


# ----------------------------------------------------------------------------- V0 and the event range

TWC_RULE = "If the maximum temperature recorded at Atlanta{code} for {day} is ..., according to The Weather Company"
CLI_RULE = "... as reported by the National Weather Service's Climatological Report (Daily) ..."


def _event(series, tag, rule, strikes=((None, 70), (70, 71), (72, 73), (74, 75), (76, 77), (77, None))):
    e = f"{series}-{tag}"
    rows = []
    for i, (lo, hi) in enumerate(strikes):
        st = "less" if lo is None else "greater" if hi is None else "between"
        rows.append({"ticker": f"{e}-M{i}", "event_ticker": e, "strike_type": st, "floor_strike": lo,
                     "cap_strike": hi, "rules_primary": rule, "rules_secondary": ""})
    return rows


def test_event_range_drops_cli_dates_and_keeps_08_14_as_burn_in():
    rows = (_event("KXHIGHTATL", "26AUG13", CLI_RULE)
            + _event("KXHIGHTATL", "26AUG14", TWC_RULE.format(code="", day="Aug 14"))
            + _event("KXHIGHTATL", "26AUG15", TWC_RULE.format(code=" (CLIATL)", day="Aug 15"))
            + _event("KXHIGHNY", "26AUG15", TWC_RULE.format(code=" (CLINYC)", day="Aug 15")))
    v0 = p0.v0_table(rows, [])
    assert set(v0) == {"KXHIGHTATL-26AUG14", "KXHIGHTATL-26AUG15"}  # 08-13 and non-KAL series never enter
    assert v0["KXHIGHTATL-26AUG14"]["role"] == "burn-in" and v0["KXHIGHTATL-26AUG14"]["kept"]
    assert v0["KXHIGHTATL-26AUG15"]["role"] == "scored" and v0["KXHIGHTATL-26AUG15"]["kept"]
    assert not p0.in_kal_range("KXHIGHTATL-26SEP30")


def test_v0_1_change_drops_the_city_from_that_date_on():
    rows = (_event("KXHIGHTATL", "26AUG15", TWC_RULE.format(code=" (CLIATL)", day="d"))
            + _event("KXHIGHTATL", "26AUG16", TWC_RULE.format(code="", day="d"))  # station code missing
            + _event("KXHIGHTATL", "26AUG17", TWC_RULE.format(code=" (CLIATL)", day="d"))
            + _event("KXHIGHMIA", "26AUG16", CLI_RULE + " The Weather Company"))
    v0 = p0.v0_table(rows, [])
    assert v0["KXHIGHTATL-26AUG15"]["kept"]
    assert not v0["KXHIGHTATL-26AUG16"]["kept"] and not v0["KXHIGHTATL-26AUG17"]["kept"]
    assert v0["KXHIGHTATL-26AUG17"]["drop_reason"] == "V0.1 change from 2026-08-16"
    assert v0["KXHIGHMIA-26AUG16"]["v0_1_reason"] == "rules name the NWS CLI source"


def test_v0_2_tiling_and_metadata_drop_the_event_only():
    good = TWC_RULE.format(code=" (CLIATL)", day="d")
    gap = ((None, 70), (70, 71), (73, 74), (75, 76), (77, 78), (78, None))
    rows = _event("KXHIGHTATL", "26AUG15", good, gap) + _event("KXHIGHTATL", "26AUG16", good) \
        + _event("KXHIGHTATL", "26AUG17", good)
    meta = [{"event_ticker": "KXHIGHTATL-26AUG17", "market_ticker": "KXHIGHTATL-26AUG17-M0"}]
    v0 = p0.v0_table(rows, meta)
    assert v0["KXHIGHTATL-26AUG15"]["drop_reason"] == "V0.2 tiling"
    assert v0["KXHIGHTATL-26AUG16"]["kept"] and v0["KXHIGHTATL-26AUG16"]["meta_match"] is None
    assert v0["KXHIGHTATL-26AUG17"]["drop_reason"] == "metadata tickers differ"


def test_intervals_and_z_follow_the_open_band_convention():
    assert p0.interval({"strike_type": "less", "cap_strike": 70}) == ((None, 69.0), 68.0)
    assert p0.interval({"strike_type": "between", "floor_strike": 70, "cap_strike": 71}) == ((70.0, 71.0), 70.5)
    assert p0.interval({"strike_type": "greater", "floor_strike": 77}) == ((78.0, None), 79.0)
    assert p0.tiles([p0.interval(r)[0] for r in _event("X", "26AUG15", "")])


# ----------------------------------------------------------------------------- t_eff and quotes

def test_t_cut_is_local_wall_clock_on_the_target_date_with_dst():
    # 2026-08-20 is EDT (UTC-4): 14:00 local = 18:00Z; Los Angeles PDT (UTC-7): 14:00 = 21:00Z
    assert p0.t_cut_utc("2026-08-20", 14, "America/New_York") == _ts("2026-08-20T18:00:00")
    assert p0.t_cut_utc("2026-08-20", 14.0, "America/Los_Angeles") == _ts("2026-08-20T21:00:00")
    assert p0.t_cut_utc("2026-08-20", 24, "America/Chicago") == _ts("2026-08-21T05:00:00")
    for bad in (None, float("nan"), 13.5, -1, 25, "x"):
        assert p0.t_cut_utc("2026-08-20", bad, "America/Chicago") is None


def test_t_eff_is_the_earlier_of_capture_and_cutoff():
    zone = "America/New_York"
    late_capture = "2026-08-20T19:30:00+00:00"   # after the 14:00 local cutoff (18:00Z)
    early_capture = "2026-08-20T15:10:00Z"
    assert p0.t_eff_utc(late_capture, "2026-08-20", 14, zone) == _ts("2026-08-20T18:00:00")
    assert p0.t_eff_utc(early_capture, "2026-08-20", 14, zone) == _ts("2026-08-20T15:10:00")
    assert p0.t_eff_utc(early_capture, "2026-08-20", None, zone) is None
    assert p0.t_eff_utc(None, "2026-08-20", 14, zone) is None


def test_quote_takes_the_latest_candle_in_the_hour_before_t_eff():
    t = _ts("2026-08-20T18:00:00")
    ts = np.array([t - 4000, t - 1800, t - 60, t + 60], np.int64)
    c = (ts, np.array([0.10, 0.20, 0.30, 0.90]), np.array([0.14, 0.24, 0.34, 0.95]))
    assert p0.quote(c, t) == pytest.approx(0.32)  # the t+60 candle is after t_eff and never used
    assert p0.quote(c, t - 1700) == pytest.approx(0.22)
    assert p0.quote(c, t - 4000 + 3601) == pytest.approx(0.22)
    assert p0.quote((ts[:1], np.array([0.1]), np.array([0.12])), t) is None  # older than 60 min
    assert p0.quote(None, t) is None


@pytest.mark.parametrize("bid,ask", [(0.0, 0.1), (0.3, 0.2), (0.5, 1.0), (0.1, 0.31), (np.nan, 0.2)])
def test_invalid_quotes_are_not_quotes(bid, ask):
    t = 1_000_000
    assert p0.quote((np.array([t], np.int64), np.array([bid]), np.array([ask])), t) is None


def test_moments_normalise_and_floor_the_variance():
    mu, sd = p0.moments([0.1, 0.1, 0.2, 0.2, 0.2, 0.2], [68, 70.5, 72.5, 74.5, 76.5, 79])
    q = np.array([1, 1, 2, 2, 2, 2]) / 10
    z = np.array([68, 70.5, 72.5, 74.5, 76.5, 79])
    assert mu == pytest.approx((q * z).sum())
    assert sd == pytest.approx(math.sqrt((q * (z - mu) ** 2).sum()))
    assert p0.moments([0.5] + [1e-9] * 5, [70] * 6)[1] == pytest.approx(0.5)  # sqrt(0.25 floor)


def test_load_candles_skips_dropped_events_before_reading_prices_and_checks_units():
    kept = {"KXHIGHTATL-26AUG15-M0"}
    rows = [{"ticker": "KXHIGHTATL-26AUG13-M0", "end_period_ts": 5, "yes_bid_close": 45.0, "yes_ask_close": 47.0},
            {"ticker": "KXHIGHTATL-26AUG15-M0", "end_period_ts": 9, "yes_bid_close": 0.4, "yes_ask_close": None},
            {"ticker": "KXHIGHTATL-26AUG15-M0", "end_period_ts": 7, "yes_bid_close": 0.4, "yes_ask_close": 0.5}]
    out = p0.load_candles(rows, kept)  # the cents-coded 08-13 row is never read
    ts, bid, ask = out["KXHIGHTATL-26AUG15-M0"]
    assert ts.tolist() == [7, 9] and np.isnan(ask[1])
    with pytest.raises(p0.P0Error, match="outside"):
        p0.load_candles([dict(rows[0], ticker="KXHIGHTATL-26AUG15-M0")], kept)
    with pytest.raises(p0.P0Error, match="conflicting"):
        p0.load_candles(rows[2:] + [dict(rows[2], yes_ask_close=0.6)], kept)


def _twin_fixture():
    good = TWC_RULE.format(code=" (CLIATL)", day="d")
    rows = _event("KXHIGHTATL", "26AUG14", TWC_RULE.format(code="", day="d")) + _event("KXHIGHTATL", "26AUG15", good)
    v0 = p0.v0_table(rows, [])
    t = _ts("2026-08-15T18:00:00")  # 14:00 EDT
    candles = {}
    for e in v0:
        for k, tick in enumerate(sorted(v0[e]["markets"])):
            candles[tick] = (np.array([t - 120], np.int64), np.array([0.10 + 0.01 * k]), np.array([0.12 + 0.01 * k]))
    return v0, candles, t


def test_twin_values_cover_only_kept_kal_snapshots_at_t_eff():
    v0, candles, t = _twin_fixture()
    snaps = pd.DataFrame([
        {"market": "atlanta", "date": "2026-08-15", "captured_at_utc": "2026-08-15T19:00:00Z", "cutoff_hour": 14,
         "station": "KATL"},                                   # t_eff = 18:00Z: covered
        {"market": "atlanta", "date": "2026-08-15", "captured_at_utc": "2026-08-15T19:00:00Z", "cutoff_hour": 16,
         "station": "KATL"},                                   # t_eff = 19:00Z: candle 62 min old, uncovered
        {"market": "atlanta", "date": "2026-08-15", "captured_at_utc": "2026-08-15T19:00:00Z",
         "cutoff_hour": None, "station": "KATL"},
        {"market": "atlanta", "date": "2026-08-15", "captured_at_utc": "2026-08-15T19:00:00Z", "cutoff_hour": 14,
         "station": "KPDK"},
        {"market": "atlanta", "date": "2026-08-13", "captured_at_utc": "2026-08-13T19:00:00Z", "cutoff_hour": 14,
         "station": "KATL"},
        {"market": "nyc", "date": "2026-08-15", "captured_at_utc": "2026-08-15T19:00:00Z", "cutoff_hour": 14,
         "station": "KLGA"},
        {"market": "atlanta", "date": "2026-08-14", "captured_at_utc": "2026-08-14T19:00:00Z", "cutoff_hour": 14,
         "station": "KATL"},                                   # burn-in event, no candle at its t_eff
    ])
    mu, sd, reasons = p0.twin_values(snaps, v0, candles)
    assert np.isfinite(mu[0]) and np.isfinite(sd[0])
    assert np.isnan(mu[1:]).all()
    assert reasons == {"covered": 1, "date outside 08-14..09-29 (amendment)": 1,
                       "no finite cutoff_hour or capture time": 1, "not a KAL market": 1,
                       "not all six markets quoted at t_eff": 2, "snapshot station is not the twin station": 1}


# ----------------------------------------------------------------------------- block-3, BH, FEX and labels

def test_block_counts_c1_draw_non_circular_blocks_of_three():
    c = p0.block_counts_c1(10, draws=200, seed=1)
    assert (c.sum(axis=1) == 10).all()
    rng = np.random.default_rng(1)
    starts = rng.integers(0, 8, 4)
    first = np.bincount((starts[:, None] + np.arange(3)).ravel()[:10], minlength=10)
    assert (c[0] == first).all()


def _c3_reference_block_counts(n_dates, b=2000, seed=20261024, length=3):
    """Verbatim ``c3_kill_tier.block_counts`` at 1b65f11ee (BOOT_B 2000, BOOT_SEED 20261024, BLOCK_LEN 3)."""
    k = -(-n_dates // length)
    starts = np.random.default_rng(seed).integers(n_dates, size=(b, k))
    idx = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
    return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)


@pytest.mark.parametrize("n", [3, 7, 14, 43, 46])
def test_circular_block_counts_equal_the_c3_reference(n):
    got = p0.block_counts_circular(n)
    want = _c3_reference_block_counts(n)
    assert got.shape == (2000, n) and np.array_equal(got, want)
    assert (got.sum(axis=1) == n).all()
    assert (p0.CIRC_B, p0.CIRC_SEED, p0.BLOCK_LEN) == (2000, 20261024, 3)
    if n >= 7:
        assert np.allclose(got.mean(axis=0), 1.0, atol=0.15)  # circular: no edge under-weighting


def test_circular_blocks_wrap_past_the_last_date():
    c = p0.block_counts_circular(5, b=50, seed=3)
    starts = np.random.default_rng(3).integers(5, size=(50, 2))
    idx = ((starts[0][:, None] + np.arange(3)) % 5).ravel()[:5]
    assert (c[0] == np.bincount(idx, minlength=5)).all()


def _rows(n, rng, shift=0.0):
    out = []
    for i in range(n):
        base = rng.uniform(1, 2, 6)
        out.append({"date": f"2026-08-{15 + i:02d}" if i < 17 else f"2026-09-{i - 16:02d}", "n_entries": 5,
                    "sums_c": (base + rng.normal(shift, 0.3, 6)).tolist(),
                    "sums_pl": [(base + rng.normal(0, 0.3, 6)).tolist() for _ in range(20)]})
    return out


def test_bounds_take_the_widest_of_three_intervals():
    rng = np.random.default_rng(5)
    rows = _rows(30, rng)
    rows[3]["n_entries"] = 0  # no entries: not in the block intervals
    b = p0.bounds(rows, p0.ms.boot_counts(30))
    parts = [b["date_clustered"], b["block3_c1"], b["block3_circular"]]
    assert b["n_block_dates"] == 29
    assert b["block3_c1"]["valid_draws"] <= p0.ms.DRAWS and b["block3_circular"]["valid_draws"] <= p0.CIRC_B
    assert b["ci95_widest"] == [min(p["ci95"][0] for p in parts), max(p["ci95"][1] for p in parts)]
    assert b["se_widest"] == max(p["se"] for p in parts)
    assert b["scheme"]["block3_circular"][:2] == [2000, 20261024]


def _res(testable=True, p=0.01, widest=(0.01, 0.05)):
    return {"candidate": "A", "testable": testable, "p0": {"p_one_sided": p, "delta": 0.03, "ci95": [0.02, 0.04]},
            "bounds": {"ci95_widest": list(widest)},
            "coverage": {"population_dates": 40, "population_snapshots": 5000}}


def test_fex_is_untestable_with_p_one_in_a_k3_bh_family():
    results = {"KAL-MEAN": _res(p=0.03), "KAL-WIDTH": _res(p=0.04), p0.FEX_ID: p0.fex_result()}
    p0.apply_bh(results, ["KAL-MEAN", "KAL-WIDTH", p0.FEX_ID])
    assert results[p0.FEX_ID]["p0"]["p_one_sided"] == 1.0 and results[p0.FEX_ID]["label"] == p0.LABEL_UNTESTABLE
    assert results["KAL-MEAN"]["bh_q"] == pytest.approx(0.06)  # 0.04 * 3 / 2 step-up
    assert results["KAL-MEAN"]["label"] == p0.LABEL_SURVIVOR
    assert "Reopen-if" in p0.register_line(results[p0.FEX_ID])


def test_labels_use_the_widest_upper_bound():
    # the date-clustered p0 ci95 alone (0.02, 0.04) would say KILL at edge size; the widest upper decides
    r = _res(p=0.5, widest=(-0.06, 0.23))
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_NULL and r["label_upper"] == 0.23
    r = _res(p=0.5, widest=(-0.06, 0.224))
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_NULL  # >= edge is null
    r = _res(p=0.5, widest=(-0.04, 0.20))
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_KILL_EDGE and r["label_upper"] == 0.20
    r = _res(p=0.01, widest=(-0.01, 0.05))  # BH rejects but the widest lower bound is not > 0
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_KILL_EDGE and not r["survive"]
    r = _res(p=0.01, widest=(None, None))
    p0.apply_bh({"A": r}, ["A"])
    assert not r["survive"] and r["label"] == p0.LABEL_NULL
    r = _res(testable=False)
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_UNTESTABLE


def test_cities_bind_series_zone_and_station_to_the_fetch_module_and_config():
    from weather.sources.free_screens import s31_venue_fetch as vf

    locs = json.loads(paths.config_path("locations.json").read_text(encoding="utf-8"))
    items = locs if isinstance(locs, list) else locs.get("locations", locs)
    by_id = items if isinstance(items, dict) else {x["id"]: x for x in items}
    for city, (series, station, code, tz) in p0.CITIES.items():
        assert vf.SERIES_TZ[series] == tz == by_id[city]["timezone"]
        assert by_id[city]["settlement"]["station_id"] == station
        assert code == "CLI" + station[1:]


# ----------------------------------------------------------------------------- start assertion (module origins)

def test_module_origins_resolve_under_the_run_tree():
    got = p0.check_origins(paths.REPO_ROOT)
    assert got["verdict"] == "PASS" and set(got["modules"]) == set(p0.ORIGIN_MODULES)
    root = paths.REPO_ROOT.resolve()
    assert all(pathlib.Path(v).is_relative_to(root) for v in got["modules"].values())


def test_module_origins_outside_the_run_tree_refuse(tmp_path):
    with pytest.raises(p0.P0Error, match="outside the run tree"):
        p0.check_origins(tmp_path)


# ----------------------------------------------------------------------------- socket-blocked end to end

SCORED = [str(date(2026, 8, 15) + timedelta(days=i)) for i in range(30)]
STRIKES = ((None, 70), (70, 71), (72, 73), (74, 75), (76, 77), (77, None))
BANDS = (("lte", None, 69), ("eq", 70, 71), ("eq", 72, 73), ("eq", 74, 75), ("eq", 76, 77), ("gte", 78, None))


def _synthetic_world(tmp_path, rng):
    """One KAL city (atlanta / KATL), burn-in 08-14 plus 30 scored dates, 48 snapshots a day, and a twin with
    six quoted markets every 30 minutes. An 08-13 CLI event with cents-coded candles must never be read."""
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    snaps, bands, labels, market, live, candles = [], [], [], [], [], []
    for d in ["2026-08-14"] + SCORED:
        day = date.fromisoformat(d)
        tag = f"26{day:%b}{day.day:02d}".upper()
        rows = _event("KXHIGHTATL", tag, TWC_RULE.format(code=" (CLIATL)", day=d), STRIKES)
        live += rows
        mids = np.clip(rng.dirichlet(np.full(6, 3.0)), 0.03, 0.9)
        t0 = int(datetime(day.year, day.month, day.day, tzinfo=zone).timestamp())
        for r, m in zip(rows, mids):
            for k in range(48):
                candles.append({"job": "candles:1m:" + r["ticker"], "run_id": "r1", "ticker": r["ticker"],
                                "end_period_ts": t0 + 1800 * k, "yes_bid_close": round(float(m) - 0.01, 4),
                                "yes_ask_close": round(float(m) + 0.01, 4)})
        for h in range(24):
            for mm in (10, 40):
                key = f"atlanta|{d}|{h:02d}{mm}"
                tc = datetime(day.year, day.month, day.day, h, mm, tzinfo=zone).astimezone(timezone.utc)
                snaps.append({"row_key": key, "date": d, "market": "atlanta", "station": "KATL", "n_bands": 6,
                              "local_hour": h, "cutoff_hour": h + 1, "captured_at_utc": tc.isoformat(),
                              "guidance_physical_floor": np.nan, "high_so_far": np.nan,
                              "trusted_current_max": np.nan})
                pm = rng.dirichlet(np.full(6, 2.0))
                ps = rng.dirichlet(np.full(6, 2.0))
                for b, (kind, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": key, "band_index": b, "kind": kind,
                                  "low": np.nan if lo is None else lo, "high": np.nan if hi is None else hi,
                                  "p_served": ps[b]})
                    market.append({"row_key": key, "band_index": b, "p_market_yes": pm[b]})
                labels.append({"row_key": key, "winner": int(rng.choice(6, p=pm))})
    cli = _event("KXHIGHTATL", "26AUG13", CLI_RULE, STRIKES)
    live += cli
    candles += [{"job": "candles:1m:" + r["ticker"], "run_id": "r1", "ticker": r["ticker"], "end_period_ts": 1,
                 "yes_bid_close": 45.0, "yes_ask_close": 47.0} for r in cli]
    lay = SimpleNamespace(snaps=pd.DataFrame(snaps), bands=pd.DataFrame(bands), labels=pd.DataFrame(labels),
                          market=pd.DataFrame(market), manifest_sha256="synthetic")

    twin = tmp_path / "twin"
    twin.mkdir()
    (twin / "kalshi_candles.jsonl").write_text("".join(json.dumps(r) + "\n" for r in candles), encoding="utf-8")
    (twin / "v0_markets_hist.jsonl").write_text("", encoding="utf-8")
    (twin / "event_markets.jsonl").write_text("", encoding="utf-8")
    jobs = sorted({r["job"] for r in candles})
    (twin / "receipts.jsonl").write_text("".join(
        json.dumps({"job": j, "run_id": "r1", "complete": True, "extract": "kalshi_candles.jsonl"}) + "\n"
        for j in jobs), encoding="utf-8")
    v0_live = tmp_path / "v0_markets.jsonl"
    v0_live.write_text("".join(json.dumps(r) + "\n" for r in live), encoding="utf-8")
    pins = {n: p0.ls.sha256_file(twin / n) for n in p0.INPUT_SHA256 if n != "v0_live"}
    pins["v0_live"] = p0.ls.sha256_file(v0_live)
    return lay, twin, v0_live, pins


def test_p0_runs_end_to_end_with_the_network_blocked(tmp_path, monkeypatch):
    import inspect
    import socket
    import urllib.request

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.sources.free_screens import s31_venue_fetch as vf

    lay, twin, v0_live, pins = _synthetic_world(tmp_path, np.random.default_rng(20261031))

    def no_network(*a, **k):
        raise AssertionError("network used")

    class NoSocket:
        def __init__(self, *a, **k):
            raise AssertionError("socket opened")

    monkeypatch.setattr(socket, "socket", NoSocket)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)

    used = []
    allowed = {"load_extract", "kalshi_ticker_date"}
    for name, obj in list(vars(vf).items()):
        if getattr(obj, "__module__", None) != vf.__name__ or not callable(obj):
            continue
        if inspect.isclass(obj) and issubclass(obj, BaseException):
            continue  # exception types stay raisable
        if name in allowed:
            def spy(*a, _f=obj, _n=name, **k):
                used.append(_n)
                return _f(*a, **k)
            monkeypatch.setattr(vf, name, spy)
        else:
            def forbidden(*a, _n=name, **k):
                raise AssertionError(f"s31_venue_fetch.{_n} used")
            monkeypatch.setattr(vf, name, forbidden)

    def build(layout):
        assert layout is lay
        kal_fit = sc.Table(lay, ["2026-08-14"] + SCORED)
        return "synthetic", ["2026-08-14"], SCORED, kal_fit, sc.Table(lay, SCORED), {"synthetic": {"verdict": "PASS"}}

    monkeypatch.chdir(paths.REPO_ROOT)
    monkeypatch.setenv("PYTHONPATH", str(paths.REPO_ROOT / "src"))
    out = tmp_path / "out"
    rec = p0.run(layout=lay, out_dir=out, twin_dir=twin, v0_live=v0_live, allow_dirty=True, input_pins=pins,
                 build=build, require_pythonpath=True)

    assert set(used) == allowed and used.count("load_extract") == 3
    assert rec["module_origins"]["verdict"] == rec["module_origins_end"]["verdict"] == "PASS"
    assert json.loads((out / "s31_p0.json").read_text(encoding="utf-8"))["labels"] == rec["labels"]
    assert (out / p0.AMENDMENT_FILE).read_bytes() == paths.docs_path(*p0.DOC_DIR, p0.AMENDMENT_FILE).read_bytes()
    assert rec["clarification5_sha256"] == p0.CLARIFICATION5_SHA256
    assert "KXHIGHTATL-26AUG13" not in rec["v0"]["events"]
    assert rec["population"]["uncovered_reasons"] == {"covered": 31 * 48}
    fex = rec["results"][p0.FEX_ID]
    assert fex["p0"]["p_one_sided"] == 1.0 and rec["labels"][p0.FEX_ID] == p0.LABEL_UNTESTABLE
    for cid in ("KAL-MEAN", "KAL-WIDTH"):
        r = rec["results"][cid]
        assert r["testable"], r
        b = r["bounds"]
        assert b["n_block_dates"] <= 30 and b["se_widest"] is not None
        parts = [b[k] for k in ("date_clustered", "block3_c1", "block3_circular")]
        assert b["ci95_widest"] == [min(p["ci95"][0] for p in parts), max(p["ci95"][1] for p in parts)]
        assert rec["labels"][cid] in (p0.LABEL_SURVIVOR, p0.LABEL_KILL_EDGE, p0.LABEL_NULL)


def test_first_party_names_cover_every_package_under_src():
    names = p0.first_party_names(paths.REPO_ROOT)
    assert {"weather", "maker_core"} <= set(names)


def test_a_loaded_first_party_module_outside_the_run_tree_refuses(tmp_path, monkeypatch):
    import sys
    import types

    stray = types.ModuleType("maker_core._stray_probe")
    stray.__file__ = str(tmp_path / "maker_core" / "_stray_probe.py")
    monkeypatch.setitem(sys.modules, "maker_core._stray_probe", stray)
    with pytest.raises(p0.P0Error, match="_stray_probe"):
        p0.check_origins(paths.REPO_ROOT)


def test_a_first_party_package_path_outside_the_run_tree_refuses(tmp_path, monkeypatch):
    import sys
    import types

    pkg = types.ModuleType("maker_core._stray_pkg")
    pkg.__path__ = [str(paths.REPO_ROOT / "src" / "maker_core"), str(tmp_path)]
    monkeypatch.setitem(sys.modules, "maker_core._stray_pkg", pkg)
    with pytest.raises(p0.P0Error, match=r"_stray_pkg\.__path__"):
        p0.check_origins(paths.REPO_ROOT)


def test_the_cli_origin_check_requires_pythonpath_at_the_run_tree_src(monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    with pytest.raises(p0.P0Error, match="PYTHONPATH"):
        p0.check_origins(paths.REPO_ROOT, require_pythonpath=True)
    monkeypatch.setenv("PYTHONPATH", str(paths.REPO_ROOT.parent / "elsewhere" / "src"))
    with pytest.raises(p0.P0Error, match="PYTHONPATH"):
        p0.check_origins(paths.REPO_ROOT, require_pythonpath=True)
    monkeypatch.setenv("PYTHONPATH", str(paths.REPO_ROOT / "src"))
    got = p0.check_origins(paths.REPO_ROOT, require_pythonpath=True)
    assert got["verdict"] == "PASS" and got["pythonpath"] == str(paths.REPO_ROOT / "src")
