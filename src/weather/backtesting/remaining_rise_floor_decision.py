"""Frozen decision rule for the t3-r3 13-16 remaining-rise look (``remaining_rise_floor_v1``).

Pure arithmetic over summary statistics that a later, pre-registered look
computes; this module reads no tape, settlement, panel or score data and has no
clock. It encodes the pre-registration's section 4 PASS rule and section 8
falsifiers and validity conditions
(``docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md``) as
decided by the owner on 2026-10-15:

- **PASS** requires the 13-16 fixed-market upper bound < 0 and the estimate at
  most -5% of the window's own 13-16 served-minus-market gap.
- **OD-B4:** sign consistency (at least 8 of 11 markets negative) is a reported
  guardrail, never a pass condition: ``sign_consistency.gating`` is always False.
- The crossed estimate is reported beside with no alpha; an opposite-sign
  crossed point estimate is reported as market-specific, never a pass condition.
- Any failed validity condition makes the look **VOID** (dates are spent),
  whatever the estimate says.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping

RULE_ID = "remaining_rise_floor_v1_decision"
STAGE_ID = "remaining_rise_floor_v1"
MATERIALITY_FRACTION = 0.05
SIGN_CONSISTENCY_MIN_NEGATIVE = 8
SIGN_CONSISTENCY_MARKETS = 11
SIGN_CONSISTENCY_GATING = False  # OD-B4 (2026-10-15): reported guardrail only
MIN_COVERAGE = 0.90
MAX_MEDIAN_METAR_AGE_MINUTES = 30.0
REPLAY_TOLERANCE = 1e-12

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_VOID = "VOID"


@dataclass(frozen=True)
class Validity:
    """Section 8 validity inputs, measured over the eligible 13-16 rows."""

    pit_violations: int
    artifact_hash_mismatches: int
    coverage: float
    median_metar_age_minutes: float | None
    replay_rows: int
    replay_rows_within_tolerance: int
    comparator_change_on_path: bool
    outcome_read_before_look: bool


@dataclass(frozen=True)
class LookSummary:
    """Section 4 primary statistics (13-16, fixed-market, date-clustered)."""

    estimate: float
    upper_bound: float
    served_minus_market_gap: float
    per_market_delta: Mapping[str, float]
    crossed_estimate: float | None = None
    crossed_interval: tuple[float, float] | None = None
    validity: Validity | None = None


@dataclass(frozen=True)
class Decision:
    verdict: str
    rule_id: str
    stage_id: str
    passed_conditions: dict
    falsifiers: list
    void_reasons: list
    sign_consistency: dict
    crossed: dict
    materiality_threshold: float
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def void_reasons(validity: Validity | None) -> list[str]:
    """Failed validity conditions; an empty list means the look is valid."""

    if validity is None:
        return ["validity_not_measured"]
    reasons = []
    if validity.pit_violations > 0:
        reasons.append("pit")
    if validity.artifact_hash_mismatches > 0:
        reasons.append("artifact_hash")
    if not validity.coverage >= MIN_COVERAGE:
        reasons.append("coverage")
    age = validity.median_metar_age_minutes
    if age is None or not age <= MAX_MEDIAN_METAR_AGE_MINUTES:
        reasons.append("freshness")
    if validity.replay_rows <= 0 or validity.replay_rows_within_tolerance != validity.replay_rows:
        reasons.append("replay")
    if validity.comparator_change_on_path:
        reasons.append("comparator")
    if validity.outcome_read_before_look:
        reasons.append("leakage")
    return reasons


def sign_consistency(per_market_delta: Mapping[str, float]) -> dict:
    """The OD-B4 guardrail: reported, never gating."""

    negative = sorted(market for market, delta in per_market_delta.items() if delta < 0)
    return {
        "negative_markets": len(negative),
        "markets": len(per_market_delta),
        "required_negative": SIGN_CONSISTENCY_MIN_NEGATIVE,
        "expected_markets": SIGN_CONSISTENCY_MARKETS,
        "met": len(negative) >= SIGN_CONSISTENCY_MIN_NEGATIVE,
        "gating": SIGN_CONSISTENCY_GATING,
        "negative": negative,
    }


def crossed_report(estimate: float, crossed_estimate: float | None, crossed_interval) -> dict:
    """Crossed estimate beside, no alpha; opposite sign is reported as market-specific."""

    disagree = crossed_estimate is not None and (crossed_estimate > 0) != (estimate > 0) and crossed_estimate != 0
    return {
        "estimate": crossed_estimate,
        "interval": list(crossed_interval) if crossed_interval is not None else None,
        "opposite_sign": bool(disagree),
        "gating": False,
    }


def decide(summary: LookSummary) -> Decision:
    """Apply the frozen rule. VOID dominates; otherwise PASS needs both gating conditions."""

    threshold = -MATERIALITY_FRACTION * summary.served_minus_market_gap
    upper_ok = summary.upper_bound < 0
    material_ok = summary.estimate <= threshold
    falsifiers = []
    if not upper_ok:
        falsifiers.append("route_closed")
    if not material_ok:
        falsifiers.append("immaterial")
    signs = sign_consistency(summary.per_market_delta)
    crossed = crossed_report(summary.estimate, summary.crossed_estimate, summary.crossed_interval)
    notes = []
    if not signs["met"]:
        notes.append("not_fleet_wide_reported_only")
    if crossed["opposite_sign"]:
        notes.append("crossed_disagreement_market_specific")
    if summary.served_minus_market_gap <= 0:
        notes.append("non_positive_gap")
    reasons = void_reasons(summary.validity)
    if reasons:
        verdict = VERDICT_VOID
    else:
        verdict = VERDICT_PASS if upper_ok and material_ok else VERDICT_FAIL
    return Decision(
        verdict=verdict,
        rule_id=RULE_ID,
        stage_id=STAGE_ID,
        passed_conditions={"upper_bound_below_zero": upper_ok, "material": material_ok},
        falsifiers=falsifiers,
        void_reasons=reasons,
        sign_consistency=signs,
        crossed=crossed,
        materiality_threshold=threshold,
        notes=notes,
    )
