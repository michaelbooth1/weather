"""Maker replay v2 universe rule as declared intervals (U1, W7): panel constants, Austin 2026-10-03.

Fictional bundles only (``fixtures/panel_v02.py``): real panel dates, invented data.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import inspect
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import calibration
from maker_core.replay.bundle import BundleError
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2 import intervals, lockstep, panel, universe_v02
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.pipeline import run_passes
from maker_core.replay.v2.pull import candidate_minutes, windows_by_condition
from maker_core.replay.v2.report import build_report
from .fixtures.panel_v02 import AUSTIN_TARGET, PANEL_DAYS, Panel, cid_of

UTC = timezone.utc
AUSTIN_DATES = tuple(date(2026, 10, d) for d in (1, 2, 3, 4))
V2 = Path(intervals.__file__).parent


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=UTC)


def iso(value):
    return value.isoformat()


def write(tmp_path, fixture, days, *, provenance="synthetic", name="b"):
    return [open_stream_bundle(fixture.write(tmp_path / name / d.isoformat(), d, provenance=provenance))
            for d in days]


def evaluate(bundles, inventory, panel_name="registered"):
    return intervals.evaluate(universe_v02.day_inputs(bundles), inventory, panel=panel_name)


@pytest.fixture(scope="module")
def registered(tmp_path_factory):
    fixture = Panel()
    bundles = write(tmp_path_factory.mktemp("panel"), fixture, PANEL_DAYS)
    inventory = fixture.inventory(PANEL_DAYS)
    return fixture, bundles, inventory, evaluate(bundles, inventory)


def windows_of(result, cid, day=None):
    return [(w["start"], w["end"]) for w in result.windows
            if w["condition_id"] == cid and (day is None or w["date"] == day.isoformat())]


def reasons_of(result, cid, day):
    return {e["reason"]: e["seconds"] for e in result.exclusions
            if e["condition_id"] == cid and e["date"] == day.isoformat()}


# -- the three mandated Austin 2026-10-03 tests -------------------------------------------------------------

def test_austin_2026_10_03_has_no_active_interval_on_any_panel_date(registered):
    fixture, bundles, inventory, result = registered
    austin = fixture.austin_excluded(PANEL_DAYS)
    assert len(austin) == 2  # two bands of the one event
    assert not [w for w in result.windows if w["condition_id"] in austin]
    seen = {(b.day, c.condition_id) for b in bundles for c in b.conditions if c.condition_id in austin}
    assert {d for d, _ in seen} == set(AUSTIN_DATES)  # discovered 10-01 at horizon 2, gone after 10-04 05:00Z
    owner_rows = [e for e in result.exclusions if e["condition_id"] in austin]
    # one OWNER_EXCLUDED_PRIOR_READ row per (date, condition), covering every second: the reason outranks
    # maintenance and horizon
    assert {(date.fromisoformat(e["date"]), e["condition_id"]) for e in owner_rows} == seen
    assert all(e["reason"] == "OWNER_EXCLUDED_PRIOR_READ" and e["seconds"] == 86400 for e in owner_rows)
    assert len(owner_rows) == len(seen)
    # Austin target 10-04 and Toronto target 10-03 keep their T+1/T+2 windows on the same dates
    austin_next = cid_of("austin", date(2026, 10, 4), 0)
    toronto_same = cid_of("toronto", AUSTIN_TARGET, 0)
    assert windows_of(result, austin_next, date(2026, 10, 2)) == [
        (iso(at(date(2026, 10, 2), 8)), iso(at(date(2026, 10, 3), 0)))]  # T+2 from local midnight (05:00Z)
    assert windows_of(result, austin_next, date(2026, 10, 3)) == [
        (iso(at(date(2026, 10, 3), 0, 4)), iso(at(date(2026, 10, 3), 5))),
        (iso(at(date(2026, 10, 3), 8)), iso(at(date(2026, 10, 4), 0)))]
    assert windows_of(result, toronto_same, date(2026, 10, 2))
    assert result.owner_exclusions == [dict(
        market_id="austin", target_date="2026-10-03", close_at_utc="2026-10-04T05:00:00+00:00",
        reason="OWNER_EXCLUDED_PRIOR_READ", source="DECISION_LOG 2026-10-05",
        event_slug="highest-temperature-in-austin-on-october-3-2026", matched_conditions=austin)]


def test_owner_exclusion_cannot_be_overridden_silently(registered, tmp_path, monkeypatch):
    fixture, bundles, inventory, result = registered
    austin = fixture.austin_excluded(PANEL_DAYS)
    day = date(2026, 10, 2)
    # (a) the sanctioned source path takes no windows at all (MF4): it derives them, and they equal evaluate's;
    # a hand-built captured plan without declared windows refuses on its own (MF2)
    derived, evaluation = intervals.sources(bundles, inventory, panel="registered")
    assert evaluation.windows == result.windows
    assert not [cid for s in derived for cid in s.plan.windows if cid in austin]
    b = bundles[PANEL_DAYS.index(day)]
    with pytest.raises(BundleError, match="captured_bundle_requires_declared_intervals"):
        lockstep.DayPlan(b.day, b.conditions, lockstep.windows_of(b.conditions, None), {}, "captured", {})
    # (b) the constant is load-bearing: remove it and the same bundles give Austin 10-03 windows
    monkeypatch.setattr(panel, "OWNER_EXCLUSIONS", ())
    open_rule = evaluate(bundles, inventory)
    assert any(w["condition_id"] in austin for w in open_rule.windows)
    assert open_rule.windows != result.windows
    monkeypatch.undo()
    # (c) no public function takes a parameter that could replace the exclusions or the panel constants
    for function, expected in ((intervals.active_intervals, ["days", "inventory", "panel", "check"]),
                               (intervals.evaluate, ["days", "inventory", "panel", "check"]),
                               (intervals.sources, ["bundles", "inventory", "panel", "check"]),
                               (universe_v02.check_inventory, ["days", "inventory", "check"])):
        names = list(inspect.signature(function).parameters)
        assert names == expected
        assert not any("exclu" in n for n in names)
    # (d) an inventory and bundles without the Austin 10-03 rows: refused, the owner knows it existed
    pruned = Panel(omit=austin)
    pruned_bundles = write(tmp_path, pruned, AUSTIN_DATES, name="pruned")
    with pytest.raises(BundleError, match="owner_exclusion_unmatched"):
        evaluate(pruned_bundles, pruned.inventory(AUSTIN_DATES))
    # (e) the market ID is a registry ID: tests/market/test_maker_replay_universe_v02.py (core imports no weather)
    # (f) the panel is a name, never an object
    for bad in ("Registered", "panel", None, object(), panel, ("registered",)):
        with pytest.raises(BundleError, match="unknown_panel"):
            evaluate(bundles, inventory, bad)


def test_excluded_market_date_is_never_scored(tmp_path, monkeypatch):
    """A-defender M1's corrected statement of plan test 3.

    The Austin 10-03 records still flow through the shared parse: the bundle keeps every condition
    (reg §4), and the engine wakes any condition whose record signature changes, active or not, so the
    aggregate ``wakes`` and the trace exclusions may differ. "Never scored" means: no decision, interval,
    fill, band-day row, state or covered run, clock window or pull candidate, and every scored output
    (band days, scores, intervals, pull cells, quote presence) byte-equal to a run with those records
    deleted.
    """
    days = AUSTIN_DATES[1:]  # 10-02..10-04: T+1 on 10-02/10-03 and T+0 on 10-04
    options = dict(bands=1, step=1, full=True, capture_minutes=range(0, 600))
    fixture = Panel(**options)
    austin = fixture.austin_excluded(days)
    names = []
    real_stream = universe_v02._stream
    monkeypatch.setattr(universe_v02, "_stream", lambda b, ref, *a: names.append(ref.name) or real_stream(b, ref, *a))
    bundles = write(tmp_path, fixture, days, provenance="captured")
    windows, _ = intervals.active_intervals(universe_v02.day_inputs(bundles), fixture.inventory(days),
                                            panel="registered")
    assert set(names) == {"descriptor.jsonl"}  # the rule read only descriptor streams after pass one
    with monkeypatch.context() as patched:  # not vacuous: without the constant Austin 10-03 is active here
        patched.setattr(panel, "OWNER_EXCLUSIONS", ())
        unexcluded, _ = intervals.active_intervals(universe_v02.day_inputs(bundles), fixture.inventory(days),
                                                   panel="registered")
        assert {w["date"] for w in unexcluded if w["condition_id"] in austin} == {"2026-10-02", "2026-10-03"}
    config = V2Config(hazard_per_minute=.001, keep=True)
    derived, evaluation = intervals.sources(bundles, fixture.inventory(days), panel="registered")
    assert evaluation.windows == windows
    run = run_passes(derived, config)
    assert set(names) == {"descriptor.jsonl"}  # scoring reads through records(), not the descriptor helper
    scored_somewhere = False
    for bound, passes in run.passes.items():
        for policy, p in passes.items():
            engine, scorer = p.engine, p.scorer
            assert not [d for d in engine.decisions if d.condition_id in austin]
            assert not [i for i in engine.intervals if i.condition_id in austin]
            assert not [f for f in engine.fills if f.condition_id in austin]
            assert not [k for k in scorer.rows if k[1] in austin]
            for runs in (scorer.state_runs, scorer.covered_runs):
                assert runs is None or not any(runs.get(cid) for cid in austin)
            assert not [w for w in engine.config.clock_pulls if w[0] in austin]
            scored_somewhere |= bool(engine.decisions) and bool(scorer.rows)
    assert scored_somewhere  # the other conditions are decided and scored
    by_condition = windows_by_condition(run.plan)
    assert not any(by_condition.get(cid) for cid in austin)
    assert not [m for cid in austin for m in candidate_minutes(by_condition.get(cid, ()))]
    report, _ = build_report(run, config, replicates=100)
    twin = Panel(omit=austin, **options)
    twin_bundles = write(tmp_path, twin, days, provenance="captured", name="deleted")
    # the twin has no Austin 10-03 rows, so it cannot pass the registered rule; it gets the same windows directly
    twin_sources = [lockstep.stream_source(b, intervals.windows_for(windows, b.day)) for b in twin_bundles]
    twin_report, _ = build_report(run_passes(twin_sources, config), config, replicates=100)
    for bound in report["bounds"]:
        mine, theirs = report["bounds"][bound], twin_report["bounds"][bound]
        for key in ("band_days", "scores", "intervals", "quote_presence"):
            assert canonical_bytes(mine[key]) == canonical_bytes(theirs[key]), (bound, key)
        assert canonical_bytes(mine["pull_efficiency"]["cells"]) == canonical_bytes(
            theirs["pull_efficiency"]["cells"])
        assert any(r["condition_id"] not in austin for rows in mine["band_days"].values() for r in rows)


# -- the rule ------------------------------------------------------------------------------------------------

def test_every_condition_second_is_counted_once_with_one_reason(registered):
    _, bundles, _, result = registered
    totals = defaultdict(int)
    for w in result.windows:
        totals[(w["date"], w["condition_id"])] += int((datetime.fromisoformat(w["end"])
                                                       - datetime.fromisoformat(w["start"])).total_seconds())
    keys = defaultdict(list)
    for e in result.exclusions:
        totals[(e["date"], e["condition_id"])] += e["seconds"]
        keys[(e["date"], e["condition_id"])].append(e["reason"])
    expected = {(b.day.isoformat(), c.condition_id) for b in bundles for c in b.conditions}
    assert set(totals) == expected and set(totals.values()) == {86400}
    assert all(len(v) == len(set(v)) and v == sorted(v, key=intervals.REASONS.index) for v in keys.values())


def test_settlement_only_dates_have_no_windows_and_settlements_are_consumed(registered, tmp_path):
    _, bundles, _, result = registered
    for day in panel.SETTLEMENT_ONLY_DATES:
        assert not [w for w in result.windows if w["date"] == day.isoformat()]
        rows = [e for e in result.exclusions if e["date"] == day.isoformat()]
        assert rows and {e["reason"] for e in rows} == {"SETTLEMENT_ONLY"}
    days = (date(2026, 10, 13), *panel.SETTLEMENT_ONLY_DATES)
    fixture = Panel(markets=("toronto",), bands=1, step=5, full=True, capture_minutes=range(0, 300))
    full = write(tmp_path, fixture, days, provenance="captured")
    derived, evaluation = intervals.sources(full, fixture.inventory(days), panel="registered")
    assert {w["date"] for w in evaluation.windows} == {"2026-10-13"}
    run = run_passes(derived, V2Config(hazard_per_minute=.001))
    settled = run.passes["strictly_through"]["no_quote"].engine.settlements
    assert {cid for cid in settled} >= {cid_of("toronto", date(2026, 10, 13), 0),
                                        cid_of("toronto", date(2026, 10, 14), 0)}


def test_target_after_last_panel_target_is_excluded_but_kept_in_inventory(registered):
    _, _, inventory, result = registered
    late = cid_of("toronto", date(2026, 10, 15), 0)  # T+2 on 10-13
    assert any(r["condition_id"] == late for r in inventory)
    assert not windows_of(result, late)
    assert reasons_of(result, late, date(2026, 10, 13)) == {"TARGET_AFTER_PANEL": 86400}


def test_toronto_horizon_roll_stale_minutes_and_first_minute_after_descriptor(registered):
    """Toronto's local midnight is 04:00Z (EDT), outside maintenance (A-defender M5)."""
    _, _, _, result = registered
    day = date(2026, 10, 5)
    rolling = cid_of("toronto", day, 0)  # T+1 until 04:00Z, then T+0; next capture 04:03:20
    # minutes 04:00..04:03 keep the stale horizon-1 descriptor (the literal rule); 04:04 is the first minute
    # after the horizon-0 descriptor and is excluded
    assert windows_of(result, rolling, day) == [(iso(at(day, 0, 4)), iso(at(day, 4, 4)))]
    reasons = reasons_of(result, rolling, day)
    assert reasons["HORIZON_OUTSIDE_1_2"] == 86400 - 4 * 3600 - 3 * 3600 - 4 * 60  # less missing, active, maintenance
    assert reasons["MISSING_DESCRIPTOR"] == 4 * 60  # 00:00..00:04 before the day's first capture
    assert reasons["MAINTENANCE_UTC"] == 3 * 3600
    assert [d for d in result.diagnostics if d["condition_id"] == rolling and d["date"] == day.isoformat()] == [
        dict(date=day.isoformat(), condition_id=rolling, reason=intervals.STALE, seconds=240)]


def test_austin_windows_at_the_05_00_boundary(registered):
    """Austin's local midnight (CDT) is exactly the maintenance start: T+1 -> T+0 and maintenance coincide."""
    _, _, _, result = registered
    day = date(2026, 10, 4)
    rolling = cid_of("austin", day, 0)
    assert windows_of(result, rolling, day) == [(iso(at(day, 0, 4)), iso(at(day, 5)))]
    assert reasons_of(result, rolling, day) == {"MAINTENANCE_UTC": 3 * 3600, "MISSING_DESCRIPTOR": 240,
                                                "HORIZON_OUTSIDE_1_2": 16 * 3600}
    t2 = cid_of("austin", date(2026, 10, 5), 0)  # T+2 until 05:00Z, then T+1 after maintenance
    assert windows_of(result, t2, day) == [(iso(at(day, 0, 4)), iso(at(day, 5))),
                                           (iso(at(day, 8)), iso(at(day + timedelta(days=1), 0)))]


def test_undecodable_descriptor_refuses_as_in_v1(tmp_path):
    """Master-agent steer on A-defender N2: an undecodable descriptor is never skipped silently."""
    day = date(2026, 10, 7)
    target = cid_of("toronto", date(2026, 10, 8), 0)
    fixture = Panel(markets=("toronto",), bands=1, invalid_at={target: at(day, 12)})
    bundles = write(tmp_path, fixture, (day,))
    with pytest.raises(BundleError, match="universe_descriptor_undecodable"):
        evaluate(bundles, fixture.inventory((day,)))
    with pytest.raises(BundleError, match="universe_descriptor_undecodable"):
        intervals.sources(bundles, fixture.inventory((day,)), panel="registered")


def test_calibration_panel_has_no_target_cap_and_no_settlement_only(tmp_path):
    fixture = Panel(bands=1)
    bundles = write(tmp_path, fixture, panel.CALIBRATION_DATES)
    result = evaluate(bundles, fixture.inventory(panel.CALIBRATION_DATES), "calibration")
    assert {e["reason"] for e in result.exclusions} <= {"MAINTENANCE_UTC", "MISSING_DESCRIPTOR", "HORIZON_OUTSIDE_1_2"}
    assert result.owner_exclusions[0]["matched_conditions"] == []
    assert {w["date"] for w in result.windows} == {d.isoformat() for d in panel.CALIBRATION_DATES}
    with pytest.raises(BundleError, match="day_outside_panel"):
        evaluate(bundles, fixture.inventory(panel.CALIBRATION_DATES), "registered")


def test_calibration_panel_refuses_any_owner_excluded_match(tmp_path, monkeypatch):
    """Owner Q1 tightening: on "calibration" an owner exclusion must match nothing."""
    fixture = Panel(bands=1)
    bundles = write(tmp_path, fixture, AUSTIN_DATES)
    monkeypatch.setattr(panel, "CALIBRATION_DATES", AUSTIN_DATES)
    with pytest.raises(BundleError, match="owner_exclusion_matched_outside_span"):
        evaluate(bundles, fixture.inventory(AUSTIN_DATES), "calibration")


def test_panel_days_refused_outside_the_named_panel_and_duplicated(registered, tmp_path):
    fixture, bundles, inventory, _ = registered
    with pytest.raises(BundleError, match="day_outside_panel"):
        evaluate(bundles[:2], fixture.inventory(PANEL_DAYS[:2]), "calibration")
    with pytest.raises(BundleError, match="duplicate_panel_day"):
        evaluate([bundles[0], bundles[0]], fixture.inventory(PANEL_DAYS[:1]))


# -- the two independent keys (A-defender M4) -------------------------------------------------------------

def relabel(inventory, cids, target="2026-10-04"):
    return [dict(r, target_date=target) if r["condition_id"] in cids else r for r in inventory]


def test_relabelled_inventory_row_is_refused_even_without_the_inventory_check(registered, monkeypatch):
    fixture, bundles, inventory, _ = registered
    austin = fixture.austin_excluded(PANEL_DAYS)
    edited = relabel(inventory, austin)
    with pytest.raises(BundleError, match="universe_target_descriptor_mismatch"):
        evaluate(bundles, edited)
    monkeypatch.setattr(universe_v02, "check_inventory", lambda days, inv, check=None: {r["condition_id"]: r for r in inv})
    with pytest.raises(BundleError, match="owner_exclusion_key_disagreement"):
        evaluate(bundles, edited)
    with pytest.raises(BundleError, match="owner_exclusion_key_disagreement"):  # partial: one band relabelled
        evaluate(bundles, relabel(inventory, austin[:1]))


def test_descriptor_close_disagreeing_with_inventory_is_refused(tmp_path, monkeypatch):
    austin = cid_of("austin", AUSTIN_TARGET, 0)
    fixture = Panel(close_override={austin: datetime(2026, 10, 5, 5, tzinfo=UTC)})
    bundles = write(tmp_path, fixture, AUSTIN_DATES)
    monkeypatch.setattr(universe_v02, "check_inventory", lambda days, inv, check=None: {r["condition_id"]: r for r in inv})
    with pytest.raises(BundleError, match="owner_exclusion_key_disagreement"):
        evaluate(bundles, fixture.inventory(AUSTIN_DATES))


def test_second_austin_event_with_another_slug_refuses_the_whole_build(tmp_path):
    """MF5 supersedes A-defender M4's "fully excluded": the literal slug key no longer selects the second
    event's conditions, so the three keys disagree and nothing is built (fail-closed; no window at all)."""
    fixture = Panel(second_austin_event=True)
    bundles = write(tmp_path, fixture, AUSTIN_DATES)
    assert len(fixture.austin_excluded(AUSTIN_DATES)) == 4
    with pytest.raises(BundleError, match="owner_exclusion_key_disagreement"):
        evaluate(bundles, fixture.inventory(AUSTIN_DATES))


def test_same_close_time_in_another_market_is_not_excluded(tmp_path):
    fixture = Panel(markets=("austin", "dallas", "toronto"), bands=1)
    bundles = write(tmp_path, fixture, AUSTIN_DATES)
    result = evaluate(bundles, fixture.inventory(AUSTIN_DATES))
    dallas = cid_of("dallas", AUSTIN_TARGET, 0)
    assert windows_of(result, dallas, date(2026, 10, 2))
    assert dallas not in result.owner_exclusions[0]["matched_conditions"]


SLUG = "highest-temperature-in-austin-on-october-3-2026"


@pytest.mark.parametrize("row", [
    ("austin", "2026-10-03", datetime(2026, 10, 4, 5, tzinfo=UTC), "OWNER_EXCLUDED_PRIOR_READ", "x", SLUG),
    ("austin", datetime(2026, 10, 3), datetime(2026, 10, 4, 5, tzinfo=UTC), "OWNER_EXCLUDED_PRIOR_READ", "x", SLUG),
    ("austin", date(2026, 10, 3), datetime(2026, 10, 4, 5), "OWNER_EXCLUDED_PRIOR_READ", "x", SLUG),
    ("austin", date(2026, 10, 3), "2026-10-04T05:00:00Z", "OWNER_EXCLUDED_PRIOR_READ", "x", SLUG),
    ("austin", date(2026, 10, 3), datetime(2026, 10, 4, 5, tzinfo=UTC), "MAINTENANCE_UTC", "x", SLUG),
    ("austin", date(2026, 10, 3), datetime(2026, 10, 4, 5, tzinfo=UTC), "OWNER_EXCLUDED_PRIOR_READ", "x", None),
    ("austin", date(2026, 10, 3), datetime(2026, 10, 4, 5, tzinfo=UTC), "OWNER_EXCLUDED_PRIOR_READ", "x"),
])
def test_type_mismatched_exclusion_constant_is_refused(registered, monkeypatch, row):
    _, bundles, inventory, _ = registered
    monkeypatch.setattr(panel, "OWNER_EXCLUSIONS", (row,))
    with pytest.raises(BundleError, match="owner_exclusion_constant_invalid"):
        evaluate(bundles, inventory)


def test_panel_constants():
    assert panel.CALIBRATION_DATES == calibration.CALIBRATION_DATES
    assert len(panel.QUOTE_DATES) == 14 and panel.QUOTE_DATES[0] == date(2026, 9, 30)
    assert panel.QUOTE_DATES[-1] == date(2026, 10, 13)
    assert panel.GATED_DAYS == tuple(date(2026, 9, 30) + timedelta(days=i) for i in range(16))
    # U6 export_gate: GATE_FIRST_UTC 2026-09-30, GATE_END_UTC 2026-10-16 exclusive (dates pinned, no import)
    gate_first, gate_end = datetime(2026, 9, 30, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC)
    assert set(panel.GATED_DAYS) == {gate_first.date() + timedelta(days=n) for n in range((gate_end - gate_first).days)}
    assert panel.OWNER_EXCLUSIONS[0].event_slug == "highest-temperature-in-austin-on-" + "october-3-2026"
    assert (panel.GATED_FIRST, panel.GATED_LAST) == (date(2026, 9, 30), date(2026, 10, 15))
    assert panel.LAST_TARGET_DATE == date(2026, 10, 14)
    row = panel.OWNER_EXCLUSIONS[0]
    local_close = datetime.combine(row.target_date + timedelta(days=1), time(), tzinfo=ZoneInfo("America/Chicago"))
    assert row.close_at_utc == local_close.astimezone(UTC) == datetime(2026, 10, 4, 5, tzinfo=UTC)
    assert intervals.owner_exclusions() == panel.OWNER_EXCLUSIONS


# -- the source path (A-defender M3) -----------------------------------------------------------------------

def test_captured_bundle_requires_declared_intervals(tmp_path):
    fixture = Panel(markets=("toronto",), bands=1, step=60)
    captured = write(tmp_path, fixture, (date(2026, 10, 7),), provenance="captured", name="c")[0]
    synthetic = write(tmp_path, fixture, (date(2026, 10, 7),), name="s")[0]
    with pytest.raises(BundleError, match="captured_bundle_requires_declared_intervals"):
        lockstep.stream_source(captured)
    assert lockstep.stream_source(captured, ()).plan.declared
    assert not lockstep.stream_source(synthetic).plan.declared


def test_sources_refuse_a_bundle_without_a_descriptor_stream(tmp_path):
    day = date(2026, 10, 7)
    fixture = Panel(markets=("toronto",), bands=1, step=60, full=True, capture_minutes=range(0, 120))
    folder = fixture.write(tmp_path / "x", day, provenance="captured")
    manifest = json.loads((folder / "bundle.json").read_bytes())
    manifest["streams"] = [s for s in manifest["streams"] if s["path"] != "descriptor.jsonl"]
    (folder / "descriptor.jsonl").unlink()
    (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
    bundle = open_stream_bundle(folder)
    with pytest.raises(BundleError, match="universe_descriptor_stream_missing"):
        intervals.sources([bundle], fixture.inventory((day,)), panel="registered")


def test_only_the_sanctioned_modules_name_the_raw_source_constructors():
    """A lint (the invariant itself is ``DayPlan.__post_init__``): under src/ and tools/, only the listed files
    name the raw plan constructors, in code or in a string (getattr/vars), or import lockstep dynamically."""
    root = V2.parents[3]
    allowed = {"src/maker_core/replay/v2/lockstep.py", "src/maker_core/replay/v2/intervals.py",
               "tools/research/maker_replay_v2/sources.py"}
    raw = re.compile(r"\b(stream_source|bundle_source|DayPlan|windows_of)\b")
    offenders = []
    for path in sorted([*(root / "src").rglob("*.py"), *(root / "tools").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root).as_posix()
        replay = relative.startswith(("src/maker_core/replay/", "tools/research/maker_replay_v2/"))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found |= bool(raw.fullmatch(node.id))
            elif isinstance(node, ast.Attribute):
                found |= bool(raw.fullmatch(node.attr))
            elif isinstance(node, ast.ImportFrom):
                found |= any(raw.fullmatch(a.name) for a in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found |= bool(raw.search(node.value))
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name in ("importlib.import_module", "import_module", "__import__"):
                    arg = node.args[0] if node.args else None
                    # a computed module name is flagged only in the replay packages, where it could hide lockstep
                    found |= (not isinstance(arg, ast.Constant) and replay) or (
                        isinstance(arg, ast.Constant) and "lockstep" in str(arg.value))
        if found and relative not in allowed:
            offenders.append(relative)
    assert offenders == []


def test_descriptor_helper_reads_only_the_descriptor_stream(registered, monkeypatch):
    _, bundles, _, _ = registered
    names = []
    real = universe_v02._stream
    monkeypatch.setattr(universe_v02, "_stream", lambda b, ref, *a: names.append(ref.name) or real(b, ref, *a))
    records = universe_v02.descriptors(bundles[3])
    assert names == ["descriptor.jsonl"] and records and {r.kind for r in records} == {"descriptor"}
