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
from datetime import datetime, time as dt_time
from pathlib import Path

from weather.paths import data_path

from weather.collection.live_variant_predictions import active_live_variants
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import all_specs, spec_for_slug
from weather.reporting.variant_registry import DEFAULT_REGISTRY_PATH, load_registry

DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
# Settlement-decisive window: a clean day should span at least this local range.
AFTERNOON_START_HOUR = 12
AFTERNOON_END_HOUR = 18
OPEN_METEO_SOURCE_FAMILY = {
    "open_meteo",
    "open_meteo_multimodel",
    "global_ensemble",
    "eccc_gem",
}


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
    times = snapshot_times(tape) if tape.exists() else []
    target_date = folder_target_date(folder)
    summary = (
        live_coverage_summary(times, interval_minutes, tolerance, as_of=as_of, target_date=target_date)
        if live
        else coverage_summary(times, interval_minutes, tolerance, target_date=target_date)
    )
    summary["event_slug"] = folder.name
    summary["folder"] = str(folder)
    summary["tape_path"] = str(tape)
    summary["variant_prediction_tape"] = variant_prediction_tape_health(folder)
    return summary


def latest_market_folder(spec, snapshots_root=DEFAULT_SNAPSHOTS_ROOT):
    root = Path(snapshots_root)
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
            "provider_cooldown_source_count": 0,
            "model_review_allowed": False,
            "trading_evidence_allowed": False,
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
                "provider_cooldown_source_count": 0,
                "unknown_source_count": 0,
                "sources": [],
                "fresh_sources": [],
                "failed_sources": [],
                "fallback_sources": [],
                "rate_limited_sources": [],
                "provider_cooldown_sources": [],
                "unknown_sources": [],
            },
        )
        source = row.get("source")
        summary["source_count"] += 1
        summary["sources"].append(source)
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
        else:
            summary["unknown_source_count"] += 1
            summary["unknown_sources"].append(source)
    affected_family_count = 0
    blocking_family_count = 0
    failed_source_count = 0
    fallback_source_count = 0
    rate_limited_source_count = 0
    provider_cooldown_source_count = 0
    for summary in families.values():
        failed_source_count += summary["failed_source_count"]
        fallback_source_count += summary["fallback_source_count"]
        rate_limited_source_count += summary["rate_limited_source_count"]
        provider_cooldown_source_count += summary["provider_cooldown_source_count"]
        affected = (
            summary["failed_source_count"]
            + summary["fallback_source_count"]
            + summary["rate_limited_source_count"]
            + summary["unknown_source_count"]
        )
        nonblocking_rate_limit_with_fresh_coverage = (
            affected
            and summary["fresh_source_count"] > 0
            and summary["failed_source_count"] == 0
            and summary["fallback_source_count"] == 0
            and summary["unknown_source_count"] == 0
            and summary["rate_limited_source_count"] > 0
        )
        summary["trading_blocking"] = bool(affected and not nonblocking_rate_limit_with_fresh_coverage)
        if nonblocking_rate_limit_with_fresh_coverage:
            summary["status"] = "rate_limited_with_fresh_family_coverage"
        else:
            summary["status"] = "degraded" if affected else "healthy"
        if affected:
            affected_family_count += 1
        if summary["trading_blocking"]:
            blocking_family_count += 1
    return {
        **metadata,
        "families": dict(sorted(families.items())),
        "affected_family_count": affected_family_count,
        "blocking_family_count": blocking_family_count,
        "failed_source_count": failed_source_count,
        "fallback_source_count": fallback_source_count,
        "rate_limited_source_count": rate_limited_source_count,
        "provider_cooldown_source_count": provider_cooldown_source_count,
        "model_review_allowed": True,
        "trading_evidence_allowed": blocking_family_count == 0,
    }


def fleet_source_family_degradation_summary(markets):
    rows = [row.get("source_family_degradation") or {} for row in markets]
    available = [row for row in rows if row.get("available")]
    return {
        "market_count": len(rows),
        "markets_with_source_status": len(available),
        "unknown_market_count": sum(1 for row in rows if not row.get("available")),
        "affected_market_count": sum(1 for row in available if row.get("affected_family_count", 0) > 0),
        "affected_family_count": sum(int(row.get("affected_family_count") or 0) for row in available),
        "blocking_family_count": sum(int(row.get("blocking_family_count") or 0) for row in available),
        "failed_source_count": sum(int(row.get("failed_source_count") or 0) for row in available),
        "fallback_source_count": sum(int(row.get("fallback_source_count") or 0) for row in available),
        "rate_limited_source_count": sum(int(row.get("rate_limited_source_count") or 0) for row in available),
        "provider_cooldown_source_count": sum(
            int(row.get("provider_cooldown_source_count") or 0) for row in available
        ),
        "model_review_allowed": bool(available),
        "trading_evidence_allowed": bool(available) and all(
            row.get("trading_evidence_allowed") for row in available
        ),
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


def fleet_collection_health(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    live=True,
    as_of=None,
):
    freshness_sla = float(interval_minutes) * float(tolerance)
    markets = []
    for spec in all_specs():
        folder = latest_market_folder(spec, snapshots_root=snapshots_root)
        if folder is None:
            markets.append({
                "market_id": spec.id,
                "city": spec.city_label,
                "unit": spec.display_unit,
                "state": "MISSING",
                "action_required": True,
                "freshness_sla_minutes": freshness_sla,
                "reason": "no snapshot tape found",
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
            "source_family_degradation": source_degradation,
            "variant_prediction_tape": variant_prediction_tape,
        })
    source_family_summary = fleet_source_family_degradation_summary(markets)
    variant_tape_summary = fleet_variant_prediction_tape_summary(markets)
    return {
        "schema_version": "fleet_collection_health_v0.1",
        "snapshots_root": str(snapshots_root),
        "interval_minutes": float(interval_minutes),
        "tolerance": float(tolerance),
        "freshness_sla_minutes": freshness_sla,
        "markets": markets,
        "summary": {
            "market_count": len(markets),
            "action_required": sum(1 for row in markets if row.get("action_required")),
            "states": {
                state: sum(1 for row in markets if row.get("state") == state)
                for state in sorted({row.get("state") for row in markets})
            },
            "source_family_degradation": source_family_summary,
            "variant_prediction_tape": variant_tape_summary,
        },
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
