"""Fail-closed treatment and support contract for source-ablation research."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from weather.model.source_plan import planned_live_source_names


SINGLE_SOURCE_VARIANTS = (
    "wu_history",
    "open_meteo",
    "weather_forecast",
    "eccc_citypage",
    "eccc_swob",
    "eccc_gem",
    "metar",
    "wu_current",
    "nws_hourly",
    "nws_grid",
    "nbm_probabilistic_tmax",
    "open_meteo_multimodel",
    "open_meteo_global_models",
    "global_ensemble",
    "marine_context",
    "mrms_precip",
    "open_meteo_air_quality",
)
GROUP_VARIANTS = {
    "all_forecasts": (
        "open_meteo",
        "weather_forecast",
        "eccc_citypage",
    ),
    "official_us_guidance": (
        "nws_hourly",
        "nws_grid",
        "nbm_probabilistic_tmax",
    ),
    "multi_model_guidance": (
        "open_meteo_multimodel",
        "open_meteo_global_models",
        "global_ensemble",
    ),
    "open_meteo_family": (
        "open_meteo",
        "open_meteo_air_quality",
        "open_meteo_global_models",
        "open_meteo_multimodel",
        "global_ensemble",
        "eccc_gem",
    ),
    "toronto_official": (
        "eccc_citypage",
        "eccc_swob",
        "eccc_gem",
    ),
}
VARIANT_MEMBERS = {
    **{name: (name,) for name in SINGLE_SOURCE_VARIANTS},
    **GROUP_VARIANTS,
}
ALL_VARIANTS = tuple(VARIANT_MEMBERS)
EXCLUDED_CAPTURED_SOURCE_KEYS = frozenset(
    {"local_history", "station_observations"}
)
KNOWN_CAPTURED_SOURCE_KEYS = frozenset(SINGLE_SOURCE_VARIANTS) | EXCLUDED_CAPTURED_SOURCE_KEYS
ALLOWED_STATION_ORIGINS = frozenset({"metar", "eccc_swob"})


class SourceAblationContractError(ValueError):
    """Raised when captured support cannot satisfy the sealed contract."""


def members_for_variant(name: str) -> tuple[str, ...]:
    try:
        return VARIANT_MEMBERS[str(name)]
    except KeyError as exc:
        raise SourceAblationContractError(f"unknown source-ablation variant: {name}") from exc


def exact_requested_variants(values: Iterable[str]) -> tuple[str, ...]:
    requested = tuple(str(value) for value in values)
    if requested != ALL_VARIANTS:
        raise SourceAblationContractError(
            "canonical source-ablation run requires the exact ordered 22-variant family"
        )
    return requested


def variant_names_for_spec(spec, requested: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Return requested variants intersecting the canonical dynamic source plan."""

    planned = set(planned_live_source_names(spec))
    output: dict[str, tuple[str, ...]] = {}
    for name in requested:
        members = members_for_variant(name)
        if any(member in planned for member in members):
            output[str(name)] = members
    return output


def assert_known_captured_source_keys(sources: Mapping[str, object]) -> None:
    unknown = sorted(str(name) for name in sources if str(name) not in KNOWN_CAPTURED_SOURCE_KEYS)
    if unknown:
        raise SourceAblationContractError(
            "unclassified captured source keys: " + ", ".join(unknown)
        )


def runtime_source_data(model, sources: Mapping[str, object], name: str) -> dict:
    data = model.source_data(sources, name)
    if (
        not isinstance(data, dict)
        or not data
        or data.get("target_date_match") is False
    ):
        return {}
    return data


def source_is_usable(model, sources: Mapping[str, object], name: str) -> bool:
    item = sources.get(name)
    return bool(
        isinstance(item, Mapping)
        and item.get("ok") is True
        and runtime_source_data(model, sources, name)
    )


def station_observation_origin(model, sources: Mapping[str, object]) -> str | None:
    """Return the unique signal-bearing captured station origin, if present."""

    item = sources.get("station_observations")
    if not source_is_usable(model, sources, "station_observations"):
        return None
    data = runtime_source_data(model, sources, "station_observations")
    if (
        model.row_temp_native(data) is None
        and model.row_max_since_7am_native(data) is None
    ):
        return None
    values = {
        str(value).strip()
        for value in (
            data.get("station_observation_source"),
            data.get("source"),
            item.get("fallback_source") if isinstance(item, Mapping) else None,
        )
        if value is not None and str(value).strip()
    }
    if not values:
        raise SourceAblationContractError(
            "signal-bearing station_observations payload has no upstream origin"
        )
    if len(values) != 1:
        raise SourceAblationContractError(
            "conflicting station_observations origins: " + ", ".join(sorted(values))
        )
    origin = next(iter(values))
    if origin not in ALLOWED_STATION_ORIGINS:
        raise SourceAblationContractError(
            f"unknown station_observations origin: {origin}"
        )
    return origin


def members_have_support(
    model,
    sources: Mapping[str, object],
    members: Iterable[str],
) -> bool:
    members = tuple(str(name) for name in members)
    if any(source_is_usable(model, sources, name) for name in members):
        return True
    return station_observation_origin(model, sources) in members


def variant_has_support(model, sources: Mapping[str, object], variant: str) -> bool:
    assert_known_captured_source_keys(sources)
    return members_have_support(model, sources, members_for_variant(variant))


def ablate_variant_sources(
    model,
    sources: Mapping[str, object],
    variant: str,
) -> dict:
    """Remove treatment members and cascade a captured derived station channel.

    If the captured station channel originated from a removed upstream source,
    it is removed too.  The model may then deterministically derive a station
    channel from another surviving upstream source, matching serving fallback.
    """

    assert_known_captured_source_keys(sources)
    members = members_for_variant(variant)
    origin = station_observation_origin(model, sources)
    output = dict(sources)
    for name in members:
        if name in output:
            output[name] = {"ok": False, "error": "ablated", "data": {}}
    if origin in members and "station_observations" in output:
        output["station_observations"] = {
            "ok": False,
            "error": "ablated_upstream_station_origin",
            "data": {},
            "fallback_source": origin,
        }
    return output
