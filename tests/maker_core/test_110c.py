"""Synthetic regressions for the pre-tag contract/policy review."""
from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from maker_core.contracts import InfoEvent, MarketDescriptor, SettlementFact, Unavailable
from maker_core.evidence.journal import Journal, SecretGuard
from maker_core.quoting.policy import decide, informed_v0


def test_contract_additions_are_trailing_and_defaulted(inputs):
    assert fields(MarketDescriptor)[-1].name == "group_relation"
    assert inputs.market.group_relation is None
    assert fields(InfoEvent)[-1].name == "active_until_utc"
    assert InfoEvent("poll", inputs.now, None, None, (), 0, None, "observe").active_until_utc is None
    assert fields(Unavailable)[-1].name == "kind"
    assert Unavailable("missing", inputs.now).kind == "missing_input"
    assert fields(SettlementFact)[-1].name == "resolved_value"
    assert SettlementFact("heads", 1, inputs.now, {"source": "hash"}, "checked").resolved_value is None


@pytest.mark.parametrize("relation", ["partition", "nested_ge", "nested_le"])
def test_group_relations(inputs, relation):
    assert replace(inputs.market, group_relation=relation).group_relation == relation
    with pytest.raises(ValueError):
        replace(inputs.market, group_relation="exclusive")


@pytest.mark.parametrize("kind", ["missing_input", "out_of_scope", "corrupt", "decided"])
def test_unavailable_kinds(inputs, kind):
    assert Unavailable("reason", inputs.now, kind).kind == kind
    with pytest.raises(ValueError):
        Unavailable("reason", inputs.now, "unknown")


@pytest.mark.parametrize("p", [0., 1.])
def test_decided_zero_stdev(inputs, p):
    assert replace(inputs.fair_value, p_yes=p, stdev=0., joint=None).stdev == 0
    with pytest.raises(ValueError):
        replace(inputs.fair_value, p_yes=.5, stdev=0., joint=None)


def test_settlement_resolved_text(inputs):
    fact = SettlementFact("heads", 1., inputs.now, {"source": "hash"}, "checked", "123 views")
    assert fact.resolved_value == "123 views"
    with pytest.raises(ValueError):
        replace(fact, resolved_value=123)


@pytest.mark.parametrize("reference", ["scheduled_at_utc", "observed_at_utc", "detected_at_utc"])
def test_event_expiry_validation(inputs, reference):
    times = dict.fromkeys(("scheduled_at_utc", "observed_at_utc", "detected_at_utc"))
    times[reference] = inputs.now
    event = InfoEvent("poll", **times, affects=("heads",), severity=1, decided=None,
                      action_hint="pull", active_until_utc=inputs.now)
    assert decide(replace(inputs, events=(event,))).reasons == ("INFO_PULL",)
    for expiry in (inputs.now-timedelta(seconds=1), inputs.now.replace(tzinfo=None)):
        with pytest.raises(ValueError):
            replace(event, active_until_utc=expiry)
    with pytest.raises(ValueError):
        replace(event, **{reference: None})


def test_half_tick_maximum_width_stays_in_window(inputs):
    book = replace(inputs.book, yes_bids=((D('.49'), D(75)),), yes_asks=((D('.52'), D(75)),),
                   no_bids=((D('.48'), D(75)),), no_asks=((D('.51'), D(75)),))
    i = replace(inputs, book=book, terms=replace(inputs.terms, max_spread_cents=D(5)),
                fair_value=replace(inputs.fair_value, p_yes=.505, stdev=.03, joint=None))
    result = decide(i)
    assert result.action == "QUOTE", result.reasons
    assert len(result.legs) == 2
    assert tuple(leg.price for leg in result.legs) == (D('.48'), D('.47'))
    assert all(D(1) <= ((result.centre if leg.outcome == 'YES' else 1-result.centre)-leg.price)*100 <= D(3)
               for leg in result.legs)


@pytest.mark.parametrize("shift", [D('-.01'), D('.01')])
@pytest.mark.parametrize("elapsed", [0, 120])
def test_one_tick_mid_only_move_holds(inputs, shift, elapsed):
    inputs = replace(inputs, terms=replace(inputs.terms, max_spread_cents=D(5)))
    initial = decide(inputs)
    def moved(levels, delta):
        return tuple((price+delta, size) for price, size in levels)
    book = replace(inputs.book, yes_bids=moved(inputs.book.yes_bids, shift),
                   yes_asks=moved(inputs.book.yes_asks, shift),
                   no_bids=moved(inputs.book.no_bids, -shift), no_asks=moved(inputs.book.no_asks, -shift))
    yes, no = initial.legs
    book = replace(book, yes_bids=book.yes_bids+((yes.price, yes.size),),
                   yes_asks=book.yes_asks+((1-no.price, no.size),))
    result = decide(replace(inputs, existing=initial.legs, book=book, previous_fair_value=.5,
                            last_requote_at=inputs.now-timedelta(seconds=elapsed)))
    assert result.action == "HOLD", result.reasons
    assert result.legs == initial.legs


def test_own_legs_removed_from_competition(inputs):
    initial = decide(inputs)
    yes, no = initial.legs
    with_own = replace(inputs.book, yes_bids=inputs.book.yes_bids+((yes.price, yes.size),),
                       yes_asks=inputs.book.yes_asks+((1-no.price, no.size),))
    result = decide(replace(inputs, book=with_own, existing=initial.legs, previous_fair_value=.5))
    assert result.action == "HOLD"
    assert result.share_many == pytest.approx(initial.share_many)
    assert result.net_per_minute == pytest.approx(initial.net_per_minute)


def test_missing_view_cannot_retain_larger_resting_size(inputs):
    result = decide(replace(inputs, existing=decide(inputs).legs,
                            fair_value=Unavailable("missing", inputs.now)))
    assert result.action == "CANCEL" and result.reasons == ("GRADE_SIZE_CAP",)


def test_profile_horizon_and_hint_are_domain_neutral(inputs):
    custom = replace(informed_v0, eligible_horizons=(0, 3))
    assert decide(replace(inputs, profile=custom, horizon_days=3)).action == "QUOTE"
    event = InfoEvent("new_high", inputs.now, None, None, ("heads",), 0, None, "observe")
    assert decide(replace(inputs, events=(event,))).action == "QUOTE"
    assert decide(replace(inputs, events=(replace(event, kind="count_update", action_hint="pull"),))).action == "NO_QUOTE"


def test_expired_detected_events_do_not_widen(inputs):
    old = inputs.now-timedelta(days=2)
    events = tuple(InfoEvent("model_cycle", None, old, old, ("heads",), 1, None, "widen",
                            old+timedelta(minutes=10)) for _ in range(2))
    assert decide(replace(inputs, events=events)).legs == decide(inputs).legs


@pytest.mark.parametrize("key", ["x-api-key", "POLY_PASSPHRASE", "X_Secret", "session-token",
                                "Bearer-Value", "walletMnemonic", "seed_phrase", "private_material"])
def test_guard_normalized_substrings(key):
    assert SecretGuard().clean({"nested": [{key: "synthetic", "value": 7}]}) == {"nested": [{"value": 7}]}


def test_opening_failure_removes_only_new_journal(inputs, tmp_path, monkeypatch):
    import maker_core.evidence.journal as journal
    path = tmp_path / "failed.jsonl"
    def fail(_):
        raise OSError("synthetic fsync failure")
    monkeypatch.setattr(journal.os, "fsync", fail)
    with pytest.raises(OSError):
        Journal(path, clock=lambda: inputs.now, scope={})
    assert not path.exists()
    path.write_text("existing evidence")
    with pytest.raises(FileExistsError):
        Journal(path, clock=lambda: inputs.now, scope={})
    assert path.read_text() == "existing evidence"
