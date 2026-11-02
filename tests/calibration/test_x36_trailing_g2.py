"""Pure pieces of the L47 K row 112 G2 module (no data, no model, no run env)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "research" / "x36_v5_reopen" / "x36_trailing_g2.py"
_SPEC = importlib.util.spec_from_file_location("x36_trailing_g2_under_test", _PATH)
g2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(g2)


def test_g1_is_loaded_only_at_its_pinned_sha():
    g1 = g2.load_g1()
    assert g1.grid()[0] == (0, 0.0)


def test_dev_window_is_aug15_to_sep29_and_never_later():
    assert g2.dev_target_ok("2026-08-15") and g2.dev_target_ok("2026-09-29")
    assert not g2.dev_target_ok("2026-08-14")
    assert not g2.dev_target_ok("2026-09-30")
    assert not g2.dev_target_ok("2026-10-15")


def test_trailing_labels_start_jul31_and_exclude_the_sealed_panel():
    assert g2.label_date_ok("2026-07-31") and g2.label_date_ok("2026-09-28")
    assert not g2.label_date_ok("2026-07-30")
    assert not g2.label_date_ok("2026-09-29")


def test_line_date_reads_the_date_text_before_parsing():
    line = '{"available": true, "mean": 91.0, "target_date": "2026-07-30", "cycle": "07"}'
    assert g2.line_date(line) == "2026-07-30"
    assert g2.line_date('{"mean": 1}') is None


def test_selection_record_reports_ties_and_uses_the_rule_tie_break():
    g1 = g2.load_g1()
    combos = g1.grid()
    approx = {c: 5.0 for c in combos}
    exact = {(0, 0.0): 5.0, (7, 0.25): 4.0, (14, 0.25): 4.0, (7, 0.5): 4.0 + 1e-13}
    rec = g2.selection_record(approx, exact, combos, 10, 0.0, g1.pick)
    assert (rec["W"], rec["lam"]) == (7, 0.25)
    assert rec["tie_break_applied"] is True
    assert rec["tied_at_minimum"] == [[7, 0.25], [14, 0.25], [7, 0.5]]
    rec = g2.selection_record(approx, {(0, 0.0): 5.0, (14, 1.0): 3.0}, combos, 10, 0.0, g1.pick)
    assert (rec["W"], rec["lam"], rec["tie_break_applied"]) == (14, 1.0, False)


def test_load_freeze_checks_sha_schema_rule_and_writer(tmp_path):
    body = {"schema": g2.SCHEMA + "/freeze", "rule_sha256": g2.RULE_SHA256, "module_sha256": "m",
            "hours": {f"h{h:02d}": {"W": 7, "lam": 0.25} for h in g2.HOURS}}
    p = tmp_path / "t.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    picks, _ = g2.load_freeze(p, sha, "m")
    assert picks[7] == (7, 0.25) and set(picks) == set(g2.HOURS)
    with pytest.raises(g2.G2Error):
        g2.load_freeze(p, "0" * 64, "m")
    with pytest.raises(g2.G2Error):
        g2.load_freeze(p, sha, "other")


def test_terciles_and_mean_band_index():
    (q1, q2), cls = g2.terciles([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert q1 < q2
    assert list(cls) == [0, 0, 1, 1, 2, 2]
    p = np.array([0.5, 0.5, 0.0, 1.0, 1.0, 2.0])
    out = g2.mean_band_index(p, np.array([0, 3]), np.array([3, 3]), np.array([0, 1, 2, 0, 1, 2]))
    assert out[0] == pytest.approx(0.5) and out[1] == pytest.approx((1 + 4) / 4)


def test_gate_passes_only_below_zero():
    assert g2.gate(-1e-6)["pass"] is True
    assert g2.gate(0.0)["verdict"] == "KILL"
    assert g2.gate(None)["pass"] is False
