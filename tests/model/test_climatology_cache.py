import csv
from types import SimpleNamespace

from weather.model.toronto_model import TorontoHighTempModel


def model_with_data_root(tmp_path, target_date):
    model = TorontoHighTempModel(target_date=target_date)
    model.spec = SimpleNamespace(
        id="toronto",
        data_root=tmp_path / str(target_date),
        c_to_native=lambda value: value,
    )
    return model


def model_with_native_climatology(tmp_path, market_id, buckets):
    model = TorontoHighTempModel(market_id=market_id, target_date="2026-06-21")
    c_to_native = model.spec.c_to_native
    model.spec = SimpleNamespace(
        id=market_id,
        data_root=tmp_path / market_id,
        c_to_native=c_to_native,
    )
    summary_path = model.spec.data_root / "daily" / "daily_summary.csv"
    summary_path.parent.mkdir(parents=True)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp_native",
                "max_temp_bucket_native",
            ),
        )
        writer.writeheader()
        for index, year in enumerate(range(1990, 2026)):
            bucket = buckets[index % len(buckets)]
            writer.writerow({
                "schema_version": "wu_daily_native_v2",
                "local_date": f"{year}-06-21",
                "temperature_unit": "F",
                "row_count": 24,
                "max_temp_native": bucket,
                "max_temp_bucket_native": bucket,
            })
    return model


def test_historical_target_cache_is_bounded_lru(tmp_path):
    old_max_entries = TorontoHighTempModel._historical_target_cache_max_entries
    try:
        TorontoHighTempModel.clear_historical_cache()
        TorontoHighTempModel._historical_target_cache_max_entries = 2

        first = model_with_data_root(tmp_path, "2026-06-01").historical_target_cache()
        model_with_data_root(tmp_path, "2026-06-02").historical_target_cache()
        assert model_with_data_root(tmp_path, "2026-06-01").historical_target_cache() is first
        model_with_data_root(tmp_path, "2026-06-03").historical_target_cache()

        keys = list(TorontoHighTempModel._historical_target_cache)
        assert keys == ["toronto:2026-06-01", "toronto:2026-06-03"]
    finally:
        TorontoHighTempModel._historical_target_cache_max_entries = old_max_entries
        TorontoHighTempModel.clear_historical_cache()


def _probability(prior, predicate):
    return sum(probability for bucket, probability in prior.items() if predicate(bucket))


def test_missing_summary_uses_wide_uniform_fallback(tmp_path):
    model = model_with_data_root(tmp_path, "2026-06-21")

    assert model.climatology_fallback_prior() == model.wide_uniform_climatology_prior()


def test_toronto_fallback_prior_keeps_legacy_uniform():
    model = TorontoHighTempModel(target_date="2026-06-21")
    prior = model.climatology_fallback_prior()

    assert prior == model.wide_uniform_climatology_prior()
    assert set(prior) == set(range(8, 33))
    assert {round(probability, 12) for probability in prior.values()} == {0.04}


def test_miami_fallback_prior_uses_hot_native_climatology(tmp_path):
    model = model_with_native_climatology(tmp_path, "miami", [88, 89, 89, 90])
    prior = model.climatology_fallback_prior()
    legacy_uniform = model.wide_uniform_climatology_prior()

    assert prior != legacy_uniform
    assert abs(sum(prior.values()) - 1.0) < 1e-9
    assert _probability(prior, lambda bucket: bucket < 75) == 0.0
    assert _probability(prior, lambda bucket: 85 <= bucket <= 93) > 0.80
    assert 87 <= max(prior, key=prior.get) <= 92
    assert max(prior.values()) > max(legacy_uniform.values()) * 5


def test_seattle_fallback_prior_uses_cooler_native_climatology(tmp_path):
    model = model_with_native_climatology(tmp_path, "seattle", [67, 68, 68, 69, 70])
    prior = model.climatology_fallback_prior()
    legacy_uniform = model.wide_uniform_climatology_prior()

    assert prior != legacy_uniform
    assert abs(sum(prior.values()) - 1.0) < 1e-9
    assert 60 <= max(prior, key=prior.get) <= 70
    assert _probability(prior, lambda bucket: 66 <= bucket <= 75) > 0.40
    assert _probability(prior, lambda bucket: bucket < 65) < _probability(
        legacy_uniform,
        lambda bucket: bucket < 65,
    )
    assert max(prior.values()) > max(legacy_uniform.values()) * 2
