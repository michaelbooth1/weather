"""Lane L5 subset scores: paired candidate-minus-control (and minus served) on pre-declared subsets.

Research only, offline, development dates <= 2026-09-29 (the dev scorecard's own guards apply: this
module calls its layout loader, fold scheme, Table and module walk-forward unchanged). Never imported by
capture, serving or trading code; importing it from ``weather.model``/``weather.market``/collection paths is
refused below. Pre-registration: ``docs/research/l5-hot-day-centre-preregistration-2026-10-24.md``.

    python -m weather.calibration.l5_subset_scores --layout C:\\swarm\\v3layout \\
        --candidate-module <file> --control-module <file> --top-list <json> --out <json>

Subsets (07-12 local unless stated): pooled, per local hour 07..12, the L5 top-decile market-days (fixed list
from the L5 diagnosis result), hot days (within-market top tercile of the 07-12 mean captured v2_mean over the
scored dates, ex ante), and each market. Intervals: the scorecard's crossed date x market weights restricted
to the subset's cells (crossed) and a date-only matrix (date-clustered).
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

for _frame in inspect.stack()[1:]:
    _mod = str(_frame.frame.f_globals.get("__name__", ""))
    if _mod.startswith(("weather.model", "weather.market", "weather.collection", "weather.maker_core")):
        raise ImportError("weather.calibration.l5_subset_scores is research-only; production import refused")

from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402

W_LO, W_HI = 7, 12


def vectors(layout_root, cand_path, ctl_path):
    start, end = data.check_range("2026-08-01", "2026-09-29")
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(layout, scored)
    out = {}
    for name, path in (("candidate", cand_path), ("control", ctl_path)):
        frame, meta = data.module_predictions(data.CandidateSpec("module", path), layout, folds)
        p, reasons = table.candidate_vector(frame)
        out[name] = (p, meta, reasons)
    return table, out


def interval(w, a):
    a = np.asarray(a, float)
    point = float(a.mean())
    den = w.sum(axis=1).astype(float)
    boot = np.divide(w @ a, den, out=np.full(len(den), np.nan), where=den > 0)
    boot = boot[np.isfinite(boot)]
    return {"estimate": point, "ci95": [float(x) for x in np.quantile(boot, [.025, .975])]}


def run(layout_root, cand_path, ctl_path, top_list_path):
    table, vec = vectors(layout_root, cand_path, ctl_path)
    bc, bk, bs = table.brier(vec["candidate"][0]), table.brier(vec["control"][0]), table.brier(table.p_served)
    hour = table.local_hour
    keys = table.keys
    dates = np.array([k[0] for k in keys])
    markets = np.array([k[1] for k in keys])
    w_cross = table.w
    w_date = sc.crossed_weights(list(dates), ["all"] * len(keys))
    top = {(r["date"], r["market"]) for r in json.loads(Path(top_list_path).read_text())}
    v2 = pd.to_numeric(table.snaps.v2_mean, errors="coerce").to_numpy(float)
    inW = (hour >= W_LO) & (hour <= W_HI)
    _, v2c = table.cells(np.nan_to_num(v2, nan=0.0), inW & np.isfinite(v2))
    idx_v2, _ = table.cells(np.nan_to_num(v2, nan=0.0), inW & np.isfinite(v2))
    v2cell = pd.Series(np.nan, index=range(len(keys)))
    v2cell[idx_v2] = v2c
    terc = v2cell.groupby(markets).transform(lambda s: s.rank(pct=True))
    hot = (terc > 2 / 3).to_numpy()
    subsets = {"07-12 pooled": (inW, np.ones(len(keys), bool))}
    for h in range(W_LO, W_HI + 1):
        subsets[f"h{h:02d}"] = (hour == h, np.ones(len(keys), bool))
    subsets["07-12 top-decile (L5 list)"] = (inW, np.array([k in top for k in keys]))
    subsets["07-12 hot days (top v2 tercile per market)"] = (inW, hot)
    coastal = {"san-francisco", "los-angeles", "seattle", "nyc", "miami"}
    subsets["07-12 coastal five (AFD screen)"] = (inW, np.isin(markets, list(coastal)))
    for m in sorted(set(markets)):
        subsets[f"07-12 {m}"] = (inW, markets == m)
    rows = []
    for name, (snap_mask, cell_mask) in subsets.items():
        idx, c = table.cells(bc, snap_mask)
        _, k = table.cells(bk, snap_mask)
        _, s = table.cells(bs, snap_mask)
        keep = cell_mask[idx]
        idx, c, k, s = idx[keep], c[keep], k[keep], s[keep]
        wc, wd = w_cross[:, idx], w_date[:, idx]
        rows.append({"subset": name, "n_market_days": int(len(idx)), "n_dates": int(len(set(dates[idx]))),
                     "n_markets": int(len(set(markets[idx]))),
                     "cand_minus_control_crossed": interval(wc, c - k),
                     "cand_minus_control_date": interval(wd, c - k),
                     "cand_minus_served_crossed": interval(wc, c - s),
                     "cand_minus_served_date": interval(wd, c - s),
                     "control_minus_served_crossed": interval(wc, k - s)})
    return {"schema": "l5_subset_scores/1", "evidence_class": "development",
            "candidate": vec["candidate"][1], "control": vec["control"][1],
            "candidate_coverage": vec["candidate"][2], "control_coverage": vec["control"][2],
            "top_list_sha256": hashlib.sha256(Path(top_list_path).read_bytes()).hexdigest(),
            "layout_manifest_sha256": table.snaps.attrs.get("manifest_sha256"), "rows": rows}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m weather.calibration.l5_subset_scores")
    p.add_argument("--layout", required=True)
    p.add_argument("--candidate-module", required=True)
    p.add_argument("--control-module", required=True)
    p.add_argument("--top-list", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    res = run(a.layout, a.candidate_module, a.control_module, a.top_list)
    body = sc.canonical_bytes(res)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(body)
    print(json.dumps({"sha256": hashlib.sha256(body).hexdigest(), "out": a.out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
