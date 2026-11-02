"""Lane L47 step 0b: order-robustness of the step-0 decomposition (DESCRIPTIVE, R-H dev inputs only).

Step 0 (``shape_confidence_l47 step0``) walks market -> width -> centre -> shape. This walks the centre first:

  S2  Gaussian(mu_mkt, sd_mkt)
  C3  Gaussian(mu_arm, sd_mkt)        -> the arm's centre at the market's width
  C3m Gaussian(mu_arm, c * sd_mkt)    -> + global multiplicative width (c pooled per arm and window)
  S5  Gaussian(mu_arm, sd_arm)        -> + the arm's own day-specific width
  S6  arm

and reports the same blocks (pooled, market-sd terciles). Selection evidence only; no new candidate is scored.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from weather.calibration import shape_confidence_l47 as s0

NAME = "shape_confidence_l47_order"
SCHEMA = "l47_step0b/1"


def step0b(*, layout, coefficients, nowcasts, p3d_files, out):
    import numpy as np

    out = Path(out)
    if out.exists():
        raise s0.L47Error(f"refusing to overwrite {out}")
    table, arms, common, meta = s0.build_arms(layout=layout, coefficients=coefficients, nowcasts=nowcasts,
                                              p3d_files=p3d_files, work=out.parent)
    offsets, n, band_snap = table.offsets, table.n, table.band_snap
    n_snaps = len(table.snaps)
    idx = table.bands.band_index.to_numpy(float)
    winner = s0._seg(table.y * idx, offsets)
    cls = (np.clip(idx - np.repeat(winner, n), -3, 3) + 3).astype(int)
    p_mkt = table.p_market
    b_mkt = table.brier(p_mkt)
    mu_q, sd_q, _ = s0.moments(p_mkt, idx, offsets, n)
    hours = table.local_hour
    result = {"schema": SCHEMA, "label": s0.STEP0_LABEL, "inputs": dict(meta, module_sha256=s0.sha256_file(__file__),
                                                                      step0_module_sha256=s0.sha256_file(s0.__file__)),
              "windows": {}}
    for window, lo, hi in s0.WINDOWS:
        in_w = common & (hours >= lo) & (hours <= hi)
        cuts = np.quantile(sd_q[in_w], [1 / 3, 2 / 3])
        terc = np.digitize(sd_q, cuts)
        wres = {"n_snapshots": int(in_w.sum()), "market_sd_tercile_cuts": cuts.tolist(), "arms": {}}
        for arm, p in arms.items():
            if window == "13-16" and arm == "L6":
                continue
            mu_p, sd_p, _ = s0.moments(p, idx, offsets, n)
            c_mult = float(np.sqrt(np.mean(sd_p[in_w] ** 2) / np.mean(sd_q[in_w] ** 2)))

            def gauss(mu, sd):
                return s0.gaussian_bands(mu, sd, idx, n, table.impossible, band_snap, n_snaps)

            stand_ins = {"S2_gauss_market": gauss(mu_q, sd_q), "C3_arm_centre_mkt_width": gauss(mu_p, sd_q),
                         "C3m_arm_centre_global_mult": gauss(mu_p, c_mult * sd_q),
                         "S5_arm_width_arm_centre": gauss(mu_p, sd_p), "S6_arm": p}

            def block(mask):
                b = {"n_snapshots": int(mask.sum()), "stand_ins": {}}
                for name, v in stand_ins.items():
                    pos = s0._positions(v, cls, band_snap, n_snaps, mask)
                    b["stand_ins"][name] = {"positions": pos, **s0._summary(pos),
                                            "excess_vs_market": s0._excess(table, v, mask, b_mkt)}
                return b

            wres["arms"][arm] = {"c_mult": c_mult, "pooled": block(in_w),
                                 "by_market_sd_tercile": [dict(tercile=t, **block(in_w & (terc == t)))
                                                          for t in range(3)]}
        result["windows"][window] = wres
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}")
    ap.add_argument("--layout", required=True)
    ap.add_argument("--coefficients", required=True)
    ap.add_argument("--nowcasts", required=True)
    ap.add_argument("--p3d", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    step0b(layout=a.layout, coefficients=a.coefficients, nowcasts=a.nowcasts, p3d_files=[Path(f) for f in a.p3d],
           out=a.out)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
