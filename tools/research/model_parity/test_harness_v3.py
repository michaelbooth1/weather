"""Fixture-only contracts for HARNESS v3 (synthetic layouts; no real labels, no external data)."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from tools.research.model_parity import (v3_arms, v3_gate, v3_outcomes, v3_power, v3_score,
                                         v3_sequential)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BANDS = [("lte", 69, 69), ("eq", 70, 71), ("eq", 72, 73), ("gte", 74, 74)]
MARKETS = ("atlanta", "chicago", "miami", "denver")
DATES = tuple(f"2026-08-{d:02d}" for d in range(1, 13))
HOURS = (3, 7, 11, 14, 19)
WINDOW_UNDATED = ("# Reserved confirmation window\n\n**Status: RESERVED (narrow scope, MG-1): the first 45 dates on or\n"
                  "after D0 (D0 >= 2026-10-15; not dated) are held out ONLY against NBM-guidance-to-band "
                  "candidates.**\n\nrest\n")


def ledger_rows(extra=()):
    base = dict(schema=v3_gate.LEDGER_SCHEMA, decided_by="test", decided_at="2026-10-19", reason="t", source="t")
    rows = [dict(base, row_id="embargo", family="*", date_start="2026-10-16", date_end="2026-11-13",
                 status="reserved", scope="all"),
            dict(base, row_id="closed", family="*", date_start="2026-09-30", date_end="9999-12-31",
                 status="closed_by_default", scope="join"),
            dict(base, row_id="spent-dev", family="*", date_start="2026-07-31", date_end="2026-09-29",
                 status="spent", scope="join")]
    return rows + [dict(base, **x) for x in extra]


def make_gate(tmp_path, window=WINDOW_UNDATED, extra=()):
    w, led = tmp_path / "window.md", tmp_path / "ledger.jsonl"
    w.write_text(window, encoding="utf-8")
    led.write_text("".join(json.dumps(r) + "\n" for r in ledger_rows(extra)), encoding="utf-8")
    return v3_gate.Gate(w, led)


def synthetic_frames(seed=7, dates=DATES, plant=None):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market = [], [], [], []
    for m in MARKETS:
        for d in dates:
            high = int(rng.integers(68, 76))
            winner = next(i for i, (k, lo, hi) in enumerate(BANDS)
                          if (k == "lte" and high <= hi) or (k == "gte" and high >= lo) or lo <= high <= hi)
            for h in HOURS:
                key = f"{m}|{d}T{h:02d}"
                floor = float(high - 1) if h >= 14 else 60.0
                snaps.append({"row_key": key, "date": d, "market": m, "local_hour": h, "n_bands": 4,
                              "captured_at_utc": f"{d}T{h:02d}:00:00+00:00", "guidance_physical_floor": floor,
                              "high_so_far": floor, "trusted_current_max": np.nan, "floor": floor,
                              "v2_mean": high + rng.normal(0, 1.5) if h < 12 else np.nan, "v2_stddev": 1.5,
                              "v2_available_at": f"{d}T00:00:00+00:00",
                              **({"aux_feature": float(high)} if plant == "content" else {})})
                served = rng.dirichlet(np.ones(4))
                mk = 0.7 * np.eye(4)[winner] + 0.3 * rng.dirichlet(np.ones(4))
                for i, (k, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": key, "band_index": i, "kind": k, "low": lo, "high": hi,
                                  "p_served": served[i], "date": d, "market": m, "local_hour": h})
                    market.append({"row_key": key, "band_index": i, "date": d, "market": m,
                                   "p_market_yes": mk[i]})
                labels.append({"row_key": key, "date": d, "market": m, "winner": winner,
                               "settlement_high": float(high), "settlement_bucket": high,
                               "promotion_countable": False})
    return pd.DataFrame(snaps), pd.DataFrame(bands), pd.DataFrame(labels), pd.DataFrame(market)


@pytest.fixture()
def layout(tmp_path):
    root = tmp_path / "layout"
    v3_outcomes.write_layout(root, *synthetic_frames())
    return root


def write_prereg(tmp_path, arms, start=DATES[0], end=DATES[-1], purpose="development", **extra):
    specs = []
    for a in arms:
        if a in v3_score.BUILTINS:
            specs.append({"builtin": a})
        else:
            p = HERE / a
            specs.append({"path": str(p), "code_sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    prereg = {"schema": v3_score.PREREG_SCHEMA, "prereg_id": "t", "purpose": purpose,
              "dates": {"start": start, "end": end}, "arms": specs, **extra}
    path = tmp_path / f"prereg-{len(list(tmp_path.glob('prereg-*')))}.json"
    path.write_text(json.dumps(prereg), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- H1 gate

def test_gate_refuses_post_horizon_joins_and_the_embargo(tmp_path):
    g = make_gate(tmp_path)
    assert g.decide("x", "2026-09-29", "development", False).allowed
    assert not g.decide("x", "2026-09-29", "confirmation", False).allowed      # spent
    assert not g.decide("x", "2026-09-30", "development", False).allowed
    assert g.decide("x", "2026-09-30", "coverage", False).allowed               # outcome-free
    for p in v3_gate.PURPOSES:
        assert not g.decide("x", "2026-10-20", p, False).allowed                # embargo: everything
    with pytest.raises(v3_gate.GateRefused) as exc:
        g.require("x", ["2026-09-28", "2026-09-30", "2026-10-01"], "development", False)
    assert [r["date"] for r in exc.value.refusals] == ["2026-09-30", "2026-10-01"]


def test_open_row_opens_one_family_for_confirmation_only(tmp_path):
    g = make_gate(tmp_path, extra=[dict(row_id="open-a", family="fam_a", date_start="2026-10-01",
                                        date_end="2026-10-31", status="open", scope="join")])
    assert g.decide("fam_a", "2026-10-02", "confirmation", False).allowed
    assert not g.decide("fam_b", "2026-10-02", "confirmation", False).allowed
    assert not g.decide("fam_a", "2026-10-02", "development", False).allowed   # would spend it
    assert not g.decide("fam_a", "2026-10-16", "confirmation", False).allowed  # embargo beats open


def test_mg1_window_binds_nbm_guidance_families_only(tmp_path):
    open_row = [dict(row_id="open-g", family="g", date_start="2026-11-20", date_end="2026-11-30",
                     status="open", scope="join")]
    g = make_gate(tmp_path, extra=open_row)
    assert not g.decide("g", "2026-11-21", "confirmation", True).allowed       # undated: from D0 bound on
    assert g.decide("g", "2026-11-21", "confirmation", False).allowed
    dated = WINDOW_UNDATED.replace("(D0 >= 2026-10-15; not dated)", "MG-1 D0 = 2026-11-01 MG-1 last = 2026-11-25")
    g2 = make_gate(tmp_path, window=dated, extra=open_row)
    assert g2.window["state"] == "reserved_dated"
    assert not g2.decide("g", "2026-11-21", "confirmation", True).allowed
    assert g2.decide("g", "2026-11-28", "confirmation", True).allowed


def test_gate_fails_closed_on_bad_sources(tmp_path):
    with pytest.raises(v3_gate.GateError):
        make_gate(tmp_path, window="# no status line\n")
    with pytest.raises(v3_gate.GateError):
        make_gate(tmp_path, window="**Status: something odd**\n")
    with pytest.raises(v3_gate.GateError):
        make_gate(tmp_path, extra=[dict(row_id="bad", family="*", date_start="2026-10-01",
                                        date_end="2026-10-02", status="open", scope="join")])
    (tmp_path / "w.md").write_text(WINDOW_UNDATED, encoding="utf-8")
    with pytest.raises(v3_gate.GateError):
        v3_gate.Gate(tmp_path / "w.md", tmp_path / "missing.jsonl")


def test_committed_ledger_and_window_parse_and_hold_the_brief():
    g = v3_gate.default_gate()
    assert not g.decide("any_family", "2026-09-30", "development", False).allowed
    assert not g.decide("any_family", "2026-10-16", "coverage", False).allowed
    assert not g.decide("any_family", "2026-11-13", "coverage", False).allowed
    assert g.decide("any_family", "2026-09-29", "development", False).allowed
    assert not any(r["status"] == "open" for r in g.rows)


# ----------------------------------------------------------------------------- H2 dry run

def test_dry_run_never_opens_or_imports_outcomes(tmp_path, layout):
    g = make_gate(tmp_path)
    script = tmp_path / "probe_dryrun_open.py"
    script.write_text(f"""
import json, sys
sys.path.insert(0, {str(REPO)!r})
opened = []
sys.addaudithook(lambda ev, args: opened.append(str(args[0])) if ev == "open" and args and isinstance(args[0], (str, bytes)) else None)
from tools.research.model_parity import v3_dryrun, v3_gate
gate = v3_gate.Gate({str(g.window_path)!r}, {str(g.ledger_path)!r})
rep = v3_dryrun.dry_run({str(layout)!r}, [{str(HERE / 'v3_arm_mg1_like.py')!r}], "development", gate)
mods = [m for m in sys.modules if m.endswith(("v3_outcomes", "v3_score", "model_parity.harness"))]
print(json.dumps({{"opened": opened, "mods": mods, "rows": rep["totals"]["rows"],
                  "eligible": rep["arms"]["mg1_like_v2_read"]["eligible"]["rows"]}}))
""", encoding="utf-8")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=tmp_path, check=True)
    res = json.loads(out.stdout.strip().splitlines()[-1])
    planted = {str(layout / v3_outcomes.LABEL_FILE), str(layout / v3_outcomes.MARKET_FILE)}
    assert (layout / v3_outcomes.LABEL_FILE).exists() and (layout / v3_outcomes.MARKET_FILE).exists()
    assert not planted & {os.path.normpath(p) for p in res["opened"]}
    assert not any(v3_outcomes.LABEL_FILE in p or v3_outcomes.MARKET_FILE in p for p in res["opened"])
    assert any("inputs_snapshots.parquet" in p for p in res["opened"])          # the hook does see opens
    assert res["mods"] == []
    assert res["rows"] == len(MARKETS) * len(DATES) * len(HOURS) and 0 < res["eligible"] < res["rows"]


def test_dry_run_module_imports_nothing_outcome_side():
    tree = ast.parse((HERE / "v3_dryrun.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not names & {"v3_outcomes", "v3_score", "harness", "v3_core"}
    for dep in ("v3_dryrun.py", "v3_inputs.py", "v3_gate.py", "v3_arms.py"):
        t = ast.parse((HERE / dep).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(t) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        imported |= {n.module or "" for n in ast.walk(t) if isinstance(n, ast.ImportFrom)}
        assert not any(x.endswith(("v3_outcomes", "v3_score", "harness", "v3_core")) for x in imported), dep
        consts = {n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not consts & {v3_outcomes.LABEL_FILE, v3_outcomes.MARKET_FILE}, dep


def test_dry_run_refuses_a_layout_holding_embargoed_dates(tmp_path):
    root = tmp_path / "emb"
    v3_outcomes.write_layout(root, *synthetic_frames(dates=("2026-10-15", "2026-10-16")))
    from tools.research.model_parity import v3_dryrun
    with pytest.raises(v3_gate.GateRefused):
        v3_dryrun.dry_run(root, [], "development", make_gate(tmp_path))


# ----------------------------------------------------------------------------- H3 power

def test_power_reaches_both_branches_and_flags_untestable():
    out = v3_power.plan(1e-4, 7e-5, 1e-5, 45, 11, dev_estimate=-0.01, sims=400)
    assert out["simulated_effect"] == pytest.approx(-0.005)
    assert out["both_branches_reachable"] and 0 < out["simulated_power_go_given_effect"] < 1
    assert out["simulated_go_given_null"] < 0.1 and out["verdict"] == "TESTABLE"
    assert abs(out["simulated_power_go_given_effect"] - out["analytic_power"]) < 0.08
    assert v3_power.plan(1e-4, 7e-5, 1e-5, 45, 11, -0.01, bar=0.005, sims=50)["verdict"] == "UNTESTABLE"


def test_power_components_from_a_dev_entry():
    entry = {"estimate": -0.01, "n_cells": 396, "markets_n": 11, "W_sd": 0.0037,
             "date_only_ci95": [-0.0133, -0.0066], "market_only_ci95": [-0.0160, -0.0057]}
    c = v3_power.components_from_entry(entry)
    assert c["dev_dates"] == 36 and c["var_date"] > 0 and c["var_market"] > 0 and c["var_resid"] >= 0
    se = v3_power.analytic_se(c["var_date"], c["var_market"], c["var_resid"], 36, 11)
    assert se == pytest.approx(max(c["s_crossed"], np.hypot(c["s_date_only"], c["s_market_only"])), rel=0.35)


# ----------------------------------------------------------------------------- H4-H7 scorer

def test_single_shot_scores_seals_and_refuses_a_second_run(tmp_path, layout, capsys):
    g = make_gate(tmp_path)
    prereg, sha = write_prereg(tmp_path, ["v3_arm_mg1_like.py", "v3_arm_served.py", "market_identity"],
                               primary={"arm": "mg1_like_v2_read", "block": "00-16"},
                               E2={"weights": {"mg1_like_v2_read": {"00-16": 0.0, "all": 0.4}}},
                               interim={"looks": [0.5, 1.0]})
    out = tmp_path / "out"
    path, digest, payload = v3_score.run(prereg, sha, layout, out, gate=g)
    assert capsys.readouterr().out == ""                       # run() prints nothing; main prints after sealing
    assert v3_score.verify_sealed(path) and not os.access(path, os.W_OK)
    assert (out / f"{sha[:16]}.boundaries.json").exists() and payload["boundaries_sealed_before_join"]
    e1 = payload["E1"]
    # (f) every arm has an input-removed twin; served has no inputs so its twin is itself
    assert {"mg1_like_v2_read__input_removed", "served_identity__input_removed"} <= set(e1)
    assert e1["mg1_like_v2_read__input_removed"]["reason_counts"] == {"absent": len(MARKETS) * len(DATES) * len(HOURS)}
    # (d) the market as its own candidate: R = 1 exactly, interval too
    r = e1["market_identity"]["groups"]["all"]["E1_R_arm_over_market"]
    assert r["estimate"] == 1.0 and r["ci95"] == [1.0, 1.0]
    # E2 with weight 0 is the market exactly; labelled complementary, not edge
    e2 = payload["E2"]["mg1_like_v2_read"]
    assert e2["groups"]["00-16"]["E2_R_blend_over_market"]["estimate"] == 1.0 and "NOT edge" in e2["label"]
    # H6 label ledger: labels only, one row per (family, date, market)
    rows = [json.loads(x) for x in (out / "label_ledger.jsonl").read_text().splitlines()]
    fams = {r["family"] for r in rows}
    assert len(rows) == len(fams) * len(MARKETS) * len(DATES)
    assert set(rows[0]) == {"schema", "family", "date", "market", "settlement_bucket", "promotion_countable",
                            "prereg_sha256", "written_utc"}
    with pytest.raises(v3_score.ScoreRefused) as exc:
        v3_score.run(prereg, sha, layout, out, gate=g)
    assert exc.value.code == v3_score.EXIT_SEALED
    assert v3_score.main(["--prereg", str(prereg), "--prereg-sha256", sha, "--layout", str(layout),
                          "--out", str(out)]) == v3_score.EXIT_SEALED


def test_scorer_verifies_prereg_and_arm_hashes(tmp_path, layout):
    g = make_gate(tmp_path)
    prereg, sha = write_prereg(tmp_path, ["v3_arm_served.py"])
    with pytest.raises(v3_score.ScoreRefused) as exc:
        v3_score.run(prereg, "0" * 64, layout, tmp_path / "o", gate=g)
    assert exc.value.code == v3_score.EXIT_VERIFY
    data = json.loads(prereg.read_text())
    data["arms"][0]["code_sha256"] = "f" * 64
    prereg.write_text(json.dumps(data))
    with pytest.raises(v3_score.ScoreRefused) as exc:
        v3_score.run(prereg, hashlib.sha256(prereg.read_bytes()).hexdigest(), layout, tmp_path / "o", gate=g)
    assert exc.value.code == v3_score.EXIT_VERIFY


def test_scorer_refuses_gated_dates_before_reading(tmp_path, layout, monkeypatch):
    g = make_gate(tmp_path)
    prereg, sha = write_prereg(tmp_path, ["v3_arm_served.py"], start="2026-09-29", end="2026-09-30")
    monkeypatch.setattr(v3_score.v3_inputs, "read_inputs", lambda *a, **k: pytest.fail("inputs read"))
    with pytest.raises(v3_score.ScoreRefused) as exc:
        v3_score.run(prereg, sha, layout, tmp_path / "o", gate=g)
    assert exc.value.code == v3_score.EXIT_GATE and "2026-09-30" in str(exc.value)


def test_boundaries_are_sealed_before_the_join(tmp_path, layout, monkeypatch):
    g = make_gate(tmp_path)
    prereg, sha = write_prereg(tmp_path, ["v3_arm_served.py"], interim={"looks": [0.5, 1.0]})
    real = v3_outcomes.load_outcomes

    def spy(*a, **k):
        assert v3_score.verify_sealed(tmp_path / "o" / f"{sha[:16]}.boundaries.json")
        return real(*a, **k)
    monkeypatch.setattr(v3_score.v3_outcomes, "load_outcomes", spy)
    v3_score.run(prereg, sha, layout, tmp_path / "o", look=1, gate=g)


def test_planted_label_column_is_refused(tmp_path):
    root = tmp_path / "planted"
    v3_outcomes.write_layout(root, *synthetic_frames(plant="content"))
    prereg, sha = write_prereg(tmp_path, ["v3_arm_served.py"])
    with pytest.raises(v3_score.ScoreRefused) as exc:
        v3_score.run(prereg, sha, root, tmp_path / "o", gate=make_gate(tmp_path))
    assert exc.value.code == v3_score.EXIT_LEAK and "aux_feature" in str(exc.value)
    assert not list((tmp_path / "o").glob("*.result.json"))
    snaps, bands, labels, market = synthetic_frames()
    with pytest.raises(Exception):
        v3_outcomes.write_layout(tmp_path / "byname", snaps.assign(settlement_high=1.0), bands, labels, market)


def test_blend_fit_refuses_dates_after_boundary():
    with pytest.raises(v3_score.ScoreRefused):
        v3_score.fit_blend_weights(None, None, None, None, ["2026-09-29", "2026-09-30"])


def test_label_ledger_dedupes_and_refuses_conflicts(tmp_path):
    led = v3_outcomes.LabelLedger(tmp_path / "l.jsonl")
    labels = synthetic_frames()[2]
    assert led.record("f", labels, "s") == (len(MARKETS) * len(DATES), 0)
    assert v3_outcomes.LabelLedger(tmp_path / "l.jsonl").record("f", labels, "s") == (0, len(MARKETS) * len(DATES))
    changed = labels.assign(settlement_bucket=labels.settlement_bucket + 1)
    with pytest.raises(v3_outcomes.OutcomeError):
        v3_outcomes.LabelLedger(tmp_path / "l.jsonl").record("f", changed, "s")


def test_obf_futility_boundaries():
    b = v3_sequential.boundaries([0.5, 1.0])
    assert b["binding"] is False and b["looks"][0]["futility_z"] == pytest.approx(0.50, abs=0.03)
    assert b["looks"][0]["beta_spent_increment"] == pytest.approx(0.0699, abs=1e-3)
    assert v3_sequential.interim_decision(b, 1, 0.2) == "FUTILITY_NONBINDING"
    assert v3_sequential.interim_decision(b, 1, 1.0) == "CONTINUE"
    assert v3_sequential.interim_decision(b, 2, 2.5) == "GO"
    three = v3_sequential.boundaries([1 / 3, 2 / 3, 1.0])["looks"]
    assert three[0]["futility_z"] < three[1]["futility_z"]
    with pytest.raises(ValueError):
        v3_sequential.boundaries([0.5, 0.9])


def test_arm_protocol_rejects_label_inputs(tmp_path):
    p = tmp_path / "bad_arm.py"
    p.write_text("NAME='b'\nFAMILY='f'\nREADS_NBM_GUIDANCE=False\nINPUTS=('settlement_high',)\n"
                 "def build(s, b):\n    return None\n", encoding="utf-8")
    with pytest.raises(v3_arms.ArmError):
        v3_arms.load_arm(p)


# ----------------------------------------------------------------------------- 2026-10-20 rulings

def test_committed_ledger_reserves_stage_b_and_allows_only_the_floor_fixture_control():
    g = v3_gate.default_gate()
    stage_b = next(r for r in g.rows if r["row_id"] == "reserved-stageB-20260603-20260730")
    assert (stage_b["status"], stage_b["scope"], stage_b["max_decisions"], stage_b["stratum"], stage_b["q"]) == \
        ("reserved", "join", 2, "B", 3.1098893)
    assert not any(r["status"] == "spent" and r["date_start"] <= "2026-07-30" and r["date_end"] >= "2026-06-03"
                   for r in g.rows)
    fixture = next(r for r in g.rows if r["status"] == "control_only")
    assert (fixture["family"], fixture["date_start"], fixture["date_end"]) == \
        ("serving_floor_control", "2026-07-02", "2026-07-10")
    assert "ba748b76" in fixture["fixture"] and "8ac77c08" in fixture["fixture"]
    for day in ("2026-06-03", "2026-07-05", "2026-07-30"):
        for purpose in ("development", "confirmation"):
            for fam in ("serving_floor_control", "nbm_guidance_band"):
                assert not g.decide(fam, day, purpose, False).allowed
        assert not g.decide("nbm_guidance_band", day, "control", False).allowed
        assert g.decide("nbm_guidance_band", day, "coverage", False).allowed       # outcome-free only
    assert g.decide("serving_floor_control", "2026-07-02", "control", False).allowed
    assert g.decide("serving_floor_control", "2026-07-10", "control", False).allowed
    assert not g.decide("serving_floor_control", "2026-07-11", "control", False).allowed
    assert not g.decide("serving_floor_control", "2026-06-20", "control", False).allowed


def test_control_only_never_lifts_embargo_closed_dates_or_other_families(tmp_path):
    rows = [dict(row_id="stage-b", family="*", date_start="2026-06-03", date_end="2026-07-30", status="reserved",
                 scope="join", max_decisions=2, stratum="B", q=3.1098893),
            dict(row_id="ctl", family="c", date_start="2026-06-01", date_end="2026-12-31", status="control_only",
                 scope="join", fixture="test")]
    g = make_gate(tmp_path, extra=rows)
    assert g.decide("c", "2026-07-01", "control", False).allowed
    assert not g.decide("c", "2026-07-01", "development", False).allowed
    assert not g.decide("d", "2026-07-01", "control", False).allowed
    assert not g.decide("c", "2026-10-01", "control", False).allowed       # closed_by_default stays
    assert not g.decide("c", "2026-10-20", "control", False).allowed       # scope-all embargo stays
    for bad in (dict(row_id="b1", family="*", date_start="2026-06-01", date_end="2026-06-02",
                     status="control_only", scope="join"),
                dict(row_id="b2", family="c", date_start="2026-06-01", date_end="2026-06-02",
                     status="control_only", scope="all")):
        with pytest.raises(v3_gate.GateError):
            make_gate(tmp_path, extra=[bad])


def test_mom_cov_recovers_components_and_nogo_interim_branches():
    rng = np.random.default_rng(3)
    d, m = 200, 11
    x = rng.normal(0, 0.02, (d, 1, 1)) + rng.normal(0, 0.01, (1, m, 1)) + rng.normal(0, 0.03, (d, m, 1))
    sd, sm, se = v3_power.mom_cov(x)
    assert sd[0, 0] == pytest.approx(4e-4, rel=0.3) and se[0, 0] == pytest.approx(9e-4, rel=0.1)
    comps = (np.diag([1e-4] * 3), np.diag([5e-5] * 3), np.diag([1e-4] * 3))
    hi = v3_power.simulate_nogo([1.3, 1.3], 0.0, comps, 45, 11, sims=400)
    null = v3_power.simulate_nogo([1.0, 1.0], 0.0, comps, 45, 11, sims=400)
    assert hi["nogo"] > 0.9 and null["nogo"] == 0.0
    good = v3_power.simulate_interim(-0.01, tuple(c[:1, :1] for c in comps), 20, 45, 11, 0.2656, sims=400)
    zero = v3_power.simulate_interim(0.0, tuple(c[:1, :1] for c in comps), 20, 45, 11, 0.2656, sims=400)
    assert good["p_futility_at_interim"] < zero["p_futility_at_interim"]
    assert 0 <= good["power_cost"] <= good["p_go_final_ignoring_interim"]
    assert v3_sequential.boundaries([20 / 45, 1.0])["looks"][0]["futility_z"] == pytest.approx(0.2656, abs=5e-4)
