"""Exact per-model training column allowlists for the legacy feature trainer.

A retrain that must change only the fit dates (not the feature set) pins each
market's served column list: the ``feature_names`` of the bundles that serve
today. This module resolves such a list, validates that serving can rebuild
every column, and records how it relates to the registry training policy.

R0 uses ``r0:<market>`` (owner decisions 2026-10-21 and M6-M8 2026-10-23,
``weather.calibration.r0_scope``): the served list minus the policy exclusions
("Drop pressure") and minus the forecast-consensus columns a single-provider
PIT corpus cannot express (Miami), refused for any market outside the US 11.
Every removed column is recorded with its reason
(``column_differences_from_served``). ``served-policy:<market>`` is the same
without the consensus drop and the scope check; plain ``served:<market>``
keeps the served list exactly and records any kept policy-excluded column as an
override. The policy itself is never edited here.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from weather.artifacts import resolve_artifact_path
from weather.calibration.feature_training_policy import (
    TRAINING_FEATURE_POLICY_ID,
    training_feature_exclusions,
    training_feature_names,
)
from weather.calibration.r0_scope import (
    column_differences,
    r0_single_provider_exclusions,
    require_r0_market,
)
from weather.market.market_registry import MarketSpec, spec_for_id
from weather.model.feature_safety import validate_feature_names_are_label_free
from weather.model.feature_store import FEATURE_COLUMNS

SERVED_ALLOWLIST_PREFIX = "served:"
SERVED_POLICY_ALLOWLIST_PREFIX = "served-policy:"
R0_ALLOWLIST_PREFIX = "r0:"
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


def load_column_allowlist(value: str, *, market_spec: MarketSpec) -> dict[str, Any]:
    """Resolve an allowlist spec into its columns and provenance.

    Modes:

    - ``r0:<market>`` (**the R0 mode**): ``served-policy`` minus the
      single-provider consensus columns (``forecast_source_count``,
      ``forecast_disagreement``; Miami only among the US 11), order kept;
      refused for a market outside R0 (Toronto).
    - ``served-policy:<market>`` (owner 2026-10-21): the served
      list with the registry training-policy exclusions removed, order kept. In
      F markets that drops exactly ``pressure`` and ``pressure_trend_3h``; in the
      C market (Toronto) the policy excludes nothing, so it equals the served list.
    - ``served:<market>``: the served list exactly; any policy-excluded column it
      keeps is reported as an override (not used by R0).
    - a JSON file holding a list, or an object with ``feature_names``.

    A served mode must name the market being trained: a list served for a
    different market is never silently transplanted.
    """

    text = str(value or "").strip()
    if not text:
        raise ColumnAllowlistError("empty --column-allowlist")
    for prefix, mode in (
        (R0_ALLOWLIST_PREFIX, "r0"),
        (SERVED_POLICY_ALLOWLIST_PREFIX, "served-policy"),
        (SERVED_ALLOWLIST_PREFIX, "served"),
    ):
        if not text.startswith(prefix):
            continue
        served_spec = spec_for_id(text[len(prefix):])
        if served_spec.id != market_spec.id:
            raise ColumnAllowlistError(
                f"{text} names a different market than the one being trained ({market_spec.id})"
            )
        if mode == "r0":
            try:
                require_r0_market(served_spec.id)
            except ValueError as exc:
                raise ColumnAllowlistError(str(exc)) from exc
        served = served_feature_names(served_spec)
        applied: list[str] = []
        single_provider: list[str] = []
        columns = list(served)
        if mode in ("served-policy", "r0"):
            columns = training_feature_names(served, market_spec=market_spec)
            applied = [name for name in served if name not in columns]
        if mode == "r0":
            single_provider = r0_single_provider_exclusions(columns)
            columns = [name for name in columns if name not in single_provider]
        return {
            "columns": columns,
            "source": text,
            "mode": mode,
            "served_feature_names": served,
            "policy_exclusions_applied": applied,
            "single_provider_exclusions_applied": single_provider,
        }
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
    return {
        "columns": list(payload),
        "source": str(path),
        "mode": "file",
        "served_feature_names": None,
        "policy_exclusions_applied": [],
        "single_provider_exclusions_applied": [],
    }


def column_allowlist_plan(
    allowlist: Sequence[str],
    *,
    market_spec: MarketSpec,
    source: str,
    known_wind_groups: Sequence[str],
    known_cloud_groups: Sequence[str],
    mode: str = "file",
    served_feature_names: Sequence[str] | None = None,
    policy_exclusions_applied: Sequence[str] = (),
    single_provider_exclusions_applied: Sequence[str] = (),
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
    served = None if served_feature_names is None else [str(name) for name in served_feature_names]
    differences = None
    if served is not None:
        try:
            differences = column_differences(
                served,
                columns,
                policy_exclusions=policy_exclusions_applied,
                single_provider_exclusions=single_provider_exclusions_applied,
            )
        except ValueError as exc:
            raise ColumnAllowlistError(str(exc)) from exc
        kept = set(columns)
        if [name for name in served if name in kept] != columns:
            raise ColumnAllowlistError("the allowlist reorders the served columns")
    return {
        "source": source,
        "mode": mode,
        "feature_names": columns,
        "numeric_feature_names": numeric,
        "all_wind_groups": wind_groups,
        "all_cloud_groups": cloud_groups,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "training_feature_policy_id": TRAINING_FEATURE_POLICY_ID,
        "served_feature_names": served,
        "policy_exclusions_applied": [str(name) for name in policy_exclusions_applied],
        "single_provider_exclusions_applied": [
            str(name) for name in single_provider_exclusions_applied
        ],
        "column_differences_from_served": differences,
        "differs_from_served": None if served is None else served != columns,
        "training_policy_exclusions_overridden": [
            name for name in columns if name in excluded
        ],
    }


# Keys copied into the trained artifacts' ``training_column_allowlist`` record.
ALLOWLIST_RECORD_KEYS = (
    "source",
    "mode",
    "sha256",
    "feature_names",
    "training_feature_policy_id",
    "served_feature_names",
    "policy_exclusions_applied",
    "single_provider_exclusions_applied",
    "column_differences_from_served",
    "differs_from_served",
    "training_policy_exclusions_overridden",
)


def allowlist_record(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {key: plan[key] for key in ALLOWLIST_RECORD_KEYS}


def resolve_column_allowlist(
    value: str,
    *,
    market_spec: MarketSpec,
    known_wind_groups: Sequence[str],
    known_cloud_groups: Sequence[str],
) -> dict[str, Any]:
    loaded = load_column_allowlist(value, market_spec=market_spec)
    return column_allowlist_plan(
        loaded["columns"],
        market_spec=market_spec,
        source=loaded["source"],
        known_wind_groups=known_wind_groups,
        known_cloud_groups=known_cloud_groups,
        mode=loaded["mode"],
        served_feature_names=loaded["served_feature_names"],
        policy_exclusions_applied=loaded["policy_exclusions_applied"],
        single_provider_exclusions_applied=loaded["single_provider_exclusions_applied"],
    )


__all__ = [
    "ALLOWLIST_RECORD_KEYS",
    "ColumnAllowlistError",
    "R0_ALLOWLIST_PREFIX",
    "SERVED_ALLOWLIST_PREFIX",
    "SERVED_POLICY_ALLOWLIST_PREFIX",
    "allowlist_record",
    "bundle_feature_names",
    "column_allowlist_plan",
    "load_column_allowlist",
    "resolve_column_allowlist",
    "served_feature_names",
]
