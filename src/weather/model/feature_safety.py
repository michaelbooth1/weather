"""Shared fail-closed policy for supervised and retrospective input fields.

The small name-only helpers remain the feature-matrix boundary used by model
training.  The recursive helpers additionally cover release contracts where a
forbidden alias can be hidden inside a feature-family or input-manifest value.
Evaluation-only labels are intentionally excluded by callers rather than being
reclassified as model inputs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


# Exact names cover legacy settlement aliases as well as derived research
# targets. Prefix/suffix rules cover schema additions without requiring every
# future label column to be added before it is rejected.
FORBIDDEN_LABEL_OUTCOME_FIELDS = frozenset(
    {
        "actual_high",
        "casebook",
        "final_high",
        "final_bucket",
        "high",
        "label",
        "label_gate",
        "max_temp",
        "observed_high",
        "outcome",
        "post_event",
        "postevent",
        "retrospective_casebook",
        "rounded_high",
        "settled_high",
        "settlement",
        "settlement_distance",
        "settlement_distance_bucket",
        "target",
        "target_market_z",
        "truth",
        "winner",
        "y",
    }
)
FORBIDDEN_LABEL_OUTCOME_PREFIXES = (
    "label_",
    "outcome_",
    "post_event",
    "postevent_",
    "retrospective_",
    "settlement_",
    "target_",
    "truth_",
    "winner_",
    "winning_",
)
FORBIDDEN_LABEL_OUTCOME_SUFFIXES = (
    "_casebook",
    "_label",
    "_label_gate",
    "_outcome",
    "_post_event",
    "_settlement_distance",
    "_winner",
)

# Phrase matching is deliberately token based.  It catches aliases such as
# ``settlement-distance-bucket`` and ``winner/casebook`` in manifests without
# treating unrelated words containing the same character sequence as labels.
FORBIDDEN_RETROSPECTIVE_TOKEN_PHRASES = (
    ("label", "gate"),
    ("post", "event"),
    ("retrospective", "casebook"),
    ("settlement", "distance"),
)
FORBIDDEN_RETROSPECTIVE_TOKENS = frozenset(
    {
        "casebook",
        "outcome",
        "postevent",
        "target",
        "winner",
        "winning",
    }
)

INPUT_MANIFEST_HINTS = frozenset(
    {
        "feature",
        "features",
        "feature_family",
        "feature_families",
        "feature_hash_inputs",
        "feature_manifest",
        "field",
        "fields",
        "input",
        "inputs",
        "input_columns",
        "model_input_fields",
        "columns",
    }
)


class ForbiddenLabelOutcomeFeatureError(ValueError):
    """Raised when a label or outcome field reaches a feature boundary."""


def _normalized_field_name(name: str) -> str:
    return str(name).strip().casefold()


def _tokens(name: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", _normalized_field_name(name)) if token)


def forbidden_model_input_reason(name: str) -> str | None:
    """Return a stable rejection category for a model-input alias."""

    normalized = _normalized_field_name(name)
    if (
        normalized in FORBIDDEN_LABEL_OUTCOME_FIELDS
        or normalized.startswith(FORBIDDEN_LABEL_OUTCOME_PREFIXES)
        or normalized.endswith(FORBIDDEN_LABEL_OUTCOME_SUFFIXES)
    ):
        return "label_or_outcome_field"
    tokens = _tokens(normalized)
    if any(token in FORBIDDEN_RETROSPECTIVE_TOKENS for token in tokens):
        return "retrospective_or_post_event_field"
    for phrase in FORBIDDEN_RETROSPECTIVE_TOKEN_PHRASES:
        width = len(phrase)
        if any(tokens[offset : offset + width] == phrase for offset in range(len(tokens) - width + 1)):
            return "retrospective_or_post_event_field"
    return None


def is_forbidden_label_outcome_field(name: str) -> bool:
    """Return whether ``name`` is reserved for labels/outcomes, case-insensitively."""
    return forbidden_model_input_reason(name) is not None


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


def _input_hint(value: str) -> bool:
    normalized = _normalized_field_name(value)
    if normalized in INPUT_MANIFEST_HINTS:
        return True
    tokens = set(_tokens(normalized))
    return bool(tokens & {"feature", "features", "input", "inputs", "column", "columns"})


def audit_recursive_model_inputs(
    payloads: Mapping[str, Any],
    *,
    evaluation_only_roots: Iterable[str] = (),
) -> dict[str, Any]:
    """Recursively scan explicit model-input contracts and feature manifests.

    Mapping keys are inspected whenever they occur below an input-bearing
    section.  Scalar values are inspected when their parent identifies a
    feature/input/column/family manifest.  This catches aliases embedded in
    nested feature-family and feature-hash manifests while avoiding prose and
    evaluation-only settlement labels that are not serving inputs.
    """

    excluded = {_normalized_field_name(value) for value in evaluation_only_roots}
    rejections: list[dict[str, str]] = []
    inspected: list[dict[str, str]] = []

    def visit(value: Any, *, source: str, path: tuple[str, ...], input_scope: bool) -> None:
        if path and _normalized_field_name(path[0]) in excluded:
            return
        if isinstance(value, Mapping):
            for raw_key, child in value.items():
                key = str(raw_key)
                child_path = (*path, key)
                child_scope = input_scope or _input_hint(key)
                if child_scope:
                    inspected.append({"source": source, "path": ".".join(child_path), "value": key})
                    reason = forbidden_model_input_reason(key)
                    if reason:
                        rejections.append(
                            {
                                "source": source,
                                "path": ".".join(child_path),
                                "value": key,
                                "reason": reason,
                            }
                        )
                visit(child, source=source, path=child_path, input_scope=child_scope)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, child in enumerate(value):
                visit(child, source=source, path=(*path, str(index)), input_scope=input_scope)
            return
        if input_scope and isinstance(value, str):
            inspected.append({"source": source, "path": ".".join(path), "value": value})
            reason = forbidden_model_input_reason(value)
            if reason:
                rejections.append(
                    {
                        "source": source,
                        "path": ".".join(path),
                        "value": value,
                        "reason": reason,
                    }
                )

    for source, payload in sorted(payloads.items()):
        visit(payload, source=str(source), path=(), input_scope=False)
    unique_rejections = {
        (row["source"], row["path"], row["value"], row["reason"]): row
        for row in rejections
    }
    return {
        "status": "PASS" if not unique_rejections else "BLOCK",
        "inspected_value_count": len(inspected),
        "rejection_count": len(unique_rejections),
        "rejections": [unique_rejections[key] for key in sorted(unique_rejections)],
        "evaluation_only_roots": sorted(excluded),
    }
