r"""S31 P0: does the Kalshi twin's capture-time price predict OUR market's error? (lane L14, 2026-10-31).

Rule ``docs/research/s31-other-venue-prices-2026-10-31/rule_s31_p0.md`` (sha256 ``d50112cc…``) with
Clarifications 1-4 and master AMENDMENT 1 (``amendment_s31_1.md``, sha256 ``AMENDMENT_SHA256``); dev-window
ledger row 99. Where the amendment and the rule disagree, the amendment wins. Development evidence only; nothing
after 2026-09-29 is read.

- **Twin (amendment §3-§4).** Kalshi events 08-14..09-29 only (The Weather Company regime) for the 7
  same-station cities. Events 08-01..08-13 (CLI-settled) are never read for prices and are in no fit or score.
  The KAL fit table is 08-14 (burn-in) plus the scored dates 08-15..09-29.
- **Capture instant.** t_eff = min(t_c, T_cut): t_c is the snapshot's ``captured_at_utc``, and T_cut is
  ``cutoff_hour``:00 local on the target date (our effective WU print cutoff). The twin quote is the latest
  1-minute candle with ``end_period_ts`` in [t_eff - 60 min, t_eff]; it must satisfy 0 < bid <= ask < 1 and
  ask - bid <= 0.20. A snapshot without a finite cutoff is uncovered.
- **Arms (K = 3).** KAL-MEAN (type C, x = mu_t), KAL-WIDTH (type S, g = sigma_t - sigma_m), FEX-MEAN
  (UNTESTABLE, p = 1). P0, placebo, bootstrap, BH and the survivors' w gate are rule_mr_sweep ``85f8192c`` via
  ``mr_sweep`` and ``mr_gate``, unchanged. The controls run first on the unamended tables and refuse on a miss.
- **Labels (Clarification 2, D3).** Survivor / KILL at edge size / screen null; underpowered for information /
  UNTESTABLE, on the wider of the date-clustered and block-3 upper bounds.

Every governing document is sha-pinned and the amendment is copied byte-identically into ``--out``; a mismatch
refuses. Writes ``s31_p0.json`` (never overwritten) and ``s31_p0_rows.jsonl``. A dirty tree refuses.

    python -m weather.calibration.s31_p0 --layout C:/swarm/v3layout --out C:/t/l14p0/run1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from weather import paths
from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as ms

SCHEMA = "s31_p0/1"
GATE = "S31-P0"
LEDGER_ROW = 99
DOC_DIR = ("research", "s31-other-venue-prices-2026-10-31")
AMENDMENT_FILE = "amendment_s31_1.md"
AMENDMENT_SHA256 = "4c29c0bf4023b2a4121a4adda0fb37e6d1bf1814ee8987923d5a8f14967f5666"
DOC_SHA256 = {
    "rule_s31_p0.md": "d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e",
    "clarification_s31_p0_1.md": "b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d",
    "clarification_s31_p0_2.md": "798dfaa912c7e94da97c0c99340d12726bb9c606b7279324b92ef4b8c670bd26",
    "clarification_s31_p0_3.md": "654408acbc40fa981b30947547863ae7140694f530f559f1bb9fefe94db0a340",
    "clarification_s31_p0_4.md": "ee35f782f89934095bad84e1c4ad92906c1a1b77ae687ec6d388879c89bc4c2c",
    AMENDMENT_FILE: AMENDMENT_SHA256,
}

# Amendment §3: the KAL event range and burn-in. Scored dates are the scorecard's (08-15..09-29).
KAL_FIRST = date(2026, 8, 14)
KAL_LAST = date(2026, 9, 29)
KAL_BURN_IN = ("2026-08-14",)
CODE_FROM = date(2026, 8, 15)  # V0.1 restated: the CLI-coded station must be named from 08-15 on
QUOTE_WINDOW_S = 3600
MAX_SPREAD = 0.20
TAIL_W = 2.0
N_MARKETS_PER_EVENT = 6
DELTA_EDGE = 0.224
BLOCK_LEN = 3
N80 = 78
TWC = "the weather company"
CLI_MARKERS = ("national weather service", "climatological report")

# our market id -> (Kalshi series, our WU label station == twin station, CLI code named in the rules, zone)
CITIES = {
    "atlanta": ("KXHIGHTATL", "KATL", "CLIATL", "America/New_York"),
    "austin": ("KXHIGHAUS", "KAUS", "CLIAUS", "America/Chicago"),
    "houston": ("KXHIGHTHOU", "KHOU", "CLIHOU", "America/Chicago"),
    "los-angeles": ("KXHIGHLAX", "KLAX", "CLILAX", "America/Los_Angeles"),
    "miami": ("KXHIGHMIA", "KMIA", "CLIMIA", "America/New_York"),
    "san-francisco": ("KXHIGHTSFO", "KSFO", "CLISFO", "America/Los_Angeles"),
    "seattle": ("KXHIGHTSEA", "KSEA", "CLISEA", "America/Los_Angeles"),
}
SERIES_CITY = {v[0]: k for k, v in CITIES.items()}

# The allowlisted fetch extracts (runs 20261031T113920Z, T115036Z, T121034Z; R13 archive copies).
DEFAULT_TWIN_DIR = r"C:\t\l14net\out_v1"
DEFAULT_V0_LIVE = r"C:\t\l14net\out_v0\v0_markets.jsonl"
INPUT_SHA256 = {
    "v0_live": "cfec19743fdf57f9b31416c0c71784135ea445c555528bf36d5be5cc0c64b6ac",
    "receipts.jsonl": "91eed4a0d8426652665e63c50f01b3e99ea4969be0d3ed648739b1c77358b104",
    "v0_markets_hist.jsonl": "48e9e3bfca644bc70c450bdd7d4389e7b7db3a671a9bb18e721ddff6d60961c4",
    "event_markets.jsonl": "e2d4742c76c91166bb4e8ab019d01ddc3ab6f465d4bd60fa10bb7ac2cfe46a4b",
    "kalshi_candles.jsonl": "711bbeefee2e57a451ce63477e251db90a9f4793b441a9a954263d3625d0ee36",
}

ARMS = (("KAL-MEAN", "C", 1), ("KAL-WIDTH", "S", 1))
FEX_ID = "FEX-MEAN"
FEX_REOPEN_IF = ("a public ForecastEx filing or contract spec that names each city's settlement station.")
LABEL_SURVIVOR = "Survivor"
LABEL_KILL_EDGE = "KILL at edge size"
LABEL_NULL = "screen null; underpowered for information"
LABEL_UNTESTABLE = "UNTESTABLE"


class P0Error(mg.GateError):
    pass


# ----------------------------------------------------------------------------- pins

def _sha_bytes(b):
    import hashlib

    return hashlib.sha256(b).hexdigest()


def check_docs(doc_dir=None, pins=None):
    """Every governing document must match its pinned sha256; returns {file: sha}."""
    doc_dir = Path(doc_dir) if doc_dir else paths.docs_path(*DOC_DIR)
    pins = pins or DOC_SHA256
    out = {}
    for name, want in pins.items():
        p = doc_dir / name
        if not p.exists():
            raise P0Error(f"refused: governing document {p} is missing")
        got = _sha_bytes(p.read_bytes())
        if got != want:
            raise P0Error(f"refused: {name} sha256 {got} is not the pinned {want}")
        out[name] = got
    return out


def pin_amendment_copy(src, out_dir, want=AMENDMENT_SHA256):
    """Write a byte-identical copy of the amendment into ``out_dir`` (exclusive create). An existing copy must
    match the pin; anything else refuses. Returns (path, sha)."""
    data = Path(src).read_bytes()
    if _sha_bytes(data) != want:
        raise P0Error(f"refused: {src} is not the pinned amendment {want}")
    dst = Path(out_dir) / AMENDMENT_FILE
    if dst.exists():
        got = _sha_bytes(dst.read_bytes())
        if got != want:
            raise P0Error(f"refused: pinned copy {dst} sha256 {got} is not {want}")
        return dst, got
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("xb") as fh:
        fh.write(data)
    got = _sha_bytes(dst.read_bytes())
    if got != want:
        raise P0Error(f"refused: pinned copy {dst} did not write byte-identically")
    return dst, got


def check_inputs(twin_dir, v0_live, pins=None):
    pins = pins or INPUT_SHA256
    files = {"v0_live": Path(v0_live), **{n: Path(twin_dir) / n for n in pins if n != "v0_live"}}
    out = {}
    for name, p in files.items():
        if not p.exists():
            raise P0Error(f"refused: input {p} is missing")
        got = ls.sha256_file(p)
        if got != pins[name]:
            raise P0Error(f"refused: input {p} sha256 {got} is not the pinned {pins[name]}")
        out[name] = {"path": str(p), "sha256": got}
    return out


# ----------------------------------------------------------------------------- V0 on the kept events

def event_of(ticker):
    return ticker.rsplit("-", 1)[0]


def ticker_date(ticker):
    from weather.sources.free_screens import s31_venue_fetch as vf

    return vf.kalshi_ticker_date(ticker)


def in_kal_range(event_ticker):
    """True iff the event is in a bound KAL series and dated 08-14..09-29 (amendment §3)."""
    series = event_ticker.split("-", 1)[0]
    if series not in SERIES_CITY:
        return False
    d = ticker_date(event_ticker)
    return KAL_FIRST <= d <= KAL_LAST


def interval(row):
    """Integer-degree interval (lo, hi) inclusive (None = open) and z (rule §4, amendment §4 row 7)."""
    st, lo, hi = row.get("strike_type"), row.get("floor_strike"), row.get("cap_strike")
    if st == "less" and hi is not None:
        x = float(hi)
        return (None, x - 1), (x - 1) - TAIL_W / 2
    if st == "greater" and lo is not None:
        y = float(lo)
        return (y + 1, None), (y + 1) + TAIL_W / 2
    if st == "between" and lo is not None and hi is not None:
        a, b = float(lo), float(hi)
        return (a, b), (a + b) / 2
    return None, None


def tiles(ivs):
    """Six intervals that tile the integer line from an open lower tail to an open upper tail."""
    if len(ivs) != N_MARKETS_PER_EVENT or any(iv is None for iv in ivs):
        return False
    s = sorted(ivs, key=lambda iv: -math.inf if iv[0] is None else iv[0])
    if s[0][0] is not None or s[-1][1] is not None:
        return False
    for a, b in zip(s, s[1:]):
        if a[1] is None or b[0] is None or b[0] != a[1] + 1:
            return False
    return all(iv[0] is None or iv[1] is None or iv[0] <= iv[1] for iv in s)


def rules_ok(rows, city, d):
    """V0.1 restated (amendment §3-§4 rows 3-4): TWC named, no CLI source, and from 08-15 the CLI-coded station."""
    code = CITIES[city][2]
    for r in rows:
        text = f"{r.get('rules_primary') or ''} {r.get('rules_secondary') or ''}"
        low = text.lower()
        if TWC not in low:
            return False, "rules do not name The Weather Company"
        if any(m in low for m in CLI_MARKERS):
            return False, "rules name the NWS CLI source"
        if d >= CODE_FROM and f"({code})" not in text:
            return False, f"rules do not name {code}"
    return True, None


def v0_table(market_rows, meta_rows):
    """Per kept event: city, date, markets with intervals and z, and the V0 verdict. A V0.1 failure drops the city
    from that date on; a V0.2 or metadata failure drops the event only."""
    by_event = defaultdict(dict)
    conflict = set()
    for r in market_rows:
        e = r.get("event_ticker") or ""
        if not in_kal_range(e) or event_of(r["ticker"]) != e:
            continue
        key = tuple(r.get(k) for k in ("strike_type", "floor_strike", "cap_strike", "rules_primary",
                                       "rules_secondary"))
        prev = by_event[e].get(r["ticker"])
        if prev is not None and prev[0] != key:
            conflict.add(e)
        by_event[e][r["ticker"]] = (key, r)
    meta = defaultdict(set)
    for r in meta_rows:
        if in_kal_range(r.get("event_ticker") or ""):
            meta[r["event_ticker"]].add(r["market_ticker"])
    out = {}
    for e in sorted(by_event):
        city = SERIES_CITY[e.split("-", 1)[0]]
        d = ticker_date(e)
        rows = [v[1] for _, v in sorted(by_event[e].items())]
        ivz = {r["ticker"]: interval(r) for r in rows}
        ok01, why01 = rules_ok(rows, city, d)
        ok02 = e not in conflict and tiles([iv for iv, _ in ivz.values()])
        meta_match = (meta[e] == set(ivz)) if e in meta else None
        out[e] = {"city": city, "date": d.isoformat(), "role": "burn-in" if d < CODE_FROM else "scored",
                  "markets": {t: {"interval": list(iv) if iv else None, "z": z} for t, (iv, z) in ivz.items()},
                  "v0_1": ok01, "v0_1_reason": why01, "v0_2": bool(ok02), "meta_match": meta_match}
    for city in CITIES:
        evs = sorted((v["date"], e) for e, v in out.items() if v["city"] == city)
        first_fail = next((d for d, e in evs if not out[e]["v0_1"]), None)
        for d, e in evs:
            v = out[e]
            dropped_from = first_fail is not None and d >= first_fail
            v["kept"] = bool(not dropped_from and v["v0_2"] and v["meta_match"] is not False)
            v["drop_reason"] = (None if v["kept"] else
                                f"V0.1 change from {first_fail}" if dropped_from else
                                "V0.2 tiling" if not v["v0_2"] else "metadata tickers differ")
    return out


# ----------------------------------------------------------------------------- twin quotes at t_eff

def load_candles(candle_rows, kept_tickers):
    """{ticker: (ts, bid, ask)} sorted by ts, for kept tickers only. Rows of other events (08-01..08-13, dropped
    events) are skipped before any price field is touched. A conflicting duplicate refuses; a finite quote
    outside [0, 1] refuses (unit check: the rule's quotes are dollars)."""
    acc = defaultdict(dict)
    for r in candle_rows:
        t = r.get("ticker")
        if t not in kept_tickers:
            continue
        ts = int(r["end_period_ts"])
        bid, ask = (np.nan if r.get(k) is None else float(r[k]) for k in ("yes_bid_close", "yes_ask_close"))
        for v in (bid, ask):
            if np.isfinite(v) and not (0.0 <= v <= 1.0):
                raise P0Error(f"refused: candle quote {v} for {t} is outside [0, 1]; unit mismatch")
        prev = acc[t].get(ts)
        if prev is not None and not (np.array_equal(prev, (bid, ask), equal_nan=True)):
            raise P0Error(f"refused: conflicting candles for {t} at {ts}")
        acc[t][ts] = (bid, ask)
    out = {}
    for t, d in acc.items():
        ts = np.array(sorted(d), np.int64)
        out[t] = (ts, np.array([d[x][0] for x in ts], float), np.array([d[x][1] for x in ts], float))
    return out


def t_cut_utc(target_date, cutoff_hour, tz_name):
    """UTC epoch seconds of ``cutoff_hour``:00 local on the target date (24 = next local midnight); None when
    the cutoff is missing or not an integer hour in 0..24."""
    try:
        h = float(cutoff_hour)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(h) or h != int(h) or not 0 <= h <= 24:
        return None
    d = date.fromisoformat(str(target_date))
    zone = ZoneInfo(tz_name)
    local = (datetime(d.year, d.month, d.day, tzinfo=zone) if h < 24 else
             datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=zone))
    if h < 24:
        local = local.replace(hour=int(h))
    return int(local.astimezone(timezone.utc).timestamp())


def t_eff_utc(captured_at_utc, target_date, cutoff_hour, tz_name):
    """min(t_c, T_cut) in UTC epoch seconds, or None (no capture time or no cutoff: uncovered)."""
    tc = pd.to_datetime(captured_at_utc, utc=True, errors="coerce")
    if pd.isna(tc):
        return None
    cut = t_cut_utc(target_date, cutoff_hour, tz_name)
    if cut is None:
        return None
    return min(int(tc.timestamp()), cut)


def quote(candles, t_eff):
    """Mid of the latest candle with end_period_ts in [t_eff - 60 min, t_eff], if valid; else None."""
    if candles is None:
        return None
    ts, bid, ask = candles
    i = int(np.searchsorted(ts, t_eff, side="right")) - 1
    if i < 0 or ts[i] < t_eff - QUOTE_WINDOW_S:
        return None
    b, a = bid[i], ask[i]
    if not (np.isfinite(b) and np.isfinite(a) and 0 < b <= a < 1 and a - b <= MAX_SPREAD + 1e-12):
        return None
    return (b + a) / 2


def moments(mids, zs):
    """q = mids / sum, mu_t = sum q z, sigma_t = sqrt(max(sum q (z - mu)^2, 0.25))."""
    m, z = np.asarray(mids, float), np.asarray(zs, float)
    q = m / m.sum()
    mu = float((q * z).sum())
    var = max(float((q * (z - mu) ** 2).sum()), ms.SIGMA2_FLOOR)
    return mu, math.sqrt(var)


def twin_values(snaps, v0, candles):
    """mu_t and sigma_t per snapshot (NaN where uncovered) and the uncovered reason counts (amendment §4 row 6).

    ``snaps`` needs market, date, captured_at_utc, cutoff_hour; ``station`` is checked when present."""
    n = len(snaps)
    mu, sd = np.full(n, np.nan), np.full(n, np.nan)
    events = {(v["city"], v["date"]): (e, v) for e, v in v0.items()}
    reasons = defaultdict(int)
    has_station = "station" in snaps.columns
    cols = [snaps[c].to_numpy() for c in ("market", "date", "captured_at_utc", "cutoff_hour")]
    stations = snaps["station"].astype(str).to_numpy() if has_station else None
    for i, (mk, d, tc, ch) in enumerate(zip(*cols)):
        mk, d = str(mk), str(d)
        if mk not in CITIES:
            reasons["not a KAL market"] += 1
            continue
        if not (KAL_FIRST.isoformat() <= d <= KAL_LAST.isoformat()):
            reasons["date outside 08-14..09-29 (amendment)"] += 1
            continue
        if has_station and stations[i] != CITIES[mk][1]:
            reasons["snapshot station is not the twin station"] += 1
            continue
        hit = events.get((mk, d))
        if hit is None:
            reasons["no event"] += 1
            continue
        e, v = hit
        if not v["kept"]:
            reasons[f"event dropped: {v['drop_reason']}"] += 1
            continue
        te = t_eff_utc(tc, d, ch, CITIES[mk][3])
        if te is None:
            reasons["no finite cutoff_hour or capture time"] += 1
            continue
        mids, zs = [], []
        for t, spec in v["markets"].items():
            qv = quote(candles.get(t), te)
            if qv is None:
                break
            mids.append(qv)
            zs.append(spec["z"])
        if len(mids) != N_MARKETS_PER_EVENT:
            reasons["not all six markets quoted at t_eff"] += 1
            continue
        mu[i], sd[i] = moments(mids, zs)
        reasons["covered"] += 1
    return mu, sd, dict(sorted(reasons.items()))


# ----------------------------------------------------------------------------- block-3 interval and labels

def block_counts(n_dates, draws=ms.DRAWS, seed=ms.SEED, block=BLOCK_LEN):
    """Moving-block bootstrap date counts (Clarification 1: blocks of 3 consecutive dates, start uniform on
    0..n-3, concatenated and cut to n)."""
    rng = np.random.default_rng(seed)
    n_blocks = -(-n_dates // block)
    out = np.zeros((draws, n_dates), int)
    span = max(1, n_dates - block + 1)
    for b in range(draws):
        starts = rng.integers(0, span, n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n_dates]
        out[b] = np.bincount(np.minimum(idx, n_dates - 1), minlength=n_dates)
    return out


def block3_interval(rows):
    """The paired-delta 95% interval under the block-3 draws, over the dates that have entries (date order)."""
    rows = sorted(rows, key=lambda r: r["date"])
    keep = [r for r in rows if r["n_entries"] > 0]
    sums_c = np.array([r["sums_c"] for r in keep], float).T
    sums_pl = [np.array([r["sums_pl"][j] for r in keep], float).T for j in range(len(keep[0]["sums_pl"]))]
    res = ms.paired_delta(sums_c, sums_pl, block_counts(len(keep)))
    return {"ci95": res["ci95"], "p_one_sided": res["p_one_sided"], "n_dates": len(keep), "block": BLOCK_LEN}


def label(res):
    """Clarification 2 (D3) label from a scored result (testable, survive, ci95, block3)."""
    if not res.get("testable"):
        return LABEL_UNTESTABLE
    if res.get("survive"):
        return LABEL_SURVIVOR
    uppers = [res["p0"]["ci95"][1], (res.get("block3") or {}).get("ci95", [None, None])[1]]
    upper = max(u for u in uppers if u is not None)
    res["label_upper"] = upper
    return LABEL_KILL_EDGE if upper < DELTA_EDGE else LABEL_NULL


def fex_result():
    return {"candidate": FEX_ID, "type": "C", "sign": 1, "testable": False,
            "reason": "master ruling 2026-10-31: FEX (i) UNTESTABLE; no ForecastEx filing names a per-city "
                      "station (Clarification 4 §4); no pairs row read", "reopen_if": FEX_REOPEN_IF,
            "coverage": {"population_snapshots": 0, "population_dates": 0},
            "p0": {"p_one_sided": 1.0, "delta": None, "ci95": [None, None]}}


def apply_bh(results, ids):
    adj, reject = ms.bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    for cid, q, rj in zip(ids, adj, reject):
        r = results[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"] = float(q)
        r["bh_reject"] = bool(rj)
        r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["label"] = label(r)
    return results


def register_line(r, amendment_sha=AMENDMENT_SHA256):
    head = f"S31 {r['candidate']} (rule d50112cc + amendment {amendment_sha[:8]}, ledger row {LEDGER_ROW})"
    if not r["testable"]:
        return f"{head}: {LABEL_UNTESTABLE}. Reopen-if: {r.get('reopen_if') or 'coverage floors met'}"
    ci = r["p0"]["ci95"]
    return (f"{head}: {r['label']}; delta {r['p0']['delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}], "
            f"label upper {r.get('label_upper', ci[1]):+.4f} vs edge {DELTA_EDGE}; realised N "
            f"{r['coverage']['population_dates']} dates (N80 {N80}); BH q {r['bh_q']:.3f}")


# ----------------------------------------------------------------------------- the run

def _jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def run(*, layout, out_dir, twin_dir=DEFAULT_TWIN_DIR, v0_live=DEFAULT_V0_LIVE, allow_dirty=False):
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.sources.free_screens import s31_venue_fetch as vf

    out = Path(out_dir)
    if (out / "s31_p0.json").exists():
        raise P0Error(f"refusing to overwrite {out / 's31_p0.json'}")
    docs = check_docs()
    inputs = check_inputs(twin_dir, v0_live)
    copy_path, copy_sha = pin_amendment_copy(paths.docs_path(*DOC_DIR, AMENDMENT_FILE), out)

    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    if set(fit_t.markets) & {"toronto"}:
        raise P0Error("toronto is not in the rule population")
    if KAL_BURN_IN[0] not in burn or scored[0] <= KAL_BURN_IN[-1]:
        raise P0Error("the KAL burn-in 2026-08-14 must be a burn-in date before the scored dates")
    controls = mg.market_controls(fit_t, score_t)  # unamended tables (amendment §3)
    kal_fit = sc.Table(lay, list(KAL_BURN_IN) + scored)
    snaps = kal_fit.snaps
    if "target_date" in snaps.columns and (snaps.target_date.astype(str) != snaps.date.astype(str)).any():
        raise P0Error("snapshot target_date differs from date")

    live = _jsonl(v0_live)
    hist = vf.load_extract(twin_dir, "v0_markets_hist.jsonl")
    meta = vf.load_extract(twin_dir, "event_markets.jsonl")
    v0 = v0_table(live + hist, meta)
    kept = {t for v in v0.values() if v["kept"] for t in v["markets"]}
    candles = load_candles(vf.load_extract(twin_dir, "kalshi_candles.jsonl"), kept)
    mu_t, sd_t, reasons = twin_values(snaps, v0, candles)
    for city in CITIES:
        sel = snaps.market.astype(str).to_numpy() == city
        if sel.any() and "station" in snaps.columns and not (snaps.station.astype(str).to_numpy()[sel]
                                                             == CITIES[city][1]).any():
            raise P0Error(f"no {city} snapshot names station {CITIES[city][1]}; station format check failed")

    geo = ms.band_geometry(kal_fit)
    values = {"KAL-MEAN": mu_t, "KAL-WIDTH": sd_t - np.sqrt(geo["var"])}
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = ms.boot_counts(len(score_dates))
    donors = {seed: ms.donor_positions(kal_fit, seed) for seed in ms.PLACEBO_SEEDS}

    results, kept_vecs, rows = {}, {}, []
    for cid, kind, sign in ARMS:
        res, vecs = ms.p0_candidate(cid, kind, sign, values[cid], kal_fit, score_t, geo, counts, score_dates,
                                    donors)
        arm_rows = res.pop("_rows", [])
        if res["testable"]:
            res["block3"] = block3_interval(arm_rows)
        rows += arm_rows
        results[cid] = res
        if vecs is not None:
            kept_vecs[cid] = vecs
    results[FEX_ID] = fex_result()
    ids = [a[0] for a in ARMS] + [FEX_ID]
    apply_bh(results, ids)

    for cid in [c for c in ids if results[c]["survive"]]:
        vec = kept_vecs[cid]
        controls[f"w0_identity_{cid}"] = mb.w0_identity(score_t, mb.restrict(kal_fit, score_t, vec["c_fit"]))
        if controls[f"w0_identity_{cid}"]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, "00-23", kal_fit, score_t, vec["c_fit"], vec["covered"],
                              p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}
        for row in rows:
            if row["candidate"] == cid:
                row["w"] = g["w"]["w_by_date"].get(row["date"])

    receipt = {
        "schema": SCHEMA, "gate": GATE, "ledger_row": LEDGER_ROW, "code": code,
        "evidence_class": "development (dev window, provisional; class SCREEN, N80 78)",
        "doc_sha256": docs, "amendment_sha256": AMENDMENT_SHA256,
        "amendment_copy": {"path": str(copy_path), "sha256": copy_sha},
        "module_sha256": {"s31_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(ms.__file__),
                          "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__),
                          "s31_venue_fetch": ls.sha256_file(vf.__file__)},
        "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
        "input_sha256": inputs,
        "v0": {"events": v0, "n_events": len(v0), "n_kept": sum(v["kept"] for v in v0.values())},
        "population": {"control_burn_in_dates": burn, "kal_burn_in_dates": list(KAL_BURN_IN),
                       "kal_event_range": [KAL_FIRST.isoformat(), KAL_LAST.isoformat()],
                       "scored_first": scored[0], "scored_last": scored[-1], "n_scored_dates": len(scored),
                       "kal_markets": sorted(CITIES), "kal_fit_snapshots": int(len(snaps)),
                       "uncovered_reasons": reasons},
        "constants": {"draws": ms.DRAWS, "seed": ms.SEED, "placebo_seeds": list(ms.PLACEBO_SEEDS),
                      "bh_q": ms.BH_Q, "k": len(ids), "sigma2_floor": ms.SIGMA2_FLOOR, "min_dates": ms.MIN_DATES,
                      "min_snapshots": ms.MIN_SNAPS, "quote_window_s": QUOTE_WINDOW_S, "max_spread": MAX_SPREAD,
                      "tail_w": TAIL_W, "delta_edge": DELTA_EDGE, "block_len": BLOCK_LEN, "n80": N80},
        "controls": controls, "results": results,
        "labels": {c: results[c]["label"] for c in ids},
        "register_lines": [register_line(results[c]) for c in ids if results[c]["label"] != LABEL_SURVIVOR],
    }
    (out / "s31_p0_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                   for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "s31_p0_rows.jsonl")
    with (out / "s31_p0.json").open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default))
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.s31_p0", description=__doc__.splitlines()[0])
    ap.add_argument("--layout", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--twin-dir", default=DEFAULT_TWIN_DIR)
    ap.add_argument("--v0-live", default=DEFAULT_V0_LIVE)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args(argv)
    from weather.calibration import market_blend as mb

    try:
        rec = run(layout=a.layout, out_dir=a.out, twin_dir=a.twin_dir, v0_live=a.v0_live,
                  allow_dirty=a.allow_dirty)
    except mb.ControlFailed as exc:
        print(f"S31 P0 refused (controls): {exc}", file=sys.stderr)
        return 7
    except ls.ScreenError as exc:
        print(f"S31 P0 refused: {exc}", file=sys.stderr)
        return 2
    for c, lab in rec["labels"].items():
        print(f"{c}: {lab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
