"""Master ruling (b): the post-look serial-correlation analysis of B's forward per-date data.

Descriptive only. It never alters B's verdict. It reads B's own decision (the ``decision`` object of
``b_look.json``, or that object alone) and a per-date table for the primary range 07-16, then reports:

- lag-1 rho on the linearised per-date residual e_t = (S_t - delta * n_t) / n_bar, pairing only consecutive
  calendar dates;
- rho_used = min(0.9, max(rho_hat, 0.22));
- VIF = max(1, (1 + rho_used) / (1 - rho_used), block-3 ratio ** 2), with the block-3 ratio computed on e_t
  and re-centred (row 84's fix);
- U_adj = delta + t(0.975, n - 1) * SD(e) / sqrt(n) * sqrt(VIF), centred on B's printed delta;
- the fragile labels: "PASS, fragile under serial correlation" iff B PASS and U_adj >= 0; "NOT-WORSE, fragile"
  iff B's INCONCLUSIVE carries NOT-WORSE and U_adj >= +0.0027; FAIL and other INCONCLUSIVE pass through.

The parameters are master's, verbatim, in
``docs/research/b-look-prep-2026-10-31/master-ruling-b-post-look.md``. The optional 07-12 / 13-16 per-date tables
feed a VAR(1) fit that is descriptive only and never decides anything.

Implementation choices the ruling leaves open (each disclosed in the note):

- rho_hat = mean over consecutive-date pairs of (e_t - e_bar)(e_{t+1} - e_bar), divided by the population
  (ddof 0) variance of e. Gaps break pairs; nothing is interpolated.
- The block-3 ratio squared is the exact (no resampling) moving-block bootstrap variance of the mean, re-centred
  on the blocks' own mean, over the iid variance: 3 * var(block means) / var(e), both ddof 0, blocks of three
  consecutive entries of the date-ordered series (gaps ignored for blocks).
- SD(e) uses ddof 1; t is Student's t at 0.975 with n - 1 degrees of freedom.
- Refusals: fewer than MIN_DATES dates, fewer than MIN_PAIRS consecutive pairs, a duplicate or unparsable date, a
  cell count that is not a positive integer, a non-finite value, zero residual variance, a delta that is not
  sum(S) / sum(n) within DELTA_TOL (B's estimate is that cell mean), or a B verdict other than PASS, FAIL or
  INCONCLUSIVE. FAIL and INCONCLUSIVE-without-NOT-WORSE still get the numbers; their verdict passes through.

It imports nothing from B's bound files and reads no data of its own: the caller supplies both inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

SCHEMA = "b_post_look_serial_v1"
RHO_FLOOR = 0.22
RHO_CAP = 0.9
BLOCK = 3
MARGIN = 0.0027
T_LEVEL = 0.975
MIN_DATES = 3
MIN_PAIRS = 2
DELTA_TOL = 1e-9
PASS_FRAGILE = "PASS, fragile under serial correlation"
NOT_WORSE_FRAGILE = "NOT-WORSE, fragile"
SPLIT_NAMES = ("07-12", "13-16")


class PostLookRefused(ValueError):
    """The inputs cannot carry ruling (b)'s analysis; nothing is reported."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- inputs

def _finite(value, what):
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise PostLookRefused(f"{what} is not a number: {value!r}") from None
    if not math.isfinite(out):
        raise PostLookRefused(f"{what} is not finite: {value!r}")
    return out


def per_date_rows(rows):
    """Validate and date-order ``[{"date": "YYYY-MM-DD", "S": float, "n": int}, ...]``."""
    out, seen = [], set()
    for i, row in enumerate(rows):
        try:
            d = date.fromisoformat(str(row["date"]))
        except (KeyError, TypeError, ValueError):
            raise PostLookRefused(f"row {i} has no ISO date: {row!r}") from None
        if d in seen:
            raise PostLookRefused(f"date {d} repeats")
        seen.add(d)
        n = row.get("n")
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise PostLookRefused(f"date {d} has cell count {n!r}, not a positive integer")
        out.append((d, _finite(row.get("S"), f"S on {d}"), n))
    out.sort()
    if len(out) < MIN_DATES:
        raise PostLookRefused(f"{len(out)} dates; at least {MIN_DATES} are needed")
    return out


def per_date_from_cells(cells):
    """Sum ``[{"date", "diff"}, ...]`` cell differences (arm minus market Brier per cell) into per-date rows."""
    acc = {}
    for i, cell in enumerate(cells):
        key = str(cell.get("date"))
        s, n = acc.get(key, (0.0, 0))
        acc[key] = (s + _finite(cell.get("diff"), f"cell {i} diff"), n + 1)
    return [{"date": k, "S": s, "n": n} for k, (s, n) in acc.items()]


def b_decision(payload):
    """B's decision object: ``b_look.json`` (its ``decision`` key) or the decision itself."""
    if not isinstance(payload, dict):
        raise PostLookRefused("B's look output is not an object")
    decision = payload.get("decision", payload)
    if not isinstance(decision, dict):
        raise PostLookRefused("B's decision is not an object")
    verdict = decision.get("verdict")
    if verdict not in ("PASS", "FAIL", "INCONCLUSIVE"):
        raise PostLookRefused(f"B's verdict is {verdict!r}; ruling (b) applies only to PASS, FAIL or INCONCLUSIVE")
    return decision


# ----------------------------------------------------------------------------- statistics

def linearised(rows, delta):
    """e_t = (S_t - delta * n_t) / n_bar, in date order."""
    n_bar = sum(n for _, _, n in rows) / len(rows)
    return [(s - delta * n) / n_bar for _, s, n in rows], n_bar


def _mean(xs):
    return sum(xs) / len(xs)


def _var0(xs):
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)


def lag1_rho(dates, e):
    """Lag-1 autocorrelation pairing only consecutive calendar dates; returns (rho_hat, n_pairs)."""
    m = _mean(e)
    pairs = [(e[i] - m) * (e[i + 1] - m) for i in range(len(e) - 1) if dates[i + 1] - dates[i] == timedelta(days=1)]
    if len(pairs) < MIN_PAIRS:
        raise PostLookRefused(f"{len(pairs)} consecutive-date pairs; at least {MIN_PAIRS} are needed")
    v = _var0(e)
    if v <= 0:
        raise PostLookRefused("the linearised residual has zero variance")
    return (sum(pairs) / len(pairs)) / v, len(pairs)


def block_ratio_sq(e, block=BLOCK):
    """Exact re-centred moving-block bootstrap variance of the mean over the iid variance (both ddof 0)."""
    v = _var0(e)
    if v <= 0:
        raise PostLookRefused("the linearised residual has zero variance")
    means = [_mean(e[i:i + block]) for i in range(len(e) - block + 1)]
    return block * _var0(means) / v


def t_quantile(df, level=T_LEVEL):
    from scipy.stats import t

    return float(t.ppf(level, df))


def var1_descriptive(ranges):
    """VAR(1) on the stacked linearised residuals of several ranges (descriptive only).

    ``ranges`` maps a range name to its validated per-date rows; only dates every range has are used, and only
    consecutive-date pairs enter the fit. Each range is linearised on its own cell mean sum(S) / sum(n).
    """
    import numpy as np

    names = list(ranges)
    common = sorted(set.intersection(*({d for d, _, _ in rows} for rows in ranges.values())))
    keep = set(common)
    series = {}
    for name in names:
        rows = [r for r in ranges[name] if r[0] in keep]
        delta = sum(s for _, s, _ in rows) / sum(n for _, _, n in rows)
        series[name], _ = linearised(rows, delta)
    x = np.array([series[name] for name in names]).T
    idx = [i for i in range(len(common) - 1) if common[i + 1] - common[i] == timedelta(days=1)]
    if len(idx) <= len(names) + 1:
        return {"status": "not_fitted", "reason": f"{len(idx)} consecutive common-date pairs", "ranges": names}
    xc = x - x.mean(axis=0)
    lagged, lead = xc[idx], xc[[i + 1 for i in idx]]
    coef, *_ = np.linalg.lstsq(lagged, lead, rcond=None)
    a = coef.T
    resid = lead - lagged @ coef
    q = resid.T @ resid / len(idx)
    sd = xc.std(axis=0)
    corr = np.corrcoef(xc.T)
    return {"status": "fitted", "ranges": names, "n_dates": len(common), "n_pairs": len(idx),
            "A": a.tolist(), "diagonal": {n: float(a[i, i]) for i, n in enumerate(names)},
            "sd": {n: float(sd[i]) for i, n in enumerate(names)},
            "correlation": corr.tolist(), "innovation_cov_min_eigenvalue": float(np.linalg.eigvalsh(q).min())}


# ----------------------------------------------------------------------------- the analysis

def fragile_label(decision, u_adj, margin=MARGIN):
    verdict = decision["verdict"]
    if verdict == "PASS":
        return PASS_FRAGILE if u_adj >= 0 else None
    if verdict == "INCONCLUSIVE" and decision.get("label") == "NOT-WORSE":
        return NOT_WORSE_FRAGILE if u_adj >= margin else None
    return None


def analyse(primary_rows, b_look, split_rows=None):
    """Ruling (b) on B's printed decision and the 07-16 per-date table; B's verdict is copied, never changed."""
    decision = b_decision(b_look)
    delta = _finite(decision.get("estimate"), "B's estimate")
    rows = per_date_rows(primary_rows)
    cell_mean = sum(s for _, s, _ in rows) / sum(n for _, _, n in rows)
    if abs(cell_mean - delta) > DELTA_TOL * max(1.0, abs(delta)):
        raise PostLookRefused(f"B's estimate {delta!r} is not the table's cell mean {cell_mean!r}")
    dates = [d for d, _, _ in rows]
    e, n_bar = linearised(rows, delta)
    n = len(e)
    rho_hat, n_pairs = lag1_rho(dates, e)
    rho_used = min(RHO_CAP, max(rho_hat, RHO_FLOOR))
    vif_ar1 = (1 + rho_used) / (1 - rho_used)
    ratio_sq = block_ratio_sq(e)
    vif = max(1.0, vif_ar1, ratio_sq)
    sd_e = math.sqrt(sum((x - _mean(e)) ** 2 for x in e) / (n - 1))
    t_q = t_quantile(n - 1)
    u_adj = delta + t_q * sd_e / math.sqrt(n) * math.sqrt(vif)
    out = {
        "schema": SCHEMA, "module_sha256": module_sha256(), "role": "descriptive post-look; B's verdict unchanged",
        "b_verdict": decision["verdict"], "b_label": decision.get("label"), "b_estimate": delta,
        "b_ci95": decision.get("ci95"), "fragile_label": fragile_label(decision, u_adj),
        "n_dates": n, "first_date": dates[0].isoformat(), "last_date": dates[-1].isoformat(),
        "n_bar": n_bar, "n_pairs": n_pairs, "rho_hat": rho_hat, "rho_used": rho_used,
        "rho_floor": RHO_FLOOR, "rho_cap": RHO_CAP,
        "vif": {"ar1": vif_ar1, "block3_ratio_sq": ratio_sq, "used": vif},
        "sd_e": sd_e, "t_quantile": t_q, "t_df": n - 1, "u_adj": u_adj, "margin": MARGIN,
    }
    if split_rows:
        ranges = {"07-16": rows}
        for name in SPLIT_NAMES:
            if name in split_rows:
                ranges[name] = per_date_rows(split_rows[name])
        out["var1_descriptive"] = var1_descriptive(ranges) if len(ranges) > 1 else None
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-date", required=True, type=Path,
                        help='JSON {"primary": [{"date","S","n"}...], "splits": {"07-12": [...], "13-16": [...]}}')
    parser.add_argument("--b-look", required=True, type=Path, help="B's b_look.json (or its decision object)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"refused: {args.out} exists")
    per_date = json.loads(args.per_date.read_text(encoding="utf-8"))
    try:
        result = analyse(per_date["primary"], json.loads(args.b_look.read_text(encoding="utf-8")),
                         per_date.get("splits"))
    except (PostLookRefused, KeyError) as exc:
        raise SystemExit(f"refused: {exc}") from None
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("b_verdict", "b_label", "fragile_label", "rho_hat", "rho_used",
                                             "u_adj")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
