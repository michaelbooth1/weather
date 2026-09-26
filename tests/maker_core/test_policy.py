from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import pytest

from maker_core.contracts import InfoEvent, Unavailable
from maker_core.evidence.journal import canonical_bytes, Journal, verify_journal
from maker_core.quoting.policy import decide, rank, blind_re1, ExposureLimit, inventory_action


def test_pure_mid_centred_and_hash_bound(inputs):
    a = decide(inputs)
    assert a.action == "QUOTE" and a.centre == D(".50")
    assert a == decide(inputs)
    changed = replace(inputs, fair_value=replace(inputs.fair_value, p_yes=.51, joint=None))
    b = decide(changed)
    assert b.centre == a.centre and b.input_hash != a.input_hash
    assert b.legs[0].price > a.legs[0].price
    assert b.legs[1].price <= a.legs[1].price


@pytest.mark.parametrize("change,reason", [
    (lambda i: replace(i, book=replace(i.book, as_of_utc=i.now - timedelta(seconds=11))), "BOOK_STALE_OR_FUTURE"),
    (lambda i: replace(i, book=replace(i.book, as_of_utc=i.now + timedelta(seconds=1))), "BOOK_STALE_OR_FUTURE"),
    (lambda i: replace(i, terms=None), "TERMS_MISSING_STALE_OR_FUTURE"),
    (lambda i: replace(i, terms=replace(i.terms, as_of_utc=i.now - timedelta(minutes=61))), "TERMS_MISSING_STALE_OR_FUTURE"),
    (lambda i: replace(i, book=replace(i.book, yes_asks=())), "NO_QUALIFIED_MID"),
    (lambda i: replace(i, book=replace(i.book, no_asks=((D('.48'), D(100)),))), "CROSSED_BOOK"),
    (lambda i: replace(i, book=replace(i.book, yes_bids=((D('.49'), D(1)),))), "NO_QUALIFIED_MID"),
    (lambda i: replace(i, portfolio=replace(i.portfolio, safety_breached=True)), "SAFETY_BUDGET"),
    (lambda i: replace(i, portfolio=replace(i.portfolio, foreign_open_order=True)), "UNKNOWN_ACCOUNT_STATE"),
    (lambda i: replace(i, portfolio=replace(i.portfolio, unknown_position=True)), "UNKNOWN_ACCOUNT_STATE"),
    (lambda i: replace(i, horizon_days=0), "HORIZON_NOT_T1_T2"),
    (lambda i: replace(i, hazard_per_minute=None), "MISSING_CONSERVATIVE_FILL_BOUND"),
    (lambda i: replace(i, hazard_per_minute=1), "NONPOSITIVE_NET"),
    (lambda i: replace(i, fair_value=replace(i.fair_value, p_yes=.6, joint=None)), "FAIR_VALUE_DISAGREEMENT"),
    (lambda i: replace(i, fair_value=replace(i.fair_value, as_of_utc=i.now-timedelta(hours=2), valid_until_utc=i.now)), "FAIR_VALUE_INVALID_OR_EXPIRED"),
    (lambda i: replace(i, market=replace(i.market, close_at_utc=i.now+timedelta(hours=3))), "LAST_THREE_HOURS"),
    (lambda i: replace(i, book=replace(i.book, post_only_available=False)), "POST_ONLY_UNAVAILABLE"),
    (lambda i: replace(i, portfolio=replace(i.portfolio, cash=D(10))), "CASH_OR_CAP"),
    (lambda i: replace(i, terms=replace(i.terms, min_size=D(100))), "NO_ELIGIBLE_SIZE"),
])
def test_rule_vetoes(inputs, change, reason):
    d = decide(change(inputs))
    assert d.action == "NO_QUOTE"
    assert d.reasons == (reason,)


def test_information_windows_decided_and_future_events(inputs):
    def event(at, hint="pull", decided=None):
        return InfoEvent("scheduled_print", at, None, None, ("heads",), 1, decided, hint)
    for offset in (-10, 3):
        d = decide(replace(inputs, events=(event(inputs.now+timedelta(minutes=offset)),)))
        assert d.reasons == ("INFO_PULL",)
    assert decide(replace(inputs, events=(event(inputs.now+timedelta(minutes=4)),))).action == "QUOTE"
    assert decide(replace(inputs, events=(event(inputs.now, "observe", {"heads": .5}),))).reasons == ("DECIDED",)
    detected = InfoEvent("new_high", None, inputs.now, inputs.now+timedelta(seconds=1), ("heads",), 1, None, "pull")
    assert decide(replace(inputs, events=(detected,))).action == "QUOTE"
    assert decide(replace(inputs, events=(replace(detected, detected_at_utc=inputs.now),))).reasons == ("INFO_PULL",)


def test_nonfinite_hazard_refused_before_hash(inputs):
    with pytest.raises(ValueError, match="nonfinite"):
        replace(inputs, hazard_per_minute=float('nan'))


def test_grade_caps_uncertainty_and_unavailable(inputs):
    unscored = replace(inputs, fair_value=replace(inputs.fair_value, calibration_grade="none"))
    # Lower trust cannot increase size. Depth/share screen may also refuse it.
    d = decide(unscored)
    assert all(leg.size <= 30 for leg in d.legs)
    blind_width = decide(replace(inputs, fair_value=Unavailable("missing", inputs.now)))
    assert blind_width.legs == decide(inputs).legs
    wide = decide(replace(inputs, fair_value=replace(inputs.fair_value, stdev=.03)))
    assert all(leg.price <= D('.48') for leg in wide.legs)
    stale = replace(inputs.fair_value, as_of_utc=inputs.now-timedelta(minutes=59))
    assert decide(replace(inputs, fair_value=stale)).centre == D('.5')


def test_depth_empty_band_and_competition(inputs):
    thin = ((D('.49'), D(20)),)
    assert decide(replace(inputs, book=replace(inputs.book, yes_bids=thin))).reasons == ("INSUFFICIENT_DEPTH",)
    deep = ((D('.49'), D(10000)),)
    assert decide(replace(inputs, hazard_per_minute=0, book=replace(inputs.book, yes_bids=deep))).reasons == ("COMPETITION_OUTSIDE_RANGE",)


@pytest.mark.parametrize("changes", [
    {"cash": D(75), "reserved_elsewhere": D(65)}, {"band_cap": D(10)},
    {"wallet_used": D(195)}, {"event_used": D(145)},
    {"exposures": (ExposureLimit("coin", D(-1), D(99), D(100)),)},
])
def test_no_overcommitment_in_any_cap(inputs, changes):
    assert decide(replace(inputs, portfolio=replace(inputs.portfolio, **changes))).reasons == ("CASH_OR_CAP",)


def test_blind_hold_first_fill_and_single_band(inputs):
    i = replace(inputs, profile=blind_re1)
    d = decide(i)
    assert d.action == "QUOTE" and all(leg.size == 75 for leg in d.legs)
    assert decide(replace(i, existing=d.legs)).action == "HOLD"
    assert decide(replace(i, existing=d.legs, fill_seen=True)).action == "END"
    assert decide(replace(i, portfolio=replace(i.portfolio, active_other_bands=1))).reasons == ("ONE_BAND_ONLY",)
    assert decide(replace(inputs, existing=d.legs, fill_seen=True)).reasons == ("FILL_CANCEL_SIBLING",)
    assert decide(replace(i, existing=d.legs, terms=replace(i.terms, min_size=D(100)))).action == "CANCEL"


def test_adverse_leg_cancel_precedes_cooldown(inputs):
    initial = decide(inputs)
    moved = replace(inputs, existing=initial.legs, last_requote_at=inputs.now,
                    fair_value=replace(inputs.fair_value, stdev=.02, p_yes=.515, joint=None))
    assert decide(moved).action == "CANCEL"


def test_rank_and_inventory_exit_fee(inputs):
    assert rank((inputs, replace(inputs, horizon_days=0))) == (decide(inputs),)
    assert inventory_action(model_move=.01, exit_price=.5, expected_adverse_move=.0043,
                            reward_eligible_resting_sell=False) == "HOLD"
    assert inventory_action(model_move=.01, exit_price=.5, expected_adverse_move=.0043,
                            reward_eligible_resting_sell=True) == "RESTING_REWARD_SELL"
    assert inventory_action(model_move=.02, exit_price=.5, expected_adverse_move=.0043,
                            reward_eligible_resting_sell=False) == "EXIT_REVIEW"


def test_fictional_event_replay_byte_parity(inputs, tmp_path):
    event = InfoEvent("upload", inputs.now, None, None, ("heads",), 1, None, "pull")
    frames = (inputs, replace(inputs, events=(event,)), replace(inputs, fill_seen=True))
    first = tuple(decide(frame) for frame in frames)
    assert [d.action for d in first] == ["QUOTE", "NO_QUOTE", "CANCEL"]
    assert canonical_bytes(first) == canonical_bytes(tuple(decide(frame) for frame in frames))
    with Journal(tmp_path / "replay.jsonl", clock=lambda: inputs.now, scope={"domain": "coin"}) as journal:
        for frame, decision in zip(frames, first):
            journal.record("decision", inputs=frame, decision=decision)
        journal.record("terminal")
    assert len(verify_journal(journal.path)) == 5


def test_mid_range_and_raw_touch_buffer(inputs):
    outside = replace(inputs.book, yes_bids=((D('.18'), D(100)),), yes_asks=((D('.20'), D(100)),))
    assert decide(replace(inputs, book=outside)).reasons == ("MID_OUTSIDE_RANGE",)
    unsafe = replace(inputs.book, yes_asks=((D('.48'), D(1)), (D('.51'), D(100))),
                     yes_bids=((D('.47'), D(1)), (D('.46'), D(100))))
    d = decide(replace(inputs, book=unsafe, fair_value=Unavailable("missing", inputs.now)))
    assert all(leg.outcome != "YES" or leg.price <= D('.47') for leg in d.legs)


def test_sizing_adverse_leg_omission_and_cooldown(inputs):
    smaller = decide(replace(inputs, terms=replace(inputs.terms, max_spread_cents=D(5)),
                             portfolio=replace(inputs.portfolio, cash=D(50))))
    assert smaller.action == "QUOTE" and all(leg.size == 50 for leg in smaller.legs)
    asymmetric = replace(inputs, fair_value=replace(inputs.fair_value, p_yes=.53, stdev=.031, joint=None),
                         terms=replace(inputs.terms, max_spread_cents=D(5)), hazard_per_minute=0,
                         book=replace(inputs.book, yes_bids=((D('.49'), D(75)),), yes_asks=((D('.51'), D(75)),)))
    d = decide(asymmetric)
    assert d.action == "QUOTE" and d.centre == D('.5')
    assert [leg.outcome for leg in d.legs] == ["YES"]
    legs = tuple(replace(leg, price=D('.47')) for leg in decide(inputs).legs)
    resting = replace(inputs, terms=replace(inputs.terms, max_spread_cents=D(5)), existing=legs,
                      last_requote_at=inputs.now, hazard_per_minute=0)
    assert decide(resting).reasons == ("REQUOTE_COOLDOWN",)
    assert decide(replace(resting, last_requote_at=inputs.now-timedelta(seconds=60))).reasons == ("REQUOTE_REQUIRED",)


def test_share_pull_floor_and_terms_change_precede_hold(inputs):
    i = replace(inputs, profile=blind_re1)
    legs = decide(i).legs
    crowded = replace(i.book, yes_bids=((D('.49'), D(10000)),), yes_asks=((D('.51'), D(10000)),))
    assert decide(replace(i, existing=legs, book=crowded)).reasons == ("SHARE_BELOW_PULL_FLOOR",)
    assert decide(replace(i, existing=legs, terms=replace(i.terms, max_spread_cents=D(2)))).action == "CANCEL"


def test_reference_plugin_full_lifecycle_replay(inputs, tmp_path):
    from .fixtures.fictional_domain import FictionalDomain
    from maker_core.contracts import Pending, SettlementFact
    plugin = FictionalDomain()
    decisions = []
    moments = (inputs.now, plugin.market.close_at_utc-timedelta(minutes=2), plugin.market.settle_at_utc)
    for run in range(2):
        encoded = []
        with Journal(tmp_path / f"lifecycle-{run}.jsonl", clock=lambda: inputs.now,
                     scope={"domain": plugin.market.domain_id}) as journal:
            for now in moments:
                market = plugin.describe("heads", now)
                frame = replace(inputs, market=market, now=now,
                                book=replace(inputs.book, as_of_utc=now),
                                terms=replace(inputs.terms, as_of_utc=now),
                                fair_value=plugin.evaluate(market, now),
                                events=plugin.upcoming((market,), now, now+timedelta(minutes=3))
                                       + plugin.observe((market,), now))
                decision = decide(frame)
                fact = plugin.resolve(market, now)
                assert isinstance(fact, SettlementFact if now == moments[-1] else Pending)
                journal.record("frame", inputs=frame, decision=decision, settlement=fact)
                encoded.append(canonical_bytes(decision))
            journal.record("terminal")
        verify_journal(journal.path)
        decisions.append(encoded)
    assert decisions[0] == decisions[1]
    assert (tmp_path / "lifecycle-0.jsonl").read_bytes() == (tmp_path / "lifecycle-1.jsonl").read_bytes()
