import hashlib
import json
from datetime import date

import pytest

from weather.calibration.forecast_training_contract import (
    preflight_pit_forecast_training_corpus,
)
from weather.sources.forecast_training_corpus import (
    CorpusVerificationError,
    DEFAULT_SOURCE_FIELDS,
    FREE_PIT_SOURCE_FIELDS,
    PITForecastTrainingCorpus,
    MaterializationBlocked,
    PlanValidationError,
    StagingValidationError,
    UNAVAILABLE_PIT_SOURCE_FIELDS,
    assert_training_only_publish_root,
    build_plan,
    materialize_corpus,
    resume_ledger,
    stage_response,
    verify_plan,
    verify_corpus_manifest,
    write_immutable_plan,
)


def _payload_hash(payload):
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _self_hash(payload, field):
    body = dict(payload)
    body.pop(field, None)
    return _payload_hash(body)


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_default_source_fields_are_the_proven_free_pit_surface():
    assert DEFAULT_SOURCE_FIELDS == FREE_PIT_SOURCE_FIELDS
    assert FREE_PIT_SOURCE_FIELDS == (
        "temperature_2m",
        "cloud_cover",
        "shortwave_radiation",
        "wind_speed_10m",
        "cape",
        "direct_radiation",
        "diffuse_radiation",
        "wind_gusts_10m",
        "precipitation_probability",
        "precipitation",
        "vapour_pressure_deficit",
        "et0_fao_evapotranspiration",
    )
    assert set(FREE_PIT_SOURCE_FIELDS).isdisjoint(UNAVAILABLE_PIT_SOURCE_FIELDS)
    assert set(UNAVAILABLE_PIT_SOURCE_FIELDS) == {
        "cloud_cover_low",
        "cloud_cover_mid",
        "cloud_cover_high",
        "visibility",
        "soil_temperature_0cm",
        "soil_moisture_0_to_1cm",
        "temperature_925hPa",
        "temperature_850hPa",
        "geopotential_height_500hPa",
    }


def _plan(tmp_path, *, markets=("toronto",), year=2021, target_year=2026, cutoffs=(10,)):
    plan = build_plan(
        years=(year,),
        target_year=target_year,
        market_ids=markets,
        season_start=(5, 10),
        season_end=(5, 10),
        cutoff_hours=cutoffs,
        planned_at_utc="2026-01-01T00:00:00+00:00",
    )
    path = tmp_path / "plan.json"
    write_immutable_plan(path, plan)
    return plan, path


def _response_for(request, *, target_date=None, empty=False, unit_override=None):
    target_date = target_date or request["window_start"]
    times = [] if empty else [f"{target_date}T{hour:02d}:00" for hour in range(24)]
    hourly = {"time": times}
    hourly_units = {}
    for field_index, binding in enumerate(request["variables"]):
        values = [] if empty else [float(field_index + hour + 1) for hour in range(24)]
        hourly[binding["request_field"]] = values
        hourly_units[binding["request_field"]] = (
            unit_override
            if unit_override and binding["source_field"] == unit_override[0]
            else binding["source_unit"]
        )
    return json.dumps({"hourly": hourly, "hourly_units": hourly_units}).encode("utf-8")


def _evidence(request, *, kind="fixed_lead_offset", available_at="2021-05-09T06:00:00Z"):
    return [
        {
            "target_date": request["window_start"],
            "issue_evidence_kind": kind,
            "issue_time_utc": "2021-05-09T00:00:00Z",
            "available_at_utc": available_at,
            "run_id_exposed": True,
            "run_id": "gfs-20210509-00z",
        }
    ]


def _stage_valid(plan_path, staging_root, request, **response_kwargs):
    return stage_response(
        plan_path,
        staging_root,
        request["request_hash"],
        _response_for(request, **response_kwargs),
        http_status=200,
        http_headers={"ETag": "fixture", "Authorization": "must-not-persist"},
        retrieved_at_utc="2026-01-01T01:00:00Z",
        issue_evidence=_evidence(request),
    )


def test_plan_is_immutable_network_free_and_excludes_target_year(tmp_path):
    plan, path = _plan(tmp_path)

    assert plan["mode"] == "dry_run_no_network"
    assert plan["schema_version"] == "pit_forecast_corpus_plan_v2"
    assert plan["network_authorized"] is False
    assert plan["provider_probe_authorized"] is False
    assert plan["years"] == [2021]
    assert plan["target_year"] == 2026
    assert plan["target_year_excluded"] is True
    assert plan["source_fields"] == list(DEFAULT_SOURCE_FIELDS)
    assert all(request["year"] != 2026 for request in plan["requests"])
    for request in plan["requests"]:
        requested_fields = [row["source_field"] for row in request["variables"]]
        assert requested_fields == list(DEFAULT_SOURCE_FIELDS)
        assert set(requested_fields).isdisjoint(UNAVAILABLE_PIT_SOURCE_FIELDS)

    changed = dict(plan)
    changed["planned_at_utc"] = "2026-01-02T00:00:00+00:00"
    with pytest.raises(PlanValidationError, match="self-hash mismatch"):
        write_immutable_plan(path, changed)

    other = build_plan(
        years=(2021,),
        target_year=2026,
        market_ids=("toronto",),
        season_start=(5, 10),
        season_end=(5, 10),
        cutoff_hours=(10,),
        planned_at_utc="2026-01-02T00:00:00+00:00",
    )
    with pytest.raises(PlanValidationError, match="different content"):
        write_immutable_plan(path, other)


def test_rehashed_legacy_plan_schema_is_rejected(tmp_path):
    plan, _ = _plan(tmp_path)
    legacy = dict(plan)
    legacy["schema_version"] = "pit_forecast_corpus_plan_v1"
    legacy["plan_sha256"] = _self_hash(legacy, "plan_sha256")

    with pytest.raises(
        PlanValidationError,
        match="unsupported PIT forecast plan schema",
    ):
        verify_plan(legacy)


def test_zero_rows_are_failed_and_never_resume_as_complete(tmp_path):
    plan, path = _plan(tmp_path)
    request = plan["requests"][0]
    staging = tmp_path / "staging"

    with pytest.raises(StagingValidationError, match="zero_rows"):
        stage_response(
            path,
            staging,
            request["request_hash"],
            _response_for(request, empty=True),
            retrieved_at_utc="2026-01-01T01:00:00Z",
            issue_evidence=_evidence(request),
        )

    ledger = resume_ledger(path, staging)
    assert ledger["all_complete"] is False
    assert ledger["complete_units"] == 0
    failures = [json.loads(line) for line in (staging / "failure_ledger.jsonl").read_text().splitlines()]
    assert failures[-1]["failure_class"] == "staged_response_validation_failed"
    assert "zero_rows" in failures[-1]["errors"]


def test_resume_requires_the_staged_body_hash_to_still_match(tmp_path):
    plan, path = _plan(tmp_path)
    request = plan["requests"][0]
    staging = tmp_path / "staging"
    _stage_valid(path, staging, request)

    body_path = staging / "requests" / request["request_hash"] / "response.json"
    body_path.write_bytes(body_path.read_bytes() + b" ")

    ledger = resume_ledger(path, staging)
    assert ledger["all_complete"] is False
    assert ledger["units"][0]["reason"] == "byte_count_mismatch"


def test_partial_staging_cannot_publish_any_corpus(tmp_path):
    plan, path = _plan(tmp_path, markets=("toronto", "nyc"))
    staging = tmp_path / "staging"
    publish = tmp_path / "training"
    _stage_valid(path, staging, plan["requests"][0])

    with pytest.raises(MaterializationBlocked, match="all request units"):
        materialize_corpus(path, staging, publish)

    assert not (publish / "corpora").exists()
    failures = [json.loads(line) for line in (staging / "failure_ledger.jsonl").read_text().splitlines()]
    assert failures[-1]["failure_class"] == "partial_staging_blocks_publication"


@pytest.mark.parametrize(
    ("target_date", "evidence_kind", "unit_override", "available_at", "error"),
    [
        ("2026-05-10", "fixed_lead_offset", None, None, "target_year_row"),
        (None, "fixed_lead_offset", ("cloud_cover", "kelvin"), None, "invalid_unit"),
        (
            None,
            "fixed_lead_offset",
            None,
            "2021-05-10T15:00:00Z",
            "available_after_cutoff",
        ),
    ],
)
def test_staging_and_publication_reject_unsafe_rows(
    tmp_path,
    target_date,
    evidence_kind,
    unit_override,
    available_at,
    error,
):
    plan, path = _plan(tmp_path)
    request = plan["requests"][0]
    staging = tmp_path / "staging"
    body = _response_for(
        request,
        target_date=target_date,
        unit_override=unit_override,
    )
    evidence = _evidence(
        request,
        kind=evidence_kind,
        available_at=available_at or "2021-05-09T06:00:00Z",
    )
    with pytest.raises(StagingValidationError, match=error):
        stage_response(
            path,
            staging,
            request["request_hash"],
            body,
            retrieved_at_utc="2026-01-01T01:00:00Z",
            issue_evidence=evidence,
        )

    assert resume_ledger(path, staging)["all_complete"] is False
    with pytest.raises(MaterializationBlocked, match="all request units"):
        materialize_corpus(path, staging, tmp_path / "training")
    assert not (tmp_path / "training" / "corpora").exists()


@pytest.mark.parametrize("kind", ["", "stitched", "stitched_continuous_archive"])
def test_stitched_or_empty_issue_evidence_is_rejected_during_staging(tmp_path, kind):
    plan, path = _plan(tmp_path)
    request = plan["requests"][0]

    with pytest.raises(StagingValidationError, match="rejected_issue_evidence"):
        stage_response(
            path,
            tmp_path / "staging",
            request["request_hash"],
            _response_for(request),
            retrieved_at_utc="2026-01-01T01:00:00Z",
            issue_evidence=_evidence(request, kind=kind),
        )


def test_complete_corpus_is_atomic_content_addressed_and_explicit(tmp_path):
    plan, path = _plan(tmp_path)
    request = plan["requests"][0]
    staging = tmp_path / "staging"
    publish = tmp_path / "training"
    receipt = _stage_valid(path, staging, request)

    assert receipt["http_headers"] == {"etag": "fixture"}
    manifest_path = materialize_corpus(path, staging, publish)
    manifest = verify_corpus_manifest(manifest_path)
    assert manifest["schema_version"] == "pit_forecast_corpus_manifest_v2"
    assert manifest_path.parent.name == manifest["corpus_id"]
    assert manifest["coverage"]["status"] == "complete"
    assert manifest["active_archive_pinned"] is True
    assert manifest["daily_path_discoverable"] is False

    preflight = preflight_pit_forecast_training_corpus(
        manifest_path,
        target_year=2026,
        required_market_ids=["toronto"],
        required_years=[2021],
        required_cutoff_hours=[10],
    )
    assert preflight["status"] == "PASS"
    assert preflight["schema_version"] == "pit_forecast_training_preflight_v2"
    assert preflight["compatibility_fallback_allowed"] is False
    assert preflight["manifest_file_sha256"]
    assert preflight["selection_row_count"] == 1
    assert preflight["selection_binding_sha256"]

    with pytest.raises(CorpusVerificationError, match="does not cover"):
        preflight_pit_forecast_training_corpus(
            manifest_path,
            target_year=2026,
            required_market_ids=["toronto"],
            required_market_date_cutoffs=[("toronto", "2021-05-10", 11)],
        )

    reader = PITForecastTrainingCorpus(manifest_path, "toronto")
    resolved = reader.resolve(date(2021, 5, 10), 10)
    assert resolved["forecast_high"] == 24.0
    assert len(resolved["profile_rows"]) == 24
    assert resolved["provenance"]["request_hash"] == request["request_hash"]
    assert resolved["provenance"]["raw_response_sha256"] == receipt["raw_response_sha256"]

    with pytest.raises(MaterializationBlocked, match="overwrite refused"):
        materialize_corpus(path, staging, publish)


def test_rehashed_legacy_manifest_schema_is_rejected(tmp_path):
    plan, path = _plan(tmp_path)
    staging = tmp_path / "staging"
    _stage_valid(path, staging, plan["requests"][0])
    manifest_path = materialize_corpus(path, staging, tmp_path / "training")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "pit_forecast_corpus_manifest_v1"
    manifest["manifest_sha256"] = _self_hash(manifest, "manifest_sha256")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        CorpusVerificationError,
        match="unsupported PIT forecast corpus manifest schema",
    ):
        verify_corpus_manifest(manifest_path)


def test_rehashed_manifest_semantics_must_still_equal_the_plan(tmp_path):
    plan, path = _plan(tmp_path)
    staging = tmp_path / "staging"
    _stage_valid(path, staging, plan["requests"][0])
    manifest_path = materialize_corpus(path, staging, tmp_path / "training")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_fields"] = manifest["source_fields"][:-1]
    manifest["manifest_sha256"] = _self_hash(manifest, "manifest_sha256")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        CorpusVerificationError,
        match="source_fields differs from the plan",
    ):
        verify_corpus_manifest(manifest_path)


@pytest.mark.parametrize(
    "issue_kind",
    ["empty", "stitched", "stitched_continuous_archive"],
)
def test_rehashed_daily_issue_evidence_cannot_pass_preflight(tmp_path, issue_kind):
    plan, path = _plan(tmp_path)
    staging = tmp_path / "staging"
    _stage_valid(path, staging, plan["requests"][0])
    manifest_path = materialize_corpus(path, staging, tmp_path / "training")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    daily_path = manifest_path.parent / "forecast_daily.jsonl"
    row = json.loads(daily_path.read_text(encoding="utf-8").strip())
    row["issue_evidence_kind"] = issue_kind
    row["derived_row_sha256"] = _self_hash(row, "derived_row_sha256")
    daily_path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest["files"]["forecast_daily.jsonl"] = {
        "sha256": _file_sha256(daily_path),
        "byte_count": daily_path.stat().st_size,
    }
    identity = {
        "plan_sha256": manifest["plan_sha256"],
        "files": manifest["files"],
        "hourly_rows": manifest["row_counts"]["hourly"],
        "daily_rows": manifest["row_counts"]["daily"],
        "coverage_rows": manifest["row_counts"]["coverage"],
    }
    manifest["corpus_id"] = _payload_hash(identity)
    manifest["manifest_sha256"] = _self_hash(manifest, "manifest_sha256")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_corpus_manifest(manifest_path)["corpus_id"] == manifest["corpus_id"]
    with pytest.raises(CorpusVerificationError, match="accepted issue evidence"):
        preflight_pit_forecast_training_corpus(
            manifest_path,
            required_market_ids=["toronto"],
            required_years=[2021],
            required_cutoff_hours=[10],
        )


def test_reader_preserves_fahrenheit_native_values_and_exposes_celsius(tmp_path):
    plan, path = _plan(tmp_path, markets=("nyc",))
    request = plan["requests"][0]
    staging = tmp_path / "staging"
    _stage_valid(path, staging, request)
    manifest_path = materialize_corpus(path, staging, tmp_path / "training")

    resolved = PITForecastTrainingCorpus(manifest_path, "nyc").resolve(
        "2021-05-10",
        10,
    )

    assert resolved["forecast_high"] == 24.0
    assert resolved["profile_rows"][-1]["temp_native"] == 24.0
    assert resolved["profile_rows"][-1]["temp_c"] == pytest.approx(-4.4444)
    assert resolved["provenance"]["temperature_unit"] == "F"


def test_publish_root_must_not_overlap_an_active_archive(tmp_path):
    active = tmp_path / "data" / "forecast_history"
    with pytest.raises(MaterializationBlocked, match="overlaps active"):
        assert_training_only_publish_root(active / "training", [active])


def test_target_year_cannot_enter_the_plan(tmp_path):
    with pytest.raises(PlanValidationError, match="structurally excluded"):
        _plan(tmp_path, year=2026, target_year=2026)
