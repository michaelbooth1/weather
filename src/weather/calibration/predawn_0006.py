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
    args = parser.parse_args(argv)
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
