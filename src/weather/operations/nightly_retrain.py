"""Nightly retrain -> validate -> immutable candidate orchestration."""

from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import hashlib
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.backtesting.settlement_ledger import DEFAULT_LABELS_CSV, DEFAULT_LEDGER_ROOT
from weather.experiment_contract import (
    ExperimentContractError,
    QUEUE_SCHEMA_VERSION,
    verify_automatic_experiment_queue,
)
from weather.operations.capture_resource_gate import (
    CAPTURE_MODES,
    DEFAULT_MIN_DISK_HEADROOM_DAYS as DEFAULT_CAPTURE_MIN_DISK_HEADROOM_DAYS,
    DEFAULT_MIN_FREE_DISK_BYTES as DEFAULT_CAPTURE_MIN_FREE_DISK_BYTES,
    DEFAULT_MIN_FREE_MEMORY_BYTES as DEFAULT_CAPTURE_MIN_FREE_MEMORY_BYTES,
    NIGHTLY_RETRAIN_WORKLOAD,
    persist_pipeline_admission,
)
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.operations.release_candidate_build import (
    prepare_candidate_outputs,
    run_candidate_release_step,
)
from weather.operations.release_manifest import (
    DEFAULT_RELEASES_ROOT,
    capture_code_identity,
    create_release,
)
from weather.operations.release_promotion import DEFAULT_CANDIDATES_ROOT
from weather.operations.producer_provenance import (
    build_invocation_proof,
    build_lock_proof,
    build_stage_sla,
    producer_release_proof,
)
from weather.paths import REPO_ROOT, data_path
from weather.io import write_json_atomic
from weather.release_contract import (
    CANDIDATE_MODES,
    PRODUCTION_CANDIDATE_MODE,
    PRODUCTION_POINT_IN_TIME_ROLE_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
)
from weather.reporting.scorecards import live_variant_settlement_scorecard
from weather.reporting.serving_gates import production_readiness_gate
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("nightly_retrain")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_report.md"
DEFAULT_DAILY_LEARNING_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning.json"
DEFAULT_DAILY_LEARNING_REPORT = DEFAULT_BACKTEST_ROOT / "daily_learning_report.md"
DEFAULT_EXPERIMENT_QUEUE_RESULTS_OUT = DEFAULT_BACKTEST_ROOT / "experiment_queue_results.json"
DEFAULT_SETTLED_DAY_FRESHNESS_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness.json"
DEFAULT_SETTLED_DAY_FRESHNESS_REPORT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness_report.md"
DEFAULT_TASK_NAME = "WeatherNightlyRetrainValidatePromote"
DEFAULT_SCHEDULE_LOCAL_TIME = "03:30"
DEFAULT_SCHEDULE_TIMEZONE = "America/Toronto"
# Settled-day labels for date D are fetched/finalized by the daily refresh
# chain, which starts at 09:30 local and takes up to ~2h. Before that window
# completes, the freshest day an overnight run can gate on is D-1.
DAILY_REFRESH_FINALIZE_COMPLETE_LOCAL_TIME = "11:30"
DEFAULT_MISSED_RUN_GRACE_MINUTES = 120
DEFAULT_SLA_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_sla_status.json"
DEFAULT_SLA_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_sla_status_report.md"
DEFAULT_STEP_TIMEOUT_SECONDS = 60 * 60


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def backtest_path(args, name):
    return str(Path(args.backtest_root) / name)


def _capture_resource_preflight(args):
    backtest_root = Path(args.backtest_root)
    out = (
        getattr(args, "capture_resource_out", "")
        or backtest_root / "capture_resource_gate.json"
    )
    report = (
        getattr(args, "capture_resource_report", "")
        or backtest_root / "capture_resource_gate.md"
    )
    return persist_pipeline_admission(
        workload=NIGHTLY_RETRAIN_WORKLOAD,
        out=out,
        report=report,
        snapshots_root=args.snapshots_root,
        disk_path=(
            getattr(args, "capture_resource_disk_path", "")
            or args.backtest_root
        ),
        capture_mode=getattr(args, "capture_resource_mode", "live"),
        active_window_start_hour=getattr(
            args,
            "capture_resource_active_window_start_hour",
            None,
        ),
        active_window_end_hour=getattr(
            args,
            "capture_resource_active_window_end_hour",
            None,
        ),
        min_free_memory_bytes=int(
            getattr(
                args,
                "capture_resource_min_free_memory_bytes",
                DEFAULT_CAPTURE_MIN_FREE_MEMORY_BYTES,
            )
        ),
        min_free_disk_bytes=int(
            getattr(
                args,
                "capture_resource_min_free_disk_bytes",
                DEFAULT_CAPTURE_MIN_FREE_DISK_BYTES,
            )
        ),
        daily_disk_growth_bytes=getattr(
            args,
            "capture_resource_daily_disk_growth_bytes",
            None,
        ),
        min_disk_headroom_days=float(
            getattr(
                args,
                "capture_resource_min_disk_headroom_days",
                DEFAULT_CAPTURE_MIN_DISK_HEADROOM_DAYS,
            )
        ),
    )


def _configured_paths(value):
    if value in (None, ""):
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    return [str(path) for path in value if str(path or "").strip()]


def _configured_name_paths(value):
    if isinstance(value, dict):
        return {str(name): Path(path) for name, path in value.items()}
    parsed = {}
    for item in value or []:
        if "=" not in str(item):
            parsed[str(item)] = Path("")
            continue
        name, path = str(item).split("=", 1)
        parsed[name.strip()] = Path(path.strip())
    return parsed


def _captured_input_parity_preflight(args, release_identity):
    backtest_root = Path(args.backtest_root)
    active_pointer = (
        getattr(args, "release_pointer", "")
        or production_readiness_gate.DEFAULT_ACTIVE_RELEASE_POINTER
    )
    releases_root = (
        getattr(args, "releases_root", "")
        or production_readiness_gate.DEFAULT_RELEASES_ROOT
    )
    json_out = (
        getattr(args, "captured_input_parity_out", "")
        or backtest_root / "live_variant_replay_parity.json"
    )
    report_out = (
        getattr(args, "captured_input_parity_report", "")
        or backtest_root / "live_variant_replay_parity.md"
    )
    expected_release_id = str((release_identity or {}).get("release_id") or "")
    expected_manifest_sha256 = str(
        (release_identity or {}).get("release_manifest_sha256")
        or (release_identity or {}).get("manifest_sha256")
        or ""
    )
    try:
        return live_variant_settlement_scorecard.persist_captured_input_replay_parity(
            _configured_paths(getattr(args, "captured_input_parity_served", [])),
            _configured_paths(getattr(args, "captured_input_parity_replay", [])),
            json_out=json_out,
            report_out=report_out,
            protected_paths=[active_pointer],
            protected_roots=[releases_root],
            expected_release_id=expected_release_id,
            expected_manifest_sha256=expected_manifest_sha256,
            max_input_age_hours=float(
                getattr(
                    args,
                    "captured_input_parity_max_age_hours",
                    live_variant_settlement_scorecard.DEFAULT_PARITY_MAX_INPUT_AGE_HOURS,
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 - terminal BLOCK must still persist
        return live_variant_settlement_scorecard.persist_captured_input_replay_parity_failure(
            exc,
            json_out=json_out,
            report_out=report_out,
            protected_paths=[active_pointer],
            protected_roots=[releases_root],
            expected_release_id=expected_release_id,
            expected_manifest_sha256=expected_manifest_sha256,
        )


def _production_readiness_status(args):
    backtest_root = Path(args.backtest_root)
    evidence_overrides = _configured_name_paths(
        getattr(args, "production_readiness_evidence", [])
    )
    evidence_overrides["replay_parity"] = Path(
        getattr(args, "captured_input_parity_out", "")
        or backtest_root / "live_variant_replay_parity.json"
    )
    evidence_overrides["capture_resource_gate"] = Path(
        getattr(args, "capture_resource_out", "")
        or backtest_root / "capture_resource_gate.json"
    )
    gate_kwargs = {
        "pointer_path": (
            getattr(args, "release_pointer", "")
            or production_readiness_gate.DEFAULT_ACTIVE_RELEASE_POINTER
        ),
        "releases_root": (
            getattr(args, "releases_root", "")
            or production_readiness_gate.DEFAULT_RELEASES_ROOT
        ),
        "served_artifact_paths": _configured_name_paths(
            getattr(args, "production_readiness_served_artifact", [])
        ),
        "served_route_path": (
            getattr(args, "production_readiness_served_route", "") or None
        ),
    }
    resolver = getattr(args, "production_readiness_release_resolver", None)
    if resolver is not None:
        gate_kwargs["release_resolver"] = resolver
    payload, json_path, report_path = (
        production_readiness_gate.build_and_write_production_readiness_status(
            backtest_root=backtest_root,
            evidence_paths=evidence_overrides,
            json_out=(
                getattr(args, "production_readiness_out", "")
                or backtest_root / "production_readiness_gate.json"
            ),
            report_out=(
                getattr(args, "production_readiness_report", "")
                or backtest_root / "production_readiness_gate.md"
            ),
            **gate_kwargs,
        )
    )
    attestation = payload.get("read_only_attestation") or {}
    return {
        "status": payload.get("status"),
        "stage": payload.get("stage"),
        "blocker_count": payload.get("blocker_count"),
        "first_blocker": payload.get("first_blocker"),
        "gate_sha256": payload.get("gate_sha256"),
        "json_out": str(json_path),
        "report_out": str(report_path),
        "read_only": attestation.get("pointer_unchanged") is True,
        "pointer_mutated": (
            False
            if attestation.get("pointer_unchanged") is True
            else True
            if attestation.get("pointer_unchanged") is False
            else None
        ),
        "pointer_sha256_before": (attestation.get("pointer_before") or {}).get("sha256"),
        "pointer_sha256_after": (attestation.get("pointer_after") or {}).get("sha256"),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_schedule_time(value):
    try:
        hour, minute = str(value).split(":", 1)
        return datetime_time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError):
        return datetime_time(hour=3, minute=30)


def latest_scheduled_window(
    *,
    now=None,
    schedule_local_time=DEFAULT_SCHEDULE_LOCAL_TIME,
    schedule_timezone=DEFAULT_SCHEDULE_TIMEZONE,
):
    zone = ZoneInfo(schedule_timezone)
    if now is None:
        local_now = datetime.now(timezone.utc).astimezone(zone)
    else:
        local_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        local_now = local_now.astimezone(zone)
    scheduled_time = parse_schedule_time(schedule_local_time)
    due = datetime.combine(local_now.date(), scheduled_time, tzinfo=zone)
    if local_now < due:
        due -= timedelta(days=1)
    return local_now, due


def run_subprocess_step(command, *, timeout_seconds=DEFAULT_STEP_TIMEOUT_SECONDS):
    started = time.time()
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "duration_seconds": round(time.time() - started, 3),
    }


def family_secondary_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.calibration.family_secondary_artifacts",
        "train",
        "--family-unit",
        args.family_unit,
        "--snapshots-root",
        args.snapshots_root,
        "--quality-grades",
        args.quality_grades,
        "--min-trust",
        str(args.min_trust),
        "--min-settled-days",
        str(args.min_settled_days),
        "--out",
        args.family_secondary_out,
        "--report",
        backtest_path(args, "f_family_secondary_artifacts_report.md"),
    ]
    if args.release_candidate_mode == PRODUCTION_CANDIDATE_MODE:
        command.extend(
            [
                "--point-in-time-preselection-lock",
                args.point_in_time_preselection_lock,
                "--artifact-root",
                str(
                    Path(args.family_secondary_out).resolve().parent
                    / "family_secondary_components"
                ),
            ]
        )
    return command


def default_settled_day_target_date(now=None):
    """Most recent settled day whose finalize inputs should exist locally.

    The settled-day freshness repair can only finalize from local WU data;
    the public WU restore for date D runs inside the daily refresh on D+1.
    Gating an overnight run on "yesterday" therefore fails every night, so
    target the day before the last completed daily-refresh finalize window.
    """
    _local_now, finalize_due = latest_scheduled_window(
        now=now,
        schedule_local_time=DAILY_REFRESH_FINALIZE_COMPLETE_LOCAL_TIME,
        schedule_timezone=DEFAULT_SCHEDULE_TIMEZONE,
    )
    return (finalize_due.date() - timedelta(days=1)).isoformat()


def settled_day_freshness_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.operations.settled_day_freshness",
        "repair",
        "--snapshots-root",
        args.snapshots_root,
        "--labels-csv",
        args.labels_csv,
        "--ledger-root",
        args.ledger_root,
        "--json-out",
        args.settled_day_freshness_out,
        "--report-out",
        args.settled_day_freshness_report,
    ]
    if args.settled_day_target_date:
        command += ["--target-date", args.settled_day_target_date]
    elif not args.settled_day_as_of:
        command += ["--target-date", default_settled_day_target_date()]
    if args.settled_day_as_of:
        command += ["--as-of", args.settled_day_as_of]
    if args.settled_day_markets:
        command += ["--markets", args.settled_day_markets]
    if args.skip_settled_day_polymarket_reconciliation:
        command.append("--skip-polymarket-reconciliation")
    return command


def daily_learning_command(args):
    return [
        sys.executable,
        "-m",
        "weather.reporting.daily.daily_learning",
        "--backtest-root",
        args.backtest_root,
        "--snapshots-root",
        args.snapshots_root,
        "--json-out",
        args.daily_learning_out,
        "--report-out",
        args.daily_learning_report,
    ]


def pooled_feature_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.calibration.pooled_feature_model",
        "--family-unit",
        args.family_unit,
        "--objective",
        "band",
        "--holdout-year",
        str(args.holdout_year),
        "--artifact",
        args.pooled_band_artifact,
        "--candidates-root",
        args.candidates_root,
        "--releases-root",
        args.releases_root,
        "--out",
        backtest_path(args, "f_family_pooled_band_model_v0_3_report.md"),
    ]
    if args.allow_legacy_serving_output:
        command.append("--allow-legacy-serving-output")
    if args.release_candidate_mode == PRODUCTION_CANDIDATE_MODE:
        command.extend(
            [
                "--point-in-time-preselection-lock",
                args.point_in_time_preselection_lock,
                "--point-in-time-outer-min-train-dates",
                str(args.point_in_time_outer_min_train_dates),
                "--point-in-time-inner-min-train-dates",
                str(args.point_in_time_inner_min_train_dates),
                "--point-in-time-embargo-days",
                str(args.point_in_time_embargo_days),
                "--point-in-time-step-dates",
                str(args.point_in_time_step_dates),
                "--point-in-time-max-fold-scopes",
                str(args.point_in_time_max_fold_scopes),
                "--point-in-time-private-memory-budget-bytes",
                str(args.point_in_time_private_memory_budget_bytes),
            ]
        )
    return command


def artifact_registry_command(args):
    return [
        sys.executable,
        "-m",
        "weather.artifacts",
        "registry",
        "--out",
        args.artifact_registry,
    ]


def prepare_production_point_in_time_outputs(args, candidate_guard):
    """Resolve production PIT roles inside this run's candidate directory."""

    mode = str(
        getattr(args, "release_candidate_mode", RESEARCH_ONLY_CANDIDATE_MODE)
        or RESEARCH_ONLY_CANDIDATE_MODE
    )
    candidate_guard["candidate_mode"] = mode
    candidate_guard["production_capable"] = mode == PRODUCTION_CANDIDATE_MODE
    if mode != PRODUCTION_CANDIDATE_MODE:
        for role in PRODUCTION_POINT_IN_TIME_ROLE_KINDS:
            setattr(args, role, "")
        candidate_guard["point_in_time_outputs"] = []
        return candidate_guard

    candidate_dir = Path(candidate_guard["candidate_dir"]).resolve()
    work_dir = candidate_dir / "qualification" / "point_in_time" / "work"
    auxiliary_defaults = {
        "point_in_time_preselection_lock": work_dir / "preselection_lock.json",
        "point_in_time_source_materialized_corpus": work_dir / "source_corpus.parquet",
        "point_in_time_source_materialized_manifest": work_dir / "source_manifest.json",
        "point_in_time_replay_manifest": work_dir / "replay_manifest.json",
        "point_in_time_promotion_selection_corpus": (
            work_dir / "promotion_selection_corpus.json"
        ),
    }
    for attribute, path in auxiliary_defaults.items():
        configured = str(getattr(args, attribute, "") or "").strip()
        resolved = Path(configured).resolve() if configured else path
        setattr(args, attribute, str(resolved))
        try:
            resolved.relative_to(candidate_dir)
        except ValueError:
            candidate_guard.setdefault("failures", []).append(
                {
                    "attribute": attribute,
                    "path": str(resolved),
                    "error": "production point-in-time work output must stay inside the candidate directory",
                }
            )
    defaults = {
        "point_in_time_corpus": "qualification/point_in_time/corpus.parquet",
        "point_in_time_materialization_manifest": (
            "qualification/point_in_time/materialization_manifest.json"
        ),
        "point_in_time_validation_plan": (
            "qualification/point_in_time/validation_plan.json"
        ),
        "point_in_time_streaming_evaluation": (
            "qualification/point_in_time/streaming_evaluation.json"
        ),
    }
    rows = []
    failures = list(candidate_guard.get("failures") or ())
    for role, relative in defaults.items():
        configured = str(getattr(args, role, "") or "").strip()
        path = Path(configured).resolve() if configured else candidate_dir / relative
        setattr(args, role, str(path))
        try:
            path.relative_to(candidate_dir)
        except ValueError:
            failures.append(
                {
                    "attribute": role,
                    "path": str(path),
                    "error": "production point-in-time output must stay inside the candidate directory",
                }
            )
        rows.append({"role": role, "path": str(path), "relative_path": relative})
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        failures.append(
            {
                "attribute": "point_in_time_outputs",
                "path": "",
                "error": "production point-in-time output paths must be distinct",
            }
        )
    source_corpus = str(getattr(args, "point_in_time_source_corpus", "") or "").strip()
    source_manifest = str(
        getattr(args, "point_in_time_source_manifest", "") or ""
    ).strip()
    folders = [
        str(path).strip()
        for path in getattr(args, "point_in_time_folder", []) or ()
        if str(path).strip()
    ]
    if bool(source_corpus) != bool(source_manifest):
        failures.append(
            {
                "attribute": "point_in_time_source",
                "path": source_corpus or source_manifest,
                "error": "source corpus and source manifest must be configured together",
            }
        )
    if source_corpus and folders:
        failures.append(
            {
                "attribute": "point_in_time_source",
                "path": source_corpus,
                "error": "source corpus cannot be combined with point-in-time folders",
            }
        )
    if not source_corpus and not folders:
        failures.append(
            {
                "attribute": "point_in_time_source",
                "path": "",
                "error": "production mode requires explicit point-in-time folders or a staged corpus/manifest",
            }
        )
    candidate_guard["point_in_time_outputs"] = rows
    candidate_guard["failures"] = failures
    if failures:
        candidate_guard["status"] = "BLOCK"
        candidate_guard["release_eligible"] = False
    return candidate_guard


def point_in_time_preselection_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.validation.point_in_time_evaluation",
        "prelock-production",
        "--lock-out",
        args.point_in_time_preselection_lock,
        "--replay-manifest-out",
        args.point_in_time_replay_manifest,
        "--quality-grades",
        args.quality_grades,
        "--snapshots-root",
        args.snapshots_root,
        "--max-market-days",
        str(args.point_in_time_max_market_days),
        "--max-rows-per-market-day",
        str(args.point_in_time_max_rows_per_market_day),
        "--batch-rows",
        str(args.point_in_time_batch_rows),
    ]
    archive_root = str(getattr(args, "point_in_time_archive_root", "") or "").strip()
    if archive_root:
        command.extend(["--archive-root", archive_root])
    as_of = str(getattr(args, "point_in_time_as_of", "") or "").strip()
    if as_of:
        command.extend(["--as-of", as_of])
    window_end = str(getattr(args, "point_in_time_window_end", "") or "").strip()
    if window_end:
        command.extend(["--window-end", window_end])
    source_replay_manifest = str(
        getattr(args, "point_in_time_source_replay_manifest", "") or ""
    ).strip()
    if source_replay_manifest:
        command.extend(["--source-replay-manifest", source_replay_manifest])
    source_corpus = str(getattr(args, "point_in_time_source_corpus", "") or "").strip()
    if source_corpus:
        command.extend(
            [
                "--source-corpus",
                source_corpus,
                "--source-manifest",
                str(args.point_in_time_source_manifest),
            ]
        )
    else:
        command.extend(
            [
                "--source-corpus-out",
                args.point_in_time_source_materialized_corpus,
                "--source-manifest-out",
                args.point_in_time_source_materialized_manifest,
            ]
        )
        for folder in getattr(args, "point_in_time_folder", []) or ():
            command.extend(["--folder", str(folder)])
    return command


def point_in_time_qualification_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.validation.point_in_time_evaluation",
        "qualify-production",
        "--candidate-id",
        args.candidate_id,
        "--release-id",
        args.candidate_id,
        "--snapshots-root",
        args.snapshots_root,
        "--model-artifact",
        args.pooled_band_artifact,
        "--calibration-artifact",
        args.family_secondary_out,
        "--routing-artifact",
        args.promotion_out,
        "--preselection-lock",
        args.point_in_time_preselection_lock,
        "--replay-manifest",
        args.point_in_time_replay_manifest,
        "--corpus-out",
        args.point_in_time_corpus,
        "--manifest-out",
        args.point_in_time_materialization_manifest,
        "--validation-plan-out",
        args.point_in_time_validation_plan,
        "--evaluation-out",
        args.point_in_time_streaming_evaluation,
        "--max-market-days",
        str(args.point_in_time_max_market_days),
        "--max-rows-per-market-day",
        str(args.point_in_time_max_rows_per_market_day),
        "--batch-rows",
        str(args.point_in_time_batch_rows),
        "--outer-min-train-dates",
        str(args.point_in_time_outer_min_train_dates),
        "--inner-min-train-dates",
        str(args.point_in_time_inner_min_train_dates),
        "--embargo-days",
        str(args.point_in_time_embargo_days),
        "--step-dates",
        str(args.point_in_time_step_dates),
        "--bootstrap-iterations",
        str(args.point_in_time_bootstrap_iterations),
        "--private-memory-budget-bytes",
        str(args.point_in_time_private_memory_budget_bytes),
        "--max-fold-scopes",
        str(args.point_in_time_max_fold_scopes),
    ]
    archive_root = str(getattr(args, "point_in_time_archive_root", "") or "").strip()
    if archive_root:
        command.extend(["--archive-root", archive_root])
    as_of = str(getattr(args, "point_in_time_as_of", "") or "").strip()
    if as_of:
        command.extend(["--as-of", as_of])
    window_end = str(getattr(args, "point_in_time_window_end", "") or "").strip()
    if window_end:
        command.extend(["--window-end", window_end])
    source_corpus = str(getattr(args, "point_in_time_source_corpus", "") or "").strip()
    if source_corpus:
        command.extend(
            [
                "--source-corpus",
                source_corpus,
                "--source-manifest",
                str(args.point_in_time_source_manifest),
            ]
        )
    else:
        command.extend(
            [
                "--source-corpus",
                args.point_in_time_source_materialized_corpus,
                "--source-manifest",
                args.point_in_time_source_materialized_manifest,
            ]
        )
    return command


def promotion_refresh_command(args, *, folders=()):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.promotion.promotion_refresh",
        "--family-unit",
        args.family_unit,
        "--snapshots-root",
        args.snapshots_root,
        "--quality-grades",
        args.quality_grades,
        "--artifact",
        args.pooled_band_artifact,
        "--out",
        args.promotion_out,
        "--report",
        args.promotion_report,
        "--long-job-state",
        str(args.long_job_state),
        "--long-job-lock",
        str(args.long_job_lock),
        "--long-job-priority",
        args.long_job_priority,
    ]
    if args.include_reconstructed:
        command.append("--include-reconstructed")
    if args.allow_unsettled:
        command.append("--allow-unsettled")
    if args.require_exact_identity:
        command.append("--require-exact-identity")
    if args.require_all_markets:
        command.append("--require-all-markets")
    if args.no_baseline:
        command.append("--no-baseline")
    command.extend(str(folder) for folder in folders)
    return command


def _canonical_sha256(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path, *, chunk_bytes=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def production_promotion_selection(args):
    """Resolve the exact unlocked promotion folders from the prelock manifest."""

    from weather.calibration.pooled_training import (
        load_production_point_in_time_preselection,
    )
    from weather.reporting.promotion.promotion_corpus import (
        folders_from_manifest,
        load_manifest,
    )

    preselection = load_production_point_in_time_preselection(
        args.point_in_time_preselection_lock
    )
    replay_manifest_path = Path(args.point_in_time_replay_manifest).resolve()
    manifest = load_manifest(replay_manifest_path)
    source = preselection.get("source") or {}
    replay_manifest_sha256 = _sha256_file(replay_manifest_path)
    replay_corpus_hash = str(manifest.get("corpus_hash") or "")
    if (
        replay_manifest_sha256 != source.get("replay_manifest_sha256")
        or replay_corpus_hash != source.get("replay_corpus_hash")
    ):
        raise ValueError(
            "production promotion replay manifest differs from the prelocked source"
        )
    entries = list(manifest.get("entries") or ())
    folders = list(folders_from_manifest(manifest, args.snapshots_root))
    if not entries or len(entries) != len(folders):
        raise ValueError("production promotion replay manifest is incomplete")
    locked = set(preselection["window_lock"]["target_dates"])
    universe_dates = set(preselection["selection_universe"]["fleet_dates"])
    selected = []
    inventory = []
    manifest_dates = set()
    for entry, folder in zip(entries, folders):
        target_date = str(entry.get("target_date") or "")
        manifest_dates.add(target_date)
        if target_date in locked:
            continue
        selected.append(Path(folder).resolve())
        inventory.append(
            {
                "folder": str(Path(folder).resolve()),
                "event_slug": str(entry.get("event_slug") or ""),
                "target_date": target_date,
                "market_id": str(entry.get("market_id") or ""),
            }
        )
    expected_dates = universe_dates - locked
    selected_dates = {row["target_date"] for row in inventory}
    if (
        manifest_dates != universe_dates
        or selected_dates != expected_dates
        or not selected
        or len(selected) > int(args.point_in_time_max_market_days)
    ):
        raise ValueError(
            "production promotion population differs from the bounded unlocked preselection"
        )
    inventory.sort(
        key=lambda row: (row["target_date"], row["market_id"], row["event_slug"])
    )
    return preselection, selected, inventory


def bind_production_promotion_selection(args, preselection, inventory):
    """Attach a self-hashed no-reuse proof to the just-written routing artifact."""

    path = Path(args.promotion_out).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    source_inventory = {
        "entries": inventory,
        "entry_count": len(inventory),
        "replay_manifest_sha256": preselection["source"][
            "replay_manifest_sha256"
        ],
        "replay_corpus_hash": preselection["source"]["replay_corpus_hash"],
    }
    source_inventory["sha256"] = _canonical_sha256(source_inventory)
    binding = {
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": preselection["window_lock"]["window_lock_id"],
        "locked_dates": list(preselection["window_lock"]["target_dates"]),
        "used_for_selection": False,
        "source_folder_date_inventory_sha256": source_inventory["sha256"],
        "source_inventory": source_inventory,
    }
    binding["binding_sha256"] = _canonical_sha256(binding)
    payload["point_in_time_selection_binding"] = binding
    write_json_atomic(path, payload, trailing_newline=True)
    return binding


def shadow_ab_monitor_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.candidate_lifecycle.shadow_ab_monitor",
        "--promotion-refresh",
        args.promotion_out,
        "--candidate-replay",
        str(Path(args.backtest_root) / "pooled_candidate_replay_latest.json"),
        "--json-out",
        args.shadow_ab_out,
        "--report-out",
        args.shadow_ab_report,
        "--current-tol",
        str(args.ab_current_tol),
        "--market-tol",
        str(args.ab_market_tol),
    ]
    if args.fail_on_shadow_ab_alert:
        command.append("--fail-on-alert")
    return command


def planned_steps(args):
    steps = []
    if not args.skip_settled_day_freshness:
        steps.append(("settled_day_freshness", settled_day_freshness_command(args)))
    if not args.skip_daily_learning:
        steps.append(("daily_learning", daily_learning_command(args)))
    if not args.skip_experiment_queue:
        steps.append(("experiment_queue", []))
    if args.release_candidate_mode == PRODUCTION_CANDIDATE_MODE:
        steps.append(
            (
                "point_in_time_preselection_lock",
                point_in_time_preselection_command(args),
            )
        )
    if not args.skip_family_secondary:
        steps.append(("family_secondary_artifacts", family_secondary_command(args)))
    if not args.skip_pooled_feature:
        steps.append(("pooled_feature_model_band", pooled_feature_command(args)))
    if not args.skip_artifact_registry:
        steps.append(("artifact_registry", artifact_registry_command(args)))
    if not args.skip_promotion_refresh:
        steps.append(("promotion_refresh", promotion_refresh_command(args)))
    if args.release_candidate_mode == PRODUCTION_CANDIDATE_MODE:
        steps.append(
            (
                "point_in_time_production_qualification",
                point_in_time_qualification_command(args),
            )
        )
    if not args.skip_shadow_ab_monitor:
        steps.append(("shadow_ab_monitor", shadow_ab_monitor_command(args)))
    return steps


def step_timeout_for(name, args):
    """Per-step timeout: validation replay outgrew the flat default.

    The retrain's promotion_refresh replays the freshly trained candidate
    over the FULL promotion corpus (~4h at 261 market-days on 2026-07-07);
    the flat 1h step timeout killed it mid-replay after an otherwise
    successful retrain night. Replay-scale steps get their own budget.
    """
    if name == "promotion_refresh":
        return int(getattr(args, "promotion_step_timeout_seconds", 0) or 6 * 60 * 60)
    return args.step_timeout_seconds


def run_step(name, command, args, runner):
    started = time.time()
    step = {
        "name": name,
        "command": command,
        "started_at_utc": utc_iso(),
        "finished_at_utc": None,
        "duration_seconds": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    try:
        result = runner(command, timeout_seconds=step_timeout_for(name, args))
        step.update(result or {})
        step["returncode"] = int(step.get("returncode") or 0)
        step["status"] = "ok" if step["returncode"] == 0 else "error"
    except Exception as exc:  # noqa: BLE001
        step["status"] = "error"
        step["returncode"] = -1
        step["stderr"] = f"{type(exc).__name__}: {exc}"
        step["traceback"] = traceback.format_exc()
    step["finished_at_utc"] = utc_iso()
    step["duration_seconds"] = round(time.time() - started, 3)
    return step


def promotion_summary(path):
    payload = read_json(path)
    decisions = payload.get("decisions") or {}
    readiness = payload.get("readiness") or {}
    promote = decisions.get("promote_markets") or []
    shadow = decisions.get("shadow_markets") or []
    blocked = decisions.get("blocked_markets") or []
    if not payload:
        verdict = "missing"
    elif blocked:
        verdict = "blocked"
    elif promote:
        verdict = "promote_ready"
    else:
        verdict = "shadow"
    return {
        "path": str(path),
        "exists": bool(payload),
        "verdict": verdict,
        "readiness_status": readiness.get("status"),
        "promote_markets": promote,
        "shadow_markets": shadow,
        "blocked_markets": blocked,
        "market_count": len((decisions.get("markets") or [])),
        "serving_gauntlet_verdict": (payload.get("serving_gauntlet") or {}).get("verdict"),
    }


def promotion_not_run_summary(path, reason):
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "verdict": "not_run",
        "reason": reason,
        "readiness_status": None,
        "promote_markets": [],
        "shadow_markets": [],
        "blocked_markets": [],
        "market_count": 0,
        "serving_gauntlet_verdict": None,
    }


def daily_learning_summary(path):
    payload = read_json(path)
    summary = payload.get("summary") or {}
    retrain_plan = payload.get("retrain_plan") or {}
    experiment_queue = payload.get("experiment_queue") or {}
    retrain_recommendation = retrain_plan.get("retrain_recommendation") or {}
    broad_slo = retrain_plan.get("broad_live_forward_slo") or (
        ((payload.get("scorecard") or {}).get("fleet") or {}).get("live_forward_slo") or {}
    )
    variant_learning_gate = retrain_plan.get("variant_learning_gate") or (
        (payload.get("scorecard") or {}).get("variant_learning_gate") or {}
    )
    blockers = [
        {
            "priority": row.get("priority"),
            "category": row.get("category"),
            "source": row.get("source"),
            "signal": row.get("signal"),
            "action": row.get("action"),
        }
        for row in payload.get("learnings") or []
        if row.get("blocker")
    ]
    input_gate = payload.get("input_gate") or {}
    return {
        "path": str(path),
        "exists": bool(payload),
        "status": payload.get("status") if payload else "missing",
        "run_date": payload.get("run_date"),
        "input_gate_status": input_gate.get("status"),
        "input_consistency_status": (input_gate.get("consistency") or {}).get("status"),
        "input_freshness_status": (input_gate.get("freshness") or {}).get("status"),
        "learning_count": summary.get("learning_count"),
        "blocker_count": summary.get("blocker_count"),
        "high_priority_learning_count": summary.get("high_priority_learning_count"),
        "retrain_input_count": summary.get("retrain_input_count"),
        "experiment_queue_count": (experiment_queue.get("summary") or {}).get("queue_count"),
        "eligible_experiment_count": (experiment_queue.get("summary") or {}).get("eligible_count"),
        "retrain_recommended": retrain_recommendation.get("recommended"),
        "retrain_recommendation": retrain_recommendation,
        "experiment_queue": experiment_queue,
        "training_ready": retrain_plan.get("training_ready"),
        "promotion_ready": retrain_plan.get("promotion_ready"),
        "broad_live_forward_slo": broad_slo,
        "variant_learning_gate": variant_learning_gate,
        "blockers": blockers,
    }


def execute_experiment_queue(args, runner=run_subprocess_step):
    del runner  # Isolated execution is a separate, still-open Phase 6 gate.
    learning = read_json(args.daily_learning_out)
    queue = learning.get("experiment_queue") or {}
    started = utc_iso()
    raw_items = queue.get("items")
    legacy_empty = queue.get("schema_version") != QUEUE_SCHEMA_VERSION and not raw_items
    contract_error = None
    verified_queue = None
    if not legacy_empty:
        try:
            verified_queue = verify_automatic_experiment_queue(
                queue,
                repo_root=REPO_ROOT,
            )
        except (ExperimentContractError, OSError, TypeError, ValueError) as exc:
            contract_error = f"{type(exc).__name__}: {exc}"
    if contract_error is not None:
        status = "BLOCK"
        reason = "experiment_queue_contract_invalid"
        items = []
    elif legacy_empty:
        status = "OK"
        reason = "legacy_empty_queue_noop"
        items = []
    else:
        items = [
            item
            for item in verified_queue.get("items") or []
            if item.get("eligible") is True
        ][: max(0, int(args.experiment_queue_top_n))]
        status = "DEFERRED" if items else "OK"
        reason = (
            "isolated_experiment_executor_not_implemented"
            if items
            else "no_materialized_eligible_experiments"
        )
    payload = {
        "schema_version": schema_version("experiment_queue_results"),
        "generated_at_utc": utc_iso(),
        "started_at_utc": started,
        "status": status,
        "reason": reason,
        "contract_error": contract_error,
        "daily_learning": str(args.daily_learning_out),
        "queue_status": queue.get("status"),
        "queue_count": (queue.get("summary") or {}).get("queue_count"),
        "eligible_count": len(items),
        "deferred_count": len(items),
        "deferred_queue_ids": [item.get("queue_id") for item in items],
        "executed_count": 0,
        "recorded_count": 0,
        "failed_count": 0,
        "top_n": int(args.experiment_queue_top_n),
        "results": [],
    }
    out = write_json(args.experiment_queue_results_out, payload)
    return payload, out


def run_experiment_queue_step(args, runner):
    started = time.time()
    step = {
        "name": "experiment_queue",
        "command": ["internal", "execute_experiment_queue"],
        "started_at_utc": utc_iso(),
        "finished_at_utc": None,
        "duration_seconds": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    try:
        payload, out = execute_experiment_queue(args, runner=runner)
        if payload.get("status") == "BLOCK":
            step["returncode"] = 2
            step["status"] = "blocked"
        elif payload.get("status") == "DEFERRED":
            step["returncode"] = 0
            step["status"] = "deferred"
        else:
            step["returncode"] = 0 if payload.get("status") != "ERROR" else 1
            step["status"] = "ok" if step["returncode"] == 0 else "error"
        step["stdout"] = f"experiment_queue_results={out}"
        step["result"] = {
            "status": payload.get("status"),
            "out": str(out),
            "queue_count": payload.get("queue_count"),
            "eligible_count": payload.get("eligible_count"),
            "deferred_count": payload.get("deferred_count"),
            "executed_count": payload.get("executed_count"),
            "recorded_count": payload.get("recorded_count"),
            "failed_count": payload.get("failed_count"),
            "reason": payload.get("reason"),
            "contract_error": payload.get("contract_error"),
            "hard_stop_pipeline": payload.get("status") == "BLOCK",
        }
    except Exception as exc:  # noqa: BLE001
        step["status"] = "error"
        step["returncode"] = -1
        step["stderr"] = f"{type(exc).__name__}: {exc}"
        step["traceback"] = traceback.format_exc()
    step["finished_at_utc"] = utc_iso()
    step["duration_seconds"] = round(time.time() - started, 3)
    return step


def daily_learning_input_integrity(daily_learning):
    """Whether daily_learning's own inputs were consistent and fresh.

    The nightly run must stop on garbage-in (inconsistent or stale critical
    inputs) but NOT on the policy/skill P0s that keep the headline BLOCKED —
    the experiment queue exists to repair exactly those gates, so gating the
    queue on the headline re-creates the settled-day-barrier circularity one
    level up (queue starved June 24 -> July 5 while headline stayed BLOCKED
    on predawn skill gates).
    """
    if not (daily_learning or {}).get("exists"):
        # Missing artifact was never a blocker for this flag; downstream steps
        # (experiment queue, retrain gates) each tolerate missing inputs.
        return True, "daily_learning_missing"
    consistency = str(daily_learning.get("input_consistency_status") or "").upper()
    freshness = str(daily_learning.get("input_freshness_status") or "").upper()
    if consistency == "FAIL":
        return False, "input_consistency_fail"
    if freshness == "FAIL":
        return False, "input_freshness_fail"
    return True, "input_gate_ok"


def _should_skip_expensive_retrain(args, daily_learning):
    if not getattr(args, "skip_when_no_retrain_recommendation", False):
        return False
    recommendation = (daily_learning or {}).get("retrain_recommendation") or {}
    if recommendation.get("scheduled_fallback"):
        return False
    return recommendation.get("recommended") is False


def settled_day_freshness_summary(path):
    payload = read_json(path)
    summary = payload.get("summary") or {}
    first_missing = next(
        (
            row
            for row in payload.get("markets") or []
            if not row.get("canonical_complete")
        ),
        {},
    )
    return {
        "path": str(path),
        "exists": bool(payload),
        "status": payload.get("status") if payload else "missing",
        "target_date": payload.get("target_date"),
        "expected_market_count": summary.get("expected_market_count"),
        "complete_market_count": summary.get("complete_market_count"),
        "incomplete_market_count": summary.get("incomplete_market_count"),
        "needs_finalization_count": summary.get("needs_finalization_count"),
        "needs_replay_status_repair_count": summary.get("needs_replay_status_repair_count"),
        "missing_label_count": summary.get("missing_label_count"),
        "missing_ledger_count": summary.get("missing_ledger_count"),
        "missing_settlement_json_count": summary.get("missing_settlement_json_count"),
        "missing_replay_status_count": summary.get("missing_replay_status_count"),
        "missing_replay_inputs_count": summary.get("missing_replay_inputs_count"),
        "missing_source_status_count": summary.get("missing_source_status_count"),
        "missing_tape_count": summary.get("missing_tape_count"),
        "source_lag_warning_count": summary.get("source_lag_warning_count"),
        "repair_command": payload.get("repair_command"),
        "replay_status_repair_command": payload.get("replay_status_repair_command"),
        "first_missing": {
            "market_id": first_missing.get("market_id"),
            "event_slug": first_missing.get("event_slug"),
            "missing_requirements": first_missing.get("missing_requirements") or [],
        },
    }


def nightly_run_sla_status(
    *,
    status_path=DEFAULT_STATUS_OUT,
    status_payload=None,
    task_name=DEFAULT_TASK_NAME,
    task_status=None,
    now=None,
    schedule_local_time=DEFAULT_SCHEDULE_LOCAL_TIME,
    schedule_timezone=DEFAULT_SCHEDULE_TIMEZONE,
    missed_run_grace_minutes=DEFAULT_MISSED_RUN_GRACE_MINUTES,
):
    status_path = Path(status_path)
    status_payload = status_payload if status_payload is not None else read_json(status_path)
    local_now, latest_due = latest_scheduled_window(
        now=now,
        schedule_local_time=schedule_local_time,
        schedule_timezone=schedule_timezone,
    )
    grace_deadline = latest_due + timedelta(minutes=float(missed_run_grace_minutes))
    run_generated = parse_datetime(
        (status_payload or {}).get("finished_at_utc")
        or (status_payload or {}).get("generated_at_utc")
        or (status_payload or {}).get("started_at_utc")
    )
    fresh = bool(run_generated and run_generated.astimezone(latest_due.tzinfo) >= latest_due)
    age_hours = None
    if run_generated:
        age_hours = round(
            (
                local_now.astimezone(timezone.utc)
                - run_generated.astimezone(timezone.utc)
            ).total_seconds() / 3600.0,
            3,
        )

    run_status = (status_payload or {}).get("status") if status_payload else "missing"
    learning = (status_payload or {}).get("daily_learning") or {}
    blockers = learning.get("blockers") or []
    first_blocker = blockers[0] if blockers else {}
    broad_slo = learning.get("broad_live_forward_slo") or {}
    broad_first_blocker = broad_slo.get("first_blocker") or next(
        iter(broad_slo.get("recovery_checklist") or []),
        {},
    )
    task_registered = None if task_status is None else bool(task_status.get("Registered"))
    alerts = []
    if task_registered is False:
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_task",
            "message": f"{task_name} is not registered",
        })
    if local_now >= grace_deadline and not fresh:
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_missed_run",
            "message": f"no fresh nightly status exists after the {schedule_local_time} scheduled window",
        })
    if fresh and run_status == "error":
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_error",
            "message": "latest nightly self-improvement run ended in error",
        })

    if any(row.get("severity") == "critical" for row in alerts):
        state = "CRITICAL"
    elif fresh and run_status == "blocked":
        state = "BLOCKED"
    elif not fresh:
        state = "PENDING"
    elif fresh and run_status in {"promote_ready", "shadow", "dry_run"}:
        state = "OK"
    else:
        state = str(run_status or "unknown").upper()

    return {
        "schema_version": "nightly_retrain_sla_status_v0.1",
        "generated_at_utc": utc_iso(),
        "state": state,
        "task_name": task_name,
        "task_registered": task_registered,
        "task_state": (task_status or {}).get("State"),
        "task_last_run": (task_status or {}).get("Last Run"),
        "task_next_run": (task_status or {}).get("Next Run"),
        "task_result": (task_status or {}).get("Result"),
        "status_path": str(status_path),
        "status_exists": bool(status_payload),
        "run_status": run_status,
        "run_generated_at_utc": run_generated.astimezone(timezone.utc).isoformat() if run_generated else None,
        "run_age_hours": age_hours,
        "fresh_for_latest_window": fresh,
        "schedule_local_time": schedule_local_time,
        "schedule_timezone": schedule_timezone,
        "latest_due_local": latest_due.isoformat(),
        "grace_deadline_local": grace_deadline.isoformat(),
        "missed_run_grace_minutes": missed_run_grace_minutes,
        "daily_learning_status": learning.get("status"),
        "daily_learning_blocker_count": learning.get("blocker_count"),
        "p0_gate": first_blocker.get("signal") or (alerts[0]["message"] if alerts else None),
        "p0_action": first_blocker.get("action"),
        "broad_live_forward_slo_status": broad_slo.get("status"),
        "broad_live_forward_slo_counts": broad_slo.get("counts_toward_live_forward_gate"),
        "broad_live_forward_first_blocker": broad_first_blocker,
        "blockers": blockers,
        "alerts": alerts,
        "remediation_command": (
            "python -m weather.operations.nightly_retrain run "
            "--fail-on-daily-learning-blocker"
        ),
    }


def pipeline_status(steps, promotion, daily_learning=None, *, fail_on_daily_learning_blocker=False):
    if any(step.get("status") == "error" for step in steps):
        return "error"
    if any(step.get("name") == "retrain_recommendation_gate" and step.get("status") == "skipped" for step in steps):
        return "skipped_no_retrain_recommendation"
    # Only an input-integrity abort marks the run blocked; a headline-BLOCKED
    # daily_learning (policy/skill P0s) no longer stops the queue or the
    # retrain, so it must not mask what the run actually did.
    if any(
        step.get("name") == "daily_learning_input_gate" and step.get("status") == "blocked"
        for step in steps
    ):
        return "blocked"
    verdict = promotion.get("verdict")
    if verdict in {"promote_ready", "shadow", "blocked"}:
        return verdict
    return "blocked"


def _markdown_cell(value):
    if value in (None, ""):
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return lines


def render_report(payload):
    promotion = payload.get("promotion") or {}
    learning = payload.get("daily_learning") or {}
    settled = payload.get("settled_day_freshness") or {}
    sla = payload.get("nightly_sla") or {}
    config = payload.get("config") or {}
    candidate_guard = config.get("candidate_output_guard") or {}
    candidate_release = payload.get("candidate_release") or {}
    admission = payload.get("capture_resource_admission") or {}
    parity = payload.get("captured_input_replay_parity") or {}
    readiness = payload.get("production_readiness") or {}
    lines = [
        "# Nightly Retrain Validate Candidate Release",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Nightly SLA: `{sla.get('state') or '-'}`",
        f"Settled-day freshness: `{settled.get('status') or '-'}`",
        f"Promotion verdict: `{promotion.get('verdict') or '-'}`",
        f"Daily learning: `{learning.get('status') or '-'}`",
        f"Capture-resource decision: `{admission.get('decision') or '-'}`",
        f"Capture-resource workload: `{admission.get('workload') or '-'}`",
        f"Captured-input replay parity: `{parity.get('status') or '-'}`",
        f"Production readiness: `{readiness.get('status') or '-'}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Return Code | Duration |",
        "| :--- | :--- | ---: | ---: |",
    ]
    for step in payload.get("steps") or []:
        lines.append(
            f"| {step.get('name')} | {step.get('status')} | "
            f"{step.get('returncode')} | {step.get('duration_seconds')} |"
        )
    lines += [
        "",
        "## Promotion",
        "",
        f"- Reason: {promotion.get('reason') or '-'}",
        f"- Promote-ready markets: {', '.join(promotion.get('promote_markets') or []) or '-'}",
        f"- Shadow markets: {', '.join(promotion.get('shadow_markets') or []) or '-'}",
        f"- Blocked markets: {', '.join(promotion.get('blocked_markets') or []) or '-'}",
        f"- Serving gauntlet: {promotion.get('serving_gauntlet_verdict') or '-'}",
        "",
        "## Candidate Release",
        "",
        f"- Output guard: {candidate_guard.get('status') or '-'}",
        f"- Candidate ID: {candidate_guard.get('candidate_id') or '-'}",
        f"- Candidate directory: {candidate_guard.get('candidate_dir') or '-'}",
        f"- Release status: {candidate_release.get('status') or '-'}",
        f"- Release ID: {candidate_release.get('release_id') or '-'}",
        f"- Manifest: {candidate_release.get('manifest_path') or '-'}",
        f"- Activation: {candidate_release.get('activation') or 'NONE'}",
        f"- Active pointer unchanged: {candidate_release.get('active_pointer_unchanged') if candidate_release.get('active_pointer_unchanged') is not None else '-'}",
        f"- Legacy compatibility enabled: {candidate_guard.get('compatibility_flag_enabled', False)}",
        "",
        "## Settled-Day Freshness",
        "",
        f"- Target date: {settled.get('target_date') or '-'}",
        f"- Expected markets: {settled.get('expected_market_count') if settled.get('expected_market_count') is not None else '-'}",
        f"- Complete markets: {settled.get('complete_market_count') if settled.get('complete_market_count') is not None else '-'}",
        f"- Incomplete markets: {settled.get('incomplete_market_count') if settled.get('incomplete_market_count') is not None else '-'}",
        f"- Needs finalization: {settled.get('needs_finalization_count') if settled.get('needs_finalization_count') is not None else '-'}",
        f"- Needs replay-status repair: {settled.get('needs_replay_status_repair_count') if settled.get('needs_replay_status_repair_count') is not None else '-'}",
        f"- Source-lag warnings: {settled.get('source_lag_warning_count') if settled.get('source_lag_warning_count') is not None else '-'}",
        f"- Report: {payload.get('config', {}).get('settled_day_freshness_report') or '-'}",
        f"- Repair command: {settled.get('repair_command') or '-'}",
        f"- Replay-status repair command: {settled.get('replay_status_repair_command') or '-'}",
        "",
        "### First Missing Market",
        "",
    ]
    first_missing = settled.get("first_missing") or {}
    lines += _markdown_table(
        ["Market", "Event", "Missing"],
        [[
            first_missing.get("market_id") or "-",
            first_missing.get("event_slug") or "-",
            ", ".join(first_missing.get("missing_requirements") or []) or "-",
        ]],
    )
    lines += [
        "",
        "## Daily Log Learning",
        "",
        f"- Run date: {learning.get('run_date') or '-'}",
        f"- Learnings: {learning.get('learning_count') if learning.get('learning_count') is not None else '-'}",
        f"- High-priority learnings: {learning.get('high_priority_learning_count') if learning.get('high_priority_learning_count') is not None else '-'}",
        f"- Blockers: {learning.get('blocker_count') if learning.get('blocker_count') is not None else '-'}",
        f"- Training ready: {learning.get('training_ready') if learning.get('training_ready') is not None else '-'}",
        f"- Promotion ready: {learning.get('promotion_ready') if learning.get('promotion_ready') is not None else '-'}",
        f"- Report: {payload.get('config', {}).get('daily_learning_report') or '-'}",
        "",
    ]
    blockers = learning.get("blockers") or []
    if blockers:
        lines += [
            "### Daily-Learning Blockers",
            "",
        ]
        lines += _markdown_table(
            ["Priority", "Category", "Source", "Signal", "Action"],
            [
                [
                    row.get("priority"),
                    row.get("category"),
                    row.get("source"),
                    row.get("signal"),
                    row.get("action"),
                ]
                for row in blockers[:10]
            ],
        )
        lines.append("")
    broad_slo = learning.get("broad_live_forward_slo") or {}
    if broad_slo:
        first = broad_slo.get("first_blocker") or next(
            iter(broad_slo.get("recovery_checklist") or []),
            {},
        )
        lines += [
            "## Broad Live-Forward SLO",
            "",
        ]
        lines += _markdown_table(
            ["Field", "Value"],
            [
                ["Status", broad_slo.get("status") or "-"],
                ["Counts toward live-forward gate", broad_slo.get("counts_toward_live_forward_gate")],
                ["Reason", broad_slo.get("reason") or "-"],
                ["First market", first.get("market_id") or "-"],
                ["First component", first.get("component") or "-"],
                ["First gate", first.get("gate") or "-"],
                ["Owner", first.get("owner") or "-"],
                ["Repair command", first.get("repair_command") or "-"],
                ["Rerun command", broad_slo.get("rerun_command") or first.get("verification_command") or "-"],
            ],
        )
        recovery_rows = [
            [
                row.get("market_id"),
                row.get("component"),
                row.get("gate"),
                row.get("owner"),
                row.get("repair_command"),
            ]
            for row in broad_slo.get("recovery_checklist") or []
        ]
        if recovery_rows:
            lines += ["", "### Recovery Checklist", ""]
            lines += _markdown_table(
                ["Market", "Component", "Gate", "Owner", "Repair Command"],
                recovery_rows[:20],
            )
            lines.append("")
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def render_sla_report(payload):
    lines = [
        "# Nightly Retrain SLA Status",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"State: **{payload.get('state')}**",
        f"Task: `{payload.get('task_name')}`",
        f"Status file: `{payload.get('status_path')}`",
        f"Run status: `{payload.get('run_status')}`",
        f"Run generated: `{payload.get('run_generated_at_utc') or '-'}`",
        f"Latest due: `{payload.get('latest_due_local')}`",
        f"Grace deadline: `{payload.get('grace_deadline_local')}`",
        f"P0 gate: `{payload.get('p0_gate') or '-'}`",
        f"Action: `{payload.get('p0_action') or payload.get('remediation_command')}`",
        "",
        "## Alerts",
        "",
    ]
    alerts = payload.get("alerts") or []
    if alerts:
        lines += _markdown_table(
            ["Severity", "Category", "Message"],
            [[row.get("severity"), row.get("category"), row.get("message")] for row in alerts],
        )
    else:
        lines.append("- none")
    blockers = payload.get("blockers") or []
    if blockers:
        lines += ["", "## Daily-Learning Blockers", ""]
        lines += _markdown_table(
            ["Priority", "Category", "Source", "Signal", "Action"],
            [
                [
                    row.get("priority"),
                    row.get("category"),
                    row.get("source"),
                    row.get("signal"),
                    row.get("action"),
                ]
                for row in blockers[:10]
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_sla_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sla_report(payload), encoding="utf-8")
    return path


def run_nightly_retrain(
    args,
    runner=run_subprocess_step,
    *,
    release_builder=create_release,
    code_identity_provider=capture_code_identity,
):
    guard_enabled = (
        not getattr(args, "dry_run", False)
        and not getattr(args, "disable_long_job_guard", False)
    )
    with long_job_guard(
        "nightly_retrain",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=guard_enabled,
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        return _run_nightly_retrain_guarded(
            args,
            runner=runner,
            long_job_guard_info=guard,
            release_builder=release_builder,
            code_identity_provider=code_identity_provider,
        )


def _run_nightly_retrain_guarded(
    args,
    runner=run_subprocess_step,
    long_job_guard_info=None,
    *,
    release_builder=create_release,
    code_identity_provider=capture_code_identity,
):
    started = time.time()
    started_at = utc_iso()
    invocation = build_invocation_proof(
        args,
        module_name="weather.operations.nightly_retrain",
        invocation_started_at_utc=started_at,
    )
    release_identity = producer_release_proof(args)
    lock_proof = build_lock_proof(
        (long_job_guard_info or {}).get("lock_acquisition"),
        prior_repair=getattr(args, "_prior_lock_repair_outcomes", None),
        required_kinds=("long_job_guard_lock",),
    )
    steps = []
    capture_resource_admission = None
    captured_input_parity = None
    if not args.dry_run:
        capture_resource_admission, _proof_path, _proof_report = (
            _capture_resource_preflight(args)
        )
    resource_denied = bool(
        capture_resource_admission
        and capture_resource_admission.get("admitted") is not True
    )
    if (
        not args.dry_run
        and not resource_denied
        and not getattr(args, "skip_captured_input_replay_parity", False)
    ):
        captured_input_parity, _parity_path, _parity_report = (
            _captured_input_parity_preflight(args, release_identity)
        )
    parity_denied = bool(
        captured_input_parity
        and captured_input_parity.get("status") != "PASS"
    )
    if resource_denied or parity_denied:
        candidate_guard = {
            "status": "DEFERRED",
            "candidate_id": args.candidate_id,
            "candidate_dir": str(
                getattr(args, "candidate_dir", "")
                or Path(args.candidates_root) / args.candidate_id
            ),
            "failures": [],
        }
    else:
        candidate_guard = prepare_candidate_outputs(args)
        candidate_guard = prepare_production_point_in_time_outputs(
            args, candidate_guard
        )
    plan = (
        planned_steps(args)
        if candidate_guard["status"] not in {"BLOCK", "DEFERRED"}
        else []
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runner": "nightly_retrain",
        "status": "running",
        "generated_at_utc": None,
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "duration_seconds": None,
        "dry_run": bool(args.dry_run),
        "invocation": invocation,
        "lock_proof": lock_proof,
        "sla": {
            "status": "PENDING",
            "predeclared": float(getattr(args, "producer_sla_seconds", 0.0) or 0.0) > 0,
            "limit_seconds": float(getattr(args, "producer_sla_seconds", 0.0) or 0.0) or None,
            "duration_seconds": None,
        },
        "release_identity": release_identity,
        "release_id": release_identity.get("release_id") if release_identity.get("status") == "PASS" else "",
        "release_manifest_sha256": (
            release_identity.get("release_manifest_sha256")
            if release_identity.get("status") == "PASS"
            else ""
        ),
        "release_identity_status": (
            "verified_serving_binding"
            if release_identity.get("status") == "PASS"
            else "unverified"
        ),
        "capture_resource_admission": capture_resource_admission,
        "captured_input_replay_parity": captured_input_parity,
        "config": {
            "family_unit": args.family_unit,
            "snapshots_root": args.snapshots_root,
            "backtest_root": args.backtest_root,
            "quality_grades": args.quality_grades,
            "pooled_band_artifact": args.pooled_band_artifact,
            "promotion_out": args.promotion_out,
            "labels_csv": args.labels_csv,
            "ledger_root": args.ledger_root,
            "settled_day_freshness_out": args.settled_day_freshness_out,
            "settled_day_freshness_report": args.settled_day_freshness_report,
            "daily_learning_out": args.daily_learning_out,
            "daily_learning_report": args.daily_learning_report,
            "experiment_queue_results_out": args.experiment_queue_results_out,
            "experiment_queue_top_n": args.experiment_queue_top_n,
            "skip_when_no_retrain_recommendation": args.skip_when_no_retrain_recommendation,
            "candidate_id": args.candidate_id,
            "candidate_dir": candidate_guard.get("candidate_dir"),
            "candidate_output_guard": candidate_guard,
            "release_candidate_mode": args.release_candidate_mode,
            "point_in_time_outputs": candidate_guard.get(
                "point_in_time_outputs", []
            ),
            "point_in_time_private_memory_budget_bytes": getattr(
                args, "point_in_time_private_memory_budget_bytes", None
            ),
            "build_candidate_release": args.build_candidate_release,
            "release_pointer": args.release_pointer,
            "long_job_guard": long_job_guard_info or {},
            "capture_resource_mode": getattr(
                args,
                "capture_resource_mode",
                "live",
            ),
            "capture_resource_out": str(
                getattr(args, "capture_resource_out", "")
                or Path(args.backtest_root) / "capture_resource_gate.json"
            ),
            "captured_input_replay_parity_required": not bool(
                getattr(args, "skip_captured_input_replay_parity", False)
            ),
            "captured_input_replay_parity_out": str(
                getattr(args, "captured_input_parity_out", "")
                or Path(args.backtest_root) / "live_variant_replay_parity.json"
            ),
            "production_readiness_gate_enabled": not bool(
                getattr(args, "skip_production_readiness_gate", False)
            ),
            "fail_on_production_readiness_block": bool(
                getattr(args, "fail_on_production_readiness_block", False)
            ),
        },
        "steps": steps,
        "promotion": {},
        "settled_day_freshness": {},
        "daily_learning": {},
        "candidate_release": {},
        "nightly_sla": {},
    }
    if resource_denied:
        admission_summary = capture_resource_admission.get("summary") or {}
        admission_enforcement = capture_resource_admission.get("enforcement") or {}
        steps.append(
            {
                "name": "capture_resource_admission",
                "command": ["internal", "capture_resource_admission"],
                "status": "blocked",
                "returncode": None,
                "duration_seconds": 0.0,
                "reason": "heavy_work_deferred_before_child_start",
                "decision": capture_resource_admission.get("decision"),
                "admitted": False,
                "blocker_codes": [
                    row.get("code")
                    for row in capture_resource_admission.get("blockers") or []
                ],
                "suggested_defer_until_utc": admission_summary.get(
                    "suggested_defer_until_utc"
                ),
                "proof_path": admission_enforcement.get("json_path"),
            }
        )
        payload["promotion"] = promotion_not_run_summary(
            args.promotion_out,
            "capture_resource_admission_deferred",
        )
        payload["candidate_release"] = {
            "status": "BLOCK",
            "reason": "capture_resource_admission_deferred",
            "activation": "NONE",
        }
        payload["status"] = "blocked"
    elif parity_denied:
        first_mismatch = captured_input_parity.get("first_mismatch") or {}
        steps.append(
            {
                "name": "captured_input_replay_parity",
                "command": ["internal", "captured_input_replay_parity"],
                "status": "blocked",
                "returncode": None,
                "duration_seconds": 0.0,
                "reason": "heavy_work_deferred_before_child_start",
                "decision": captured_input_parity.get("status"),
                "mismatch_count": (
                    captured_input_parity.get("summary") or {}
                ).get("mismatch_count"),
                "first_mismatch": first_mismatch,
                "next_action": first_mismatch.get("next_action")
                or "generate exact captured-input replay rows and rerun parity",
                "proof_path": (
                    captured_input_parity.get("outputs") or {}
                ).get("json_path"),
            }
        )
        payload["promotion"] = promotion_not_run_summary(
            args.promotion_out,
            "captured_input_replay_parity_blocked",
        )
        payload["candidate_release"] = {
            "status": "BLOCK",
            "reason": "captured_input_replay_parity_blocked",
            "activation": "NONE",
        }
        payload["status"] = "blocked"
    elif candidate_guard["status"] == "BLOCK":
        steps.append(
            {
                "name": "candidate_output_preflight",
                "command": ["internal", "candidate_output_guard"],
                "status": "error",
                "returncode": -1,
                "duration_seconds": 0.0,
                "stderr": "; ".join(row["error"] for row in candidate_guard["failures"]),
            }
        )
        payload["promotion"] = promotion_not_run_summary(
            args.promotion_out,
            "candidate_output_preflight_blocked",
        )
        payload["candidate_release"] = {
            "status": "BLOCK",
            "reason": "candidate_output_preflight_blocked",
            "activation": "NONE",
        }
        payload["status"] = "error"
    elif args.dry_run:
        steps.extend(
            {
                "name": name,
                "command": command,
                "status": "planned",
                "returncode": None,
                "duration_seconds": 0.0,
            }
            for name, command in plan
        )
        if args.build_candidate_release:
            steps.append(
                {
                    "name": "candidate_release_build",
                    "command": ["internal", "build_immutable_candidate_release", args.candidate_id],
                    "status": "planned",
                    "returncode": None,
                    "duration_seconds": 0.0,
                }
            )
        payload["candidate_release"] = {
            "status": "PLANNED" if args.build_candidate_release else "DISABLED",
            "activation": "MANUAL_POINTER_ONLY" if args.build_candidate_release else "NONE",
        }
        payload["status"] = "dry_run"
    else:
        for name, command in plan:
            promotion_selection_context = None
            if name == "experiment_queue":
                step = run_experiment_queue_step(args, runner)
            else:
                if name == "family_secondary_artifacts":
                    payload["daily_learning"] = daily_learning_summary(args.daily_learning_out)
                    if _should_skip_expensive_retrain(args, payload["daily_learning"]):
                        steps.append({
                            "name": "retrain_recommendation_gate",
                            "command": ["internal", "skip_expensive_retrain"],
                            "status": "skipped",
                            "returncode": 0,
                            "duration_seconds": 0.0,
                            "reason": "retrain_not_recommended",
                            "retrain_recommendation": payload["daily_learning"].get("retrain_recommendation") or {},
                        })
                        break
                if (
                    name == "promotion_refresh"
                    and args.release_candidate_mode == PRODUCTION_CANDIDATE_MODE
                ):
                    try:
                        preselection, folders, inventory = (
                            production_promotion_selection(args)
                        )
                        command = promotion_refresh_command(args, folders=folders)
                        corpus_option = command.index("--out")
                        command[corpus_option:corpus_option] = [
                            "--corpus-out",
                            args.point_in_time_promotion_selection_corpus,
                        ]
                        promotion_selection_context = (preselection, inventory)
                    except Exception as exc:  # noqa: BLE001 - fail closed before replay
                        step = {
                            "name": name,
                            "command": ["internal", "production_promotion_selection"],
                            "status": "error",
                            "returncode": -1,
                            "duration_seconds": 0.0,
                            "stdout": "",
                            "stderr": str(exc),
                        }
                        steps.append(step)
                        if not args.continue_on_error:
                            break
                        continue
                step = run_step(name, command, args, runner)
                if (
                    name == "promotion_refresh"
                    and step.get("status") == "ok"
                    and promotion_selection_context is not None
                ):
                    try:
                        preselection, inventory = promotion_selection_context
                        binding = bind_production_promotion_selection(
                            args,
                            preselection,
                            inventory,
                        )
                        step["point_in_time_selection_binding"] = binding
                    except Exception as exc:  # noqa: BLE001 - unbound route is unusable
                        step["status"] = "error"
                        step["returncode"] = -1
                        step["stderr"] = (
                            str(step.get("stderr") or "")
                            + "\nproduction promotion binding failed: "
                            + str(exc)
                        ).strip()
            steps.append(step)
            if (step.get("result") or {}).get("hard_stop_pipeline") or (
                step["status"] == "error" and not args.continue_on_error
            ):
                break
            if name == "daily_learning" and args.fail_on_daily_learning_blocker:
                payload["daily_learning"] = daily_learning_summary(args.daily_learning_out)
                integrity_ok, integrity_reason = daily_learning_input_integrity(
                    payload["daily_learning"]
                )
                if not integrity_ok:
                    steps.append({
                        "name": "daily_learning_input_gate",
                        "command": ["internal", "daily_learning_input_integrity"],
                        "status": "blocked",
                        "returncode": None,
                        "duration_seconds": 0.0,
                        "reason": integrity_reason,
                        "input_consistency_status": payload["daily_learning"].get(
                            "input_consistency_status"
                        ),
                        "input_freshness_status": payload["daily_learning"].get(
                            "input_freshness_status"
                        ),
                    })
                    break
        payload["settled_day_freshness"] = settled_day_freshness_summary(args.settled_day_freshness_out)
        payload["daily_learning"] = daily_learning_summary(args.daily_learning_out)
        ran_steps = {step.get("name") for step in steps}
        if "promotion_refresh" in ran_steps:
            payload["promotion"] = promotion_summary(args.promotion_out)
        else:
            skipped_for_recommendation = any(
                step.get("name") == "retrain_recommendation_gate" and step.get("status") == "skipped"
                for step in steps
            )
            aborted_on_input_gate = any(
                step.get("name") == "daily_learning_input_gate" and step.get("status") == "blocked"
                for step in steps
            )
            reason = (
                "daily_learning_input_gate_blocked"
                if aborted_on_input_gate
                else "retrain_not_recommended"
                if skipped_for_recommendation
                else "promotion_refresh_not_run"
            )
            payload["promotion"] = promotion_not_run_summary(args.promotion_out, reason)
        payload["status"] = pipeline_status(
            steps,
            payload["promotion"],
            payload["daily_learning"],
            fail_on_daily_learning_blocker=args.fail_on_daily_learning_blocker,
        )
        if not args.build_candidate_release:
            payload["candidate_release"] = {
                "status": "DISABLED",
                "reason": "candidate_release_build_disabled",
                "activation": "NONE",
            }
        elif candidate_guard["status"] != "PASS":
            payload["candidate_release"] = {
                "status": "BLOCK",
                "reason": "legacy_training_output_quarantined",
                "activation": "NONE",
            }
            steps.append(
                {
                    "name": "candidate_release_build",
                    "command": ["internal", "build_immutable_candidate_release", args.candidate_id],
                    "status": "blocked",
                    "returncode": None,
                    "duration_seconds": 0.0,
                    "reason": "legacy_training_output_quarantined",
                }
            )
            payload["status"] = "blocked"
        elif payload["status"] == "promote_ready":
            release_step, release_result = run_candidate_release_step(
                args,
                promotion=payload["promotion"],
                candidate_guard=candidate_guard,
                release_builder=release_builder,
                code_identity_provider=code_identity_provider,
            )
            steps.append(release_step)
            payload["candidate_release"] = release_result
            if release_step["status"] != "ok":
                payload["status"] = "error"
        else:
            payload["candidate_release"] = {
                "status": "NOT_BUILT",
                "reason": "existing_validation_gates_not_passed",
                "activation": "NONE",
            }
            steps.append(
                {
                    "name": "candidate_release_build",
                    "command": ["internal", "build_immutable_candidate_release", args.candidate_id],
                    "status": "skipped",
                    "returncode": 0,
                    "duration_seconds": 0.0,
                    "reason": "existing_validation_gates_not_passed",
                }
            )
    if not args.dry_run and not getattr(args, "skip_production_readiness_gate", False):
        readiness_started = time.time()
        readiness_step = {
            "name": "production_readiness_gate",
            "command": ["internal", "production_readiness_gate"],
            "status": "running",
            "returncode": None,
            "started_at_utc": utc_iso(),
            "finished_at_utc": None,
            "duration_seconds": 0.0,
        }
        try:
            readiness_step["result"] = _production_readiness_status(args)
            readiness_step["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - final status persistence is mandatory
            readiness_step.update(
                {
                    "status": "error",
                    "returncode": -1,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
            payload["status"] = "error"
        readiness_step["finished_at_utc"] = utc_iso()
        readiness_step["duration_seconds"] = round(
            time.time() - readiness_started,
            3,
        )
        steps.append(readiness_step)
        payload["production_readiness"] = readiness_step.get("result") or {
            "status": "ERROR",
            "error": readiness_step.get("error"),
        }
        if (
            getattr(args, "fail_on_production_readiness_block", False)
            and payload["production_readiness"].get("status") != "PASS"
            and payload.get("status") != "error"
        ):
            payload["status"] = "blocked"
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["sla"] = build_stage_sla(
        duration_seconds=payload["duration_seconds"],
        limit_seconds=getattr(args, "producer_sla_seconds", 0.0),
    )
    payload["nightly_sla"] = nightly_run_sla_status(
        status_path=args.status_out,
        status_payload=payload,
        missed_run_grace_minutes=args.missed_run_grace_minutes,
    )
    payload["nightly_sla"]["generated_at_utc"] = payload["generated_at_utc"]
    status_path = write_json(args.status_out, payload)
    report_path = write_report(args.report_out, payload)
    return payload, status_path, report_path


def build_run_parser(parser):
    parser.add_argument("--family-unit", default="F", choices=["F"])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--min-settled-days", type=int, default=2)
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--family-secondary-out", default="")
    parser.add_argument("--pooled-band-artifact", default="")
    parser.add_argument("--artifact-registry", default="")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument(
        "--release-candidate-mode",
        choices=sorted(CANDIDATE_MODES),
        default=RESEARCH_ONLY_CANDIDATE_MODE,
        help=(
            "research_only remains the default; production requires an explicit "
            "bounded point-in-time source and materializes all qualification roles"
        ),
    )
    parser.add_argument("--candidates-root", default=str(DEFAULT_CANDIDATES_ROOT))
    parser.add_argument("--releases-root", default=str(DEFAULT_RELEASES_ROOT))
    parser.add_argument("--release-pointer", default="")
    parser.add_argument("--release-parent", default="")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--point-in-time-folder", action="append", default=[])
    parser.add_argument("--point-in-time-source-corpus", default="")
    parser.add_argument("--point-in-time-source-manifest", default="")
    parser.add_argument("--point-in-time-source-replay-manifest", default="")
    parser.add_argument("--point-in-time-archive-root", default="")
    parser.add_argument("--point-in-time-as-of", default="")
    parser.add_argument("--point-in-time-window-end", default="")
    parser.add_argument("--point-in-time-corpus", default="")
    parser.add_argument("--point-in-time-materialization-manifest", default="")
    parser.add_argument("--point-in-time-validation-plan", default="")
    parser.add_argument("--point-in-time-streaming-evaluation", default="")
    parser.add_argument("--point-in-time-max-market-days", type=int, default=60)
    parser.add_argument(
        "--point-in-time-max-rows-per-market-day", type=int, default=250_000
    )
    parser.add_argument("--point-in-time-batch-rows", type=int, default=65_536)
    parser.add_argument(
        "--point-in-time-outer-min-train-dates", type=int, default=14
    )
    parser.add_argument(
        "--point-in-time-inner-min-train-dates", type=int, default=7
    )
    parser.add_argument(
        "--point-in-time-embargo-days", type=int, choices=range(3, 8), default=3
    )
    parser.add_argument("--point-in-time-step-dates", type=int, default=7)
    parser.add_argument(
        "--point-in-time-max-fold-scopes", type=int, default=128
    )
    parser.add_argument(
        "--point-in-time-bootstrap-iterations", type=int, default=2_000
    )
    parser.add_argument(
        "--point-in-time-private-memory-budget-bytes",
        type=int,
        default=4 * 1024**3,
        help="Declared private-memory ceiling for bounded production qualification.",
    )
    parser.add_argument(
        "--expected-live-runtimes",
        default="snapshot_loop,observation_trigger,market_making,taker_bot",
    )
    parser.set_defaults(build_candidate_release=True)
    parser.add_argument(
        "--build-candidate-release",
        dest="build_candidate_release",
        action="store_true",
        help="Build an immutable but inactive release only after all existing gates pass (default).",
    )
    parser.add_argument(
        "--skip-candidate-release-build",
        dest="build_candidate_release",
        action="store_false",
    )
    parser.add_argument(
        "--allow-legacy-serving-output",
        action="store_true",
        help="Temporary compatibility only: permit old output paths but quarantine and block release creation.",
    )
    parser.add_argument("--promotion-out", default=str(DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"))
    parser.add_argument("--promotion-report", default=str(DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh_report.md"))
    parser.add_argument("--daily-learning-out", default=str(DEFAULT_DAILY_LEARNING_OUT))
    parser.add_argument("--daily-learning-report", default=str(DEFAULT_DAILY_LEARNING_REPORT))
    parser.add_argument("--experiment-queue-results-out", default=str(DEFAULT_EXPERIMENT_QUEUE_RESULTS_OUT))
    parser.add_argument("--experiment-queue-top-n", type=int, default=3)
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--settled-day-freshness-out", default=str(DEFAULT_SETTLED_DAY_FRESHNESS_OUT))
    parser.add_argument("--settled-day-freshness-report", default=str(DEFAULT_SETTLED_DAY_FRESHNESS_REPORT))
    parser.add_argument("--settled-day-target-date", default="")
    parser.add_argument("--settled-day-as-of", default="")
    parser.add_argument("--settled-day-markets", default="")
    parser.add_argument("--shadow-ab-out", default=str(DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor.json"))
    parser.add_argument("--shadow-ab-report", default=str(DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor_report.md"))
    parser.add_argument("--ab-current-tol", type=float, default=0.003)
    parser.add_argument("--ab-market-tol", type=float, default=0.003)
    parser.add_argument("--step-timeout-seconds", type=float, default=DEFAULT_STEP_TIMEOUT_SECONDS)
    parser.add_argument(
        "--capture-resource-mode",
        choices=CAPTURE_MODES,
        default="live",
        help=(
            "Host role for pre-training admission. Use offline_host only on "
            "an explicitly non-capture research host."
        ),
    )
    parser.add_argument("--capture-resource-disk-path", default="")
    parser.add_argument("--capture-resource-out", default="")
    parser.add_argument("--capture-resource-report", default="")
    parser.add_argument(
        "--capture-resource-min-free-memory-bytes",
        type=int,
        default=DEFAULT_CAPTURE_MIN_FREE_MEMORY_BYTES,
    )
    parser.add_argument(
        "--capture-resource-min-free-disk-bytes",
        type=int,
        default=DEFAULT_CAPTURE_MIN_FREE_DISK_BYTES,
    )
    parser.add_argument(
        "--capture-resource-daily-disk-growth-bytes",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--capture-resource-min-disk-headroom-days",
        type=float,
        default=DEFAULT_CAPTURE_MIN_DISK_HEADROOM_DAYS,
    )
    parser.add_argument(
        "--capture-resource-active-window-start-hour",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--capture-resource-active-window-end-hour",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--captured-input-parity-served",
        action="append",
        default=[],
        help="Explicit live-served prediction row file; repeat for multiple files.",
    )
    parser.add_argument(
        "--captured-input-parity-replay",
        action="append",
        default=[],
        help=(
            "Explicit prediction rows regenerated from the exact captured inputs; "
            "missing rows block candidate work."
        ),
    )
    parser.add_argument("--captured-input-parity-out", default="")
    parser.add_argument("--captured-input-parity-report", default="")
    parser.add_argument(
        "--captured-input-parity-max-age-hours",
        type=float,
        default=live_variant_settlement_scorecard.DEFAULT_PARITY_MAX_INPUT_AGE_HOURS,
    )
    parser.add_argument("--skip-captured-input-replay-parity", action="store_true")
    parser.add_argument(
        "--production-readiness-evidence",
        action="append",
        default=[],
        metavar="NAME=PATH",
    )
    parser.add_argument(
        "--production-readiness-served-artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
    )
    parser.add_argument("--production-readiness-served-route", default="")
    parser.add_argument("--production-readiness-out", default="")
    parser.add_argument("--production-readiness-report", default="")
    parser.add_argument("--skip-production-readiness-gate", action="store_true")
    parser.add_argument(
        "--fail-on-production-readiness-block",
        action="store_true",
        help="Return a blocking status when the final read-only readiness gate is not PASS.",
    )
    parser.add_argument(
        "--promotion-step-timeout-seconds",
        type=float,
        default=6 * 60 * 60,
        help="Timeout for the retrain's promotion_refresh validation replay, "
             "which replays the fresh candidate over the full promotion corpus "
             "(~4h at 261 market-days) and outgrew the flat step timeout.",
    )
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-family-secondary", action="store_true")
    parser.add_argument("--skip-settled-day-freshness", action="store_true")
    parser.add_argument("--skip-settled-day-polymarket-reconciliation", action="store_true")
    parser.add_argument("--skip-daily-learning", action="store_true")
    parser.add_argument("--skip-experiment-queue", action="store_true")
    parser.add_argument("--skip-when-no-retrain-recommendation", action="store_true")
    parser.add_argument("--skip-pooled-feature", action="store_true")
    parser.add_argument("--skip-artifact-registry", action="store_true")
    parser.add_argument("--skip-promotion-refresh", action="store_true")
    parser.add_argument("--skip-shadow-ab-monitor", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.set_defaults(fail_on_daily_learning_blocker=True)
    parser.add_argument("--fail-on-daily-learning-blocker", dest="fail_on_daily_learning_blocker", action="store_true")
    parser.add_argument("--no-fail-on-daily-learning-blocker", dest="fail_on_daily_learning_blocker", action="store_false")
    parser.add_argument("--fail-on-shadow-ab-alert", action="store_true")
    parser.add_argument("--missed-run-grace-minutes", type=float, default=DEFAULT_MISSED_RUN_GRACE_MINUTES)
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    parser.add_argument("--scheduler-task-name", default="")
    parser.add_argument("--scheduler-task-executable", default="")
    parser.add_argument("--scheduler-task-working-directory", default="")
    parser.add_argument(
        "--scheduler-invocation-topology",
        choices=("direct", "delegated_child"),
        default="direct",
    )
    parser.add_argument("--scheduler-task-action-arguments-b64", default="")
    parser.add_argument("--scheduler-process-executable", default="")
    parser.add_argument("--scheduler-correlation-seconds", type=float, default=120.0)
    parser.add_argument(
        "--producer-sla-seconds",
        type=float,
        default=0.0,
        help="Predeclared terminal SLA for this exact scheduled run; zero is non-countable.",
    )
    return parser


def cmd_run(args):
    payload, status_path, report_path = run_nightly_retrain(args)
    print(f"Nightly retrain: {payload['status']}")
    print(f"Status written to {status_path}")
    print(f"Report written to {report_path}")
    if payload["status"] == "error":
        return 1
    if (
        args.fail_on_production_readiness_block
        and (payload.get("production_readiness") or {}).get("status") != "PASS"
    ):
        return 2
    if args.fail_on_block and payload["status"] in {"blocked", "shadow"}:
        return 2
    return 0


def cmd_status(args):
    payload = nightly_run_sla_status(
        status_path=args.status_path,
        task_name=args.task_name,
        schedule_local_time=args.schedule_local_time,
        schedule_timezone=args.schedule_timezone,
        missed_run_grace_minutes=args.missed_run_grace_minutes,
    )
    print(f"Nightly retrain SLA: {payload['state']}")
    if args.write:
        json_path = write_json(args.out, payload)
        report_path = write_sla_report(args.report, payload)
        print(f"JSON written to {json_path}")
        print(f"Report written to {report_path}")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 2 if payload["state"] == "CRITICAL" else 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run candidate-only nightly retraining, validation, and inactive release construction."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = build_run_parser(sub.add_parser("run"))
    run.set_defaults(func=cmd_run)
    status = sub.add_parser("status")
    status.add_argument("--status-path", default=str(DEFAULT_STATUS_OUT))
    status.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    status.add_argument("--schedule-local-time", default=DEFAULT_SCHEDULE_LOCAL_TIME)
    status.add_argument("--schedule-timezone", default=DEFAULT_SCHEDULE_TIMEZONE)
    status.add_argument("--missed-run-grace-minutes", type=float, default=DEFAULT_MISSED_RUN_GRACE_MINUTES)
    status.add_argument("--out", default=str(DEFAULT_SLA_STATUS_OUT))
    status.add_argument("--report", default=str(DEFAULT_SLA_REPORT_OUT))
    status.add_argument(
        "--write",
        action="store_true",
        help="Write the SLA JSON/report artifacts. By default status is read-only and prints JSON.",
    )
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
