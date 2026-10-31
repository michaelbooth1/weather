"""C3 kill-tier driver: K1 identity, K3 synthetic positive / negation / null, refusals R1-R5, out-dir rule.

Synthetic fixtures only: no real price, label, snapshot or bundle is opened. Rule: the C3 kill-tier DRAFT
(docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-DRAFT.md) as amended by REVISION-1 (master D1) REVISION-2 (wider of date-clustered and block-3 bounds) and REVISION-3 (step 5 too).
"""
import ast
import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest

from tests.host_guard import import_or_skip_on_capture_host

c3 = import_or_skip_on_capture_host("weather.calibration.c3_kill_tier")

SOURCE = Path(c3.__file__)


@pytest.fixture(scope="module")
def k3():
    return c3.run_k3()


@pytest.fixture(scope="module")
def synthetic():
    return c3.synthetic_rows()


def _report(rows, **extra):
    return dict(code_tip=c3.FROZEN_SCORER_COMMIT, exports=[{"day": "2026-09-24", "hashes": {"bundle.json": "0" * 64}}],
                selected_hours=rows, **extra)


def test_constants_match_the_draft_and_open_points_are_provisional():
    assert c3.PLACEBO_SEEDS == tuple(20260921 + j for j in range(20))
    assert (c3.BOOT_B, c3.BOOT_SEED, c3.BH_Q, c3.EPS, c3.GAP_DAYS) == (2000, 20261024, 0.10, 1e-4, 1)
    assert np.array_equal(c3.W_GRID, np.arange(101) / 100.0)
    assert (c3.MIN_DATES, c3.MIN_EVENT_HOURS, c3.MEAN_W_MIN) == (10, 200, 0.05)
    assert set(c3.PROVISIONAL) == {"OP1_burn_in_dates", "OP2_kill_scope", "OP3_min_markets", "OP4_austin_option"}
    assert (c3.BURN_IN_DATES, c3.MIN_MARKETS, c3.AUSTIN_OPTION) == (4, 5, "a")
    assert c3.ROW80_RECEIPT_SHA256 == "6c0f4a1d4b5e5e12445fc79203b2c6ab66dbe1e0e21e7451ac1e6cb3bbc54504"  # master 2026-10-31


def test_no_network_imports():
    allowed = {"__future__", "argparse", "hashlib", "json", "math", "subprocess", "sys", "collections", "datetime",
               "pathlib", "zoneinfo", "numpy", "weather.paths", "weather", "weather.market.market_registry"}
    found = set()
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module)
    found.discard("weather.calibration")       # market_blend, imported unchanged
    assert found <= allowed, found - allowed


def test_k1_w0_is_the_market_exactly_on_a_synthetic_panel(synthetic):
    flat = c3.flatten(synthetic)
    result = c3.k1(flat, flat.c)
    assert result["passed"] and result["max_abs_diff"] == 0.0 and result["brier_ratio"] == 1.0


def test_k3_positive_is_not_killed(k3):
    assert k3["checks"]["positive_not_killed"], k3["arms"]["positive"]


def test_k3_negation_is_killed_with_delta_below_zero(k3):
    assert k3["checks"]["negation_delta_upper_below_zero"], k3["arms"]["negation"]
    assert k3["checks"]["negation_killed"], k3["arms"]["negation"]


def test_k3_null_interval_covers_zero(k3):
    assert k3["checks"]["null_delta_interval_covers_zero"], k3["arms"]["null"]
    assert k3["passed"]


def test_k3_is_deterministic(k3):
    assert c3.run_k3()["arms"] == k3["arms"]


def test_placebo_is_a_derangement_and_uses_no_label(synthetic):
    flat = c3.flatten(synthetic)
    s = flat.c - flat.m
    sp, donor, unshuffled = c3.placebo_s(flat, s, c3.PLACEBO_SEEDS[0])
    assert unshuffled == 0 and (donor >= 0).all()
    assert (flat.date[donor] != flat.date).all()
    assert (flat.market[donor] == flat.market).all() and (flat.hour[donor] == flat.hour).all()
    flipped = copy.deepcopy(flat)
    flipped.y = 1.0 - flipped.y
    assert np.array_equal(c3.placebo_s(flipped, s, c3.PLACEBO_SEEDS[0])[0], sp)


def test_rho_matches_numpy():
    rng = np.random.default_rng(1)
    s, e = rng.normal(size=50), rng.normal(size=50)
    S = np.array([len(s), s.sum(), e.sum(), (s * s).sum(), (e * e).sum(), (s * e).sum()])
    assert c3.rho(S) == pytest.approx(np.corrcoef(s, e)[0, 1], abs=1e-12)


def test_bh_single_arm_reduces_to_p_le_q():
    assert c3.bh([0.10]) == [True] and c3.bh([0.1001]) == [False]
    assert c3.bh([0.01, 0.04, 0.2]) == [True, True, False]


def _p0r(holds=True, excluded=False, power=0.9):
    return dict(holds=holds, edge_excluded=excluded, power_at_edge=power)


def _wr(holds=True, excluded=False):
    return dict(holds=holds, edge_excluded=excluded)


def test_decide_truth_table():
    assert c3.decide(False, _p0r(), _wr())[0] == c3.INCONCLUSIVE
    assert c3.decide(True, _p0r(power=0.49), _wr()) == (c3.DESCRIPTIVE, "power_at_edge_below_min")
    assert c3.decide(True, _p0r(power=None), _wr())[0] == c3.DESCRIPTIVE
    assert c3.decide(True, _p0r(holds=False, excluded=True, power=0.49), _wr())[0] == c3.DESCRIPTIVE   # cannot drop A1
    assert c3.decide(True, _p0r(holds=False, excluded=True), _wr()) == (c3.KILL, "p0_delta_upper_below_delta_edge")
    assert c3.decide(True, _p0r(holds=True, excluded=True), _wr())[0] == c3.KILL   # real but below edge size
    # P0 not holding alone is never a kill
    assert c3.decide(True, _p0r(holds=False), _wr()) == (c3.INCONCLUSIVE, "p0_not_held_underpowered_for_information")
    assert c3.decide(True, _p0r(), _wr(holds=False, excluded=True)) == (c3.KILL, "w_gain_upper_below_edge_gain")
    assert c3.decide(True, _p0r(), _wr(holds=False))[0] == c3.INCONCLUSIVE
    assert c3.decide(True, _p0r(), _wr()) == (c3.NOT_KILLED, "p0_and_w_hold")


def test_block_counts_are_circular_blocks_of_three():
    n = 14
    k = c3.block_counts(n, b=500)
    assert k.shape == (500, n) and np.all(k.sum(axis=1) == n)
    assert np.array_equal(k, c3.block_counts(n, b=500))                     # fixed seed
    assert np.allclose(k.mean(axis=0), 1.0, atol=0.15)                      # circular: no end underweighting
    rng = np.random.default_rng(c3.BOOT_SEED)
    starts = rng.integers(n, size=(500, 5))
    first = [(starts[0, 0] + j) % n for j in range(3)]
    assert all(k[0, d] >= 1 for d in first)                                  # a block is 3 consecutive dates


def test_interval_takes_the_wider_bounds():
    rng = np.random.default_rng(3)
    a, b = rng.normal(0, 1, 2000), rng.normal(0.2, 2, 2000)
    iv = c3.interval(a, b)
    lo, hi = iv["ci95_wider"]
    assert lo == min(iv["ci95_date_clustered"][0], iv["ci95_block3"][0])
    assert hi == max(iv["ci95_date_clustered"][1], iv["ci95_block3"][1])
    assert iv["se_wider"] == max(iv["se_date_clustered"], iv["se_block3"])


def test_p0_deciding_interval_is_the_wider_one(k3):
    flat, arms = c3.k3_arms()
    placebos, _ = c3.placebo_candidates(flat, arms["positive"])
    r, _ = c3.p0(flat, arms["positive"], placebos)
    dc, b3 = r["delta_ci95_date_clustered"], r["delta_ci95_block3"]
    assert r["delta_ci95"] == [min(dc[0], b3[0]), max(dc[1], b3[1])]
    assert r["se_delta"] == max(r["se_delta_date_clustered"], r["se_delta_block3"])
    assert r["p_one_sided"] == max(r["p_one_sided_date_clustered"], r["p_one_sided_block3"])


def test_w_holds_uses_the_wider_bounds():
    flat, arms = c3.k3_arms()
    placebos, _ = c3.placebo_candidates(flat, arms["positive"])
    w, _ = c3.w_gate(flat, arms["positive"], placebos)
    for key in ("blend_minus_placebo", "blend_minus_floor_only", "blend_minus_market"):
        iv = w[key]
        assert iv["ci95_wider"][0] <= min(iv["ci95_date_clustered"][0], iv["ci95_block3"][0])
        assert iv["ci95_wider"][1] >= max(iv["ci95_date_clustered"][1], iv["ci95_block3"][1])
    expect = (w["mean_w"] >= c3.MEAN_W_MIN and w["blend_minus_placebo"]["ci95_wider"][1] < 0
              and w["blend_minus_floor_only"]["ci95_wider"][1] < 0)
    assert w["holds"] == expect
    src = Path(c3.__file__).read_text(encoding="utf-8")
    assert 'vs_placebo["ci95"][1]' not in src and 'vs_floor["ci95"][1]' not in src


def test_edge_size_constants_and_power():
    assert c3.DELTA_EDGE == pytest.approx(0.2236, abs=1e-4) and c3.DELTA_EDGE ** 2 == pytest.approx(c3.EDGE_GAIN)
    assert c3.POWER_MIN == 0.5
    assert c3.power_at(c3.DELTA_EDGE, c3.DELTA_EDGE / c3.Z95) == pytest.approx(0.5)   # SE 0.114 is the 0.5 line
    assert c3.power_at(0.224, 0.080) == pytest.approx(0.80, abs=0.01)
    assert c3.power_at(1.0, 0.0) is None and c3.power_at(1.0, None) is None
    assert c3.RULE_REVIEWED_SHA256.startswith("cd4d814f") and not c3.DATE_GATE_TRACE["override_applied"]


def test_coverage_floor_makes_a_thin_panel_inconclusive(synthetic):
    thin = [r for r in synthetic if r["market_id"] in ("toronto", "nyc", "atlanta", "chicago")]
    assert not c3.coverage(c3.flatten(thin))["ok"]


def _independent_tables(rows):
    def est(sub):
        cells = {}
        for r in sub:
            cells.setdefault((r["target_date"], r["market_id"]), []).append(r)
        if not cells:
            return None
        out = {"provider": [], "mid": []}
        for hours in cells.values():
            for key, name in (("probability", "provider"), ("mid", "mid")):
                out[name].append(sum(sum((b[key] - b["observed_yes"]) ** 2 for b in h["bands"]) / len(h["bands"])
                                     for h in hours) / len(hours))
        p, m = sum(out["provider"]) / len(cells), sum(out["mid"]) / len(cells)
        return {"provider": {"estimate": p}, "mid": {"estimate": m}, "provider_minus_mid": {"estimate": p - m}}
    tables = {f"{s}_lead_{lead}": {"brier": est([r for r in rows if r["source"] == s and r["lead"] == lead])}
              for s in ("nbp", "fallback") for lead in (1, 2)}
    tables["pooled_descriptive"] = {"brier": est(rows)}
    return tables


def test_k2c_rederivation_matches_and_detects_a_change(synthetic):
    tables = _independent_tables(synthetic)
    assert c3.check_tables(synthetic, tables)["passed"]
    tables["nbp_lead_1"]["brier"]["mid"]["estimate"] += 1e-9
    with pytest.raises(c3.Void):
        c3.check_tables(synthetic, tables)


def test_k2a_bundle_pairs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "bundle.json").write_bytes(b"{}")
    (b / "bundle.json").write_bytes(b"{}")
    sha = hashlib.sha256(b"{}").hexdigest()
    report = {"exports": [{"hashes": {"bundle.json": sha}}]}
    assert c3.check_bundles([(a, b)], report)["passed"]
    (b / "bundle.json").write_bytes(b"{ }")
    with pytest.raises(c3.Void):
        c3.check_bundles([(a, b)], report)


def test_r1_target_outside_the_panel_refuses(synthetic):
    row = dict(synthetic[0], target_date="2026-10-09")
    with pytest.raises(c3.Refused, match="R1"):
        c3.check_rows(_report([row]))


def test_r2_bundle_day_outside_the_window_refuses(synthetic):
    report = _report(synthetic[:1])
    report["exports"][0]["day"] = "2026-10-08"
    with pytest.raises(c3.Refused, match="R2"):
        c3.check_rows(report)


def test_r3_austin_1003_refuses(synthetic):
    row = dict(synthetic[0], market_id="austin", target_date="2026-10-03")
    with pytest.raises(c3.Refused, match="R3"):
        c3.check_rows(_report([row]))


def test_r4_receipt_required_pinned_and_matching(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"receipt")
    with pytest.raises(c3.Refused, match="R4"):
        c3.check_row80(None, pinned="0" * 64)
    with pytest.raises(c3.Refused, match="R4"):
        c3.check_row80(receipt)                     # does not match the pinned receipt
    with pytest.raises(c3.Refused, match="R4"):
        c3.check_row80(receipt, pinned="0" * 64)
    assert c3.check_row80(receipt, pinned=hashlib.sha256(b"receipt").hexdigest())["sha256"]


def test_r5_wrong_scorer_tip_refuses(synthetic):
    with pytest.raises(c3.Refused, match="R5"):
        c3.check_rows(dict(_report(synthetic[:1]), code_tip="1" * 40))


def test_main_refuses_r4_before_opening_any_report(tmp_path):
    out = tmp_path / "out"
    missing = tmp_path / "never-created" / "report.json"
    code = c3.main(["--report", str(missing), "--report-repeat", str(missing),
                    "--bundle-pair", str(tmp_path / "x"), str(tmp_path / "y"),
                    "--scorer-worktree", str(tmp_path / "tree"), "--out", str(out)])
    assert code == c3.EXIT_REFUSED and not out.exists()


def test_out_dir_must_be_new_and_disjoint_from_inputs(tmp_path):
    existing = tmp_path / "exists"
    existing.mkdir()
    with pytest.raises(c3.Refused):
        c3.check_out_dir(existing, [])
    with pytest.raises(c3.Refused):
        c3.check_out_dir(tmp_path / "inputs" / "out", [tmp_path / "inputs"])
    (tmp_path / "inputs").mkdir()
    assert c3.check_out_dir(tmp_path / "fresh", [tmp_path / "inputs"]) == (tmp_path / "fresh").resolve()


def test_evaluate_on_synthetic_rows_writes_only_into_a_new_dir(tmp_path, synthetic):
    result, lines = c3.evaluate(synthetic)
    assert result["k1"]["passed"] and result["outcome"] in (c3.KILL, c3.NOT_KILLED, c3.INCONCLUSIVE, c3.DESCRIPTIVE)
    out = tmp_path / "run"
    c3.write_out(out, dict(outcome=result["outcome"]), lines)
    assert sorted(p.name for p in out.iterdir()) == ["c3_result.json", "c3_rows.jsonl"]
    with pytest.raises(FileExistsError):
        c3.write_out(out, {})
