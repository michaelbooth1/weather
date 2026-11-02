"""Lane L47 (close-the-gap 2026-11-01): shape / confidence research on the 07-12 arms. Research only.

``step0``: DESCRIPTIVE, existing R-H atlas inputs only (dev 2026-08-01..09-29; nothing later is opened). It splits
the arms' surplus mass two or more bands from the winner by side (below / above) and by market predictability
(terciles of the capture-time market's own spread), and decomposes the arm-vs-market position pattern through a
chain of Gaussian stand-ins:

  S1 market (as priced)                          -> the reference
  S2 Gaussian(mu_mkt, sd_mkt)                    -> how Gaussian the market itself is
  S3m Gaussian(mu_mkt, c * sd_mkt)               -> (i) global multiplicative width, c pooled
  S3a Gaussian(mu_mkt, sqrt(sd_mkt^2 + k^2))     -> (i') global additive width (a worse, day-blind centre)
  S4 Gaussian(mu_mkt, sd_arm)                    -> (ii) the arm's own day-specific width
  S5 Gaussian(mu_arm, sd_arm)                    -> + the arm's centre
  S6 arm (as emitted)                            -> (iii) + the arm's shape (skew, tails, climatology mix)

All moments are in band-index units on each snapshot's own bands. Every stand-in is rule-4 floor-masked and
renormalised exactly as the scorecard masks a candidate. Selection evidence only: no new candidate is scored.

This module imports the B-bound modules read-only (``mg2_composite``, ``r0_ols_floor_challenger``, the dev
scorecard, ``l6_stack``) and never edits them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

NAME = "shape_confidence_l47"
STEP0_SCHEMA = "l47_step0/1"
STEP0_LABEL = ("SELECTION EVIDENCE - L47 step 0, descriptive, R-H atlas inputs (dev 2026-08-01..09-29, capture-time "
               "market p_market_yes); no new candidate scored; no edge claim")
RH_RANGE = ("2026-08-01", "2026-09-29")
WINDOWS = (("07-12", 7, 12), ("13-16", 13, 16))
RH_P3D_SHA256 = ("cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542",
                 "abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109")
RH_L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"
RH_L6_NOWCAST_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"
RH_LAYOUT_MANIFEST_SHA256 = "4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22"
# R-H atlas position masses at 07-12 (rh_atlas.json ff7ee231...), reproduced as a check
RH_POSITIONS_0712 = {"P3d_N_fix": (0.0389, 0.0845, 0.2000, 0.2925, 0.2248, 0.1066, 0.0527),
                     "L6": (0.0312, 0.0839, 0.2202, 0.3248, 0.2088, 0.0867, 0.0444),
                     "market": (0.0208, 0.0624, 0.2258, 0.4148, 0.2204, 0.0571, 0.0201)}
POSITION_CLASSES = ("<=-3", "-2", "-1", "0", "+1", "+2", ">=+3")


class L47Error(RuntimeError):
    pass


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _seg(values, offsets):
    import numpy as np

    return np.add.reduceat(values, offsets)


def moments(p, idx, offsets, n):
    """Per-snapshot normalised mean, sd and standardised skew of band index under p."""
    import numpy as np

    tot = _seg(p, offsets)
    tot = np.where(tot > 0, tot, 1.0)
    rep = np.repeat(tot, n)
    q = p / rep
    mu = _seg(q * idx, offsets)
    d = idx - np.repeat(mu, n)
    var = _seg(q * d * d, offsets)
    sd = np.sqrt(np.maximum(var, 1e-12))
    skew = _seg(q * d ** 3, offsets) / sd ** 3
    return mu, sd, skew


def gaussian_bands(mu, sd, idx, n, impossible, band_snap, n_snaps):
    """Discretised Gaussian on each snapshot's bands (band k = [k-.5, k+.5], open end bands), floor-masked."""
    import numpy as np
    from scipy.special import ndtr

    m = np.repeat(mu, n)
    s = np.repeat(np.maximum(sd, 1e-6), n)
    first = np.zeros(len(idx), bool)
    last = np.zeros(len(idx), bool)
    starts = np.concatenate([[0], np.cumsum(n)[:-1]])
    first[starts] = True
    last[starts + n - 1] = True
    up = np.where(last, np.inf, idx + 0.5)
    lo = np.where(first, -np.inf, idx - 0.5)
    p = ndtr((up - m) / s) - ndtr((lo - m) / s)
    p = np.where(impossible, 0.0, p)
    tot = np.bincount(band_snap, weights=p, minlength=n_snaps)
    return p / np.where(tot > 0, tot, 1.0)[band_snap]


def _positions(p, cls, band_snap, n_snaps, mask):
    import numpy as np

    out = []
    for k in range(len(POSITION_CLASSES)):
        mass = np.bincount(band_snap, weights=np.where(cls == k, p, 0.0), minlength=n_snaps)
        out.append(float(mass[mask].mean()))
    return out


def _summary(pos):
    """below2 = <=-2, above2 = >=+2 masses; winner; one-away each side."""
    return {"below2": pos[0] + pos[1], "minus1": pos[2], "winner": pos[3], "plus1": pos[4],
            "above2": pos[5] + pos[6]}


def _excess(table, p, mask, b_mkt):
    import numpy as np

    from weather.reporting.scorecards import dev_scorecard as sc

    idx, c = table.cells(table.brier(p), mask)
    _, m = table.cells(b_mkt, mask)
    est = sc.ratio_interval(table.w_date[:, idx], c - m, np.ones(len(idx)))
    return {"estimate": est["estimate"], "ci95": est["ci95"], "n_market_days": int(len(idx)),
            "n_snapshots": int(mask.sum())}


def _spearman(a, b):
    import numpy as np
    from scipy.stats import spearmanr

    ok = np.isfinite(a) & np.isfinite(b)
    return float(spearmanr(a[ok], b[ok]).statistic) if ok.sum() > 2 else None


def build_arms(*, layout, coefficients, nowcasts, p3d_files, work):
    """R-H's table and the two arm vectors, refused unless the inputs are R-H's."""
    from weather.calibration import mg2_composite as mg2
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    import pandas as pd

    if sha256_file(nowcasts) != RH_L6_NOWCAST_SHA256:
        raise L47Error("L6 nowcasts are not R-H's")
    if sorted(sha256_file(f) for f in p3d_files) != sorted(RH_P3D_SHA256):
        raise L47Error("P3d_N emissions are not R-H's")
    part = mg2.load_part(coefficients, "l6", RH_L6_PART_SHA256)
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    state = {"coef": {int(h): tuple(v) for h, v in part["coef"].items()}, "column": part["column"]}
    start, end = data.check_range(*RH_RANGE)
    lay = data.load_layout(layout, data.DEV_FIRST, end)
    if lay.manifest_sha256 != RH_LAYOUT_MANIFEST_SHA256:
        raise L47Error(f"layout manifest {lay.manifest_sha256} is not R-H's")
    folds = data.make_folds(lay.dates, start, end, 7, 1, 7)
    dates = sorted(d for d in {str(x) for x in lay.dates} if RH_RANGE[0] <= d <= RH_RANGE[1])
    if dates[-1] > RH_RANGE[1]:
        raise L47Error("a date after 2026-09-29 entered the table")
    table = sc.Table(lay, dates)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    combined = work / "dev_P3d_N_fix_07_16.jsonl"
    combined.write_bytes(b"".join(Path(f).read_bytes() for f in p3d_files))
    p_fix, cov_fix, _ = l3._vector(table, l3._candidate_frame(str(combined), table, lay, folds, data)[0])
    combined.unlink()
    snaps_floor = table.snaps.assign(floor=table.snaps[list(data.FLOOR_FIELDS)].apply(
        pd.to_numeric, errors="coerce").max(axis=1))
    p_l6, cov_l6, _ = l3._vector(table, l6_stack.predict(state, snaps_floor, table.bands))
    return table, {"P3d_N_fix": p_fix, "L6": p_l6}, cov_fix & cov_l6, {
        "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
        "dates": [dates[0], dates[-1], len(dates)]}


def step0(*, layout, coefficients, nowcasts, p3d_files, out):
    import numpy as np

    out = Path(out)
    if out.exists():
        raise L47Error(f"refusing to overwrite {out}")
    table, arms, common, meta = build_arms(layout=layout, coefficients=coefficients, nowcasts=nowcasts,
                                           p3d_files=p3d_files, work=out.parent)
    offsets, n, band_snap = table.offsets, table.n, table.band_snap
    n_snaps = len(table.snaps)
    idx = table.bands.band_index.to_numpy(float)
    winner = _seg(table.y * idx, offsets)
    cls = (np.clip(idx - np.repeat(winner, n), -3, 3) + 3).astype(int)
    p_mkt = table.p_market
    b_mkt = table.brier(p_mkt)
    mu_q, sd_q, sk_q = moments(p_mkt, idx, offsets, n)
    hours = table.local_hour
    result = {"schema": STEP0_SCHEMA, "label": STEP0_LABEL, "inputs": dict(meta, module_sha256=sha256_file(__file__),
                                                                         p3d_files={str(f): sha256_file(f)
                                                                                    for f in p3d_files}),
              "windows": {}}
    for window, lo, hi in WINDOWS:
        in_w = common & (hours >= lo) & (hours <= hi)
        cuts = np.quantile(sd_q[in_w], [1 / 3, 2 / 3])
        terc = np.digitize(sd_q, cuts)  # 0 = sharpest market (most predictable)
        wres = {"n_snapshots": int(in_w.sum()), "market_sd_tercile_cuts": cuts.tolist(), "arms": {}}
        for arm, p in arms.items():
            if window == "13-16" and arm == "L6":
                continue  # L6 is MG-1 at 13-16; not part of this lane's question
            mu_p, sd_p, sk_p = moments(p, idx, offsets, n)
            m = in_w
            c_mult = float(np.sqrt(np.mean(sd_p[m] ** 2) / np.mean(sd_q[m] ** 2)))
            k2 = float(max(np.mean(sd_p[m] ** 2 - sd_q[m] ** 2), 0.0))
            gauss = lambda mu, sd: gaussian_bands(mu, sd, idx, n, table.impossible, band_snap, n_snaps)  # noqa: E731
            stand_ins = {
                "S1_market": p_mkt,
                "S2_gauss_market": gauss(mu_q, sd_q),
                "S3m_global_mult": gauss(mu_q, c_mult * sd_q),
                "S3a_global_add": gauss(mu_q, np.sqrt(sd_q ** 2 + k2)),
                "S4_arm_width_mkt_centre": gauss(mu_q, sd_p),
                "S5_arm_width_arm_centre": gauss(mu_p, sd_p),
                "S6_arm": p,
            }
            err_q = np.abs(winner - mu_q)
            err_p = np.abs(winner - mu_p)
            ares = {"global_width": {"c_mult": c_mult, "k_add": float(np.sqrt(k2))},
                    "pooled": {}, "by_market_sd_tercile": [], "by_market": {}}

            def block(mask):
                b = {"n_snapshots": int(mask.sum()),
                     "sd_market_mean": float(sd_q[mask].mean()), "sd_arm_mean": float(sd_p[mask].mean()),
                     "sd_ratio_mean": float((sd_p[mask] / sd_q[mask]).mean()),
                     "centre_offset_mean": float((mu_p - mu_q)[mask].mean()),
                     "centre_offset_abs_mean": float(np.abs(mu_p - mu_q)[mask].mean()),
                     "skew_market_mean": float(sk_q[mask].mean()), "skew_arm_mean": float(sk_p[mask].mean()),
                     "abs_err_market_mean": float(err_q[mask].mean()), "abs_err_arm_mean": float(err_p[mask].mean()),
                     "stand_ins": {}}
                for name, v in stand_ins.items():
                    pos = _positions(v, cls, band_snap, n_snaps, mask)
                    entry = {"positions": pos, **_summary(pos)}
                    if name != "S1_market":
                        entry["excess_vs_market"] = _excess(table, v, mask, b_mkt)
                    b["stand_ins"][name] = entry
                return b

            ares["pooled"] = block(m)
            ares["pooled"]["spread_skill"] = {
                "spearman_sd_market_vs_abs_err_market": _spearman(sd_q[m], err_q[m]),
                "spearman_sd_arm_vs_abs_err_arm": _spearman(sd_p[m], err_p[m]),
                "spearman_sd_arm_vs_sd_market": _spearman(sd_p[m], sd_q[m]),
                "ols_sd_arm_on_sd_market": np.polyfit(sd_q[m], sd_p[m], 1).tolist()}
            for t in range(3):
                ares["by_market_sd_tercile"].append(dict(tercile=t, **block(m & (terc == t))))
            for mk in sorted(set(table.markets[m])):
                ares["by_market"][mk] = block(m & (table.markets == mk))
            if window == "07-12":
                got = [round(x, 4) for x in ares["pooled"]["stand_ins"]["S6_arm"]["positions"]]
                want = list(RH_POSITIONS_0712[arm])
                got_m = [round(x, 4) for x in ares["pooled"]["stand_ins"]["S1_market"]["positions"]]
                ares["rh_reproduction"] = {"arm": got == want, "market": got_m == list(RH_POSITIONS_0712["market"]),
                                           "got": got, "want": want}
            wres["arms"][arm] = ares
        result["windows"][window] = wres
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def build_parser():
    ap = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s0 = sub.add_parser("step0", help="descriptive shape/confidence split on R-H's dev inputs")
    s0.add_argument("--layout", required=True)
    s0.add_argument("--coefficients", required=True)
    s0.add_argument("--nowcasts", required=True)
    s0.add_argument("--p3d", nargs="+", required=True)
    s0.add_argument("--out", required=True)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "step0":
        res = step0(layout=args.layout, coefficients=args.coefficients, nowcasts=args.nowcasts,
                    p3d_files=[Path(f) for f in args.p3d], out=args.out)
        print(json.dumps({w: {a: r.get("rh_reproduction") for a, r in v["arms"].items()}
                          for w, v in res["windows"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
