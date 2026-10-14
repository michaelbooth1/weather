"""SPECULATIVE option M (pending owner M/X; do not land): C15 manifest builder and A8 on the §4 minute rule.

Guards: T1 report 6 option M (registration draft §4 "active at UTC minute t", C15 row A8 sentence, §4 gate-ordering
disclosure); the unsigned text edits are in docs/research/maker-replay-v2-C15-A8-option-M-UNSIGNED-DRAFT.md.
Fictional fixtures only; never a captured day.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from types import SimpleNamespace

import pytest

from maker_core.replay import execution_manifest
from maker_core.replay.v2 import horizon, lockstep, panel

from .test_replay_v2_horizon import iso, manifest_case, utc
from .test_replay_v2_intervals import ZONES, reasons_of, registered, windows_of  # noqa: F401  (module fixture)

A8_FIXTURES = ("dense-09-27", "dense-11-01-dst", "w0-09-27-roll", "w2-on-level")  # attribution.fixtures()


def test_minute_lines_round_each_read_up_to_its_minute_start_and_keep_the_order():
    lines = {"c": [(utc(2026, 11, 1, 0, 3, 20), 2), (utc(2026, 11, 1, 0, 3, 40), None),
                   (utc(2026, 11, 1, 4), 1), (utc(2026, 11, 1, 4, 0, 0, 1), 0)]}
    assert horizon.minute_lines(lines) == {"c": [(utc(2026, 11, 1, 0, 4), 2), (utc(2026, 11, 1, 0, 4), None),
                                                 (utc(2026, 11, 1, 4), 1), (utc(2026, 11, 1, 4, 1), 0)]}
    # several reads in one minute: the last holds at the minute start, as ``runs`` reads one instant
    assert horizon.runs(horizon.minute_lines(lines)["c"], utc(2026, 11, 1), utc(2026, 11, 1, 5)) == [
        (utc(2026, 11, 1), utc(2026, 11, 1, 4), horizon.MISSING), (utc(2026, 11, 1, 4), utc(2026, 11, 1, 4, 1), None),
        (utc(2026, 11, 1, 4, 1), utc(2026, 11, 1, 5), horizon.OUTSIDE)]


def test_the_manifest_window_opens_at_the_minute_start_after_a_mid_minute_first_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_manifest, "SETTLEMENT_DATE", date(2026, 11, 30))
    windows, excluded = manifest_case(tmp_path, date(2026, 11, 22), [(utc(2026, 11, 20, 14, 3, 20), 2)],
                                      [date(2026, 11, 20)])  # 09:03:20 EST: lead 2
    assert [(w["start"], w["end"]) for w in windows] == [(iso(2026, 11, 20, 14, 4), iso(2026, 11, 21))]
    assert [(e["reason"], e["start"], e["end"]) for e in excluded] == [
        ("missing_descriptor", iso(2026, 11, 20), iso(2026, 11, 20, 14, 4))]


def test_mutant_exact_instant_manifest_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(horizon, "minute_lines", lambda lines: lines)
    with pytest.raises(AssertionError):
        test_the_manifest_window_opens_at_the_minute_start_after_a_mid_minute_first_capture(tmp_path, monkeypatch)


def test_the_manifest_construction_gives_the_intervals_windows_on_the_registered_fixture_panel(registered):
    """One §4 rule: ``execution_manifest.active_intervals`` itself (called, not re-implemented) equals
    ``intervals.evaluate`` on every eligible (date, condition). The inline exact-instant split is only the
    comparison that shows the minute rule is exercised (it differs), and its minute form must equal the manifest."""
    _, bundles, inventory, result = registered
    # the panel is v0.2 stream bundles; ``active_intervals`` reads a v0.1-shaped ``records`` attribute, so hand it
    # each day's records already read (the same records, the same conditions; ``descriptor_source`` takes either)
    v01_shaped = [SimpleNamespace(day=b.day, conditions=b.conditions, records=tuple(b.records()),
                                  coverage_groups=b.coverage_groups, provenance=b.provenance) for b in bundles]
    manifest_windows, _ = execution_manifest.active_intervals(v01_shaped, inventory)
    manifest = {}
    for w in manifest_windows:
        manifest.setdefault((w["date"], w["condition_id"]), []).append((w["start"], w["end"]))
    lines = horizon.timelines([lockstep.descriptor_source(b) for b in bundles], ZONES)
    minute_lines = horizon.minute_lines(lines)
    owner = {cid for row in result.owner_exclusions for cid in row["matched_conditions"]}
    checked = differs = 0
    for b in bundles:
        if b.day in panel.SETTLEMENT_ONLY_DATES:
            continue
        m0 = utc(b.day.year, b.day.month, b.day.day, 5)
        m1 = m0 + timedelta(hours=3)
        for c in b.conditions:
            if c.condition_id in owner or reasons_of(result, c.condition_id, b.day).get("TARGET_AFTER_PANEL"):
                continue

            def split(timeline):
                out = []
                for low, high, reason in horizon.runs(timeline, c.active_from, c.active_until):
                    if reason is None:
                        out += [(x.isoformat(), y.isoformat()) for x, y in ((low, min(high, m0)), (max(low, m1), high))
                                if x < y]
                return out
            minute = split(minute_lines.get(c.condition_id, ()))
            built = manifest.get((b.day.isoformat(), c.condition_id), [])
            assert windows_of(result, c.condition_id, b.day) == built == minute, (b.day, c.condition_id)
            differs += minute != split(lines.get(c.condition_id, ()))
            checked += 1
    assert checked > 100 and differs > 0, (checked, differs)


# -- A8 re-run on minute windows (the four registered fixtures) ---------------------------------------------------
def _verdicts(result):
    return {(f, k): c["attribution"]["verdict"] for f, passes in result.items() for k, c in passes.items()}


def test_a8_rerun_on_minute_windows_passes_on_the_four_registered_fixtures():
    from tools.research.maker_replay_v2 import attribution
    table, zones = attribution.fixtures()
    assert tuple(table) == A8_FIXTURES
    gap = {}
    for name in A8_FIXTURES:  # the minute windows differ from the exact ones: the 59 s rule is exercised
        sources = table[name]()
        lines = horizon.timelines(sources, zones)
        gap[name] = sum(horizon.day_windows(s.plan, lines)[0] != horizon.day_windows(s.plan,
                                                                                     horizon.minute_lines(lines))[0]
                        for s in sources)
    result = attribution.report_q2()
    print("C15A8_MINUTE_Q2_JSON " + json.dumps(dict(gap=gap, result=result), sort_keys=True, default=str))
    cells = {(f, k): c["attribution"] for f, passes in result.items() for k, c in passes.items()}
    assert len(cells) == 32
    assert set(_verdicts(result).values()) == {"PASS"}, {k: c for k, c in cells.items() if c["verdict"] != "PASS"}
    assert all(set(c["classes"]) <= {"A8"} for c in cells.values()), cells
    assert all(c["clause_violations"] == c["unexplained_cuts"] == 0 for c in cells.values()), cells
    assert gap["w0-09-27-roll"] and gap["dense-11-01-dst"], gap


def test_mutant_a8_reading_the_engine_horizon_at_the_instant_fails_on_minute_windows(monkeypatch):
    """The registered (exact-instant) A8 rules on minute windows: the Defender's 10-13 probe, which must FAIL."""
    from tools.research.maker_replay_v2 import attribution
    original = attribution.attributing

    def exact(engine, q2=False):
        cls = original(engine, q2=q2)
        cls.clause_horizon = cls.engine_horizon
        return cls
    monkeypatch.setattr(attribution, "attributing", exact)
    result = attribution.report_q2(["w0-09-27-roll", "dense-11-01-dst"])
    assert set(_verdicts(result).values()) - {"PASS"}, result


def test_mutant_exact_windows_fail_the_minute_a8_rules(monkeypatch):
    from tools.research.maker_replay_v2 import attribution
    monkeypatch.setattr(horizon, "minute_lines", lambda lines: lines)
    result = attribution.report_q2(["w0-09-27-roll", "dense-11-01-dst"])
    assert set(_verdicts(result).values()) - {"PASS"}, result
