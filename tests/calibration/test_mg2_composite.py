"""MG-2 composite binding: the 13:00 switch, the reservation guard, outcome-blind checks, fail-closed import.

Guards: MG-2 pre-registration docs/research/mg2-composite-binding-2026-10-25/rule.md (§1a serve parity, §4
reserved window, §7 void conditions, §8 C4/C7 gate vectors).
"""
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

from tests.host_guard import import_or_skip_on_capture_host

mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")

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
    assert source == {"atlanta|s0": "pre", "atlanta|s1": mg2.POST, "atlanta|s2": mg2.POST}
    assert frame[frame.row_key == "atlanta|s0"].p.tolist() == [.1, .2, .7]
    # P3d_N missing at 16 -> MG-1, never served or the pre half
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
              "l6_coefficients_sha256": "0" * 64, "p3d_n_state_sha256": "PENDING",
              "forecast_high_source": "PENDING", "own_obs_source": "PENDING",
              "function_sha256": "f" * 64, "noninferiority_margin_00_16": "0.0010"}
    fields.update(over)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    path = tmp_path / "rule.md"
    path.write_text(f"# rule\n\n```{mg2.RULE_BLOCK}\n{body}\n```\n", encoding="utf-8")
    return path


def _gate_vectors(folder):
    """A forward emission's as-of-capture vectors and the emit audit that names their sha (rule §8 C7)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    vectors = folder / mg2.ASOF_VECTORS
    pd.DataFrame({"row_key": ["a|1"], "band_index": [0], "p": [1.0]}).to_parquet(vectors, index=False)
    audit = {"mode": "forward", "asof_capture": {"vectors_sha256": mg2.sha256_file(vectors)}}
    (folder / mg2.EMIT_AUDIT).write_text(json.dumps(audit), encoding="utf-8")
    return vectors


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
    kw = dict(layout_root=tmp_path, replay_root=tmp_path, p3d_n_state=tmp_path, nowcasts=tmp_path,
              coefficients=tmp_path, rule=rule, out=tmp_path / "o")
    with pytest.raises(mg2.Mg2Refused, match="D0"):
        mg2.emit(first="2026-10-27", last="2026-10-28", **kw)
    with pytest.raises(mg2.Mg2Refused, match="dev dates"):
        mg2.emit(first="2026-09-29", last="2026-09-30", control=True, **kw)


def test_coefficient_parts_are_hashed_separately_and_pending_refuses(tmp_path):
    path = tmp_path / "c.json"
    path.write_bytes(mg2.canonical({"l6_stack": {"coef": {"7": [0.1, 0.9, 5]}}}))
    with pytest.raises(mg2.Mg2Refused, match="l6 coefficients sha"):
        mg2.load_part(path, "l6", "0" * 64)
    good = hashlib.sha256(mg2.canonical({"coef": {"7": [0.1, 0.9, 5]}})).hexdigest()
    assert mg2.load_part(path, "l6", good) == {"coef": {"7": [0.1, 0.9, 5]}}
    with pytest.raises(mg2.Mg2Refused, match="PENDING"):
        mg2.load_part(path, "l6", "PENDING")
    assert mg2.COEF_PARTS == {"l6": "l6_stack"}  # P3d_N is bound by its own state file sha


def test_outcome_blind_checks_catch_pit_parser_and_replay():
    snaps = _snaps([8, 9, 14])
    snaps.loc[1, "v2_available_at"] = "2026-09-01T13:00:00Z"  # after capture
    frame = _frame(snaps, [.2, .3, .5])
    sources = {"atlanta|s0": "pre", "atlanta|s1": "mg1", "atlanta|s2": mg2.POST}
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


def test_arm_a_is_retired_from_the_binding():
    """The afternoon arm is P3d_N (pick 1ce2b5b4); no arm A or A' code path remains."""
    src = (ROOT / "src/weather/calibration/mg2_composite.py").read_text(encoding="utf-8")
    for name in ("arm_a_fit", "arm_a_distribution", "arm_a_records", "forecast_high_reader", "ARM_A_FEATURES",
                 "arm_a_coefficients_sha256", "MG2_ARM_A_DISTRIBUTIONS"):
        assert name not in src, name
    assert mg2.POST == "p3d_n"


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
        if path.name in ("mg2_composite.py", "mg2_inputs.py", "mg2_p3d_n.py", "b_scorer.py"):  # binding, parts, B
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


def _captured_sources(monkeypatch):
    """Hypothetical captured readers, so the gates after parity can be reached in a test."""
    return {"forecast_high_source": "captured_nbm_v2_mean_07z", "own_obs_source": "captured_metar_l6_own",
            "p3d_n_state_sha256": "1" * 64}


def test_forward_emit_needs_the_release_binding(tmp_path, monkeypatch):
    rule = _rule(tmp_path, d0="2026-10-27", **_captured_sources(monkeypatch))
    with pytest.raises(mg2.Mg2Refused, match="release binding"):
        mg2.emit(layout_root=tmp_path, replay_root=tmp_path, p3d_n_state=tmp_path, nowcasts=tmp_path,
                 coefficients=tmp_path, rule=rule, out=tmp_path / "o", first="2026-10-27", last="2026-10-28")


# ----------------------------------------------------------------------------- serve parity

@pytest.mark.parametrize("over,missing", [
    ({}, ["forecast_high", "own_obs"]),
    ({"forecast_high_source": "pit_previous_runs_gfs_seamless_day1",
      "own_obs_source": "iem_own_station_free_fetch"}, ["forecast_high", "own_obs"]),
    ({"forecast_high_source": "nonexistent", "own_obs_source": "iem_own_station_free_fetch"},
     ["forecast_high", "own_obs"]),
])
def test_every_input_must_come_from_the_capture_at_replay_time(tmp_path, over, missing):
    """Forward emission and the look refuse unless every MG-2 input is read from the capture.

    The retired dev sources (Open-Meteo Previous Runs for arm A, the free IEM fetch for L6) and unknown or
    PENDING ids are all refused.
    """
    _, fields = mg2.read_rule(_rule(tmp_path, **over))
    report = mg2.input_parity(fields)
    assert not report["ok"] and report["not_captured"] == missing
    with pytest.raises(mg2.Mg2Refused, match="serve parity"):
        mg2.require_forward_parity(fields)
    rule = _rule(tmp_path, d0="2026-10-27", **over)
    with pytest.raises(mg2.Mg2Refused, match="serve parity"):
        mg2.emit(layout_root=tmp_path, replay_root=tmp_path, nowcasts=tmp_path, coefficients=tmp_path,
                 p3d_n_state=tmp_path, rule=rule, out=tmp_path / "o", first="2026-10-27", last="2026-10-28",
                 release_binding=tmp_path)


def test_parity_rejects_a_source_registered_for_another_input(tmp_path):
    _, fields = mg2.read_rule(_rule(tmp_path, forecast_high_source="iem_own_station_free_fetch"))
    with pytest.raises(mg2.Mg2Refused, match="not forecast_high"):
        mg2.input_parity(fields)


def test_parity_passes_only_with_captured_sources_and_a_frozen_p3d_n_state(tmp_path, monkeypatch):
    over = _captured_sources(monkeypatch)
    _, fields = mg2.read_rule(_rule(tmp_path, **over))
    assert mg2.require_forward_parity(fields)["ok"]
    _, pending = mg2.read_rule(_rule(tmp_path, **dict(over, p3d_n_state_sha256="PENDING")))
    with pytest.raises(mg2.Mg2Refused, match="PENDING"):
        mg2.require_forward_parity(pending)


def test_registered_sources_are_classified_and_none_external_is_called_captured():
    assert set(mg2.SOURCE_FIELDS) == {s["input"] for s in mg2.SOURCES.values()}
    for sid, entry in mg2.SOURCES.items():
        assert entry["class"] in {mg2.CAPTURED, mg2.EXTERNAL}
    assert mg2.SOURCES["pit_previous_runs_gfs_seamless_day1"]["class"] == mg2.EXTERNAL
    assert mg2.SOURCES["iem_own_station_free_fetch"]["class"] == mg2.EXTERNAL
    assert mg2.SOURCES["captured_nbm_v2_mean_07z"]["class"] == mg2.CAPTURED
    assert mg2.SOURCES["captured_metar_l6_own"]["class"] == mg2.CAPTURED


def test_the_score_look_also_requires_parity(tmp_path):
    out = tmp_path / "out"
    snaps = pd.DataFrame({"row_key": ["a|1"], "date": ["2026-12-01"]})
    tmp_path.joinpath("layout").mkdir()
    from weather.reporting.scorecards import dev_scorecard_data as data

    snaps.to_parquet(tmp_path / "layout" / data.SNAPSHOTS_FILE, index=False)
    rule = _rule(tmp_path, d0="2026-12-01", n_forward_dates="1")
    with pytest.raises(mg2.Mg2Refused, match="serve parity"):
        mg2.score(layout_root=tmp_path / "layout", vectors=_gate_vectors(tmp_path / "emit"), rule=rule, out=out,
                  release_binding=tmp_path, today=date(2027, 6, 1))


NETWORK_MODULES = {"requests", "urllib", "urllib3", "httpx", "http", "aiohttp", "socket", "ftplib"}


def test_the_binding_makes_no_external_fetch():
    """No network import and no URL literal in the binding; its readers take local captured files only."""
    tree = ast.parse((ROOT / "src/weather/calibration/mg2_composite.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & NETWORK_MODULES
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in NETWORK_MODULES
            assert not any("fetch" in a.name.lower() or "url" in a.name.lower() for a in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value


def test_release_binding_and_function_hash_are_enforced(tmp_path):
    rule = _rule(tmp_path)
    rule_sha, fields = mg2.read_rule(rule)
    with pytest.raises(mg2.Mg2Refused, match="running_max_since_midnight"):
        mg2.verify_function(fields)
    from weather.model import observed_running_max

    fields["function_sha256"] = mg2.sha256_file(observed_running_max.__file__)
    assert mg2.verify_function(fields) == fields["function_sha256"]
    good = {"rule_sha256": rule_sha, "function_sha256": fields["function_sha256"], "files": mg2.release_hashes(),
            **{k: fields[k] for k in ("l6_coefficients_sha256", "p3d_n_state_sha256",
                                      "forecast_high_source", "own_obs_source")}}
    path = tmp_path / "release-binding.json"
    path.write_text(json.dumps(good))
    assert mg2.verify_release(path, rule_sha, fields)["rule_sha256"] == rule_sha
    bad = dict(good, files=dict(good["files"], **{mg2.RELEASE_FILES[0]: "0" * 64}))
    path.write_text(json.dumps(bad))
    with pytest.raises(mg2.Mg2Refused, match="mismatch"):
        mg2.verify_release(path, rule_sha, fields)
    assert set(mg2.RELEASE_FILES) == set(good["files"]) and all((ROOT / f).is_file() for f in mg2.RELEASE_FILES)


def _row(block, est, lo, hi):
    return {"market": "ALL", "block": block,
            "model_minus_control_date_clustered": {"estimate": est, "ci95": [lo, hi]}}


@pytest.mark.parametrize("u016,u1316,verdict", [(0.0009, -0.0001, "PASS"), (0.0010, -0.0001, "FAIL"),
                                                 (-0.002, 0.0, "FAIL"), (0.002, -0.01, "FAIL")])
def test_gate_needs_both_noninferiority_00_16_and_superiority_13_16(u016, u1316, verdict):
    rows = [_row("00-16", -0.001, -0.003, u016), _row("13-16", -0.005, -0.01, u1316)]
    assert mg2.gate_verdict(rows, 0.0010)["verdict"] == verdict


def test_second_look_is_refused(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "mg2_look.json").write_text("{}")
    with pytest.raises(mg2.Mg2Refused, match="exactly one look"):
        mg2.score(layout_root=tmp_path, vectors=_gate_vectors(tmp_path / "emit"), rule=_rule(tmp_path),
                  out=tmp_path / "out", release_binding=tmp_path)
