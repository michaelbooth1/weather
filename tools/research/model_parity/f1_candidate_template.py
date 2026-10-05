"""Candidate template for model-parity hunters (F1). Copy to <id>_<slug>.py and edit.

Run from C:\\pt\\swarm with the repo interpreter:
    C:\\Users\\Michael\\Documents\\github\\weather\\venv\\Scripts\\python.exe -m tools.research.model_parity.f1_candidate_template

Before your FIRST score: append your rule to C:\\swarm\\registry.jsonl (DESIGN section 1).
This template scores only served probabilities with the rule-4 floor applied (the floor-only rung,
|delta| < 0.0002 in every block), which is not a hypothesis.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\f1\template_demo")   # hunters: C:\swarm\out\<id>\


def vectorised_candidate():
    """Pattern 1: build probabilities from the allow-listed tables (no market, no labels)."""
    snaps, bands = h.candidate_inputs()
    # snaps: one row per snapshot (row_key, market, date, stratum, local_hour, block, captured_at_utc,
    #        captured features such as high_so_far / guidance_physical_floor / nws_grid_high / hrrr_high,
    #        v2_* NBM values with v2_available_at, floor, floor_bucket, n_bands ...)
    # bands: one row per snapshot x band (row_key, band_index, kind, low, high, p_served, floor_impossible)
    # External data must be joined point in time: h.assert_point_in_time(available_at, captured_at_utc).
    p = bands.p_served.to_numpy(copy=True)          # <- replace with your rule
    cand = bands[["row_key", "band_index"]].assign(p=p)
    # Rows you cannot cover: drop them (served fallback is applied by the harness, rule 6).
    return cand


def rowwise_candidate():
    """Pattern 2: a per-snapshot function; return None to fall back to served."""
    def rule(snap, bands, p_served):
        # snap["local_hour"], snap["features"]["high_so_far"], bands[i]["kind"/"low"/"high"] ...
        # snap["winner"] or snap["p_market_yes"] raise LeakageError.
        return p_served                              # <- replace with your rule
    return h.from_rowwise(rule, where=lambda s: s.local_hour.between(17, 23))


def main():
    for name, cand in (("template_vectorised_identity", vectorised_candidate()),
                       ("template_rowwise_identity_17_23", rowwise_candidate())):
        result = h.score(cand, name=name)            # floor applied, all-row primary + matched
        h.save(result, OUT)
        print(h.markdown(result))
        t = h.table_lookup(result, "17-23", "from_20260823", "all_row")
        print(name, "17-23 from all-row delta", t["candidate_minus_served"]["estimate"],
              "class", result["classes"]["17-23"]["class"])
    print(json.dumps({"HARNESS_SHA256": h.harness_sha256()}))


if __name__ == "__main__":
    main()
