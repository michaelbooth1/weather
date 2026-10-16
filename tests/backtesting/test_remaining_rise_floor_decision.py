"""t3-r3 13-16 decision rule: PASS conditions, OD-B4 sign-consistency guardrail, crossed report, VOID.

Guards: remaining-rise 13-16 pre-registration §4 (PASS) and §8 (falsifiers, validity conditions) as decided by
owner OD-B4 (2026-10-15): sign consistency is a reported guardrail, not a pass condition.
"""

import pytest

from weather.backtesting import remaining_rise_floor_decision as rule

MARKETS = [f"M{i:02d}" for i in range(11)]


def _valid(**overrides):
    values = {
        "pit_violations": 0,
        "artifact_hash_mismatches": 0,
        "coverage": 0.95,
        "median_metar_age_minutes": 10.0,
        "replay_rows": 100,
        "replay_rows_within_tolerance": 100,
        "comparator_change_on_path": False,
        "outcome_read_before_look": False,
    }
    values.update(overrides)
    return rule.Validity(**values)


def _summary(estimate=-0.01, upper=-0.002, gap=0.10, negative=11, crossed=-0.005, validity=None):
    deltas = {market: (-0.01 if i < negative else 0.01) for i, market in enumerate(MARKETS)}
    return rule.LookSummary(
        estimate=estimate,
        upper_bound=upper,
        served_minus_market_gap=gap,
        per_market_delta=deltas,
        crossed_estimate=crossed,
        crossed_interval=(-0.02, 0.01) if crossed is not None else None,
        validity=validity or _valid(),
    )


def test_pass_needs_upper_bound_below_zero_and_materiality():
    decision = rule.decide(_summary())
    assert decision.verdict == rule.VERDICT_PASS
    assert decision.falsifiers == [] and decision.void_reasons == []
    assert decision.materiality_threshold == pytest.approx(-0.005)


def test_upper_bound_boundary():
    assert rule.decide(_summary(upper=-1e-9)).verdict == rule.VERDICT_PASS
    decision = rule.decide(_summary(upper=0.0))
    assert decision.verdict == rule.VERDICT_FAIL
    assert decision.falsifiers == ["route_closed"]


def test_materiality_boundary_is_five_percent_of_gap():
    assert rule.decide(_summary(estimate=-0.05, gap=1.0)).verdict == rule.VERDICT_PASS
    decision = rule.decide(_summary(estimate=-0.0499, gap=1.0))
    assert decision.verdict == rule.VERDICT_FAIL
    assert decision.falsifiers == ["immaterial"]


def test_sign_consistency_is_reported_never_gating():
    met = rule.decide(_summary(negative=8)).sign_consistency
    assert (met["negative_markets"], met["met"], met["gating"]) == (8, True, False)
    decision = rule.decide(_summary(negative=7))
    assert decision.verdict == rule.VERDICT_PASS
    assert decision.sign_consistency["met"] is False
    assert decision.sign_consistency["gating"] is False
    assert "not_fleet_wide_reported_only" in decision.notes


def test_crossed_disagreement_is_reported_not_gating():
    decision = rule.decide(_summary(crossed=0.003))
    assert decision.verdict == rule.VERDICT_PASS
    assert decision.crossed["opposite_sign"] is True
    assert "crossed_disagreement_market_specific" in decision.notes
    assert rule.decide(_summary(crossed=-0.001)).crossed["opposite_sign"] is False
    assert rule.decide(_summary(crossed=None)).crossed["opposite_sign"] is False


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"pit_violations": 1}, "pit"),
        ({"artifact_hash_mismatches": 1}, "artifact_hash"),
        ({"coverage": 0.8999}, "coverage"),
        ({"median_metar_age_minutes": 30.01}, "freshness"),
        ({"median_metar_age_minutes": None}, "freshness"),
        ({"replay_rows_within_tolerance": 99}, "replay"),
        ({"replay_rows": 0, "replay_rows_within_tolerance": 0}, "replay"),
        ({"comparator_change_on_path": True}, "comparator"),
        ({"outcome_read_before_look": True}, "leakage"),
    ],
)
def test_each_failed_validity_condition_voids_a_passing_look(overrides, reason):
    decision = rule.decide(_summary(validity=_valid(**overrides)))
    assert decision.verdict == rule.VERDICT_VOID
    assert decision.void_reasons == [reason]


def test_validity_boundaries_are_inclusive():
    decision = rule.decide(_summary(validity=_valid(coverage=0.90, median_metar_age_minutes=30.0)))
    assert decision.verdict == rule.VERDICT_PASS


def test_unmeasured_validity_is_void():
    summary = rule.LookSummary(estimate=-0.01, upper_bound=-0.002, served_minus_market_gap=0.1, per_market_delta={})
    assert rule.decide(summary).void_reasons == ["validity_not_measured"]


def test_decision_serialises():
    assert rule.decide(_summary()).to_dict()["rule_id"] == rule.RULE_ID
