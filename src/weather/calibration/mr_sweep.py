r"""MR P0 sweep: which capture-time signals predict the market's error? (lane L3, 2026-10-30; rule ``RULE_SHA256``).

Rule ``docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`` (sha256 ``85f8192c…``, dev-window ledger row 78,
approved by master via the coordinator 2026-10-30). One run on the dev scorecard (scored 2026-08-15..09-29, all
hours); nothing later is read. Per candidate (section 3 of the rule):

1. capture-time feature values from the captured replay inputs (receipt time <= ``captured_at_utc``) or the
   layout's NBM v2 columns, turned into a band signal ``s`` (types C / S / D) and a market tilt
   ``c = sum(m) * m~ exp(s / sd_s) / norm``;
2. P0: ``rho(c - m, y - m)`` minus the reviewer's deranged-DISAGREEMENT placebo
   ``c_pl(d) = m(d) + (c(d') - m(d'))`` (clipped to [EPS, 1], renormalised to sum(m); 20 derangements, seeds
   20260921 + j) as a paired date-cluster bootstrap (10,000 draws, seed 20261024, draw b uses derangement b mod 20);
3. Benjamini-Hochberg at q = 0.10 over K = 17; survivor iff BH rejects and the paired lower bound > 0;
4. survivors only: the 37cb46be w gate (``mr_gate.gate_candidate``, block 00-23) with ``c_pl,0`` as the placebo.

Writes ``mr_sweep.json`` (never overwrites), ``mr_sweep_rows.jsonl`` (one row per candidate and date) and the
extracted capture-time ``features.parquet``. A dirty tree refuses.

    python -m weather.calibration.loyo_screen mr-sweep --layout C:/swarm/v3layout --out C:/t/l3/mr/sweep1
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg

SCHEMA = "mr_sweep/1"
GATE = "MR-SWEEP"
RULE_SHA256 = "85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956"
LEDGER_ROW = 78
DRAWS = 10_000
SEED = 20261024
PLACEBO_SEEDS = tuple(20260921 + j for j in range(20))
BH_Q = 0.10
SIGMA2_FLOOR = 0.25
MIN_DATES, MIN_SNAPS = 20, 1000
DEFAULT_REPLAY = r"C:\Users\Michael\Documents\github\weather\data\inbox\replay-inputs-le0929"
COVER = {"CLR": 0, "SKC": 0, "CAV": 0, "FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4, "VV": 4}
SLUG = re.compile(r"^highest-temperature-in-(?P<market>.+)-on-[a-z]+-\d+-\d{4}$")
SNAP_ID = re.compile(r'"snapshot_id":\s*"([^"]+)"')

# (id, type, sign, value column, receipt column) - rule section 3, rows 1-17, in order
CANDIDATES = (
    ("OM-GFS", "C", 1, "mm_gfs_seamless", "rc_mm"),
    ("OM-HRRR", "C", 1, "mm_ncep_hrrr_conus", "rc_mm"),
    ("OM-NAM", "C", 1, "mm_ncep_nam_conus", "rc_mm"),
    ("OM-IFS", "C", 1, "gm_ecmwf_ifs025", "rc_gm"),
    ("OM-AIFS", "C", 1, "gm_ecmwf_aifs025", "rc_gm"),
    ("OM-GRAPHCAST", "C", 1, "gm_gfs_graphcast025", "rc_gm"),
    ("OM-AIGFS", "C", 1, "gm_ncep_aigfs025", "rc_gm"),
    ("OM-BEST", "C", 1, "om_best", "rc_om"),
    ("OM-MM-SPREAD", "S", 1, "mm_spread", "rc_mm"),
    ("OM-GM-SPREAD", "S", 1, "gm_spread", "rc_gm"),
    ("GEFS-CONTROL", "C", 1, "ge_control", "rc_ge"),
    ("GEFS-MEMBER-CENTRE", "C", 1, "ge_centre", "rc_ge"),
    ("NBM-SKEW", "D", 1, "nbm_skew", "rc_nbm"),
    ("MET-MAX", "C", 1, "met_max", "rc_met"),
    ("MET-COOLING", "D", 1, "met_cooling", "rc_met"),
    ("MET-DEWDEP", "D", 1, "met_dewdep", "rc_met"),
    ("MET-COVER", "D", -1, "met_cover", "rc_met"),
)
MM_MODELS = ("gfs_seamless", "ncep_hrrr_conus", "ncep_nam_conus")
GM_MODELS = ("ecmwf_ifs025", "ecmwf_aifs025", "gfs_graphcast025", "ncep_aigfs025")


class SweepError(mg.GateError):
    pass


# ----------------------------------------------------------------------------- capture-time features

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return np.nan
    return f if np.isfinite(f) else np.nan


def _cover(v):
    if not isinstance(v, str) or not v.strip():
        return np.nan
    tok = v.strip().upper().split()[0]
    for key, code in COVER.items():
        if tok.startswith(key):
            return float(code)
    return np.nan


def record_features(rec):
    """One replay record -> value and receipt-time columns (rule section 2); a source that is not ``ok`` gives
    NaN values and no receipt."""
    src = rec.get("sources") or {}

    def source(name):
        s = src.get(name) or {}
        if s.get("ok") is not True:
            return None, None
        return (s.get("data") or {}), s.get("fetched_at")

    out = {}
    d, rc = source("open_meteo_multimodel")
    highs = (d or {}).get("day_model_highs") or {}
    for mdl in MM_MODELS:
        out[f"mm_{mdl}"] = _num(highs.get(mdl)) if d is not None else np.nan
    out["mm_spread"] = _num((d or {}).get("day_high_spread")) if d is not None else np.nan
    out["rc_mm"] = rc
    d, rc = source("open_meteo_global_models")
    highs = (d or {}).get("day_model_highs") or {}
    for mdl in GM_MODELS:
        out[f"gm_{mdl}"] = _num(highs.get(mdl)) if d is not None else np.nan
    out["gm_spread"] = _num((d or {}).get("day_high_spread")) if d is not None else np.nan
    out["rc_gm"] = rc
    d, rc = source("open_meteo")
    out["om_best"] = _num((d or {}).get("day_max_native")) if d is not None else np.nan
    out["rc_om"] = rc
    d, rc = source("global_ensemble")
    d = d or {}
    out["ge_control"] = _num(d.get("day_max_native"))
    out["ge_centre"] = (_num(d.get("day_member_high_p10")) + _num(d.get("day_member_high_p90"))) / 2
    out["rc_ge"] = rc
    d, rc = source("metar")
    if d is None or d.get("target_date_match") is not True:
        d, rc = {}, None
    t, mx, dp = _num(d.get("temp_native")), _num(d.get("same_day_max_native")), _num(d.get("dewpoint_native"))
    out.update(met_max=mx, met_cooling=t - mx, met_dewdep=t - dp, met_cover=_cover(d.get("cover")),
               rc_met=rc, rc_met_report=d.get("report_time"))
    return out


def extract_features(replay_root, row_keys):
    """Stream every replay record of the layout's snapshots (read only); returns (one row per row_key, records
    read, malformed lines). A line that does not parse (a truncated write) carries no capture-time value: it is
    skipped and listed, so its snapshot is uncovered unless another complete record has it."""
    root = Path(replay_root) / "snapshots"
    keys, rows, seen, malformed = set(row_keys), [], 0, []
    markets = {k.split("|", 1)[0] for k in keys}
    for folder in sorted(root.iterdir()):
        hit = SLUG.match(folder.name)
        f = folder / "replay_inputs.jsonl"
        if not hit or hit["market"] not in markets or not f.exists():
            continue
        market = hit["market"]
        with f.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not any(f"{market}|{sid}" in keys for sid in SNAP_ID.findall(line)):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    malformed.append({"file": folder.name, "line": lineno, "chars": len(line), "error": str(exc)[:120],
                                      "snapshot_ids": SNAP_ID.findall(line)[:3]})
                    continue
                rk = f"{market}|{rec.get('snapshot_id')}"
                if rk not in keys:
                    continue
                seen += 1
                rows.append({"row_key": rk, "replay_captured_at_utc": rec.get("captured_at_utc"),
                             **record_features(rec)})
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SweepError(f"no replay record matched the layout under {root}")
    return frame.drop_duplicates("row_key", keep="last").reset_index(drop=True), seen, malformed


def _utc(series):
    """ISO strings (any offset) -> naive UTC datetime64[ns] numpy array (NaT where missing or unparseable)."""
    t = pd.to_datetime(pd.Series(np.asarray(series, dtype=object)), utc=True, format="ISO8601", errors="coerce")
    return t.dt.tz_convert(None).to_numpy("datetime64[ns]")


def candidate_values(snaps, feats):
    """Per candidate: values on ``snaps`` (NaN where uncovered: no value, no receipt, or receipt after capture)."""
    f = feats.set_index("row_key").reindex(snaps.row_key.to_numpy())
    cap = _utc(snaps.captured_at_utc)
    receipt = {c: _utc(f[c]) for c in ("rc_mm", "rc_gm", "rc_om", "rc_ge", "rc_met")}
    report = _utc(f["rc_met_report"])
    receipt["rc_met"] = np.where(np.isnat(report) | np.isnat(receipt["rc_met"]), np.datetime64("NaT", "ns"),
                                 np.maximum(receipt["rc_met"], report))
    p10, p50, p90 = (pd.to_numeric(snaps[f"v2_{q}"], errors="coerce").to_numpy(float) for q in ("p10", "p50", "p90"))
    with np.errstate(invalid="ignore", divide="ignore"):
        skew = np.where(p90 > p10, (p90 + p10 - 2 * p50) / (p90 - p10), np.nan)
    nbm_ok = (snaps.v2_status.astype(str).to_numpy() == "available") & (
        snaps.v2_available_basis.astype(str).to_numpy() == "response_received_at")
    receipt["rc_nbm"] = np.where(nbm_ok, _utc(snaps.v2_available_at), np.datetime64("NaT", "ns"))
    out = {}
    for cid, _, _, col, rc in CANDIDATES:
        v = skew if col == "nbm_skew" else f[col].to_numpy(float)
        r = receipt[rc]
        ok = np.isfinite(v) & ~np.isnat(r) & ~np.isnat(cap) & (r <= cap)
        out[cid] = np.where(ok, v, np.nan)
    return out


# ----------------------------------------------------------------------------- signals and candidate vectors

def band_geometry(table):
    """z_b per band and the normalised market moments per snapshot (rule section 1)."""
    b = table.bands
    kind, lo, hi = b.kind.astype(str).to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float)
    eq = kind == "eq"
    width = np.where(eq, hi - lo + 1, np.nan)
    w_med = pd.Series(width).groupby(table.band_snap).median().reindex(range(len(table.snaps))).to_numpy(float)
    w_b = np.repeat(np.where(np.isfinite(w_med), w_med, 1.0), table.n)
    z = np.where(eq, (lo + hi) / 2, np.where(kind == "lte", hi - w_b / 2, lo + w_b / 2))
    m = table.p_market
    tot = np.bincount(table.band_snap, weights=m, minlength=len(table.snaps))
    mt = m / np.repeat(np.where(tot > 0, tot, 1.0), table.n)
    mu = np.bincount(table.band_snap, weights=mt * z, minlength=len(table.snaps))
    dz = z - np.repeat(mu, table.n)
    var = np.bincount(table.band_snap, weights=mt * dz * dz, minlength=len(table.snaps))
    var = np.maximum(var, SIGMA2_FLOOR)
    return {"z": z, "mt": mt, "tot": tot, "mu": mu, "var": var, "dz": dz}


def standardise(values, markets):
    """g_z within market over the covered snapshots given (feature values only)."""
    out = np.full(len(values), np.nan)
    for mk in np.unique(markets):
        sel = (markets == mk) & np.isfinite(values)
        if sel.sum() >= 2:
            sd = values[sel].std()
            out[sel] = (values[sel] - values[sel].mean()) / (sd if sd > 0 else 1.0)
    return out


def band_signal(kind, sign, values, table, geo):
    """s_b (rule section 4); NaN on uncovered snapshots."""
    n = table.n
    var_b, dz = np.repeat(geo["var"], n), geo["dz"]
    if kind == "C":
        return (np.repeat(values - geo["mu"], n)) * dz / var_b
    g = np.repeat(standardise(values, table.markets), n)
    if kind == "S":
        return g * (dz * dz - var_b) / var_b
    if kind == "D":
        return sign * g * dz / np.sqrt(var_b)
    raise SweepError(f"unknown signal type {kind}")


def tilt(table, geo, s, covered):
    """c = sum(m) * m~ exp(s / sd_s) / norm on covered snapshots, the market elsewhere; returns (c, sd_s)."""
    cov_b = covered[table.band_snap]
    sd = float(np.std(s[cov_b])) if cov_b.any() else 1.0
    sd = sd if sd > 0 else 1.0
    a = np.where(cov_b, s / sd, 0.0)
    amax = pd.Series(a).groupby(table.band_snap).transform("max").to_numpy()
    w = geo["mt"] * np.exp(a - amax)
    norm = np.bincount(table.band_snap, weights=w, minlength=len(table.snaps))
    c = np.repeat(geo["tot"], table.n) * w / np.repeat(np.where(norm > 0, norm, 1.0), table.n)
    return np.where(cov_b, c, table.p_market), sd


def donor_positions(fit_t, seed):
    """``market_blend.placebo_vector``'s band permutation for ``seed`` (value-independent, so computed once)."""
    from weather.calibration import market_blend as mb

    pos, meta = mb.placebo_vector(fit_t, np.arange(len(fit_t.bands)), seed=seed)
    return pos, meta


def disagreement_placebo(fit_t, c_fit, seed, donor=None):
    """The reviewer's calibration-matched placebo on the fit table: m(d) + (c(d') - m(d')), clipped to [EPS, 1]
    and renormalised to sum(m) per snapshot; donor d' from ``market_blend.placebo_vector`` (``donor`` = a cached
    ``donor_positions(fit_t, seed)``)."""
    from weather.calibration import market_blend as mb

    m = fit_t.p_market
    pos, meta = donor if donor is not None else donor_positions(fit_t, seed)
    donor_diff = (np.asarray(c_fit, float) - m)[pos]
    raw = np.clip(m + donor_diff, mb.EPS, 1.0)
    tot_m = np.bincount(fit_t.band_snap, weights=m, minlength=len(fit_t.snaps))
    tot_r = np.bincount(fit_t.band_snap, weights=raw, minlength=len(fit_t.snaps))
    return raw * np.repeat(tot_m / tot_r, fit_t.n), meta


# ----------------------------------------------------------------------------- statistics

def date_sums(x, e, date_idx, n_dates):
    """Per-date sufficient sums (n, sx, se, sxx, see, sxe) - shape (6, n_dates)."""
    return np.stack([np.bincount(date_idx, weights=w, minlength=n_dates)
                     for w in (np.ones_like(x), x, e, x * x, e * e, x * e)])


def boot_counts(n_dates, draws=DRAWS, seed=SEED):
    rng = np.random.default_rng(seed)
    return np.stack([np.bincount(rng.integers(0, n_dates, n_dates), minlength=n_dates) for _ in range(draws)])


def paired_delta(sums_c, sums_pl, counts):
    """Delta = rho_c - mean_j rho_pl,j; replicate b pairs rho*_c,b with rho*_pl,(b mod J),b (same date draw)."""
    rho_c = float(mg._rho(*sums_c.sum(axis=1)))
    rho_pl = np.array([float(mg._rho(*s.sum(axis=1))) for s in sums_pl])
    boot_c = mg._rho(*(counts @ sums_c.T).T)
    j_b = np.arange(len(counts)) % len(sums_pl)
    boot_pl = np.empty(len(counts))
    for j, s in enumerate(sums_pl):
        sel = j_b == j
        boot_pl[sel] = mg._rho(*(counts[sel] @ s.T).T)
    delta_b = boot_c - boot_pl
    fin = np.isfinite(delta_b)
    q = (lambda v: np.quantile(v[np.isfinite(v)], [0.025, 0.975]).tolist() if np.isfinite(v).any() else [None, None])
    return {"delta": rho_c - float(rho_pl.mean()), "ci95": q(delta_b),
            "p_one_sided": float((1 + np.sum(delta_b[fin] <= 0)) / (fin.sum() + 1)),
            "rho_c": rho_c, "rho_c_ci95": q(boot_c), "rho_pl_mean": float(rho_pl.mean()),
            "rho_pl_ci95": q(boot_pl), "rho_pl_by_seed": rho_pl.tolist(), "valid_draws": int(fin.sum())}


def bh_adjust(pvals, q=BH_Q):
    """Benjamini-Hochberg step-up: adjusted q-values and the reject flags at level ``q``."""
    p = np.asarray(pvals, float)
    k = len(p)
    order = np.argsort(p, kind="mergesort")
    adj = np.empty(k)
    running = 1.0
    for rank in range(k, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * k / rank)
        adj[i] = running
    return adj, adj <= q


# ----------------------------------------------------------------------------- one candidate

def p0_candidate(cid, kind, sign, values_fit, fit_t, score_t, geo_fit, counts, score_dates, donors=None):
    """Signal, tilt, the 20 disagreement placebos and the paired P0 for one candidate (rule sections 4-5)."""
    from weather.calibration import market_blend as mb

    covered = np.isfinite(values_fit)
    s = band_signal(kind, sign, np.where(covered, values_fit, np.nan), fit_t, geo_fit)
    c_fit, sd_s = tilt(fit_t, geo_fit, s, covered)
    cov_float = np.repeat(covered.astype(float), fit_t.n)
    placebos, donor_ok, metas = [], np.ones(len(fit_t.snaps), bool), []
    donors = donors or {seed: donor_positions(fit_t, seed) for seed in PLACEBO_SEEDS}
    for seed in PLACEBO_SEEDS:
        pl, meta = disagreement_placebo(fit_t, c_fit, seed, donors[seed])
        dcov = cov_float[donors[seed][0]]
        donor_ok &= np.bincount(fit_t.band_snap, weights=dcov, minlength=len(fit_t.snaps)) == fit_t.n
        placebos.append(pl)
        metas.append(meta)
    pop_fit = covered & donor_ok
    pop = mb.restrict_snap(fit_t, score_t, pop_fit)
    band = pop[score_t.band_snap]
    m, y = score_t.p_market, score_t.y
    e = y - m
    didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    c = mb.restrict(fit_t, score_t, c_fit)
    pls = [mb.restrict(fit_t, score_t, p) for p in placebos]
    nd = len(score_dates)
    sums_c = date_sums((c - m)[band], e[band], didx[band], nd)
    sums_pl = [date_sums((p - m)[band], e[band], didx[band], nd) for p in pls]
    n_dates = int((sums_c[0] > 0).sum())
    n_snaps = int(pop.sum())
    res = {"candidate": cid, "type": kind, "sign": sign, "sd_s": sd_s,
           "coverage": {"fit_covered_snapshots": int(covered.sum()), "fit_snapshots": int(len(covered)),
                        "population_snapshots": n_snaps, "population_dates": n_dates,
                        "score_snapshots": int(len(score_t.snaps))},
           "placebo_meta": metas}
    if n_dates < MIN_DATES or n_snaps < MIN_SNAPS:
        res.update(testable=False, p0={"p_one_sided": 1.0, "delta": None, "ci95": [None, None]})
        return res, None
    res["testable"] = True
    res["p0"] = paired_delta(sums_c, sums_pl, counts)
    a_fit = c_fit[donors[PLACEBO_SEEDS[0]][0]]  # the parent's c-deranged placebo (placebo_vector of c)
    sums_a = date_sums((mb.restrict(fit_t, score_t, a_fit) - m)[band], e[band], didx[band], nd)
    rho_a = float(mg._rho(*sums_a.sum(axis=1)))
    boot_a = mg._rho(*(counts @ sums_a.T).T)
    ci_a = np.quantile(boot_a[np.isfinite(boot_a)], [0.025, 0.975]).tolist()
    res["diagnostic_c_deranged_placebo"] = {"rho": rho_a, "ci95": ci_a, "covers_0": bool(ci_a[0] <= 0 <= ci_a[1])}
    res["by_block"] = _subgroups(hour_blocks(score_t.local_hour), pop, score_t, c, pls, e, didx, nd, counts)
    res["by_market"] = _subgroups(score_t.markets, pop, score_t, c, pls, e, didx, nd, counts)
    snap_didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())
    n_snap_date = np.bincount(snap_didx[pop], minlength=nd)
    rows = [{"candidate": cid, "date": score_dates[i], "n_entries": int(sums_c[0, i]),
             "n_snapshots": int(n_snap_date[i]),
             "sums_c": sums_c[:, i].tolist(), "sums_pl": [s[:, i].tolist() for s in sums_pl]}
            for i in range(nd)]
    res["_rows"] = rows
    return res, {"c_fit": c_fit, "pl0_fit": placebos[0], "covered": covered}


REPORT_BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))


def hour_blocks(hours):
    out = np.empty(len(hours), dtype=object)
    for name, lo, hi in REPORT_BLOCKS:
        out[(hours >= lo) & (hours <= hi)] = name
    return out.astype(str)


def _subgroups(labels, pop, score_t, c, pls, e, didx, nd, counts):
    out = {}
    m = score_t.p_market
    for lab in sorted(set(labels)):
        band = (pop & (labels == lab))[score_t.band_snap]
        if band.sum() < 50:
            continue
        sc_ = date_sums((c - m)[band], e[band], didx[band], nd)
        sp = [date_sums((p - m)[band], e[band], didx[band], nd) for p in pls]
        r = paired_delta(sc_, sp, counts)
        out[str(lab)] = {k: r[k] for k in ("delta", "ci95", "rho_c", "rho_pl_mean")}
    return out


# ----------------------------------------------------------------------------- the run

def run(*, layout, out_dir, replay_root=DEFAULT_REPLAY, allow_dirty=False):
    """Controls, features, P0 for all 17 candidates, BH, the w gate for survivors; writes the receipt and rows."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = Path(out_dir)
    if (out / "mr_sweep.json").exists():
        raise SweepError(f"refusing to overwrite {out / 'mr_sweep.json'}")
    sums_path = Path(replay_root) / "SHA256SUMS"
    if not sums_path.exists():
        raise SweepError(f"replay SHA256SUMS missing under {replay_root}")
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    if set(fit_t.markets) & {"toronto"}:
        raise SweepError("the sweep population is the US markets; toronto is not in the rule")
    controls = mg.market_controls(fit_t, score_t)

    feats, n_records, malformed = extract_features(replay_root, set(fit_t.snaps.row_key))
    out.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(out / "features.parquet", index=False)
    values = candidate_values(fit_t.snaps, feats)
    geo = band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = boot_counts(len(score_dates))
    donors = {seed: donor_positions(fit_t, seed) for seed in PLACEBO_SEEDS}

    results, kept, rows = {}, {}, []
    for cid, kind, sign, _, _ in CANDIDATES:
        res, vecs = p0_candidate(cid, kind, sign, values[cid], fit_t, score_t, geo, counts, score_dates, donors)
        rows += res.pop("_rows", [])
        results[cid] = res
        if vecs is not None:
            kept[cid] = vecs
    ids = [c[0] for c in CANDIDATES]
    adj, reject = bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    for cid, q, rj in zip(ids, adj, reject):
        r = results[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"] = float(q)
        r["bh_reject"] = bool(rj)
        r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["verdict"] = "SURVIVE" if r["survive"] else ("UNTESTABLE" if not r["testable"] else "KILL")

    for cid in [c for c in ids if results[c]["survive"]]:
        vec = kept[cid]
        controls[f"w0_identity_{cid}"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
        if controls[f"w0_identity_{cid}"]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, "00-23", fit_t, score_t, vec["c_fit"], vec["covered"], p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}
        for row in rows:
            if row["candidate"] == cid:
                row["w"] = g["w"]["w_by_date"].get(row["date"])
                row["paired_brier"] = g["per_date"].get(row["date"])

    lines = [line_for(results[c]) for c in ids]
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "development (dev window, provisional)",
               "module_sha256": {"mr_sweep": ls.sha256_file(__file__), "mr_gate": ls.sha256_file(mg.__file__),
                                 "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "replay_sha256sums_sha256": ls.sha256_file(sums_path),
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet"),
               "replay_records_read": n_records, "replay_malformed_lines": malformed,
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "n_market_days": len(score_t.keys),
                              "markets": sorted(set(score_t.markets))},
               "constants": {"draws": DRAWS, "seed": SEED, "placebo_seeds": list(PLACEBO_SEEDS), "bh_q": BH_Q,
                             "sigma2_floor": SIGMA2_FLOOR, "min_dates": MIN_DATES, "min_snapshots": MIN_SNAPS,
                             "eps": mb.EPS, "nbm_v2_status_ok": "available"},
               "controls": controls, "results": results, "lines": lines}
    (out / "mr_sweep_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                     for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "mr_sweep_rows.jsonl")
    (out / "mr_sweep.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                       encoding="utf-8")
    return receipt


def line_for(r):
    p0 = r["p0"]
    if not r["testable"]:
        return f"UNTESTABLE: {r['candidate']} coverage {r['coverage']['population_snapshots']} snapshots / " \
               f"{r['coverage']['population_dates']} dates; q {r['bh_q']:.3f}"
    ci = p0["ci95"]
    tail = f"; w gate {r['w_gate']['verdict']} (mean w {r['w_gate']['w']['summary']['mean']:.3f})" if "w_gate" in r else ""
    return (f"{r['verdict']}: {r['candidate']} delta {p0['delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]; "
            f"p {p0['p_one_sided']:.4f}; BH q {r['bh_q']:.3f}; rho_c {p0['rho_c']:+.4f}, "
            f"rho_pl {p0['rho_pl_mean']:+.4f}{tail}")
