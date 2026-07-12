"""Pure current/incumbent blend policy shared by live serving and replay.

The policy deliberately resolves one alpha per market-band row.  Keeping the
resolver independent of either adapter makes market overrides, source-health
caps, contextual overrides, and multiple matching rules replayable byte for
byte.  Context rules are evaluated in declaration order and the last matching
rule wins, which preserves the historical replay contract.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


_RULE_METADATA_FIELDS = {"alpha", "policy_id", "description"}
_SOURCE_LIST_LIMIT = 3


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _source_state(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or "").strip().lower()
    ok = _boolish(row.get("ok"))
    stale = _boolish(row.get("stale"))
    if ok is False or status in {"failed", "error", "missing"}:
        return "failed"
    if stale is True or status in {"stale", "stale_cache", "expired"}:
        return "stale"
    if ok is True or status in {"fresh", "ok", "available"}:
        return "fresh"
    return "unknown"


def _source_list_label(sources: Sequence[str]) -> str:
    names = sorted(str(source) for source in sources if str(source or "").strip())
    if len(names) <= _SOURCE_LIST_LIMIT:
        return ",".join(names)
    return f"{','.join(names[:_SOURCE_LIST_LIMIT])},+{len(names) - _SOURCE_LIST_LIMIT}"


def source_freshness_state_from_diagnostics(diagnostics: Any) -> str:
    """Collapse live diagnostic rows to the replay freshness-group taxonomy.

    Missing or malformed diagnostics fail closed as ``missing_source_status``;
    they are never inferred to be healthy.
    """

    if isinstance(diagnostics, Mapping):
        rows = []
        for source, raw in diagnostics.items():
            row = dict(raw) if isinstance(raw, Mapping) else {}
            row.setdefault("source", source)
            rows.append(row)
    elif isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        rows = [row for row in diagnostics if isinstance(row, Mapping)]
    else:
        rows = []
    if not rows:
        return "missing_source_status"

    by_state: dict[str, list[str]] = defaultdict(list)
    observed = 0
    for row in rows:
        source = str(row.get("source") or "").strip()
        if not source:
            continue
        observed += 1
        state = _source_state(row)
        if state != "fresh":
            by_state[state].append(source)
    if not observed:
        return "missing_source_status"
    parts = [
        f"{state}:{_source_list_label(by_state[state])}"
        for state in ("failed", "stale", "unknown")
        if by_state.get(state)
    ]
    return ";".join(parts) if parts else "all_fresh"


def _cutoff_regime(value: Any) -> str:
    try:
        hour = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if hour <= 8:
        return "early"
    if hour <= 14:
        return "midday"
    return "late"


def _forecast_source_count_bucket(value: Any) -> str:
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if count <= 1:
        return "low_count"
    if count == 2:
        return "two_sources"
    return "three_plus_sources"


def _forecast_disagreement_bucket(value: Any) -> str:
    try:
        disagreement = abs(float(value))
    except (TypeError, ValueError):
        return "unknown"
    if disagreement < 1.0:
        return "low_disagreement"
    if disagreement < 2.5:
        return "moderate_disagreement"
    return "high_disagreement"


def _forecast_bucket_pressure(value: Any) -> str:
    try:
        pressure = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if pressure <= -1.0:
        return "cool_side"
    if pressure >= 1.0:
        return "warm_side"
    return "near_forecast"


def canonical_current_blend_context(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Fill only deterministic context aliases shared by live and replay."""

    context = dict(row or {})
    source_state = (
        context.get("source_freshness_state")
        or context.get("source_status_group")
        or "missing_source_status"
    )
    context["source_freshness_state"] = source_state
    context.setdefault("source_status_group", source_state)

    cutoff_hour = context.get("cutoff_hour")
    if cutoff_hour in (None, ""):
        cutoff_hour = context.get("candidate_cutoff_hour")
    cutoff_regime = context.get("cutoff_regime") or context.get("candidate_cutoff_regime")
    context["cutoff_regime"] = cutoff_regime or _cutoff_regime(cutoff_hour)

    if context.get("forecast_source_count_bucket") in (None, ""):
        context["forecast_source_count_bucket"] = _forecast_source_count_bucket(
            context.get("forecast_source_count")
        )
    if context.get("forecast_disagreement_bucket") in (None, ""):
        context["forecast_disagreement_bucket"] = _forecast_disagreement_bucket(
            context.get("forecast_disagreement")
        )
    if context.get("forecast_bucket_pressure") in (None, ""):
        context["forecast_bucket_pressure"] = _forecast_bucket_pressure(
            context.get("band_mid_minus_forecast")
        )
    return context


def current_blend_context_value(row: Mapping[str, Any] | None, key: str) -> Any:
    context = canonical_current_blend_context(row)
    if key == "cutoff_hour":
        value = context.get("cutoff_hour")
        return value if value not in (None, "") else context.get("candidate_cutoff_hour", "")
    return context.get(key)


def current_blend_context_rule_matches(
    row: Mapping[str, Any] | None,
    rule: Mapping[str, Any] | None,
) -> bool:
    context = canonical_current_blend_context(row)
    for key, expected in (rule or {}).items():
        if key in _RULE_METADATA_FIELDS:
            continue
        if key.endswith("_min") or key.endswith("_max"):
            base_key = key[:-4]
            actual = current_blend_context_value(context, base_key)
            try:
                actual_value = float(actual)
                expected_value = float(expected)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(actual_value) or not math.isfinite(expected_value):
                return False
            if key.endswith("_min") and actual_value < expected_value:
                return False
            if key.endswith("_max") and actual_value > expected_value:
                return False
            continue
        actual = current_blend_context_value(context, key)
        expected_values = expected if isinstance(expected, list) else [expected]
        if str(actual) not in {str(value) for value in expected_values}:
            return False
    return True


def resolve_current_blend_alpha(
    row: Mapping[str, Any] | None,
    config: Mapping[str, Any] | None,
) -> float:
    """Resolve candidate weight using the canonical ordered policy.

    Precedence is market/default, then a source-state cap, then contextual
    overrides in declaration order.  Therefore, when multiple context rules
    match, the last matching rule is authoritative.
    """

    context = canonical_current_blend_context(row)
    config = config or {}
    market_alpha = config.get("current_blend_market_alpha") or {}
    market_id = context.get("market_id")
    if isinstance(market_alpha, Mapping) and market_id in market_alpha:
        alpha: Any = market_alpha[market_id]
    else:
        alpha = config.get("current_blend_default_alpha", 1.0)

    source_alpha = config.get("current_blend_source_freshness_alpha") or {}
    if isinstance(source_alpha, Mapping) and source_alpha:
        source_state = context["source_freshness_state"]
        source_default = config.get("current_blend_source_freshness_default_alpha", 0.0)
        source_state_alpha = source_alpha.get(source_state, source_default)
        try:
            alpha = min(float(alpha), float(source_state_alpha))
        except (TypeError, ValueError):
            alpha = source_state_alpha

    rules = config.get("current_blend_context_alpha") or []
    if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes)):
        for rule in rules:
            if isinstance(rule, Mapping) and current_blend_context_rule_matches(context, rule):
                alpha = rule.get("alpha", alpha)
    try:
        resolved = float(alpha)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(resolved):
        return 1.0
    return max(0.0, min(1.0, resolved))


def blend_with_current(
    candidate_probability: Any,
    incumbent_probability: Any,
    *,
    row: Mapping[str, Any] | None,
    config: Mapping[str, Any] | None,
) -> float:
    """Apply the resolved candidate weight to one candidate/incumbent pair."""

    candidate = max(0.0, min(1.0, float(candidate_probability)))
    incumbent = max(0.0, min(1.0, float(incumbent_probability)))
    alpha = resolve_current_blend_alpha(row, config)
    return (alpha * candidate) + ((1.0 - alpha) * incumbent)
