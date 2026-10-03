from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError
from maker_core.replay.pull_efficiency import pull_efficiency, ratio_intervals, _Midpoints
from .fixtures.pull_panel import panel
from .fixtures.replay_scenario import Scenario
from maker_core.replay.engine import ReplayConfig, replay

MATCHED = {"status": "MATCHED"}


def endpoint(a, b, **kwargs):
    return pull_efficiency(a, b, MATCHED, replicates=100, **kwargs)


def test_exact_five_cent_move_overlapping_yes_band_minutes_and_paired_counts():
    a, b = panel()
    result = endpoint(a, b)
    assert result["counts"] == dict(opportunities=6, large_moves=4, informed_pulled=2,
                                   clock_pulled=2, informed_removed=2, clock_removed=1)
    assert result["ratio"] == 2 and result["status"] == "UNDERPOWERED"
    assert result["exclusions"] == {"MISSING_END_MIDPOINT": 5}
    assert sum(result["exclusions"].values()) + result["counts"]["opportunities"] == result["candidates"]
    assert result["intervals"]["date_x_market"]["interval"] == [2, 2]


def test_powered_exact_two_passes_point_hurdle_both_bounds_without_lower_bound_hurdle():
    a, b = panel(days=10, markets=10)
    for bound in ("strictly_through", "at_price"):
        left = replace(a, config=replace(a.config, fill_bound=bound))
        right = replace(b, config=replace(b.config, fill_bound=bound))
        result = endpoint(left, right)
        assert result["status"] == "HURDLE_MET" and result["ratio"] == 2
        assert all(x["status"] == "OK" for x in result["intervals"].values())
    assert endpoint(*panel(days=10, markets=10, informed_pulls=(0, 3)))["status"] == "HURDLE_NOT_MET"


def test_point_hurdle_passes_even_when_crossed_lower_bound_is_below_two():
    a, b = panel(days=10, markets=10, informed_pulls=(0, 1, 2), clock_pulls=(2, 3, 4))
    leg = a.spans[3].legs
    # Half the cities remove three moves, half remove one, at equal pull exposure.
    a = replace(a, spans=tuple(replace(s, legs=() if s.start.minute in (0, 3, 4) else leg)
                              if int(s.market_id.removeprefix("market")) < 5 else s for s in a.spans))
    result = endpoint(a, b)
    assert result["ratio"] == 2 and result["status"] == "HURDLE_MET"
    assert result["intervals"]["date_x_market"]["interval"][0] < 2


@pytest.mark.parametrize("a_pulls,b_pulls", [((), ()), ((0,), (3,)), ((0,), ())])
def test_zero_denominators_or_clock_removed_move_is_unidentified(a_pulls, b_pulls):
    result = endpoint(*panel(informed_pulls=a_pulls, clock_pulls=b_pulls))
    assert result["status"] == "UNIDENTIFIED" and result["ratio"] is None
    assert all(x["valid_replicates"] == 0 and x["undefined_replicates"] == 100 for x in result["intervals"].values())


def test_candidate_zero_removed_moves_is_identified_zero():
    result = endpoint(*panel(informed_pulls=(3,), clock_pulls=(2,)))
    assert result["ratio"] == 0 and "UNIDENTIFIED" not in result["reasons"]


def test_common_set_matching_is_separate_and_exactly_one_minute_is_allowed():
    a, b = panel(informed_pulls=(0, 1, 2))
    assert endpoint(a, b)["exposure_match"]["status"] == "MATCHED"
    a, b = panel(informed_pulls=(0, 1, 2, 3))
    assert endpoint(a, b)["status"] == "UNMATCHED"
    a, b = panel()
    assert pull_efficiency(a, b, {"status": "UNMATCHED"}, replicates=100)["status"] == "UNMATCHED"


def test_resting_state_at_start_cannot_take_credit_for_later_cancellation():
    a, b = panel()
    # At t=0 one leg rests for one microsecond; it is then canceled for the rest of the minute.
    first = a.spans[0]
    leg = a.spans[2].legs
    split = first.start + timedelta(microseconds=1)
    a = replace(a, spans=(replace(first, end=split, legs=leg), replace(first, start=split), *a.spans[1:]))
    result = endpoint(a, b)
    assert result["counts"]["informed_pulled"] == 1 and result["counts"]["informed_removed"] == 1


def test_horizon_gap_in_either_policy_excludes_interval_and_inactive_endpoint_excludes():
    a, b = panel()
    for field in ("covered", "evaluation_active"):
        broken = replace(b, spans=tuple(replace(s, **{field: False}) if i == 5 else s for i, s in enumerate(b.spans)))
        result = endpoint(a, broken)
        assert result["counts"]["opportunities"] == 0
        assert result["exclusions"]["UNCOVERED_HORIZON"] == 6
    # A missing span is also a gap, including exactly at the ending midpoint.
    result = endpoint(a, replace(b, spans=b.spans[:5] + b.spans[6:]))
    assert result["counts"]["opportunities"] == 0


def test_latest_start_and_first_end_boundaries_and_source_age():
    a, _ = panel()
    at, cid, book = a.books[0]
    def points(start_age=60, end_late=120, source_age=0):
        start = at-timedelta(seconds=start_age)
        end = at+timedelta(seconds=300+end_late)
        return _Midpoints(((start, cid, replace(book, as_of_utc=start-timedelta(seconds=source_age))),
                           (end, cid, replace(book, as_of_utc=end))))
    assert points().endpoints(cid, at)[0] is not None
    assert points(start_age=61).endpoints(cid, at)[1] == "MISSING_START_MIDPOINT"
    assert points(end_late=121).endpoints(cid, at)[1] == "MISSING_END_MIDPOINT"
    assert points(source_age=1).endpoints(cid, at)[1] == "MISSING_START_MIDPOINT"
    first = replace(book, as_of_utc=at+timedelta(minutes=5))
    second = replace(book, as_of_utc=at+timedelta(minutes=6), yes_bids=((D(".8"), D(1)),), yes_asks=((D(".9"), D(1)),))
    marks = _Midpoints(((at, cid, book), (first.as_of_utc, cid, first), (second.as_of_utc, cid, second)))
    assert marks.endpoints(cid, at)[0][1] == D(".5")  # Cannot pick a later/larger move.
    for invalid in (replace(first, yes_asks=()), replace(first, yes_bids=((D(".9"), D(1)),))):
        marks = _Midpoints(((at, cid, book), (first.as_of_utc, cid, invalid), (second.as_of_utc, cid, second)))
        assert marks.endpoints(cid, at)[0][1] == D(".85")


def test_absolute_move_just_below_threshold_does_not_count():
    a, b = panel(mids=[".5"]*5+[".450001"]*6)
    assert endpoint(a, b)["counts"]["large_moves"] == 0
    a, b = panel(mids=[".5"]*5+[".45"]*6)
    assert endpoint(a, b)["counts"]["large_moves"] == 5


def test_bootstrap_sums_counts_and_preserves_paired_date_market_multiplicities():
    def counts(pulls, removed, clock_removed):
        return dict(opportunities=100, large_moves=50, informed_pulled=pulls, clock_pulled=pulls,
                    informed_removed=removed, clock_removed=clock_removed)
    cells = {(f"d{d}", f"m{m}"): counts(20, 20 if m < 5 else 2, 10) for d in range(10) for m in range(10)}
    result = ratio_intervals(cells, replicates=200)
    assert result["date"]["interval"] == [1.1, 1.1]
    assert result["date_x_market"]["interval"][0] < 1.1 < result["date_x_market"]["interval"][1]
    assert canonical_bytes(result) == canonical_bytes(ratio_intervals(dict(reversed(list(cells.items()))), replicates=200))
    assert result["date_x_market"]["seed"] == 20260927
    thin = ratio_intervals({k: v for k, v in cells.items() if k[1] == "m0"}, replicates=100)
    assert thin["date"]["status"] == thin["date_x_market"]["status"] == "UNDERPOWERED"
    unequal = ratio_intervals({("d1", "m1"): counts(1, 1, 1), ("d2", "m2"): counts(20, 20, 2)}, replicates=100)
    assert unequal["date"]["estimate"] == 7  # Mean cell ratios would be 5.5.


def test_sparse_draws_omit_empty_and_nonempty_undefined_separately():
    cells = {("d1", "m1"): dict(opportunities=1, large_moves=1, informed_pulled=1, clock_pulled=1,
                                 informed_removed=1, clock_removed=1),
             ("d2", "m2"): dict(opportunities=1, large_moves=0, informed_pulled=1, clock_pulled=1,
                                 informed_removed=0, clock_removed=0)}
    result = ratio_intervals(cells, replicates=500)["date_x_market"]
    assert result["empty_replicates"] > 0 and result["undefined_replicates"] > 0
    assert result["valid_replicates"] + result["omitted_replicates"] == 500
    assert result["interval"] == [1, 1]
    empty = ratio_intervals({}, replicates=100)["date"]
    assert empty["empty_replicates"] == 100 and empty["interval"] is None


def test_nine_dates_or_fewer_than_one_hundred_valid_draws_is_underpowered():
    a, b = panel(days=9, markets=10)
    assert endpoint(a, b)["status"] == "UNDERPOWERED"
    cells = {(f"d{d}", f"m{m}"): dict(opportunities=1, large_moves=int(m == 0),
                                      informed_pulled=1, clock_pulled=1,
                                      informed_removed=int(m == 0), clock_removed=int(m == 0))
             for d in range(10) for m in range(10)}
    result = ratio_intervals(cells, replicates=100)["date_x_market"]
    assert result["status"] == "UNDERPOWERED"
    assert 0 < result["valid_replicates"] < 100 and result["interval"] is not None


def test_trace_binding_opportunity_cap_and_invalid_counts_refuse():
    a, b = panel()
    with pytest.raises(BundleError, match="unpaired"):
        endpoint(a, replace(b, books=()))
    with pytest.raises(BundleError, match="opportunity_cap"):
        endpoint(replace(a, config=replace(a.config, max_events=1)), b)
    with pytest.raises(BundleError, match="invalid_pull_counts"):
        ratio_intervals({("d", "m"): {}}, replicates=100)


def test_engine_traces_integrate_with_endpoint_without_policy_reexecution(tmp_path):
    scenario = Scenario(markets=("a",), minutes=12)
    for minute in range(12):
        scenario.book("a", minute*60, mid=D(".50") if minute < 5 else D(".55"))
    bundle = scenario.bundle(tmp_path/"bundle")
    a = replay((bundle,), ReplayConfig(hazard_per_minute=0))
    b = replay((bundle,), ReplayConfig(policy="clock_only", hazard_per_minute=0))
    result = endpoint(a, b)
    assert result["counts"]["opportunities"] == 7
    assert result["counts"]["large_moves"] == 5


def _scenario_bundles(tmp_path):
    from maker_core.replay.engine import ReplayEngine
    scenario = Scenario(markets=("a", "b"), minutes=30)
    for minute in range(30):
        for market in ("a", "b"):
            scenario.book(market, minute*60, mid=D(".5") if minute % 7 else D(".56"))
    bundle = scenario.bundle(tmp_path/"day")
    a, b = scenario.cid("a"), scenario.cid("b")
    at = scenario.at
    # Unaligned, overlapping and abutting windows exercise the union and the minute rounding.
    return replace(bundle, active_intervals=((a, at(30), at(615)), (a, at(300), at(1200)), (a, at(1200), at(1290)),
                                             (b, at(61), at(119)), (b, at(600), at(1800)))), ReplayEngine


def test_preflight_candidates_equal_the_pull_loop_and_refuse_at_the_same_cap(tmp_path):
    from maker_core.replay.pull_efficiency import opportunity_candidates
    bundle, ReplayEngine = _scenario_bundles(tmp_path)
    config = ReplayConfig(hazard_per_minute=0, max_outputs=10_000)
    informed = replay((bundle,), config)
    clock = replay((bundle,), replace(config, policy="clock_only"))
    counted = opportunity_candidates(ReplayEngine((bundle,), config).windows)
    assert counted == endpoint(informed, clock)["candidates"] == 21 + 0 + 20
    # The scored loop refuses exactly when the preflight count exceeds max_events.
    tight = replace(informed, config=replace(informed.config, max_events=counted))
    endpoint(tight, replace(clock, config=replace(clock.config, max_events=counted)))
    with pytest.raises(BundleError, match="pull_opportunity_cap"):
        endpoint(replace(tight, config=replace(tight.config, max_events=counted-1)), clock)


def test_clarification_2_engine_bounds_heap_events_not_input_records(tmp_path):
    bundle, ReplayEngine = _scenario_bundles(tmp_path)
    records = len(bundle.records)
    # Fewer heap timestamps than records: 30 book minutes plus window boundaries, many records per clock.
    cap = 64
    assert records > cap
    # Addendum mode (one shared max_events) still bounds input records by it.
    with pytest.raises(BundleError, match="engine_event_cap"):
        ReplayEngine((bundle,), ReplayConfig(hazard_per_minute=0, max_events=cap))
    # Clarification 2 mode: records are bound by max_records at load, heap events by max_events.
    engine = ReplayEngine((bundle,), ReplayConfig(hazard_per_minute=0, max_events=cap, max_outputs=10_000))
    engine.run()
    assert engine.processed <= cap
    with pytest.raises(BundleError, match="engine_event_cap"):
        ReplayEngine((bundle,), ReplayConfig(hazard_per_minute=0, max_events=engine.processed-1,
                                             max_outputs=10_000)).run()
