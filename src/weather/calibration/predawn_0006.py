r"""Lane L3: the pre-dawn 00-06 block (lever inventory row 2 / F8). Research only.

MG-2 serves MG-1 unchanged at local hours 00-06, and no lane has examined the block since EF section 10q.

Step 1 (``tags``, ``atlas``) is descriptive SELECTION EVIDENCE, not pre-registered:
- MG-1 against the capture-time market ``p_market_yes`` on dev layout dates 2026-07-31..09-29, local hours 00-06;
- broken down by hour, market, market x hour, bucket position relative to the winning band, and lane L2's R-H
  regime tags (``pooled_residual_model.rh_tags`` run at hours 00-06);
- "centre vs sharpness": the arm re-centred on the market-implied median band (L2's ``ri_recentre``). The
  re-centred excess is what remains after the centre is moved to the market's; the difference is the centre part;
- winner-bucket mass for arm and market.

P3d_N / P3d_N_fix emit only at cutoffs 07-20 (EF section 10ab scope), so MG-1 is the only arm at 00-06.

Reuses lane L2's R-H tagger and helpers (claude/rung0712-20261025) and L3's scorecard plumbing
(``r0_ols_floor_challenger``); both are imported lazily, so the module runs only in a stack holding them. Never
imported by serving; outputs must sit outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

LABEL = ("SELECTION EVIDENCE - descriptive dev-window atlas of the pre-dawn block (local hours 00-06), reference = "
         "captured capture-time market p_market_yes; not pre-registered; no edge claim")
HOURS = tuple(range(0, 7))
WINDOWS = (("00-06", 0, 6), ("00-05", 0, 5), ("06", 6, 6))
CONTEXT_WINDOWS = (("07-12", 7, 12),)
SMALL_N = 15


class PredawnError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tags(*, layout, replay_root, obs_parquet, out_path):
    """L2's R-H regime tags on snapshots at local hours 00-06 (captured obs and forecasts only)."""
    from weather.calibration import pooled_residual_model as l2

    return l2.rh_tags(layout=layout, replay_root=replay_root, obs_parquet=obs_parquet, out_path=Path(out_path),
                      hours=HOURS)


def atlas(*, layout, tags_path, out_path, start="2026-07-31", end="2026-09-29"):
    import numpy as np
    import pandas as pd

    from weather.calibration import pooled_residual_model as l2
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = l2.require_output_outside_repo(Path(out_path))
    if out_path.exists():
        raise PredawnError(f"refusing to overwrite {out_path}")
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)

    # positive control on the standard scored population (as R-H)
    ctl = sc.Table(lay, scored)
    p_c, _, _ = l3._vector(ctl, loss_atlas.mg1_frame(ctl))
    _, e = ctl.cells(ctl.brier(p_c) - ctl.brier(ctl.p_market), (ctl.local_hour >= 7) & (ctl.local_hour <= 12))
    control = float(e.mean())
    if round(control, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PredawnError(f"MG-1 positive control failed: {control:.5f}")
    del ctl

    dates = sorted(d for d in {str(x) for x in lay.dates} if start <= d <= end)
    table = sc.Table(lay, dates)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    p, cov, cov_reasons = l3._vector(table, loss_atlas.mg1_frame(table))
    p_mkt = table.p_market
    b, b_mkt = table.brier(p), table.brier(p_mkt)
    p_rc = l2.ri_recentre(p, p_mkt, table.offsets, table.n, table.impossible)
    b_rc = table.brier(p_rc)
    win_arm = np.add.reduceat(p * table.y, table.offsets)
    win_mkt = np.add.reduceat(p_mkt * table.y, table.offsets)
    has_winner = np.add.reduceat(table.y, table.offsets) > 0
    hours, markets = table.local_hour, table.markets

    tag_frame = pd.read_parquet(tags_path).set_index("row_key").reindex(table.snaps.row_key)
    tag_cols = {t: tag_frame[t].fillna("untagged").astype(str).to_numpy() for t in l2.RH_TAGS}

    def interval(idx, num):
        return sc.ratio_interval(date_w[:, idx], num, np.ones_like(num))

    def cell(mask, total):
        mask = mask & cov
        if not mask.any():
            return None
        idx, c = table.cells(b, mask)
        _, m = table.cells(b_mkt, mask)
        _, rc = table.cells(b_rc, mask)
        widx, wa = table.cells(win_arm, mask & has_winner)
        _, wm = table.cells(win_mkt, mask & has_winner)
        return {"n_market_days": int(len(idx)), "n_dates": int(len({table.keys[i][0] for i in idx})),
                "n_snapshots": int(mask.sum()), "small_n": bool(len(idx) < SMALL_N),
                "brier_arm": float(c.mean()), "brier_market": float(m.mean()),
                "excess": interval(idx, c - m),
                "excess_after_recentring": interval(idx, rc - m),
                "centre_part": interval(idx, c - rc),
                "share_of_window_excess": float((b - b_mkt)[mask].sum() / total) if total else None,
                "winner_mass_arm": float(wa.mean()) if len(wa) else None,
                "winner_mass_market": float(wm.mean()) if len(wm) else None,
                "winner_mass_arm_minus_market": (sc.ratio_interval(date_w[:, widx], wa - wm, np.ones_like(wa))
                                                 if len(wa) else None)}

    cls, _ = l2.position_classes(table)
    result = {"label": LABEL, "arm": "MG-1 (loss_atlas.mg1_frame)",
              "arms_not_available": {"P3d_N_fix": "emits only at cutoffs 07-20 (EF section 10ab scope)"},
              "controls": {"mg1_excess_07_12_scored": control},
              "population": {"dates": [dates[0], dates[-1], len(dates)], "n_market_days": len(table.keys),
                             "covered_snapshots": {w: int((cov & (hours >= lo) & (hours <= hi)).sum())
                                                   for w, lo, hi in WINDOWS + CONTEXT_WINDOWS},
                             "coverage_reasons": cov_reasons},
              "inputs": {"tags_sha256": _sha(tags_path), "layout_manifest_sha256": lay.manifest_sha256,
                         "scorecard_code_sha256": sc.code_sha256(), "module_sha256": _sha(__file__),
                         "l2_module_sha256": _sha(l2.__file__), "l3_module_sha256": _sha(l3.__file__),
                         "bootstrap": {"draws": sc.DRAWS, "seed": sc.SEED, "clustering": "date"}},
              "cells": [], "positions": [], "tag_crosstab": {}}
    for window, lo, hi in WINDOWS + CONTEXT_WINDOWS:
        in_w = cov & (hours >= lo) & (hours <= hi)
        total = float((b - b_mkt)[in_w].sum())

        def add(dim, value, mask):
            c = cell(mask, total)
            if c is not None:
                result["cells"].append({"window": window, "dim": dim, "value": value, **c})

        add("all", "all", in_w)
        for h in range(lo, hi + 1):
            add("hour", f"h{h:02d}", in_w & (hours == h))
        if (window, lo, hi) in CONTEXT_WINDOWS:
            continue
        for m in sorted(set(markets)):
            add("market", m, in_w & (markets == m))
            if window == "00-06":
                for h in range(lo, hi + 1):
                    add("market_x_hour", f"{m}|h{h:02d}", in_w & (markets == m) & (hours == h))
        for t, values in tag_cols.items():
            for v in sorted(set(values[in_w])):
                add(t, v, in_w & (values == v))
        diff_band = ((p - table.y) ** 2 - (p_mkt - table.y) ** 2) / np.repeat(table.n, table.n)
        idx, mden = table.cells(np.ones(len(table.snaps)), in_w)
        for k, name in enumerate(l2.POSITION_CLASSES):
            sel = cls == k
            per_snap = np.bincount(table.band_snap, weights=np.where(sel, diff_band, 0.0), minlength=len(table.snaps))
            mass_arm = np.bincount(table.band_snap, weights=np.where(sel, p, 0.0), minlength=len(table.snaps))
            mass_mkt = np.bincount(table.band_snap, weights=np.where(sel, p_mkt, 0.0), minlength=len(table.snaps))
            _, cnum = table.cells(per_snap, in_w)
            result["positions"].append({
                "window": window, "position": name,
                "excess_contribution": sc.ratio_interval(date_w[:, idx], cnum, mden),
                "mean_mass_arm": float(mass_arm[in_w].mean()), "mean_mass_market": float(mass_mkt[in_w].mean())})
        for t, values in tag_cols.items():
            result["tag_crosstab"][f"{window}|{t}"] = pd.Series(values[in_w]).value_counts().to_dict()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ============================================================================ step 2: rule R-PD (pre-registered)
#
# C:\t\l3\pd\rule_pd.md, sha256 pinned below. L6's own-obs stack at cutoffs 00-06. Every input is point in time;
# nothing dated after 2026-09-29 is read. Order: P1 and P2 (stop, not kill, on failure), gate 1 (LOYO), gate 2
# (dev vs MG-1, only if gate 1 passes), gate 3 (vs market, reported only).

RULE_PD_SHA256 = "e010d166dbd65ce268991e203be78b94d1c22fdbbdc4d6b3056ebe19e98e39e2"
STACK_MIN_N = 200
LOYO_YEARS = (2021, 2022, 2023, 2024, 2025)
LOYO_MONTHS = (8, 9)
LOYO_SEED = 20261026
SUPPORT = 80                      # integer-F buckets from half-up(R) upward; the last takes the upper tail
P1_EXACT_MIN, P1_DIFFER_MAX, P1_TOL = 0.99, 0.005, 1e-9
P2_TOL, P2_T_MIN, P2_OTHER_MIN = 0.05, 0.95, 0.90
P2_OTHER = ("r", "tend3", "prev_dmax")
STACK_GROUPS = (("00-06", 0, 6), ("00-05", 0, 5), ("06", 6, 6)) + tuple((f"h{h:02d}", h, h) for h in HOURS)
CANDIDATE_MODULE = Path(__file__).resolve().parents[3] / "tools" / "research" / "predawn_0006" / "stack_candidate.py"


def check_rule(rule_path):
    got = _sha(rule_path)
    if got != RULE_PD_SHA256:
        raise PredawnError(f"rule sha {got} != pinned {RULE_PD_SHA256}")
    return got


def _write_once(path, payload):
    from weather.calibration import pooled_residual_model as l2

    path = l2.require_output_outside_repo(Path(path))
    if path.exists():
        raise PredawnError(f"refusing to overwrite {path} (one run per gate)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return path


def _require_passed(path, what):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("passed") is not True:
        raise PredawnError(f"{what} ({path}) has not passed; the rule stops here")
    return _sha(path)


# ---------------------------------------------------------------- NBM (L9's corpus rows and cycle rule, unchanged)

def load_nbm_with_sd(paths):
    """{(market, date): [(cycle, last_modified_utc, (mean, sd)), ...]}: ``ols_floor_ladder.load_nbm``'s filter,
    carrying the same row's sd. Corpora are unioned; a conflicting duplicate (market, date, cycle) refuses."""
    from collections import defaultdict
    from datetime import datetime

    table, seen = defaultdict(list), {}
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r["available"] or r["mean"] is None:
                continue
            if r["target_date"] > "2026-09-29":
                raise PredawnError(f"NBM corpus row after 2026-09-29: {r['target_date']}")
            key = (r["market_id"], r["target_date"], r["cycle"])
            lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
            value = (float(r["mean"]), None if r.get("sd") is None else float(r["sd"]))
            if key in seen:
                if seen[key] != (lm, value):
                    raise PredawnError(f"conflicting duplicate NBM corpus row {key}")
                continue
            seen[key] = (lm, value)
            table[(r["market_id"], r["target_date"])].append((r["cycle"], lm, value))
    return table


def nbm_at(table, market, day, hour, tz):
    """(mean, sd, cycle) at local ``hour`` of ``day`` by L9's ``nbm_at_cutoff``; (nan, nan, None) when none."""
    from weather.calibration import ols_floor_ladder as lad

    value, cycle = lad.nbm_at_cutoff(table, market, day, hour, tz)
    if value is None:
        return float("nan"), float("nan"), None
    mean, sd = value
    return mean, (float("nan") if sd is None else sd), cycle


# ---------------------------------------------------------------- P1: NBM parity at dev 00-06

def p1(*, layout, nbm_corpora, rule, out_path):
    import numpy as np
    import pandas as pd

    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id

    check_rule(rule)
    cols = ["row_key", "market", "date", "local_hour", "captured_at_utc", "v2_mean", "v2_stddev", "v2_available_at",
            "v2_cycle_key"]
    s = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=cols)
    s = s[pd.to_numeric(s.local_hour, errors="coerce").isin(HOURS)].copy()
    if (s.date.astype(str) > "2026-09-29").any():
        raise PredawnError("layout snapshot after 2026-09-29")
    s["nbm"] = usable_v2_mean(s)
    table = load_nbm_with_sd(nbm_corpora)
    counts = {}
    total = {"snapshots": 0, "captured_unusable": 0, "corpus_none": 0, "both": 0, "exact": 0, "differs": 0}
    differs = []
    tz = {}
    for r in s.itertuples(index=False):
        if r.market not in tz:
            tz[r.market] = spec_for_id(r.market).timezone
        h = int(r.local_hour)
        mean, _, cycle = nbm_at(table, r.market, str(r.date)[:10], h, tz[r.market])
        c = counts.setdefault(f"h{h:02d}", dict.fromkeys(total, 0))
        for d in (c, total):
            d["snapshots"] += 1
        if not np.isfinite(r.nbm):
            kind = "captured_unusable"
        elif cycle is None:
            kind = "corpus_none"
        else:
            for d in (c, total):
                d["both"] += 1
            kind = "exact" if abs(mean - r.nbm) <= P1_TOL else "differs"
            if kind == "differs" and len(differs) < 40:
                differs.append({"row_key": r.row_key, "captured": float(r.nbm), "corpus": mean, "cycle": cycle,
                                "captured_cycle_key": r.v2_cycle_key})
        for d in (c, total):
            d[kind] += 1
    exact = total["exact"] / total["both"] if total["both"] else 0.0
    differ = total["differs"] / total["both"] if total["both"] else 1.0
    passed = bool(exact >= P1_EXACT_MIN and differ <= P1_DIFFER_MAX)
    payload = {"label": "R-PD precondition P1 (NBM parity, dev 00-06): input only, no label/price/vector read",
               "rule_sha256": RULE_PD_SHA256, "passed": passed, "share_exact_of_both": exact,
               "share_differs_of_both": differ,
               "thresholds": {"exact_min": P1_EXACT_MIN, "differs_max": P1_DIFFER_MAX, "tol": P1_TOL},
               "total": total, "by_hour": counts, "differs_examples": differs,
               "inputs": {"corpora": {str(p): _sha(p) for p in nbm_corpora},
                          "layout_snapshots_sha256": _sha(Path(layout) / "inputs_snapshots.parquet"),
                          "module_sha256": _sha(__file__)}}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- history (L6's builder, cutoffs H:30, H = 0..6)

def history_queries(dates, tz, hours=HOURS):
    """``upstream_obs_screen.history_queries`` with the hours as a parameter (local H:30)."""
    import pandas as pd

    q = pd.DataFrame([(d, h) for d in dates for h in hours], columns=["local_date", "hour"])
    loc = pd.to_datetime(q.local_date) + pd.to_timedelta(q.hour, unit="h") + pd.Timedelta(minutes=30)
    q["t_utc"] = loc.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return q.dropna(subset=["t_utc"]).reset_index(drop=True)


def build_history(research_root, nbm_table=None, hours=HOURS):
    """``upstream_obs_screen.build_history`` unchanged except the cutoffs; plus the market id and, when given, the
    NBM (mean, sd, cycle) at local hour H by L9's rule. Aug-Sep 2021-25 only (the rule's history)."""
    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as l6

    obs, sel, prov = l6.load(research_root)
    frames = []
    for code, icao in enumerate(l6.stations(sel)):
        m = sel[icao]
        g, dmax = l6.market_series(obs, icao, m["timezone"])
        dates = [d for d in dmax.index if d <= "2025-12-31" and int(d[5:7]) >= 8]
        q = history_queries(dates, m["timezone"], hours)
        f = l6.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["station"], f["local_date"], f["hour"] = icao, q.local_date, q.hour
        f["market"] = m["market"]
        f["dmax"] = q.local_date.map(dmax).to_numpy(float)
        f["year"] = q.local_date.str[:4].astype(int)
        f["month"] = q.local_date.str[5:7].astype(int)
        if nbm_table is not None:
            got = [nbm_at(nbm_table, m["market"], d, int(h), m["timezone"]) for d, h in zip(q.local_date, q.hour)]
            f["v"] = [x[0] for x in got]
            f["s"] = [x[1] for x in got]
            f["nbm_cycle"] = [x[2] for x in got]
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out = out[np.isfinite(out.r) & np.isfinite(out.t) & np.isfinite(out.dmax)].reset_index(drop=True)
    out = out[out.month.isin(LOYO_MONTHS) & out.year.isin(LOYO_YEARS)].reset_index(drop=True)
    out["y"] = out.dmax - out.r
    return out, prov


# ---------------------------------------------------------------- stack (L6's form) and the bucket Brier

def stack_fit(z, x, hours):
    """Per hour: OLS z = a + b x, b clipped to [0, 1] (a = mean(z - b x)); hours with < 200 rows are absent.
    The arithmetic is ``l6_stack.fit``'s."""
    import numpy as np

    coef = {}
    for h in HOURS:
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
    """Multi-category Brier of the integer-F buckets of normal(mu, sigma): mass below half-up(R) removed and the
    rest renormalised; the top bucket of the support takes the upper tail; one-hot at ``label``."""
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
    """mean_cell(num) / mean_cell(den) over (date, market) cells, date-clustered bootstrap (2,000 draws)."""
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
                         n_dates=int(len({keys[i][0] for i in present})), brier_base=float(b.mean()))
    return out


# ---------------------------------------------------------------- gate 1: strictly nested LOYO 2021-25

def gate1(*, research_root, nbm_corpora, rule, p1_path, p2_path, out_path):
    import numpy as np

    from weather.calibration import upstream_obs_screen as l6

    check_rule(rule)
    pre = {"p1_sha256": _require_passed(p1_path, "P1"), "p2_sha256": _require_passed(p2_path, "P2")}
    nbm = load_nbm_with_sd(nbm_corpora)
    hist, prov = build_history(research_root, nbm)
    cols = list(l6.OWN)
    X, target = hist[cols].to_numpy(float), hist.y.to_numpy(float)
    year = hist.year.to_numpy(int)
    years = sorted(set(int(y) for y in year))
    if tuple(years) != LOYO_YEARS:
        raise PredawnError(f"history years {years} != {LOYO_YEARS}")
    fitted = {}

    def model_without(excluded):
        key = tuple(sorted(excluded))
        if key not in fitted:
            tr = ~np.isin(year, key)
            fitted[key] = l6.make_model(cols).fit(X[tr], target[tr])
        return fitted[key]

    R, v, s = hist.r.to_numpy(float), hist.v.to_numpy(float), hist.s.to_numpy(float)
    dmax, hours = hist.dmax.to_numpy(float), hist.hour.to_numpy(int)
    sigma = np.maximum(s, 1.0)
    has_v = np.isfinite(v) & np.isfinite(s)
    mu_arm = np.full(len(hist), np.nan)
    coefs = {}
    for Y in years:
        te = year == Y
        n_outer = R[te] + model_without({Y}).predict(X[te])
        n_inner = np.full(len(hist), np.nan)
        for Xy in years:
            if Xy == Y:
                continue
            m = year == Xy
            n_inner[m] = R[m] + model_without({Xy, Y}).predict(X[m])
        tr = ~te & has_v
        coef = stack_fit(np.where(tr, dmax - v, np.nan), np.where(tr, n_inner - v, np.nan), hours)
        coefs[str(Y)] = {f"h{h:02d}": list(c) for h, c in coef.items()}
        mu_arm[te] = stack_mu(v[te], n_outer, hours[te], coef)
    rows = has_v
    b_arm = np.full(len(hist), np.nan)
    b_base = np.full(len(hist), np.nan)
    b_arm[rows] = bucket_brier(mu_arm[rows], sigma[rows], R[rows], dmax[rows])
    b_base[rows] = bucket_brier(v[rows], sigma[rows], R[rows], dmax[rows])
    dates = hist.local_date.astype(str).to_numpy()
    markets = hist.market.astype(str).to_numpy()
    groups = {name: rows & (hours >= lo) & (hours <= hi) for name, lo, hi in STACK_GROUPS}
    pooled = _cell_ratio(dates, markets, b_arm - b_base, b_base, groups, LOYO_SEED)
    per_market = {m: _cell_ratio(dates, markets, b_arm - b_base, b_base, {"00-06": rows & (markets == m)},
                                 LOYO_SEED).get("00-06") for m in sorted(set(markets))}
    per_year = {str(Y): _cell_ratio(dates, markets, b_arm - b_base, b_base, {"00-06": rows & (year == Y)},
                                    LOYO_SEED).get("00-06") for Y in years}
    head = pooled["00-06"]
    hour_lows = {f"h{h:02d}": pooled[f"h{h:02d}"]["ci95"][0] for h in HOURS if f"h{h:02d}" in pooled}
    worse = [h for h, lo in hour_lows.items() if lo is not None and lo > 0]
    upper_ok = bool(head["ci95"][1] is not None and head["ci95"][1] < 0)
    passed = bool(upper_ok and not worse)
    mu_rows, v_rows = np.where(rows, mu_arm, np.nan), np.where(rows, v, np.nan)
    payload = {"label": "R-PD gate 1: strictly nested LOYO 2021-25 Aug-Sep, own-obs stack vs MG-1 analogue "
                        "(integer-F bucket Brier); development evidence, no edge claim",
               "rule_sha256": RULE_PD_SHA256, "preconditions": pre, "passed": passed,
               "reading": {"pooled_upper_below_0": upper_ok, "hours_with_lower_above_0": worse},
               "dB": pooled, "per_market_00_06": per_market, "per_year_00_06": per_year,
               "population": {"history_rows": int(len(hist)), "scored_rows": int(rows.sum()),
                              "rows_without_nbm": int((~rows).sum()),
                              "nbm_cycle_counts": {str(k): int(c) for k, c in
                                                   hist.nbm_cycle.fillna("none").value_counts().items()},
                              "rmse_mu_arm_vs_dmax": float(np.sqrt(np.nanmean((mu_rows - dmax) ** 2))),
                              "rmse_v_vs_dmax": float(np.sqrt(np.nanmean((v_rows - dmax) ** 2)))},
               "stack_coef_by_held_out_year": coefs, "hgb_fits": len(fitted),
               "inputs": dict(prov, corpora={str(p): _sha(p) for p in nbm_corpora}, hgb=l6.HGB_PARAMS,
                              own=cols, l6_module_sha256=_sha(l6.__file__), module_sha256=_sha(__file__),
                              bootstrap={"draws": 2000, "seed": LOYO_SEED, "clustering": "date"},
                              support_buckets=SUPPORT)}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- serve on captured METAR (cl. 2 (e)) and P2

def captured_features(layout, replay_root, research_root, hours=HOURS):
    """L6 OWN features at each dev snapshot (local hours ``hours``) from captured METAR only.

    Pick rule clarification 2 (e) as ``r0_ols_floor_challenger.l6_captured_nowcasts`` implements it (10-minute
    usability, T-group dewpoint, prev-day max from the previous local date's last captured snapshot), plus R-PD's
    reach-back: rows of that previous-day snapshot observed before local midnight are added to each snapshot's own
    rows (de-duplicated on the observation instant, the snapshot's own row winning), so the 3-hour-ago value and the
    latest <= 90-minute-old value can reach across midnight.
    """
    from collections import defaultdict
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration import upstream_obs_screen as l6

    _, sel, _ = l6.load(research_root)
    codes = {icao: code for code, icao in enumerate(l6.stations(sel))}
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet",
                            columns=["row_key", "station", "market", "date", "local_hour", "snapshot_id"])
    if (snaps.date.astype(str) > "2026-09-29").any():
        raise PredawnError("layout holds a snapshot after 2026-09-29")
    station_of = snaps.groupby("market").station.first().to_dict()
    snaps = snaps[pd.to_numeric(snaps.local_hour, errors="coerce").isin(hours)]
    wanted = {(r.market, r.snapshot_id): (r.row_key, str(r.date)[:10]) for r in snaps.itertuples(index=False)}
    captured, snap_rows, last_rows = defaultdict(dict), defaultdict(list), defaultdict(dict)
    stats = defaultdict(int)
    for market, target, folder in l3._event_folders(replay_root):
        if market not in station_of or not (l3.DEV_FIRST - timedelta(days=1) <= target <= l3.DEV_LAST):
            continue
        path = folder / "replay_inputs.jsonl"
        if not path.is_file():
            continue
        station = station_of[market]
        last = None
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                head = line[:line.find('"sources":')] if '"sources":' in line else line
                sid, _ = l3._json_value_after(head, "snapshot_id")
                cap_s, _ = l3._json_value_after(head, "captured_at_utc")
                if cap_s is None:
                    continue
                cap = datetime.fromisoformat(cap_s)
                last = (line, cap)
                hit = wanted.get((market, sid))
                if hit is None:
                    continue
                key, local_date = hit
                captured[market][key] = [p for p in (l3.parse_captured_metar(r.get("raw"), cap)
                                                     for r in l3._captured_rows(line, station)) if p is not None]
                snap_rows[market].append((key, cap, local_date))
                stats["snapshots_scanned"] += 1
        if last is not None:
            last_rows[market][target.isoformat()] = [
                p for p in (l3.parse_captured_metar(r.get("raw"), last[1])
                            for r in l3._captured_rows(last[0], station)) if p is not None]
    frames = []
    for market in sorted(snap_rows):
        station = station_of[market]
        tz = ZoneInfo(sel[station]["timezone"])
        prev = {}
        for day in sorted({d for _, _, d in snap_rows[market]}):
            before = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
            value = l3.routine_dmax(last_rows[market].get(before, []), tz, before)
            if value is None:
                stats["prev_dmax_missing_days"] += 1
            else:
                prev[day] = value
        for key, _, day in snap_rows[market]:
            before = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()
            own = captured[market][key]
            have = {r["valid"] for r in own}
            extra = [r for r in last_rows[market].get(before, [])
                     if r["valid"].astimezone(tz).date().isoformat() < day and r["valid"] not in have]
            if extra:
                stats["snapshots_with_reach_back_rows"] += 1
            captured[market][key] = own + extra
        frames.append(l3.l6_captured_features(snap_rows[market], captured[market], tz, codes[station], prev))
    feat = pd.concat(frames, ignore_index=True)
    ok = np.isfinite(feat.r) & np.isfinite(feat.t)
    stats["no_usable_row"] = int((~ok).sum())
    return feat[ok].reset_index(drop=True), dict(stats)


def iem_features(layout, research_root, hours=HOURS):
    """L6's builder (IEM rows) at each dev snapshot's captured_at_utc, as ``upstream_obs_screen.serve`` does."""
    import numpy as np
    import pandas as pd

    from weather.calibration import upstream_obs_screen as l6

    obs, sel, _ = l6.load(research_root)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet",
                            columns=["row_key", "station", "date", "captured_at_utc", "local_hour"])
    snaps = snaps[pd.to_numeric(snaps.local_hour, errors="coerce").isin(hours)].reset_index(drop=True)
    frames = []
    for code, icao in enumerate(l6.stations(sel)):
        m = sel[icao]
        s = snaps[snaps.station == icao]
        if s.empty:
            continue
        g, dmax = l6.market_series(obs, icao, m["timezone"])
        q = pd.DataFrame({"t_utc": pd.to_datetime(s.captured_at_utc, utc=True).to_numpy(),
                          "local_date": s.date.astype(str).str[:10].to_numpy()}, index=s.index)
        q["t_utc"] = pd.to_datetime(q.t_utc, utc=True)
        f = l6.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["row_key"] = s.row_key
        frames.append(f)
    feat = pd.concat(frames)
    return feat[np.isfinite(feat.r) & np.isfinite(feat.t)].reset_index(drop=True)


def serve(*, layout, replay_root, research_root, rule, out_dir):
    """Dev nowcasts N_own at 00-06 (HGB on all Aug-Sep 2021-25 rows at H:30, H = 0..6) on captured METAR, and P2."""
    import numpy as np
    import pandas as pd

    from weather.calibration import pooled_residual_model as l2
    from weather.calibration import upstream_obs_screen as l6

    check_rule(rule)
    out = l2.require_output_outside_repo(Path(out_dir))
    if (out / "p2.json").exists():
        raise PredawnError(f"refusing to overwrite {out / 'p2.json'}")
    out.mkdir(parents=True, exist_ok=True)
    hist, prov = build_history(research_root)
    cols = list(l6.OWN)
    model = l6.make_model(cols).fit(hist[cols].to_numpy(float), hist.y.to_numpy(float))
    cap, stats = captured_features(layout, replay_root, research_root)
    iem = iem_features(layout, research_root)
    res = pd.DataFrame({"row_key": cap.row_key, "n_own": cap.r.to_numpy(float) + model.predict(
        cap[cols].to_numpy(float)), "n_up": np.nan, "n_ring": np.nan})
    res.to_parquet(out / "nowcasts.parquet", index=False)
    cap.to_parquet(out / "serve_features_captured.parquet", index=False)
    iem.to_parquet(out / "serve_features_iem.parquet", index=False)
    joined = cap.set_index("row_key").join(iem.set_index("row_key")[cols], rsuffix="_iem", how="inner")
    parity = {}
    for col in ("t", "td", "r", "tend3", "spd", "cover", "log_ceiling", "prev_dmax"):
        d = (joined[col] - joined[f"{col}_iem"]).dropna()
        parity[col] = {"n_both": int(len(d)),
                       "share_within_0.05": float((d.abs() <= P2_TOL).mean()) if len(d) else None,
                       "mad": float(d.abs().mean()) if len(d) else None,
                       "captured_nan_iem_present": int((joined[col].isna() & joined[f"{col}_iem"].notna()).sum()),
                       "iem_nan_captured_present": int((joined[col].notna() & joined[f"{col}_iem"].isna()).sum())}
    hour = np.floor(joined.hour_f.to_numpy(float)).astype(int)
    by_hour = {}
    for h in HOURS:
        m = hour == h
        by_hour[f"h{h:02d}"] = {}
        for c in ("t",) + P2_OTHER:
            d = (joined[c] - joined[f"{c}_iem"])[m].dropna()
            by_hour[f"h{h:02d}"][c] = float((d.abs() <= P2_TOL).mean()) if len(d) else None
    checks = {"t": (parity["t"]["share_within_0.05"] or 0.0) >= P2_T_MIN}
    for c in P2_OTHER:
        checks[c] = (parity[c]["share_within_0.05"] or 0.0) >= P2_OTHER_MIN
    payload = {"label": "R-PD precondition P2 (obs parity, dev 00-06): captured-built vs IEM-built OWN features; "
                        "input only, no label/price/vector read",
               "rule_sha256": RULE_PD_SHA256, "passed": bool(all(checks.values())), "checks": checks,
               "thresholds": {"tol": P2_TOL, "t_min": P2_T_MIN, "other_min": P2_OTHER_MIN},
               "parity": parity, "by_hour_share_within_0.05": by_hour,
               "rows": {"captured": int(len(cap)), "iem": int(len(iem)), "joined": int(len(joined))},
               "stats": stats, "history_rows": int(len(hist)),
               "inputs": dict(prov, nowcasts_sha256=_sha(out / "nowcasts.parquet"),
                              layout_snapshots_sha256=_sha(Path(layout) / "inputs_snapshots.parquet"),
                              l6_module_sha256=_sha(l6.__file__), module_sha256=_sha(__file__), hgb=l6.HGB_PARAMS)}
    _write_once(out / "p2.json", payload)
    return payload


# ---------------------------------------------------------------- gates 2 and 3: dev walk-forward vs MG-1 / market

def gate2(*, layout, nowcasts, rule, p1_path, p2_path, gate1_path, out_path, start="2026-08-01", end="2026-09-29"):
    import os

    import numpy as np
    import pandas as pd

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    check_rule(rule)
    pre = {"p1_sha256": _require_passed(p1_path, "P1"), "p2_sha256": _require_passed(p2_path, "P2"),
           "gate1_sha256": _require_passed(gate1_path, "gate 1")}
    os.environ["PREDAWN_NOWCASTS"] = str(nowcasts)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)
    p_mg1, cov_mg1, reasons_mg1 = l3._vector(table, loss_atlas.mg1_frame(table))
    mg1_b = table.brier(p_mg1)
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(mg1_b - market_b, w0712)
    control = float(e.mean())
    if round(control, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise PredawnError(f"MG-1 positive control failed: 07-12 excess {control:.5f}")
    frame, meta = data.module_predictions(data.CandidateSpec("module", str(CANDIDATE_MODULE)), lay, folds)
    p_arm, cov_arm, reasons_arm = l3._vector(table, frame)
    arm_b = table.brier(p_arm)
    n_tab = pd.read_parquet(nowcasts).set_index("row_key").n_own
    has_n = np.isfinite(n_tab.reindex(table.snaps.row_key).to_numpy(float))
    has_v = np.isfinite(pd.to_numeric(table.snaps.v2_mean, errors="coerce").to_numpy(float))
    in_block = np.isin(table.local_hour, HOURS)
    stacked = in_block & has_n & has_v
    band_fixed = (~stacked)[table.band_snap]
    identity = float(np.max(np.abs(p_arm - p_mg1)[band_fixed])) if band_fixed.any() else 0.0
    if not identity <= 1e-12 or not np.array_equal(cov_arm, cov_mg1):
        raise PredawnError(f"identity control failed: max |arm - MG-1| outside the stack {identity}, "
                           f"coverage equal {np.array_equal(cov_arm, cov_mg1)}")
    everything = np.ones(len(table.snaps), dtype=bool)
    pools = [("ALL", everything), ("PRIMARY5", np.isin(table.markets, sorted(l3.PRIMARY_MARKETS)))] + [
        (m, table.markets == m) for m in sorted(set(table.markets))]
    rows = []
    for scope, base in (("covered", cov_arm & cov_mg1), ("blended", everything)):
        for pool, in_pool in pools:
            for group, lo, hi in STACK_GROUPS:
                if pool not in ("ALL", "PRIMARY5") and group != "00-06":
                    continue
                mask = base & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(arm_b, mask)
                _, k = table.cells(mg1_b, mask)
                _, m = table.cells(market_b, mask)
                ones = np.ones(len(idx))
                rows.append({"scope": scope, "pool": pool, "group": group, "n_market_days": int(len(idx)),
                             "n_snapshots": int(mask.sum()), "n_snapshots_stacked": int((mask & stacked).sum()),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - k, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - k, m),
                             "excess_arm": sc.ratio_interval(date_w[:, idx], c - m, ones),
                             "excess_mg1": sc.ratio_interval(date_w[:, idx], k - m, ones)})
    pick = {(r["scope"], r["pool"], r["group"]): r for r in rows}
    head = pick[("covered", "ALL", "00-06")]["dR_date_clustered"]
    lows = {f"h{h:02d}": pick[("covered", "ALL", f"h{h:02d}")]["dR_date_clustered"]["ci95"][0]
            for h in HOURS if ("covered", "ALL", f"h{h:02d}") in pick}
    worse = [h for h, lo in lows.items() if lo is not None and lo > 0]
    lo, hi = head["ci95"]
    if hi is not None and hi < 0 and not worse:
        verdict = "WIN"
    elif lo is not None and lo > 0:
        verdict = "HARM"
    else:
        verdict = "NULL"
    gate3 = {g: {"excess_arm": pick[("covered", "ALL", g)]["excess_arm"],
                 "excess_mg1_identical_rows": pick[("covered", "ALL", g)]["excess_mg1"]}
             for g, _, _ in STACK_GROUPS if ("covered", "ALL", g) in pick}
    payload = {"label": "R-PD gates 2 (dev walk-forward vs MG-1) and 3 (vs market, reported only); development "
                        "evidence, no edge claim",
               "rule_sha256": RULE_PD_SHA256, "preconditions": pre,
               "gate2": {"verdict": verdict, "passed": verdict == "WIN",
                         "primary": dict(head, scope="covered", pool="ALL", group="00-06", interval="date-clustered"),
                         "hours_with_lower_above_0": worse},
               "gate3_reported_only": gate3, "rows": rows,
               "controls": {"mg1_excess_07_12": control, "identity_max_abs_diff": identity,
                            "coverage_mg1": reasons_mg1, "coverage_arm": reasons_arm},
               "population": {"dates": [scored[0], scored[-1], len(scored)], "n_market_days": len(table.keys)},
               "meta": meta,
               "inputs": {"nowcasts_sha256": _sha(nowcasts), "candidate_module_sha256": _sha(CANDIDATE_MODULE),
                          "module_sha256": _sha(__file__), "layout_manifest_sha256": lay.manifest_sha256,
                          "scorecard_code_sha256": sc.code_sha256(),
                          "bootstrap": {"draws": sc.DRAWS, "seed": sc.SEED, "clustering": "date and crossed"}}}
    _write_once(out_path, payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.predawn_0006", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tags", help="R-H regime tags at local hours 00-06 (heavy)")
    t.add_argument("--layout", required=True)
    t.add_argument("--replay-root", required=True)
    t.add_argument("--obs-parquet", required=True)
    t.add_argument("--out", required=True)
    a = sub.add_parser("atlas", help="00-06 market-relative loss atlas of MG-1, selection evidence (heavy)")
    a.add_argument("--layout", required=True)
    a.add_argument("--tags", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--from", dest="start", default="2026-07-31")
    a.add_argument("--to", dest="end", default="2026-09-29")
    q = sub.add_parser("p1", help="R-PD precondition P1: NBM parity at dev 00-06 (light)")
    q.add_argument("--layout", required=True)
    q.add_argument("--nbm-corpus", action="append", required=True)
    q.add_argument("--rule", required=True)
    q.add_argument("--out", required=True)
    v = sub.add_parser("serve", help="R-PD dev nowcasts on captured METAR and precondition P2 (heavy)")
    v.add_argument("--layout", required=True)
    v.add_argument("--replay-root", required=True)
    v.add_argument("--research-root", required=True)
    v.add_argument("--rule", required=True)
    v.add_argument("--out-dir", required=True)
    g1 = sub.add_parser("gate1", help="R-PD gate 1: nested LOYO 2021-25 (heavy)")
    g1.add_argument("--research-root", required=True)
    g1.add_argument("--nbm-corpus", action="append", required=True)
    g1.add_argument("--rule", required=True)
    g1.add_argument("--p1", required=True)
    g1.add_argument("--p2", required=True)
    g1.add_argument("--out", required=True)
    g2 = sub.add_parser("gate2", help="R-PD gates 2 and 3: dev walk-forward vs MG-1 and market (heavy)")
    g2.add_argument("--layout", required=True)
    g2.add_argument("--nowcasts", required=True)
    g2.add_argument("--rule", required=True)
    g2.add_argument("--p1", required=True)
    g2.add_argument("--p2", required=True)
    g2.add_argument("--gate1", required=True)
    g2.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "p1":
        r = p1(layout=args.layout, nbm_corpora=args.nbm_corpus, rule=args.rule, out_path=args.out)
        print(json.dumps({k: r[k] for k in ("passed", "share_exact_of_both", "share_differs_of_both", "total")},
                         indent=1))
        return 0
    if args.command == "serve":
        r = serve(layout=args.layout, replay_root=args.replay_root, research_root=args.research_root,
                  rule=args.rule, out_dir=args.out_dir)
        print(json.dumps({k: r[k] for k in ("passed", "checks", "rows", "stats")}, indent=1))
        return 0
    if args.command == "gate1":
        r = gate1(research_root=args.research_root, nbm_corpora=args.nbm_corpus, rule=args.rule, p1_path=args.p1,
                  p2_path=args.p2, out_path=args.out)
        print(json.dumps({"passed": r["passed"], "reading": r["reading"], "dB_00_06": r["dB"]["00-06"]}, indent=1))
        return 0
    if args.command == "gate2":
        r = gate2(layout=args.layout, nowcasts=args.nowcasts, rule=args.rule, p1_path=args.p1, p2_path=args.p2,
                  gate1_path=args.gate1, out_path=args.out)
        print(json.dumps({"gate2": r["gate2"], "controls": r["controls"]}, indent=1, default=str))
        return 0
    if args.command == "tags":
        print(json.dumps(tags(layout=args.layout, replay_root=args.replay_root, obs_parquet=args.obs_parquet,
                              out_path=args.out), indent=1, sort_keys=True))
        return 0
    if args.command == "atlas":
        r = atlas(layout=args.layout, tags_path=args.tags, out_path=args.out, start=args.start, end=args.end)
        print(json.dumps({"controls": r["controls"], "population": r["population"]}, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
