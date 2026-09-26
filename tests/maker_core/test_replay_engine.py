from dataclasses import replace
from decimal import Decimal as D

from maker_core.contracts import InfoEvent
from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.engine import ReplayConfig, replay
from .fixtures.replay_scenario import Scenario

CONFIG = ReplayConfig(hazard_per_minute=.001)


def run(s, tmp_path, config=CONFIG):
    return replay((s.bundle(tmp_path / "bundle"),), config)


def test_ordered_replay_reserves_cash_and_keeps_mid(tmp_path):
    s = Scenario(minutes=3)
    for minute in range(3):
        for market in s.markets:
            s.book(market, minute*60)
    result = run(s, tmp_path, replace(CONFIG, initial_cash=D(40), wallet_cap=D(40)))
    first = [d for d in result.decisions if d.at == s.start]
    assert first[0].decision.action == "QUOTE"
    assert first[0].decision.centre == D(".50")
    assert first[1].decision.action == "NO_QUOTE"  # Shared cash is already reserved.
    assert any(d.decision.action == "HOLD" for d in result.decisions)
    for at in {span.start for span in result.spans}:
        assert sum(span.reserved for span in result.spans if span.start == at) <= D(40)


def test_future_view_and_future_event_do_not_change_previous_decisions(tmp_path):
    s = Scenario(markets=("a",), minutes=4)
    for minute in range(4):
        s.book("a", minute*60)
    before = replay((s.bundle(tmp_path / "before"),), CONFIG)
    s.view("a", 120, p=.99)
    s.add("a", "info_event", 121, {"events": [InfoEvent("new_high", None, s.at(121), s.at(121),
                                                              (s.cid("a"),), 1, None, "pull")]})
    after = replay((s.bundle(tmp_path / "after"),), CONFIG)
    assert canonical_bytes([d for d in before.decisions if d.at < s.at(120)]) == canonical_bytes(
        [d for d in after.decisions if d.at < s.at(120)])
    assert any(d.decision.action == "CANCEL" for d in after.decisions if d.at == s.at(120))


def test_gap_is_excluded_and_resting_legs_cancelled(tmp_path):
    s = Scenario(markets=("a",), minutes=4)
    s.book("a", 0)
    s.book("a", 180)
    result = run(s, tmp_path)
    gap = [span for span in result.spans if not span.covered]
    assert sum((span.end-span.start).total_seconds() for span in gap) == 120
    assert all(not span.legs and span.reason == "CAPTURE_GAP" for span in gap)


def test_scheduled_pull_and_fresh_reentry(tmp_path):
    s = Scenario(markets=("a",), minutes=17)
    event = InfoEvent("scheduled_print", s.at(240), None, None, (s.cid("a"),), 1, None, "pull",
                      active_until_utc=s.at(840))
    s.add("a", "info_event", 0, {"events": [event]})
    for minute in range(17):
        s.book("a", minute*60)
    s.view("a", 900)
    result = run(s, tmp_path)
    assert any(d.at == s.at(60) and d.decision.action == "CANCEL"
               and d.decision.reasons == ("INFO_PULL",) for d in result.decisions)
    assert not any(d.decision.action == "QUOTE" and s.at(60) <= d.at < s.at(900) for d in result.decisions)
    assert any(d.decision.action == "QUOTE" and d.at == s.at(900) for d in result.decisions)


def test_decided_is_permanent_even_if_clock_snapshot_empties(tmp_path):
    s = Scenario(markets=("a",), minutes=3)
    s.book("a", 0)
    s.add("a", "info_event", 1, {"events": [InfoEvent("decided", None, s.at(1), s.at(1),
             (s.cid("a"),), 1, {s.cid("a"): .5}, "observe")]})
    s.add("a", "info_event", 60, {"events": []})
    s.book("a", 60)
    result = run(s, tmp_path)
    assert all(d.decision.action != "QUOTE" for d in result.decisions if d.at >= s.at(1))
    assert any(d.decision.reasons == ("DECIDED",) for d in result.decisions)


def test_mid_drift_and_minimum_increase_trigger_cancellation(tmp_path):
    s = Scenario(markets=("a",), minutes=4)
    s.book("a", 0)
    s.view("a", 60, p=.52)
    s.book("a", 60, mid=D(".52"))
    s.terms("a", 120, minimum=D(50))
    s.book("a", 120, mid=D(".52"))
    result = run(s, tmp_path)
    assert any(d.at == s.at(60) and d.decision.action == "CANCEL" for d in result.decisions)
    assert any(d.at == s.at(60) and d.decision.action == "QUOTE" for d in result.decisions)
    assert not any(span.legs for span in result.spans if span.start >= s.at(120))


def test_payload_future_clock_is_exclusion_not_a_guessed_view(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    s.book("a", 0)
    view = next(r for r in s.records if r["kind"] == "outcome_view")
    view["payload"]["value"]["as_of_utc"] = s.at(60).isoformat()
    from maker_core.replay.bundle import sha256
    view["payload_sha256"] = sha256(canonical_bytes(view["payload"]))
    result = run(s, tmp_path)
    assert result.exclusions[0]["reason"] == "INVALID_OUTCOME_VIEW"
    assert not any(span.covered or span.legs for span in result.spans)
