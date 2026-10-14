"""§4 window start at a descriptor change: the minute rule (``intervals``) against the exact instant (``horizon``).

Characterisation only (T1 r3, 2026-10-14). The owner ruled §4 whole-minute on 2026-10-13. ``intervals.evaluate``
(U1) applies it; the C15 manifest builder (``execution_manifest.active_intervals``) and A8
(``attribution.horizon_sources``) still cut windows with ``horizon.runs``/``horizon.day_windows`` at the exact
descriptor instant. Moving those two is BLOCKED-ON-OWNER (T1 report 6: the registered C15 row and the §4 gate-ordering
disclosure assume exact instants), so this table pins today's difference at a captured descriptor change on both
sides, including the 59 s edge. Fictional bundles only.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.v2 import horizon, intervals, lockstep, universe_v02

from .fixtures.panel_v02 import ZONES, Panel

DAY = CALIBRATION_DATES[0]
START = datetime.combine(DAY, time(), tzinfo=timezone.utc)
FIRST = START + timedelta(minutes=3)  # the fixture's first capture minute (offset 3)
SECOND = timedelta(seconds=1)


class SecondPanel(Panel):
    """The fixture panel with every capture ``second`` seconds into its minute (the base fixture uses 20)."""

    def __init__(self, second, **kwargs):
        super().__init__(**kwargs)
        self.second = second

    def captures(self, day):
        return [at.replace(second=self.second) for at in super().captures(day)]


def _active(windows, at):
    return any(a <= at < b for a, b in windows)


@pytest.fixture(scope="module", params=[0, 1, 20, 59], ids=lambda s: f"capture_at_{s:02d}s")
def evaluated(request, tmp_path_factory):
    second = request.param
    panel = SecondPanel(second, bands=1, step=10, capture_minutes=range(0, 120))
    bundle = open_stream_bundle(panel.write(tmp_path_factory.mktemp(f"s{second}") / DAY.isoformat(), DAY))
    minute = intervals.evaluate(universe_v02.day_inputs([bundle]), panel.inventory([DAY]), panel="calibration")
    lines = horizon.timelines([lockstep.descriptor_source(bundle)], ZONES)
    exact, _ = horizon.day_windows(lockstep.descriptor_source(bundle).plan, lines)
    by_cid = {}
    for w in minute.windows:
        by_cid.setdefault(w["condition_id"], []).append(
            (datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"])))
    starting = sorted(cid for cid, ws in exact.items() if any(a == FIRST + second * SECOND for a, _ in ws))
    assert starting, "no window opens at the first capture"
    return second, by_cid, exact, starting


def test_the_window_start_at_a_captured_descriptor_change(evaluated):
    second, minute, exact, starting = evaluated
    change = FIRST + second * SECOND  # the first descriptor's capture instant: the band enters lead 1..2 here
    boundary = change if second == 0 else FIRST + timedelta(minutes=1)  # the first minute start at or after it
    gap = (boundary - change).total_seconds()
    assert gap == {0: 0, 1: 59, 20: 40, 59: 1}[second]  # the 59 s edge is a change at :01
    for cid in starting:
        rows = [
            # instant,                 exact (C15 builder / A8 today), minute (intervals, the ruled §4)
            (change - SECOND,          False,                          False),
            (change,                   True,                           second == 0),
            (boundary - SECOND,        second != 0 or None,            False),
            (boundary,                 True,                           True),
        ]
        for at, want_exact, want_minute in rows:
            if want_exact is None:  # boundary - 1 s == change - 1 s when the change is on a minute start
                continue
            assert _active(exact[cid], at) is want_exact, (cid, at, "exact")
            assert _active(minute.get(cid, ()), at) is want_minute, (cid, at, "minute")


def test_the_two_rules_agree_except_inside_the_gap(evaluated):
    """Off the [change, boundary) gap at each descriptor change the two rules give the same active set."""
    second, minute, exact, _ = evaluated
    for cid, windows in exact.items():
        for a, b in windows:
            ceil = a if a.second == 0 and a.microsecond == 0 else a.replace(second=0, microsecond=0) + timedelta(
                minutes=1)
            assert (ceil - a).total_seconds() <= 59
            for probe in (ceil, b - SECOND):
                if probe < b and not START + timedelta(hours=5) <= probe < START + timedelta(hours=8):
                    assert _active(minute.get(cid, ()), probe), (cid, probe)
