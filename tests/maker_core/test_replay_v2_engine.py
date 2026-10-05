"""Maker replay v2 engine (W3) against the reference schedule (W4); fictional fixtures only."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.v2.engine import EngineV2, RunningTotalsMismatch
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import DaySource, bundle_source, drive, run_plan
from maker_core.replay.v2.money import MoneyError
from maker_core.replay.v2.reference import ReferenceEngine
from tools.research.maker_replay_v2.bench import differential, fingerprint
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import ScaledDay, materialize, regrouped
from .fixtures.replay_scenario import Scenario

DAY = date(2026, 9, 27)
DAY_START = __import__("datetime").datetime(2026, 9, 27, tzinfo=__import__("datetime").timezone.utc)
POLICIES = ("informed-v0", "blind_re1", "no_quote", "clock_only")
CONFIG = V2Config(hazard_per_minute=.001, debug=True, keep=True)


def pair(source, config):
    plan = run_plan([source])
    v2, ref = EngineV2(config, plan), ReferenceEngine(replace(config, debug=False), plan)
    drive([source], [v2, ref])
    return v2, ref


def scenario(tmp_path, minutes=12):
    s = Scenario(minutes=minutes)
    for minute in range(minutes):
        for market in s.markets:
            s.book(market, minute * 60 + (5 if market == "b" else 0), mid=D(".5") + (D(".01") if minute % 5 == 3 else 0))
    s.trade("a", 125, price=".40", size="10")
    s.trade("b", 400, price=".60", size="10", outcome="NO")
    return bundle_source(s.bundle(tmp_path / "bundle"))


@pytest.mark.parametrize("policy", POLICIES)
def test_v2_engine_equals_reference_on_typed_scenario(tmp_path, policy):
    v2, ref = pair(scenario(tmp_path), replace(CONFIG, policy=policy))
    assert fingerprint(v2) == fingerprint(ref)
    assert canonical_bytes(v2.decisions) == canonical_bytes(ref.decisions)
    assert v2.decision_count > 0


def test_every_pass_and_clock_trial_equal_reference_on_dense_fixture():
    source, _ = materialize(DenseDay(DAY, union=12, trades=20000, minutes=40))
    result = differential(source, V2Config(hazard_per_minute=.001))
    assert result["divergences"] == []
    assert result["engines_compared"] >= 9 and result["clock_trials"] >= 1
    assert result["quotes"]["strictly_through"]["informed-v0"] > 0
    assert result["quotes"]["strictly_through"]["clock_only"] > 0


def test_every_pass_equals_reference_on_w0_fixture_across_horizon_roll():
    day = ScaledDay(DAY, union=12, trades=2000, start_minute=225, minutes=30)  # 03:45-04:15 UTC, NY roll 04:00
    source, _ = materialize(day)
    assert differential(source, V2Config(hazard_per_minute=.001))["divergences"] == []


def test_decision_digest_invariant_under_coverage_regrouping_and_view_elision():
    """Session A finding 2: v2 reads no capture time of an elidable record and hashes none into a digest.

    The same fictional day as v0.1 (per-condition coverage, byte-identical view/descriptor repeats kept),
    as v0.2 (subscription groups, repeats elided, so the surviving views keep their first capture time)
    and as v0.2 regrouped into one group per condition gives identical decision streams, intervals and cash.
    """
    day = ScaledDay(DAY, union=12, trades=20000, start_minute=600, minutes=30, repeat_views=True)
    forms = [materialize(day, "v0.1")[0], materialize(day, "v0.2")[0],
             regrouped(day, {cid: "solo-" + cid for cid in day.groups})]
    count = [len(list(f.records())) for f in forms]
    assert count[1] < count[2] < count[0]  # groups shrink coverage; elision drops the repeats even ungrouped
    dense = DenseDay(DAY, union=12, trades=20000, minutes=30)
    dense_forms = [materialize(dense, "v0.1")[0], materialize(dense, "v0.2")[0],
                   regrouped(dense, {cid: "solo-" + cid for cid in dense.groups})]
    assert len(list(dense_forms[1].records())) < len(list(dense_forms[2].records()))
    for group in (forms, dense_forms):
        for policy in POLICIES:
            config = replace(CONFIG, policy=policy)
            prints = []
            for source in group:
                engine = EngineV2(config, run_plan([source]))
                drive([source], [engine])
                prints.append(fingerprint(engine))
            assert prints[0] == prints[1] == prints[2], policy


def test_a_band_is_not_decided_at_another_bands_events(tmp_path):
    s = Scenario(minutes=10)
    s.book("a", 0)
    s.book("b", 0)
    for minute in range(1, 10):
        s.book("a", minute * 60)  # only a has records after the first minute
    source = bundle_source(s.bundle(tmp_path / "bundle"))
    v2, ref = pair(source, CONFIG)
    b = s.cid("b")
    times = [d.at for d in v2.decisions if d.condition_id == b]
    # b is decided at its book and again only at its own timers (book gap at 60 s), never at a's books.
    assert times and max(times) <= s.at(60) and len(times) <= 3
    assert fingerprint(v2) == fingerprint(ref)


def test_intervals_are_run_length_not_instants_times_bands():
    source, _ = materialize(DenseDay(DAY, union=40, trades=2000, minutes=20))
    plan = run_plan([source])
    engine = EngineV2(replace(CONFIG, debug=False), plan)
    drive([source], [engine])
    assert engine.interval_count < engine.instants * len(engine.states) / 10
    assert engine.wakes < engine.instants * len(engine.states) / 10


def test_one_parse_drives_several_engines_identically():
    source, _ = materialize(DenseDay(DAY, union=12, trades=20000, minutes=20))
    parses = []

    def counted():
        parses.append(1)
        return source.records()
    shared = DaySource(source.plan, counted)
    plan = run_plan([shared])
    configs = [replace(CONFIG, policy=p, fill_bound=b) for p in POLICIES for b in ("strictly_through", "at_price")]
    together = [EngineV2(c, plan) for c in configs]
    drive([shared], together)
    assert len(parses) == 1
    for config, engine in zip(configs, together):
        alone = EngineV2(config, plan)
        drive([source], [alone])
        assert fingerprint(alone) == fingerprint(engine)


def test_running_totals_debug_assertion_detects_drift():
    source, _ = materialize(DenseDay(DAY, union=12, trades=20000, minutes=20))
    plan = run_plan([source])
    engine = EngineV2(replace(CONFIG, policy="clock_only"), plan)
    original = engine.changed

    def drifting(cid):
        original(cid)
        engine.R = engine.R + D("0.000001")
    engine.changed = drifting
    with pytest.raises(RunningTotalsMismatch):
        drive([source], [engine])


def test_money_not_representable_at_one_millionth_is_refused(tmp_path):
    s = Scenario(markets=("a",), minutes=4)
    for minute in range(4):
        s.book("a", minute * 60)
    s.trade("a", 61, price=".40", size="10.1234567")
    source = bundle_source(s.bundle(tmp_path / "bundle"))
    engine = EngineV2(CONFIG, run_plan([source]))
    with pytest.raises(MoneyError):
        drive([source], [engine])


def _book(s, seconds, mid=D(".5"), as_of=None, depth=D(75)):
    """A book record with an explicit freshness clock (``as_of``) and its trade coverage."""
    from maker_core.quoting.policy import Book
    s.add("a", "coverage", seconds, dict(trade_stream_ok=True, valid_until_utc=s.at(seconds + 60).isoformat()))
    yb, ya = ((mid - D(".01"), depth),), ((mid + D(".01"), depth),)
    nb, na = ((1 - mid - D(".01"), depth),), ((1 - mid + D(".01"), depth),)
    s.add("a", "book", seconds, Book(s.at(seconds if as_of is None else as_of), yb, ya, nb, na))


def _run(s, tmp_path):
    source = bundle_source(s.bundle(tmp_path / "bundle"))
    v2, ref = pair(source, CONFIG)
    assert fingerprint(v2) == fingerprint(ref)
    return v2


def test_unchanged_resends_cause_no_decisions_and_keep_resting_informed_legs(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    _book(s, 0)
    for seconds in (20, 40):  # exporter re-projections of the 0 s fetch: same payload, same clock
        _book(s, seconds, as_of=0)
    v2 = _run(s, tmp_path)
    assert [d.decision.action for d in v2.decisions if d.at == s.at(0)] == ["QUOTE"]
    assert not [d for d in v2.decisions if s.at(0) < d.at < s.at(60)]
    resting = [i for i in v2.intervals if i.start < s.at(60) and i.legs]
    assert resting and resting[0].start == s.at(0) and resting[-1].end >= s.at(60)


def test_a_quiet_resend_keeps_the_book_fresh_without_deciding(tmp_path):
    s = Scenario(markets=("a",), minutes=3)
    _book(s, 0)
    for seconds in (50, 100):  # re-fetched, levels unchanged: the freshness clock moves
        _book(s, seconds)
    s.view("a", 105, p=.5)  # an own event 5 s after the last re-send reads a fresh book
    v2 = _run(s, tmp_path)
    assert not [d for d in v2.decisions if d.at in (s.at(50), s.at(100))]
    assert not [d for d in v2.decisions if d.decision.reasons[0] in ("CAPTURE_GAP", "BOOK_STALE_OR_FUTURE")
                and d.at < s.at(160)]
    at_view = [d for d in v2.decisions if d.at == s.at(105)]
    assert at_view and at_view[0].decision.reasons[0] not in ("CAPTURE_GAP", "BOOK_STALE_OR_FUTURE")
    assert any(d.decision.reasons == ("CAPTURE_GAP",) and d.at == s.at(160) for d in v2.decisions)


def test_a_changed_book_wakes(tmp_path):
    s = Scenario(markets=("a",), minutes=2)
    _book(s, 0)
    _book(s, 20, as_of=0)  # re-send: no wake
    _book(s, 40, mid=D(".52"))  # changed levels: wake
    v2 = _run(s, tmp_path)
    assert not [d for d in v2.decisions if d.at == s.at(20)]
    assert [d for d in v2.decisions if d.at == s.at(40)]


def test_a_silent_feed_goes_stale_on_schedule(tmp_path):
    s = Scenario(markets=("a",), minutes=3)
    _book(s, 0)
    _book(s, 30, as_of=0)  # a re-projection of the old fetch does not refresh the clock
    v2 = _run(s, tmp_path)
    stale = [d for d in v2.decisions if d.decision.reasons[0] == "CAPTURE_GAP"]
    assert stale and stale[0].at == s.at(60) and stale[0].decision.action == "CANCEL"


def test_book_state_excludes_only_the_clock():
    from dataclasses import replace as dc_replace
    from maker_core.quoting.policy import Book
    from maker_core.replay.v2.kernel import book_state
    level = ((D(".49"), D(75)),)
    book = Book(DAY_START, level, ((D(".51"), D(75)),), level, ((D(".51"), D(75)),))
    assert book_state(book) == book_state(dc_replace(book, as_of_utc=DAY_START + timedelta(seconds=9)))
    assert book_state(book) != book_state(dc_replace(book, yes_bids=((D(".49"), D(76)),)))
    assert book_state(book) != book_state(dc_replace(book, no_asks=((D(".51"), D(75)), (D(".52"), D(1)))))
    assert book_state(book) != book_state(dc_replace(book, post_only_available=False))


def test_config_quantizes_caps_and_refuses_inexact_caps():
    assert str(V2Config(initial_cash=D(40)).initial_cash) == "40.000000"
    with pytest.raises(MoneyError):
        V2Config(initial_cash=D("40.0000001"))


def test_multi_day_run_equals_reference():
    sources = []
    for offset in range(2):
        dense = DenseDay(DAY + timedelta(days=offset), union=12, trades=20000, minutes=20)
        sources.append(materialize(dense)[0])
    plan = run_plan(sources)
    for policy in ("informed-v0", "clock_only"):
        config = replace(CONFIG, policy=policy)
        v2, ref = EngineV2(config, plan), ReferenceEngine(replace(config, debug=False), plan)
        drive(sources, [v2, ref])
        assert fingerprint(v2) == fingerprint(ref)


def test_reentry_and_pull_digests_ignore_a_repeated_views_capture_time(tmp_path):
    """A byte-identical view re-captured after an INFO_PULL is no fresh input in v2; the frozen engine resumed on it."""
    from maker_core.contracts import InfoEvent
    from maker_core.replay.engine import ReplayConfig, replay

    def build(root, repeat):
        s = Scenario(markets=("a",), minutes=17)
        event = InfoEvent("scheduled_print", s.at(240), None, None, (s.cid("a"),), 1, None, "pull",
                          active_until_utc=s.at(840))
        s.add("a", "info_event", 0, {"events": [event]})
        for minute in range(17):
            s.book("a", minute * 60)
        if repeat:
            first = next(r for r in s.records if r["kind"] == "outcome_view")
            s.add("a", "outcome_view", 900, first["payload"])
        return s.bundle(root)

    with_repeat, elided = build(tmp_path / "repeat", True), build(tmp_path / "elided", False)
    prints = []
    for bundle in (with_repeat, elided):
        engine = EngineV2(CONFIG, run_plan([bundle_source(bundle)]))
        drive([bundle_source(bundle)], [engine])
        prints.append(fingerprint(engine))
        assert any(d.decision.reasons == ("AWAIT_FRESH_REENTRY_INPUTS",) for d in engine.decisions)
    assert prints[0] == prints[1]
    frozen = [replay((b,), ReplayConfig(hazard_per_minute=.001)) for b in (with_repeat, elided)]
    assert canonical_bytes(frozen[0].decisions) != canonical_bytes(frozen[1].decisions)  # v1 read the capture time


def test_factor_exposure_that_one_millionth_cannot_hold_is_refused_not_rounded():
    """C5 holds for the weather plugin's unit loadings; a fractional loading can make an exposure inexact."""
    from maker_core.replay.v2.money import mul, q
    cost = q(mul(D("0.37"), D("12.3457")))  # a fill cost: exact at 1e-6
    assert q(mul(cost, D("1.0"))) == cost
    with pytest.raises(MoneyError):
        q(mul(cost, D("0.5")))
