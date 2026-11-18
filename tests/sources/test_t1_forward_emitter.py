"""Tests for the T+1 forward test's daily emitter (lane L3, P3 of the T+1 forward prereg rev 9).

Guards: T+1 forward prereg rev 9 (docs/research/t1-forward-prereg-2026-10-30/README.md @ f07e8053b) sections 2, 3
and 5 -- arm construction, the receipt rule, the append-only emit store, parity VOIDs, and the rule that the emitter
never reads the WS T+1 price recorder.

Inputs are synthetic recorder layouts under tmp_path plus, when present on this workstation, the real NBM text and
ECMWF ENS forward recorder stores. No price row, label, METAR or outcome is read.
"""
from __future__ import annotations

import ast
import builtins
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import pytest

from tools.research import t1_forward_emitter as em

UTC = dt.timezone.utc
NBM_SHA = em.PINNED_RECORDER_SHA256["nbm_text"]
ENS_SHA = em.PINNED_RECORDER_SHA256["ecmwf_ens"]
D = dt.date(2026, 10, 20)  # EDT, no DST change near it
T = D + dt.timedelta(days=1)


def _t(*a):
    return dt.datetime(*a, tzinfo=UTC)


def _z(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------------------------------- synthetic stores
def _nbp_block(market, icao, cycle, sha, knots, *, parse_ok=True, column=None):
    column = column or _t(T.year, T.month, T.day + 1, 0)
    cols = [column - dt.timedelta(hours=12), column, column + dt.timedelta(hours=12)]
    values = {row: [knots[i] - 3, knots[i], knots[i] - 5] for i, row in enumerate(em.NBP_ROWS)}
    return {"kind": "block", "product": "nbp", "market": market, "icao": icao, "cycle_utc": _z(cycle),
            "file_sha256": sha, "parse_ok": parse_ok,
            "columns": [{"fhr": 0, "valid_utc": _z(c)} for c in cols], "values": values}


def write_nbm_cycle(root: Path, cycle: dt.datetime, received: dt.datetime, blocks, *, recorder=NBM_SHA,
                    product_ok=True, product_sha="p" * 64, tamper=False):
    d = root / cycle.strftime("%Y%m%d") / cycle.strftime("%H")
    d.mkdir(parents=True)
    rows = list(blocks)
    rows.append({"kind": "product", "product": "nbp", "status": "ok" if product_ok else "error",
                 "cycle_utc": _z(cycle), "last_modified_utc": _z(received - dt.timedelta(minutes=5)),
                 "fetched_utc": _z(received - dt.timedelta(minutes=1)), "sha256": product_sha})
    rows.append({"kind": "cycle_done", "cycle_utc": _z(cycle)})
    data = "".join(json.dumps(r) + "\n" for r in rows).encode()
    (d / "nbm_text.jsonl").write_bytes(data + (b"\n" if tamper else b""))
    man = {"schema": em.NBM_SCHEMA, "recorder_sha256": recorder, "rows_sha256": hashlib.sha256(data).hexdigest(),
           "cycle_utc": _z(cycle), "written_utc": _z(received)}
    (d / "manifest.json").write_text(json.dumps(man))


def write_ens_run(root: Path, run: dt.datetime, received: dt.datetime, members, highs_k, *, market="nyc",
                  spike_valid=None, recorder=ENS_SHA):
    d = root / run.strftime("%Y%m%d%H")
    d.mkdir(parents=True)
    steps = list(range(3, 75, 3))
    lines = []
    for m in members:
        for s in steps:
            valid = run + dt.timedelta(hours=s)
            v = highs_k[m] - 5.0 if s % 2 else highs_k[m] - 8.0
            if valid == spike_valid:
                v = highs_k[m] + 40.0
            lines.append(json.dumps({"kind": "point", "param": "mx2t3", "market": market, "member": m, "step": s,
                                     "valid_utc": valid.isoformat(), "window_h": 3, "bilinear_k": v,
                                     "last_modified_utc": (received - dt.timedelta(minutes=10)).isoformat(),
                                     "fetched_utc": (received - dt.timedelta(minutes=3)).isoformat()}))
    # put each member's day maximum at one inside window: 2026-10-21 18Z (14 EDT)
    peak = _t(2026, 10, 21, 18)
    if run + dt.timedelta(hours=72) >= peak:
        for m in members:
            s = int((peak - run).total_seconds() // 3600)
            lines.append(json.dumps({"kind": "point", "param": "mx2t3", "market": market, "member": m, "step": s,
                                     "valid_utc": peak.isoformat(), "window_h": 3, "bilinear_k": highs_k[m],
                                     "last_modified_utc": (received - dt.timedelta(minutes=10)).isoformat(),
                                     "fetched_utc": (received - dt.timedelta(minutes=3)).isoformat()}))
    # drop the generic peak rows so the explicit ones win (dict keeps the last; keep both consistent instead)
    data = ("\n".join(_dedupe(lines)) + "\n").encode()
    (d / "points.jsonl").write_bytes(data)
    man = {"schema": em.ENS_SCHEMA, "recorder_sha256": recorder, "points_sha256": hashlib.sha256(data).hexdigest(),
           "run_utc": run.isoformat(), "steps": steps, "written_utc": received.isoformat(),
           "max_last_modified_utc": (received - dt.timedelta(minutes=10)).isoformat(),
           "max_fetched_utc": (received - dt.timedelta(minutes=3)).isoformat()}
    (d / "manifest.json").write_text(json.dumps(man))


def _dedupe(lines):
    seen = {}
    for line in lines:
        r = json.loads(line)
        seen[(r["market"], r["member"], r["valid_utc"])] = line
    return list(seen.values())


def build_store(tmp_path: Path):
    nbm, ens = tmp_path / "nbm_text" / "forward", tmp_path / "ecmwf_ens" / "forward"
    nbm.mkdir(parents=True)
    ens.mkdir(parents=True)
    c00, c12 = _t(2026, 10, 20, 0), _t(2026, 10, 20, 12)
    write_nbm_cycle(nbm, c00, _t(2026, 10, 20, 1, 20),
                    [_nbp_block("nyc", "KLGA", c00, "p" * 64, (60, 62, 64, 66, 68)),
                     _nbp_block("toronto", "CYYZ", c00, "p" * 64, (50, 50, 52, 54, 56))])
    write_nbm_cycle(nbm, c12, _t(2026, 10, 20, 13, 20),
                    [_nbp_block("nyc", "KLGA", c12, "p" * 64, (61, 63, 65, 67, 69)),
                     _nbp_block("toronto", "CYYZ", c12, "p" * 64, (51, 51, 53, 55, 57))])
    highs = {m: 290.0 + 0.05 * m for m in range(1, 51)}
    write_ens_run(ens, _t(2026, 10, 19, 12), _t(2026, 10, 19, 19, 47), range(1, 51), highs,
                  spike_valid=_t(2026, 10, 21, 6))  # (03Z, 06Z] crosses local midnight 04Z: an edge window
    write_ens_run(ens, _t(2026, 10, 20, 0), _t(2026, 10, 20, 7, 52), range(1, 45), highs)  # 44 members
    return nbm, ens


NOW = _t(2026, 10, 22, 12)


def _rows(out: Path):
    return [json.loads(x) for x in (out / D.strftime("%Y%m%d") / "emit.jsonl").read_text().splitlines()]


def _row(rows, market, hour):
    return next(r for r in rows if r["market"] == market and r["local_hour"] == hour)


# ------------------------------------------------------------------------------------------- population
def test_markets_match_registry_and_exclude_denver():
    from weather.market.market_registry import spec_for_id

    assert len(em.MARKETS) == 11 and "denver" not in em.MARKETS
    for market, (tz, unit) in em.MARKETS.items():
        spec = spec_for_id(market)
        assert (spec.timezone, spec.display_unit) == (tz, unit), market


def test_snapshots_normal_fall_back_and_spring_forward():
    snaps, skipped = em.snapshots(D)
    assert len(snaps) == 264 and skipped == []
    snaps, skipped = em.snapshots(dt.date(2026, 11, 1))
    nyc1 = next(s for s in snaps if s["market"] == "nyc" and s["local_hour"] == 1)
    assert nyc1["capture_utc"] == _t(2026, 11, 1, 5)  # first occurrence of 01:00 (EDT)
    assert len(snaps) == 264 and skipped == []
    snaps, skipped = em.snapshots(dt.date(2027, 3, 14))
    assert len(skipped) == 11 and {s["local_hour"] for s in skipped} == {2}
    assert len(snaps) == 253


# ------------------------------------------------------------------------------------------- A1 construction
def test_nbp_mixture_is_piecewise_linear_through_untied_knots():
    segs = em.nbp_segments([60, 62, 64, 66, 68])
    assert math.isclose(sum(m for _a, _b, m in segs), 1.0)
    for v, q in zip((60, 62, 64, 66, 68), em.NBP_LEVELS):
        assert math.isclose(em.mixture_cdf(segs, v), q)
    assert math.isclose(em.mixture_cdf(segs, 63), 0.375)
    assert em.mixture_cdf(segs, 60 - 1.5 * 2) == 0.0 and math.isclose(em.mixture_cdf(segs, 68 + 1.5 * 2), 1.0)


def test_nbp_tied_knots_spread_over_the_integer_interval_and_tails_floor_at_one():
    segs = em.nbp_segments([50, 50, 52, 54, 54])
    assert math.isclose(em.mixture_cdf(segs, 49.5), 0.10 * (49.5 - 48.5) / 1.5)
    expected = 0.10 * 0.5 / 1.5 + 0.15 + 0.25 * 0.25  # lower tail part + tied gap + linear 50..52 part
    assert math.isclose(em.mixture_cdf(segs, 50.5) - em.mixture_cdf(segs, 49.5), expected, rel_tol=1e-12)
    assert math.isclose(em.mixture_cdf(segs, 54 + 1.5), 1.0)  # upper tail width 1.5 * max(0, 1)
    assert em.mixture_cdf(segs, 50 - 1.5) == 0.0


def test_band_probability_from_bins_matches_the_prereg_band_rule():
    segs = em.nbp_segments([60, 62, 64, 66, 68])
    b = em.binned(lambda x: em.mixture_cdf(segs, x), 50, 80, "F")
    band = sum(b["pmf"][k - 50] for k in (63, 64))  # interior band 63..64
    assert math.isclose(band, em.mixture_cdf(segs, 64.5) - em.mixture_cdf(segs, 62.5))
    assert math.isclose(sum(b["pmf"]) + b["below"] + b["above"], 1.0)


def test_celsius_bins_map_exactly_from_fahrenheit():
    segs = em.nbp_segments([50, 50, 52, 54, 56])
    b = em.binned(lambda x: em.mixture_cdf(segs, x), 5, 20, "C")
    c = 11
    lo, hi = (c - 0.5) * 9 / 5 + 32, (c + 0.5) * 9 / 5 + 32
    assert math.isclose(b["pmf"][c - 5], em.mixture_cdf(segs, hi) - em.mixture_cdf(segs, lo))


@pytest.mark.parametrize(
    "knots, reason",
    [((60, 62, 61, 66, 68), "nbp_percentiles_not_monotone"), ((60, 62, None, 66, 68), "nbp_value_missing")],
)
def test_bad_percentiles_are_uncovered(knots, reason):
    block = _nbp_block("nyc", "KLGA", _t(2026, 10, 20, 0), "p" * 64, (60, 62, 64, 66, 68))
    for i, row in enumerate(em.NBP_ROWS):
        block["values"][row][1] = knots[i]
    assert em.nbp_knots(block, T) == (None, reason)


def test_nbp_column_must_be_valid_at_00z_on_t_plus_one():
    block = _nbp_block("nyc", "KLGA", _t(2026, 10, 20, 0), "p" * 64, (60, 62, 64, 66, 68),
                       column=_t(2026, 10, 21, 0))
    assert em.nbp_knots(block, T) == (None, "nbp_column_missing")


# ------------------------------------------------------------------------------------------- source choice
def test_choose_takes_the_latest_product_that_passes_receipt_and_age():
    cap = _t(2026, 10, 20, 12)
    items = [{"cycle_utc": _t(2026, 10, 19, 22), "receipt_utc": _t(2026, 10, 19, 23)},   # age 14 h: too old
             {"cycle_utc": _t(2026, 10, 19, 23), "receipt_utc": _t(2026, 10, 20, 0)},    # age 13 h: allowed
             {"cycle_utc": _t(2026, 10, 20, 11), "receipt_utc": _t(2026, 10, 20, 12, 1)}]  # received after capture
    assert em._choose(items, cap, em.NBP_MAX_AGE, "cycle_utc") is items[1]
    assert em._choose(items[:1], cap, em.NBP_MAX_AGE, "cycle_utc") is None
    exact = [{"cycle_utc": cap, "receipt_utc": cap}]  # receipt equal to capture counts
    assert em._choose(exact, cap, em.NBP_MAX_AGE, "cycle_utc") is exact[0]


# ------------------------------------------------------------------------------------------- end to end
def test_emit_receipt_rule_age_limit_members_and_edge_windows(tmp_path):
    nbm, ens = build_store(tmp_path)
    out = tmp_path / "emit"
    man = em.emit_day(D, out, nbm, ens, context_roots=(), now=NOW)
    assert man["void"] is False and man["parity"]["failures"] == []
    rows = _rows(out)
    assert len(rows) == 264
    # 12Z cycle received 13:20Z: not used at 08 EDT (12Z) or 09 EDT (13Z); used from 10 EDT (14Z)
    assert _row(rows, "nyc", 8)["arms"]["A1"]["source"]["cycle_utc"].startswith("2026-10-20T00:00")
    assert _row(rows, "nyc", 9)["arms"]["A1"]["source"]["cycle_utc"].startswith("2026-10-20T00:00")  # age 13 h
    assert _row(rows, "nyc", 10)["arms"]["A1"]["source"]["cycle_utc"].startswith("2026-10-20T12:00")
    # 00Z cycle is older than 13 h at 21 EDT (01Z next day) and the 12Z cycle is used; nothing before 01:20Z
    assert _row(rows, "nyc", 21)["arms"]["A1"]["source"]["cycle_utc"].startswith("2026-10-20T12:00")
    # markets with no block are uncovered, never imputed
    assert not _row(rows, "miami", 12)["arms"]["A1"]["covered"]
    # ENS: before the 00Z run's receipt (07:52Z) the 10-19 12Z run is used
    a2 = _row(rows, "nyc", 3)["arms"]["A2"]
    assert a2["covered"] and a2["source"]["run_utc"].startswith("2026-10-19T12:00") and a2["source"]["n_members"] == 50
    # from 04 EDT (08Z) the latest run is the 00Z run with 44 members: uncovered, no fallback to an older run
    a2_late = _row(rows, "nyc", 4)["arms"]["A2"]
    assert not a2_late["covered"] and a2_late["reason"] == "ens_members_44_lt_45"
    assert a2_late["source"]["run_utc"].startswith("2026-10-20T00:00")
    # the edge window's spike (+40 K) never enters a member high
    highs = a2["source"]["member_high_f"]
    assert max(highs) < (290.0 + 2.5 - 273.15) * 1.8 + 32 + 1e-6
    # A3 is the exact equal-weight blend, only where both arms are covered
    r = _row(rows, "nyc", 3)["arms"]
    assert r["A3"]["covered"] and all(math.isclose(c, 0.5 * a + 0.5 * b, abs_tol=1e-15)
                                      for a, b, c in zip(r["A1"]["pmf"], r["A2"]["pmf"], r["A3"]["pmf"]))
    assert not _row(rows, "toronto", 9)["arms"]["A3"]["covered"]
    for row in rows:
        for arm in row["arms"].values():
            if arm["covered"]:
                assert math.isclose(sum(arm["pmf"]) + arm["below"] + arm["above"], 1.0, abs_tol=1e-9)
    idx = (out / "index.jsonl").read_text().splitlines()
    assert len(idx) == 1 and json.loads(idx[0])["emit_sha256"] == man["emit_sha256"]
    emit_bytes = (out / D.strftime("%Y%m%d") / "emit.jsonl").read_bytes()
    assert hashlib.sha256(emit_bytes).hexdigest() == man["emit_sha256"]


def test_emit_store_is_append_only_and_refuses_an_unfinished_day(tmp_path):
    nbm, ens = build_store(tmp_path)
    out = tmp_path / "emit"
    with pytest.raises(em.RefusedDate, match="not over"):
        em.emit_day(D, out, nbm, ens, context_roots=(), now=_t(2026, 10, 21, 6, 30))
    em.emit_day(D, out, nbm, ens, context_roots=(), now=NOW)
    with pytest.raises(em.RefusedDate, match="append-only"):
        em.emit_day(D, out, nbm, ens, context_roots=(), now=NOW)


def test_block_without_a_matching_ok_product_is_never_used(tmp_path):
    nbm, ens = tmp_path / "nbm", tmp_path / "ens"
    ens.mkdir()
    c00 = _t(2026, 10, 20, 0)
    write_nbm_cycle(nbm, c00, _t(2026, 10, 20, 1, 20),
                    [_nbp_block("nyc", "KLGA", c00, "x" * 64, (60, 62, 64, 66, 68))])
    out = tmp_path / "emit"
    em.emit_day(D, out, nbm, ens, context_roots=(), now=NOW)
    a1 = _row(_rows(out), "nyc", 6)["arms"]["A1"]
    assert not a1["covered"] and a1["reason"] == "nbp_block_missing_or_ambiguous"


@pytest.mark.parametrize("kind", ["tamper", "recorder"])
def test_parity_failure_voids_the_date_and_rows_are_kept(tmp_path, kind):
    nbm, ens = tmp_path / "nbm", tmp_path / "ens"
    ens.mkdir()
    c00 = _t(2026, 10, 20, 0)
    write_nbm_cycle(nbm, c00, _t(2026, 10, 20, 1, 20),
                    [_nbp_block("nyc", "KLGA", c00, "p" * 64, (60, 62, 64, 66, 68))],
                    tamper=kind == "tamper", recorder=NBM_SHA if kind == "tamper" else "0" * 64)
    out = tmp_path / "emit"
    man = em.emit_day(D, out, nbm, ens, context_roots=(), now=NOW)
    assert man["void"] is True and man["parity"]["failures"]
    assert len(_rows(out)) == 264
    assert json.loads((out / "index.jsonl").read_text())["void"] is True


# ------------------------------------------------------------------------------------------- never the prices
def test_price_recorder_root_is_refused(tmp_path):
    prices = tmp_path / "t1_prices" / "forward"
    prices.mkdir(parents=True)
    with pytest.raises(em.RefusedPath):
        em.emit_day(D, tmp_path / "emit", prices, tmp_path, context_roots=(), now=NOW)
    with pytest.raises(em.RefusedPath):
        em._guard(prices / "x.jsonl", (tmp_path,))
    with pytest.raises(em.RefusedPath):
        em._guard(tmp_path / "other" / "x.jsonl", (tmp_path / "nbm",))


def test_every_file_read_is_inside_the_forecast_roots(tmp_path, monkeypatch):
    nbm, ens = build_store(tmp_path)
    opened = []
    real_open = builtins.open

    def spy(file, mode="r", *a, **k):
        if "r" in mode and "+" not in mode:
            opened.append(Path(file).resolve())
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    em.compute_rows(D, nbm, ens, (nbm, ens))
    assert opened
    for p in opened:
        assert str(p).startswith((str(nbm.resolve()), str(ens.resolve()))), p


def test_module_imports_only_the_standard_library_and_names_no_comparator_field():
    src = Path(em.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"__future__", "argparse", "datetime", "hashlib", "json", "math", "os", "sys", "tempfile",
                    "pathlib", "zoneinfo"}, mods
    lowered = src.lower()
    for word in ("outcomeprices", "p_market_yes", "best_bid", "condition_id", "settlement", "metar",
                 "high_so_far"):
        assert word not in lowered, word


# ------------------------------------------------------------------------------------------- real recorder data
REAL_NBM, REAL_ENS = em.DEFAULT_NBM_ROOT, em.DEFAULT_ENS_ROOT


@pytest.mark.skipif(not ((REAL_NBM / "20261031").is_dir() and (REAL_ENS / "2026103100").is_dir()),
                    reason="workstation forward recorder stores not present")
def test_real_recorder_day_emits_unvoided_and_mass_conserving(tmp_path):
    out = tmp_path / "emit"
    man = em.emit_day(dt.date(2026, 10, 31), out, REAL_NBM, REAL_ENS, context_roots=(), now=_t(2026, 11, 1, 12))
    assert man["void"] is False, man["parity"]["failures"]
    assert man["counts"]["snapshots"] == 264 and man["counts"]["A1_covered"] > 200
    assert man["counts"]["A2_covered"] > 200
    rows = [json.loads(x) for x in (out / "20261031" / "emit.jsonl").read_text().splitlines()]
    tor = _row(rows, "toronto", 12)
    assert tor["unit"] == "C" and tor["arms"]["A1"]["covered"]
    for row in rows:
        for arm in row["arms"].values():
            if arm["covered"]:
                assert math.isclose(sum(arm["pmf"]) + arm["below"] + arm["above"], 1.0, abs_tol=1e-9)
