"""R0 training inputs for the per-market feature trainer (retrain memo R0.2 M3, M4, M5, M6 flag, M10).

Guards: retrain memo R0.2 M3-M5 (PIT corpus consumer, two-corpus union, pinned centre date), the generic
--training-years flag and the M10 fail-closed data-root check; no ambient forecast fallback when corpora are given.
Corpora are built in-test with the real plan/stage/materialize path; nothing reads data/ or LFS artifacts.
"""

from __future__ import annotations

import json
import pickle
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from weather.calibration.feature_model import CLOUD_GROUPS, WIND_GROUPS, parse_cli_args
from weather.calibration.feature_model_training_inputs import (
    FORECAST_SOURCE_PIT,
    PITForecastCorpusUnion,
    TrainingInputError,
    null_forecast_relative_marine_fields,
    parse_target_date,
    parse_training_years,
    require_market_history,
    select_training_days,
    training_inputs_record,
)
from weather.calibration.forecast_training_contract import FORECAST_RELATIVE_MARINE_FIELDS
from weather.market.market_registry import NYC
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.sources.forecast_training_corpus import (
    CorpusVerificationError,
    build_plan,
    materialize_corpus,
    stage_response,
    write_immutable_plan,
)

CENTRE = date(2026, 11, 24)


def _response(request):
    target_date = request["window_start"]
    hourly = {"time": [f"{target_date}T{hour:02d}:00" for hour in range(24)]}
    units = {}
    for index, binding in enumerate(request["variables"]):
        hourly[binding["request_field"]] = [float(index + hour + 1) for hour in range(24)]
        units[binding["request_field"]] = binding["source_unit"]
    return json.dumps({"hourly": hourly, "hourly_units": units}).encode("utf-8")


def _evidence(request):
    target = date.fromisoformat(request["window_start"])
    issue_day = (target - timedelta(days=1)).isoformat()
    return [{
        "target_date": request["window_start"],
        "issue_evidence_kind": "fixed_lead_offset",
        "issue_time_utc": f"{issue_day}T00:00:00Z",
        "available_at_utc": f"{issue_day}T06:00:00Z",
        "run_id_exposed": True,
        "run_id": f"gfs-{issue_day}-00z",
    }]


def _corpus(root, year, *, markets=("nyc",), fields=("temperature_2m",), cutoffs=INTRADAY_CUTOFF_HOURS):
    root.mkdir(parents=True)
    plan = build_plan(
        years=(year,),
        target_year=2026,
        market_ids=markets,
        season_start=(11, 24),
        season_end=(11, 24),
        cutoff_hours=cutoffs,
        planned_at_utc="2026-01-01T00:00:00+00:00",
        source_fields=fields,
    )
    plan_path = root / "plan.json"
    write_immutable_plan(plan_path, plan)
    for request in plan["requests"]:
        stage_response(
            plan_path,
            root / "staging",
            request["request_hash"],
            _response(request),
            http_status=200,
            http_headers={"ETag": "fixture"},
            retrieved_at_utc="2026-01-01T01:00:00Z",
            issue_evidence=_evidence(request),
        )
    return materialize_corpus(plan_path, root / "staging", root / "training")


@pytest.fixture(scope="module")
def corpora(tmp_path_factory):
    base = tmp_path_factory.mktemp("pit")
    return {
        "2021": _corpus(base / "a", 2021),
        "2022": _corpus(base / "b", 2022),
        "2021_wide": _corpus(base / "c", 2021, markets=("nyc", "chicago")),
        "2022_cloud": _corpus(base / "d", 2022, fields=("temperature_2m", "cloud_cover")),
        "2023_chicago": _corpus(base / "e", 2023, markets=("chicago",)),
    }


def _union(paths, market="nyc"):
    return PITForecastCorpusUnion(
        paths, market, target_year=2026, required_cutoff_hours=INTRADAY_CUTOFF_HOURS,
    )


# M5 / M6 flag parsing --------------------------------------------------------


def test_target_date_parses_iso_only():
    assert parse_target_date("2026-11-24") == CENTRE
    assert parse_target_date(CENTRE) is CENTRE
    for bad in ("2026-11-31", "11/24/2026", "2026-11-24T00:00", ""):
        with pytest.raises(TrainingInputError):
            parse_target_date(bad)


def test_training_years_accept_lists_and_ranges():
    assert parse_training_years("2021-2023") == (2021, 2022, 2023)
    assert parse_training_years("2025, 2021-2022,2021") == (2021, 2022, 2025)
    assert parse_training_years([2024, 2023]) == (2023, 2024)
    for bad in ("", "2023-2021", "21", "2021;2022", "1800"):
        with pytest.raises(TrainingInputError):
            parse_training_years(bad)


# M3 / M4: the union of verified corpora ---------------------------------------


def test_union_dispatches_by_year_and_never_falls_back(corpora):
    union = _union([corpora["2022"], corpora["2021"]])
    assert union.years == (2021, 2022)
    first = union.resolve("2021-11-24", 7)
    second = union.resolve("2022-11-24", 20)
    assert first["forecast_high"] == 24.0 == second["forecast_high"]
    assert len(first["profile_rows"]) == 24
    ids = [row["corpus_id"] for row in union.record()["corpora"]]
    assert first["provenance"]["corpus_id"] == ids[0]
    assert second["provenance"]["corpus_id"] == ids[1]
    assert ids[0] != ids[1]
    with pytest.raises(CorpusVerificationError, match="ambient fallback is not allowed"):
        union.resolve("2023-11-24", 12)
    # Order of the manifests does not change the recorded identity.
    assert _union([corpora["2021"], corpora["2022"]]).record() == union.record()


def test_union_refuses_a_repeated_corpus(corpora):
    with pytest.raises(TrainingInputError, match="given twice"):
        _union([corpora["2021"], corpora["2021"]])


def test_union_refuses_overlapping_years(corpora):
    with pytest.raises(TrainingInputError, match=r"overlap in years \[2021\]"):
        _union([corpora["2021"], corpora["2021_wide"]])


def test_union_refuses_incompatible_corpora(corpora):
    with pytest.raises(TrainingInputError, match="source_fields"):
        _union([corpora["2021"], corpora["2022_cloud"]])


def test_union_refuses_a_corpus_without_the_market(corpora):
    with pytest.raises(TrainingInputError, match="absent from PIT corpus"):
        _union([corpora["2021"], corpora["2023_chicago"]])


def test_union_requires_a_manifest_and_the_full_cutoff_matrix(corpora):
    with pytest.raises(TrainingInputError, match="at least one"):
        _union([])
    with pytest.raises(CorpusVerificationError, match="cutoff matrix"):
        PITForecastCorpusUnion(
            [corpora["2021"]], "nyc", target_year=2026, required_cutoff_hours=(10,),
        )


def test_union_refuses_a_centre_year_that_differs_from_the_corpus(corpora):
    with pytest.raises(CorpusVerificationError, match="target year"):
        PITForecastCorpusUnion(
            [corpora["2021"]], "nyc", target_year=2027,
            required_cutoff_hours=INTRADAY_CUTOFF_HOURS,
        )


# Training-window selection ----------------------------------------------------


def _daily(years, day=(11, 24)):
    return {date(year, *day): {"bucket": 50} for year in years}


def test_selection_is_unchanged_without_options():
    daily = _daily((2019, 2020))
    kept, counts = select_training_days(daily)
    assert kept == daily and counts == {}


def test_selection_defaults_to_the_corpus_years():
    kept, counts = select_training_days(
        _daily((2019, 2021, 2022, 2025)), forecast_years=(2021, 2022), target_date=CENTRE,
    )
    assert sorted(day.year for day in kept) == [2021, 2022]
    assert counts == {"2021": 1, "2022": 1}


def test_explicit_years_must_be_covered_by_a_corpus():
    with pytest.raises(TrainingInputError, match=r"\[2024\] have no PIT corpus"):
        select_training_days(
            _daily((2021, 2024)), training_years=(2021, 2024), forecast_years=(2021, 2022),
        )
    kept, counts = select_training_days(
        _daily((2021, 2022)), training_years=(2021,), forecast_years=(2021, 2022),
    )
    assert list(kept) == [date(2021, 11, 24)] and counts == {"2021": 1}


def test_explicit_years_without_corpus_select_any_prior_years():
    kept, counts = select_training_days(
        _daily((2018, 2024, 2025)), training_years=(2024, 2025), target_date=CENTRE,
    )
    assert counts == {"2024": 1, "2025": 1}
    assert date(2018, 11, 24) not in kept


def test_selection_refuses_empty_or_non_prior_years():
    with pytest.raises(TrainingInputError, match=r"\[2023\] have no labelled day"):
        select_training_days(_daily((2021,)), training_years=(2021, 2023))
    with pytest.raises(TrainingInputError, match="not earlier than the centre year"):
        select_training_days(_daily((2026,)), training_years=(2026,), target_date=CENTRE)


def test_forecast_relative_marine_fields_are_dropped_only():
    features = {column: 1.5 for column in FORECAST_RELATIVE_MARINE_FIELDS}
    features["marine_water_temp"] = 9.0
    cleaned = null_forecast_relative_marine_fields(features)
    assert all(cleaned[column] is None for column in FORECAST_RELATIVE_MARINE_FIELDS)
    assert cleaned["marine_water_temp"] == 9.0
    assert features[FORECAST_RELATIVE_MARINE_FIELDS[0]] == 1.5
    assert null_forecast_relative_marine_fields(None) is None


def test_missing_market_history_fails_closed(tmp_path):
    spec = SimpleNamespace(data_root=tmp_path / "wunderground" / "klga")
    with pytest.raises(TrainingInputError, match="Training from a worktree"):
        require_market_history(spec)
    summary = spec.data_root / "daily" / "daily_summary.csv"
    summary.parent.mkdir(parents=True)
    summary.write_text("local_date\n", encoding="utf-8")
    assert require_market_history(spec) == summary


def test_training_inputs_record_is_hashed_and_names_the_corpora(corpora):
    union = _union([corpora["2021"], corpora["2022"]])
    record = training_inputs_record(
        target_date=CENTRE, training_years=(2021, 2022), corpus_union=union,
        day_counts={"2022": 15, "2021": 15},
    )
    assert record["centre_date"] == "2026-11-24" and record["centre_date_pinned"] is True
    assert record["forecast_source"] == FORECAST_SOURCE_PIT
    assert record["ambient_forecast_fallback"] is False
    assert list(record["training_days_by_year"]) == ["2021", "2022"]
    assert [row["years"] for row in record["pit_forecast_corpus"]["corpora"]] == [[2021], [2022]]
    changed = training_inputs_record(
        target_date=date(2026, 12, 10), training_years=(2021, 2022), corpus_union=union,
        day_counts={"2022": 15, "2021": 15},
    )
    assert changed["record_sha256"] != record["record_sha256"]


# Trainer wiring ---------------------------------------------------------------


def test_record_builder_reads_the_resolver_per_cutoff(monkeypatch):
    import weather.calibration.feature_model as trainer

    calls = []

    def fake_record(local_date, rows, daily_row, hour, **kwargs):
        calls.append((hour, kwargs))
        return {"hour": hour}

    class Resolver:
        def resolve(self, target_date, cutoff_hour):
            return {"forecast_high": 40.0 + cutoff_hour, "profile_rows": [{"h": cutoff_hour}]}

    monkeypatch.setattr(trainer, "build_historical_feature_record", fake_record)
    model = SimpleNamespace(wind_group=None, cloud_group=None, microclimate_features=None)
    day = date(2021, 11, 24)
    marine = {(day.isoformat(), hour): {FORECAST_RELATIVE_MARINE_FIELDS[0]: 3.0, "sst": 8.0}
              for hour in INTRADAY_CUTOFF_HOURS}
    raw = trainer.build_feature_records_for_model(
        model, {day: {"bucket": 50}}, {day: [{"minute_of_day": 420}]}, None, None,
        marine_water_contrast_index=marine, forecast_resolver=Resolver(),
    )
    assert sorted(raw) == list(INTRADAY_CUTOFF_HOURS)
    for hour, kwargs in calls:
        assert kwargs["forecast_high"] == 40.0 + hour
        assert kwargs["forecast_profile_rows"] == [{"h": hour}]
        assert kwargs["marine_context_features"][FORECAST_RELATIVE_MARINE_FIELDS[0]] is None
        assert kwargs["marine_context_features"]["sst"] == 8.0


def test_record_builder_default_path_is_unchanged(monkeypatch):
    import weather.calibration.feature_model as trainer

    calls = []
    monkeypatch.setattr(
        trainer, "build_historical_feature_record",
        lambda *args, **kwargs: calls.append(kwargs) or {"ok": 1},
    )
    model = SimpleNamespace(wind_group=None, cloud_group=None, microclimate_features=None)
    day = date(2021, 6, 1)
    marine = {(day.isoformat(), 7): {FORECAST_RELATIVE_MARINE_FIELDS[0]: 3.0}}
    trainer.build_feature_records_for_model(
        model, {day: {}}, {day: [{}]}, {day.isoformat(): 77.0}, {day.isoformat(): ["p"]},
        marine_water_contrast_index=marine,
    )
    assert {kwargs["forecast_high"] for kwargs in calls} == {77.0}
    assert calls[0]["marine_context_features"][FORECAST_RELATIVE_MARINE_FIELDS[0]] == 3.0


def _records(n=36):
    rng = np.random.default_rng(3)
    rows = []
    for index in range(n):
        rows.append({
            "high_so_far": float(rng.normal(50, 4)),
            "forecast_high": float(rng.normal(52, 4)),
            "wind_group": WIND_GROUPS[index % len(WIND_GROUPS)],
            "cloud_group": CLOUD_GROUPS[index % len(CLOUD_GROUPS)],
            "target_date": date(2021 + index % 2, 11, 17) + timedelta(days=index % 15),
            "final_bucket": 50 + index % 3,
        })
    return rows


class _FakeModel:
    constructed = []

    def __init__(self, market_id="toronto", target_date=None):
        type(self).constructed.append(target_date)
        self.spec = NYC
        self.calibrated_weights = None
        self.target_date = target_date or date(2026, 10, 21)

    def historical_target_cache(self):
        daily = {}
        for year in (2019, 2020, 2021, 2022, 2025):
            for offset in range(-7, 8):
                daily[date(year, 11, 24) + timedelta(days=offset)] = {"bucket": 50}
        return {"daily": daily, "by_date": {}, "bucket_space": [50, 51, 52]}


def _patch_trainer(monkeypatch, seen):
    import weather.calibration.feature_model as trainer

    _FakeModel.constructed = []
    monkeypatch.setattr(trainer, "TorontoHighTempModel", _FakeModel)
    monkeypatch.setattr(trainer, "RUN_LOO", False)
    monkeypatch.setattr(trainer, "require_market_history", lambda spec: None)

    def no_ambient(*args, **kwargs):
        raise AssertionError("the ambient forecast archive must not be read")

    seen["ambient"] = no_ambient
    for loader in ("load_forecast_daily", "load_forecast_profiles"):
        monkeypatch.setattr(trainer, loader, lambda *args, **kwargs: seen["ambient"]())
    for loader in ("load_marine_water_contrast_features", "load_reanalysis_synoptic_features"):
        monkeypatch.setattr(trainer, loader, lambda *args, **kwargs: {})

    def fake_records(model, daily, by_date, forecast_index, forecast_profiles, **kwargs):
        seen["daily"] = sorted(daily)
        seen["resolver"] = kwargs.get("forecast_resolver")
        seen["forecast_index"] = forecast_index
        return defaultdict(list, {12: _records()})

    monkeypatch.setattr(trainer, "build_feature_records_for_model", fake_records)
    monkeypatch.setattr(
        trainer, "train_late_day_continuation_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no late-day in R0")),
    )
    return trainer


def test_main_trains_from_the_union_at_the_pinned_centre(tmp_path, monkeypatch, corpora):
    seen = {}
    trainer = _patch_trainer(monkeypatch, seen)
    out = tmp_path / "r0"
    trainer.main(
        "nyc",
        output_root=str(out),
        target_date="2026-11-24",
        pit_forecast_corpus_manifests=[str(corpora["2021"]), str(corpora["2022"])],
    )
    assert _FakeModel.constructed == [CENTRE]
    assert {day.year for day in seen["daily"]} == {2021, 2022}
    assert len(seen["daily"]) == 30
    assert isinstance(seen["resolver"], PITForecastCorpusUnion)
    assert seen["forecast_index"] is None
    hgb = pickle.loads((out / "feature_model_hgb_nyc.pkl").read_bytes())
    coefs = json.loads((out / "feature_model_coefs_nyc.json").read_text(encoding="utf-8"))
    assert hgb["training_inputs"] == coefs["training_inputs"]
    record = coefs["training_inputs"]
    assert record["centre_date"] == "2026-11-24"
    assert record["training_years"] == [2021, 2022]
    assert record["training_days_by_year"] == {"2021": 15, "2022": 15}
    assert record["forecast_source"] == FORECAST_SOURCE_PIT
    assert len(record["pit_forecast_corpus"]["corpora"]) == 2
    assert coefs["base_models_only"] is True


def test_main_training_years_without_corpus_reads_ambient(tmp_path, monkeypatch):
    seen = {}
    trainer = _patch_trainer(monkeypatch, seen)
    seen["ambient"] = lambda: {}
    trainer.main("nyc", output_root=str(tmp_path / "r0"), training_years="2025,2019")
    assert _FakeModel.constructed == [None]
    assert {day.year for day in seen["daily"]} == {2019, 2025}
    assert seen["resolver"] is None
    coefs = json.loads((tmp_path / "r0" / "feature_model_coefs_nyc.json").read_text(encoding="utf-8"))
    assert coefs["training_inputs"]["forecast_source"] == "ambient_forecast_archive"
    assert coefs["training_inputs"]["centre_date_pinned"] is False


def test_main_refuses_uncovered_training_years_before_fitting(tmp_path, monkeypatch, corpora):
    seen = {}
    trainer = _patch_trainer(monkeypatch, seen)
    with pytest.raises(TrainingInputError, match=r"\[2025\] have no PIT corpus"):
        trainer.main(
            "nyc", output_root=str(tmp_path / "r0"), target_date="2026-11-24",
            pit_forecast_corpus_manifests=[str(corpora["2021"])], training_years="2021,2025",
        )
    assert "daily" not in seen
    assert not (tmp_path / "r0").exists()


@pytest.mark.parametrize(
    "kwargs",
    [{"target_date": "2026-11-24"}, {"training_years": "2021"},
     {"pit_forecast_corpus_manifests": ["m.json"]}],
)
def test_main_refuses_r0_inputs_on_the_served_path(monkeypatch, kwargs):
    trainer = _patch_trainer(monkeypatch, {})
    with pytest.raises(TrainingInputError, match="need --output-root"):
        trainer.main("nyc", **kwargs)
    assert _FakeModel.constructed == []


def test_cli_parses_repeatable_manifests_and_pins():
    args = parse_cli_args([
        "--market", "nyc", "--output-root", "out", "--target-date", "2026-12-10",
        "--pit-forecast-corpus-manifest", "a.json", "--pit-forecast-corpus-manifest", "b.json",
        "--training-years", "2021-2023",
    ])
    assert args.pit_forecast_corpus_manifests == ["a.json", "b.json"]
    assert (args.target_date, args.training_years) == ("2026-12-10", "2021-2023")


@pytest.mark.parametrize(
    "argv",
    [
        ["--target-date", "2026-11-24"],
        ["--training-years", "2021"],
        ["--pit-forecast-corpus-manifest", "a.json"],
        ["--output-root", "o", "--target-date", "2026-13-01"],
        ["--output-root", "o", "--training-years", "2023-2021"],
        ["--output-root", "o", "--late-day-only", "--target-date", "2026-11-24"],
    ],
)
def test_cli_refuses_misused_r0_inputs(argv):
    with pytest.raises(SystemExit) as raised:
        parse_cli_args(["--market", "nyc", *argv])
    assert raised.value.code == 2


def test_cli_defaults_leave_the_new_inputs_unset():
    args = parse_cli_args([])
    assert (args.target_date, args.pit_forecast_corpus_manifests, args.training_years) == (
        None, None, None,
    )


def test_training_inputs_record_passes_the_release_leakage_audit(corpora):
    """The record rides inside base-model artifacts a research release freezes (M14)."""
    from weather.model.feature_safety import audit_recursive_model_inputs

    record = training_inputs_record(
        target_date=CENTRE, training_years=(2021, 2022), corpus_union=_union([corpora["2021"], corpora["2022"]]),
        day_counts={"2021": 15, "2022": 15},
    )
    audit = audit_recursive_model_inputs({"base_model.nyc.feature_lr_coefficients": {"training_inputs": record}})
    assert audit["status"] == "PASS", audit["rejections"]
