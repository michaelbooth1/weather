from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from maker_core.contracts import InfoEvent
from maker_core.evidence.journal import digest, plain
from maker_core.quoting.one_sided import (
    MIN_MARGIN, NAME, EdgeProfile, decide_one_sided, edge_inputs, one_sided_edge_v0,
)
from maker_core.quoting.policy import QuoteLeg, blind_re1, decide, informed_v0
from maker_core.quoting.rewards import order_score, q_min, share_of
from maker_core.replay.bundle import BundleError
from maker_core.replay.engine import ReplayConfig, replay
from maker_core.replay.one_sided import EdgeReplayConfig, edge_replay
from maker_core.replay.one_sided_report import (
    EDGE_POLICIES, edge_comparison_report, edge_report_bytes, fill_markout_cells, read_edge_authorization,
)
from .fixtures.replay_scenario import Scenario

SKILLED = EdgeProfile(NAME, True, z=1.0, K=10.0, skilled_cells=(("known-bias", 2),))
MU = 1.0 * .015 + MIN_MARGIN  # Fixture view stdev .015, zero age.


def dead(now, cid="heads"):
    return InfoEvent("decided", None, now, now, (cid,), 1., {cid: 1.}, "pull")


def viewed(i, p):
    return replace(i, fair_value=replace(i.fair_value, p_yes=p, joint=None))


# Golden: pinned at b157c52a (pre-change tip) with no tracked file modified.
GOLDEN = {"informed-v0": (16, "768d029154f49b92967d896782bab944c53e9b8c34fd70f75bc1c59bbca045a7",
                          "16604f09ec101ce9d049a318a0f953dcef6b0889a08642d89be81ec2d778d740"),
          "blind_re1": (14, "2091cf25b54e88c5e0a4364fe1083572c136b6031c149c67dea9a0d2b2fe8831",
                        "5e0d67d79120082dc72f0edeb83ad812769b91b4528f8e7dbcefc8f2b399a761")}


def golden_scenario():
    s = Scenario(minutes=6)
    for minute in range(6):
        for market in s.markets:
            s.book(market, minute*60)
    s.trade("a", 150, price=".47", size="10")
    return s


def test_frozen_profiles_decisions_and_input_hashes_are_byte_identical(tmp_path, inputs):
    bundle = golden_scenario().bundle(tmp_path / "golden")
    for policy, (count, decisions, hashes) in GOLDEN.items():
        result = replay((bundle,), ReplayConfig(policy=policy, hazard_per_minute=.001))
        assert (len(result.decisions), digest(result.decisions),
                digest(sorted(d.decision.input_hash for d in result.decisions))) == (count, decisions, hashes)
    assert digest(informed_v0) == "ce4b9f010afb246caa275be61e0403f156eb26da0c4e0000b75aa8e2cb8dd378"
    assert digest(blind_re1) == "967054c81b6a2b82def04c06287f48b9a74d8845a28da70e1f5ce18da59d43c0"
    assert decide(inputs).input_hash == "7b62453b808e4887a2ef606d7adaaf49955b1fd6e9d36991ab8ea71583b24ed1"
    # The edge profile cannot run through the frozen kernel.
    assert decide(replace(inputs, profile=one_sided_edge_v0)).reasons == ("UNSUPPORTED_PROFILE",)


def test_profile_validation_and_defaults():
    assert one_sided_edge_v0.z is None and one_sided_edge_v0.K is None and one_sided_edge_v0.skilled_cells == ()
    assert one_sided_edge_v0.eligible_horizons == (0, 1, 2)
    for bad in (dict(a=.004), dict(z=0.), dict(K=float("nan")), dict(first_fill_ends=True)):
        with pytest.raises(ValueError):
            EdgeProfile(NAME, True, **bad)
    with pytest.raises(ValueError):
        EdgeProfile("informed-v0", True)


def test_fallback_is_the_unchanged_symmetric_decision(inputs):
    base, edge = decide(inputs), decide_one_sided(edge_inputs(inputs))
    assert edge.legs == base.legs and edge.action == base.action == "QUOTE"
    assert edge.reasons == (*base.reasons, "SYMMETRIC_FALLBACK") and edge.profile == NAME
    assert edge.input_hash != base.input_hash and edge.signal == "none" and edge.expected_edge is None
    # Unfixed z/K: even a large skilled disagreement never becomes a model side.
    unfixed = decide_one_sided(edge_inputs(viewed(inputs, .6), replace(one_sided_edge_v0, skilled_cells=SKILLED.skilled_cells)))
    assert unfixed.reasons == ("FAIR_VALUE_DISAGREEMENT", "SYMMETRIC_FALLBACK") and not unfixed.legs


@pytest.mark.parametrize("p,side", [(.5 + MU + .001, "YES"), (.5 - MU - .001, "NO"),
                                    (.5 + MU - .001, None), (.5 - MU + .001, None)])
def test_model_side_only_beyond_margin(inputs, p, side):
    d = decide_one_sided(edge_inputs(viewed(inputs, p), SKILLED))
    if side is None:
        assert d.reasons[-1] == "SYMMETRIC_FALLBACK" and d.signal == "none"
    else:
        assert d.reasons == ("ONE_SIDED_QUOTE",) and d.signal == "model"
        assert [leg.outcome for leg in d.legs] == [side] and d.legs[0].price == D(".49")
        fair = p if side == "YES" else 1 - p
        assert d.expected_edge == pytest.approx(fair - .49)


def test_model_side_needs_skilled_scored_cell_and_plausible_edge(inputs):
    strong = viewed(inputs, .5 + MU + .001)
    for profile, i in ((replace(SKILLED, skilled_cells=()), strong),
                       (replace(SKILLED, skilled_cells=(("known-bias", 1),)), strong),
                       (SKILLED, replace(strong, fair_value=replace(strong.fair_value, calibration_grade="shadow"))),
                       (SKILLED, viewed(inputs, .5 + 10 * .015 + .01))):
        assert decide_one_sided(edge_inputs(i, profile)).signal == "none"


def test_dead_band_quotes_no_and_vetoes_yes(inputs):
    i = edge_inputs(inputs, events=(dead(inputs.now),), band_kind="eq")
    d = decide_one_sided(i)
    assert d.signal == "observed_dead" and [(l.outcome, l.price) for l in d.legs] == [("NO", D(".49"))]
    assert d.expected_edge == pytest.approx(.51)
    # The model pointing YES cannot override an impossible band.
    yes_model = decide_one_sided(edge_inputs(viewed(inputs, .6), SKILLED, events=(dead(inputs.now),), band_kind="lte"))
    assert [leg.outcome for leg in yes_model.legs] == ["NO"]
    # Monotone running max: routine print pulls do not pull the dead-band NO leg.
    pull = InfoEvent("scheduled_print", inputs.now, None, None, ("heads",), 1., None, "pull")
    assert decide_one_sided(replace(i, events=(dead(inputs.now), pull))).signal == "observed_dead"
    # T+0 is eligible for the signal; the symmetric fallback there stays informed-v0's refusal.
    assert decide_one_sided(replace(i, horizon_days=0)).action == "QUOTE"
    assert decide_one_sided(edge_inputs(replace(inputs, horizon_days=0))).reasons[0] == "HORIZON_NOT_ELIGIBLE"


def test_reached_open_top_and_unknown_direction_never_quote_no(inputs):
    reached = edge_inputs(inputs, events=(dead(inputs.now),), band_kind="gte")
    assert not decide_one_sided(reached).legs
    no_model = decide_one_sided(edge_inputs(viewed(inputs, .4), SKILLED, events=(dead(inputs.now),), band_kind="gte"))
    assert not any(leg.outcome == "NO" for leg in no_model.legs)
    pair = (QuoteLeg("YES", D(".48"), D(75)), QuoteLeg("NO", D(".48"), D(75)))
    assert decide_one_sided(replace(reached, existing=pair)).reasons == ("OBSERVED_VETO",)
    assert decide_one_sided(replace(reached, band_kind=None)).reasons == ("DECIDED_DIRECTION_UNKNOWN",)


def test_one_yes_leg_per_event(inputs):
    i = edge_inputs(viewed(inputs, .5 + MU + .001), SKILLED, event_yes_elsewhere=True)
    assert decide_one_sided(i).reasons == ("ONE_YES_PER_EVENT",)
    no_side = edge_inputs(viewed(inputs, .5 - MU - .001), SKILLED, event_yes_elsewhere=True)
    assert decide_one_sided(no_side).action == "QUOTE"


def test_one_sided_reward_score_is_a_third_inside_the_band_and_zero_outside():
    for mid in (.10, .5, .90):
        assert q_min(30., 0., mid) == pytest.approx(10.)
    for mid in (.0999, .9001):
        assert q_min(30., 0., mid) == 0.


def test_kernel_share_uses_the_one_sided_score_and_mid_band(inputs):
    i = edge_inputs(inputs, events=(dead(inputs.now),), band_kind="eq")
    d = decide_one_sided(i)
    own = order_score(75., 1., 3., 20.)
    competing = (order_score(100., 1., 3., 20.) * 2) / 2
    assert d.share_many == pytest.approx(share_of(own / 3, competing))
    edge = replace(i, book=replace(i.book, yes_bids=((D(".94"), D(100)),), yes_asks=((D(".96"), D(100)),),
                                   no_bids=((D(".04"), D(100)),), no_asks=((D(".06"), D(100)),)))
    assert decide_one_sided(edge).reasons == ("MID_OUTSIDE_ONE_SIDED_RANGE",)


def test_pulls_widen_side_flip_and_signal_changes_cancel(inputs):
    i = edge_inputs(viewed(inputs, .5 + MU + .001), SKILLED)
    pull = InfoEvent("scheduled_print", i.now, None, None, ("heads",), 1., None, "pull")
    assert decide_one_sided(replace(i, events=(pull,))).reasons == ("INFO_PULL",)
    widen = InfoEvent("model_cycle", None, i.now, i.now, ("heads",), 1., None, "widen", i.now + timedelta(minutes=10))
    older = replace(i, fair_value=replace(i.fair_value, as_of_utc=i.now - timedelta(minutes=5)))
    assert decide_one_sided(replace(older, events=(widen,))).reasons == ("AWAIT_FRESH_VIEW",)
    assert decide_one_sided(replace(i, events=(widen,))).reasons == ("ONE_SIDED_QUOTE",)  # View is not older.
    yes_leg, no_leg = (QuoteLeg("YES", D(".49"), D(75)),), (QuoteLeg("NO", D(".49"), D(75)),)
    # As in replay, the displayed book includes own resting size; the kernel removes it.
    held = decide_one_sided(replace(i, existing=yes_leg, book=replace(i.book, yes_bids=((D(".49"), D(175)),))))
    assert held.action == "HOLD" and held.legs == yes_leg
    flip = decide_one_sided(replace(i, existing=no_leg))
    assert (flip.action, flip.reasons) == ("CANCEL", ("SIDE_FLIP",))
    lost = decide_one_sided(replace(edge_inputs(inputs), existing=yes_leg))
    assert (lost.action, lost.reasons) == ("CANCEL", ("SIGNAL_LOST",))
    pair = (QuoteLeg("YES", D(".48"), D(75)), QuoteLeg("NO", D(".48"), D(75)))
    assert decide_one_sided(replace(i, existing=pair)).reasons == ("SIGNAL_ONSET",)


def test_hold_to_settlement_after_fill(inputs):
    i = edge_inputs(inputs, events=(dead(inputs.now),), band_kind="eq", fill_seen=True)
    assert decide_one_sided(i).reasons == ("HOLD_TO_SETTLEMENT",) and not decide_one_sided(i).legs


def dead_band_scenario(minutes=6, band_kind="eq"):
    s = Scenario(markets=("a",), minutes=minutes)
    cid = s.cid("a")
    if band_kind is not None:
        s.add("a", "plugin_input", 0, dict(source="snapshots", original_captured_at=s.at(0).isoformat(),
              record=dict(condition_id=cid, bin_kind=band_kind, captured_at_utc=s.at(0).isoformat())))
    s.add("a", "info_event", 60, {"events": [dead(s.at(60), cid)]})
    for minute in range(minutes):
        s.book("a", minute*60)
    return s


def test_replay_quotes_dead_band_no_while_informed_pulls(tmp_path):
    bundle = dead_band_scenario().bundle(tmp_path / "b")
    config = EdgeReplayConfig(hazard_per_minute=.001)
    edge = edge_replay((bundle,), config)
    informed = replay((bundle,), config.base())
    after = [d.decision for d in edge.decisions if d.at >= bundle.conditions[0].active_from + timedelta(seconds=60)]
    assert any(d.action == "QUOTE" and [l.outcome for l in d.legs] == ["NO"] for d in after)
    assert all(d.profile == NAME for d in after)
    assert any(d.decision.reasons == ("DECIDED",) for d in informed.decisions)
    assert edge.config is config and plain(edge.config)["profile"]["name"] == NAME
    unknown = edge_replay((dead_band_scenario(band_kind=None).bundle(tmp_path / "u"),), config)
    assert any(d.decision.reasons == ("DECIDED_DIRECTION_UNKNOWN",) for d in unknown.decisions)
    assert not any(leg.outcome == "YES" for d in edge.decisions for leg in d.decision.legs
                   if d.at >= bundle.conditions[0].active_from + timedelta(seconds=60))


def test_replay_holds_filled_band_to_settlement(tmp_path):
    s = dead_band_scenario(minutes=8)
    s.trade("a", 150, price=".48", size="10", outcome="NO")
    s.settle("a", 420, p=0)
    result = edge_replay((s.bundle(tmp_path / "b"),), EdgeReplayConfig(hazard_per_minute=.001))
    assert len(result.fills) == 1 and result.fills[0].outcome == "NO"
    later = [d.decision for d in result.decisions if d.at > result.fills[0].at]
    assert later and not any(d.action == "QUOTE" for d in later)
    assert any(d.reasons == ("HOLD_TO_SETTLEMENT",) for d in later)
    cells, unresolved = fill_markout_cells(result)
    assert unresolved == [] and list(cells.values()) == [pytest.approx(1 - .49)]


def test_replay_one_yes_leg_per_event(tmp_path):
    s = Scenario(minutes=3)
    for market in s.markets:
        shared = replace(s.descriptors[market], event_id="event-shared")
        s.add(market, "descriptor", 0, dict(market=plain(shared), horizon_days=2))
        s.view(market, 0, p=.5 + MU + .001, grade="scored")
        for minute in range(3):
            s.book(market, minute*60)
    profile = replace(SKILLED, skilled_cells=(("synthetic", 2),))
    result = edge_replay((s.bundle(tmp_path / "b"),), EdgeReplayConfig(hazard_per_minute=.001, profile=profile))
    reasons = {d.condition_id: d.decision.reasons for d in result.decisions if d.at == s.start}
    assert reasons[s.cid("a")] == ("ONE_SIDED_QUOTE",) and reasons[s.cid("b")] == ("ONE_YES_PER_EVENT",)


def test_edge_config_and_report_allowlists(tmp_path):
    with pytest.raises(BundleError):
        EdgeReplayConfig(policy="informed-v0")
    assert EDGE_POLICIES[0] == NAME and set(EDGE_POLICIES[1:]) == {"informed-v0", "no_quote", "blind_re1", "clock_only"}
    with pytest.raises(BundleError, match="not_approved"):
        read_edge_authorization(tmp_path / "missing.json", "0" * 64)
    bundle = dead_band_scenario().bundle(tmp_path / "r")
    report = edge_comparison_report((bundle,), EdgeReplayConfig(hazard_per_minute=.001), replicates=100)
    bound = report["bounds"]["strictly_through"]
    assert report["candidate"] == NAME and set(bound["scores"]) == set(EDGE_POLICIES)
    assert "fill_markout" in bound and report["status"] == "FIXTURE_ONLY"
    raw, text = edge_report_bytes(report)
    assert raw and b"Settlement markout per filled share" in text
