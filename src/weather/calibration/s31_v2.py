r"""S31 v2: coverage-tolerant twin summaries and covered-only placebo donors (lane L14, 2026-10-31).

Rule ``docs/research/s31-other-venue-prices-2026-10-31/rule_s31_v2.md`` (dev-window ledger row 102) on top of
``rule_s31_p0.md``, AMENDMENT 1 and Clarifications 1-5, which ``weather.calibration.s31_p0`` implements and
which this module reuses unchanged except for:

- **Twin summary (rule §4).** At least k = 5 of the 6 bins quoted at t_eff; one missing bin's mid is imputed as
  max(0, 1 - sum of the five quoted mids); then the unchanged moments.
- **Placebo donors (rule §5).** Donors are covered snapshots only, within (market, local hour); a seed whose
  donor is unavailable is dropped for that snapshot (not the snapshot); dropped-seed counts are disclosed.
  ``mr_sweep.p0_candidate`` (and its ``donor_ok``) is not used.
- **Family (rule §3).** K = 2 (KAL-MEAN, KAL-WIDTH); FEX-MEAN is UNTESTABLE outside the family.
- **Projection (rule §6).** ``project`` reads quote presence and timestamps only, through field allowlists:
  no bid, ask, price or volume value is ever materialised as a number.

    python -m weather.calibration.s31_v2 project --layout C:/swarm/v3layout --out C:/t/l14v2/proj
    python -m weather.calibration.s31_v2 run --layout C:/swarm/v3layout --out C:/t/l14v2/run1
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from weather import paths
from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as ms
from weather.calibration import s31_p0 as sp

SCHEMA = "s31_v2/1"
GATE = "S31-V2"
LEDGER_ROW = 102
RULE_FILE = "rule_s31_v2.md"
RULE_SHA256 = None  # pinned at freeze; ``run`` refuses while None
K_MIN = 5
J_MIN = 10
ARMS = sp.ARMS
FAMILY = tuple(a[0] for a in ARMS)  # K = 2
POWER_MIN = 0.5

# Field allowlists for the outcome-blind projection (rule §6).
CANDLE_KEEP = ("job", "run_id", "ticker", "end_period_ts")
CANDLE_PRESENCE = ("yes_bid_close", "yes_ask_close")
SNAP_COLUMNS = ("row_key", "market", "station", "date", "captured_at_utc", "cutoff_hour", "local_hour", "n_bands")

ORIGIN_MODULES = sp.ORIGIN_MODULES + ("weather.calibration.s31_v2",)


class V2Error(sp.P0Error):
    pass


# ----------------------------------------------------------------------------- twin summary (rule §4)

def impute(mids):
    """Five quoted mids (None for the missing one) -> six mids with the complement imputed; six pass through."""
    missing = [i for i, v in enumerate(mids) if v is None]
    if not missing:
        return list(mids), None
    if len(missing) != 1:
        raise ValueError("impute needs at most one missing bin")
    out = list(mids)
    out[missing[0]] = max(0.0, 1.0 - sum(v for v in mids if v is not None))
    return out, missing[0]


def _position(i, zs):
    order = np.argsort(zs, kind="mergesort")
    rank = int(np.where(order == i)[0][0])
    return "lower tail" if rank == 0 else "upper tail" if rank == len(zs) - 1 else "interior"


def twin_scan(snaps, v0, quote_at, with_moments=True):
    """Per snapshot: the number of bins quoted and, with ``with_moments``, mu_t and sigma_t under rule §4.

    ``quote_at(ticker, t_eff)`` returns a mid (or any non-None marker for presence) or None. The eligibility
    chain (KAL market, 08-14..09-29, station, kept event, finite t_eff) is s31_p0's, unchanged."""
    n = len(snaps)
    mu, sd = np.full(n, np.nan), np.full(n, np.nan)
    nq = np.zeros(n, int)
    covered = np.zeros(n, bool)
    events = {(v["city"], v["date"]): (e, v) for e, v in v0.items()}
    reasons, missing_pos = defaultdict(int), defaultdict(int)
    has_station = "station" in snaps.columns
    cols = [snaps[c].to_numpy() for c in ("market", "date", "captured_at_utc", "cutoff_hour")]
    stations = snaps["station"].astype(str).to_numpy() if has_station else None
    lo, hi = sp.KAL_FIRST.isoformat(), sp.KAL_LAST.isoformat()
    for i, (mk, d, tc, ch) in enumerate(zip(*cols)):
        mk, d = str(mk), str(d)
        if mk not in sp.CITIES:
            reasons["not a KAL market"] += 1
            continue
        if not (lo <= d <= hi):
            reasons["date outside 08-14..09-29 (amendment)"] += 1
            continue
        if has_station and stations[i] != sp.CITIES[mk][1]:
            reasons["snapshot station is not the twin station"] += 1
            continue
        hit = events.get((mk, d))
        if hit is None:
            reasons["no event"] += 1
            continue
        _, v = hit
        if not v["kept"]:
            reasons[f"event dropped: {v['drop_reason']}"] += 1
            continue
        te = sp.t_eff_utc(tc, d, ch, sp.CITIES[mk][3])
        if te is None:
            reasons["no finite cutoff_hour or capture time"] += 1
            continue
        specs = list(v["markets"].items())
        qs = [quote_at(t, te) for t, _ in specs]
        nq[i] = sum(q is not None for q in qs)
        if nq[i] < K_MIN:
            reasons["fewer than five of six bins quoted at t_eff"] += 1
            continue
        covered[i] = True
        zs = [spec["z"] for _, spec in specs]
        reasons[f"covered ({nq[i]} of 6 quoted)"] += 1
        if nq[i] < sp.N_MARKETS_PER_EVENT:
            missing_pos[_position(next(j for j, q in enumerate(qs) if q is None), zs)] += 1
        if with_moments:
            mids, _ = impute(qs)
            mu[i], sd[i] = sp.moments(mids, zs)
    return {"mu": mu, "sd": sd, "n_quoted": nq, "covered": covered, "reasons": dict(sorted(reasons.items())),
            "missing_bin_position": dict(sorted(missing_pos.items()))}


def value_quote_at(candles):
    return lambda t, te: sp.quote(candles.get(t), te)


# ----------------------------------------------------------------------------- covered-only donors (rule §5)

def covered_donors(dates, markets, hours, captured, row_keys, n_bands, covered, seeds=ms.PLACEBO_SEEDS):
    """Per seed, the donor snapshot index of every snapshot (-1 where the seed is unavailable) and the counts.

    Donors are covered snapshots on another date in the same (market, local hour); rank r on date d takes rank
    min(r, n_d' - 1) on the deranged date d'. A seed is unavailable for a snapshot whose cell has under 2 covered
    dates or whose donor has a different band count."""
    from weather.calibration import market_blend as mb

    covered = np.asarray(covered, bool)
    idx = np.flatnonzero(covered)
    df = pd.DataFrame({"i": idx, "d": np.asarray(dates)[idx].astype(str), "m": np.asarray(markets)[idx].astype(str),
                       "h": np.asarray(hours)[idx].astype(int), "t": np.asarray(captured)[idx].astype(str),
                       "k": np.asarray(row_keys)[idx].astype(str)})
    df = df.sort_values(["m", "h", "d", "t", "k"], kind="mergesort").reset_index(drop=True)
    df["r"] = df.groupby(["m", "h", "d"], sort=False).cumcount()
    groups = [g for _, g in df.groupby(["m", "h"], sort=True)]
    nb = np.asarray(n_bands, int)
    src = np.full((len(seeds), len(covered)), -1, int)
    small_cell = sum(len(g) for g in groups if g.d.nunique() < 2)
    mismatch = np.zeros(len(seeds), int)
    for j, seed in enumerate(seeds):
        rng = np.random.default_rng(seed)
        for g in groups:
            ds = sorted(g.d.unique())
            if len(ds) < 2:
                continue
            perm = mb.derangement(len(ds), rng)
            donor = dict(zip(ds, (ds[p] for p in perm)))
            pools = g.groupby("d").i.apply(list).to_dict()
            for i, d, r in zip(g.i.to_numpy(), g.d.to_numpy(), g.r.to_numpy()):
                pool = pools[donor[d]]
                s = pool[min(r, len(pool) - 1)]
                if nb[s] != nb[i]:
                    mismatch[j] += 1
                    continue
                src[j, i] = s
    avail = src >= 0
    j_i = avail.sum(axis=0)
    stats = {"covered": int(covered.sum()), "cell_under_2_covered_dates_snapshots": int(small_cell),
             "dropped_pairs_cell_under_2_dates": int(small_cell * len(seeds)),
             "dropped_pairs_band_count_mismatch": int(mismatch.sum()),
             "band_count_mismatch_by_seed": mismatch.tolist(),
             "snapshots_with_no_seed": int((covered & (j_i == 0)).sum()),
             "seeds_available_histogram": {str(k): int(v) for k, v in
                                           zip(*np.unique(j_i[covered], return_counts=True))}}
    return src, stats


def seed_floors(avail_score, score_dates_of_snap, seeds=ms.PLACEBO_SEEDS):
    """Seeds whose available score population meets MIN_DATES and MIN_SNAPS (rule §5.7)."""
    keep, per_seed = [], []
    for j, seed in enumerate(seeds):
        a = avail_score[j]
        n_s, n_d = int(a.sum()), int(len(set(score_dates_of_snap[a])))
        ok = n_s >= ms.MIN_SNAPS and n_d >= ms.MIN_DATES
        per_seed.append({"seed": int(seed), "available_snapshots": n_s, "available_dates": n_d, "kept": ok})
        if ok:
            keep.append(j)
    return keep, per_seed


# ----------------------------------------------------------------------------- the v2 candidate (rule §5)

def _placebo_from_src(fit_t, c_fit, src_j):
    """m(d) + (c(d') - m(d')) with donor snapshots ``src_j`` (self where unavailable), clipped and renormalised
    as ``mr_sweep.disagreement_placebo``."""
    from weather.calibration import market_blend as mb

    s = np.where(src_j >= 0, src_j, np.arange(len(src_j)))
    pos = np.repeat(fit_t.offsets[s], fit_t.n) + (np.arange(len(fit_t.bands)) - np.repeat(fit_t.offsets, fit_t.n))
    m = fit_t.p_market
    raw = np.clip(m + (np.asarray(c_fit, float) - m)[pos], mb.EPS, 1.0)
    tot_m = np.bincount(fit_t.band_snap, weights=m, minlength=len(fit_t.snaps))
    tot_r = np.bincount(fit_t.band_snap, weights=raw, minlength=len(fit_t.snaps))
    return raw * np.repeat(tot_m / tot_r, fit_t.n)


def _sums(x, e, didx, band, nd):
    return ms.date_sums(x[band], e[band], didx[band], nd)


def p0_candidate_v2(cid, kind, sign, values_fit, fit_t, score_t, geo_fit, counts, score_dates, src, donor_stats):
    """Signal, tilt, covered-only placebos with per-seed availability, and the paired P0 (rule §5)."""
    from weather.calibration import market_blend as mb

    covered = np.isfinite(values_fit)
    s = ms.band_signal(kind, sign, np.where(covered, values_fit, np.nan), fit_t, geo_fit)
    c_fit, sd_s = ms.tilt(fit_t, geo_fit, s, covered)
    avail_fit = (src >= 0) & covered[None, :]
    pop_fit = covered & avail_fit.any(axis=0)
    pop = mb.restrict_snap(fit_t, score_t, pop_fit)
    avail = np.stack([mb.restrict_snap(fit_t, score_t, a) for a in avail_fit]) & pop[None, :]
    snap_dates = score_t.snaps.date.astype(str).to_numpy()
    keep, per_seed = seed_floors(avail, snap_dates)
    m, y = score_t.p_market, score_t.y
    e = y - m
    nd = len(score_dates)
    didx = np.searchsorted(score_dates, snap_dates)[score_t.band_snap]
    c = mb.restrict(fit_t, score_t, c_fit)
    band = pop[score_t.band_snap]
    sums_c = _sums(c - m, e, didx, band, nd)
    pl_fit = {j: _placebo_from_src(fit_t, c_fit, src[j]) for j in keep}
    pls = {j: mb.restrict(fit_t, score_t, pl_fit[j]) for j in keep}
    bands_j = {j: avail[j][score_t.band_snap] for j in keep}
    sums_pl = [_sums(pls[j] - m, e, didx, bands_j[j], nd) for j in keep]
    n_dates = int((sums_c[0] > 0).sum())
    n_snaps = int(pop.sum())
    res = {"candidate": cid, "type": kind, "sign": sign, "sd_s": sd_s,
           "coverage": {"fit_covered_snapshots": int(covered.sum()), "fit_snapshots": int(len(covered)),
                        "population_snapshots": n_snaps, "population_dates": n_dates,
                        "score_snapshots": int(len(score_t.snaps))},
           "donors": {**donor_stats, "per_seed": per_seed, "seeds_kept": len(keep),
                      "seeds_dropped_entirely": [p["seed"] for p in per_seed if not p["kept"]]}}
    if n_dates < ms.MIN_DATES or n_snaps < ms.MIN_SNAPS or len(keep) < J_MIN:
        res.update(testable=False, p0={"p_one_sided": 1.0, "delta": None, "ci95": [None, None]})
        return res, None
    res["testable"] = True
    res["p0"] = ms.paired_delta(sums_c, sums_pl, counts)
    first = np.full(len(fit_t.snaps), -1, int)  # each snapshot's lowest-numbered available kept seed
    for j in reversed(keep):
        first = np.where(src[j] >= 0, src[j], first)
    a_src = first
    pl0_fit = _placebo_from_src(fit_t, c_fit, a_src)
    a_fit_pos = np.where(a_src >= 0, a_src, np.arange(len(a_src)))
    a_pos = np.repeat(fit_t.offsets[a_fit_pos], fit_t.n) + (np.arange(len(fit_t.bands))
                                                            - np.repeat(fit_t.offsets, fit_t.n))
    a_fit = np.asarray(c_fit)[a_pos]
    sums_a = _sums(mb.restrict(fit_t, score_t, a_fit) - m, e, didx, band, nd)
    rho_a = float(mg._rho(*sums_a.sum(axis=1)))
    boot_a = mg._rho(*(counts @ sums_a.T).T)
    ci_a = np.quantile(boot_a[np.isfinite(boot_a)], [0.025, 0.975]).tolist()
    res["diagnostic_c_deranged_placebo"] = {"rho": rho_a, "ci95": ci_a, "covers_0": bool(ci_a[0] <= 0 <= ci_a[1])}
    for name, labels in (("by_block", ms.hour_blocks(score_t.local_hour)), ("by_market", score_t.markets)):
        out = {}
        for lab in sorted(set(labels)):
            sel = pop & (labels == lab)
            bsel = sel[score_t.band_snap]
            if bsel.sum() < 50:
                continue
            r = ms.paired_delta(_sums(c - m, e, didx, bsel, nd),
                                [_sums(pls[j] - m, e, didx, bsel & bands_j[j], nd) for j in keep], counts)
            out[str(lab)] = {k: r[k] for k in ("delta", "ci95", "rho_c", "rho_pl_mean")}
        res[name] = out
    snap_didx = np.searchsorted(score_dates, snap_dates)
    n_snap_date = np.bincount(snap_didx[pop], minlength=nd)
    res["_rows"] = [{"candidate": cid, "date": score_dates[i], "n_entries": int(sums_c[0, i]),
                     "n_snapshots": int(n_snap_date[i]), "sums_c": sums_c[:, i].tolist(),
                     "sums_pl": [sp_[:, i].tolist() for sp_ in sums_pl]} for i in range(nd)]
    return res, {"c_fit": c_fit, "pl0_fit": pl0_fit, "covered": pop_fit}


# ----------------------------------------------------------------------------- presence-only projection (§6)

class _Float:
    """Sentinel for every JSON float token: the projection never materialises a float value."""
    __slots__ = ()


FLOAT = _Float()


def _presence_hook(pairs):
    out = {}
    for k, v in pairs:
        if k in CANDLE_KEEP:
            out[k] = v
        elif k in CANDLE_PRESENCE:
            out[k + "_present"] = v is not None
    return out


def parse_presence(line):
    """One candle JSON line through allowlist P: kept keys plus presence booleans, nothing else."""
    return json.loads(line, object_pairs_hook=_presence_hook, parse_float=lambda _s: FLOAT,
                      parse_constant=lambda _s: FLOAT)


def complete_runs(twin_dir, extract):
    done = {}
    p = Path(twin_dir) / "receipts.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("complete") and r.get("job") and r.get("extract") == extract:
                done[r["job"]] = r["run_id"]
    return done


def load_presence(twin_dir, kept_tickers, extract="kalshi_candles.jsonl"):
    """{ticker: (ts, present)} for kept tickers of complete runs; present = both sides non-null."""
    done = complete_runs(twin_dir, extract)
    acc = defaultdict(dict)
    with open(Path(twin_dir) / extract, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = parse_presence(line)
            if done.get(r.get("job")) != r.get("run_id") or r.get("ticker") not in kept_tickers:
                continue
            pres = bool(r.get("yes_bid_close_present")) and bool(r.get("yes_ask_close_present"))
            ts = int(r["end_period_ts"])
            prev = acc[r["ticker"]].get(ts)
            if prev is not None and prev != pres:
                raise V2Error(f"refused: conflicting candle presence for {r['ticker']} at {ts}")
            acc[r["ticker"]][ts] = pres
    out = {}
    for t, d in acc.items():
        ts = np.array(sorted(d), np.int64)
        out[t] = (ts, np.array([d[x] for x in ts], bool))
    return out


def presence_quote_at(presence):
    def q(t, te):
        c = presence.get(t)
        if c is None:
            return None
        ts, pres = c
        i = int(np.searchsorted(ts, te, side="right")) - 1
        if i < 0 or ts[i] < te - sp.QUOTE_WINDOW_S or not pres[i]:
            return None
        return True
    return q


def read_snapshots(layout):
    """Allowlisted columns of the manifest-verified ``inputs_snapshots.parquet``; no other layout file opened."""
    import pyarrow.parquet as pq

    from weather.reporting.scorecards import dev_scorecard_data as data

    manifest, manifest_sha = data._read_manifest(layout)
    p = Path(layout) / data.SNAPSHOTS_FILE
    got = ls.sha256_file(p)
    if got != manifest["files"][data.SNAPSHOTS_FILE]["sha256"]:
        raise V2Error(f"refused: {p} does not match its manifest sha256")
    frame = pq.read_table(p, columns=list(SNAP_COLUMNS)).to_pandas()
    if (pd.to_datetime(frame.date.astype(str)).dt.date > data.DEV_LAST).any():
        raise V2Error("refused: a snapshot after 2026-09-29")
    return frame, manifest_sha, got


def projection_population(snaps):
    """Fit snapshots (08-14 + scored) and the scored dates, as ``s31_p0.build_tables`` selects them."""
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard_data as data

    start, end = data.check_range(*mb.RANGE)
    days = pd.to_datetime(snaps.date.astype(str)).dt.date
    in_lay = snaps[((days >= data.DEV_FIRST) & (days <= end)).to_numpy()]
    folds = data.make_folds(sorted(in_lay.date.astype(str).unique()), start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    fit = in_lay[in_lay.date.astype(str).isin(list(sp.KAL_BURN_IN) + scored)].reset_index(drop=True)
    return fit, scored


def project(*, layout, twin_dir=sp.DEFAULT_TWIN_DIR, v0_live=sp.DEFAULT_V0_LIVE, input_pins=None):
    """Rule §6: presence-only coverage, donors and floors (counts only), an upper bound on the run's coverage."""
    from weather.sources.free_screens import s31_venue_fetch as vf

    inputs = sp.check_inputs(twin_dir, v0_live, input_pins)
    snaps, manifest_sha, snaps_sha = read_snapshots(layout)
    fit, scored = projection_population(snaps)
    v0 = sp.v0_table(sp._jsonl(v0_live) + vf.load_extract(twin_dir, "v0_markets_hist.jsonl"),
                     vf.load_extract(twin_dir, "event_markets.jsonl"))
    kept = {t for v in v0.values() if v["kept"] for t in v["markets"]}
    presence = load_presence(twin_dir, kept)
    scan = twin_scan(fit, v0, presence_quote_at(presence), with_moments=False)
    covered = scan["covered"]
    src, dstats = covered_donors(fit.date, fit.market, fit.local_hour, fit.captured_at_utc, fit.row_key,
                                 fit.n_bands, covered)
    avail = (src >= 0) & covered[None, :]
    pop_fit = covered & avail.any(axis=0)
    is_scored = fit.date.astype(str).isin(scored).to_numpy()
    dates = fit.date.astype(str).to_numpy()
    keep, per_seed = seed_floors(avail[:, is_scored] & pop_fit[is_scored][None, :], dates[is_scored])
    pop = pop_fit & is_scored
    kal = fit.market.astype(str).isin(list(sp.CITIES)).to_numpy() & is_scored
    n_pop_dates = len(set(dates[pop]))
    out = {"schema": SCHEMA + "-projection", "rule": RULE_FILE, "ledger_row": LEDGER_ROW,
           "upper_bound": "quote presence only; value checks (0 < bid <= ask < 1, spread <= 0.20) not applied",
           "input_sha256": inputs, "layout_manifest_sha256": manifest_sha, "snapshots_sha256": snaps_sha,
           "snapshot_columns_read": list(SNAP_COLUMNS), "candle_fields_read": list(CANDLE_KEEP),
           "candle_presence_fields": list(CANDLE_PRESENCE),
           "v0": {"n_events": len(v0), "n_kept": sum(v["kept"] for v in v0.values())},
           "scored_dates": {"first": scored[0], "last": scored[-1], "n": len(scored)},
           "fit_snapshots": int(len(fit)), "kal_scored_snapshots": int(kal.sum()),
           "kal_scored_dates": len(set(dates[kal])),
           "covered_fit": {"total": int(covered.sum()),
                           "six_quoted": int((covered & (scan["n_quoted"] == 6)).sum()),
                           "five_quoted": int((covered & (scan["n_quoted"] == 5)).sum())},
           "missing_bin_position": scan["missing_bin_position"], "uncovered_reasons": scan["reasons"],
           "donors": {**dstats, "per_seed_scored": per_seed, "seeds_kept": len(keep),
                      "seeds_dropped_entirely": [p["seed"] for p in per_seed if not p["kept"]]},
           "population": {"snapshots": int(pop.sum()), "dates": n_pop_dates,
                          "covered_scored_snapshots": int((covered & is_scored).sum()),
                          "floors": {"min_dates": ms.MIN_DATES, "min_snapshots": ms.MIN_SNAPS, "j_min": J_MIN,
                                     "met": bool(n_pop_dates >= ms.MIN_DATES and pop.sum() >= ms.MIN_SNAPS
                                                 and len(keep) >= J_MIN)}}}
    return out


def power_at_edge(n_dates, s_full, s_proj, sigma_kal=0.09488224588269815, vif=None, delta=sp.DELTA_EDGE):
    """Rule §7: Phi(delta / SE - 1.96), SE = sigma_kal * sqrt(s_full / s_proj) * sqrt(VIF) / sqrt(N)."""
    if n_dates <= 0 or s_proj <= 0:
        return {"power": 0.0, "se": None}
    sigma = sigma_kal * math.sqrt(s_full / s_proj)
    se = sigma * math.sqrt(vif) / math.sqrt(n_dates)
    z = delta / se - 1.96
    return {"power": 0.5 * (1 + math.erf(z / math.sqrt(2))), "se": se, "sigma_proj": sigma, "vif": vif,
            "n_dates": n_dates, "s_full": s_full, "s_proj": s_proj, "delta_edge": delta}


def rev2_vif(d_by_date):
    """Rule §7 VIF: max(1, (1 + rho)/(1 - rho), ratio^2), ratio from the REV-2 circular block-3 (B 2000)."""
    d = np.asarray(d_by_date, float)
    n = len(d)
    m = d.mean()
    rho = float(((d[:-1] - m) * (d[1:] - m)).sum() / ((d - m) ** 2).sum())
    counts = sp.block_counts_circular(n)
    boot = counts @ d / n
    ratio = float(np.std(boot, ddof=1) / (np.std(d, ddof=1) / math.sqrt(n)))
    return {"rho": rho, "ratio": ratio, "vif": max(1.0, (1 + rho) / (1 - rho), ratio ** 2), "n": n}


# ----------------------------------------------------------------------------- the run (after the admit only)

def run(*, layout, out_dir, twin_dir=sp.DEFAULT_TWIN_DIR, v0_live=sp.DEFAULT_V0_LIVE, allow_dirty=False,
        input_pins=None, build=sp.build_tables, require_pythonpath=False, rule_sha=None):
    """The v2 P0. Refuses until the rule sha is pinned at freeze."""
    rule_sha = rule_sha or RULE_SHA256
    if rule_sha is None:
        raise V2Error("refused: rule_s31_v2.md is not frozen (RULE_SHA256 unset)")
    origins = sp.check_origins(modules=ORIGIN_MODULES, require_pythonpath=require_pythonpath)
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.sources.free_screens import s31_venue_fetch as vf

    out = Path(out_dir)
    if (out / "s31_v2.json").exists():
        raise V2Error(f"refusing to overwrite {out / 's31_v2.json'}")
    docs = sp.check_docs(pins={**sp.DOC_SHA256, RULE_FILE: rule_sha})
    inputs = sp.check_inputs(twin_dir, v0_live, input_pins)
    copy_path, copy_sha = sp.pin_amendment_copy(paths.docs_path(*sp.DOC_DIR, sp.AMENDMENT_FILE), out)
    manifest_sha, burn, scored, kal_fit, score_t, controls = build(layout)
    snaps = kal_fit.snaps
    v0 = sp.v0_table(sp._jsonl(v0_live) + vf.load_extract(twin_dir, "v0_markets_hist.jsonl"),
                     vf.load_extract(twin_dir, "event_markets.jsonl"))
    kept = {t for v in v0.values() if v["kept"] for t in v["markets"]}
    candles = sp.load_candles(vf.load_extract(twin_dir, "kalshi_candles.jsonl"), kept)
    scan = twin_scan(snaps, v0, value_quote_at(candles))
    geo = ms.band_geometry(kal_fit)
    values = {"KAL-MEAN": scan["mu"], "KAL-WIDTH": scan["sd"] - np.sqrt(geo["var"])}
    src, dstats = covered_donors(snaps.date, kal_fit.markets, kal_fit.local_hour, snaps.captured_at_utc,
                                 snaps.row_key, kal_fit.n, scan["covered"])
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = ms.boot_counts(len(score_dates))
    results, vecs, rows = {}, {}, []
    for cid, kind, sign in ARMS:
        res, vec = p0_candidate_v2(cid, kind, sign, values[cid], kal_fit, score_t, geo, counts, score_dates,
                                   src, dstats)
        arm_rows = res.pop("_rows", [])
        if res["testable"]:
            res["bounds"] = sp.bounds(arm_rows, counts)
        rows += arm_rows
        results[cid] = res
        if vec is not None:
            vecs[cid] = vec
    sp.apply_bh(results, list(FAMILY))
    fex = sp.fex_result()
    fex.update(label=sp.LABEL_UNTESTABLE, in_family=False, survive=False)
    for cid in [c for c in FAMILY if results[c]["survive"]]:
        vec = vecs[cid]
        controls[f"w0_identity_{cid}"] = mb.w0_identity(score_t, mb.restrict(kal_fit, score_t, vec["c_fit"]))
        if controls[f"w0_identity_{cid}"]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, "00-23", kal_fit, score_t, vec["c_fit"], vec["covered"],
                              p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}
    origins_end = sp.check_origins(modules=ORIGIN_MODULES, require_pythonpath=require_pythonpath)
    receipt = {
        "schema": SCHEMA, "gate": GATE, "ledger_row": LEDGER_ROW, "code": code, "k": len(FAMILY),
        "module_origins": origins, "module_origins_end": origins_end, "doc_sha256": docs,
        "amendment_copy": {"path": str(copy_path), "sha256": copy_sha},
        "module_sha256": {"s31_v2": ls.sha256_file(__file__), "s31_p0": ls.sha256_file(sp.__file__),
                          "mr_sweep": ls.sha256_file(ms.__file__), "mr_gate": ls.sha256_file(mg.__file__),
                          "market_blend": ls.sha256_file(mb.__file__), "s31_venue_fetch": ls.sha256_file(vf.__file__)},
        "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": manifest_sha, "input_sha256": inputs,
        "population": {"control_burn_in_dates": burn, "kal_burn_in_dates": list(sp.KAL_BURN_IN),
                       "scored_first": scored[0], "scored_last": scored[-1], "n_scored_dates": len(scored),
                       "kal_fit_snapshots": int(len(snaps)), "uncovered_reasons": scan["reasons"],
                       "missing_bin_position": scan["missing_bin_position"],
                       "five_quoted": int((scan["covered"] & (scan["n_quoted"] == 5)).sum()),
                       "six_quoted": int((scan["covered"] & (scan["n_quoted"] == 6)).sum())},
        "constants": {"k_min": K_MIN, "j_min": J_MIN, "placebo_seeds": list(ms.PLACEBO_SEEDS), "bh_q": ms.BH_Q,
                      "draws": ms.DRAWS, "seed": ms.SEED, "min_dates": ms.MIN_DATES, "min_snapshots": ms.MIN_SNAPS,
                      "quote_window_s": sp.QUOTE_WINDOW_S, "max_spread": sp.MAX_SPREAD,
                      "delta_edge": sp.DELTA_EDGE, "circular_b": sp.CIRC_B, "circular_seed": sp.CIRC_SEED},
        "controls": controls, "results": results, "fex_outside_family": fex,
        "labels": {**{c: results[c]["label"] for c in FAMILY}, sp.FEX_ID: fex["label"]},
    }
    (out / "s31_v2_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                   for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "s31_v2_rows.jsonl")
    with (out / "s31_v2.json").open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default))
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.s31_v2", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("project", "run"):
        p = sub.add_parser(name)
        p.add_argument("--layout", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--twin-dir", default=sp.DEFAULT_TWIN_DIR)
        p.add_argument("--v0-live", default=sp.DEFAULT_V0_LIVE)
        if name == "run":
            p.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "project":
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            rec = project(layout=a.layout, twin_dir=a.twin_dir, v0_live=a.v0_live)
            with (out / "s31_v2_projection.json").open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, indent=1, sort_keys=True))
            print(json.dumps({k: rec[k] for k in ("covered_fit", "population")}, sort_keys=True))
            return 0
        from weather.calibration import market_blend as mb

        try:
            rec = run(layout=a.layout, out_dir=a.out, twin_dir=a.twin_dir, v0_live=a.v0_live,
                      allow_dirty=a.allow_dirty, require_pythonpath=True)
        except mb.ControlFailed as exc:
            print(f"S31 v2 refused (controls): {exc}", file=sys.stderr)
            return 7
    except ls.ScreenError as exc:
        print(f"S31 v2 refused: {exc}", file=sys.stderr)
        return 2
    for c, lab in rec["labels"].items():
        print(f"{c}: {lab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
