"""S31 P0 (amendment 1): pins, event range, t_eff, quotes, moments, block-3 and labels on synthetic inputs."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

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

def test_block_counts_draw_consecutive_blocks_of_three():
    c = p0.block_counts(10, draws=200, seed=1)
    assert (c.sum(axis=1) == 10).all()
    rng = np.random.default_rng(1)
    starts = rng.integers(0, 8, 4)
    first = np.bincount((starts[:, None] + np.arange(3)).ravel()[:10], minlength=10)
    assert (c[0] == first).all()


def _res(testable=True, p=0.01, ci=(0.01, 0.05), b3=(0.0, 0.06)):
    return {"candidate": "A", "testable": testable, "p0": {"p_one_sided": p, "delta": 0.03, "ci95": list(ci)},
            "block3": {"ci95": list(b3)}, "coverage": {"population_dates": 40, "population_snapshots": 5000}}


def test_fex_is_untestable_with_p_one_in_a_k3_bh_family():
    results = {"KAL-MEAN": _res(p=0.03), "KAL-WIDTH": _res(p=0.04), p0.FEX_ID: p0.fex_result()}
    p0.apply_bh(results, ["KAL-MEAN", "KAL-WIDTH", p0.FEX_ID])
    assert results[p0.FEX_ID]["p0"]["p_one_sided"] == 1.0 and results[p0.FEX_ID]["label"] == p0.LABEL_UNTESTABLE
    assert results["KAL-MEAN"]["bh_q"] == pytest.approx(0.06)  # 0.04 * 3 / 2 step-up
    assert results["KAL-MEAN"]["label"] == p0.LABEL_SURVIVOR
    assert "Reopen-if" in p0.register_line(results[p0.FEX_ID])


def test_labels_use_the_wider_upper_bound():
    r = _res(p=0.5, ci=(-0.05, 0.20), b3=(-0.06, 0.23))
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_NULL and r["label_upper"] == 0.23
    r = _res(p=0.5, ci=(-0.05, 0.20), b3=(-0.04, 0.19))
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_KILL_EDGE and r["label_upper"] == 0.20
    r = _res(p=0.01, ci=(-0.01, 0.05))  # BH rejects but the lower bound is not > 0
    p0.apply_bh({"A": r}, ["A"])
    assert r["label"] == p0.LABEL_KILL_EDGE
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
