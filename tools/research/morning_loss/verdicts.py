"""L5: apply the pre-registered KEEP / LEAD / KILL rules to the scorecard and subset outputs and print tables.

    python tools/research/morning_loss/verdicts.py C:\\t\\l5\\scores
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = (("l5a_debias", "MG-1"), ("l5b_linear", "MG-1"), ("l5c_afd", "matched intercepts"),
        ("l5d_corpus_linear", "MG-1"), ("l5e_corpus_half", "MG-1"), ("l5f_corpus_linear_augsep", "MG-1"))


def ci(e):
    lo, hi = e["ci95"]
    return f"{e['estimate']:+.4f} [{lo:+.4f}, {hi:+.4f}]"


def main(root):
    root = Path(root)
    for name, ctl in RUNS:
        files = sorted((root / name).glob("*.json"))
        if not files:
            print(f"## {name}: no score yet\n")
            continue
        sc = json.loads(files[-1].read_text())
        rows = {(r["market"], r["block"]): r for r in sc["rows"]}
        head = rows[("ALL", "07-12")]
        ms, mc = head["model_minus_served"], head["model_minus_control"]
        mcd = head["model_minus_control_date_clustered"]
        keep = ms["ci95"][1] < 0 and mc["ci95"][1] < 0
        lead = (not keep) and mcd["ci95"][1] < 0
        verdict = "KEEP" if keep else "LEAD" if lead else "KILL"
        print(f"## {name} (control {ctl}; score {files[-1].stem[:12]}): **{verdict}**")
        print(f"- 07-12 pooled: cand - served {ci(ms)}; cand - control {ci(mc)} (MDE80 {mc.get('mde80', 0):.4f}); "
              f"date-clustered {ci(mcd)}; control - served {ci(head['control_minus_served'])}")
        for h in range(7, 13):
            r = rows.get(("ALL", f"h{h:02d}"))
            if r:
                print(f"  - h{h:02d}: cand - control {ci(r['model_minus_control'])}; cand - served {ci(r['model_minus_served'])}")
        for sub in sorted(root.glob(f"{name}_subsets*.json")):
            s = json.loads(sub.read_text())
            print(f"- subsets `{sub.name}` (control {s['control']['name']}):")
            for r in s["rows"]:
                print(f"  - {r['subset']} (n={r['n_market_days']}): cand - control crossed "
                      f"{ci(r['cand_minus_control_crossed'])}, date {ci(r['cand_minus_control_date'])}; "
                      f"cand - served {ci(r['cand_minus_served_crossed'])}")
        print()


if __name__ == "__main__":
    main(sys.argv[1])
