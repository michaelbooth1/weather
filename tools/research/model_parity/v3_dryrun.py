"""HARNESS v3 H2: dry run — coverage and countability only, outcome-free BY CONSTRUCTION.

This module imports only ``v3_gate``, ``v3_inputs`` and ``v3_arms`` (none of which can name or
open a label or market file) and opens only the layout manifest plus the two input files, each
after the gate allows every date it holds for ``purpose="coverage"``. It never imports
``v3_outcomes``, ``v3_score`` or ``harness`` (which hold label/market access); a test plants label
and market files and asserts through an audit hook that they are never opened.

Report: rows, market-days and dates per block and per market; for each arm the snapshots it
covers (arm built on inputs only, floor present) and, per date, whether the gate would admit a
label/market join for the arm's family under the requested scoring purpose (countability).

    python -m tools.research.model_parity.v3_dryrun --layout C:\\swarm\\v3layout \
        --arm tools/research/model_parity/v3_arm_mg1_like.py --purpose development
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from tools.research.model_parity import v3_arms, v3_gate, v3_inputs


def _counts(snaps, mask):
    sub = snaps[mask]
    return {"rows": int(len(sub)), "market_days": int(len(sub[["date", "market"]].drop_duplicates())),
            "dates": int(sub.date.nunique())}


def dry_run(layout, arm_paths, purpose, gate=None):
    gate = gate or v3_gate.default_gate()
    arms = [v3_arms.load_arm(p) for p in arm_paths]
    family = arms[0].FAMILY if arms else "coverage_only"
    reads = any(a.READS_NBM_GUIDANCE for a in arms)
    snaps, bands, manifest = v3_inputs.read_inputs(layout, gate, family, reads, purpose="coverage")
    hours = snaps.local_hour.to_numpy(int)
    floor = snaps[list(v3_inputs.FLOOR_FIELDS)].notna().any(axis=1).to_numpy()
    report = {"purpose_requested": purpose, "gate": gate.identity(), "layout_manifest_files":
              sorted(n for n in manifest["files"] if n in v3_inputs.INPUT_FILES.values()),
              "totals": _counts(snaps, np.ones(len(snaps), bool)), "blocks": {}, "markets": {},
              "arms": {}, "outcome_free": True}
    for g, _, _ in v3_inputs.GROUPS:
        report["blocks"][g] = _counts(snaps, v3_inputs.group_mask(hours, g))
    for m in sorted(snaps.market.unique()):
        report["markets"][m] = _counts(snaps, (snaps.market == m).to_numpy())
    dates = sorted(snaps.date.astype(str).unique())
    for arm in arms:
        cand = v3_arms.build(arm, snaps, bands)
        covered = snaps.row_key.isin(set(cand.row_key)).to_numpy() & floor
        decisions = {d: gate.decide(arm.FAMILY, d, purpose, arm.READS_NBM_GUIDANCE) for d in dates}
        countable = snaps.date.astype(str).map(lambda d: decisions[d].allowed).to_numpy(bool)
        entry = {"family": arm.FAMILY, "reads_nbm_guidance": arm.READS_NBM_GUIDANCE,
                 "declared_inputs": list(arm.INPUTS), "code_sha256": arm.CODE_SHA256,
                 "eligible": _counts(snaps, covered),
                 "eligible_and_countable": _counts(snaps, covered & countable),
                 "refused_dates": {d: x.reasons for d, x in decisions.items() if not x.allowed},
                 "blocks": {}, "markets": {}}
        for g, _, _ in v3_inputs.GROUPS:
            gm = v3_inputs.group_mask(hours, g)
            entry["blocks"][g] = {"eligible": _counts(snaps, covered & gm),
                                  "eligible_and_countable": _counts(snaps, covered & gm & countable),
                                  "eligible_share": float(covered[gm].mean()) if gm.any() else None}
        for m in sorted(snaps.market.unique()):
            mm = (snaps.market == m).to_numpy()
            entry["markets"][m] = {"eligible": _counts(snaps, covered & mm),
                                   "eligible_and_countable": _counts(snaps, covered & mm & countable)}
        report["arms"][arm.NAME] = entry
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="HARNESS v3 dry run (coverage and countability only)")
    ap.add_argument("--layout", required=True)
    ap.add_argument("--arm", action="append", default=[])
    ap.add_argument("--purpose", default="development", choices=v3_gate.JOIN_PURPOSES)
    a = ap.parse_args(argv)
    print(json.dumps(dry_run(a.layout, a.arm, a.purpose), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
