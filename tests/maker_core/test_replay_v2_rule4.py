"""Maker replay v2 rule 4 = option B (owner, 2026-10-05); fictional fixtures only.

Option B wakes ``informed-v0`` on a view's content without its clocks (``as_of_utc``, ``stdev``). The S5-style
equivalence: on a day whose views are re-stamped at every evaluation (as the exporter does), the option-B run
equals, decision for decision and in every fingerprint field, a run under the registered rule (payload hash)
on the same rows with each time-only re-stamp delivered at the condition's next wake. That is, a re-stamp that
moves only ``as_of_utc`` or ``stdev`` never wakes a band and is read exactly at its next own event. A mutant
that drops ``p_yes`` from the view state must fail the same check.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from maker_core.contracts import OutcomeView, Unavailable
from maker_core.replay.v2 import kernel
from maker_core.replay.v2.compaction import compact
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.kernel import V2Config, view_state
from maker_core.replay.v2.lockstep import DaySource, drive, record_from_row, run_plan
from tools.research.maker_replay_v2.bench import fingerprint
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.rule4 import WakeLog, lazy, restamped
from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, ScaledDay, plan_of

DAY = date(2026, 9, 27)  # fictional
CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)
T0 = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)


def registered(state):
    """The rule-4 view state before option B: the view's payload hash."""
    return state.sha.get("outcome_view")


def without_p_yes(state):
    value = view_state(state)
    return value if value is None or value[0] != "view" else value[:2] + value[3:]


def source(day, pairs):
    records = [record_from_row(r) for r in compact([row for row, _ in pairs], day.groups)]
    return DaySource(plan_of(day), lambda: iter(records))


def run(day, pairs, engine=EngineV2):
    src = source(day, pairs)
    result = engine(CONFIG, run_plan([src]))
    drive([src], [result], time_zones=FIXTURE_ZONES)
    return result


def stream(engine):
    return [(e.at, e.condition_id, e.decision) for e in engine.decisions]


def check(monkeypatch, day, pairs, state=None):
    """(rule run, registered run on lazy rows): the rule's wakes decide where time-only rows are delivered."""
    if state is not None:
        monkeypatch.setattr(kernel, "view_state", state)
    under_rule = run(day, pairs, WakeLog)
    monkeypatch.setattr(kernel, "view_state", registered)
    reference = run(day, lazy(pairs, under_rule.wake_log))
    monkeypatch.undo()
    return under_rule, reference


def test_view_state_ignores_only_the_clocks():
    view = OutcomeView("c", .4, .02, None, T0, T0 + timedelta(hours=1), "h", "m", "none")

    def state(value):
        return type("S", (), {"latest": {"outcome_view": value}})()

    restamp = replace(view, as_of_utc=T0 + timedelta(minutes=5), stdev=.021)
    assert view_state(state(restamp)) == view_state(state(view))
    for changed in (replace(view, p_yes=.41), replace(view, inputs_hash="g"), replace(view, calibration_grade="shadow"),
                    replace(view, valid_until_utc=T0 + timedelta(hours=2)), replace(view, model_id="n")):
        assert view_state(state(changed)) != view_state(state(view))
    late = Unavailable("missing", T0 + timedelta(minutes=1))
    assert view_state(state(late)) == view_state(state(Unavailable("missing", T0)))
    assert view_state(state(Unavailable("other", T0))) != view_state(state(Unavailable("missing", T0)))


DAYS = {"dense": lambda: DenseDay(DAY, union=16, trades=20000, minutes=30),
        "w0": lambda: ScaledDay(DAY, union=120, trades=2000, start_minute=600, minutes=20)}


@pytest.mark.parametrize("mode", ["restamp", "drift", "pjump"])
@pytest.mark.parametrize("name", sorted(DAYS))
def test_option_b_equals_the_registered_rule_reading_restamps_at_the_next_wake(monkeypatch, name, mode):
    day = DAYS[name]()
    pairs = restamped(day.rows(), mode)
    assert any(label for _, label in pairs)
    under_b, reference = check(monkeypatch, day, pairs)
    assert stream(under_b) == stream(reference)
    assert fingerprint(under_b) == fingerprint(reference)
    assert under_b.wakes == reference.wakes
    # The registered rule on the eager rows wakes at re-stamps (that is what option B removes).
    monkeypatch.setattr(kernel, "view_state", registered)
    eager = run(day, pairs)
    monkeypatch.undo()
    assert eager.wakes > under_b.wakes
    if name == "dense":
        assert sum(e.decision.action == "QUOTE" for e in under_b.decisions) > 0


def test_p_yes_removal_mutant_is_caught(monkeypatch):
    day = DAYS["dense"]()
    pairs = restamped(day.rows(), "pjump")
    assert any(not label and row["kind"] == "outcome_view" for row, label in pairs[1:])
    mutant, reference = check(monkeypatch, day, pairs, without_p_yes)
    assert fingerprint(mutant) != fingerprint(reference)
    assert mutant.wakes < reference.wakes
