"""Exact per-model training column allowlists for the legacy feature trainer.

A retrain that must change only the fit dates (not the feature set) pins each
market's served column list: the ``feature_names`` of the bundles that serve
today. This module resolves such a list, validates that serving can rebuild
every column, and reports any column that the registry training policy would
otherwise exclude. It never edits that policy: an allowlist that keeps a
policy-excluded column is recorded as an explicit override, not dropped.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from weather.artifacts import resolve_artifact_path
from weather.calibration.feature_training_policy import training_feature_exclusions
from weather.market.market_registry import MarketSpec, spec_for_id
from weather.model.feature_safety import validate_feature_names_are_label_free
from weather.model.feature_store import FEATURE_COLUMNS

SERVED_ALLOWLIST_PREFIX = "served:"
WIND_PREFIX = "wind_"
CLOUD_PREFIX = "cloud_"
GROUP_SOURCE_COLUMNS = frozenset({"wind_group", "cloud_group"})


class ColumnAllowlistError(ValueError):
    """The requested training column allowlist cannot be honoured exactly."""


def _cutoff_bundles(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(key): value
        for key, value in payload.items()
        if str(key).isdigit() and isinstance(value, Mapping)
    }


def bundle_feature_names(payload: Mapping[str, Any], *, label: str = "bundle") -> list[str]:
    """Return the single ``feature_names`` list shared by every cutoff bundle.

    Fails closed when there are no cutoff bundles, a bundle has no list, or the
    cutoff bundles disagree (a per-cutoff list cannot be one allowlist).
    """

    bundles = _cutoff_bundles(payload)
    if not bundles:
        raise ColumnAllowlistError(f"{label}: no cutoff-hour bundles")
    lists: dict[tuple[str, ...], list[str]] = {}
    for hour in sorted(bundles, key=int):
        names = bundles[hour].get("feature_names")
        if not isinstance(names, Sequence) or isinstance(names, str) or not names:
            raise ColumnAllowlistError(f"{label}: cutoff {hour} has no feature_names")
        lists.setdefault(tuple(str(name) for name in names), []).append(hour)
    if len(lists) != 1:
        detail = "; ".join(
            f"{len(names)} columns at cutoffs {','.join(hours)}"
            for names, hours in lists.items()
        )
        raise ColumnAllowlistError(f"{label}: cutoff bundles disagree ({detail})")
    return list(next(iter(lists)))


def served_feature_names(
    market_spec: MarketSpec,
    *,
    hgb_path: str | Path | None = None,
    coefs_path: str | Path | None = None,
) -> list[str]:
    """Return a market's served column list from its HGB pickle and LR coefs.

    Both artifacts must exist and carry the identical list in the identical
    order; any disagreement fails closed rather than picking one.
    """

    suffix = market_spec.artifact_suffix
    hgb = Path(hgb_path) if hgb_path else resolve_artifact_path(f"feature_model_hgb{suffix}.pkl")
    coefs = Path(coefs_path) if coefs_path else resolve_artifact_path(
        f"feature_model_coefs{suffix}.json"
    )
    for path in (hgb, coefs):
        if not path.is_file():
            raise ColumnAllowlistError(f"served artifact is missing: {path}")
    with hgb.open("rb") as handle:
        head = handle.read(64)
        if head.startswith(b"version https://git-lfs"):
            raise ColumnAllowlistError(f"served artifact is an LFS pointer: {hgb}")
        handle.seek(0)
        hgb_payload = pickle.load(handle)
    with coefs.open("r", encoding="utf-8") as handle:
        coefs_payload = json.load(handle)
    hgb_names = bundle_feature_names(hgb_payload, label=str(hgb))
    coef_names = bundle_feature_names(coefs_payload, label=str(coefs))
    if hgb_names != coef_names:
        raise ColumnAllowlistError(
            f"served HGB and LR coefs disagree for {market_spec.id}: "
            f"{len(hgb_names)} vs {len(coef_names)} columns"
        )
    return hgb_names


def load_column_allowlist(value: str, *, market_spec: MarketSpec) -> tuple[list[str], str]:
    """Resolve ``served:<market>`` or a JSON-list file into ``(columns, source)``.

    ``served:<market>`` must name the market being trained: a list served for a
    different market is never silently transplanted.
    """

    text = str(value or "").strip()
    if not text:
        raise ColumnAllowlistError("empty --column-allowlist")
    if text.startswith(SERVED_ALLOWLIST_PREFIX):
        market_id = text[len(SERVED_ALLOWLIST_PREFIX):]
        served_spec = spec_for_id(market_id)
        if served_spec.id != market_spec.id:
            raise ColumnAllowlistError(
                f"{text} names a different market than the one being trained ({market_spec.id})"
            )
        return served_feature_names(served_spec), text
    path = Path(text)
    if not path.is_file():
        raise ColumnAllowlistError(f"column allowlist file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, Mapping):
        payload = payload.get("feature_names")
    if not isinstance(payload, list) or not all(isinstance(name, str) for name in payload):
        raise ColumnAllowlistError(
            f"{path}: expected a JSON list of column names or an object with 'feature_names'"
        )
    return list(payload), str(path)


def column_allowlist_plan(
    allowlist: Sequence[str],
    *,
    market_spec: MarketSpec,
    source: str,
    known_wind_groups: Sequence[str],
    known_cloud_groups: Sequence[str],
) -> dict[str, Any]:
    """Validate an allowlist against the serving contract and describe it.

    The returned plan keeps the allowlist order exactly. Numeric columns must
    form one leading block followed by the one-hot block, because the LR serving
    path slices the numeric block by the trained scaler width.
    """

    columns = [str(name) for name in allowlist]
    if not columns:
        raise ColumnAllowlistError("column allowlist is empty")
    duplicates = sorted({name for name in columns if columns.count(name) > 1})
    if duplicates:
        raise ColumnAllowlistError(f"column allowlist repeats columns: {duplicates}")
    validate_feature_names_are_label_free(columns, context="column allowlist")
    known_wind = {str(group) for group in known_wind_groups}
    known_cloud = {str(group) for group in known_cloud_groups}
    servable_numeric = {name for name in FEATURE_COLUMNS if name not in GROUP_SOURCE_COLUMNS}
    numeric: list[str] = []
    wind_groups: list[str] = []
    cloud_groups: list[str] = []
    unknown: list[str] = []
    for name in columns:
        if name in servable_numeric:
            if wind_groups or cloud_groups:
                raise ColumnAllowlistError(
                    f"numeric column {name!r} follows the one-hot block; "
                    "numeric columns must lead"
                )
            numeric.append(name)
        elif name.startswith(WIND_PREFIX) and name[len(WIND_PREFIX):] in known_wind:
            wind_groups.append(name[len(WIND_PREFIX):])
        elif name.startswith(CLOUD_PREFIX) and name[len(CLOUD_PREFIX):] in known_cloud:
            cloud_groups.append(name[len(CLOUD_PREFIX):])
        else:
            unknown.append(name)
    if unknown:
        raise ColumnAllowlistError(
            f"column allowlist names columns serving cannot build: {unknown}"
        )
    excluded = set(training_feature_exclusions(market_spec))
    canonical = json.dumps(columns, separators=(",", ":"))
    return {
        "source": source,
        "feature_names": columns,
        "numeric_feature_names": numeric,
        "all_wind_groups": wind_groups,
        "all_cloud_groups": cloud_groups,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "training_policy_exclusions_overridden": [
            name for name in columns if name in excluded
        ],
    }


def resolve_column_allowlist(
    value: str,
    *,
    market_spec: MarketSpec,
    known_wind_groups: Sequence[str],
    known_cloud_groups: Sequence[str],
) -> dict[str, Any]:
    columns, source = load_column_allowlist(value, market_spec=market_spec)
    return column_allowlist_plan(
        columns,
        market_spec=market_spec,
        source=source,
        known_wind_groups=known_wind_groups,
        known_cloud_groups=known_cloud_groups,
    )


__all__ = [
    "ColumnAllowlistError",
    "SERVED_ALLOWLIST_PREFIX",
    "bundle_feature_names",
    "column_allowlist_plan",
    "load_column_allowlist",
    "resolve_column_allowlist",
    "served_feature_names",
]
