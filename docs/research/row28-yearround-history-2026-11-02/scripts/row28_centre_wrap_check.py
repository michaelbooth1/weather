"""Row 28 r4-final: linear (bound nearest_centre) vs circular centre choice, per arm centre set.

Calendar arithmetic plus PIT-corpus coverage metadata only (to list training dates); no label,
observation or score is read. Rule L (Feb 29 -> same year's Feb 28) is applied to the linear pick.

Run: venv python -I this_file --repo <worktree> --corpora <dir> --deciding <deciding_dates_r4.txt>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import date, timedelta


def md(c):
    return int(c[5:7]), int(c[8:10])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--corpora", required=True)
    ap.add_argument("--deciding", required=True)
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "src"))
    from weather.calibration import pooled_residual_model as prm  # read-only use

    set_a = tuple(prm.FORWARD_CENTRES) + tuple(prm.JAN_JUL_CENTRES) + ("2026-12-24",)
    set_b = tuple(prm.JAN_JUL_CENTRES[:10]) + ("2026-12-24",)
    arms = {"A": set_a, "B": set_b, "C": set_a, "D": set_a}

    def linear(d, cs):
        if d.month == 2 and d.day == 29:          # Rule L
            d = date(d.year, 2, 28)
        return prm.nearest_centre(d.isoformat(), cs)

    def circular(d, cs):
        ref = date(2001, 2, 28) if (d.month, d.day) == (2, 29) else date(2001, d.month, d.day)
        r = ref.timetuple().tm_yday
        dist = {c: min(abs(date(2001, *md(c)).timetuple().tm_yday - r),
                       365 - abs(date(2001, *md(c)).timetuple().tm_yday - r)) for c in cs}
        best = min(dist.values())
        return sorted(c for c, v in dist.items() if v == best)

    deciding = [date.fromisoformat(x.strip()) for x in open(a.deciding, encoding="utf-8") if x.strip()]
    assert len(deciding) == 660

    manifests = sorted(glob.glob(os.path.join(a.corpora, "*", "manifest.json")))
    train_days = set()
    for c in set_a:
        for y in prm.covered_years(c, manifests):
            train_days.update(prm.window_days(c, y))
    train_days = {d for d in train_days if 2021 <= d.year <= 2025 and d < date(2025, 12, 17)}

    def in_arm_b(d):
        return d.month <= 5 or (d.month == 12 and d.day >= 17)

    out = {}
    for arm, cs in arms.items():
        all_md = []
        d = date(2001, 1, 1)
        while d.year == 2001:
            all_md.append(d)
            d += timedelta(1)
        diff_md = [x.strftime("%m-%d") for x in all_md if linear(x, cs) not in circular(x, cs)]
        ties_md = [x.strftime("%m-%d") for x in all_md if len(circular(x, cs)) > 1]
        tr = sorted(x for x in train_days if arm != "B" or in_arm_b(x))
        sc_diff = [x.isoformat() for x in deciding if linear(x, cs) not in circular(x, cs)]
        tr_diff = [x.isoformat() for x in tr if linear(x, cs) not in circular(x, cs)]
        out[arm] = {
            "centres": len(cs),
            "month_days_linear_ne_circular": len(diff_md),
            "month_days_examples": diff_md[:5] + (["..."] if len(diff_md) > 5 else []) + diff_md[-2:],
            "circular_tie_month_days": ties_md,
            "scored_dates_differ": len(sc_diff),
            "scored_rows_differ": 40 * len(sc_diff),
            "training_dates": len(tr),
            "training_dates_differ": len(tr_diff),
            "training_dates_differ_list": tr_diff[:10],
        }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
