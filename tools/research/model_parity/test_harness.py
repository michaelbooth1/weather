"""Fixture-only contracts for the model-parity harness; no external data, no network."""
import gzip
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from tools.research.model_parity import harness as h

BANDS = [{"kind": "lte", "low": 69, "high": 69, "label": "69 or below"},
         {"kind": "eq", "low": 70, "high": 71, "label": "70-71"},
         {"kind": "eq", "low": 72, "high": 73, "label": "72-73"},
         {"kind": "gte", "low": 74, "high": 74, "label": "74 or higher"}]
MARKETS = ("atlanta", "chicago", "miami")
DATES = ("2026-08-20", "2026-08-21", "2026-08-25", "2026-08-26")


def make_row(market, date, hour, winner, floor=None, served=(.1, .4, .3, .2)):
    return {"schema": "guidance-extract-rows/1", "snapshot_id": f"{date}T{hour:02d}",
            "market": market, "station": "KXXX", "event_slug": f"{market}-{date}",
            "target_date": date, "stratum": "before_20260823" if date < "2026-08-23" else "from_20260823",
            "captured_at_utc": f"{date}T{hour:02d}:00:00+00:00", "local_hour": hour, "unit": "F",
            "bands": BANDS, "p_served": list(served), "p_market_yes": [.05, .5, .4, .05],
            "best_bid": [None] * 4, "best_ask": [None] * 4, "market_mid": [None] * 4,
            "winner": winner, "settlement_high": 70.0 + winner, "settlement_bucket": 70 + winner,
            "settlement_source": "daily_summary",
            "features": {"guidance_physical_floor": floor, "high_so_far": floor, "trusted_current_max": None,
                         "cutoff_hour": "7"}}


def write_extract(root, extra=()):
    rows = []
    for m in MARKETS:
        for i, d in enumerate(DATES):
            for hour in (3, 7, 11, 14, 19):
                rows.append(make_row(m, d, hour, winner=(i + hour) % 3 + 1,
                                     floor=72.0 if hour >= 14 else 66.0))
    rows.extend(extra)
    with gzip.open(root / "guidance_rows.jsonl.gz", "wt", encoding="utf-8") as s:
        s.writelines(json.dumps(r) + "\n" for r in rows)
    with gzip.open(root / "market_days.jsonl.gz", "wt", encoding="utf-8") as s:
        s.writelines(json.dumps({"market": m, "target_date": d, "admitted": True}) + "\n"
                     for m in MARKETS for d in DATES)
    (root / "manifest.json").write_text(json.dumps({"status": "COMPLETE", "parser": {"head": "2e17ce0eb" + "0" * 31},
                                                    "row_counts": {"rows": len(rows), "market_days_admitted": 12}}))
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((root / n).read_bytes()).hexdigest()} *{n}\n" for n in h.INPUTS))
    return rows


@pytest.fixture()
def cache(tmp_path):
    write_extract(tmp_path)
    c = tmp_path / "cache"
    h.build_cache(root=tmp_path, cache=c)
    return c


def test_cache_shape_weights_and_floor_mask(cache):
    d = h.data(cache)
    assert len(d.snaps) == 60 and len(d.bands) == 240 and d.w.shape == (h.DRAWS, 12)
    assert d.receipt["rows_with_target_after_2026_09_29"] == 0
    # floor 72 -> bucket 72: bands 69 and 70-71 impossible; floor 66 -> nothing impossible
    late = d.bands[d.bands.local_hour >= 14]
    assert late.groupby("band_index").floor_impossible.all().tolist() == [True, True, False, False]
    assert not d.bands[d.bands.local_hour < 14].floor_impossible.any()


def test_rows_after_boundary_are_counted_and_never_cached(tmp_path):
    write_extract(tmp_path, extra=[make_row("atlanta", "2026-09-30", 7, 1)])
    receipt = h.build_cache(root=tmp_path, cache=tmp_path / "c")
    assert receipt["rows_with_target_after_2026_09_29"] == 1 and receipt["rows_cached"] == 60
    with pytest.raises(AssertionError, match="rule 5"):
        h.data(tmp_path / "c")


def test_hash_mismatch_refuses(tmp_path):
    write_extract(tmp_path)
    (tmp_path / "market_days.jsonl.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256SUMS"):
        h.build_cache(root=tmp_path, cache=tmp_path / "c")


def test_allow_list_has_no_market_or_label_columns(cache):
    snaps, bands = h.candidate_inputs(cache)
    assert not (h.FORBIDDEN & set(snaps.columns)) and not (h.FORBIDDEN & set(bands.columns))
    assert {"high_so_far", "floor", "local_hour", "row_key"} <= set(snaps.columns)
    g = h.GuardedDict({"a": 1})
    for key in ("winner", "p_market_yes", "settlement_high", "market_mid"):
        with pytest.raises(h.LeakageError):
            g[key]
        with pytest.raises(h.LeakageError):
            g.get(key)


def test_rowwise_function_cannot_read_labels(cache):
    def peek(snap, bands, p):
        return np.eye(4)[snap["winner"]]
    with pytest.raises(h.LeakageError):
        h.from_rowwise(peek, cache=cache)


def test_candidate_frame_refuses_forbidden_or_partial(cache):
    c = h.served_candidate(cache)
    with pytest.raises(h.LeakageError):
        h.score(c.assign(winner=0), cache=cache)
    with pytest.raises(ValueError, match="only some bands"):
        h.score(c[c.band_index != 2], cache=cache)
    with pytest.raises(ValueError, match="exactly"):
        h.score(c.rename(columns={"p": "prob"}), cache=cache)


def test_served_identity_is_exactly_zero_and_fallback_is_served(cache):
    r = h.score(h.served_candidate(cache), unfloored=True, cache=cache)
    for t in r["tables"]:
        assert t["candidate_minus_served"]["estimate"] == 0.0
    empty = pd.DataFrame({"row_key": [], "band_index": [], "p": []})
    r = h.score(empty, cache=cache)
    assert r["candidate_share"] == 0 and r["reason_counts"] == {"absent": 60}
    t = h.table_lookup(r, "all")
    assert t["candidate_minus_served"]["estimate"] == 0.0
    assert h.table_lookup(r, "all", population="matched")["status"] == "NO_DATA"


def test_floor_applied_and_renormalised(cache):
    uniform = h.served_candidate(cache).assign(p=.25)
    r = h.score(uniform, name="uniform", cache=cache)
    d = h.data(cache)
    pc, use, _ = h._candidate_vector(uniform, d, False)
    late = (d.bands.local_hour >= 14).to_numpy()
    assert np.allclose(pc[late].reshape(-1, 4), [0, 0, .5, .5])
    assert np.allclose(pc[~late], .25)
    assert r["floor_applied"] and use.all()
    diag = h.score(uniform, unfloored=True, cache=cache)
    assert all(c["class"] == "DIAGNOSTIC_UNFLOORED" for c in diag["classes"].values())


def test_missing_floor_falls_back_to_served(tmp_path):
    write_extract(tmp_path, extra=[make_row("atlanta", "2026-08-20", 8, 1, floor=None)])
    h.build_cache(root=tmp_path, cache=tmp_path / "c")
    r = h.score(h.served_candidate(tmp_path / "c").assign(p=.25), cache=tmp_path / "c")
    assert r["reason_counts"]["missing_floor"] == 1


def test_oracle_candidate_is_flagged_as_leakage_suspect(cache):
    d = h.data(cache)
    oracle = h.served_candidate(cache).assign(p=d.y)   # test only: built from the label
    r = h.score(oracle, cache=cache)
    assert "all" in r["leakage_suspect_groups"]


def test_interval_uses_w_and_matches_plain_mean(cache):
    d = h.data(cache)
    a = np.arange(12, dtype=float)
    out = h.interval(np.arange(12), a, cache=cache)
    assert out["estimate"] == pytest.approx(a.mean())
    boot = (d.w @ a) / d.w.sum(axis=1)
    assert out["ci95"] == pytest.approx(np.quantile(boot, [.025, .975]).tolist())
    assert h.mde80(np.arange(12), a - a.mean() + .001, cache=cache) > 0


def table(est, ci, gap=.02, neg=9, clusters=11):
    return {"candidate_minus_served": {"estimate": est, "ci95": ci},
            "served_minus_market": {"estimate": gap}, "markets_negative": neg, "market_clusters": clusters}


def test_lead_rule_conditions():
    def tables(t_from, t_before):
        return {("06-09", "from_20260823", "all_row"): t_from, ("06-09", "before_20260823", "all_row"): t_before}
    lead = h.classify(tables(table(-.002, [-.003, -.001]), table(-.001, [-.01, .01])), "06-09")
    assert lead["class"] == "LEAD"                   # -0.002 <= -5% of 0.02 gap
    weak_size = h.classify(tables(table(-.0005, [-.001, -.0001]), table(-.001, [0, 0])), "06-09")
    assert weak_size["class"] == "WEAK" and not weak_size["conditions"]["size"]
    big = table(-.014, [-.02, -.01], gap=1.0)          # passes via the twice-81a line only
    assert h.classify(tables(big, table(-.001, [0, 0])), "06-09")["class"] == "LEAD"
    strata = h.classify(tables(table(-.002, [-.003, -.001]), table(.001, [0, 0])), "06-09")
    assert strata["class"] == "WEAK" and not strata["conditions"]["both_strata_same_sign"]
    markets = h.classify(tables(table(-.002, [-.003, -.001], neg=7), table(-.001, [0, 0])), "06-09")
    assert markets["class"] == "WEAK"
    ci = h.classify(tables(table(-.002, [-.003, .001]), table(-.001, [0, 0])), "06-09")
    assert ci["class"] == "WEAK"
    assert h.classify(tables(table(.002, [.001, .003]), table(.001, [0, 0])), "06-09")["class"] == "HARM"
    assert h.classify(tables(table(.002, [-.001, .003]), table(.001, [0, 0])), "06-09")["class"] == "NULL"


def test_point_in_time_guard():
    assert h.assert_point_in_time(["2026-08-01T10:00Z"], ["2026-08-01T10:00Z"])
    with pytest.raises(AssertionError, match="rule 1"):
        h.assert_point_in_time(["2026-08-01T10:01Z"], ["2026-08-01T10:00Z"])
    with pytest.raises(AssertionError, match="rule 1"):
        h.assert_point_in_time([None], ["2026-08-01T10:00Z"])


def test_blocks():
    assert [h.block_of(x) for x in (0, 5, 6, 9, 10, 12, 13, 16, 17, 23)] == [
        "00-05", "00-05", "06-09", "06-09", "10-12", "10-12", "13-16", "13-16", "17-23", "17-23"]
