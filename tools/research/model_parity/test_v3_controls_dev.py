"""HARNESS v3 development controls (real dev data, dates <= 2026-09-29). NOT a unit test.

Runs only with HARNESS_V3_DEV=1, through the workstation heavy wrapper::

    scripts\\ops\\workstation_heavy.ps1 -Kind pytest -Queue -RepoRoot <wt> -PythonPath <venv python>
        -ArgumentsBase64 <b64 of ["-m","pytest","-q","-p","no:cacheprovider","--basetemp=C:\\t\\hv3c",
                                   "tools/research/model_parity/test_v3_controls_dev.py"]>

Writes C:\\swarm\\out\\hv3\\<stamp>\\controls.json (plus the sealed single-shot result) and asserts
every control.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("HARNESS_V3_DEV") != "1",
                                reason="development controls run only under the heavy wrapper")

LAYOUT = Path(os.environ.get("HARNESS_V3_LAYOUT", r"C:\swarm\v3layout"))
OUT = Path(os.environ.get("HARNESS_V3_OUT", r"C:\swarm\out\hv3"))
STATS = Path(r"C:\swarm\out\r-stat-mg1\stats.json")
REPO = Path(__file__).resolve().parents[3]


def test_v3_development_controls():
    from tools.research.model_parity import (harness as h, v3_controls as c, v3_dryrun, v3_gate, v3_power,
                                             v3_score)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = OUT / stamp
    out.mkdir(parents=True)
    gate = v3_gate.default_gate()
    record = {"stamp": stamp, "HARNESS_V3_SHA256": v3_score.harness_v3_sha256(),
              "HARNESS_SHA256_v2": h.harness_sha256(), "gate": gate.identity(),
              "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()}
    record["v2_positive_control"] = c.v2_positive_control()
    fixture = subprocess.run(["git", "-C", str(REPO), "show", f"{c.FLOOR_FIXTURE_COMMIT}:{c.FLOOR_FIXTURE_PATH}"],
                             capture_output=True, check=True).stdout
    record["a_floor_shift"] = c.floor_shift(fixture, gate)
    if not (LAYOUT / "manifest.json").exists():
        c.v3_outcomes.split_v2_cache(LAYOUT)
    record["layout_manifest"] = json.loads((LAYOUT / "manifest.json").read_text(encoding="utf-8"))
    record["layout_manifest"]["files"] = {k: {kk: vv for kk, vv in v.items() if kk != "dates"} | {
        "first_date": v["dates"][0], "last_date": v["dates"][-1]} for k, v in record["layout_manifest"]["files"].items()}
    dry = v3_dryrun.dry_run(LAYOUT, [str(c.HERE / "v3_arm_mg1_like.py"), str(c.HERE / "v3_arm_served.py")],
                            "control", gate)
    record["dry_run"] = {"totals": dry["totals"], "blocks": dry["blocks"],
                         "arms": {k: {"eligible": v["eligible"], "eligible_and_countable": v["eligible_and_countable"],
                                      "block_eligible_share": {g: b["eligible_share"] for g, b in v["blocks"].items()}}
                                  for k, v in dry["arms"].items()}}
    record["h3_mg1_dev_components"] = {
        n: v3_power.plan(**{k: v for k, v in v3_power.load_components(STATS, "d1/mg1_minus_served/00-16").items()
                            if k in ("var_date", "var_market", "var_resid")}, dates=n, markets=11,
                         dev_estimate=v3_power.load_components(STATS, "d1/mg1_minus_served/00-16")["dev_estimate"],
                         sims=2000) for n in (20, 45, 90)}
    record["h3_mg1_dev_components"]["components"] = v3_power.load_components(STATS, "d1/mg1_minus_served/00-16")
    dev = c.Dev(LAYOUT, gate)
    record["b_injected_skill"] = c.injected_skill(dev)
    record["e_date_shuffle"] = c.date_shuffle(dev)
    # (d)+(f) single-shot scorer on the dev layout, all arms in one pass, sealed
    from tools.research.model_parity import v3_arms
    mg1 = v3_arms.load_arm(c.HERE / "v3_arm_mg1_like.py")
    cand = v3_arms.build(mg1, dev.snaps, dev.bands)
    pc = dev.t.candidate_vector(cand)[0]
    weights = v3_score.fit_blend_weights(dev.t, pc, dev.y, dev.pm,
                                         sorted(dev.snaps.date.astype(str).unique()))
    prereg = out / "controls_prereg.json"
    sha = c.write_prereg(prereg, ["v3_arm_mg1_like.py", "v3_arm_served.py", "market_identity"],
                         primary={"arm": "mg1_like_v2_read", "block": "00-16"},
                         E2={"weights": {"mg1_like_v2_read": weights}, "fit_last_date": "2026-09-29",
                             "note": "fit on the same dev dates it is scored on: in-sample, control only"},
                         interim={"looks": [0.5, 1.0], "alpha": 0.025, "beta": 0.2})
    path, digest, payload = v3_score.run(prereg, sha, LAYOUT, out, gate=gate)
    record["d_single_shot"] = {"prereg_sha256": sha, "result": str(path), "result_sha256": digest,
                               "sealed_ok": v3_score.verify_sealed(path), "decision": payload["decision"],
                               "E1": c.summarise_run(payload), "E2": payload["E2"],
                               "leakage_suspects": payload["leakage_suspects"], "boundaries": payload["boundaries"]}
    again = v3_score.main(["--prereg", str(prereg), "--prereg-sha256", sha, "--layout", str(LAYOUT), "--out", str(out)])
    record["d_single_shot"]["second_run_exit_code"] = again
    # v3 core equals v2 harness on the same candidate (semantic parity)
    snaps2, bands2 = h.candidate_inputs()
    cand2 = v3_arms.build(mg1, snaps2, bands2)
    v2 = h.score(cand2, name="v3_parity_mg1_like")
    v2_0016 = h.table_lookup(v2, "00-16")["candidate_minus_served"]
    v3_0016 = payload["E1"]["mg1_like_v2_read"]["groups"]["00-16"]["arm_minus_served"]
    facts = h.table_facts()
    g_all = payload["E1"]["served_identity"]["groups"]["all"]
    record["v2_v3_parity"] = {"mg1_like_00_16_v2": v2_0016["estimate"], "mg1_like_00_16_v2_ci95": v2_0016["ci95"],
                              "mg1_like_00_16_v3": v3_0016["estimate"], "mg1_like_00_16_v3_ci95": v3_0016["ci95"],
                              "served_over_market_v2": facts["served_to_market_ratio"]["estimate"],
                              "served_over_market_v3": g_all["brier_served"] / g_all["brier_market"]}
    # (c) planted label column
    planted = OUT / f"{stamp}_planted_layout"
    c.write_planted_layout(LAYOUT, planted, gate)
    p2 = out / "planted_prereg.json"
    sha2 = c.write_prereg(p2, ["v3_arm_served.py"])
    try:
        v3_score.run(p2, sha2, planted, out / "planted", gate=gate)
        record["c_planted_label"] = {"refused": False}
    except v3_score.ScoreRefused as exc:
        record["c_planted_label"] = {"refused": True, "exit_code": exc.code, "message": str(exc)[:300],
                                     "result_written": any((out / "planted").glob("*.result.json"))}
    for f in planted.iterdir():
        f.unlink()
    planted.rmdir()
    (out / "controls.json").write_text(json.dumps(record, indent=1, default=float), encoding="utf-8")

    e1 = record["d_single_shot"]["E1"]
    assert record["v2_positive_control"]["pass"]
    assert record["a_floor_shift"]["pass"]
    assert record["b_injected_skill"]["pass"]
    assert record["c_planted_label"]["refused"] and record["c_planted_label"]["exit_code"] == v3_score.EXIT_LEAK
    assert not record["c_planted_label"]["result_written"]
    assert all(x["R"] == 1.0 and x["R_ci95"] == [1.0, 1.0] for x in e1["market_identity"].values())
    assert again == v3_score.EXIT_SEALED and record["d_single_shot"]["sealed_ok"]
    assert record["e_date_shuffle"]["pass"]
    for arm in ("mg1_like_v2_read", "served_identity"):
        assert arm + "__input_removed" in e1
    assert all(x["arm_minus_served"] == 0.0 for x in e1["mg1_like_v2_read__input_removed"].values())
    assert abs(record["v2_v3_parity"]["mg1_like_00_16_v2"] - record["v2_v3_parity"]["mg1_like_00_16_v3"]) < 1e-12
    assert abs(record["v2_v3_parity"]["served_over_market_v2"] - record["v2_v3_parity"]["served_over_market_v3"]) < 1e-12
    assert not record["d_single_shot"]["leakage_suspects"]



def test_v3_power_calibration_dev():
    """2026-10-20 ruling: H3 calibration at ~0.575 and ~0.40 power, plus control (a) re-run under the
    revised ledger (06-03..07-30 reserved for Stage-B; control_only row for the fixture)."""
    from tools.research.model_parity import v3_controls as c, v3_gate, v3_score
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + "_power"
    out = OUT / stamp
    out.mkdir(parents=True)
    gate = v3_gate.default_gate()
    record = {"stamp": stamp, "HARNESS_V3_SHA256": v3_score.harness_v3_sha256(), "gate": gate.identity(),
              "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()}
    fixture = subprocess.run(["git", "-C", str(REPO), "show", f"{c.FLOOR_FIXTURE_COMMIT}:{c.FLOOR_FIXTURE_PATH}"],
                             capture_output=True, check=True).stdout
    record["a_floor_shift"] = c.floor_shift(fixture, gate)
    try:
        gate.require("nbm_guidance_band", ["2026-07-05"], "control", False)
        record["stage_b_control_refused_for_other_family"] = False
    except v3_gate.GateRefused:
        record["stage_b_control_refused_for_other_family"] = True
    dev = c.Dev(LAYOUT, gate)
    record["b2_power_calibration"] = c.power_calibration(dev)
    (out / "power_calibration.json").write_text(json.dumps(record, indent=1, default=float), encoding="utf-8")
    assert record["a_floor_shift"]["pass"] and record["stage_b_control_refused_for_other_family"]
    assert all("empirical_power" in d for d in record["b2_power_calibration"]["designs"])



def test_v3_nogo_reachability_dev():
    """2026-10-20 ruling: P(NO-GO) at 20/45/90 forward dates under dev / half / null, and the
    20-of-45-date interim futility crossing and power cost."""
    from tools.research.model_parity import v3_controls as c, v3_gate, v3_score
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + "_nogo"
    out = OUT / stamp
    out.mkdir(parents=True)
    gate = v3_gate.default_gate()
    record = {"stamp": stamp, "HARNESS_V3_SHA256": v3_score.harness_v3_sha256(), "gate": gate.identity(),
              "git_head": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()}
    dev = c.Dev(LAYOUT, gate)
    record["nogo"] = c.nogo_reachability(dev)
    (out / "nogo.json").write_text(json.dumps(record, indent=1, default=float), encoding="utf-8")
    assert len(record["nogo"]["nogo"]) == 18 and len(record["nogo"]["interim"]) == 6
