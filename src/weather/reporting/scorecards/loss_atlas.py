"""Loss atlas: where a candidate's loss against the market sits, and which slice a candidate closes.

Development evidence only (target dates 2026-07-31..2026-09-29, read through the dev scorecard's date
guard; nothing after 2026-09-29 and no 88a, panel or settlement data for 09-30..10-15 is ever read).
Nothing here is confirmation, edge or promotion evidence. Offline research: no network, writes only to
``--out``. It is not imported by serving, capture or training, and it refuses to import on the
dedicated capture host (``refuse_production_import``).

Method credit: lane L5's morning-loss diagnosis (branch ``claude/morning-loss-diagnosis-20261024`` @
``dee30cabe``, ``tools/research/morning_loss/{analyse,posthoc,extract_regimes}.py``; record
``docs/research/morning-loss-diagnosis-2026-10-24.md``). Its band geometry, centre-shift operator,
two-ordering Shapley centre/width decomposition, per-draw top-decile recomputation, regime flags and
arrival-time rule are moved here unchanged in meaning; the shift operator is vectorised (a test pins it
to L5's loop). MG-1 is the zero-parameter NBM read used as control by lane G
(``free_source_candidates.mg1`` on ``claude/free-source-screens-20261023``, rule ``r-t5-inc-c1``).

Population and scoring are the dev scorecard's (``weather.reporting.scorecards.dev_scorecard``): layout
``harness_v3_layout/1``, range 2026-08-01..2026-09-29, default walk-forward folds (7-day, gap 1, >= 7
training dates), the rule-4 floor mask and served fallback for every candidate, equal (date, market)
cells. Every interval is reported twice: ``ci95`` over the scorecard's crossed date x market weights
(binding for pooled rows, EF section 5) and ``ci95_date`` over date-clustered weights; both use 2,000
draws and seed 20260921. Rankings (top decile) are recomputed inside every draw.

**Positive control, always first:** before any candidate is read the served vector is scored with the
scorecard's own ``score_rows``; pooled R must be 1.774 (all hours) and 1.526 (00-16) to three decimals,
else the run is refused (exit 7) and nothing is written.

CLI::

    python -m weather.reporting.scorecards.loss_atlas atlas --layout C:\\swarm\\v3layout \\
        --candidate served --out <dir>
    python -m weather.reporting.scorecards.loss_atlas atlas --layout <dir> \\
        --candidate-distributions <jsonl[.gz]> --trained-through 2026-07-31 [--regimes <parquet>] --out <dir>
    python -m weather.reporting.scorecards.loss_atlas regimes --replay-root <...\\snapshots> \\
        --layout <dir> --out <regimes.parquet>

Outputs are content-addressed: ``<out>/<sha256>.json`` and ``<out>/<sha256>.md``. With a candidate
other than ``served`` the atlas adds delta sections (candidate vs served, candidate vs MG-1).
"""
from __future__ import annotations

import os


def refuse_production_import(os_name=None, identity=None):
    """Fail closed when imported on the dedicated capture host (or where that cannot be ruled out).

    On Windows the host identity must be provable; if it cannot be read, or it matches the tracked
    capture-host id, the import fails. ``identity`` returns ``(host_id, capture_host_id)``; tests inject it.
    """
    if (os.name if os_name is None else os_name) != "nt":
        return
    if identity is None:
        identity = _tracked_identity
    try:
        host_id, capture_id = identity()
    except Exception as exc:  # identity not provable: refuse
        raise ImportError(f"loss_atlas refuses to import: host identity not provable ({exc})") from exc
    if not host_id or not capture_id or host_id == capture_id:
        raise ImportError("loss_atlas is workstation research and refuses to import on the dedicated "
                          "capture host (or where that cannot be ruled out)")


def _tracked_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment

    return current_execution_host_id(), load_execution_host_assignment()["dedicated_capture_execution_host_id"]


refuse_production_import()

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.special import ndtr  # noqa: E402

from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402

SCHEMA_VERSION = "loss_atlas/1"
RANGE = ("2026-08-01", "2026-09-29")
FOLDS = (7, 1, 7)
CONTROL_EXPECTED = {"all": 1.774, "00-16": 1.526}
CONTROL_DIGITS = 3
WINDOW = (7, 12)
TOP_FRAC = 0.10
ARRIVE_TOL = 1.5
ARRIVE_LAST_HOUR = 16
LEAD_N = 2.0
SHIFT_CHUNK = 4000
FLAGS = ("R1_frontal", "R2_cloud", "R3_precip", "R4_low_gap", "R5_revision", "R6_tendency")
FORBIDDEN_INPUT = re.compile(r"88a|panel", re.IGNORECASE)
CANDIDATE_KINDS = ("served", "market", "mg1", "module", "vectors", "distributions")


class ControlFailed(data.Refused):
    """The served positive control did not reproduce; the atlas refuses to run."""

    exit_code = 7


def screen_input_path(path, label):
    """Refuse an input path that names 88a or panel data (never read by development research)."""
    if path is not None and FORBIDDEN_INPUT.search(str(path)):
        raise data.Refused(f"refused: {label} path {path} names 88a or panel data")


# ----------------------------------------------------------------------------- band geometry (L5)

class Geometry:
    """Band representative degrees, centres and the centre-shift operator (lane L5, moved)."""

    def __init__(self, table):
        b = table.bands
        self.t = table
        self.kind = b.kind.to_numpy()
        self.low = b.low.to_numpy(float)
        self.high = b.high.to_numpy(float)
        width = np.where(self.kind == "eq", self.high - self.low + 1, np.nan)
        cnt = pd.DataFrame({"s": table.band_snap, "w": width}).dropna().value_counts().reset_index()
        cnt = cnt.sort_values(["s", "count", "w"], ascending=[True, False, True]).drop_duplicates("s")
        snap_w = pd.Series(2.0, index=range(len(table.snaps)))
        snap_w[cnt.s.to_numpy()] = cnt.w.to_numpy()
        self.w = snap_w.to_numpy()[table.band_snap]
        self.rep = np.where(self.kind == "eq", (self.low + self.high) / 2,
                            np.where(self.kind == "lte", self.high - (self.w - 1) / 2, self.low + (self.w - 1) / 2))
        self.lo_edge = np.where(self.kind == "lte", -np.inf, self.low - 0.5)
        self.hi_edge = np.where(self.kind == "gte", np.inf, self.high + 0.5)
        lo_int = np.where(self.kind == "lte", self.high - self.w + 1, self.low)
        hi_int = np.where(self.kind == "gte", self.low + self.w - 1, self.high)
        self.u_lo = lo_int - 0.5                 # uniform support of each band's mass
        self.u_n = hi_int - lo_int + 1

    def norm(self, p):
        tot = np.add.reduceat(p, self.t.offsets)
        return p / np.where(tot > 0, tot, 1.0)[self.t.band_snap]

    def centre_sd(self, p):
        q = self.norm(p)
        c = np.add.reduceat(q * self.rep, self.t.offsets)
        v = np.add.reduceat(q * (self.rep - c[self.t.band_snap]) ** 2, self.t.offsets)
        return c, np.sqrt(np.maximum(v, 0))

    def shift(self, p, delta, snaps):
        """Translate each listed snapshot's band pmf by ``delta`` degrees; floor-mask; renormalise.

        Each band's mass is uniform over its integer degrees (a tail band over ``w`` degrees beyond its
        edge), integer k owning [k - 0.5, k + 0.5); the translated mass is rebinned to the same bands.
        A snapshot whose shifted mass is all impossible keeps its original vector (L5 semantics).
        """
        t = self.t
        out = p.copy()
        snaps = np.asarray(snaps, int)
        if not len(snaps):
            return out
        for chunk in np.array_split(snaps, max(1, int(math.ceil(len(snaps) / SHIFT_CHUNK)))):
            n = t.n[chunk]
            off = t.offsets[chunk]
            starts = np.cumsum(n) - n
            local = np.repeat(np.arange(len(chunk)), n)
            bj = np.repeat(off, n) + (np.arange(n.sum()) - np.repeat(starts, n))
            nn = n[local]
            pair_j = np.repeat(np.arange(len(bj)), nn)
            pair_s = local[pair_j]
            pstart = np.cumsum(nn) - nn
            pb = np.repeat(off[local], nn) + (np.arange(nn.sum()) - np.repeat(pstart, nn))
            tot = np.add.reduceat(p[bj], starts)
            q = p[pb] / np.maximum(tot[pair_s], 1e-300)
            d = delta[chunk][pair_s]
            jj = bj[pair_j]
            with np.errstate(invalid="ignore"):
                hi = q * np.clip((self.hi_edge[jj] - d - self.u_lo[pb]) / self.u_n[pb], 0.0, 1.0)
                lo = q * np.clip((self.lo_edge[jj] - d - self.u_lo[pb]) / self.u_n[pb], 0.0, 1.0)
            new = np.maximum(np.bincount(pair_j, weights=hi - lo, minlength=len(bj)), 0.0)
            new[t.impossible[bj]] = 0.0
            ntot = np.add.reduceat(new, starts)
            keep = ntot[local] > 0
            out[bj] = np.where(keep, new / np.where(ntot > 0, ntot, 1.0)[local], p[bj])
        return out


# ----------------------------------------------------------------------------- candidates

def mg1_frame(table):
    """MG-1 (``r-t5-inc-c1``, EF 10q; lane G's control): Normal(v2_mean, max(v2_stddev, 1)) on integers,
    H = max(B, X) with B = floor(F + 0.5), F the rule-4 floor; only where v2 was available at capture."""
    s = table.snaps
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce")
    mu = pd.to_numeric(s.v2_mean, errors="coerce").to_numpy(float)
    sd = pd.to_numeric(s.v2_stddev, errors="coerce").to_numpy(float)
    ok = (np.isfinite(mu) & np.isfinite(sd) & avail.notna().to_numpy() & cap.notna().to_numpy()
          & (avail <= cap).fillna(False).to_numpy())
    if "floor" in s.columns:
        floor = pd.to_numeric(s["floor"], errors="coerce").to_numpy(float)
    else:
        floor = s[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1).to_numpy(float)
    B = np.where(np.isfinite(floor), np.floor(floor + 0.5), -np.inf)
    sel = ok[table.band_snap]
    b = table.bands[sel]
    snap = table.band_snap[sel]
    kind = b.kind.to_numpy()
    low, high = b.low.to_numpy(float), b.high.to_numpy(float)
    m, sg, bb = mu[snap], np.maximum(sd[snap], 1.0), B[snap]
    up = np.where(kind == "gte", np.inf, high + 0.5)
    lo = np.where((kind == "lte") | (low <= bb), -np.inf, low - 0.5)
    possible = (kind == "gte") | (high >= bb)
    p = np.clip(np.where(possible, ndtr((up - m) / sg) - ndtr((lo - m) / sg), 0.0), 0.0, None)
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int), "p": p})


def candidate_vector(spec, layout, folds, table):
    """The candidate's band vector on the scored population, through the scorecard's contract."""
    ident = spec.identity()
    if spec.kind == "served":
        ident["walk_forward"] = "not_applicable_served_vector_of_record"
        return table.p_served, ident, {}
    if spec.kind == "market":
        ident["walk_forward"] = "not_applicable_market_identity_control"
        return table.p_market, ident, {}
    if spec.kind == "mg1":
        ident.update(rule="r-t5-inc-c1 (MG-1), zero fitted parameters",
                     walk_forward="not_applicable_no_fitted_parameters")
        p, reasons = table.candidate_vector(mg1_frame(table))
        return p, ident, reasons
    builder = {"module": data.module_predictions, "vectors": data.vector_predictions,
               "distributions": data.distribution_predictions}[spec.kind]
    frame, meta = builder(spec, layout, folds)
    ident.update(meta)
    if spec.kind == "module":
        ident["walk_forward"] = "enforced_fit_per_fold"
    p, reasons = table.candidate_vector(frame)
    return p, ident, reasons


# ----------------------------------------------------------------------------- statistics

def _q(boot):
    b = np.asarray(boot, float)
    b = b[np.isfinite(b)]
    return [float(x) for x in np.quantile(b, [.025, .975])] if len(b) else [None, None]


def _q_level(boot, level):
    b = np.asarray(boot, float)
    b = b[np.isfinite(b)]
    a = (1 - level) / 2
    return [float(x) for x in np.quantile(b, [a, 1 - a])] if len(b) else [None, None]


class Stats:
    """Crossed (binding) and date-clustered bootstrap weights over the scored (date, market) cells."""

    def __init__(self, table):
        self.W = table.w
        self.Wd = sc.crossed_weights([k[0] for k in table.keys], ["all"] * len(table.keys))
        self.n = len(table.keys)

    def ratio(self, a, b=None, sel=None, power=False):
        a = np.asarray(a, float)
        b = np.ones(len(a)) if b is None else np.asarray(b, float)
        ok = np.isfinite(a) & np.isfinite(b)
        if sel is not None:
            ok &= sel
        if not ok.any() or b[ok].sum() == 0:
            return {"estimate": None, "ci95": [None, None], "ci95_date": [None, None], "n_cells": int(ok.sum())}
        a, b = a[ok], b[ok]
        out = {"estimate": float(a.sum() / b.sum()), "n_cells": int(ok.sum())}
        for key, w in (("ci95", self.W[:, ok]), ("ci95_date", self.Wd[:, ok])):
            den = w @ b
            boot = np.divide(w @ a, den, out=np.full(len(den), np.nan), where=den != 0)
            out[key] = _q(boot)
            if power and key == "ci95":
                out.update({k: v for k, v in sc.mde80(out["estimate"], boot).items() if k in ("mde80", "power")})
        return out

    def top_ratio(self, rank, num, den, den_in_top=False, sel=None):
        """sum(num over the top decile of ``rank``) / sum(den over the top decile or all), decile per draw."""
        rank = np.asarray(rank, float)
        ok = np.isfinite(rank) & np.isfinite(num) & np.isfinite(den)
        if sel is not None:
            ok &= sel
        idx = np.flatnonzero(ok)
        if not len(idx):
            return {"estimate": None, "ci95": [None, None], "ci95_date": [None, None]}
        r, a, b = rank[idx], np.asarray(num, float)[idx], np.asarray(den, float)[idx]
        top = top_mask(r)
        d0 = b[top].sum() if den_in_top else b.sum()
        out = {"estimate": float(a[top].sum() / d0) if d0 else None}
        for key, w in (("ci95", self.W), ("ci95_date", self.Wd)):
            boot = []
            for wb in w[:, idx].astype(float):
                m = wb > 0
                tb = np.zeros(len(r), bool)
                tb[np.flatnonzero(m)] = top_mask(r[m], wb[m])
                dd = (wb * b)[tb].sum() if den_in_top else (wb * b).sum()
                boot.append((wb * a)[tb].sum() / dd if dd else np.nan)
            out[key] = _q(boot)
        return out

    def top_boot_masks(self, rank, sel=None):
        """Per-draw top-decile masks (crossed), for statistics that need the draw's own decile."""
        rank = np.asarray(rank, float)
        ok = np.isfinite(rank) if sel is None else np.isfinite(rank) & sel
        for wb in self.W.astype(float):
            m = (wb > 0) & ok
            tb = np.zeros(len(rank), bool)
            tb[np.flatnonzero(m)] = top_mask(rank[m], wb[m])
            yield wb, tb


def top_mask(E, weights=None):
    """Top ``TOP_FRAC`` of (weighted) cells by E; unweighted = ceil(10%) (lane L5)."""
    E = np.asarray(E, float)
    order = np.argsort(-E, kind="stable")
    m = np.zeros(len(E), bool)
    if not len(E):
        return m
    if weights is None:
        k = int(math.ceil(TOP_FRAC * len(E)))
    else:
        cw = np.cumsum(weights[order])
        k = int(np.searchsorted(cw, TOP_FRAC * cw[-1]) + 1)
    m[order[:k]] = True
    return m


# ----------------------------------------------------------------------------- positive control

def positive_control(table, expected=None):
    """Served vs market pooled R from the scorecard's own rows; refuse unless it reproduces."""
    expected = CONTROL_EXPECTED if expected is None else expected
    rows = {r["block"]: r for r in sc.score_rows(table, table.p_served, True) if r["market"] == sc.ALL_MARKETS}
    observed = {block: rows[block]["gap_ratio"]["estimate"] if block in rows else None for block in expected}
    match = {block: observed[block] is not None
             and round(observed[block], CONTROL_DIGITS) == round(expected[block], CONTROL_DIGITS)
             for block in expected}
    out = {"control": "served vs market pooled R (dev scorecard score_rows, crossed W)",
           "expected": dict(expected), "observed": observed,
           "ci95": {b: rows[b]["gap_ratio"]["ci95"] for b in expected if b in rows},
           "digits": CONTROL_DIGITS, "verdict": "PASS" if all(match.values()) else "FAIL"}
    if out["verdict"] != "PASS":
        raise ControlFailed(f"refused: positive control failed (served R observed {observed}, expected "
                            f"{dict(expected)} to {CONTROL_DIGITS} decimals); the atlas does not run")
    return out


# ----------------------------------------------------------------------------- atlas core

class Model:
    """One scored vector with its per-snapshot Brier, centre and shifted-vector Brier (L5 orderings)."""

    def __init__(self, name, p, ctx):
        t, geo = ctx.t, ctx.geo
        self.name = name
        self.p = p
        self.b = t.brier(p)
        self.c, self.sd = geo.centre_sd(p)
        allsn = np.arange(len(t.snaps))
        if name == "market":
            self.b_sh = self.b_msh = self.b
        else:
            self.b_sh = t.brier(geo.shift(p, ctx.c_m - self.c, allsn))          # ordering A
            self.b_msh = t.brier(geo.shift(t.p_market, self.c - ctx.c_m, allsn))  # ordering B


class Context:
    def __init__(self, layout, table, window):
        self.layout, self.t, self.window = layout, table, window
        self.geo = Geometry(table)
        self.st = Stats(table)
        self.hour = table.local_hour
        cap = pd.to_datetime(table.snaps.captured_at_local.astype(str).str.slice(0, 19), errors="coerce")
        self.tod = self.hour + cap.dt.minute.fillna(0).to_numpy() / 60.0
        self.inW = (self.hour >= window[0]) & (self.hour <= window[1])
        lab = layout.labels.set_index("row_key").reindex(table.snaps.row_key)
        self.y = lab.settlement_high.to_numpy(float)
        self.c_m, self.sd_m = self.geo.centre_sd(table.p_market)
        self.b_m = table.brier(table.p_market)
        self.dates = np.array([k[0] for k in table.keys])
        self.markets = np.array([k[1] for k in table.keys])

    def cm(self, values, mask=None):
        mask = self.inW if mask is None else mask
        idx, v = self.t.cells(np.asarray(values, float), mask)
        full = np.full(len(self.t.keys), np.nan)
        full[idx] = v
        return full


def _components(ctx, m, mask):
    E = ctx.cm(m.b - ctx.b_m, mask)
    cA = ctx.cm(m.b - m.b_sh, mask)
    cB = E - ctx.cm(m.b - m.b_msh, mask)
    return E, cA, cB, (cA + cB) / 2


def decomposition(ctx, m, mask=None):
    st = ctx.st
    E, cA, cB, sh = _components(ctx, m, mask)
    y = ctx.cm(ctx.y, mask)
    c_x, c_mk = ctx.cm(m.c, mask), ctx.cm(ctx.c_m, mask)
    z2 = ctx.cm(((ctx.y - m.c) / np.maximum(m.sd, 0.25)) ** 2, mask)
    return {"excess_over_market": st.ratio(E, power=True),
            "R": st.ratio(ctx.cm(m.b, mask), ctx.cm(ctx.b_m, mask)),
            "centre_share_A": st.ratio(cA, E), "centre_share_B": st.ratio(cB, E),
            "centre_share_shapley": st.ratio(sh, E), "width_share_shapley": st.ratio(E - sh, E),
            "centre_bias": st.ratio(c_x - y), "centre_bias_market": st.ratio(c_mk - y),
            "centre_mae": st.ratio(ctx.cm(np.abs(m.c - ctx.y), mask)),
            "centre_mae_market": st.ratio(ctx.cm(np.abs(ctx.c_m - ctx.y), mask)),
            "centre_mae_minus_market": st.ratio(ctx.cm(np.abs(m.c - ctx.y), mask)
                                                - ctx.cm(np.abs(ctx.c_m - ctx.y), mask)),
            "market_minus_model_centre": st.ratio(c_mk - c_x),
            "mean_sd": st.ratio(ctx.cm(m.sd, mask)), "mean_sd_market": st.ratio(ctx.cm(ctx.sd_m, mask)),
            "mean_z2": st.ratio(z2)}


def per_market(ctx, m):
    E, _, _, sh = _components(ctx, m, None)
    out = {}
    for mk in sorted(set(ctx.markets)):
        sel = ctx.markets == mk
        out[mk] = {"excess_over_market": ctx.st.ratio(E, sel=sel),
                   "R": ctx.st.ratio(ctx.cm(m.b), ctx.cm(ctx.b_m), sel=sel),
                   "centre_share_shapley": ctx.st.ratio(sh, E, sel=sel),
                   "centre_bias": ctx.st.ratio(ctx.cm(m.c - ctx.y), sel=sel),
                   "centre_mae": ctx.st.ratio(ctx.cm(np.abs(m.c - ctx.y)), sel=sel),
                   "centre_mae_market": ctx.st.ratio(ctx.cm(np.abs(ctx.c_m - ctx.y)), sel=sel)}
    return out


def per_hour(ctx, m):
    out = {}
    for h in sorted(set(ctx.hour.tolist())):
        mh = ctx.hour == h
        E, _, _, sh = _components(ctx, m, mh)
        out[f"{h:02d}"] = {"excess_over_market": ctx.st.ratio(E),
                           "R": ctx.st.ratio(ctx.cm(m.b, mh), ctx.cm(ctx.b_m, mh)),
                           "centre_share_shapley": ctx.st.ratio(sh, E),
                           "centre_bias": ctx.st.ratio(ctx.cm(m.c - ctx.y, mh)),
                           "centre_mae": ctx.st.ratio(ctx.cm(np.abs(m.c - ctx.y), mh)),
                           "centre_mae_market": ctx.st.ratio(ctx.cm(np.abs(ctx.c_m - ctx.y), mh))}
    return out


def concentration(ctx, m, models):
    E = ctx.cm(m.b - ctx.b_m)
    ok = np.isfinite(E)
    pos = np.maximum(E, 0)
    top = np.zeros(len(E), bool)
    top[np.flatnonzero(ok)] = top_mask(E[ok])
    ycell = ctx.cm(ctx.y)
    centres = {name: ctx.cm(x.c) for name, x in models.items()}
    others = {name: ctx.cm(x.b - ctx.b_m) for name, x in models.items() if name != m.name}
    listing = []
    for i in np.flatnonzero(top)[np.argsort(-E[top], kind="stable")]:
        row = {"date": str(ctx.dates[i]), "market": str(ctx.markets[i]), "excess": float(E[i]),
               "outcome": _f(ycell[i]), "centre_market": _f(ctx.cm(ctx.c_m)[i])}
        row.update({f"centre_{name}": _f(v[i]) for name, v in centres.items()})
        row.update({f"excess_{name}": _f(v[i]) for name, v in others.items()})
        listing.append(row)
    return {"k_top": int(top.sum()), "n_cells": int(ok.sum()),
            "share_of_total_excess": ctx.st.top_ratio(E, E, E),
            "share_of_positive_excess": ctx.st.top_ratio(E, pos, pos),
            "composition_by_market": {str(k): int(v) for k, v in
                                      pd.Series(ctx.markets[top]).value_counts().sort_index().items()},
            "n_dates": int(len(set(ctx.dates[top]))), "top_decile": listing}, top


def heat_terciles(ctx):
    """Within-market tercile of the market's window centre (ex ante; lane L5 post-hoc (b))."""
    cw = pd.DataFrame({"m": ctx.markets, "c": ctx.cm(ctx.c_m)})
    terc = np.full(len(cw), np.nan)
    for _, g in cw.dropna().groupby("m"):
        if len(g) >= 3:
            terc[g.index.to_numpy()] = pd.qcut(g.c.rank(method="first"), 3, labels=[1, 2, 3]).astype(float)
    return terc


def regimes_section(ctx, m, top, terc, flags):
    E = ctx.cm(m.b - ctx.b_m)
    c_x, c_mk, y = ctx.cm(m.c), ctx.cm(ctx.c_m), ctx.cm(ctx.y)
    out = {"heat_tercile": {}}
    for k in (1, 2, 3):
        sel = terc == k
        out["heat_tercile"][str(k)] = {"n_cells": int(sel.sum()), "excess_over_market": ctx.st.ratio(E, sel=sel),
                                       "market_minus_model_centre": ctx.st.ratio(c_mk - c_x, sel=sel),
                                       "centre_bias": ctx.st.ratio(c_x - y, sel=sel),
                                       "centre_bias_market": ctx.st.ratio(c_mk - y, sel=sel),
                                       "n_top_decile": int((sel & top).sum())}
    out["flags"] = {}
    for f, (flag, avail) in flags.items():
        out["flags"][f] = _flag_stats(ctx, E, top, flag, avail)
    return out


def _flag_stats(ctx, E, top, flag, avail):
    a = avail & np.isfinite(E)
    ft = flag[top & a].mean() if (top & a).any() else math.nan
    fa = flag[a].mean() if a.any() else math.nan
    boot = []
    for wb, tb in ctx.st.top_boot_masks(E):
        num = (wb * flag * a)[tb].sum() / max((wb * a)[tb].sum(), 1e-12)
        den = (wb * flag * a).sum() / max((wb * a).sum(), 1e-12)
        boot.append(num / den if den > 0 else np.nan)
    base = pd.Series(flag[a]).groupby(ctx.markets[a]).mean()
    fl_top = top & a & flag
    res = {"freq_top": _f(ft), "freq_all": _f(fa), "FR": _f(ft / fa) if fa and fa > 0 else None,
           "FR_ci95": _q(boot), "FR_ci_bonferroni": _q_level(boot, 1 - 0.05 / len(FLAGS)),
           "n_top_flagged": int(fl_top.sum()), "n_markets_top_flagged": int(len(set(ctx.markets[fl_top]))),
           "market_stratified_expected": float(sum(base.get(mk, 0) for mk in ctx.markets[top & a])),
           "excess_flag1": ctx.st.ratio(E, sel=a & flag), "excess_flag0": ctx.st.ratio(E, sel=a & ~flag)}
    lo, blo = res["FR_ci95"][0], res["FR_ci_bonferroni"][0]
    sig = lo is not None and lo > 1.0 and res["n_top_flagged"] >= 10 and res["n_markets_top_flagged"] >= 3
    res["verdict"] = "STRONG_SIGNAL" if sig and blo is not None and blo > 1.0 else "SIGNAL" if sig else "NO_SIGNAL"
    return res


def regime_flags(ctx, regimes_path):
    """R5 from layout forecast columns (L5); R1-R4, R6 from an ``regimes`` parquet when given."""
    t = ctx.t
    keys = t.keys
    snaps = t.snaps.assign(_cell=t.cell, _tod=ctx.tod)
    parts = []
    for col in ("hrrr_high", "nws_grid_high_raw", "v2_p50"):
        if col not in snaps:
            continue
        v = pd.to_numeric(snaps[col], errors="coerce")
        g = snaps.assign(_v=v).dropna(subset=["_v"])
        first = g.sort_values("_tod").groupby("_cell")._v.first()
        last = g[g.local_hour <= 12].sort_values("_tod").groupby("_cell")._v.last()
        parts.append((last - first).reindex(range(len(keys))).to_numpy(float))
    with np.errstate(all="ignore"):
        rev = np.nanmean(np.vstack(parts), axis=0) if parts else np.full(len(keys), np.nan)
    flags = {"R5_revision": (np.abs(np.nan_to_num(rev, nan=0.0)) >= 2, np.isfinite(rev))}
    source = {"R5_revision": "layout hrrr_high / nws_grid_high_raw / v2_p50 (first vs last <= 12:59)"}
    if regimes_path is not None:
        reg = pd.read_parquet(regimes_path)
        if len(reg) and (pd.to_datetime(reg.date.astype(str)).dt.date > data.DEV_LAST).any():
            raise data.Refused(f"refused: regimes file holds a date after {data.DEV_LAST}")
        reg = reg.set_index(["date", "market"]).reindex(pd.MultiIndex.from_tuples(keys))
        avail_cols = {"R4_low_gap": "overnight_low_gap", "R6_tendency": "tendency_anomaly"}
        for f in FLAGS:
            if f == "R5_revision" or f not in reg:
                continue
            col = avail_cols.get(f)
            avail = reg[col].notna().to_numpy() if col in reg else reg[f].notna().to_numpy()
            flags[f] = (reg[f].fillna(False).to_numpy(bool), avail)
            source[f] = f"regimes parquet sha256 {data.sha256_file(regimes_path)}"
    return {k: flags[k] for k in FLAGS if k in flags}, source


def timing(ctx, m, top):
    """Arrival rule (L5): first snapshot from which |centre - outcome| <= 1.5 F through 16:59."""
    sel = ctx.hour <= ARRIVE_LAST_HOUR
    df = pd.DataFrame({"cell": ctx.t.cell, "tod": ctx.tod, "cx": m.c, "cm": ctx.c_m, "y": ctx.y})[sel]
    df = df.sort_values(["cell", "tod"], kind="stable")

    def arrival(tod, err):
        ok = (err <= ARRIVE_TOL)[::-1]
        suffix = np.logical_and.accumulate(ok)[::-1]
        return float(tod[np.argmax(suffix)]) if suffix[-1] else float(ARRIVE_LAST_HOUR + 1)

    arr = np.full((len(ctx.t.keys), 2), np.nan)
    for cell, g in df.groupby("cell", sort=True):
        tod, y = g.tod.to_numpy(), g.y.to_numpy()
        arr[cell] = arrival(tod, np.abs(g.cx.to_numpy() - y)), arrival(tod, np.abs(g.cm.to_numpy() - y))
    lead = arr[:, 0] - arr[:, 1]
    E = ctx.cm(m.b - ctx.b_m)
    out = {"tolerance_F": ARRIVE_TOL, "lead_signal_hours": LEAD_N}
    for name, msk in (("top", top), ("all", np.isfinite(lead))):
        ok = msk & np.isfinite(lead)
        entry = {"mean_lead_h": _f(lead[ok].mean()) if ok.any() else None,
                 "median_lead_h": _f(np.median(lead[ok])) if ok.any() else None,
                 "mean_arrival_model_h": _f(arr[ok, 0].mean()) if ok.any() else None,
                 "mean_arrival_market_h": _f(arr[ok, 1].mean()) if ok.any() else None,
                 "frac_market_first": _f((lead[ok] > 0).mean()) if ok.any() else None,
                 "frac_model_never_by_17": _f((arr[ok, 0] > ARRIVE_LAST_HOUR).mean()) if ok.any() else None}
        if name == "top":
            entry["lead"] = ctx.st.top_ratio(np.where(np.isfinite(lead), E, np.nan), np.nan_to_num(lead),
                                             np.ones(len(lead)), den_in_top=True)
        else:
            entry["lead"] = ctx.st.ratio(lead)
        out[name] = entry
    lo = out["top"]["lead"]["ci95"][0]
    est = out["top"]["mean_lead_h"]
    out["verdict"] = "SIGNAL" if est is not None and est >= LEAD_N and lo is not None and lo > 0 else "NO_SIGNAL"
    df["h"] = np.floor(df.tod).astype(int)
    hm = df.groupby(["cell", "h"])[["cx", "cm", "y"]].mean().reset_index()
    curves = {}
    for name, msk in (("top", top), ("all", np.ones(len(top), bool))):
        sub = hm[hm.cell.isin(np.flatnonzero(msk))]
        g = sub.assign(ex=(sub.cx - sub.y).abs(), em=(sub.cm - sub.y).abs(), gap=sub.cm - sub.cx) \
            .groupby("h")[["ex", "em", "gap"]].mean()
        curves[name] = {f"{int(h):02d}": {"mae_model": float(r.ex), "mae_market": float(r.em),
                                          "market_minus_model": float(r.gap)} for h, r in g.iterrows()}
    out["hourly_centre_curves"] = curves
    return out


def delta_section(ctx, cand, base, base_top, terc):
    """Which slice of ``base``'s window loss the candidate closed (positive = closed)."""
    st = ctx.st
    Eb, _, _, shb = _components(ctx, base, None)
    Ec, _, _, shc = _components(ctx, cand, None)
    closed = Eb - Ec
    out = {"base": base.name,
           "candidate_minus_base_brier": st.ratio(ctx.cm(cand.b) - ctx.cm(base.b), power=True),
           "closed_excess": st.ratio(closed),
           "share_of_base_excess_closed": st.ratio(closed, Eb),
           "closed_in_centre_share": st.ratio(shb - shc, Eb),
           "closed_in_width_share": st.ratio((Eb - shb) - (Ec - shc), Eb),
           "centre_bias_change": st.ratio(ctx.cm(cand.c - ctx.y) - ctx.cm(base.c - ctx.y)),
           "centre_mae_change": st.ratio(ctx.cm(np.abs(cand.c - ctx.y)) - ctx.cm(np.abs(base.c - ctx.y))),
           "base_top_decile_closed_share": st.top_ratio(Eb, closed, Eb, den_in_top=True),
           "share_of_closure_from_base_top_decile": st.top_ratio(Eb, closed, closed),
           "per_market": {}, "per_hour": {}, "heat_tercile": {}}
    for mk in sorted(set(ctx.markets)):
        sel = ctx.markets == mk
        out["per_market"][mk] = {"closed_excess": st.ratio(closed, sel=sel),
                                 "share_closed": st.ratio(closed, Eb, sel=sel)}
    for h in sorted(set(ctx.hour.tolist())):
        mh = ctx.hour == h
        cl = ctx.cm(base.b - cand.b, mh)
        out["per_hour"][f"{h:02d}"] = {"closed_excess": st.ratio(cl),
                                       "share_closed": st.ratio(cl, ctx.cm(base.b - ctx.b_m, mh))}
    for k in (1, 2, 3):
        sel = terc == k
        out["heat_tercile"][str(k)] = {"closed_excess": st.ratio(closed, sel=sel),
                                       "share_closed": st.ratio(closed, Eb, sel=sel)}
    out["base_top_decile_n"] = int(base_top.sum())
    return out


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def code_sha256():
    h = hashlib.sha256()
    for module in (sys.modules[__name__], sc, data):
        h.update(Path(module.__file__).read_bytes())
    return h.hexdigest()


def run_atlas(layout_root, spec, regimes_path=None, window=WINDOW, control_expected=None):
    """Positive control first; then the atlas for ``spec`` against served, MG-1 and the market."""
    if spec.kind not in CANDIDATE_KINDS:
        raise data.Refused(f"refused: unknown candidate kind {spec.kind!r}")
    for path, label in ((layout_root, "layout"), (spec.path, "candidate"), (regimes_path, "regimes")):
        screen_input_path(path, label)
    start, end = data.check_range(*RANGE)
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, *FOLDS)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    if not scored:
        raise data.Refused("refused: the fold scheme scores no date in this range")
    table = sc.Table(layout, scored)
    control = positive_control(table, control_expected)           # always first; raises on failure
    ctx = Context(layout, table, window)
    p_c, ident, coverage = candidate_vector(spec, layout, folds, table)
    p_mg1, mg1_cov = table.candidate_vector(mg1_frame(table))
    models = {"candidate": Model("candidate", p_c, ctx), "served": Model("served", table.p_served, ctx),
              "mg1": Model("mg1", p_mg1, ctx)}
    terc = heat_terciles(ctx)
    flags, flag_source = regime_flags(ctx, regimes_path)
    sections, tops = {}, {}
    for name, m in models.items():
        conc, top = concentration(ctx, m, models)
        tops[name] = top
        sections[name] = {"decomposition": decomposition(ctx, m), "per_market": per_market(ctx, m),
                          "per_hour": per_hour(ctx, m), "concentration": conc,
                          "regimes": regimes_section(ctx, m, top, terc, flags), "timing": timing(ctx, m, top)}
    deltas = {}
    if spec.kind != "served":
        deltas["vs_served"] = delta_section(ctx, models["candidate"], models["served"], tops["served"], terc)
    if spec.kind != "mg1":
        deltas["vs_mg1"] = delta_section(ctx, models["candidate"], models["mg1"], tops["mg1"], terc)
    return {
        "schema": SCHEMA_VERSION, "code_sha256": code_sha256(), "evidence_class": "development",
        "method_credit": "lane L5 morning-loss diagnosis (claude/morning-loss-diagnosis-20261024 @ dee30cabe); "
                         "MG-1 per lane G free_source_candidates.mg1 (r-t5-inc-c1)",
        "data_rule": "dates <= 2026-09-29 only (dev scorecard guard); no 88a, panel or 09-30..10-15 settlement "
                     "data; candidate and regimes paths naming 88a/panel are refused",
        "positive_control": control,
        "range": {"from": RANGE[0], "to": RANGE[1], "folds": dict(zip(("fold_days", "gap_days",
                                                                        "min_train_dates"), FOLDS))},
        "window": {"local_hours": list(window)},
        "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                       "n_markets": len(set(table.markets)), "n_market_days": len(table.keys),
                       "n_snapshots": int(len(table.snaps)), "n_window_snapshots": int(ctx.inW.sum())},
        "candidate": ident, "candidate_coverage": coverage, "mg1_coverage": mg1_cov,
        "regime_flag_sources": flag_source,
        "provenance": {"labels": layout.label_source, "layout_manifest_sha256": layout.manifest_sha256,
                       "layout_files": layout.file_sha256},
        "constants": {"draws": sc.DRAWS, "seed": sc.SEED, "top_frac": TOP_FRAC, "arrive_tol_F": ARRIVE_TOL,
                      "intervals": "ci95 crossed date x market (binding pooled, EF 5); ci95_date date-clustered"},
        "models": sections, "deltas": deltas,
    }


# ----------------------------------------------------------------------------- report

def _x(entry, digits=4, pct=False):
    if not isinstance(entry, dict) or entry.get("estimate") is None:
        return "n/a"
    k = 100.0 if pct else 1.0
    fmt = (lambda v: "n/a" if v is None else f"{v * k:.{1 if pct else digits}f}")
    lo, hi = entry.get("ci95") or [None, None]
    dlo, dhi = entry.get("ci95_date") or [None, None]
    return f"{fmt(entry['estimate'])} [{fmt(lo)}, {fmt(hi)}] (date [{fmt(dlo)}, {fmt(dhi)}])"


def atlas_markdown(payload, sha):
    w = payload["window"]["local_hours"]
    win = f"{w[0]:02d}-{w[1]:02d}"
    pc = payload["positive_control"]
    cand = payload["candidate"]
    L = [f"# Loss atlas `{sha[:12]}`", "",
         "Development evidence only (dates <= 2026-09-29); descriptive; not confirmation, edge or promotion "
         "evidence. Method: lane L5 morning-loss diagnosis; MG-1 per lane G.", "",
         f"- Positive control **{pc['verdict']}**: served R all {pc['observed']['all']:.3f}, 00-16 "
         f"{pc['observed']['00-16']:.3f} (expected {pc['expected']['all']}, {pc['expected']['00-16']}).",
         f"- Candidate `{cand['kind']}` {cand.get('name', '')}; walk-forward: {cand.get('walk_forward')}; "
         f"coverage {payload['candidate_coverage']}",
         f"- Population: {payload['population']['n_dates']} dates {payload['population']['first_date']}.."
         f"{payload['population']['last_date']}, {payload['population']['n_markets']} markets, "
         f"{payload['population']['n_market_days']} market-days; window {win} local.",
         "- Intervals: crossed date x market (binding pooled), then date-clustered.", ""]
    L += [f"## Decomposition of the {win} excess over the market", "",
          "| Quantity | " + " | ".join(payload["models"]) + " |", "| --- |" + " --- |" * len(payload["models"])]
    rows = (("Excess Brier over market", "excess_over_market", False), ("R = model / market", "R", False),
            ("Centre share (Shapley)", "centre_share_shapley", True),
            ("Width share (Shapley)", "width_share_shapley", True),
            ("Centre share, ordering A", "centre_share_A", True), ("Centre share, ordering B", "centre_share_B", True),
            ("Centre bias (centre - outcome), F", "centre_bias", False),
            ("Market centre bias, F", "centre_bias_market", False), ("Centre MAE, F", "centre_mae", False),
            ("Market centre MAE, F", "centre_mae_market", False),
            ("Centre MAE minus market, F", "centre_mae_minus_market", False),
            ("Mean SD / market SD, F", None, False), ("Mean z^2", "mean_z2", False))
    for label, key, pct in rows:
        cells = []
        for name, sec in payload["models"].items():
            d = sec["decomposition"]
            if key is None:
                cells.append(f"{_fx(d['mean_sd'].get('estimate'), 2)} / {_fx(d['mean_sd_market'].get('estimate'), 2)}")
            else:
                cells.append(_x(d[key], 2 if "F" in label else 4, pct))
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    for name, sec in payload["models"].items():
        c = sec["concentration"]
        L += ["", f"## {name}: per hour (excess, R, centre share, centre MAE model / market)", "",
              "| Hour | Excess | R | Centre share % | MAE model / market |", "| --- | --- | --- | --- | --- |"]
        for h, r in sec["per_hour"].items():
            L.append(f"| {h} | {_x(r['excess_over_market'])} | {_x(r['R'], 3)} | "
                     f"{_x(r['centre_share_shapley'], pct=True)} | {_fx(r['centre_mae']['estimate'], 2)} / "
                     f"{_fx(r['centre_mae_market']['estimate'], 2)} |")
        L += ["", f"## {name}: per market ({win}, date-clustered)", "",
              "| Market | Excess | R | Centre share % | Centre bias, F |", "| --- | --- | --- | --- | --- |"]
        for mk, r in sec["per_market"].items():
            L.append(f"| {mk} | {_x(r['excess_over_market'])} | {_x(r['R'], 3)} | "
                     f"{_x(r['centre_share_shapley'], pct=True)} | {_x(r['centre_bias'], 2)} |")
        L += ["", f"## {name}: concentration", "",
              f"- Top decile: {c['k_top']} of {c['n_cells']} market-days on {c['n_dates']} dates; share of total "
              f"excess {_x(c['share_of_total_excess'], pct=True)}%, of positive excess "
              f"{_x(c['share_of_positive_excess'], pct=True)}%.",
              f"- Composition: {c['composition_by_market']}", "",
              "| # | date | market | excess | outcome | centre model | centre market |", "| --- |" + " --- |" * 6]
        for i, r in enumerate(c["top_decile"], 1):
            L.append(f"| {i} | {r['date']} | {r['market']} | {r['excess']:.3f} | {_fx(r['outcome'], 0)} | "
                     f"{_fx(r.get('centre_' + name), 1)} | {_fx(r['centre_market'], 1)} |")
        rg = sec["regimes"]
        L += ["", f"## {name}: regimes", "", "| Heat tercile (market centre, within market) | Excess | "
              "Market - model centre, F | Model bias, F | Market bias, F | top-decile days |",
              "| --- | --- | --- | --- | --- | --- |"]
        for k, r in rg["heat_tercile"].items():
            L.append(f"| {k} | {_x(r['excess_over_market'])} | {_x(r['market_minus_model_centre'], 2)} | "
                     f"{_x(r['centre_bias'], 2)} | {_x(r['centre_bias_market'], 2)} | {r['n_top_decile']} |")
        if rg["flags"]:
            L += ["", "| Flag | Freq top / all | FR [95%] | Top flagged / markets | Verdict |",
                  "| --- | --- | --- | --- | --- |"]
            for f, r in rg["flags"].items():
                L.append(f"| {f} | {_fx(r['freq_top'], 3)} / {_fx(r['freq_all'], 3)} | {_fx(r['FR'], 2)} "
                         f"[{_fx(r['FR_ci95'][0], 2)}, {_fx(r['FR_ci95'][1], 2)}] | {r['n_top_flagged']} / "
                         f"{r['n_markets_top_flagged']} | {r['verdict']} |")
        tm = sec["timing"]
        L += ["", f"## {name}: timing (arrival within {tm['tolerance_F']} F through 16:59)", "",
              f"- Top decile: market arrives {_fx(tm['top']['mean_arrival_market_h'], 2)} h, model "
              f"{_fx(tm['top']['mean_arrival_model_h'], 2)} h; lead {_x(tm['top']['lead'], 2)} h; "
              f"verdict {tm['verdict']}.",
              f"- All days: lead {_x(tm['all']['lead'], 2)} h; market first on "
              f"{_fx(tm['all']['frac_market_first'], 3)} of days."]
    for key, d in payload["deltas"].items():
        L += ["", f"## Delta: candidate {key.replace('_', ' ')} (positive = loss closed, {win})", "",
              f"- Candidate - base Brier: {_x(d['candidate_minus_base_brier'])}; MDE80 "
              f"{_fx(d['candidate_minus_base_brier'].get('mde80'))}",
              f"- Share of base excess closed: {_x(d['share_of_base_excess_closed'], pct=True)}% = centre "
              f"{_x(d['closed_in_centre_share'], pct=True)}% + width {_x(d['closed_in_width_share'], pct=True)}%",
              f"- Centre bias change {_x(d['centre_bias_change'], 2)} F; centre MAE change "
              f"{_x(d['centre_mae_change'], 2)} F",
              f"- Base top decile ({d['base_top_decile_n']} days): closed share "
              f"{_x(d['base_top_decile_closed_share'], pct=True)}%; share of all closure from it "
              f"{_x(d['share_of_closure_from_base_top_decile'], pct=True)}%", "",
              "| Slice | Closed excess | Share closed % |", "| --- | --- | --- |"]
        for k, r in d["heat_tercile"].items():
            L.append(f"| heat tercile {k} | {_x(r['closed_excess'])} | {_x(r['share_closed'], pct=True)} |")
        for k, r in d["per_market"].items():
            L.append(f"| {k} | {_x(r['closed_excess'])} | {_x(r['share_closed'], pct=True)} |")
        for k, r in d["per_hour"].items():
            L.append(f"| hour {k} | {_x(r['closed_excess'])} | {_x(r['share_closed'], pct=True)} |")
    return "\n".join(L) + "\n"


def _fx(x, digits=4):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{digits}f}"


# ----------------------------------------------------------------------------- regimes (L5 extractor, moved)

TS_RE = re.compile(rb'"captured_at_local":\s*"([^"]+)"')
TS_PREFIX = 800
WX_RE = re.compile(r"[-+]?(MI|BC|PR|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|PL|GR|GS|UP)*")
CEIL_RE = re.compile(r"(BKN|OVC|VV)(\d{3})")


def _ts_at(f, pos):
    f.seek(pos)
    m = TS_RE.search(f.read(TS_PREFIX))
    return dt.datetime.fromisoformat(m.group(1).decode()) if m else None


def _next_line_start(f, off, size):
    if off == 0:
        return 0
    f.seek(off - 1)
    f.readline()  # discarded, never parsed
    pos = f.tell()
    return pos if pos < size else None


def first_and_last_on_date(path, target):
    """(first record, last record captured on ``target``); only those two lines are parsed.

    Lines are located from the timestamp prefix alone, so no line captured after ``target`` is parsed.
    """
    size = Path(path).stat().st_size
    with open(path, "rb") as f:
        first_ts = _ts_at(f, 0)
        if first_ts is None or first_ts.date() > target:
            return None, None
        f.seek(0)
        first = json.loads(f.readline())
        lo, hi = 0, size
        while hi - lo > 2_000_000:
            mid = (lo + hi) // 2
            pos = _next_line_start(f, mid, size)
            if pos is None or pos >= hi:
                hi = mid
                continue
            ts = _ts_at(f, pos)
            if ts is not None and ts.date() <= target:
                lo = pos
            else:
                hi = mid
        best, pos = lo, lo
        while pos is not None and pos < size:
            ts = _ts_at(f, pos)
            if ts is None or ts.date() > target:
                break
            best = pos
            f.seek(pos)
            f.readline()
            pos = f.tell()
        f.seek(best)
        last = json.loads(f.readline())
    if dt.datetime.fromisoformat(last["captured_at_local"]).date() != target:
        raise data.LayoutError(f"{path}: last on-date line mismatch")
    return first, last


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def metar_features(rows):
    rows = sorted({r["datetime"]: r for r in rows if r.get("datetime")}.values(), key=lambda r: r["datetime"])
    out = {"n_metar": len(rows)}
    if not rows:
        return out
    hour = (lambda r: int(r["datetime"][11:13]))
    times = [dt.datetime.fromisoformat(r["datetime"]) for r in rows]
    shift = dew = False
    max_dir, max_dew = 0.0, 0.0
    for i, (ri, ti) in enumerate(zip(rows, times)):
        if hour(ri) > 15:
            continue
        for rj, tj in zip(rows[i + 1:], times[i + 1:]):
            if (tj - ti).total_seconds() > 3 * 3600 or hour(rj) > 15:
                break
            di, dj = _num(ri.get("wind_dir")), _num(rj.get("wind_dir"))
            si, sj = _num(ri.get("wind_speed")) or 0, _num(rj.get("wind_speed")) or 0
            if di is not None and dj is not None and si >= 6 and sj >= 6:
                d = abs((dj - di + 180) % 360 - 180)
                max_dir = max(max_dir, d)
                shift |= d >= 90
            pi, pj = _num(ri.get("dewpoint_native")), _num(rj.get("dewpoint_native"))
            if pi is not None and pj is not None:
                max_dew = max(max_dew, pi - pj)
                dew |= pi - pj >= 8
    out.update(max_dir_change=max_dir, max_dew_drop=max_dew, R1_frontal=bool(shift or dew))
    low, n_morning, precip, ceil_min = 0, 0, False, math.inf
    for r in rows:
        h = hour(r)
        body = (r.get("raw") or "").split(" RMK")[0].split()[2:]
        if 6 <= h <= 12:
            n_morning += 1
            ceils = [int(m.group(2)) * 100 for tok in body if (m := CEIL_RE.fullmatch(tok[:6]))]
            if ceils and min(ceils) <= 3000:
                low += 1
            if ceils:
                ceil_min = min(ceil_min, min(ceils))
        if h <= 15:
            for tok in body:
                if tok.startswith("VC") or not WX_RE.fullmatch(tok):
                    continue
                if any(code in tok for code in ("RA", "DZ", "TS", "SH", "GR")):
                    precip = True
    out.update(low_ceiling_frac=(low / n_morning) if n_morning else math.nan,
               R2_cloud=bool(n_morning and low / n_morning >= 0.5), R3_precip=precip,
               min_ceiling_06_12=ceil_min if math.isfinite(ceil_min) else math.nan)
    by_hour = {hour(r): float(r["temp_native"]) for r in rows if r.get("temp_native") is not None}
    lows = [v for h, v in by_hour.items() if h <= 8]
    out.update(obs_min_00_08=min(lows) if lows else math.nan, obs_t06=by_hour.get(6, math.nan),
               obs_t11=by_hour.get(11, math.nan))
    return out


def forecast_features(first, target):
    om = ((first.get("sources") or {}).get("open_meteo") or {}).get("data") or {}
    rows = [r for r in om.get("day_rows") or [] if str(r.get("valid_time", ""))[:10] == target.isoformat()]
    by_hour = {int(r["time"][:2]): r for r in rows if r.get("temp_native") is not None}
    lows = [float(r["temp_native"]) for h, r in by_hour.items() if h <= 8]
    morning = [h for h in range(6, 13) if h in by_hour]
    return {"fc_min_00_08": min(lows) if lows else math.nan,
            "fc_t06": float(by_hour[6]["temp_native"]) if 6 in by_hour else math.nan,
            "fc_t11": float(by_hour[11]["temp_native"]) if 11 in by_hour else math.nan,
            "fc_low_cloud_06_12": sum(float(by_hour[h].get("low_cloud") or 0) for h in morning) / max(1, len(morning)),
            "fc_precip_00_15": sum(float(r.get("precipitation") or 0) for h, r in by_hour.items() if h <= 15)}


def extract_regimes(replay_root, layout_root, first_date="2026-08-15"):
    """Per market-day regime features from captured replay inputs (lane L5 ``extract_regimes``)."""
    screen_input_path(replay_root, "replay root")
    manifest, _ = data._read_manifest(layout_root)
    data._guard_manifest_dates(manifest)
    snaps, _ = data._read_verified(layout_root, data.SNAPSHOTS_FILE, manifest)
    snaps = snaps[["market", "date", "event_slug"]].drop_duplicates()
    snaps = snaps[(snaps.date >= first_date) & (snaps.date <= data.DEV_LAST.isoformat())]
    recs = []
    for r in snaps.sort_values(["date", "market"]).itertuples():
        target = dt.date.fromisoformat(r.date)
        if target > data.DEV_LAST:
            raise data.Refused("refused: date after 2026-09-29")
        path = Path(replay_root) / r.event_slug / "replay_inputs.jsonl"
        rec = {"market": r.market, "date": r.date}
        if not path.exists():
            recs.append({**rec, "status": "missing_folder"})
            continue
        first, last = first_and_last_on_date(path, target)
        if first is None:
            recs.append({**rec, "status": "no_on_date_line"})
            continue
        metar = ((last.get("sources") or {}).get("metar") or {}).get("data") or {}
        rec.update(status="ok", last_captured_local=last["captured_at_local"])
        rec.update(metar_features(metar.get("rows") or []))
        rec.update(forecast_features(first, target))
        recs.append(rec)
    df = pd.DataFrame(recs)
    for col in ("fc_min_00_08", "obs_min_00_08", "obs_t11", "obs_t06", "fc_t11", "fc_t06"):
        if col not in df:
            df[col] = np.nan
    df["overnight_low_gap"] = df.fc_min_00_08 - df.obs_min_00_08
    df["R4_low_gap"] = df.overnight_low_gap.abs() >= 3
    df["tendency_anomaly"] = (df.obs_t11 - df.obs_t06) - (df.fc_t11 - df.fc_t06)
    df["R6_tendency"] = df.tendency_anomaly.abs() >= 3
    return df


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.reporting.scorecards.loss_atlas",
                                     description="Loss atlas on the development window (dates <= 2026-09-29).")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("atlas", help="positive control, then the atlas for one candidate")
    a.add_argument("--layout", required=True)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--candidate", choices=("served", "market", "mg1"))
    g.add_argument("--candidate-module")
    g.add_argument("--candidate-vectors")
    g.add_argument("--candidate-distributions")
    a.add_argument("--trained-through")
    a.add_argument("--no-training", action="store_true")
    a.add_argument("--regimes", help="parquet from the 'regimes' subcommand (R1-R4, R6 flags)")
    a.add_argument("--window", default="07-12", help="local-hour window HH-HH (default 07-12)")
    a.add_argument("--out", required=True)
    r = sub.add_parser("regimes", help="per market-day regime flags from captured replay inputs (L5)")
    r.add_argument("--replay-root", required=True)
    r.add_argument("--layout", required=True)
    r.add_argument("--first-date", default="2026-08-15")
    r.add_argument("--out", required=True)
    return parser


def _spec(args):
    if args.candidate:
        return data.CandidateSpec(args.candidate)
    if args.candidate_module:
        return data.CandidateSpec("module", args.candidate_module)
    kind, path = (("vectors", args.candidate_vectors) if args.candidate_vectors
                  else ("distributions", args.candidate_distributions))
    return data.CandidateSpec(kind, path, args.trained_through, args.no_training)


def _window(text):
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", text)
    if not m or not 0 <= int(m.group(1)) <= int(m.group(2)) <= 23:
        raise data.Refused(f"refused: --window must be HH-HH within 00-23, got {text!r}")
    return int(m.group(1)), int(m.group(2))


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "regimes":
            if data.parse_date(args.first_date) > data.DEV_LAST:
                raise data.Refused("refused: --first-date after 2026-09-29")
            df = extract_regimes(args.replay_root, args.layout, args.first_date)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(args.out, index=False)
            print(json.dumps({"out": str(args.out), "sha256": data.sha256_file(args.out),
                              "status": df.status.value_counts().to_dict()}))
            return 0
        payload = run_atlas(args.layout, _spec(args), args.regimes, _window(args.window))
        sha, json_path, md_path = sc.write_outputs(payload, args.out, atlas_markdown)
        print(json.dumps({"sha256": sha, "json": str(json_path), "md": str(md_path),
                          "positive_control": payload["positive_control"]["verdict"]}))
        return 0
    except (data.Refused, data.LayoutError, data.LeakageError, data.WalkForwardError) as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
