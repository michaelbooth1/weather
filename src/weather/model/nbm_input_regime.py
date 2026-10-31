"""NBM parser input regime of a trained artifact (EF 10k/10l).

Parser version 1 read tomorrow morning's minimum as today's maximum for
12Z/13Z/19Z bulletins; version 2 reads only the target day's maximum. Their
values are different inputs, so an artifact consumes ``nbm_prob_tmax_*``
values only from the parser version it was trained on.

An artifact that selects any NBM column and declares no
``nbm_prob_tmax_parser_version`` was trained before the repair: version 1.
A row whose NBM payload recorded no parser version is a version-1 row (that is
how every pre-repair capture replays). On a mismatch the artifact's NBM inputs
are masked to missing, the state the artifact already saw whenever guidance was
absent or floor-dropped, and the caller records that it did so. Nothing here
rewrites a captured payload or feature row it does not own.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, MutableMapping

from weather.sources.nbm_probabilistic_tmax import (
    NBM_NBP_PARSER_V1,
    NBM_NBP_PARSER_V2,
    NBM_PROB_TMAX_FEATURE_COLUMNS,
    nbp_parser_version_number,
)

ARTIFACT_NBM_PARSER_VERSION_KEY = "nbm_prob_tmax_parser_version"
ROW_NBM_PARSER_VERSION_COLUMN = "nbm_prob_tmax_parser_version"
LEGACY_NBM_PARSER_VERSION = 1
NBM_INPUT_COLUMNS = frozenset(NBM_PROB_TMAX_FEATURE_COLUMNS)


def nbm_parser_label(version: int | None) -> str | None:
    """Return the recorded parser label for a version number (None stays None)."""
    if version is None:
        return None
    return {1: NBM_NBP_PARSER_V1, 2: NBM_NBP_PARSER_V2}[nbp_parser_version_number(version)]


def artifact_feature_names(artifact: Mapping[str, Any] | None) -> set[str]:
    names: set[str] = set()
    if not isinstance(artifact, Mapping):
        return names
    names.update(str(name) for name in artifact.get("feature_names") or [])
    models = artifact.get("models")
    bundles = models.values() if isinstance(models, Mapping) else models or []
    for bundle in bundles:
        if isinstance(bundle, Mapping):
            names.update(str(name) for name in bundle.get("feature_names") or [])
    return names


def artifact_nbm_parser_version(artifact: Mapping[str, Any] | None) -> int | None:
    """Return the NBM parser regime an artifact was trained on, or None.

    None means the artifact selects no NBM input and needs no guard. An
    unknown declared version raises ``ValueError`` (fail closed).
    """
    if not NBM_INPUT_COLUMNS & artifact_feature_names(artifact):
        return None
    declared = (artifact or {}).get(ARTIFACT_NBM_PARSER_VERSION_KEY)
    if declared in (None, ""):
        return LEGACY_NBM_PARSER_VERSION
    return nbp_parser_version_number(declared)


def row_nbm_parser_version(row: Mapping[str, Any]) -> int:
    value = row.get(ROW_NBM_PARSER_VERSION_COLUMN)
    if value is None or value == "":
        return LEGACY_NBM_PARSER_VERSION
    number = float(value)
    if math.isnan(number):
        return LEGACY_NBM_PARSER_VERSION
    if not number.is_integer():
        raise ValueError(f"unsupported NBP parser version: {value!r}")
    return nbp_parser_version_number(int(number))


def quarantine_nbm_inputs(row: MutableMapping[str, Any], trained_version: int | None) -> dict[str, Any] | None:
    """Mask a row's NBM inputs in place when its parser regime differs.

    Returns None when the artifact needs no guard, otherwise a small record of
    the decision: trained and row versions, whether the row was masked, and how
    many non-missing values were removed.
    """
    if trained_version is None:
        return None
    observed = row_nbm_parser_version(row)
    masked_values = 0
    if observed != trained_version:
        for column in NBM_PROB_TMAX_FEATURE_COLUMNS:
            value = row.get(column)
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                masked_values += 1
            row[column] = None
    return {
        "trained_parser_version": int(trained_version),
        "row_parser_version": int(observed),
        "masked": observed != trained_version,
        "masked_values": masked_values,
    }
