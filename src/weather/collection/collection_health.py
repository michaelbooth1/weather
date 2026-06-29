"""Collection health: detect gaps and coverage problems in snapshot tapes so we
know which captured market-days are clean enough to trust in the backtest.

A day is only useful for settlement-scored evaluation if it was captured
continuously across the afternoon warming window. This module reports, per day:
capture count vs expected, the largest gap, every gap beyond tolerance, the
covered local-hour range, and a clean verdict.

CLI:
  python -m weather.collection.collection_health [folder ...] [--interval-minutes 10] [--tolerance 1.5]
  python -m weather.collection.collection_health --live --strict [folder ...]
"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from weather.paths import data_path

from weather.collection.redaction import redact_sensitive_url_parts
from weather.collection.live_variant_predictions import active_live_variants
from weather.market.market_config import config_for_date, date_from_event_slug, ensure_date
from weather.market.market_registry import all_specs, spec_for_slug
from weather.variant_registry import DEFAULT_REGISTRY_PATH, load_registry

DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
# Settlement-decisive window: a clean day should span at least this local range.
AFTERNOON_START_HOUR = 12
AFTERNOON_END_HOUR = 18
EARLY_HOUR_START_HOUR = 0
EARLY_HOUR_END_HOUR = 8
OPEN_METEO_SOURCE_FAMILY = {
    "open_meteo",
    "open_meteo_multimodel",
    "global_ensemble",
    "eccc_gem",
}
PAID_WEATHER_PROVIDER_FAMILIES = {
    "weather_forecast",
    "wu_current",
    "wu_history",
}
FREE_REPLACEMENT_REQUIRED_FAMILIES = {"local_history"}
FREE_REPLACEMENT_OBSERVATION_FAMILIES = {"metar", "eccc_swob"}
FREE_REPLACEMENT_GUIDANCE_FAMILIES = {
    "open_meteo",
    "nws_grid",
    "nws_hourly",
    "nbm_probabilistic_tmax",
    "eccc_citypage",
}
FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES = 3
SETTLEMENT_SOURCE_AUTH_FAILURE = "settlement_source_auth_failure"
SETTLEMENT_AUTH_FAILURE_BUCKET = "settlement_auth_failure"
SNAPSHOT_STATUS_COMMAND = "python -m weather.collection.snapshot_tracker --status"
SNAPSHOT_RESTART_COMMAND = "python -m weather.collection.snapshot_tracker --restart"
SNAPSHOT_FLEET_VERIFY_COMMAND = (
    "python -m weather.reporting.fleet.fleet_observability report "
    "--out data/backtest/fleet_observability.json "
    "--report data/backtest/fleet_observability_report.md"
)
SOURCE_STATUS_VERIFY_COMMAND = SNAPSHOT_STATUS_COMMAND
SOURCE_STATUS_BULK_REPAIR_COMMAND = (
    "python -m weather.collection.snapshot_tracker "
    "--backfill-source-status --overwrite-source-status"
)
SOURCE_STATUS_PROOF_SCHEMA_VERSION = "source_status_proof_v0.2"


def parse_times(iso_strings):
    times = []
    for s in iso_strings:
        if not s:
            continue
        try:
            times.append(datetime.fromisoformat(str(s)))
        except ValueError:
            continue
    return sorted(times)


def detect_gaps(times, interval_minutes, tolerance=1.5):
    """Consecutive captures spaced more than tolerance x the interval apart."""
    limit = interval_minutes * tolerance
    gaps = []
    for a, b in zip(times, times[1:]):
        gap_min = (b - a).total_seconds() / 60.0
        if gap_min > limit:
            gaps.append({"after": a, "before": b, "gap_minutes": gap_min})
    return gaps


def gap_times_for_window(times, window_start, window_end):
    """Times relevant for cadence inside the settlement-decisive window.

    Keep the nearest capture before/after the window so missing captures right
    after 12:00 or right before 18:00 still count as window gaps, while late
    evening/post-settlement gaps do not poison a clean training day.
    """
    inside = [t for t in times if window_start <= t <= window_end]
    before = max((t for t in times if t < window_start), default=None)
    after = min((t for t in times if t > window_end), default=None)
    if before is not None and (not inside or inside[0] > window_start):
        inside.insert(0, before)
    if after is not None and (not inside or inside[-1] < window_end):
        inside.append(after)
    return inside


def coverage_summary(times, interval_minutes, tolerance=1.5, target_date=None):
    times = sorted(times)
    n = len(times)
    if n == 0:
        return {"n": 0, "clean": False, "reason": "no captures"}
    span_min = (times[-1] - times[0]).total_seconds() / 60.0
    expected = int(span_min // interval_minutes) + 1 if span_min > 0 else 1
    first, last = times[0], times[-1]
    
    if target_date is not None:
        window_start, window_end = local_window(target_date, first.tzinfo)
        covers_afternoon = first <= window_start and last >= window_end
        gap_times = gap_times_for_window(times, window_start, window_end)
    else:
        covers_afternoon = first.hour <= AFTERNOON_START_HOUR and (last.hour >= AFTERNOON_END_HOUR or last.date() > first.date())
        gap_times = times
    gaps = detect_gaps(gap_times, interval_minutes, tolerance)
    max_gap = max((g["gap_minutes"] for g in gaps), default=interval_minutes if n > 1 else 0.0)
    clean = n >= 2 and not gaps and covers_afternoon
    reasons = []
    if n < 2:
        reasons.append("too few captures")
    if gaps:
        reasons.append(f"{len(gaps)} gap(s), max {max_gap:.0f} min")
    if not covers_afternoon:
        reasons.append(
            f"afternoon window not fully covered (captured {first:%H:%M}-{last:%H:%M})")
    return {
        "n": n,
        "first": first,
        "last": last,
        "span_minutes": span_min,
        "expected": expected,
        "capture_ratio": n / expected if expected else 0.0,
        "max_gap_minutes": max_gap,
        "gaps": gaps,
        "covers_afternoon": covers_afternoon,
        "clean": clean,
        "reason": "; ".join(reasons) if reasons else "ok",
    }


def local_window(target_date, tzinfo=None):
    return (
        datetime.combine(target_date, dt_time(AFTERNOON_START_HOUR, tzinfo=tzinfo)),
        datetime.combine(target_date, dt_time(AFTERNOON_END_HOUR, tzinfo=tzinfo)),
    )


def early_hour_window(target_date, tzinfo=None):
    return (
        datetime.combine(target_date, dt_time(EARLY_HOUR_START_HOUR, tzinfo=tzinfo)),
        datetime.combine(target_date, dt_time(EARLY_HOUR_END_HOUR, tzinfo=tzinfo)),
    )


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _gap_windows(gaps):
    return [
        {
            "after": _iso(item.get("after")),
            "before": _iso(item.get("before")),
            "gap_minutes": item.get("gap_minutes"),
        }
        for item in gaps or []
    ]


def _snapshot_cadence_root_cause(summary):
    reason = str(summary.get("reason") or "").lower()
    if "stale code" in reason or "source tree" in reason:
        return "stale_code_restart"
    if "duplicate writer" in reason or "writer lock" in reason:
        return "duplicate_writer_prevention"
    if "disk" in reason or "headroom" in reason or "backpressure" in reason:
        return "disk_backpressure"
    if "provider" in reason or "source delay" in reason or "rate limit" in reason:
        return "provider_source_delay"
    if summary.get("n", 0) == 0 or "no snapshot tape" in reason or "no captures" in reason:
        return "process_down"
    if "latest capture" in reason:
        return "long_iteration_or_stalled_loop"
    if summary.get("gaps") or "gap" in reason:
        return "unknown_snapshot_gap"
    if summary.get("clean") or summary.get("state") == "COLLECTING":
        return "within_cadence"
    if "afternoon window" in reason:
        return "unknown_snapshot_gap"
    return "unknown"


def snapshot_cadence_proof(
    summary,
    *,
    freshness_sla_minutes,
    latest_snapshot_id=None,
    latest_snapshot_at_utc=None,
    latest_snapshot_at_local=None,
):
    """Serializable per-market cadence evidence for live-forward SLO reports."""
    gaps = _gap_windows(summary.get("gaps") or [])
    action_required = bool(summary.get("action_required", not summary.get("clean")))
    closed_non_countable = summary.get("state") == "PARTIAL" or (
        action_required
        and bool(gaps)
    )
    root_cause = _snapshot_cadence_root_cause(summary)
    return {
        "status": "BLOCK" if action_required else "PASS",
        "counts_so_far": not action_required,
        "active_day_countable": not closed_non_countable,
        "recoverable_same_day": bool(action_required and not closed_non_countable),
        "root_cause": root_cause,
        "root_cause_class": root_cause,
        "state": summary.get("state") or ("CLEAN" if summary.get("clean") else "CHECK"),
        "reason": summary.get("reason"),
        "snapshot_count": summary.get("n", 0),
        "latest_snapshot_id": latest_snapshot_id,
        "latest_snapshot_at_utc": latest_snapshot_at_utc,
        "latest_snapshot_at_local": latest_snapshot_at_local,
        "latest_age_minutes": summary.get("latest_age_minutes"),
        "freshness_sla_minutes": freshness_sla_minutes,
        "window_start": _iso(summary.get("window_start")),
        "window_end": _iso(summary.get("window_end")),
        "covers_afternoon": summary.get("covers_afternoon"),
        "gap_count": len(gaps),
        "max_gap_minutes": summary.get("max_gap_minutes"),
        "gap_windows": gaps,
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
        "proof_requirements": [
            "snapshot loop state RUNNING",
            "runtime_code_state current",
            "consecutive_errors 0",
            "single writer lock owner",
            "snapshot_coverage_gap blocked markets 0 after rerun",
        ],
    }


def early_hour_coverage_summary(
    times,
    interval_minutes,
    tolerance=1.5,
    *,
    target_date=None,
    as_of=None,
    native_tz=None,
):
    """Serializable 00:00-08:00 local snapshot coverage proof for active-day evidence."""
    if native_tz is not None:
        times = [
            ts.astimezone(native_tz) if ts.tzinfo is not None else ts.replace(tzinfo=native_tz)
            for ts in (times or [])
        ]
        if as_of is not None:
            as_of = as_of.astimezone(native_tz) if as_of.tzinfo is not None else as_of.replace(tzinfo=native_tz)
    times = sorted(times or [])
    tzinfo = (times[-1].tzinfo if times else None) if times else (as_of.tzinfo if as_of is not None else None)
    if as_of is not None:
        if tzinfo is None and as_of.tzinfo is not None:
            as_of = as_of.replace(tzinfo=None)
        elif tzinfo is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=tzinfo)
        elif tzinfo is not None:
            as_of = as_of.astimezone(tzinfo)
    if target_date is None:
        target_date = times[0].date() if times else (as_of.date() if as_of is not None else None)
    if target_date is None:
        return {
            "schema_version": "early_hour_coverage_v0.1",
            "status": "MISSING",
            "counts_toward_early_hour_evidence": False,
            "target_date": None,
            "reason": "target date is unavailable",
            "snapshot_count": 0,
            "expected_snapshot_count": 0,
            "minimum_snapshot_count": 0,
            "gap_count": 0,
            "gap_windows": [],
            "status_command": SNAPSHOT_STATUS_COMMAND,
            "repair_command": SNAPSHOT_RESTART_COMMAND,
            "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
        }

    window_start, window_end = early_hour_window(target_date, tzinfo)
    window_minutes = (window_end - window_start).total_seconds() / 60.0
    expected_count = int(window_minutes // float(interval_minutes)) + 1
    minimum_count = max(1, int(window_minutes // float(interval_minutes)))
    freshness_limit = float(interval_minutes) * float(tolerance)
    as_of = as_of or datetime.now(tzinfo)
    window_times = [ts for ts in times if window_start <= ts <= window_end]
    gaps = detect_gaps(window_times, interval_minutes, tolerance) if len(window_times) >= 2 else []
    gap_windows = _gap_windows(gaps)
    first = window_times[0] if window_times else None
    last = window_times[-1] if window_times else None
    enough_snapshots = len(window_times) >= minimum_count
    covers_window = bool(
        first
        and last
        and first <= window_start + timedelta(minutes=freshness_limit)
        and last >= window_end - timedelta(minutes=freshness_limit)
    )

    reasons = []
    if as_of < window_end:
        status = "PENDING"
        reasons.append(f"early-hour window closes at {window_end:%H:%M}")
    else:
        if not enough_snapshots:
            reasons.append(f"{len(window_times)}/{minimum_count} minimum early-hour snapshots")
        if not covers_window:
            if first and last:
                reasons.append(f"early-hour window not fully covered (captured {first:%H:%M}-{last:%H:%M})")
            else:
                reasons.append("no early-hour captures")
        if gaps:
            max_gap = max(float(row.get("gap_minutes") or 0.0) for row in gap_windows)
            reasons.append(f"{len(gaps)} early-hour gap(s), max {max_gap:.0f} min")
        status = "PASS" if not reasons else "BLOCK"

    return {
        "schema_version": "early_hour_coverage_v0.1",
        "status": status,
        "counts_toward_early_hour_evidence": status == "PASS",
        "target_date": target_date.isoformat(),
        "window_start": _iso(window_start),
        "window_end": _iso(window_end),
        "snapshot_count": len(window_times),
        "expected_snapshot_count": expected_count,
        "minimum_snapshot_count": minimum_count,
        "missing_snapshot_count": max(0, minimum_count - len(window_times)),
        "coverage_ratio": (len(window_times) / expected_count) if expected_count else 0.0,
        "first_snapshot_at_local": _iso(first),
        "last_snapshot_at_local": _iso(last),
        "covers_window": covers_window,
        "enough_snapshots": enough_snapshots,
        "gap_count": len(gap_windows),
        "max_gap_minutes": max((row.get("gap_minutes") for row in gap_windows), default=None),
        "gap_windows": gap_windows,
        "reason": "; ".join(reasons) if reasons else "early-hour snapshot coverage is countable",
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
    }


def live_coverage_summary(times, interval_minutes, tolerance=1.5, as_of=None, target_date=None):
    """Collection health for an in-progress market day.

    Completed-day labeling should use coverage_summary(), which is deliberately
    strict. This helper avoids marking a morning live tape partial merely
    because the 12:00-18:00 settlement-decisive window has not happened yet.
    """
    times = sorted(times)
    as_of = as_of or datetime.now(times[-1].tzinfo if times else None)
    tzinfo = as_of.tzinfo or (times[-1].tzinfo if times else None)
    target_date = target_date or (times[0].date() if times else as_of.date())
    window_start, window_end = local_window(target_date, tzinfo)
    freshness_limit = interval_minutes * tolerance

    if not times:
        if as_of >= window_end:
            return {
                "state": "PARTIAL",
                "action_required": True,
                "clean": False,
                "n": 0,
                "reason": "no captures before window close",
                "window_start": window_start,
                "window_end": window_end,
            }
        if as_of >= window_start:
            return {
                "state": "AT_RISK",
                "action_required": True,
                "clean": False,
                "n": 0,
                "reason": "no captures after window start",
                "window_start": window_start,
                "window_end": window_end,
            }
        return {
            "state": "PENDING",
            "action_required": False,
            "clean": False,
            "n": 0,
            "reason": "no captures yet; afternoon window has not started",
            "window_start": window_start,
            "window_end": window_end,
        }

    final_summary = coverage_summary(times, interval_minutes, tolerance, target_date=target_date)
    final_summary.update({
        "window_start": window_start,
        "window_end": window_end,
    })
    if as_of >= window_end:
        final_summary["state"] = "CLEAN" if final_summary["clean"] else "PARTIAL"
        final_summary["action_required"] = not final_summary["clean"]
        return final_summary

    latest = times[-1]
    latest_age = (as_of - latest).total_seconds() / 60.0
    gaps = final_summary.get("gaps") or []
    reasons = []
    if gaps:
        reasons.append(final_summary["reason"])
    if latest_age > freshness_limit:
        reasons.append(f"latest capture is {latest_age:.0f} min old")
    if as_of >= window_start and times[0] > window_start:
        reasons.append(f"first capture after window start ({times[0]:%H:%M})")

    if reasons:
        final_summary["state"] = "AT_RISK"
        final_summary["action_required"] = True
        final_summary["reason"] = "; ".join(reasons)
    else:
        final_summary["state"] = "COLLECTING"
        final_summary["action_required"] = False
        final_summary["reason"] = (
            f"capture cadence healthy; afternoon window closes at {window_end:%H:%M}"
        )
    final_summary["latest_age_minutes"] = latest_age
    return final_summary


def folder_target_date(folder):
    return date_from_event_slug(Path(folder).name)


def summarize_folder(folder, interval_minutes=10.0, tolerance=1.5, live=False, as_of=None):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    raw_times = snapshot_times(tape) if tape.exists() else []
    freshness_sla = float(interval_minutes) * float(tolerance)
    target_date = folder_target_date(folder)
    spec = spec_for_slug(folder.name)
    native_tz = getattr(spec, "tz", None)
    times = [
        ts.astimezone(native_tz) if native_tz is not None and ts.tzinfo is not None
        else ts.replace(tzinfo=native_tz) if native_tz is not None
        else ts
        for ts in raw_times
    ]
    if as_of is not None and native_tz is not None:
        as_of = as_of.astimezone(native_tz) if as_of.tzinfo is not None else as_of.replace(tzinfo=native_tz)
    summary = (
        live_coverage_summary(times, interval_minutes, tolerance, as_of=as_of, target_date=target_date)
        if live
        else coverage_summary(times, interval_minutes, tolerance, target_date=target_date)
    )
    _latest_rows, snapshot_meta = latest_snapshot_rows(folder)
    summary["event_slug"] = folder.name
    summary["folder"] = str(folder)
    summary["tape_path"] = str(tape)
    summary["variant_prediction_tape"] = variant_prediction_tape_health(folder)
    summary["latest_snapshot_id"] = snapshot_meta.get("snapshot_id")
    summary["latest_snapshot_at_utc"] = snapshot_meta.get("captured_at_utc")
    summary["latest_snapshot_at_local"] = snapshot_meta.get("captured_at_local")
    summary["snapshot_cadence_proof"] = snapshot_cadence_proof(
        summary,
        freshness_sla_minutes=freshness_sla,
        latest_snapshot_id=snapshot_meta.get("snapshot_id"),
        latest_snapshot_at_utc=snapshot_meta.get("captured_at_utc"),
        latest_snapshot_at_local=snapshot_meta.get("captured_at_local"),
    )
    summary["early_hour_coverage"] = early_hour_coverage_summary(
        times,
        interval_minutes,
        tolerance,
        target_date=target_date,
        as_of=as_of,
        native_tz=native_tz,
    )
    return summary


def latest_market_folder(spec, snapshots_root=DEFAULT_SNAPSHOTS_ROOT, target_date=None):
    root = Path(snapshots_root)
    if target_date is not None:
        folder = root / config_for_date(ensure_date(target_date), spec.id).event_slug
        return folder if (folder / "snapshots_long.csv").exists() else None
    candidates = []
    for tape in root.glob("*/snapshots_long.csv"):
        folder = tape.parent
        folder_spec = spec_for_slug(folder.name)
        if folder_spec and folder_spec.id == spec.id:
            candidates.append(folder)
    if not candidates:
        return None
    return max(candidates, key=lambda folder: folder_target_date(folder))


def bool_value(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok"}


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_status_repair_command(folder):
    return (
        "python -m weather.collection.snapshot_tracker "
        "--backfill-source-status --overwrite-source-status "
        f"--source-status-folder {Path(folder)}"
    )


def source_family_for_row(row):
    family = row.get("source_family")
    if family:
        return family
    source = row.get("source") or "unknown"
    if source in OPEN_METEO_SOURCE_FAMILY:
        return "open_meteo"
    return source


def source_status_for_row(row):
    status = str(row.get("status") or "").strip().lower()
    if status:
        return status
    if bool_value(row.get("ok")) and not bool_value(row.get("stale")):
        return "fresh"
    if bool_value(row.get("stale")):
        return "stale_cache"
    return "failed"


def source_degradation_bucket(row):
    status = source_status_for_row(row)
    degradation = str(row.get("degradation_state") or "").strip().lower()
    family = source_family_for_row(row)
    http_status = str(row.get("http_status") or "").strip()
    if (
        status == SETTLEMENT_SOURCE_AUTH_FAILURE
        or degradation == SETTLEMENT_SOURCE_AUTH_FAILURE
        or (family in PAID_WEATHER_PROVIDER_FAMILIES and http_status in {"401", "403"})
    ):
        return SETTLEMENT_AUTH_FAILURE_BUCKET
    if status in {"expected_current_day_unavailable", "expected_unavailable"} or degradation in {
        "expected_current_day_unavailable",
        "expected_unavailable",
    }:
        return "expected_unavailable"
    if status == "rate_limited":
        return "rate_limited"
    if status == "rate_limited_cache":
        return "fallback"
    if status in {"stale", "stale_cache", "expired"}:
        return "fallback"
    if status in {"failed", "error", "missing"} or not bool_value(row.get("ok")):
        return "failed"
    if status in {"fresh", "fresh_cache", "ok", "available"}:
        return "fresh"
    return "unknown"


def source_status_detail(row, bucket):
    return {
        "source": row.get("source"),
        "source_family": source_family_for_row(row),
        "status": source_status_for_row(row),
        "bucket": bucket,
        "ok": bool_value(row.get("ok")),
        "stale": bool_value(row.get("stale")),
        "http_status": row.get("http_status"),
        "retry_after_seconds": maybe_float(row.get("retry_after_seconds")),
        "degradation_state": row.get("degradation_state"),
        "cache_status": row.get("cache_status"),
        "fallback_source": row.get("fallback_source"),
        "fetched_at": row.get("fetched_at"),
        "age_minutes": maybe_float(row.get("age_minutes")),
        "ttl_minutes": maybe_float(row.get("ttl_minutes")),
        "latency_ms": maybe_float(row.get("latency_ms")),
        "row_count": maybe_float(row.get("row_count")),
        "error": redact_sensitive_url_parts(row.get("error")),
    }


def family_claim_lane_allowance(summary):
    affected = bool(
        int(summary.get("failed_source_count") or 0)
        + int(summary.get("fallback_source_count") or 0)
        + int(summary.get("rate_limited_source_count") or 0)
        + int(summary.get("settlement_auth_failure_source_count") or 0)
        + int(summary.get("unknown_source_count") or 0)
    )
    paper_trading = not bool(summary.get("trading_blocking"))
    optional_paid_provider_auth = bool(
        summary.get("free_source_replacement_covered")
        and paid_provider_auth_only(summary)
    )
    strict_lane_allowed = not affected or optional_paid_provider_auth
    return {
        "model_review": True,
        "paper_trading": paper_trading,
        "live_trade_permission": strict_lane_allowed,
        "promotion_readiness": strict_lane_allowed,
    }


def healthy_free_source_families(families):
    healthy = []
    for family, summary in families.items():
        if family in PAID_WEATHER_PROVIDER_FAMILIES:
            continue
        affected = (
            int(summary.get("failed_source_count") or 0)
            + int(summary.get("fallback_source_count") or 0)
            + int(summary.get("rate_limited_source_count") or 0)
            + int(summary.get("settlement_auth_failure_source_count") or 0)
            + int(summary.get("unknown_source_count") or 0)
        )
        if int(summary.get("fresh_source_count") or 0) > 0 and affected == 0:
            healthy.append(family)
    return sorted(healthy)


def free_source_replacement_proof(families):
    healthy = set(healthy_free_source_families(families))
    missing_required = sorted(FREE_REPLACEMENT_REQUIRED_FAMILIES - healthy)
    has_observation = bool(healthy & FREE_REPLACEMENT_OBSERVATION_FAMILIES)
    has_guidance = bool(healthy & FREE_REPLACEMENT_GUIDANCE_FAMILIES)
    allowed = (
        len(healthy) >= FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES
        and not missing_required
        and has_observation
        and has_guidance
    )
    missing = []
    if missing_required:
        missing.append("local_history")
    if not has_observation:
        missing.append("metar_or_eccc_swob")
    if not has_guidance:
        missing.append("free_forecast_guidance")
    if len(healthy) < FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES:
        missing.append("minimum_three_healthy_free_families")
    reason = (
        "fresh free-source replacement covers local history, observations, and forecast guidance"
        if allowed
        else "missing " + ", ".join(missing)
    )
    return {
        "allowed": allowed,
        "reason": reason,
        "healthy_free_family_count": len(healthy),
        "healthy_free_families": sorted(healthy),
        "required_families": sorted(FREE_REPLACEMENT_REQUIRED_FAMILIES),
        "observation_families": sorted(FREE_REPLACEMENT_OBSERVATION_FAMILIES),
        "guidance_families": sorted(FREE_REPLACEMENT_GUIDANCE_FAMILIES),
        "min_healthy_free_families": FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES,
    }


def paid_provider_auth_only(summary):
    return bool(
        int(summary.get("settlement_auth_failure_source_count") or 0) > 0
        and int(summary.get("failed_source_count") or 0) == 0
        and int(summary.get("fallback_source_count") or 0) == 0
        and int(summary.get("rate_limited_source_count") or 0) == 0
        and int(summary.get("unknown_source_count") or 0) == 0
    )


def latest_source_status_rows(folder):
    path = Path(folder) / "source_status_long.csv"
    if not path.exists():
        return [], {"available": False, "reason": "source_status_long.csv missing"}
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [], {"available": False, "reason": "source_status_long.csv empty"}
    def row_sort_time(row):
        parsed = parse_times([row.get("captured_at_utc") or row.get("captured_at_local")])
        return parsed[0].timestamp() if parsed else float("-inf")
    latest = max(
        rows,
        key=row_sort_time,
    )
    latest_snapshot_id = latest.get("snapshot_id")
    latest_rows = [
        row for row in rows
        if row.get("snapshot_id") == latest_snapshot_id
    ]
    return latest_rows, {
        "available": True,
        "snapshot_id": latest_snapshot_id,
        "captured_at_utc": latest.get("captured_at_utc"),
        "captured_at_local": latest.get("captured_at_local"),
    }


def source_family_degradation(folder):
    folder = Path(folder)
    rows, metadata = latest_source_status_rows(folder)
    if not metadata.get("available"):
        return {
            **metadata,
            "families": {},
            "affected_family_count": 0,
            "blocking_family_count": 0,
            "failed_source_count": 0,
            "fallback_source_count": 0,
            "rate_limited_source_count": 0,
            "settlement_auth_failure_source_count": 0,
            "provider_cooldown_source_count": 0,
            "expected_unavailable_source_count": 0,
            "free_source_replacement": free_source_replacement_proof({}),
            "free_source_replacement_allowed": False,
            "claim_lane_allowance": {
                "model_review": False,
                "paper_trading": False,
                "live_trade_permission": False,
                "promotion_readiness": False,
            },
            "model_review_allowed": False,
            "trading_evidence_allowed": False,
            "live_trade_permission_allowed": False,
            "promotion_readiness_allowed": False,
            "repair_command": source_status_repair_command(folder),
            "verification_command": SOURCE_STATUS_VERIFY_COMMAND,
        }
    families = {}
    for row in rows:
        family = source_family_for_row(row)
        bucket = source_degradation_bucket(row)
        summary = families.setdefault(
            family,
            {
                "source_count": 0,
                "fresh_source_count": 0,
                "failed_source_count": 0,
                "fallback_source_count": 0,
                "rate_limited_source_count": 0,
                "settlement_auth_failure_source_count": 0,
                "provider_cooldown_source_count": 0,
                "expected_unavailable_source_count": 0,
                "unknown_source_count": 0,
                "sources": [],
                "fresh_sources": [],
                "failed_sources": [],
                "fallback_sources": [],
                "rate_limited_sources": [],
                "settlement_auth_failure_sources": [],
                "provider_cooldown_sources": [],
                "expected_unavailable_sources": [],
                "unknown_sources": [],
                "source_details": [],
            },
        )
        source = row.get("source")
        summary["source_count"] += 1
        summary["sources"].append(source)
        summary["source_details"].append(source_status_detail(row, bucket))
        if bucket == "fresh":
            summary["fresh_source_count"] += 1
            summary["fresh_sources"].append(source)
        elif bucket == "failed":
            summary["failed_source_count"] += 1
            summary["failed_sources"].append(source)
        elif bucket == "fallback":
            summary["fallback_source_count"] += 1
            summary["fallback_sources"].append(source)
        elif bucket == "rate_limited":
            summary["rate_limited_source_count"] += 1
            summary["rate_limited_sources"].append(source)
            if str(row.get("cache_status") or "").strip().lower() == "provider_cooldown":
                summary["provider_cooldown_source_count"] += 1
                summary["provider_cooldown_sources"].append(source)
        elif bucket == SETTLEMENT_AUTH_FAILURE_BUCKET:
            summary["settlement_auth_failure_source_count"] += 1
            summary["settlement_auth_failure_sources"].append(source)
        elif bucket == "expected_unavailable":
            summary["expected_unavailable_source_count"] += 1
            summary["expected_unavailable_sources"].append(source)
        else:
            summary["unknown_source_count"] += 1
            summary["unknown_sources"].append(source)
    affected_family_count = 0
    blocking_family_count = 0
    failed_source_count = 0
    fallback_source_count = 0
    rate_limited_source_count = 0
    settlement_auth_failure_source_count = 0
    provider_cooldown_source_count = 0
    expected_unavailable_source_count = 0
    free_replacement = free_source_replacement_proof(families)
    for family, summary in families.items():
        failed_source_count += summary["failed_source_count"]
        fallback_source_count += summary["fallback_source_count"]
        rate_limited_source_count += summary["rate_limited_source_count"]
        settlement_auth_failure_source_count += summary["settlement_auth_failure_source_count"]
        provider_cooldown_source_count += summary["provider_cooldown_source_count"]
        expected_unavailable_source_count += summary["expected_unavailable_source_count"]
        affected = (
            summary["failed_source_count"]
            + summary["fallback_source_count"]
            + summary["rate_limited_source_count"]
            + summary["settlement_auth_failure_source_count"]
            + summary["unknown_source_count"]
        )
        nonblocking_rate_limit_with_fresh_coverage = (
            affected
            and summary["fresh_source_count"] > 0
            and summary["failed_source_count"] == 0
            and summary["fallback_source_count"] == 0
            and summary["settlement_auth_failure_source_count"] == 0
            and summary["unknown_source_count"] == 0
            and summary["rate_limited_source_count"] > 0
        )
        paid_provider_replaced_for_paper = bool(
            free_replacement["allowed"]
            and family in PAID_WEATHER_PROVIDER_FAMILIES
            and paid_provider_auth_only(summary)
        )
        summary["free_source_replacement_covered"] = paid_provider_replaced_for_paper
        summary["trading_blocking"] = bool(
            affected
            and not nonblocking_rate_limit_with_fresh_coverage
            and not paid_provider_replaced_for_paper
        )
        if summary["settlement_auth_failure_source_count"]:
            summary["status"] = SETTLEMENT_SOURCE_AUTH_FAILURE
        elif nonblocking_rate_limit_with_fresh_coverage:
            summary["status"] = "rate_limited_with_fresh_family_coverage"
        elif summary["expected_unavailable_source_count"] and not affected:
            summary["status"] = "expected_current_day_unavailable"
        else:
            summary["status"] = "degraded" if affected else "healthy"
        if affected:
            affected_family_count += 1
        if summary["trading_blocking"]:
            blocking_family_count += 1
        summary["claim_lane_allowance"] = family_claim_lane_allowance(summary)
        summary["top_cache_states"] = dict(sorted(Counter(
            detail.get("cache_status") or "unknown"
            for detail in summary.get("source_details") or []
        ).items()))
        summary["max_cache_age_minutes"] = max(
            (
                detail.get("age_minutes")
                for detail in summary.get("source_details") or []
                if detail.get("age_minutes") is not None
            ),
            default=None,
        )
        summary["max_retry_after_seconds"] = max(
            (
                detail.get("retry_after_seconds")
                for detail in summary.get("source_details") or []
                if detail.get("retry_after_seconds") is not None
            ),
            default=None,
        )
    claim_lane_allowance = {
        "model_review": True,
        "paper_trading": blocking_family_count == 0,
        "live_trade_permission": all(
            (row.get("claim_lane_allowance") or {}).get("live_trade_permission")
            for row in families.values()
        ),
        "promotion_readiness": all(
            (row.get("claim_lane_allowance") or {}).get("promotion_readiness")
            for row in families.values()
        ),
    }
    result = {
        **metadata,
        "families": dict(sorted(families.items())),
        "affected_family_count": affected_family_count,
        "blocking_family_count": blocking_family_count,
        "failed_source_count": failed_source_count,
        "fallback_source_count": fallback_source_count,
        "rate_limited_source_count": rate_limited_source_count,
        "settlement_auth_failure_source_count": settlement_auth_failure_source_count,
        "provider_cooldown_source_count": provider_cooldown_source_count,
        "expected_unavailable_source_count": expected_unavailable_source_count,
        "free_source_replacement": free_replacement,
        "free_source_replacement_allowed": free_replacement["allowed"],
        "claim_lane_allowance": claim_lane_allowance,
        "model_review_allowed": True,
        "trading_evidence_allowed": blocking_family_count == 0,
        "live_trade_permission_allowed": claim_lane_allowance["live_trade_permission"],
        "promotion_readiness_allowed": claim_lane_allowance["promotion_readiness"],
        "repair_command": source_status_repair_command(folder),
        "verification_command": SOURCE_STATUS_VERIFY_COMMAND,
    }
    return result


def fleet_source_family_degradation_summary(markets):
    rows = [row.get("source_family_degradation") or {} for row in markets]
    available = [row for row in rows if row.get("available")]
    affected_by_family = Counter()
    blocking_by_family = Counter()
    cooldown_by_family = Counter()
    fallback_by_family = Counter()
    rate_limited_by_family = Counter()
    settlement_auth_by_family = Counter()
    expected_by_family = Counter()
    settlement_auth_markets = []
    for market in markets:
        source_status = market.get("source_family_degradation") or {}
        if not source_status.get("available"):
            continue
        auth_count = sum(
            int(family_row.get("settlement_auth_failure_source_count") or 0)
            for family_row in (source_status.get("families") or {}).values()
        )
        if auth_count:
            settlement_auth_markets.append(market.get("market_id"))
    for row in available:
        for family, family_row in (row.get("families") or {}).items():
            affected = (
                int(family_row.get("failed_source_count") or 0)
                + int(family_row.get("fallback_source_count") or 0)
                + int(family_row.get("rate_limited_source_count") or 0)
                + int(family_row.get("settlement_auth_failure_source_count") or 0)
                + int(family_row.get("unknown_source_count") or 0)
            )
            if affected:
                affected_by_family[family] += 1
            if family_row.get("trading_blocking"):
                blocking_by_family[family] += 1
            cooldown_by_family[family] += int(family_row.get("provider_cooldown_source_count") or 0)
            fallback_by_family[family] += int(family_row.get("fallback_source_count") or 0)
            rate_limited_by_family[family] += int(family_row.get("rate_limited_source_count") or 0)
            settlement_auth_by_family[family] += int(
                family_row.get("settlement_auth_failure_source_count") or 0
            )
            expected_by_family[family] += int(family_row.get("expected_unavailable_source_count") or 0)
    top_degraded_family = None
    if affected_by_family:
        top_degraded_family = affected_by_family.most_common(1)[0][0]

    def row_source_count(row, field):
        if row.get(field) is not None:
            return int(row.get(field) or 0)
        return sum(
            int(family_row.get(field) or 0)
            for family_row in (row.get("families") or {}).values()
        )

    summary = {
        "market_count": len(rows),
        "markets_with_source_status": len(available),
        "unknown_market_count": sum(1 for row in rows if not row.get("available")),
        "affected_market_count": sum(1 for row in available if row.get("affected_family_count", 0) > 0),
        "source_status_blocked_market_count": sum(
            1 for row in rows if not row.get("trading_evidence_allowed")
        ),
        "live_trade_permission_blocked_market_count": sum(
            1 for row in rows if not row.get("live_trade_permission_allowed")
        ),
        "promotion_readiness_blocked_market_count": sum(
            1 for row in rows if not row.get("promotion_readiness_allowed")
        ),
        "top_degraded_family": top_degraded_family,
        "affected_family_market_counts": dict(sorted(affected_by_family.items())),
        "blocking_family_market_counts": dict(sorted(blocking_by_family.items())),
        "provider_cooldown_family_source_counts": dict(sorted(cooldown_by_family.items())),
        "fallback_family_source_counts": dict(sorted(fallback_by_family.items())),
        "rate_limited_family_source_counts": dict(sorted(rate_limited_by_family.items())),
        "settlement_auth_failure_family_source_counts": dict(sorted(settlement_auth_by_family.items())),
        "expected_unavailable_family_source_counts": dict(sorted(expected_by_family.items())),
        "settlement_source_auth_failure_market_count": len(settlement_auth_markets),
        "settlement_source_auth_failure_markets": sorted(
            market for market in settlement_auth_markets if market
        ),
        "settlement_source_auth_failure_fleet_blocker": len(settlement_auth_markets) >= 2,
        "free_source_replacement_allowed_market_count": sum(
            1 for row in available if row.get("free_source_replacement_allowed")
        ),
        "affected_family_count": sum(int(row.get("affected_family_count") or 0) for row in available),
        "blocking_family_count": sum(int(row.get("blocking_family_count") or 0) for row in available),
        "failed_source_count": sum(row_source_count(row, "failed_source_count") for row in available),
        "fallback_source_count": sum(row_source_count(row, "fallback_source_count") for row in available),
        "rate_limited_source_count": sum(row_source_count(row, "rate_limited_source_count") for row in available),
        "settlement_auth_failure_source_count": sum(
            row_source_count(row, "settlement_auth_failure_source_count") for row in available
        ),
        "expected_unavailable_source_count": sum(
            row_source_count(row, "expected_unavailable_source_count") for row in available
        ),
        "provider_cooldown_source_count": sum(
            row_source_count(row, "provider_cooldown_source_count") for row in available
        ),
        "model_review_allowed": bool(available),
        "trading_evidence_allowed": bool(available) and all(
            row.get("trading_evidence_allowed") for row in available
        ),
        "live_trade_permission_allowed": bool(available) and all(
            row.get("live_trade_permission_allowed") for row in available
        ),
        "promotion_readiness_allowed": bool(available) and all(
            row.get("promotion_readiness_allowed") for row in available
        ),
    }
    paper_blocked = (
        int(summary["source_status_blocked_market_count"] or 0)
        + int(summary["unknown_market_count"] or 0)
    )
    strict_blocked = (
        int(summary["live_trade_permission_blocked_market_count"] or 0)
        + int(summary["promotion_readiness_blocked_market_count"] or 0)
    )
    if paper_blocked:
        if summary["unknown_market_count"]:
            root_cause = "missing_source_status"
        elif summary["settlement_source_auth_failure_fleet_blocker"]:
            root_cause = "settlement_source_auth_failure"
        elif summary["source_status_blocked_market_count"]:
            root_cause = "source_status_trading_blocked"
        elif summary["promotion_readiness_blocked_market_count"]:
            root_cause = "source_status_promotion_blocked"
        else:
            root_cause = "source_status_live_permission_blocked"
        status = "BLOCK"
        reason = (
            f"source status blocked: trading={summary['source_status_blocked_market_count']} "
            f"live={summary['live_trade_permission_blocked_market_count']} "
            f"promotion={summary['promotion_readiness_blocked_market_count']} "
            f"unknown={summary['unknown_market_count']}"
        )
    elif strict_blocked:
        if summary["settlement_source_auth_failure_fleet_blocker"]:
            root_cause = "settlement_source_auth_failure_optional_provider"
        elif summary["promotion_readiness_blocked_market_count"]:
            root_cause = "source_status_promotion_blocked"
        else:
            root_cause = "source_status_live_permission_blocked"
        status = "WARN"
        reason = (
            "source status allows paper trading evidence; stricter lanes remain blocked: "
            f"live={summary['live_trade_permission_blocked_market_count']} "
            f"promotion={summary['promotion_readiness_blocked_market_count']}"
        )
    else:
        root_cause = "source_status_clean"
        status = "PASS"
        reason = "source status available and allowed for trading/live/promotion lanes"
    summary.update({
        "status": status,
        "root_cause_class": root_cause,
        "reason": reason,
    })
    return summary


def source_status_market_proof(row):
    source_status = row.get("source_family_degradation") or {}
    affected = [
        {
            "family": family,
            "status": family_row.get("status"),
            "trading_blocking": family_row.get("trading_blocking"),
            "free_source_replacement_covered": family_row.get("free_source_replacement_covered"),
            "claim_lane_allowance": family_row.get("claim_lane_allowance") or {},
            "failed_source_count": family_row.get("failed_source_count"),
            "fallback_source_count": family_row.get("fallback_source_count"),
            "rate_limited_source_count": family_row.get("rate_limited_source_count"),
            "settlement_auth_failure_source_count": family_row.get("settlement_auth_failure_source_count"),
            "provider_cooldown_source_count": family_row.get("provider_cooldown_source_count"),
            "expected_unavailable_source_count": family_row.get("expected_unavailable_source_count"),
            "fallback_sources": family_row.get("fallback_sources") or [],
            "rate_limited_sources": family_row.get("rate_limited_sources") or [],
            "settlement_auth_failure_sources": family_row.get("settlement_auth_failure_sources") or [],
            "provider_cooldown_sources": family_row.get("provider_cooldown_sources") or [],
            "expected_unavailable_sources": family_row.get("expected_unavailable_sources") or [],
            "top_cache_states": family_row.get("top_cache_states") or {},
            "max_cache_age_minutes": family_row.get("max_cache_age_minutes"),
            "max_retry_after_seconds": family_row.get("max_retry_after_seconds"),
            "source_details": family_row.get("source_details") or [],
        }
        for family, family_row in sorted((source_status.get("families") or {}).items())
        if family_row.get("status") != "healthy"
    ]
    top_family = affected[0]["family"] if affected else None
    return {
        "market_id": row.get("market_id"),
        "event_slug": row.get("event_slug"),
        "target_date": row.get("target_date"),
        "available": source_status.get("available"),
        "snapshot_id": source_status.get("snapshot_id"),
        "captured_at_utc": source_status.get("captured_at_utc"),
        "captured_at_local": source_status.get("captured_at_local"),
        "reason": source_status.get("reason"),
        "claim_lane_allowance": source_status.get("claim_lane_allowance") or {},
        "model_review_allowed": source_status.get("model_review_allowed"),
        "paper_trading_allowed": source_status.get("trading_evidence_allowed"),
        "live_trade_permission_allowed": source_status.get("live_trade_permission_allowed"),
        "promotion_readiness_allowed": source_status.get("promotion_readiness_allowed"),
        "affected_family_count": source_status.get("affected_family_count", 0),
        "blocking_family_count": source_status.get("blocking_family_count", 0),
        "provider_cooldown_source_count": source_status.get("provider_cooldown_source_count", 0),
        "settlement_auth_failure_source_count": source_status.get("settlement_auth_failure_source_count", 0),
        "expected_unavailable_source_count": source_status.get("expected_unavailable_source_count", 0),
        "free_source_replacement": source_status.get("free_source_replacement") or {},
        "free_source_replacement_allowed": source_status.get("free_source_replacement_allowed"),
        "top_degraded_family": top_family,
        "affected_families": affected,
        "repair_command": source_status.get("repair_command"),
        "verification_command": source_status.get("verification_command"),
    }


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def row_sort_time(row):
    parsed = parse_times([row.get("captured_at_utc") or row.get("captured_at_local")])
    return parsed[0].timestamp() if parsed else float("-inf")


def latest_snapshot_rows(folder):
    path = Path(folder) / "snapshots_long.csv"
    rows = read_csv_rows(path)
    if not rows:
        return [], {"available": False, "reason": "snapshots_long.csv missing or empty", "path": str(path)}
    latest = max(rows, key=row_sort_time)
    snapshot_id = latest.get("snapshot_id")
    latest_rows = [row for row in rows if row.get("snapshot_id") == snapshot_id]
    return latest_rows, {
        "available": True,
        "snapshot_id": snapshot_id,
        "captured_at_utc": latest.get("captured_at_utc"),
        "captured_at_local": latest.get("captured_at_local"),
        "path": str(path),
    }


def _active_variant_ids(registry_path=DEFAULT_REGISTRY_PATH):
    registry = load_registry(registry_path)
    variants = active_live_variants(registry)
    return sorted(str(row.get("variant_id")) for row in variants if row.get("variant_id"))


def variant_prediction_tape_health(folder, registry_path=DEFAULT_REGISTRY_PATH):
    """Freshness check for the live active-variant prediction tape."""
    folder = Path(folder)
    snapshot_rows, snapshot_meta = latest_snapshot_rows(folder)
    if not snapshot_meta.get("available"):
        return {
            "available": False,
            "state": "MISSING",
            "action_required": True,
            "reason": snapshot_meta.get("reason"),
            "path": str(folder / "variant_predictions_long.csv"),
        }
    try:
        active_ids = _active_variant_ids(registry_path)
        registry_error = None
    except Exception as exc:  # noqa: BLE001 - collection health must remain reportable
        active_ids = []
        registry_error = f"{type(exc).__name__}: {exc}"
    if registry_error:
        return {
            "available": False,
            "state": "REGISTRY_ERROR",
            "action_required": True,
            "reason": f"variant registry unreadable: {registry_error}",
            "path": str(folder / "variant_predictions_long.csv"),
            "snapshot_id": snapshot_meta.get("snapshot_id"),
        }
    if not active_ids:
        return {
            "available": True,
            "state": "OK",
            "action_required": False,
            "reason": "no active variants require live rows",
            "path": str(folder / "variant_predictions_long.csv"),
            "snapshot_id": snapshot_meta.get("snapshot_id"),
            "active_variant_count": 0,
        }

    path = folder / "variant_predictions_long.csv"
    rows = read_csv_rows(path)
    if not rows:
        return {
            "available": False,
            "state": "MISSING",
            "action_required": True,
            "reason": "variant_predictions_long.csv missing or empty",
            "path": str(path),
            "snapshot_id": snapshot_meta.get("snapshot_id"),
            "active_variant_count": len(active_ids),
        }
    latest_snapshot_id = snapshot_meta.get("snapshot_id")
    latest_rows = [row for row in rows if row.get("snapshot_id") == latest_snapshot_id]
    serving_band_count = len(snapshot_rows)
    expected_rows = len(active_ids) * serving_band_count
    statuses = Counter(str(row.get("prediction_status") or "missing").lower() for row in latest_rows)
    present_ids = sorted({row.get("variant_id") for row in latest_rows if row.get("variant_id")})
    missing_ids = sorted(set(active_ids) - set(present_ids))
    invalid_status_rows = sum(
        count
        for status, count in statuses.items()
        if status not in {"predicted", "skipped", "failed"}
    )
    ok = bool(latest_rows) and not missing_ids and len(latest_rows) >= expected_rows and invalid_status_rows == 0
    reasons = []
    if not latest_rows:
        reasons.append("latest serving snapshot has no variant rows")
    if missing_ids:
        reasons.append("missing active variants: " + ", ".join(missing_ids))
    if len(latest_rows) < expected_rows:
        reasons.append(f"{len(latest_rows)}/{expected_rows} expected latest variant-band rows")
    if invalid_status_rows:
        reasons.append(f"{invalid_status_rows} rows have invalid prediction_status")
    return {
        "available": True,
        "state": "OK" if ok else "STALE",
        "action_required": not ok,
        "reason": "; ".join(reasons) if reasons else "latest active-variant rows are fresh",
        "path": str(path),
        "snapshot_id": latest_snapshot_id,
        "captured_at_utc": snapshot_meta.get("captured_at_utc"),
        "captured_at_local": snapshot_meta.get("captured_at_local"),
        "active_variant_count": len(active_ids),
        "active_variant_ids": active_ids,
        "present_variant_ids": present_ids,
        "missing_variant_ids": missing_ids,
        "serving_band_count": serving_band_count,
        "expected_latest_rows": expected_rows,
        "latest_rows": len(latest_rows),
        "status_counts": dict(sorted(statuses.items())),
    }


def fleet_variant_prediction_tape_summary(markets):
    rows = [row.get("variant_prediction_tape") or {} for row in markets]
    return {
        "market_count": len(rows),
        "markets_with_variant_tape": sum(1 for row in rows if row.get("available")),
        "action_required": sum(1 for row in rows if row.get("action_required")),
        "missing_or_stale_market_count": sum(
            1 for row in rows if row.get("state") in {"MISSING", "STALE", "REGISTRY_ERROR"}
        ),
        "active_variant_count": max((int(row.get("active_variant_count") or 0) for row in rows), default=0),
    }


def fleet_snapshot_cadence_proof_summary(markets):
    rows = [row.get("snapshot_cadence_proof") or {} for row in markets]
    root_causes = Counter(row.get("root_cause") or "unknown" for row in rows)
    blocked = [row for row in rows if row.get("status") != "PASS"]
    gap_rows = [row for row in rows if int(row.get("gap_count") or 0) > 0]
    max_gaps = [
        float(row.get("max_gap_minutes"))
        for row in rows
        if row.get("max_gap_minutes") is not None
    ]
    return {
        "status": "PASS" if not blocked else "BLOCK",
        "market_count": len(rows),
        "blocked_market_count": len(blocked),
        "snapshot_coverage_gap_market_count": len(gap_rows),
        "total_gap_count": sum(int(row.get("gap_count") or 0) for row in rows),
        "max_gap_minutes": max(max_gaps) if max_gaps else None,
        "root_cause_counts": dict(sorted(root_causes.items())),
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
    }


def fleet_early_hour_coverage_summary(markets):
    rows = [row.get("early_hour_coverage") or {} for row in markets]
    blocked = [row for row in rows if row.get("status") != "PASS"]
    gap_rows = [row for row in rows if int(row.get("gap_count") or 0) > 0]
    max_gaps = [
        float(row.get("max_gap_minutes"))
        for row in rows
        if row.get("max_gap_minutes") is not None
    ]
    status_counts = Counter(row.get("status") or "MISSING" for row in rows)
    first_blocker = next((row for row in rows if row.get("status") != "PASS"), {})
    return {
        "status": "PASS" if not blocked else "BLOCK",
        "market_count": len(rows),
        "countable_market_count": sum(
            1 for row in rows if row.get("counts_toward_early_hour_evidence")
        ),
        "blocked_market_count": len(blocked),
        "early_hour_coverage_blocked_market_count": len(blocked),
        "status_counts": dict(sorted(status_counts.items())),
        "total_snapshot_count": sum(int(row.get("snapshot_count") or 0) for row in rows),
        "expected_snapshot_count": sum(int(row.get("expected_snapshot_count") or 0) for row in rows),
        "minimum_snapshot_count": sum(int(row.get("minimum_snapshot_count") or 0) for row in rows),
        "total_missing_snapshot_count": sum(int(row.get("missing_snapshot_count") or 0) for row in rows),
        "total_gap_count": sum(int(row.get("gap_count") or 0) for row in rows),
        "gap_market_count": len(gap_rows),
        "max_gap_minutes": max(max_gaps) if max_gaps else None,
        "first_blocking_market": first_blocker.get("market_id"),
        "first_blocking_reason": first_blocker.get("reason"),
        "counts_toward_early_hour_evidence": not blocked,
        "next_unblock_action": (
            "none"
            if not blocked
            else "collect next active day with countable 00:00-08:00 snapshot coverage"
        ),
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
    }


def fleet_capture_liveness(markets, interval_minutes=10.0):
    """Is data flowing right now for every market that *should* be capturing?

    This is the signal a live monitor (heartbeat) must alarm on -- and the one
    that was missing during the 2026-06-27 false alarm, where a naive
    fleet-newest-mtime check could neither see a single dark market nor tell a
    genuine outage from a market that simply has not reached its capture window.

    Two timezone/cadence pitfalls it is built to avoid -- the exact two that
    produced false reads that day:

      1. Pre-window quiet. A market whose settlement (afternoon) window has not
         started yet is PENDING -- expected quiet, never an alarm. This is what
         each western market is in during the pre-dawn UTC hours, when measuring
         gaps in UTC cried wolf.
      2. End-of-sleep jitter. The loop captures all markets sequentially then
         sleeps ~one interval, so right before a new cycle the markets captured
         early last cycle are legitimately ~1.x intervals old. Alarming at the
         per-market AT_RISK SLA (1.5x interval) would fire every sleep cycle.

    So a market is only "dark" when its latest capture is older than
    ``2 * interval + slack`` (it has actually missed multiple cycles), mirroring
    the loop's own dead-detection threshold. Source-auth and other degradations
    are reported separately and deliberately do not fire this alarm: this is
    about capture liveness only.
    """
    # Mirror loop_health's dead_after = 2*interval + 2: a market is dark only
    # once it has missed ~two full capture cycles, not on normal sleep jitter.
    stale_after = 2.0 * float(interval_minutes) + 2.0
    pending, healthy, stale = [], [], []
    # Window-open states from live_coverage_summary: COLLECTING (in-window, on
    # cadence) and AT_RISK (window started, something off). PENDING is pre-window
    # and CLEAN/PARTIAL are post-window -- neither is a live "going dark" alarm.
    open_window_states = {"COLLECTING", "AT_RISK"}
    for row in markets:
        state = str(row.get("state") or "").upper()
        age = row.get("latest_age_minutes")
        market_id = row.get("market_id")
        if state == "PENDING":
            pending.append(market_id)
            continue
        if state in open_window_states:
            is_dark = age is None or age > stale_after
            if is_dark:
                stale.append({
                    "market_id": market_id,
                    "state": state,
                    "latest_age_minutes": age,
                })
            else:
                healthy.append(market_id)
            continue
        # CLEAN / PARTIAL (post-window), MISSING, or anything else: not a live
        # capture-liveness alarm. Coverage quality for these is reported by the
        # cadence and early-hour proofs.
        healthy.append(market_id)
    return {
        "schema_version": "fleet_capture_liveness_v0.1",
        "status": "OK" if not stale else "STALE",
        "stale_after_minutes": round(stale_after, 1),
        "market_count": len(markets),
        "healthy_market_count": len(healthy),
        "pending_market_count": len(pending),
        "stale_market_count": len(stale),
        "stale_markets": stale,
        "pending_markets": pending,
        "reason": (
            "all in-window markets are capturing on cadence"
            if not stale
            else f"{len(stale)} market(s) dark (>{round(stale_after)}min) inside an open "
            "capture window: " + ", ".join(str(row["market_id"]) for row in stale)
        ),
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
    }


def fleet_collection_health(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    live=True,
    as_of=None,
    target_date=None,
):
    freshness_sla = float(interval_minutes) * float(tolerance)
    target_date = ensure_date(target_date) if target_date is not None else None
    markets = []
    for spec in all_specs():
        folder = latest_market_folder(spec, snapshots_root=snapshots_root, target_date=target_date)
        if folder is None:
            expected_config = config_for_date(target_date, spec.id) if target_date is not None else None
            missing_summary = {
                "state": "MISSING",
                "action_required": True,
                "clean": False,
                "n": 0,
                "reason": "no snapshot tape found",
            }
            cadence_proof = snapshot_cadence_proof(
                missing_summary,
                freshness_sla_minutes=freshness_sla,
            )
            early_hour_coverage = early_hour_coverage_summary(
                [],
                interval_minutes,
                tolerance,
                target_date=target_date,
                as_of=as_of,
                native_tz=spec.tz,
            )
            markets.append({
                "market_id": spec.id,
                "city": spec.city_label,
                "unit": spec.display_unit,
                "event_slug": expected_config.event_slug if expected_config else None,
                "target_date": expected_config.target_date.isoformat() if expected_config else None,
                "state": "MISSING",
                "action_required": True,
                "snapshot_action_required": True,
                "freshness_sla_minutes": freshness_sla,
                "reason": "no snapshot tape found",
                "snapshots": 0,
                "snapshot_cadence_proof": cadence_proof,
                "early_hour_coverage": early_hour_coverage,
            })
            continue
        summary = summarize_folder(
            folder,
            interval_minutes=interval_minutes,
            tolerance=tolerance,
            live=live,
            as_of=as_of,
        )
        source_degradation = source_family_degradation(folder)
        variant_prediction_tape = summary.get("variant_prediction_tape") or {}
        snapshot_action_required = bool(summary.get("action_required", not summary.get("clean")))
        action_required = snapshot_action_required or bool(variant_prediction_tape.get("action_required"))
        markets.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "unit": spec.display_unit,
            "state": summary.get("state") or ("CLEAN" if summary.get("clean") else "CHECK"),
            "action_required": action_required,
            "snapshot_action_required": snapshot_action_required,
            "freshness_sla_minutes": freshness_sla,
            "latest_age_minutes": summary.get("latest_age_minutes"),
            "event_slug": summary.get("event_slug"),
            "folder": summary.get("folder"),
            "target_date": folder_target_date(folder).isoformat(),
            "snapshots": summary.get("n", 0),
            "capture_ratio": summary.get("capture_ratio"),
            "max_gap_minutes": summary.get("max_gap_minutes"),
            "reason": summary.get("reason"),
            "latest_snapshot_id": summary.get("latest_snapshot_id"),
            "latest_snapshot_at_utc": summary.get("latest_snapshot_at_utc"),
            "latest_snapshot_at_local": summary.get("latest_snapshot_at_local"),
            "snapshot_cadence_proof": summary.get("snapshot_cadence_proof") or {},
            "early_hour_coverage": summary.get("early_hour_coverage") or {},
            "source_family_degradation": source_degradation,
            "variant_prediction_tape": variant_prediction_tape,
        })
    source_family_summary = fleet_source_family_degradation_summary(markets)
    variant_tape_summary = fleet_variant_prediction_tape_summary(markets)
    cadence_summary = fleet_snapshot_cadence_proof_summary(markets)
    early_hour_summary = fleet_early_hour_coverage_summary(markets)
    capture_liveness = fleet_capture_liveness(markets, interval_minutes=interval_minutes)
    source_status_markets = [source_status_market_proof(row) for row in markets]
    return {
        "schema_version": "fleet_collection_health_v0.1",
        "snapshots_root": str(snapshots_root),
        "interval_minutes": float(interval_minutes),
        "tolerance": float(tolerance),
        "freshness_sla_minutes": freshness_sla,
        "markets": markets,
        "snapshot_cadence_proof": {
            "summary": cadence_summary,
            "markets": [
                {
                    "market_id": row.get("market_id"),
                    "event_slug": row.get("event_slug"),
                    "target_date": row.get("target_date"),
                    **(row.get("snapshot_cadence_proof") or {}),
                }
                for row in markets
            ],
        },
        "early_hour_coverage_proof": {
            "schema_version": "fleet_early_hour_coverage_proof_v0.1",
            "summary": early_hour_summary,
            "markets": [
                {
                    "market_id": row.get("market_id"),
                    "event_slug": row.get("event_slug"),
                    "target_date": row.get("target_date"),
                    **(row.get("early_hour_coverage") or {}),
                }
                for row in markets
            ],
            "status_command": SNAPSHOT_STATUS_COMMAND,
            "repair_command": SNAPSHOT_RESTART_COMMAND,
            "verification_command": SNAPSHOT_FLEET_VERIFY_COMMAND,
        },
        "source_status_proof": {
            "schema_version": SOURCE_STATUS_PROOF_SCHEMA_VERSION,
            "status": source_family_summary.get("status"),
            "root_cause_class": source_family_summary.get("root_cause_class"),
            "reason": source_family_summary.get("reason"),
            "summary": source_family_summary,
            "markets": source_status_markets,
            "repair_command": SOURCE_STATUS_BULK_REPAIR_COMMAND,
            "verification_command": SOURCE_STATUS_VERIFY_COMMAND,
        },
        "summary": {
            "market_count": len(markets),
            "action_required": sum(1 for row in markets if row.get("action_required")),
            "states": {
                state: sum(1 for row in markets if row.get("state") == state)
                for state in sorted({row.get("state") for row in markets})
            },
            "source_family_degradation": source_family_summary,
            "source_status_proof": source_family_summary,
            "variant_prediction_tape": variant_tape_summary,
            "snapshot_cadence_proof": cadence_summary,
            "early_hour_coverage_proof": early_hour_summary,
            "capture_liveness": capture_liveness,
        },
        "capture_liveness": capture_liveness,
    }


def serialize_summary(summary):
    out = {}
    for key, value in summary.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif key == "gaps":
            out[key] = [
                {
                    "after": item.get("after").isoformat() if isinstance(item.get("after"), datetime) else item.get("after"),
                    "before": item.get("before").isoformat() if isinstance(item.get("before"), datetime) else item.get("before"),
                    "gap_minutes": item.get("gap_minutes"),
                }
                for item in value
            ]
        else:
            out[key] = value
    return out


def snapshot_times(tape_path):
    """Unique capture timestamps (one per snapshot) from a snapshots_long.csv."""
    seen, times = set(), []
    with open(tape_path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = row.get("snapshot_id")
            ts = row.get("captured_at_local")
            if sid and sid not in seen and ts:
                seen.add(sid)
                times.append(ts)
    return parse_times(times)


def main():
    parser = argparse.ArgumentParser(description="Report snapshot-collection health and gaps.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    parser.add_argument("--live", action="store_true", help="Evaluate as an in-progress live market day.")
    parser.add_argument("--fleet", action="store_true", help="Report one latest collection-health row per market.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any tape needs attention.")
    args = parser.parse_args()

    if args.fleet:
        payload = fleet_collection_health(
            snapshots_root=args.snapshots_root,
            interval_minutes=args.interval_minutes,
            tolerance=args.tolerance,
            live=args.live,
        )
        any_attention = any(row.get("action_required") for row in payload["markets"])
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                f"Fleet collection health: {payload['summary']['market_count']} markets, "
                f"{payload['summary']['action_required']} need attention"
            )
            for row in payload["markets"]:
                print(
                    f"[{row['state']}] {row['market_id']}: "
                    f"{row.get('event_slug') or '-'}; "
                    f"{row.get('snapshots', 0)} snapshots -> {row.get('reason')}"
                )
        if args.strict and any_attention:
            sys.exit(2)
        return

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    summaries = []
    any_attention = False
    for folder in folders:
        folder_path = Path(folder)
        tape = folder_path / "snapshots_long.csv"
        if not tape.exists():
            continue
        summary = summarize_folder(folder_path, args.interval_minutes, args.tolerance, live=args.live)
        summaries.append(summary)
        if summary.get("action_required", not summary.get("clean")):
            any_attention = True

    if args.json:
        print(json.dumps([serialize_summary(item) for item in summaries], indent=2, sort_keys=True))
        if args.strict and any_attention:
            sys.exit(2)
        return

    for summary in summaries:
        name = summary["event_slug"]
        if summary["n"] == 0:
            flag = summary.get("state") or "EMPTY"
            print(f"[{flag}] {name}: no captures -> {summary['reason']}")
            continue
        flag = summary.get("state") or ("CLEAN" if summary["clean"] else "CHECK")
        print(f"[{flag}] {name}: {summary['n']} snapshots "
              f"{summary['first']:%H:%M}-{summary['last']:%H:%M}, "
              f"capture {summary['capture_ratio'] * 100:.0f}% of expected, "
              f"max gap {summary['max_gap_minutes']:.0f} min -> {summary['reason']}")
        for g in summary.get("gaps") or []:
            print(f"         gap {g['gap_minutes']:.0f} min: {g['after']:%H:%M} -> {g['before']:%H:%M}")
    if any_attention:
        print("\nSome days are not clean; treat their backtest contributions with caution.")
    if args.strict and any_attention:
        sys.exit(2)


if __name__ == "__main__":
    main()
