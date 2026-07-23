from types import SimpleNamespace

import pytest

from weather.backtesting.source_ablation_contract import (
    ALL_VARIANTS,
    GROUP_VARIANTS,
    SourceAblationContractError,
    ablate_variant_sources,
    exact_requested_variants,
    runtime_source_data,
    variant_has_support,
    variant_names_for_spec,
)
from weather.model.source_plan import planned_live_source_names


class _Model:
    @staticmethod
    def source_data(sources, name):
        item = sources.get(name) or {}
        if item.get("ok") is not True:
            return {}
        return item.get("data") or {}

    @staticmethod
    def row_temp_native(data):
        for key in ("temp_native", "temp_c"):
            if data.get(key) is not None:
                return float(data[key])
        return None

    @staticmethod
    def row_max_since_7am_native(data):
        for key in ("max_since_7am_native", "max_since_7am_c"):
            if data.get(key) is not None:
                return float(data[key])
        return None


def _item(data, **metadata):
    return {"ok": True, "data": data, **metadata}


def test_dynamic_source_plan_includes_free_adjuncts_and_nbm_for_us_market():
    spec = SimpleNamespace(
        sources=("wu_history", "open_meteo", "nws_grid"),
        wu_history_id="KXYZ:9:US",
    )
    plan = planned_live_source_names(spec)
    assert plan == (
        "wu_history",
        "open_meteo",
        "nws_grid",
        "open_meteo_air_quality",
        "open_meteo_global_models",
        "nbm_probabilistic_tmax",
    )
    selected = variant_names_for_spec(
        spec,
        (
            "open_meteo_air_quality",
            "open_meteo_global_models",
            "nbm_probabilistic_tmax",
        ),
    )
    assert tuple(selected) == (
        "open_meteo_air_quality",
        "open_meteo_global_models",
        "nbm_probabilistic_tmax",
    )


def test_dynamic_source_plan_does_not_add_us_nbm_to_canadian_market():
    spec = SimpleNamespace(sources=("open_meteo",), wu_history_id="CYYZ:9:CA")
    assert planned_live_source_names(spec) == (
        "open_meteo",
        "open_meteo_air_quality",
        "open_meteo_global_models",
    )


def test_exact_family_has_17_singles_5_groups_and_six_member_open_meteo_group():
    assert len(ALL_VARIANTS) == 22
    assert tuple(ALL_VARIANTS[-5:]) == tuple(GROUP_VARIANTS)
    assert GROUP_VARIANTS["open_meteo_family"] == (
        "open_meteo",
        "open_meteo_air_quality",
        "open_meteo_global_models",
        "open_meteo_multimodel",
        "global_ensemble",
        "eccc_gem",
    )
    assert exact_requested_variants(ALL_VARIANTS) == ALL_VARIANTS
    with pytest.raises(SourceAblationContractError, match="exact ordered"):
        exact_requested_variants(reversed(ALL_VARIANTS))


def test_failed_or_target_date_rejected_source_is_not_support():
    model = _Model()
    failed = {"metar": {"ok": False, "data": {"temp_c": 20}}}
    wrong_date = {
        "metar": _item({"temp_c": 20, "target_date_match": False})
    }
    assert not variant_has_support(model, failed, "metar")
    assert not variant_has_support(model, wrong_date, "metar")


def test_post_filter_rejection_applies_to_history_swob_and_group_fallback():
    model = _Model()
    sources = {
        "wu_history": _item({"rows": [], "target_date_match": False}),
        "eccc_swob": _item({"rows": [], "target_date_match": False}),
        "eccc_citypage": _item({"forecast_high_c": 24.0}),
    }

    assert runtime_source_data(model, sources, "wu_history") == {}
    assert runtime_source_data(model, sources, "eccc_swob") == {}
    assert not variant_has_support(model, sources, "wu_history")
    assert not variant_has_support(model, sources, "eccc_swob")
    assert variant_has_support(model, sources, "toronto_official")


def test_station_origin_is_support_and_cascades_when_upstream_is_removed():
    model = _Model()
    sources = {
        "metar": _item({"temp_c": 21}),
        "eccc_swob": _item({"temp_c": 20}),
        "station_observations": _item(
            {
                "temp_native": 21,
                "source": "metar",
                "station_observation_source": "metar",
            },
            fallback_source="metar",
        ),
    }
    assert variant_has_support(model, sources, "metar")
    ablated = ablate_variant_sources(model, sources, "metar")
    assert ablated["metar"]["ok"] is False
    assert ablated["station_observations"]["ok"] is False
    assert ablated["eccc_swob"] is sources["eccc_swob"]


def test_conflicting_station_origins_and_unknown_captured_keys_fail_closed():
    model = _Model()
    conflicting = {
        "station_observations": _item(
            {
                "temp_native": 21,
                "source": "metar",
                "station_observation_source": "eccc_swob",
            },
            fallback_source="metar",
        )
    }
    with pytest.raises(SourceAblationContractError, match="conflicting"):
        variant_has_support(model, conflicting, "metar")
    with pytest.raises(SourceAblationContractError, match="unclassified"):
        variant_has_support(model, {"mystery": _item({"temp_c": 1})}, "metar")
