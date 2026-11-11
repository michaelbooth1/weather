"""Tiny invented-fixture checks for the new owner-option attempt.

Guards: T093 v2 fresh streams, cap skips, completeness and F2 resource priority.
"""

import os

import pytest

from weather.backtesting import low_ask_calibration as cal


def test_v2_arm_set_replaces_high_ask_and_crosses_eligibility_scenarios():
    assert len(cal.CAP90_ARMS) == 360
    assert {a["ask"] for a in cal.CAP90_ARMS} == {.8, .9}
    assert {a["slot_fraction"] for a in cal.CAP90_ARMS} == {1, .75, .5}
    assert len([a for a in cal.CAP90_ARMS if cal.is_planning_arm(a)]) == 6
    assert len(cal.SIZE_ARMS) == 120 and cal.SIZE_ARMS[-1]["ask"] == .93


def test_new_bootstrap_stream_is_fresh_and_v1_default_is_preserved():
    np, _, _ = cal.libraries()
    old = cal.bootstrap_weights(128)
    repeated = cal.bootstrap_weights(128, seed=20261110)
    fresh = cal.bootstrap_weights(128, seed=20261111)
    assert all(np.array_equal(a, b) for a, b in zip(old, repeated))
    assert not np.array_equal(old[0], fresh[0])


@pytest.mark.parametrize("fraction", [1, .75, .5, 0])
def test_cap_mask_keeps_source_completeness_and_counts_skips(fraction):
    np, _, _ = cal.libraries()
    arm = dict(phi=.22, common=.5, persistent=0, mechanism="spread", support=810,
               ask=.8, slot_fraction=fraction)
    panels, adequate, diag = cal.synthetic_panels(np.random.default_rng(1001), 2, arm, ask_cap=.9)
    assert adequate.all() and diag["executable_city_days"].tolist() == [810, 810]
    assert diag["adequate_dates"].tolist() == [68, 68]
    if fraction == 1:
        assert diag["ask_cap_slots"].tolist() == [0, 0]
    elif fraction == 0:
        assert diag["ask_cap_slots"].tolist() == [1620, 1620]
        assert not panels.any() and not diag["cash_cap_slots"].any()
    else:
        assert ((diag["ask_cap_slots"] > 0) & (diag["ask_cap_slots"] < 1620)).all()


def test_cap_is_inclusive_and_above_cap_slots_are_executable_skips():
    np, _, _ = cal.libraries()
    arm = dict(phi=0, common=0, persistent=0, mechanism="clustered", support=900,
               ask=.93, slot_fraction=1)
    panels, adequate, diag = cal.synthetic_panels(np.random.default_rng(1002), 1, arm, ask_cap=.9)
    assert adequate[0] and not panels.any() and diag["ask_cap_slots"][0] == 1800
    arm["ask"] = .9
    panels, adequate, diag = cal.synthetic_panels(np.random.default_rng(1002), 1, arm, ask_cap=.9)
    assert adequate[0] and panels.any() and diag["ask_cap_slots"][0] == 0


def test_cap90_boundary_null_uses_exact_cost_on_retained_cities(monkeypatch):
    np, _, _ = cal.libraries()
    original = cal.city_survival
    def capture(probability, persistent, **kwargs):
        assert probability == pytest.approx(.9145, rel=0, abs=1e-12)
        result = original(probability, persistent, **kwargs)
        retained = [i for i, city in enumerate(sorted(cal.CITIES)) if city != "chicago"]
        assert result[retained].mean() == pytest.approx(.9145, rel=0, abs=1e-12)
        return result
    monkeypatch.setattr(cal, "city_survival", capture)
    arm = dict(phi=.5, common=.5, persistent=.25, mechanism="spread", support=825,
               ask=.9, slot_fraction=.75)
    cal.synthetic_panels(np.random.default_rng(1003), 1, arm, ask_cap=.9)


def test_bootstrap_generation_obeys_cooperative_stop_guard():
    calls = []
    def stop():
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("synthetic pregate stop")
    with pytest.raises(RuntimeError, match="synthetic pregate stop"):
        cal.bootstrap_weights(512, seed=cal.V2_SEED, guard=stop)
    assert len(calls) == 2


def test_v2_summary_reports_each_fraction_separately():
    reports = []
    for i, arm in enumerate(cal.CAP90_ARMS):
        planning = cal.is_planning_arm(arm)
        lower = .9*arm["slot_fraction"]
        reports.append(dict(arm_index=i, arm=arm, size_upper=.01, null_diagnostics={},
                            planning_power_lower=lower,
                            power=[dict(intended_city_day_effect=e, lower=lower) for e in cal.EFFECTS] if planning else []))
    result = cal.summarize_reports(reports, arm_set="cap90")
    assert len(result["power_cells"]) == 24 and len(result["size_cells"]) == 360
    assert [r["power_lower"] for r in result["power_by_fraction"]] == pytest.approx([.9, .675, .45])
    assert [r["status"] for r in result["power_by_fraction"]] == ["CALIBRATED", "SCREEN_ONLY", "SCREEN_ONLY"]
    assert result["status"] == "SCREEN_ONLY"


def test_v2_guard_stops_at_pregate_marker_or_83_percent(tmp_path, monkeypatch):
    previous = tmp_path / "T045i"
    previous.mkdir()
    (previous / "started.json").write_text("{}")  # Before the named T045j-and-later scope.
    monkeypatch.setattr(cal, "v2_commit_percent", lambda: 82.999)
    cal.v2_runtime_guard(tmp_path)
    monkeypatch.setattr(cal, "v2_commit_percent", lambda: 83)
    with pytest.raises(RuntimeError, match="83 percent"):
        cal.v2_runtime_guard(tmp_path)


@pytest.mark.parametrize("name", ["T045j", "T045jr1", "T045jr1r1", "T045k", "T045later"])
@pytest.mark.parametrize("completed", [False, True])
def test_pregate_guard_blocks_running_but_preserves_completed_records(tmp_path, monkeypatch, name, completed):
    task = tmp_path / name
    task.mkdir()
    (task / "started.json").write_text("{}")
    if completed:
        (task / "exit.txt").write_text("0")
    monkeypatch.setattr(cal, "v2_commit_percent", lambda: 82)
    if completed:
        cal.v2_runtime_guard(tmp_path)
        assert cal.running_pregates(tmp_path) == []
    else:
        with pytest.raises(RuntimeError, match="pregate started"):
            cal.v2_runtime_guard(tmp_path)
        assert cal.running_pregates(tmp_path) == [task]
    assert (task / "started.json").read_text() == "{}"


def test_guard_binding_bridge_changes_only_the_recorded_code_hash():
    import json
    patch = json.loads(cal.repo_path("docs/research/low-ask-1/CALIBRATION_V2_GUARD_BINDING.json").read_text())
    assert patch["replacement_code_sha256"] == cal.hash_bytes(cal.Path(cal.__file__))
    old = dict(code_sha256=patch["previous_code_sha256"], seed=20261111, null_n=20000)
    new = dict(old, code_sha256=patch["replacement_code_sha256"])
    assert cal.calibration_binding_matches(old, new)
    assert cal.calibration_binding_matches(new, new)
    assert not cal.calibration_binding_matches(new, old)
    assert not cal.calibration_binding_matches(dict(old, seed=20261112), new)
    assert not cal.calibration_binding_matches(dict(old, null_n=20001), new)
    assert not cal.calibration_binding_matches(dict(old, code_sha256="unreviewed"), new)


@pytest.mark.skipif(os.name != "nt", reason="Windows workstation commit query")
def test_commit_query_returns_a_finite_percentage():
    assert 0 <= cal.v2_commit_percent() <= 100
