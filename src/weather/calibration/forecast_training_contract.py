"""Fail-closed preflight for explicit PIT forecast inputs to retraining."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from weather.market.market_registry import all_specs
from weather.model.feature_store import FORECAST_PROFILE_COLUMNS
from weather.schema_registry import schema_version
from weather.sources.forecast_training_corpus import (
    ACTIVE_FORECAST_ARCHIVE_ROOT,
    CONSUMER_DISPOSITIONS,
    EXCLUDED_PROFILE_FEATURES,
    PITForecastTrainingCorpus,
    PROFILE_FEATURE_SOURCE_FIELDS,
    CorpusVerificationError,
    assert_training_only_publish_root,
    load_plan,
    verify_corpus_manifest,
)


PREFLIGHT_SCHEMA_VERSION = schema_version("pit_forecast_training_preflight")
FORECAST_RELATIVE_MARINE_FIELDS = (
    "marine_water_minus_forecast_high",
    "marine_onshore_water_minus_forecast_high",
    "marine_onshore_cooling_potential",
)
REQUIRED_EXCLUDED_CONSUMERS = (
    "forecast_relative_marine_fields",
    "forecast_error_secondary_artifact",
    "late_day_continuation",
    "analog_distance",
)


def _canonical_hash(payload):
    import hashlib

    body = dict(payload)
    body.pop("preflight_sha256", None)
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_row_hash(payload, field):
    body = dict(payload)
    body.pop(field, None)
    return _canonical_hash(body)


def validate_consumer_dispositions(dispositions):
    if dispositions != CONSUMER_DISPOSITIONS:
        raise CorpusVerificationError("consumer dispositions differ from the frozen contract")
    profile = dispositions.get("pooled_forecast_profiles") or {}
    included = set(profile.get("included_feature_columns") or [])
    excluded = set((profile.get("excluded_feature_columns") or {}).keys())
    expected = set(FORECAST_PROFILE_COLUMNS)
    if included & excluded:
        raise CorpusVerificationError("forecast profile fields are both included and excluded")
    if included | excluded != expected:
        missing = sorted(expected - (included | excluded))
        extra = sorted((included | excluded) - expected)
        raise CorpusVerificationError(
            f"forecast profile disposition is incomplete; missing={missing}, extra={extra}"
        )
    if included != set(PROFILE_FEATURE_SOURCE_FIELDS):
        raise CorpusVerificationError("included profile features lack a frozen source-field map")
    if excluded != set(EXCLUDED_PROFILE_FEATURES):
        raise CorpusVerificationError("excluded profile feature receipt drifted")
    for consumer in REQUIRED_EXCLUDED_CONSUMERS:
        row = dispositions.get(consumer) or {}
        if row.get("disposition") != "excluded" or not row.get("reason"):
            raise CorpusVerificationError(f"consumer is not explicitly excluded: {consumer}")
    marine = dispositions["forecast_relative_marine_fields"]
    if tuple(marine.get("fields") or []) != FORECAST_RELATIVE_MARINE_FIELDS:
        raise CorpusVerificationError("forecast-relative marine exclusion is incomplete")
    return True


def preflight_pit_forecast_training_corpus(
    manifest_path,
    *,
    target_year=None,
    required_market_ids=None,
    required_years=None,
    required_cutoff_hours=None,
    active_archive_roots=None,
):
    manifest_path = Path(manifest_path)
    manifest = verify_corpus_manifest(manifest_path)
    assert_training_only_publish_root(
        manifest_path.parent,
        active_archive_roots=active_archive_roots or [ACTIVE_FORECAST_ARCHIVE_ROOT],
    )
    validate_consumer_dispositions(manifest.get("consumer_dispositions") or {})
    plan = load_plan(manifest_path.parent / "plan.json")
    if plan["plan_sha256"] != manifest["plan_sha256"]:
        raise CorpusVerificationError("published plan does not match corpus manifest")

    expected_target_year = int(target_year or manifest["target_year"])
    if int(manifest["target_year"]) != expected_target_year:
        raise CorpusVerificationError("corpus target year differs from retrain target year")
    expected_markets = sorted(
        required_market_ids or [spec.id for spec in all_specs()]
    )
    expected_years = sorted(int(year) for year in (required_years or manifest["years"]))
    expected_cutoffs = sorted(
        int(hour)
        for hour in (required_cutoff_hours or manifest["cutoff_hours_local"])
    )
    if sorted(manifest["market_ids"]) != expected_markets:
        raise CorpusVerificationError("corpus market matrix differs from retrain requirement")
    if sorted(int(year) for year in manifest["years"]) != expected_years:
        raise CorpusVerificationError("corpus year matrix differs from retrain requirement")
    if sorted(int(hour) for hour in manifest["cutoff_hours_local"]) != expected_cutoffs:
        raise CorpusVerificationError("corpus cutoff matrix differs from retrain requirement")
    if expected_target_year in expected_years:
        raise CorpusVerificationError("target year entered the training-year matrix")

    expected_coverage_keys = {
        (request["market_id"], target_date, cutoff_hour)
        for request in plan["requests"]
        for target_date in request["expected_local_dates"]
        for cutoff_hour in expected_cutoffs
    }

    coverage_by_key = {}
    coverage_path = manifest_path.parent / "coverage.jsonl"
    with coverage_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = (
                row.get("market_id"),
                row.get("target_date"),
                int(row.get("cutoff_hour_local")),
            )
            if key in coverage_by_key:
                raise CorpusVerificationError(f"duplicate coverage matrix row: {key}")
            coverage_by_key[key] = row
            if row.get("coverage_row_sha256") != _canonical_row_hash(
                row,
                "coverage_row_sha256",
            ):
                raise CorpusVerificationError(f"coverage row hash mismatch: {key}")
            if int(str(row["target_date"])[:4]) == expected_target_year:
                raise CorpusVerificationError("target-year coverage row entered training corpus")
            if int(row.get("year") or 0) != int(str(row["target_date"])[:4]):
                raise CorpusVerificationError(f"coverage year differs from target date: {key}")
            if row.get("issue_contract") != plan["issue_contract"]["kind"]:
                raise CorpusVerificationError(f"coverage issue contract drifted: {key}")
            if row.get("status") != "complete":
                raise CorpusVerificationError(f"non-complete coverage row: {key}")
            field_status = row.get("field_status") or {}
            if set(field_status) != set(manifest["source_fields"]):
                raise CorpusVerificationError(f"coverage field matrix mismatch: {key}")
            if any(status != "complete" for status in field_status.values()):
                raise CorpusVerificationError(f"incomplete field coverage: {key}")
    expected_coverage_rows = int(
        (manifest.get("coverage") or {}).get("expected_market_date_cutoffs") or -1
    )
    coverage_keys = set(coverage_by_key)
    if len(coverage_keys) != expected_coverage_rows:
        raise CorpusVerificationError(
            f"coverage matrix count mismatch: {len(coverage_keys)} != {expected_coverage_rows}"
        )
    if coverage_keys != expected_coverage_keys:
        missing = sorted(expected_coverage_keys - coverage_keys)[:5]
        extra = sorted(coverage_keys - expected_coverage_keys)[:5]
        raise CorpusVerificationError(
            f"coverage matrix differs from immutable plan; missing={missing}, extra={extra}"
        )

    daily_keys = set()
    daily_path = manifest_path.parent / "forecast_daily.jsonl"
    with daily_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = (
                row.get("market_id"),
                row.get("target_date"),
                int(row.get("cutoff_hour_local")),
            )
            if key in daily_keys:
                raise CorpusVerificationError(f"duplicate daily training row: {key}")
            daily_keys.add(key)
            if row.get("derived_row_sha256") != _canonical_row_hash(
                row,
                "derived_row_sha256",
            ):
                raise CorpusVerificationError(f"daily derived-row hash mismatch: {key}")
            if key not in coverage_keys:
                raise CorpusVerificationError(f"daily row lacks coverage decision: {key}")
            if int(str(row["target_date"])[:4]) == expected_target_year:
                raise CorpusVerificationError("target-year daily row entered training corpus")
            if row.get("issue_evidence_kind") in {None, "", "stitched_continuous_archive"}:
                raise CorpusVerificationError(f"daily row lacks accepted issue evidence: {key}")
            issue_time = row.get("issue_time_utc")
            available_at = row.get("available_at_utc")
            feature_as_of = row.get("feature_as_of_utc")
            if not issue_time or not available_at or not feature_as_of:
                raise CorpusVerificationError(f"daily row lacks PIT timestamps: {key}")
            issue_dt = datetime.fromisoformat(str(issue_time).replace("Z", "+00:00"))
            available_dt = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
            as_of_dt = datetime.fromisoformat(str(feature_as_of).replace("Z", "+00:00"))
            if issue_dt > as_of_dt or available_dt > as_of_dt:
                raise CorpusVerificationError(f"daily row contains forecast lookahead: {key}")
            coverage = coverage_by_key[key]
            for field in ("feature_as_of_utc", "issue_time_utc", "available_at_utc"):
                if row.get(field) != coverage.get(field):
                    raise CorpusVerificationError(
                        f"daily and coverage PIT timestamps differ for {key}: {field}"
                    )
    if daily_keys != coverage_keys:
        raise CorpusVerificationError("daily and coverage key matrices differ")

    expected_profile_dates = {
        (request["market_id"], target_date)
        for request in plan["requests"]
        for target_date in request["expected_local_dates"]
    }
    expected_normalized_fields = {
        binding["normalized_field"]
        for request in plan["requests"]
        for binding in request["variables"]
    }
    profile_times = defaultdict(set)
    hourly_rows = 0
    hourly_path = manifest_path.parent / "forecast_hourly.jsonl"
    with hourly_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            hourly_rows += 1
            key = (row.get("market_id"), row.get("target_date"))
            if key not in expected_profile_dates:
                raise CorpusVerificationError(f"hourly row is outside planned matrix: {key}")
            if row.get("derived_row_sha256") != _canonical_row_hash(
                row,
                "derived_row_sha256",
            ):
                raise CorpusVerificationError(f"hourly derived-row hash mismatch: {key}")
            valid_time = row.get("valid_time_utc")
            if not valid_time or valid_time in profile_times[key]:
                raise CorpusVerificationError(f"duplicate or empty hourly valid time: {key}")
            profile_times[key].add(valid_time)
            if set(row.get("values") or {}) != expected_normalized_fields:
                raise CorpusVerificationError(f"hourly field matrix mismatch: {key}")
            if set(int(hour) for hour in row.get("safe_cutoff_hours_local") or []) != set(
                expected_cutoffs
            ):
                raise CorpusVerificationError(f"hourly cutoff safety matrix mismatch: {key}")
            if row.get("issue_evidence_kind") != plan["issue_contract"]["kind"]:
                raise CorpusVerificationError(f"hourly issue contract drifted: {key}")
    incomplete_profiles = sorted(
        key for key in expected_profile_dates if len(profile_times.get(key) or ()) != 24
    )
    if incomplete_profiles:
        raise CorpusVerificationError(
            f"hourly profile matrix is incomplete: {incomplete_profiles[:5]}"
        )
    if hourly_rows != int((manifest.get("row_counts") or {}).get("hourly") or -1):
        raise CorpusVerificationError("hourly row count differs from manifest")
    if len(daily_keys) != int((manifest.get("row_counts") or {}).get("daily") or -1):
        raise CorpusVerificationError("daily row count differs from manifest")
    if len(coverage_keys) != int((manifest.get("row_counts") or {}).get("coverage") or -1):
        raise CorpusVerificationError("coverage row count differs from manifest")

    receipt = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "status": "PASS",
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": manifest["manifest_sha256"],
        "corpus_id": manifest["corpus_id"],
        "target_year": expected_target_year,
        "target_year_excluded": True,
        "market_ids": expected_markets,
        "years": expected_years,
        "cutoff_hours_local": expected_cutoffs,
        "coverage_rows": len(coverage_keys),
        "hourly_rows": hourly_rows,
        "compatibility_fallback_allowed": False,
        "active_archive_discoverable": False,
        "consumer_dispositions_verified": True,
    }
    receipt["preflight_sha256"] = _canonical_hash(receipt)
    return receipt


def open_pit_forecast_training_corpus(manifest_path, market_id, **preflight_kwargs):
    receipt = preflight_pit_forecast_training_corpus(
        manifest_path,
        **preflight_kwargs,
    )
    return PITForecastTrainingCorpus(manifest_path, market_id), receipt
