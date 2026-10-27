r"""Lane L3, R-Z: HRRR 3x3 spatial spread of the forecast day-max as day-specific width. Research only.

Rule ``C:/t/l3/rz/rule_rz.md`` (sha pinned below), HISTORY ONLY: P0 (Spearman screen of the spread anomaly
against the arm's absolute error) and gate 1 (strictly nested LOYO 2021-25 Aug-Sep, R-PD's bucket-Brier harness)
for two blocks: 07-12 on the L6 stack, 00-06 on the MG-1 analogue. The lever widens or narrows
sigma = max(s, 1) by exp(gamma_h (z - zbar_{m,h})); centre, floor and band mapping are unchanged.

Inputs are L6's observation history, L9's NBM corpus and lane L13's HRRR 3x3 blocks; nothing dated after
2026-09-29 is read and no dev, capture, price, panel or settlement row is opened. Imports L3/L6/L9 research
helpers lazily; never imported by serving; outputs must sit outside the repository and are written once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RULE_RZ_SHA256 = "36fa772621a2d916058d7ec6c1b4beb44eff8efba340e76a050263fdb9ec1a41"
OBS_SHA256 = "37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2"
NBM_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
BLOCKS = {
    "07-12": {"hours": (7, 8, 9, 10, 11, 12), "arm": "l6_stack",
              "manifest": "fef6c307a411e6373af05830b55c4dff8cb23d08f46e18f07949821f08fe88e6",
              "selections": "31bd3d3a7c6456df657e8f99b763a06a80bc41772881f67dc7eeaf5dee1f4e67"},
    "00-06": {"hours": (0, 1, 2, 3, 4, 5, 6), "arm": "mg1_analogue",
              "manifest": "f1d56fb66502d69e0101843ffcfb2ae12a570c787573d45ddb35bec31f27b5da",
              "selections": "9a6909c63bbcd664199e458ac41669e921803b2eeb8a689f10f930e4da7e5bb7"},
}
EXCLUDED_STATIONS = ("CYYZ",)
STACK_MIN_N = 200
LOYO_YEARS = (2021, 2022, 2023, 2024, 2025)
LOYO_MONTHS = (8, 9)
LOYO_SEED = 20261026
SUPPORT = 80
SD_FLOOR_F = 0.1
GAMMA_GRID = tuple(round(0.05 * i, 2) for i in range(21))
P0_RHO_MIN = 0.05
P0_FLIP_MAX = 1                    # closes at >= 2 opposite-sign years
COVERAGE_MIN = 0.90
LOGMULT_MAX = 0.02
REPRO_TOL = 1e-12
DATA_LAST = "2026-09-29"
HISTORY_LAST = "2025-12-31"
TMP_VAR = "TMP:2 m above ground"


class RZError(RuntimeError):
    pass


def _outside_repo(path):
    """Research output never lands in the repository (the same check as L2's ``require_output_outside_repo``)."""
    from weather.paths import REPO_ROOT

    resolved = Path(path).resolve()
    repo = Path(REPO_ROOT).resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError(f"output must be outside the repository: {resolved}")
    return resolved


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_rule(rule_path):
    got = _sha(rule_path)
    if got != RULE_RZ_SHA256:
        raise RZError(f"rule sha {got} != pinned {RULE_RZ_SHA256}")
    return got


def _pin(path, pinned, what):
    got = _sha(path)
    if got != pinned:
        raise RZError(f"{what} {path} sha {got} != pinned {pinned}")
    return got


def _write_once(path, payload):
    path = _outside_repo(Path(path))
    if path.exists():
        raise RZError(f"refusing to overwrite {path} (one run per gate)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------- HRRR 3x3 spread (L13's PIT cycle choice)

def k_to_f(k):
    return (k - 273.15) * 9.0 / 5.0 + 32.0


def spread_of_cells(cell_max_f):
    """z = ln(max(population sd of the 9 cell day-maxes, 0.1 F)) and the sd itself."""
    import numpy as np

    x = np.asarray(cell_max_f, float)
    sd = float(np.std(x, ddof=0))
    return float(np.log(max(sd, SD_FLOOR_F))), sd


def hrrr_spread(hrrr_root, manifest_pin, selections_pin):
    """DataFrame (station, local_date, hour, sd9, z) for history selections (<= 2025-12-31). A selection with no
    cycle, a truncated window, or any needed message or cell absent is absent (never imputed)."""
    import numpy as np
    import pandas as pd

    root = Path(hrrr_root)
    pins = {"manifest_sha256": _pin(root / "manifest.jsonl", manifest_pin, "HRRR manifest"),
            "selections_sha256": _pin(root / "selections.jsonl", selections_pin, "HRRR selections"),
            "stations_sha256": _sha(root / "stations.json")}
    stations = sorted(json.loads((root / "stations.json").read_text(encoding="utf-8")))
    sidx = {s: i for i, s in enumerate(stations)}
    msgs = {}
    with open(root / "manifest.jsonl", encoding="utf-8") as handle:
        for line in handle:
            if TMP_VAR not in line:
                continue
            r = json.loads(line)
            if r.get("status") != "ok" or r.get("var") != TMP_VAR:
                continue
            arr = np.full((len(stations), 9), np.nan)
            for st, p in (r.get("points") or {}).items():
                block = p.get("block3x3") if isinstance(p, dict) else None
                if st in sidx and block is not None and len(block) == 9:
                    arr[sidx[st]] = [np.nan if v is None else float(v) for v in block]
            msgs[(r["cycle_utc"], int(r["fh"]))] = arr
    rows = []
    stats = {"selections": 0, "after_history": 0, "excluded_station": 0, "truncated": 0, "no_cycle": 0,
             "absent": 0, "ok": 0}
    with open(root / "selections.jsonl", encoding="utf-8") as handle:
        for line in handle:
            s = json.loads(line)
            stats["selections"] += 1
            if s["local_date"] > DATA_LAST:
                raise RZError(f"HRRR selection after {DATA_LAST}: {s['local_date']}")
            if s["local_date"] > HISTORY_LAST:
                stats["after_history"] += 1
                continue
            if s["station"] in EXCLUDED_STATIONS:
                stats["excluded_station"] += 1
                continue
            if s.get("window_truncated_at_f18"):
                stats["truncated"] += 1
                continue
            if not s.get("cycle_utc") or not s.get("fhs"):
                stats["no_cycle"] += 1
                continue
            got = [msgs.get((s["cycle_utc"], int(fh))) for fh in s["fhs"]]
            if any(g is None for g in got):
                stats["absent"] += 1
                continue
            cells = np.stack([g[sidx[s["station"]]] for g in got])
            if not np.isfinite(cells).all():
                stats["absent"] += 1
                continue
            z, sd = spread_of_cells(k_to_f(cells.max(0)))
            stats["ok"] += 1
            rows.append((s["station"], s["local_date"], int(s["hour_local"]), sd, z))
    frame = pd.DataFrame(rows, columns=["station", "local_date", "hour", "sd9", "z"])
    if frame.duplicated(["station", "local_date", "hour"]).any():
        raise RZError("duplicate HRRR selection (station, local_date, hour)")
    return frame, stats, pins


# ---------------------------------------------------------------- NBM and history (R-PD's helpers, hours as a block)

def load_nbm_with_sd(paths):
    from collections import defaultdict
    from datetime import datetime

    table, seen = defaultdict(list), {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r["available"] or r["mean"] is None:
                continue
            if r["target_date"] > DATA_LAST:
                raise RZError(f"NBM corpus row after {DATA_LAST}: {r['target_date']}")
            key = (r["market_id"], r["target_date"], r["cycle"])
            lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
            value = (float(r["mean"]), None if r.get("sd") is None else float(r["sd"]))
            if key in seen:
                if seen[key] != (lm, value):
                    raise RZError(f"conflicting duplicate NBM corpus row {key}")
                continue
            seen[key] = (lm, value)
            table[(r["market_id"], r["target_date"])].append((r["cycle"], lm, value))
    return table


def nbm_at(table, market, day, hour, tz):
    from weather.calibration import ols_floor_ladder as lad

    value, cycle = lad.nbm_at_cutoff(table, market, day, hour, tz)
    if value is None:
        return float("nan"), float("nan"), None
    mean, sd = value
    return mean, (float("nan") if sd is None else sd), cycle


def history_queries(dates, tz, hours):
    import pandas as pd

    q = pd.DataFrame([(d, h) for d in dates for h in hours], columns=["local_date", "hour"])
    loc = pd.to_datetime(q.local_date) + pd.to_timedelta(q.hour, unit="h") + pd.Timedelta(minutes=30)
    q["t_utc"] = loc.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return q.dropna(subset=["t_utc"]).reset_index(drop=True)


def build_history(research_root, nbm_table, hours):
    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as l6

    obs, sel, prov = l6.load(research_root)
    frames = []
    for code, icao in enumerate(l6.stations(sel)):
        m = sel[icao]
        g, dmax = l6.market_series(obs, icao, m["timezone"])
        dates = [d for d in dmax.index if d <= HISTORY_LAST and int(d[5:7]) >= 8]
        q = history_queries(dates, m["timezone"], hours)
        f = l6.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["station"], f["local_date"], f["hour"] = icao, q.local_date, q.hour
        f["market"] = m["market"]
        f["dmax"] = q.local_date.map(dmax).to_numpy(float)
        f["year"] = q.local_date.str[:4].astype(int)
        f["month"] = q.local_date.str[5:7].astype(int)
        got = [nbm_at(nbm_table, m["market"], d, int(h), m["timezone"]) for d, h in zip(q.local_date, q.hour)]
        f["v"] = [x[0] for x in got]
        f["s"] = [x[1] for x in got]
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out = out[np.isfinite(out.r) & np.isfinite(out.t) & np.isfinite(out.dmax)].reset_index(drop=True)
    out = out[out.month.isin(LOYO_MONTHS) & out.year.isin(LOYO_YEARS)].reset_index(drop=True)
    out = out[~out.station.isin(EXCLUDED_STATIONS)].reset_index(drop=True)
    out["y"] = out.dmax - out.r
    return out, prov


def stack_fit(z, x, hours, block_hours):
    import numpy as np

    coef = {}
    for h in block_hours:
        sel = (hours == h) & np.isfinite(z) & np.isfinite(x)
        if sel.sum() < STACK_MIN_N:
            continue
        zz, xx = z[sel], x[sel]
        xc = xx - xx.mean()
        b = float((xc * (zz - zz.mean())).sum() / max((xc ** 2).sum(), 1e-9))
        b = min(max(b, 0.0), 1.0)
        coef[int(h)] = (float((zz - b * xx).mean()), b, int(sel.sum()))
    return coef


def stack_mu(v, n, hours, coef):
    import numpy as np

    v, n = np.asarray(v, float), np.asarray(n, float)
    mu = v.copy()
    for h, (a, b, _) in coef.items():
        sel = (hours == h) & np.isfinite(n) & np.isfinite(v)
        mu[sel] = v[sel] + a + b * (n[sel] - v[sel])
    return mu


def bucket_brier(mu, sigma, floor_r, label):
    import numpy as np
    from scipy.special import ndtr

    mu, sigma = np.asarray(mu, float), np.asarray(sigma, float)
    B = np.floor(np.asarray(floor_r, float) + 0.5)
    y = np.asarray(label, float)
    k = B[:, None] + np.arange(SUPPORT)[None, :]
    lower = ndtr((k - 0.5 - mu[:, None]) / sigma[:, None])
    upper = ndtr((k + 0.5 - mu[:, None]) / sigma[:, None])
    upper[:, -1] = 1.0
    mass = np.clip(upper - lower, 0.0, None)
    total = mass.sum(1)
    dead = ~(total > 0)
    mass[dead] = 0.0
    mass[dead, 0] = 1.0
    p = mass / np.where(dead, 1.0, total)[:, None]
    onehot = (k == y[:, None]).astype(float)
    outside = ~onehot.any(1)
    return ((p - onehot) ** 2).sum(1) + outside.astype(float)


def _cell_ratio(dates, markets, num, den, masks, seed):
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc

    keys = sorted(set(zip(dates, markets)))
    index = {k: i for i, k in enumerate(keys)}
    cell = np.array([index[k] for k in zip(dates, markets)], int)
    w = l3._date_weights([k[0] for k in keys], sc.DRAWS, seed)
    out = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        cnt = np.bincount(cell[mask], minlength=len(keys))
        present = np.flatnonzero(cnt)
        a = np.bincount(cell[mask], weights=num[mask], minlength=len(keys))[present] / cnt[present]
        b = np.bincount(cell[mask], weights=den[mask], minlength=len(keys))[present] / cnt[present]
        out[name] = dict(sc.ratio_interval(w[:, present], a, b), n_rows=int(mask.sum()), n_cells=int(len(present)),
                         n_dates=int(len({keys[i][0] for i in present})), brier_base=float(b.mean()),
                         abs_delta=float(a.mean()))
    return out


# ---------------------------------------------------------------- the arm, nested (shared by P0 and gate 1)

def sigma_rz(s, z, zbar, gamma):
    """sigma = max(s, 1) * exp(gamma (z - zbar)); gamma = 0 returns max(s, 1) exactly."""
    import numpy as np

    base = np.maximum(np.asarray(s, float), 1.0)
    g = np.asarray(gamma, float)
    return base * np.exp(g * (np.asarray(z, float) - np.asarray(zbar, float)))


def prepare(block, *, research_root, nbm_corpora, hrrr_root):
    """History rows of ``block`` with z joined; the out-of-year arm centre and, per held-out year, the inner
    (training-year) centre. Returns (hist, mu_out, mu_in_by_year, info)."""
    import numpy as np

    from weather.calibration import upstream_obs_screen as l6

    spec = BLOCKS[block]
    hours_b = spec["hours"]
    obs_sha = _pin(Path(research_root) / "upstream_obs" / "obs.parquet", OBS_SHA256, "L6 obs")
    corp = {str(p): _pin(p, NBM_SHA256, "NBM corpus") for p in nbm_corpora}
    nbm = load_nbm_with_sd(nbm_corpora)
    hist, prov = build_history(research_root, nbm, hours_b)
    zf, zstats, zpins = hrrr_spread(hrrr_root, spec["manifest"], spec["selections"])
    hist = hist.merge(zf, on=["station", "local_date", "hour"], how="left", validate="many_to_one")
    year = hist.year.to_numpy(int)
    years = sorted(set(int(y) for y in year))
    if tuple(years) != LOYO_YEARS:
        raise RZError(f"{block}: history years {years} != {LOYO_YEARS}")
    R, v, s = hist.r.to_numpy(float), hist.v.to_numpy(float), hist.s.to_numpy(float)
    dmax, hours = hist.dmax.to_numpy(float), hist.hour.to_numpy(int)
    has_vs = np.isfinite(v) & np.isfinite(s)
    mu_out = np.full(len(hist), np.nan)
    mu_in = {}
    coefs = {}
    fits = 0
    if spec["arm"] == "mg1_analogue":
        mu_out = v.copy()
        for Y in years:
            mu_in[Y] = v.copy()
    else:
        cols = list(l6.OWN)
        X, target = hist[cols].to_numpy(float), hist.y.to_numpy(float)
        fitted = {}

        def model_without(excluded):
            key = tuple(sorted(excluded))
            if key not in fitted:
                tr = ~np.isin(year, key)
                fitted[key] = l6.make_model(cols).fit(X[tr], target[tr])
            return fitted[key]

        for Y in years:
            te = year == Y
            n_outer = R[te] + model_without({Y}).predict(X[te])
            n_inner = np.full(len(hist), np.nan)
            for Xy in years:
                if Xy == Y:
                    continue
                m = year == Xy
                n_inner[m] = R[m] + model_without({Xy, Y}).predict(X[m])
            tr = ~te & has_vs
            coef = stack_fit(np.where(tr, dmax - v, np.nan), np.where(tr, n_inner - v, np.nan), hours, hours_b)
            coefs[str(Y)] = {f"h{h:02d}": list(c) for h, c in coef.items()}
            mu_out[te] = stack_mu(v[te], n_outer, hours[te], coef)
            mu_in[Y] = np.where(~te, stack_mu(v, n_inner, hours, coef), np.nan)
        fits = len(fitted)
    has_z = np.isfinite(hist.z.to_numpy(float))
    coverage = float((has_vs & has_z).sum() / max(has_vs.sum(), 1))
    info = {"block": block, "arm": spec["arm"], "hours": list(hours_b), "history_rows": int(len(hist)),
            "rows_with_v_s": int(has_vs.sum()), "rows_with_v_s_z": int((has_vs & has_z).sum()),
            "z_coverage": coverage, "hrrr_stats": zstats, "stack_coef_by_held_out_year": coefs, "hgb_fits": fits,
            "inputs": dict(prov, obs_pinned=obs_sha, corpora=corp, hrrr_root=str(hrrr_root), **zpins,
                           hgb=l6.HGB_PARAMS if spec["arm"] == "l6_stack" else None,
                           l6_module_sha256=_sha(l6.__file__))}
    return hist, mu_out, mu_in, info


def zbar_table(hist, rows, train):
    """{(market, hour): mean z} over ``rows & train``."""
    sub = hist[rows & train]
    return sub.groupby(["market", "hour"]).z.mean().to_dict()


def zbar_for(hist, table):
    import numpy as np

    return np.array([table.get((m, h), np.nan) for m, h in zip(hist.market, hist.hour)], float)


# ---------------------------------------------------------------- P0

def _spearman(a, b):
    from scipy.stats import spearmanr

    if len(a) < 3:
        return None
    rho = spearmanr(a, b).statistic
    return None if rho != rho else float(rho)


def p0_block(block, **kw):
    import numpy as np

    hist, mu_out, _, info = prepare(block, **kw)
    year = hist.year.to_numpy(int)
    v, s, z = hist.v.to_numpy(float), hist.s.to_numpy(float), hist.z.to_numpy(float)
    rows = np.isfinite(v) & np.isfinite(s) & np.isfinite(z) & np.isfinite(mu_out)
    za = np.full(len(hist), np.nan)
    for Y in LOYO_YEARS:
        te = year == Y
        zb = zbar_for(hist, zbar_table(hist, rows, ~te))
        za[te] = z[te] - zb[te]
    rows &= np.isfinite(za)
    e = np.abs(hist.dmax.to_numpy(float) - mu_out)
    hours, markets = hist.hour.to_numpy(int), hist.market.astype(str).to_numpy()

    def rho(mask):
        m = rows & mask
        return {"rho": _spearman(za[m], e[m]), "n": int(m.sum())}

    pooled = rho(np.ones(len(hist), bool))
    per_year = {str(Y): rho(year == Y) for Y in LOYO_YEARS}
    per_hour = {f"h{h:02d}": rho(hours == h) for h in BLOCKS[block]["hours"]}
    per_market = {m: rho(markets == m) for m in sorted(set(markets))}
    sign = 1.0 if (pooled["rho"] or 0.0) >= 0 else -1.0
    flips = [y for y, r in per_year.items() if r["rho"] is not None and r["rho"] * sign < 0]
    stopped = info["z_coverage"] < COVERAGE_MIN
    closed = bool(pooled["rho"] is None or pooled["rho"] < P0_RHO_MIN or len(flips) > P0_FLIP_MAX)
    return {"block": block, "pooled": pooled, "per_year": per_year, "per_hour": per_hour,
            "per_market_reported_only": per_market, "opposite_sign_years": flips,
            "precondition_coverage_ok": not stopped, "closed": bool(closed and not stopped),
            "stopped": bool(stopped), "survives": bool(not closed and not stopped),
            "mean_abs_error": float(e[rows].mean()) if rows.any() else None, "info": info}


def p0(*, research_root, nbm_corpora, hrrr_0712, hrrr_0006, rule, out_path):
    check_rule(rule)
    roots = {"07-12": hrrr_0712, "00-06": hrrr_0006}
    blocks = {b: p0_block(b, research_root=research_root, nbm_corpora=nbm_corpora, hrrr_root=roots[b])
              for b in BLOCKS}
    payload = {"label": "R-Z P0 (history only, LOYO 2021-25 Aug-Sep): Spearman of the HRRR 3x3 spread anomaly "
                        "against |dmax - mu_arm|; no Brier read; development evidence, no edge claim",
               "rule_sha256": RULE_RZ_SHA256, "thresholds": {"rho_min": P0_RHO_MIN, "closes_at_opposite_years": 2,
                                                            "coverage_min": COVERAGE_MIN},
               "blocks": blocks, "surviving_blocks": [b for b, r in blocks.items() if r["survives"]],
               "module_sha256": _sha(__file__)}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- gate 1

def gate1_block(block, **kw):
    import numpy as np

    hist, mu_out, mu_in, info = prepare(block, **kw)
    year = hist.year.to_numpy(int)
    R, v, s, z = (hist[c].to_numpy(float) for c in ("r", "v", "s", "z"))
    dmax, hours = hist.dmax.to_numpy(float), hist.hour.to_numpy(int)
    rows = np.isfinite(v) & np.isfinite(s) & np.isfinite(z) & np.isfinite(mu_out)
    gamma_row = np.zeros(len(hist))
    zbar_row = np.full(len(hist), np.nan)
    gammas = {}
    for Y in LOYO_YEARS:
        te = year == Y
        tr_all = rows & ~te & np.isfinite(mu_in[Y])
        zb = zbar_for(hist, zbar_table(hist, rows, ~te))
        zbar_row[te] = zb[te]
        gammas[str(Y)] = {}
        for h in BLOCKS[block]["hours"]:
            tr = tr_all & (hours == h) & np.isfinite(zb)
            best, best_b = 0.0, None
            for g in GAMMA_GRID:
                b = float(bucket_brier(mu_in[Y][tr], sigma_rz(s[tr], z[tr], zb[tr], g), R[tr], dmax[tr]).mean())
                if best_b is None or b < best_b:
                    best, best_b = g, b
            gammas[str(Y)][f"h{h:02d}"] = {"gamma": best, "inner_brier": best_b, "n_train": int(tr.sum())}
            gamma_row[te & (hours == h)] = best
    rows &= np.isfinite(zbar_row)
    sig_base = np.maximum(s, 1.0)
    sig_arm = sigma_rz(s, z, zbar_row, gamma_row)
    b_base = np.full(len(hist), np.nan)
    b_arm = np.full(len(hist), np.nan)
    b_zero = np.full(len(hist), np.nan)
    b_base[rows] = bucket_brier(mu_out[rows], sig_base[rows], R[rows], dmax[rows])
    b_arm[rows] = bucket_brier(mu_out[rows], sig_arm[rows], R[rows], dmax[rows])
    b_zero[rows] = bucket_brier(mu_out[rows], sigma_rz(s[rows], z[rows], zbar_row[rows], 0.0), R[rows], dmax[rows])
    logmult = gamma_row * (z - zbar_row)
    controls = {
        "gamma0_reproduces_base_max_abs": float(np.abs(b_zero[rows] - b_base[rows]).max()),
        "heldout_mean_log_multiplier": float(logmult[rows].mean()),
        "centre_and_floor_unchanged": True,   # arm and base share mu_out and R by construction (same arrays)
    }
    checks = {"gamma0": controls["gamma0_reproduces_base_max_abs"] <= REPRO_TOL,
              "log_multiplier": abs(controls["heldout_mean_log_multiplier"]) <= LOGMULT_MAX,
              "centre_floor": True}
    dates = hist.local_date.astype(str).to_numpy()
    markets = hist.market.astype(str).to_numpy()
    groups = {block: rows}
    groups.update({f"h{h:02d}": rows & (hours == h) for h in BLOCKS[block]["hours"]})
    pooled = _cell_ratio(dates, markets, b_arm - b_base, b_base, groups, LOYO_SEED)
    per_market = {m: _cell_ratio(dates, markets, b_arm - b_base, b_base, {block: rows & (markets == m)},
                                 LOYO_SEED).get(block) for m in sorted(set(markets))}
    per_year = {str(Y): _cell_ratio(dates, markets, b_arm - b_base, b_base, {block: rows & (year == Y)},
                                    LOYO_SEED).get(block) for Y in LOYO_YEARS}
    head = pooled[block]
    hour_ups = {f"h{h:02d}": (pooled.get(f"h{h:02d}") or {}).get("ci95", [None, None])[1]
                for h in BLOCKS[block]["hours"]}
    hours_not_below = [h for h, up in hour_ups.items() if up is None or not up < 0]
    upper_ok = bool(head["ci95"][1] is not None and head["ci95"][1] < 0)
    harm_markets = [m for m, r in per_market.items() if r and r["ci95"][0] is not None and r["ci95"][0] > 0]
    passed = bool(upper_ok and not hours_not_below and all(checks.values()))
    return {"block": block, "passed": passed,
            "reading": {"pooled_upper_below_0": upper_ok, "hours_with_upper_not_below_0": hours_not_below,
                        "controls_ok": checks, "markets_with_lower_above_0_reported_only": harm_markets},
            "controls": controls, "dB": pooled, "per_market_reported_only": per_market, "per_year": per_year,
            "gamma_by_held_out_year": gammas, "scored_rows": int(rows.sum()),
            "share_gamma_zero": float((gamma_row[rows] == 0).mean()), "info": info}


def gate1(*, research_root, nbm_corpora, hrrr_0712, hrrr_0006, rule, p0_path, out_path):
    check_rule(rule)
    p0_payload = json.loads(Path(p0_path).read_text(encoding="utf-8"))
    if p0_payload.get("rule_sha256") != RULE_RZ_SHA256:
        raise RZError("P0 output was not produced under this rule")
    surviving = list(p0_payload.get("surviving_blocks") or [])
    if not surviving:
        raise RZError("no block survived P0; the rule stops before gate 1")
    roots = {"07-12": hrrr_0712, "00-06": hrrr_0006}
    blocks = {b: gate1_block(b, research_root=research_root, nbm_corpora=nbm_corpora, hrrr_root=roots[b])
              for b in surviving}
    payload = {"label": "R-Z gate 1 (history only): strictly nested LOYO 2021-25 Aug-Sep, HRRR 3x3 spread width "
                        "vs the same arm with gamma = 0 (integer-F bucket Brier); development evidence, no edge claim",
               "rule_sha256": RULE_RZ_SHA256, "p0_sha256": _sha(p0_path), "blocks": blocks,
               "passed_blocks": [b for b, r in blocks.items() if r["passed"]],
               "bootstrap": {"draws": 2000, "seed": LOYO_SEED, "clustering": "date"}, "support_buckets": SUPPORT,
               "gamma_grid": list(GAMMA_GRID), "module_sha256": _sha(__file__)}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.rz_hrrr_spread",
                                     description="Lane L3 R-Z: HRRR 3x3 spread as width (history only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("p0", "gate1"):
        p = sub.add_parser(name)
        p.add_argument("--research-root", required=True)
        p.add_argument("--nbm-corpus", action="append", required=True)
        p.add_argument("--hrrr-0712", required=True)
        p.add_argument("--hrrr-0006", required=True)
        p.add_argument("--rule", required=True)
        p.add_argument("--out", required=True)
        if name == "gate1":
            p.add_argument("--p0", required=True)
    a = parser.parse_args(argv)
    common = dict(research_root=a.research_root, nbm_corpora=a.nbm_corpus, hrrr_0712=a.hrrr_0712,
                  hrrr_0006=a.hrrr_0006, rule=a.rule, out_path=a.out)
    if a.cmd == "p0":
        out = p0(**common)
        summary = {b: {k: r[k] for k in ("pooled", "opposite_sign_years", "closed", "stopped", "survives")}
                   for b, r in out["blocks"].items()}
    else:
        out = gate1(p0_path=a.p0, **common)
        summary = {b: {"passed": r["passed"], "dB": r["dB"][b], "reading": r["reading"]}
                   for b, r in out["blocks"].items()}
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
