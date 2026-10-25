"""MG-2 composite binding: the 13:00 switch, the reservation guard, outcome-blind checks, fail-closed import."""
import ast
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather import mg1_reserved_window as w
from weather.calibration import mg2_composite as mg2

ROOT = Path(__file__).resolve().parents[2]


def _snaps(hours, floor=70.0):
    n = len(hours)
    return pd.DataFrame({
        "row_key": [f"atlanta|s{i}" for i in range(n)], "market": ["atlanta"] * n, "local_hour": hours,
        "date": ["2026-09-01"] * n, "guidance_physical_floor": [floor] * n, "high_so_far": [np.nan] * n,
        "trusted_current_max": [np.nan] * n, "v2_available_at": ["2026-09-01T10:00:00Z"] * n,
        "captured_at_utc": ["2026-09-01T12:00:00Z"] * n, "v2_period_kind": ["maximum"] * n})


def _bands(snaps):
    rows = []
    for rk in snaps.row_key:
        rows += [(rk, 0, "lte", np.nan, 69.0), (rk, 1, "between", 70.0, 71.0), (rk, 2, "gte", 72.0, np.nan)]
    return pd.DataFrame(rows, columns=["row_key", "band_index", "kind", "low", "high"])


def _frame(snaps, probs):
    rows = [(rk, i, p) for rk in snaps.row_key for i, p in enumerate(probs)]
    return pd.DataFrame(rows, columns=["row_key", "band_index", "p"])


def test_switch_is_fixed_at_13_and_falls_back_to_mg1():
    snaps = _snaps([12, 13, 16])
    bands = _bands(snaps)
    pre, post, base = _frame(snaps, [.1, .2, .7]), _frame(snaps, [.0, .5, .5]), _frame(snaps, [.2, .3, .5])
    frame, source = mg2.compose(snaps, bands, pre, post, base)
    assert mg2.SWITCH_HOUR == 13
    assert source == {"atlanta|s0": "pre", "atlanta|s1": "arm_a", "atlanta|s2": "arm_a"}
    assert frame[frame.row_key == "atlanta|s0"].p.tolist() == [.1, .2, .7]
    # arm A missing at 16 -> MG-1, never served or the pre half
    frame, source = mg2.compose(snaps, bands, pre, post[post.row_key != "atlanta|s2"], base)
    assert source["atlanta|s2"] == "mg1"
    assert frame[frame.row_key == "atlanta|s2"].p.tolist() == [.2, .3, .5]


def test_post_half_with_no_mass_the_floor_allows_uses_mg1():
    snaps = _snaps([14], floor=72.0)  # B = 72: only the gte band is possible
    bands = _bands(snaps)
    post = _frame(snaps, [.4, .6, .0])
    _, source = mg2.compose(snaps, bands, _frame(snaps, [1, 0, 0]), post, _frame(snaps, [0, 0, 1]))
    assert source["atlanta|s0"] == "mg1"


def test_pre_half_never_used_after_the_switch():
    snaps = _snaps([13])
    bands = _bands(snaps)
    _, source = mg2.compose(snaps, bands, _frame(snaps, [1, 0, 0]), _frame(snaps, [])[:0],
                            _frame(snaps, [0, 0, 1]))
    assert source["atlanta|s0"] == "mg1"


def _rule(tmp_path, **over):
    fields = {"switch_hour": "13", "d0": "2026-10-27", "n_forward_dates": "3", "owner_decision_id": "NONE",
              "coefficients_sha256": "0" * 64}
    fields.update(over)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    path = tmp_path / "rule.md"
    path.write_text(f"# rule\n\n```{mg2.RULE_BLOCK}\n{body}\n```\n", encoding="utf-8")
    return path


def test_scorer_refuses_reserved_dates_without_a_dated_owner_decision(tmp_path):
    _, fields = mg2.read_rule(_rule(tmp_path))
    with pytest.raises(mg2.Mg2Refused, match="reserved window"):
        mg2.score_guard(fields, ["2026-10-27", "2026-10-28", "2026-10-29"])
    last = w.window()[1]
    assert last is not None and last >= date(2026, 11, 28)
    with pytest.raises(mg2.Mg2Refused, match="reserved window"):
        mg2.score_guard(fields, [last.isoformat()])


@pytest.mark.parametrize("bad", ["yes", "OD-2026-13-01-x", "2026-10-25", "OD-20261025-x", "OD-2026-10-25-"])
def test_malformed_owner_decision_id_refuses(tmp_path, bad):
    _, fields = mg2.read_rule(_rule(tmp_path, owner_decision_id=bad))
    with pytest.raises((mg2.Mg2Refused, ValueError)):
        mg2.score_guard(fields, ["2026-10-27", "2026-10-28", "2026-10-29"])


def test_owner_decision_still_needs_mg1_look_receipt_and_a_closed_window(tmp_path):
    _, fields = mg2.read_rule(_rule(tmp_path, owner_decision_id="OD-2026-10-26-mg2-exemption"))
    days = ["2026-10-27", "2026-10-28", "2026-10-29"]
    with pytest.raises(mg2.Mg2Refused, match="receipt"):
        mg2.score_guard(fields, days)
    receipt = tmp_path / "mg1_look.json"
    receipt.write_text("{}")
    with pytest.raises(mg2.Mg2Refused, match="not closed"):
        mg2.score_guard(fields, days, today=date(2026, 11, 1), mg1_look_receipt=receipt)
    out = mg2.score_guard(fields, days, today=date(2027, 1, 20), mg1_look_receipt=receipt)
    assert out["inside_mg1_window"] == 3 and out["owner_decision_id"] == "OD-2026-10-26-mg2-exemption"


def test_post_window_dates_need_no_decision_but_need_d0_and_n(tmp_path):
    end = w.window()[1]
    first = date.fromordinal(end.toordinal() + 1)
    days = [date.fromordinal(first.toordinal() + i).isoformat() for i in range(3)]
    _, fields = mg2.read_rule(_rule(tmp_path, d0=first.isoformat()))
    assert mg2.score_guard(fields, days)["inside_mg1_window"] == 0
    with pytest.raises(mg2.Mg2Refused, match="exactly 3"):
        mg2.score_guard(fields, days[:2])
    with pytest.raises(mg2.Mg2Refused, match="before D0"):
        mg2.score_guard(fields, [end.isoformat()] + days[:2])
    _, unset = mg2.read_rule(_rule(tmp_path, d0="UNSET"))
    with pytest.raises(mg2.Mg2Refused, match="UNSET"):
        mg2.score_guard(unset, days)


def test_rule_switch_hour_must_match_code(tmp_path):
    with pytest.raises(mg2.Mg2Refused, match="switch_hour"):
        mg2.read_rule(_rule(tmp_path, switch_hour="12"))


def test_emit_refuses_forward_without_d0_and_control_after_dev(tmp_path):
    rule = _rule(tmp_path, d0="UNSET")
    kw = dict(layout_root=tmp_path, replay_root=tmp_path, forecast_manifest=tmp_path, nowcasts=tmp_path,
              coefficients=tmp_path, rule=rule, out=tmp_path / "o")
    with pytest.raises(mg2.Mg2Refused, match="D0"):
        mg2.emit(first="2026-10-27", last="2026-10-28", **kw)
    with pytest.raises(mg2.Mg2Refused, match="dev dates"):
        mg2.emit(first="2026-09-29", last="2026-09-30", control=True, **kw)


def test_coefficients_hash_is_enforced(tmp_path):
    path = tmp_path / "c.json"
    path.write_bytes(b"{}")
    with pytest.raises(mg2.Mg2Refused, match="coefficients sha"):
        mg2.load_coefficients(path, "0" * 64)
    assert mg2.load_coefficients(path, hashlib.sha256(b"{}").hexdigest()) == {}


def test_outcome_blind_checks_catch_pit_parser_and_replay():
    snaps = _snaps([8, 9, 14])
    snaps.loc[1, "v2_available_at"] = "2026-09-01T13:00:00Z"  # after capture
    frame = _frame(snaps, [.2, .3, .5])
    sources = {"atlanta|s0": "pre", "atlanta|s1": "mg1", "atlanta|s2": "arm_a"}
    other = frame.copy()
    other.loc[0, "p"] += 1e-9
    out = mg2.outcome_blind_checks(snaps, sources, frame, replayed=other)
    assert out["pit_v2_after_capture"] == 1 and not out["pit_pass"]
    assert out["parser_status"].startswith("UNVERIFIED") and out["parser_pass"] is False
    assert not out["replay_pass"]
    snaps["v2_parser_version"] = 2
    snaps.loc[1, "v2_available_at"] = "2026-09-01T11:00:00Z"
    out = mg2.outcome_blind_checks(snaps, sources, frame, replayed=frame.copy())
    assert out["pit_pass"] and out["parser_pass"] and out["replay_pass"] and out["coverage_pass"]


def test_inputs_reader_never_opens_label_or_price_files(tmp_path):
    snaps = _snaps([9])
    snaps.to_parquet(tmp_path / "inputs_snapshots.parquet")
    _bands(snaps).to_parquet(tmp_path / "inputs_bands.parquet")
    for name in mg2.LABEL_FILES:
        (tmp_path / name).write_bytes(b"not parquet")  # would raise if opened
    s, b = mg2.read_inputs(tmp_path)
    assert len(s) == 1 and len(b) == 3
    snaps.assign(winner=1).to_parquet(tmp_path / "inputs_snapshots.parquet")
    with pytest.raises(AssertionError):
        mg2.read_inputs(tmp_path)


def test_arm_a_distribution_is_l3s_ols_floor():
    from weather.calibration import r0_ols_floor_challenger as l3

    rng = np.random.default_rng(0)
    records = [{"forecast_high": float(f), "high_so_far": float(f - 5 + rng.normal()),
                "current_temp": float(f - 3), "final_bucket": int(round(f + rng.normal())), "target_date": "x"}
               for f in rng.uniform(70, 95, 200)]
    entry = mg2.arm_a_fit(records)
    ref = l3.fit_fold(records)
    assert np.allclose(entry["beta"], ref["beta"], atol=0, rtol=0) and entry["ols_sd"] == ref["ols_sd"]
    record = {"forecast_high": 88.0, "high_so_far": 84.02, "current_temp": 84.0}
    support = list(range(60, 110))
    expected, _ = l3.challenger_distributions(ref, record, support)
    assert mg2.arm_a_distribution(entry, record, support) == expected["ols_floor"]


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.mg2_composite")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.mg2_composite", {"__name__": "weather.model.toronto_model"})
    finally:
        sys.modules["weather.calibration.mg2_composite"] = saved


def test_no_production_module_imports_the_binding():
    """Production never reaches MG-2: no module outside the research calibration lane names it."""
    hits = []
    for path in (ROOT / "src").rglob("*.py"):
        if path.name == "mg2_composite.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, (ast.Import, ast.ImportFrom)) else []
            mod = node.module if isinstance(node, ast.ImportFrom) and node.module else ""
            if "mg2_composite" in mod or any("mg2_composite" in n for n in names):
                hits.append(str(path.relative_to(ROOT)))
    for path in (ROOT / "app").rglob("*.py"):
        if "mg2_composite" in path.read_text(encoding="utf-8"):
            hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_forward_sizing_scales_with_n():
    rng = np.random.default_rng(1)
    dates = np.repeat([f"d{i}" for i in range(40)], 11)
    delta = rng.normal(-0.001, 0.01, len(dates))
    out = mg2.forward_sizing(dates, delta, (20, 80), margin=0.001)
    assert out["per_n"]["80"]["se"] < out["per_n"]["20"]["se"]
    assert abs(out["per_n"]["20"]["se"] / out["per_n"]["80"]["se"] - 2.0) < 0.3
    assert set(out["per_n"]["20"]) >= {"mde80", "power_superiority_at_dev_point", "power_noninferiority_at_dev_point"}
