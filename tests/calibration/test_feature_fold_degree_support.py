"""Invented degree distributions for the ordinary per-market training diagnostics."""

from datetime import date
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from weather.calibration import feature_model as trainer
from weather.calibration.feature_probability_calibration import fit_temperature_blend_grid


@pytest.mark.parametrize("first", [-2, 70])
def test_inner_block_has_only_its_own_observed_degrees(monkeypatch, first):
    class UniformClassifier:
        def fit(self, matrix, labels):
            self.classes_ = np.unique(labels)

        def predict_proba(self, matrix):
            return np.full((len(matrix), len(self.classes_)), 1 / len(self.classes_))

    monkeypatch.setattr(trainer, "make_feature_hgb", UniformClassifier)
    # The last record lies outside the outer fold; the penultimate year has a unique degree.
    years = [2018, 2018, 2019, 2019, 2020, 2020, 2021]
    labels = pd.Series([first, first + 1, first, first + 1, first + 2, first + 1, first + 3])
    records = [
        {"target_date": date(year, 1, 1 + index % 2), "final_bucket": int(labels[index])}
        for index, year in enumerate(years)
    ]
    frame = pd.DataFrame({"reading": np.arange(len(records))})
    predictions = trainer.inner_hgb_calibration_rows(
        frame, labels, records, None, ["reading"], 1, tuple(range(6))
    )
    assert len(predictions) == 6
    assert all(first + 3 not in prior for prior, _, _ in predictions)
    prior, raw, _ = next(entry for entry in predictions if entry[2] == first + 2)
    assert set(prior) == set(raw) == {first, first + 1}
    assert prior == pytest.approx({first: 0.5, first + 1: 0.5})


def test_conditional_prior_can_use_all_training_classes_or_an_independent_declared_domain():
    full_fold = trainer.smoothed_dist([0, 0, 1])
    subset = trainer.smoothed_dist([0, 0], tuple(full_fold))
    assert set(subset) == {0, 1}
    assert subset[1] == pytest.approx(0.1 / 2.2)
    declared = trainer.smoothed_dist([0, 1], support=(0, 1, 2))
    assert declared[2] == pytest.approx(0.1 / 2.3)


def test_absent_winner_incurs_the_same_multiclass_brier_as_an_explicit_zero():
    assert trainer.brier_score({0: 0.5, 1: 0.5}, 2) == 1.5
    assert trainer.brier_score({0: 0.5, 1: 0.5, 2: 0.0}, 2) == 1.5
    assert trainer.brier_score({0: 0.5, 1: 0.5}, 1) == 0.5


def test_support_leak_can_reverse_the_fitted_weight_on_the_registered_grid():
    other_fold = ({0: 0.9, 1: 0.1}, {0: 0.1, 1: 0.9}, 1)
    raw = {0: 0.5, 1: 0.5}
    leaked = trainer.smoothed_dist([0, 1], support=(0, 1, 2))
    honest = trainer.smoothed_dist([0, 1])

    def fitted(prior):
        return fit_temperature_blend_grid([(prior, raw, 2), other_fold], temperatures=(1.0,))

    assert fitted(leaked)["blend_weight"] == 0.50
    assert fitted(honest)["blend_weight"] == 0.97
    for weight in (0.50, 0.97):
        assert trainer.log_loss(trainer.blend(honest, raw, weight), 2) == pytest.approx(-math.log(1e-15))


def test_item27_entry_sends_each_fold_to_learn_its_own_support(monkeypatch):
    class ReachedEvaluator(Exception):
        pass

    spec = SimpleNamespace(id="invented", artifact_suffix="")
    model = SimpleNamespace(
        spec=spec, historical_target_cache=lambda: {"daily": {}, "by_date": {}}
    )
    monkeypatch.setattr(trainer, "TorontoHighTempModel", lambda market_id: model)
    for name in ("daily_path_for", "long_path_for", "load_forecast_daily", "load_forecast_profiles",
                 "load_marine_water_contrast_features", "load_reanalysis_synoptic_features"):
        monkeypatch.setattr(trainer, name, lambda *args, **kwargs: None)
    raw = {"invented": []}
    monkeypatch.setattr(trainer, "build_feature_records_for_model", lambda *args, **kwargs: raw)

    def evaluate(raw_data, winds, clouds, bucket_space, *, market_spec, n_splits):
        assert raw_data is raw and bucket_space is None and market_spec is spec and n_splits == 3
        raise ReachedEvaluator

    monkeypatch.setattr(trainer, "evaluate_feature_family_segments", evaluate)
    with pytest.raises(ReachedEvaluator):
        trainer.main_item27_feature_value_report(market_id="invented", n_splits=3)
