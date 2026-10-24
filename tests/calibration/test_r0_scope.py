"""R0 scope and column contract (owner M7/M8 2026-10-23; DL 2026-10-21 pressure and base-only rows).

Guards: retrain memo R0.2 M7 (Miami drops the forecast-consensus columns a single-provider PIT corpus
cannot express, and stays in), M8 (R0 = the US 11; Toronto keeps its served model) and the
"Drop pressure" decision: the r0:<market> allowlist removes exactly those columns, keeps the served
order, refuses Toronto, and every removed column is recorded with its reason in both trained
artifacts (served_model_differences), which also passes the release leakage audit.
Fixture artifacts only; nothing reads data/ or LFS bytes.
"""

from __future__ import annotations

import json
import pickle

import pytest

from tests.calibration.test_feature_model_training_inputs import _patch_trainer, corpora  # noqa: F401
from weather.calibration.feature_column_allowlist import (
    ColumnAllowlistError,
    allowlist_record,
    resolve_column_allowlist,
)
from weather.calibration.feature_model import CLOUD_GROUPS, WIND_GROUPS
from weather.calibration.feature_model_training_inputs import TrainingInputError
from weather.calibration.r0_scope import (
    PIT_SINGLE_PROVIDER_EXCLUDED_COLUMNS,
    R0_MARKET_IDS,
    REASON_POLICY,
    REASON_SINGLE_PROVIDER,
    R0ScopeError,
    column_differences,
    require_r0_market,
    served_model_differences,
)
from weather.market.market_registry import MIAMI, NYC, TORONTO
from weather.model.feature_safety import audit_recursive_model_inputs

PRESSURE = ["pressure", "pressure_trend_3h"]
CONSENSUS = ["forecast_source_count", "forecast_disagreement"]
ONE_HOT = [f"wind_{group}" for group in WIND_GROUPS] + [f"cloud_{group}" for group in CLOUD_GROUPS]
# Shape of the served Miami v0.4 list: pressure and both consensus columns inside the numeric block.
MIAMI_STYLE = [
    "high_so_far", "current_temp", "pressure", "pressure_trend_3h", "forecast_high", "forecast_gap",
    "forecast_source_count", "forecast_disagreement", "live_reading_temp",
] + ONE_HOT
# A served list without consensus columns (every other US market).
PLAIN_STYLE = [name for name in MIAMI_STYLE if name not in CONSENSUS]


@pytest.fixture
def served(monkeypatch):
    import weather.calibration.feature_column_allowlist as allowlist_module

    lists = {"miami": MIAMI_STYLE, "toronto": MIAMI_STYLE}

    def fake(spec, **_):
        return list(lists.get(spec.id, PLAIN_STYLE))

    monkeypatch.setattr(allowlist_module, "served_feature_names", fake)
    return lists


def _resolve(value, spec):
    return resolve_column_allowlist(
        value, market_spec=spec, known_wind_groups=WIND_GROUPS, known_cloud_groups=CLOUD_GROUPS,
    )


def test_scope_is_exactly_the_us11():
    assert len(R0_MARKET_IDS) == 11 and "toronto" not in R0_MARKET_IDS
    assert require_r0_market("miami") == "miami"
    with pytest.raises(R0ScopeError, match="outside R0"):
        require_r0_market("toronto")
    assert PIT_SINGLE_PROVIDER_EXCLUDED_COLUMNS == tuple(CONSENSUS)


def test_r0_mode_for_miami_drops_pressure_and_consensus_in_served_order(served):
    plan = _resolve("r0:miami", MIAMI)
    assert plan["mode"] == "r0"
    assert plan["feature_names"] == [n for n in MIAMI_STYLE if n not in PRESSURE + CONSENSUS]
    assert plan["policy_exclusions_applied"] == PRESSURE
    assert plan["single_provider_exclusions_applied"] == CONSENSUS
    assert plan["differs_from_served"] is True
    rows = plan["column_differences_from_served"]
    assert [row["column"] for row in rows] == PRESSURE + CONSENSUS
    assert [row["reason"] for row in rows] == [REASON_POLICY] * 2 + [REASON_SINGLE_PROVIDER] * 2
    assert all(row["decision"] for row in rows)


def test_r0_mode_equals_served_policy_where_no_consensus_is_served(served):
    r0 = _resolve("r0:nyc", NYC)
    policy = _resolve("served-policy:nyc", NYC)
    assert r0["feature_names"] == policy["feature_names"] == [n for n in PLAIN_STYLE if n not in PRESSURE]
    assert r0["single_provider_exclusions_applied"] == []
    assert [row["column"] for row in r0["column_differences_from_served"]] == PRESSURE
    assert policy["column_differences_from_served"] == r0["column_differences_from_served"]
    # served-policy alone never drops consensus columns (Miami keeps them there).
    assert set(CONSENSUS) <= set(_resolve("served-policy:miami", MIAMI)["feature_names"])


def test_r0_mode_refuses_toronto_and_another_market(served):
    with pytest.raises(ColumnAllowlistError, match="outside R0"):
        _resolve("r0:toronto", TORONTO)
    with pytest.raises(ColumnAllowlistError, match="different market"):
        _resolve("r0:miami", NYC)


def test_column_differences_fail_closed():
    with pytest.raises(R0ScopeError, match="no recorded reason"):
        column_differences(["a", "b"], ["a"])
    with pytest.raises(R0ScopeError, match="not in the served list"):
        column_differences(["a"], ["a", "z"])
    assert column_differences(["a", "pressure"], ["a"], policy_exclusions=["pressure"])[0]["reason"] == REASON_POLICY


def test_differences_record_names_everything_and_passes_the_leakage_audit(served):
    record = allowlist_record(_resolve("r0:miami", MIAMI))
    inputs = {"centre_date": "2026-11-24", "training_years": [2021, 2022, 2023],
              "training_days_by_year": {"2021": 15}, "forecast_source": "pit_forecast_corpus",
              "pit_forecast_corpus": {"corpora": [{"corpus_id": "c" * 64}]}}
    differences = served_model_differences(record, inputs, base_models_only=True)
    assert differences["served_column_count"] == len(MIAMI_STYLE)
    assert differences["trained_column_count"] == len(MIAMI_STYLE) - 4
    assert [row["column"] for row in differences["columns_removed"]] == PRESSURE + CONSENSUS
    assert differences["columns_added"] == []
    assert differences["base_models_only"] is True
    assert differences["forecast_corpus_ids"] == ["c" * 64]
    audit = audit_recursive_model_inputs({
        "base_model.miami.feature_hgb": {"served_model_differences": differences,
                                         "training_column_allowlist": record},
    })
    assert audit["status"] == "PASS", audit["rejections"]


def test_main_refuses_r0_mode_without_a_pit_corpus(tmp_path, monkeypatch, served):
    _patch_trainer(monkeypatch, {})
    import weather.calibration.feature_model as trainer

    with pytest.raises(TrainingInputError, match="trains R0 only"):
        trainer.main("nyc", column_allowlist="r0:nyc", output_root=str(tmp_path / "r0"))
    assert not (tmp_path / "r0").exists()


def test_main_r0_mode_records_the_differences_in_both_artifacts(tmp_path, monkeypatch, served, corpora):  # noqa: F811
    served["nyc"] = [  # the fixture records carry only these numeric columns
        "high_so_far", "pressure", "forecast_high", "forecast_source_count", "forecast_disagreement",
    ] + ONE_HOT
    trainer = _patch_trainer(monkeypatch, {})
    out = tmp_path / "r0"
    trainer.main(
        "nyc", column_allowlist="r0:nyc", output_root=str(out), target_date="2026-11-24",
        pit_forecast_corpus_manifests=[str(corpora["2021"]), str(corpora["2022"])],
    )
    hgb = pickle.loads((out / "feature_model_hgb_nyc.pkl").read_bytes())
    coefs = json.loads((out / "feature_model_coefs_nyc.json").read_text(encoding="utf-8"))
    assert hgb["served_model_differences"] == coefs["served_model_differences"]
    differences = coefs["served_model_differences"]
    assert [row["column"] for row in differences["columns_removed"]] == ["pressure", *CONSENSUS]
    assert differences["centre_date"] == "2026-11-24"
    assert differences["training_years"] == [2021, 2022]
    assert differences["forecast_source"] == "pit_forecast_corpus"
    assert coefs["12"]["feature_names"] == ["high_so_far", "forecast_high", *ONE_HOT]
    assert coefs["training_column_allowlist"]["mode"] == "r0"


# Owner-approved R0 leaf sweep (2026-10-24): research-only --min-samples-leaf ---------------------


def test_default_hgb_is_the_served_trainer_hgb():
    from sklearn.ensemble import HistGradientBoostingClassifier

    import weather.calibration.feature_model as trainer

    params = trainer.make_feature_hgb().get_params()
    reference = HistGradientBoostingClassifier(
        max_iter=50, max_leaf_nodes=15, learning_rate=0.05, random_state=42,
    ).get_params()
    assert params == reference
    assert trainer.HGB_MIN_SAMPLES_LEAF == trainer.SERVED_HGB_MIN_SAMPLES_LEAF == 20


@pytest.mark.parametrize("value", ["0", "abc", "2.5", "1001", " "])
def test_min_samples_leaf_parse_fails_closed(value):
    from weather.calibration.feature_model import parse_min_samples_leaf

    with pytest.raises(TrainingInputError, match="min-samples-leaf"):
        parse_min_samples_leaf(value)


def test_cli_min_samples_leaf_needs_output_root():
    from weather.calibration.feature_model import parse_cli_args

    args = parse_cli_args(["--market", "nyc", "--output-root", "o", "--min-samples-leaf", "5"])
    assert args.min_samples_leaf == "5"
    assert parse_cli_args([]).min_samples_leaf is None
    for argv in (["--min-samples-leaf", "5"], ["--output-root", "o", "--min-samples-leaf", "0"],
                 ["--late-day-only", "--min-samples-leaf", "5"]):
        with pytest.raises(SystemExit):
            parse_cli_args(["--market", "nyc", *argv])


def test_main_refuses_min_samples_leaf_on_the_served_path(monkeypatch):
    trainer = _patch_trainer(monkeypatch, {})
    with pytest.raises(TrainingInputError, match="needs --output-root"):
        trainer.main("nyc", min_samples_leaf=5)
    assert trainer.HGB_MIN_SAMPLES_LEAF == 20


def test_main_leaf_sweep_fits_and_records_the_value(tmp_path, monkeypatch, served, corpora):  # noqa: F811
    served["nyc"] = ["high_so_far", "pressure", "forecast_high"] + ONE_HOT
    trainer = _patch_trainer(monkeypatch, {})
    out = tmp_path / "r0-msl5"
    trainer.main(
        "nyc", column_allowlist="r0:nyc", output_root=str(out), target_date="2026-11-24",
        pit_forecast_corpus_manifests=[str(corpora["2021"]), str(corpora["2022"])],
        min_samples_leaf=5,
    )
    assert trainer.HGB_MIN_SAMPLES_LEAF == 20  # restored after the run
    hgb = pickle.loads((out / "feature_model_hgb_nyc.pkl").read_bytes())
    coefs = json.loads((out / "feature_model_coefs_nyc.json").read_text(encoding="utf-8"))
    fitted = [value for value in hgb["12"].values() if hasattr(value, "_predictors")]
    assert fitted and all(model.get_params()["min_samples_leaf"] == 5 for model in fitted)
    for info in (hgb, coefs):
        assert info["hgb_hyperparameters"]["min_samples_leaf"] == 5
        assert info["hgb_hyperparameters"]["served_min_samples_leaf"] == 20
        assert info["served_model_differences"]["hyperparameters"]["hgb_min_samples_leaf"] == 5


def test_served_leaf_keeps_the_differences_record_unchanged():
    record = {"served_feature_names": ["a"], "feature_names": ["a"], "column_differences_from_served": []}
    default = served_model_differences(record, None, base_models_only=True)
    assert default == served_model_differences(record, None, base_models_only=True, hgb_min_samples_leaf=20)
    assert default["hyperparameters"] == "unchanged_from_served_trainer"
    swept = served_model_differences(record, None, base_models_only=True, hgb_min_samples_leaf=10)
    assert swept["hyperparameters"]["hgb_min_samples_leaf"] == 10


def test_main_writes_per_row_blocked_validation_losses(tmp_path, monkeypatch, served, corpora):  # noqa: F811
    served["nyc"] = ["high_so_far", "pressure", "forecast_high"] + ONE_HOT
    trainer = _patch_trainer(monkeypatch, {})
    monkeypatch.setattr(trainer, "RUN_LOO", True)
    out = tmp_path / "r0-rows"
    trainer.main(
        "nyc", column_allowlist="r0:nyc", output_root=str(out), target_date="2026-11-24",
        pit_forecast_corpus_manifests=[str(corpora["2021"]), str(corpora["2022"])],
    )
    path = out / "feature_model_blocked_validation_rows_nyc.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows and {row["hour"] for row in rows} == {12}
    assert {row["validation_year"] for row in rows} <= {2021, 2022}
    assert all(row["validation_date"][:4] == str(row["validation_year"]) for row in rows)
    for key in ("baseline_log_loss", "lr_log_loss", "hgb_log_loss", "hgb_brier"):
        assert all(isinstance(row[key], float) for row in rows)
    report = (out / "feature_model_report_nyc.md").read_text(encoding="utf-8")
    assert "HGBC LogLoss" in report
    for key in ("baseline_floored_log_loss", "lr_floored_log_loss", "hgb_floored_log_loss", "hgb_floored_brier"):
        assert all(isinstance(row[key], float) for row in rows)
    assert all("hgb_distribution" not in row for row in rows)  # distributions are opt-in
    floored = [row for row in rows if row["observed_floor_bucket"] is not None]
    assert floored


# Research-only floored scoring of the R0 rows (coordinator GO 2026-10-24) ------------------------


def test_observed_floor_matches_the_serving_hard_floor_and_never_mutates():
    from weather.calibration.feature_model import apply_observed_floor, observed_floor_bucket
    from weather.model.model_distribution import DistributionMixin

    probs = {60: 0.2, 61: 0.3, 62: 0.4, 63: 0.1}
    before = dict(probs)
    floored = apply_observed_floor(probs, 62)
    assert probs == before
    serving = dict(probs)
    DistributionMixin.apply_floor(None, serving, 62, 0.000001)
    total = sum(serving.values())
    assert floored == pytest.approx({k: v / total for k, v in serving.items()})
    assert sum(floored.values()) == pytest.approx(1.0)
    assert apply_observed_floor(probs, None) == probs
    assert observed_floor_bucket(61.5) == 62
    assert observed_floor_bucket(float("nan")) is None
    assert observed_floor_bucket(None) is None


def test_validation_row_distributions_flag_needs_output_root():
    from weather.calibration.feature_model import parse_cli_args

    assert parse_cli_args([]).validation_row_distributions is False
    args = parse_cli_args(["--market", "nyc", "--output-root", "o", "--validation-row-distributions"])
    assert args.validation_row_distributions is True
    for argv in (["--validation-row-distributions"], ["--late-day-only", "--validation-row-distributions"]):
        with pytest.raises(SystemExit):
            parse_cli_args(["--market", "nyc", *argv])


def test_main_refuses_row_distributions_on_the_served_path(monkeypatch):
    trainer = _patch_trainer(monkeypatch, {})
    with pytest.raises(TrainingInputError, match="needs --output-root"):
        trainer.main("nyc", validation_row_distributions=True)


def test_row_distributions_leave_the_trained_bundles_byte_identical(tmp_path, monkeypatch, served, corpora):  # noqa: F811
    served["nyc"] = ["high_so_far", "pressure", "forecast_high"] + ONE_HOT
    trainer = _patch_trainer(monkeypatch, {})
    monkeypatch.setattr(trainer, "RUN_LOO", True)

    class _FixedClock:  # trained_at is wall-clock; pin it so the bundles compare byte for byte
        @staticmethod
        def now():
            from datetime import datetime

            return datetime(2026, 10, 24, 12, 0, 0)

    monkeypatch.setattr(trainer, "datetime", _FixedClock)
    outputs = {}
    for flag in (False, True):
        out = tmp_path / f"r0-dist-{int(flag)}"
        trainer.main(
            "nyc", column_allowlist="r0:nyc", output_root=str(out), target_date="2026-11-24",
            pit_forecast_corpus_manifests=[str(corpora["2021"]), str(corpora["2022"])],
            validation_row_distributions=flag,
        )
        outputs[flag] = out
    for name in ("feature_model_hgb_nyc.pkl", "feature_model_coefs_nyc.json"):
        assert (outputs[False] / name).read_bytes() == (outputs[True] / name).read_bytes()
    rows_path = "feature_model_blocked_validation_rows_nyc.jsonl"
    plain = [json.loads(line) for line in (outputs[False] / rows_path).read_text(encoding="utf-8").splitlines()]
    rich = [json.loads(line) for line in (outputs[True] / rows_path).read_text(encoding="utf-8").splitlines()]
    assert len(plain) == len(rich)
    for a, b in zip(plain, rich):
        assert {k: b[k] for k in a} == a
        assert set(b) - set(a) == {"observed_high", "actual_bucket", "hgb_distribution"}
        assert sum(b["hgb_distribution"].values()) == pytest.approx(1.0)
        from weather.calibration.feature_model import apply_observed_floor, log_loss

        dist = {int(k): v for k, v in b["hgb_distribution"].items()}
        assert log_loss(dist, b["actual_bucket"]) == pytest.approx(b["hgb_log_loss"])
        assert log_loss(apply_observed_floor(dist, b["observed_floor_bucket"]), b["actual_bucket"]) == (
            pytest.approx(b["hgb_floored_log_loss"])
        )
