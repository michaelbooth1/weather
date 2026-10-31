"""C3 kill-tier driver: K1 identity, K3 synthetic positive / negation / null, refusals R1-R5, out-dir rule.

Synthetic fixtures only: no real price, label, snapshot or bundle is opened. Rule: the C3 kill-tier DRAFT
(docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-DRAFT.md); OP1-OP4 are PROVISIONAL.
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
    assert c3.ROW80_RECEIPT_SHA256 is None          # pinned by master at freeze, never before


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


def test_decide_truth_table():
    assert c3.decide(False, True, True) == c3.INCONCLUSIVE
    assert c3.decide(True, False, True) == c3.KILL
    assert c3.decide(True, True, False) == c3.KILL
    assert c3.decide(True, True, True) == c3.NOT_KILLED


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
        c3.check_row80(receipt)                     # not pinned in the driver yet
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
    assert result["k1"]["passed"] and result["outcome"] in (c3.KILL, c3.NOT_KILLED, c3.INCONCLUSIVE)
    out = tmp_path / "run"
    c3.write_out(out, dict(outcome=result["outcome"]), lines)
    assert sorted(p.name for p in out.iterdir()) == ["c3_result.json", "c3_rows.jsonl"]
    with pytest.raises(FileExistsError):
        c3.write_out(out, {})
