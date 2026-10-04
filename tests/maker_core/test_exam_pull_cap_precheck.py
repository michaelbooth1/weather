"""Fixture tests for tools/exam_pull_cap_precheck.py; fictional bundle manifests only."""
from datetime import date, datetime, timedelta, timezone
import json
import sys

import pytest

from tools import exam_pull_cap_precheck as precheck

CALIBRATION_DATES = tuple(date(2026, 9, d) for d in (27, 28, 29))
# Heap pops of one full fictional calibration day at D = 12 (measured with the exam tree's engine,
# docs/roadmap/agent-report-2026-10-03-pull-cap-precheck.md): 88a density with one reward row per
# selected condition per minute, and the same day without per-condition reward clocks.
POPS_88A_DENSITY, POPS_WITHOUT_REWARD_CLOCKS = 38_281, 4_454
MEASURED_FIELDS = dict(input_bytes=1, records=1, decisions_spans=1, report_bytes=1, runtime_seconds=1.0,
                       peak_memory_above_baseline_bytes=1, baseline_memory_bytes=1)


def _day(root, day, conditions=12):
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    folder = root / day.isoformat() / "bundle"
    folder.mkdir(parents=True)
    rows = [dict(condition_id=f"c{day:%m%d}-{k:02d}", market_id=f"city{k:02d}", domain_id="fictional",
                 active_from=start.isoformat(), active_until=(start + timedelta(days=1)).isoformat())
            for k in range(conditions)]
    (folder / "bundle.json").write_text(json.dumps(dict(format="fixture", day=day.isoformat(), conditions=rows,
                                                        streams=[])))
    return folder, [(r["condition_id"], (day + timedelta(days=k % 3)).isoformat()) for k, r in enumerate(rows)]


def _panel(root):
    folders, universe = [], []
    for day in (*precheck.QUOTE_DATES, precheck.SETTLEMENT_DATE):
        folder, targets = _day(root, day)
        folders.append(folder)
        universe += [dict(condition_id=c, target_date=t) for c, t in targets]
    (root / "universe.json").write_text(json.dumps(universe))
    return folders


def _measurement(root, events):
    per_date = {d.isoformat(): dict(MEASURED_FIELDS, engine_events=e) for d, e in zip(CALIBRATION_DATES, events)}
    ceiling = precheck.ceiling_from_rehearsals({d: m["engine_events"] for d, m in per_date.items()})
    path = root / f"measurement-{max(events)}.json"
    path.write_text(json.dumps(dict(per_date=per_date, derived=dict(ceilings=dict(engine_events=ceiling)))))
    return path


def _run(capsys, argv):
    code = precheck.main(argv)
    lines = capsys.readouterr().out.strip().splitlines()
    return code, json.loads("\n".join(line for line in lines if not line.startswith(("panel:", "projection:"))))


def test_minute_count_matches_the_exam_preflight_on_unaligned_windows():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    at = lambda seconds: start + timedelta(seconds=seconds)  # noqa: E731
    windows = {"a": [(at(30), at(615)), (at(300), at(1200)), (at(1200), at(1290))],
               "b": [(at(61), at(119)), (at(600), at(1800))]}
    # Same windows and expected count as the exam tree's own preflight test (21 + 0 + 20).
    assert precheck.opportunity_candidates(windows) == 41


def test_full_day_panel_passes_at_88a_density_and_refuses_without_reward_clocks(tmp_path, capsys):
    bundles = [arg for folder in _panel(tmp_path) for arg in ("--bundle", str(folder))]
    common = [*bundles, "--universe", str(tmp_path / "universe.json"), "--allow-without-exam-tree"]
    # 13 quote dates x 12 bands + 8 bands on 10-13 (horizon 2 targets 10-15), 1,260 minutes each.
    expected = (13 * 12 + 8) * 1260
    dense = _measurement(tmp_path, (POPS_88A_DENSITY, POPS_88A_DENSITY // 2, POPS_88A_DENSITY))
    code, out = _run(capsys, [*common, "--ceiling-measurement", str(dense)])
    assert code == precheck.PASS
    assert out["panel"]["candidates"] == expected and out["panel"]["count_kind"] == "exact"
    assert out["max_events"] == 2**20 and out["panel"]["verdict"] == "PREFLIGHT_WOULD_PASS"
    assert out["panel"]["complete"] is True
    sparse = _measurement(tmp_path, (POPS_WITHOUT_REWARD_CLOCKS,) * 3)
    code, out = _run(capsys, [*common, "--ceiling-measurement", str(sparse)])
    assert code == precheck.REFUSE
    assert out["max_events"] == 2**17 and out["panel"]["ratio"] == expected / 2**17 > 1.5
    # Without the universe, bands targeting past the settlement date stay counted: an upper bound.
    code, out = _run(capsys, [*bundles, "--allow-without-exam-tree", "--max-events", str(expected)])
    assert out["panel"]["candidates"] == 14 * 12 * 1260 and out["panel"]["count_kind"] == "upper_bound_without_universe"
    assert code == precheck.REFUSE


def test_refuses_a_ceiling_that_is_not_rule_derived_and_a_missing_exam_tree(tmp_path, capsys, monkeypatch):
    folders = _panel(tmp_path)
    bad = tmp_path / "bad.json"
    per_date = {d.isoformat(): dict(engine_events=10) for d in CALIBRATION_DATES}
    bad.write_text(json.dumps(dict(per_date=per_date, derived=dict(ceilings=dict(engine_events=2**30)))))
    code, out = _run(capsys, ["--bundle", str(folders[0]), "--ceiling-measurement", str(bad),
                              "--allow-without-exam-tree"])
    assert code == precheck.ERROR and "not_rule_derived" in out["error"]
    monkeypatch.setitem(sys.modules, "maker_core.replay.pull_efficiency", None)
    code, out = _run(capsys, ["--bundle", str(folders[0]), "--max-events", "10"])
    assert code == precheck.ERROR and "exam_tree_not_on_pythonpath" in out["error"]


def test_calibration_projection_from_rehearsals_alone(tmp_path, capsys):
    calibration = [_day(tmp_path, d, conditions=12 * 6)[0] for d in CALIBRATION_DATES]
    rehearsals = []
    for day in CALIBRATION_DATES:
        path = tmp_path / f"rehearsal-{day}.json"
        path.write_text(json.dumps(dict(date=day.isoformat(), measured=dict(engine_events=POPS_88A_DENSITY))))
        rehearsals += ["--rehearsal", str(path)]
    code, out = _run(capsys, [arg for f in calibration for arg in ("--calibration-bundle", str(f))] + rehearsals)
    projection = out["projection"]
    assert projection["candidates"] == 14 * 72 * 1260 and projection["max_events"] == 2**20
    assert projection["per_date"]["2026-09-27"]["candidates_per_heap_pop"] == 72 * 1260 / POPS_88A_DENSITY
    assert code == precheck.REFUSE  # A sixfold daily union at the same heap pops crosses the ceiling.


def test_exam_tree_recount_agrees(tmp_path, capsys):
    pytest.importorskip("maker_core.replay.pull_efficiency")
    from maker_core.replay import ceilings
    folders = _panel(tmp_path)
    per_date = {d.isoformat(): dict(MEASURED_FIELDS, engine_events=POPS_88A_DENSITY) for d in CALIBRATION_DATES}
    path = tmp_path / "exam-measurement.json"
    path.write_text(json.dumps(dict(per_date=per_date, derived=ceilings.derive(per_date))))
    code, out = _run(capsys, [arg for f in folders for arg in ("--bundle", str(f))]
                     + ["--universe", str(tmp_path / "universe.json"), "--ceiling-measurement", str(path)])
    assert code == precheck.PASS and out["panel"]["exam_tree"]["status"] == "AGREES"
