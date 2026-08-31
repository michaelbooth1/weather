from types import SimpleNamespace
from unittest.mock import call, patch

from weather.calibration import pooled_feature_assembly as assembly
from weather.calibration.forecast_training_contract import (
    REQUIRED_EXCLUDED_CONSUMERS,
    validate_consumer_dispositions,
)
from weather.model.feature_store import FORECAST_PROFILE_COLUMNS
from weather.sources.forecast_training_corpus import (
    CONSUMER_DISPOSITIONS,
    FREE_PIT_SOURCE_FIELDS,
    PROFILE_FEATURE_SOURCE_FIELDS,
    UNAVAILABLE_PIT_SOURCE_FIELDS,
)


def test_consumer_dispositions_cover_every_forecast_profile_column():
    assert validate_consumer_dispositions(CONSUMER_DISPOSITIONS) is True
    profile = CONSUMER_DISPOSITIONS["pooled_forecast_profiles"]
    included = set(profile["included_feature_columns"])
    excluded = set(profile["excluded_feature_columns"])

    assert included.isdisjoint(excluded)
    assert included | excluded == set(FORECAST_PROFILE_COLUMNS)
    for consumer in REQUIRED_EXCLUDED_CONSUMERS:
        assert CONSUMER_DISPOSITIONS[consumer]["disposition"] == "excluded"
        assert CONSUMER_DISPOSITIONS[consumer]["reason"]


def test_profile_dispositions_never_require_an_unavailable_pit_field():
    included_source_fields = {
        source_field
        for source_fields in PROFILE_FEATURE_SOURCE_FIELDS.values()
        for source_field in source_fields
    }
    assert included_source_fields <= set(FREE_PIT_SOURCE_FIELDS)
    assert included_source_fields.isdisjoint(UNAVAILABLE_PIT_SOURCE_FIELDS)

    profile = CONSUMER_DISPOSITIONS["pooled_forecast_profiles"]
    excluded = profile["excluded_feature_columns"]
    for feature in (
        "forecast_low_cloud_mean",
        "forecast_low_cloud_max",
        "forecast_mid_cloud_mean",
        "forecast_high_cloud_mean",
        "forecast_temperature_925hpa_mean",
        "forecast_temperature_850hpa_mean",
        "forecast_surface_to_925_lapse_proxy",
        "forecast_925_to_850_lapse_proxy",
        "forecast_geopotential_height_500hpa_mean",
        "forecast_visibility_min",
        "forecast_soil_temperature_0cm_mean",
        "forecast_soil_moisture_0_to_1cm_mean",
    ):
        assert "unavailable from the free PIT endpoint" in excluded[feature]


def test_family_dataset_preflights_and_passes_explicit_market_readers():
    specs = [SimpleNamespace(id="alpha"), SimpleNamespace(id="beta")]

    def reader(manifest_path, market_id):
        return SimpleNamespace(manifest_path=manifest_path, market_id=market_id)

    def market_records(spec, **kwargs):
        corpus = kwargs["pit_forecast_corpus"]
        assert corpus.market_id == spec.id
        return [{"market_id": spec.id}]

    with (
        patch.object(assembly, "family_specs", return_value=specs),
        patch.object(
            assembly,
            "preflight_pit_forecast_training_corpus",
            return_value={"status": "PASS"},
        ) as preflight,
        patch.object(assembly, "PITForecastTrainingCorpus", side_effect=reader) as reader_cls,
        patch.object(assembly, "build_market_records", side_effect=market_records),
    ):
        records, counts = assembly.build_family_dataset(
            unit="all",
            cutoff_hours=(8, 12),
            pit_forecast_corpus_manifest="explicit/manifest.json",
        )

    preflight.assert_called_once_with(
        "explicit/manifest.json",
        required_cutoff_hours=(8, 12),
    )
    assert reader_cls.call_args_list == [
        call("explicit/manifest.json", "alpha"),
        call("explicit/manifest.json", "beta"),
    ]
    assert records == [{"market_id": "alpha"}, {"market_id": "beta"}]
    assert counts == {"alpha": 1, "beta": 1}


def test_family_dataset_passes_explicit_honest_rich_hybrid_resolvers():
    specs = [SimpleNamespace(id="alpha"), SimpleNamespace(id="beta")]

    def reader(history_root, spec, *, variant, pit_lead_days):
        return SimpleNamespace(
            history_root=history_root,
            market_id=spec.id,
            variant=variant,
            pit_lead_days=pit_lead_days,
        )

    def market_records(spec, **kwargs):
        resolver = kwargs["forecast_training_resolver"]
        assert resolver.market_id == spec.id
        assert resolver.variant == "hybrid"
        assert kwargs["pit_forecast_corpus"] is None
        return [{"market_id": spec.id}]

    with (
        patch.object(assembly, "family_specs", return_value=specs),
        patch.object(
            assembly,
            "ForecastTrainingVariantResolver",
            side_effect=reader,
        ) as reader_cls,
        patch.object(assembly, "build_market_records", side_effect=market_records),
    ):
        records, counts = assembly.build_family_dataset(
            unit="all",
            forecast_training_variant="hybrid",
            forecast_history_root="explicit/forecast-history",
            pit_lead_days=1,
        )

    assert reader_cls.call_args_list == [
        call(
            "explicit/forecast-history",
            specs[0],
            variant="hybrid",
            pit_lead_days=1,
        ),
        call(
            "explicit/forecast-history",
            specs[1],
            variant="hybrid",
            pit_lead_days=1,
        ),
    ]
    assert records == [{"market_id": "alpha"}, {"market_id": "beta"}]
    assert counts == {"alpha": 1, "beta": 1}
