"""Shared fail-closed policy for supervised label and outcome fields."""

from __future__ import annotations

from collections.abc import Iterable


# Exact names cover legacy settlement aliases as well as derived research
# targets. Prefix/suffix rules cover schema additions without requiring every
# future label column to be added before it is rejected.
FORBIDDEN_LABEL_OUTCOME_FIELDS = frozenset(
    {
        "actual_high",
        "final_high",
        "high",
        "label",
        "max_temp",
        "observed_high",
        "outcome",
        "rounded_high",
        "settled_high",
        "settlement",
        "target",
        "target_market_z",
        "truth",
        "y",
    }
)
FORBIDDEN_LABEL_OUTCOME_PREFIXES = (
    "label_",
    "outcome_",
    "settlement_",
    "target_",
    "truth_",
    "winning_band",
)
FORBIDDEN_LABEL_OUTCOME_SUFFIXES = ("_label", "_outcome")


class ForbiddenLabelOutcomeFeatureError(ValueError):
    """Raised when a label or outcome field reaches a feature boundary."""


def _normalized_field_name(name: str) -> str:
    return str(name).strip().casefold()


def is_forbidden_label_outcome_field(name: str) -> bool:
    """Return whether ``name`` is reserved for labels/outcomes, case-insensitively."""
    normalized = _normalized_field_name(name)
    return (
        normalized in FORBIDDEN_LABEL_OUTCOME_FIELDS
        or normalized.startswith(FORBIDDEN_LABEL_OUTCOME_PREFIXES)
        or normalized.endswith(FORBIDDEN_LABEL_OUTCOME_SUFFIXES)
    )


def forbidden_label_outcome_fields(feature_names: Iterable[str]) -> list[str]:
    """Return the unique forbidden names present in ``feature_names``."""
    return sorted(
        {str(name) for name in feature_names if is_forbidden_label_outcome_field(str(name))},
        key=str.casefold,
    )


def filter_forbidden_label_outcome_fields(feature_names: Iterable[str]) -> list[str]:
    """Remove label/outcome fields while preserving feature order."""
    return [
        name
        for name in feature_names
        if not is_forbidden_label_outcome_field(str(name))
    ]


def validate_feature_names_are_label_free(
    feature_names: Iterable[str],
    *,
    context: str = "feature selection",
) -> None:
    """Fail closed if a feature boundary still contains any outcome field."""
    forbidden = forbidden_label_outcome_fields(feature_names)
    if forbidden:
        raise ForbiddenLabelOutcomeFeatureError(
            f"{context} contains forbidden label/outcome field(s): {', '.join(forbidden)}"
        )
