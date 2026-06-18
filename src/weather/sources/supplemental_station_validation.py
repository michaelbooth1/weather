"""Validation reports and promotion gates for supplemental nearby stations."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.market.market_registry import all_specs, spec_for_id
from weather.sources.daily_summary import native_bucket, native_high
from weather.sources.supplemental_stations import (
    DEFAULT_REGISTRY_PATH,
    guard_not_canonical_root,
    load_registry,
    source_root,
    supplemental_sources,
)
from weather.paths import REPO_ROOT, relative_to_repo
from weather.units import round_half_up


VALIDATION_SCHEMA_VERSION = "supplemental_station_validation_v0.1"
DEFAULT_OUT = REPO_ROOT / "data" / "backtest" / "supplemental_station_validation.json"
DEFAULT_REPORT = REPO_ROOT / "data" / "backtest" / "supplemental_station_validation_report.md"
PROMOTION_STATES = {
    "candidate",
    "validated_supplemental",
    "shadow_only",
    "rejected",
    "retired",
}

REFERENCE_SOURCES = {
    "wu": {"label": "WU settlement history", "required": True, "weak": False},
    "metar": {"label": "METAR/ASOS", "required": True, "weak": False},
    "ghcnh": {"label": "canonical GHCNh", "required": False, "weak": False},
    "reanalysis": {"label": "ERA5-style reanalysis", "required": False, "weak": True},
}

DEFAULT_THRESHOLD_PROFILES = {
    ("C", "supplemental"): {
        "min_full_overlap_days": 365,
        "min_target_season_overlap_days": 100,
        "min_regime_overlap_days": 30,
        "min_missing_day_reduction": 1,
        "max_full_period_mae": 1.0,
        "max_target_season_mae": 0.75,
        "max_regime_mae": 1.0,
        "min_bucket_match_rate": 0.97,
        "max_abs_difference": 3.0,
        "max_distance_km": 10.0,
        "max_elevation_mismatch_m": 100.0,
        "max_weak_reference_mae": 2.0,
    },
    ("F", "supplemental"): {
        "min_full_overlap_days": 365,
        "min_target_season_overlap_days": 100,
        "min_regime_overlap_days": 30,
        "min_missing_day_reduction": 1,
        "max_full_period_mae": 1.8,
        "max_target_season_mae": 1.5,
        "max_regime_mae": 1.8,
        "min_bucket_match_rate": 0.97,
        "max_abs_difference": 5.0,
        "max_distance_km": 10.0,
        "max_elevation_mismatch_m": 100.0,
        "max_weak_reference_mae": 3.0,
    },
}


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iter_dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def season_dates(start, end, start_month=5, start_day=20, end_month=6, end_day=30):
    days = []
    for year in range(start.year, end.year + 1):
        lo = max(start, date(year, start_month, start_day))
        hi = min(end, date(year, end_month, end_day))
        if lo <= hi:
            days.extend(iter_dates(lo, hi))
    return days


def safe_float(value):
    if value in (None, "", "None", "null", "NaN"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number <= -999:
        return None
    return number


def pct(part, total):
    return float(part) / float(total) if total else None


def source_fingerprint(source):
    fields = {
        key: source.get(key)
        for key in (
            "market_id",
            "source_id",
            "source_type",
            "source_role",
            "station_id",
            "station_name",
            "root_path",
            "latitude",
            "longitude",
            "elevation_m",
            "distance_from_canonical_km",
            "canonical_market_id",
            "canonical_station_id",
            "adopted_date_windows",
        )
    }
    blob = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def threshold_profile(unit, source_role="supplemental", overrides=None):
    unit = unit or "C"
    source_role = source_role or "supplemental"
    profile = dict(
        DEFAULT_THRESHOLD_PROFILES.get((unit, source_role))
        or DEFAULT_THRESHOLD_PROFILES.get((unit, "supplemental"))
        or DEFAULT_THRESHOLD_PROFILES[("C", "supplemental")]
    )
    overrides = overrides or {}
    if isinstance(overrides, dict):
        profile.update(overrides.get(f"{unit}:{source_role}") or {})
        profile.update(overrides.get(unit) or {})
        profile.update(overrides.get(source_role) or {})
        profile.update({key: value for key, value in overrides.items() if key in profile})
    return profile


def daily_summary_path(source_name, spec):
    station = spec.icao.lower()
    if source_name == "wu":
        return REPO_ROOT / "data" / "wunderground" / station / "daily" / "daily_summary.csv"
    if source_name == "metar":
        return REPO_ROOT / "data" / "metar" / station / "daily" / "daily_summary.csv"
    if source_name == "ghcnh":
        return REPO_ROOT / "data" / "noaa_ghcnh" / station / "daily" / "daily_summary.csv"
    if source_name == "reanalysis":
        return REPO_ROOT / "data" / "reanalysis" / station / "daily" / "daily_summary.csv"
    raise KeyError(source_name)


def daily_value_rows(path):
    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("local_date") or row.get("date")
            if not value:
                continue
            try:
                local_date = date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
            high = native_high(row)
            if high is None:
                high = safe_float(row.get("high"))
            if high is None:
                continue
            bucket = native_bucket(row)
            if bucket is None:
                bucket = safe_float(row.get("bucket"))
            rows[local_date] = {
                "high": high,
                "bucket": int(bucket) if bucket is not None else round_half_up(high),
            }
    return rows


def date_coverage(rows, expected_dates):
    expected = set(expected_dates or [])
    covered = set(rows) & expected if expected else set(rows)
    missing = sorted(expected - set(rows)) if expected else []
    return {
        "expected_days": len(expected),
        "covered_days": len(covered),
        "missing_days": len(missing),
        "coverage_rate": pct(len(covered), len(expected)) if expected else None,
        "first_covered": min(rows).isoformat() if rows else None,
        "last_covered": max(rows).isoformat() if rows else None,
        "sample_missing": [item.isoformat() for item in missing[:10]],
    }


def regime_for_high(high, unit):
    high = safe_float(high)
    if high is None:
        return None
    if unit == "F":
        if high < 68:
            return "cool"
        if high < 82:
            return "mild"
        return "hot"
    if high < 20:
        return "cool"
    if high < 28:
        return "mild"
    return "hot"


def compare_high_rows(candidate, reference, expected_dates=None, unit="C", regime=None):
    if expected_dates:
        expected = set(expected_dates)
    else:
        expected = set(candidate) | set(reference)
    overlap = sorted(set(candidate) & set(reference) & expected)
    diffs = []
    bucket_matches = []
    for local_date in overlap:
        candidate_row = candidate[local_date]
        reference_row = reference[local_date]
        if regime and regime_for_high(reference_row.get("high"), unit) != regime:
            continue
        candidate_high = safe_float(candidate_row.get("high"))
        reference_high = safe_float(reference_row.get("high"))
        if candidate_high is None or reference_high is None:
            continue
        diffs.append(candidate_high - reference_high)
        candidate_bucket = candidate_row.get("bucket")
        reference_bucket = reference_row.get("bucket")
        if candidate_bucket is not None and reference_bucket is not None:
            bucket_matches.append(int(candidate_bucket) == int(reference_bucket))
    if not diffs:
        return {"days": 0}
    return {
        "days": len(diffs),
        "mean_bias": round(sum(diffs) / len(diffs), 4),
        "mae": round(sum(abs(diff) for diff in diffs) / len(diffs), 4),
        "max_abs": round(max(abs(diff) for diff in diffs), 4),
        "candidate_exceeds_rate": round(sum(1 for diff in diffs if diff > 0) / len(diffs), 4),
        "candidate_misses_rate": round(sum(1 for diff in diffs if diff < 0) / len(diffs), 4),
        "bucket_match_rate": (
            round(sum(1 for match in bucket_matches if match) / len(bucket_matches), 4)
            if bucket_matches else None
        ),
    }


def station_metadata(root):
    root = Path(root)
    for name in ("station.json", "manifest.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if name == "station.json":
            return payload if isinstance(payload, dict) else {}
        station = (payload.get("metadata") or {}).get("station") if isinstance(payload, dict) else None
        if isinstance(station, dict):
            return station
    return {}


def station_elevation_m(source, root):
    value = safe_float(source.get("elevation_m"))
    if value is not None:
        return value
    station = station_metadata(root)
    return safe_float(station.get("ELEVATION") or station.get("elevation_m") or station.get("elevation"))


def gate_result(name, severity, ok, evidence, threshold=None, action=None):
    return {
        "name": name,
        "severity": severity,
        "ok": bool(ok),
        "status": "PASS" if ok else severity.upper(),
        "evidence": evidence,
        "threshold": threshold,
        "action": action,
    }


def metric_gates(reference_name, period_name, metrics, thresholds, *, required=True, weak=False, regime=None):
    gates = []
    min_days = (
        thresholds["min_target_season_overlap_days"]
        if period_name == "target_season"
        else thresholds["min_full_overlap_days"]
    )
    if regime:
        min_days = thresholds["min_regime_overlap_days"]
    days = int(metrics.get("days") or 0)
    severity = "warn" if weak else "hard"
    diagnostic_only = period_name == "full_period" and not regime
    metric_severity = "warn" if diagnostic_only else severity
    if not required and days < min_days:
        return [
            gate_result(
                f"{reference_name}_{period_name}{'_' + regime if regime else ''}_overlap",
                "warn",
                True,
                f"{days} overlap days; optional reference has insufficient coverage for gating.",
                threshold=f">= {min_days} days when available",
            )
        ]
    gates.append(gate_result(
        f"{reference_name}_{period_name}{'_' + regime if regime else ''}_overlap",
        severity,
        days >= min_days,
        f"{days} overlap days.",
        threshold=f">= {min_days} days",
        action="Backfill more overlap or keep this supplemental source out of promoted feature sets.",
    ))
    if days < min_days:
        return gates

    mae_limit = thresholds["max_regime_mae"] if regime else (
        thresholds["max_target_season_mae"]
        if period_name == "target_season"
        else thresholds["max_full_period_mae"]
    )
    if weak:
        mae_limit = thresholds["max_weak_reference_mae"]
    gates.append(gate_result(
        f"{reference_name}_{period_name}{'_' + regime if regime else ''}_mae",
        metric_severity,
        metrics.get("mae") is not None and float(metrics.get("mae")) <= float(mae_limit),
        f"MAE is {metrics.get('mae')}.",
        threshold=f"<= {mae_limit}",
        action="Keep the source in shadow or reject it if overlap bias is too large.",
    ))
    gates.append(gate_result(
        f"{reference_name}_{period_name}{'_' + regime if regime else ''}_max_abs",
        metric_severity,
        metrics.get("max_abs") is not None
        and float(metrics.get("max_abs")) <= float(thresholds["max_abs_difference"]),
        f"Max absolute difference is {metrics.get('max_abs')}.",
        threshold=f"<= {thresholds['max_abs_difference']}",
        action="Inspect station identity, unit normalization, and daily-high construction.",
    ))
    bucket_rate = metrics.get("bucket_match_rate")
    gates.append(gate_result(
        f"{reference_name}_{period_name}{'_' + regime if regime else ''}_bucket_match",
        metric_severity,
        bucket_rate is not None and float(bucket_rate) >= float(thresholds["min_bucket_match_rate"]),
        f"Bucket match rate is {bucket_rate}.",
        threshold=f">= {thresholds['min_bucket_match_rate']:.1%}",
        action="Do not promote if rounded market buckets diverge too often.",
    ))
    return gates


def source_validation(
    spec,
    source,
    start,
    end,
    thresholds=None,
):
    guard_not_canonical_root(source, spec)
    start = parse_date(start)
    end = parse_date(end)
    if start is None or end is None:
        raise ValueError("start and end are required")
    profile = threshold_profile(spec.display_unit, source.get("source_role"), thresholds)
    root = source_root(source)
    candidate_path = root / "daily" / "daily_summary.csv"
    candidate_rows = daily_value_rows(candidate_path)
    canonical_rows = daily_value_rows(daily_summary_path("ghcnh", spec))
    expected_period = list(iter_dates(start, end))
    expected_season = season_dates(start, end)

    references = {}
    all_gates = []
    for reference_name, meta in REFERENCE_SOURCES.items():
        rows = daily_value_rows(daily_summary_path(reference_name, spec))
        reference = {
            "label": meta["label"],
            "required": meta["required"],
            "weak_sanity_check": meta["weak"],
            "path": relative_to_repo(daily_summary_path(reference_name, spec)),
            "daily_days": len(rows),
            "metrics": {
                "full_period": compare_high_rows(
                    candidate_rows,
                    rows,
                    expected_period,
                    unit=spec.display_unit,
                ),
                "target_season": compare_high_rows(
                    candidate_rows,
                    rows,
                    expected_season,
                    unit=spec.display_unit,
                ),
            },
            "weather_regimes": {},
        }
        for regime in ("cool", "mild", "hot"):
            reference["weather_regimes"][regime] = compare_high_rows(
                candidate_rows,
                rows,
                expected_season,
                unit=spec.display_unit,
                regime=regime,
            )
        references[reference_name] = reference

        required = bool(meta["required"])
        weak = bool(meta["weak"])
        available = bool(rows)
        if required or available:
            all_gates.extend(metric_gates(
                reference_name,
                "full_period",
                reference["metrics"]["full_period"],
                profile,
                required=required,
                weak=weak,
            ))
            all_gates.extend(metric_gates(
                reference_name,
                "target_season",
                reference["metrics"]["target_season"],
                profile,
                required=required,
                weak=weak,
            ))
        if reference_name == "wu":
            for regime, metrics in reference["weather_regimes"].items():
                days = int(metrics.get("days") or 0)
                if days >= int(profile["min_regime_overlap_days"]):
                    all_gates.extend(metric_gates(
                        reference_name,
                        "target_season",
                        metrics,
                        profile,
                        required=True,
                        weak=False,
                        regime=regime,
                    ))
                elif days > 0:
                    all_gates.append(gate_result(
                        f"wu_target_season_{regime}_overlap",
                        "warn",
                        True,
                        f"{days} {regime} overlap days; regime remains shadow-only until it reaches the threshold.",
                        threshold=f">= {profile['min_regime_overlap_days']} days",
                    ))

    candidate_dates = set(candidate_rows)
    canonical_dates = set(canonical_rows)
    period_set = set(expected_period)
    season_set = set(expected_season)
    added_period = sorted((candidate_dates - canonical_dates) & period_set)
    added_season = sorted((candidate_dates - canonical_dates) & season_set)

    distance_km = safe_float(source.get("distance_from_canonical_km"))
    all_gates.append(gate_result(
        "distance_from_canonical",
        "hard",
        distance_km is not None and distance_km <= float(profile["max_distance_km"]),
        f"Distance from canonical station is {distance_km} km.",
        threshold=f"<= {profile['max_distance_km']} km",
        action="Reject or keep as candidate if the station is too far from the market station.",
    ))
    all_gates.append(gate_result(
        "target_season_missing_day_reduction",
        "hard",
        len(added_season) >= int(profile["min_missing_day_reduction"]),
        f"Adds {len(added_season)} target-season days not covered by canonical GHCNh.",
        threshold=f">= {profile['min_missing_day_reduction']} day(s)",
        action="Do not promote a nearby station that does not reduce the canonical history gap.",
    ))

    candidate_elevation = station_elevation_m(source, root)
    canonical_elevation = station_elevation_m(
        {"elevation_m": None},
        REPO_ROOT / "data" / "noaa_ghcnh" / spec.icao.lower(),
    )
    elevation_mismatch = None
    if candidate_elevation is not None and canonical_elevation is not None:
        elevation_mismatch = abs(candidate_elevation - canonical_elevation)
        all_gates.append(gate_result(
            "elevation_mismatch",
            "hard",
            elevation_mismatch <= float(profile["max_elevation_mismatch_m"]),
            f"Elevation mismatch is {round(elevation_mismatch, 2)} m.",
            threshold=f"<= {profile['max_elevation_mismatch_m']} m",
            action="Reject or keep in shadow if the source is in a materially different elevation regime.",
        ))
    else:
        all_gates.append(gate_result(
            "elevation_mismatch",
            "warn",
            True,
            "Elevation mismatch is unknown because one station lacks usable elevation metadata.",
            threshold=f"<= {profile['max_elevation_mismatch_m']} m when known",
            action="Populate elevation metadata before relying on elevation-sensitive regimes.",
        ))

    hard_failures = [gate for gate in all_gates if gate["severity"] == "hard" and not gate["ok"]]
    shadow_failures = [gate for gate in all_gates if gate["severity"] == "shadow" and not gate["ok"]]
    registry_state = source.get("validation_status")
    if registry_state == "retired":
        promotion_state = "retired"
    elif not candidate_rows:
        promotion_state = "rejected"
    elif hard_failures:
        overlap_failures = [
            gate for gate in hard_failures
            if gate["name"].endswith("_overlap")
        ]
        promotion_state = "candidate" if overlap_failures else "rejected"
    elif shadow_failures:
        promotion_state = "shadow_only"
    else:
        promotion_state = "validated_supplemental"

    validated_regimes = []
    unvalidated_regimes = []
    for regime, metrics in (references.get("wu") or {}).get("weather_regimes", {}).items():
        days = int(metrics.get("days") or 0)
        if days < int(profile["min_regime_overlap_days"]):
            if days:
                unvalidated_regimes.append(regime)
            continue
        regime_gate_prefix = f"wu_target_season_{regime}_"
        failed = [
            gate for gate in all_gates
            if gate["name"].startswith(regime_gate_prefix) and not gate["ok"]
        ]
        if failed:
            unvalidated_regimes.append(regime)
        else:
            validated_regimes.append(regime)

    return {
        "source_id": source.get("source_id"),
        "market_id": spec.id,
        "city": getattr(spec, "city_label", spec.id),
        "unit": spec.display_unit,
        "source_type": source.get("source_type"),
        "source_role": source.get("source_role"),
        "station_id": source.get("station_id"),
        "station_name": source.get("station_name"),
        "root_path": relative_to_repo(root),
        "daily_summary_path": relative_to_repo(candidate_path),
        "source_fingerprint": source_fingerprint(source),
        "registry_validation_status": registry_state,
        "promotion_state": promotion_state,
        "eligible_for_training": promotion_state == "validated_supplemental",
        "eligible_for_source_trust_features": promotion_state == "validated_supplemental",
        "validation_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "target_season_days": len(expected_season),
        },
        "thresholds": profile,
        "coverage": {
            "full_period": date_coverage(candidate_rows, expected_period),
            "target_season": date_coverage(candidate_rows, expected_season),
            "canonical_ghcnh_target_season_days": len(canonical_dates & season_set),
            "target_season_missing_day_reduction": len(added_season),
            "full_period_missing_day_reduction": len(added_period),
            "sample_added_target_season_days": [item.isoformat() for item in added_season[:10]],
        },
        "metadata": {
            "distance_from_canonical_km": distance_km,
            "candidate_elevation_m": candidate_elevation,
            "canonical_elevation_m": canonical_elevation,
            "elevation_mismatch_m": (
                round(elevation_mismatch, 2) if elevation_mismatch is not None else None
            ),
        },
        "references": references,
        "validated_weather_regimes": validated_regimes,
        "unvalidated_weather_regimes": unvalidated_regimes,
        "gates": all_gates,
        "failures": [
            gate for gate in all_gates
            if gate["severity"] != "warn" and not gate["ok"]
        ],
        "warnings": [
            gate for gate in all_gates
            if gate["severity"] == "warn" and not gate.get("ok")
        ],
    }


def build_validation_payload(market_ids=None, start=None, end=None, registry=None, thresholds=None):
    start = parse_date(start) or date(2000, 1, 1)
    end = parse_date(end) or datetime.now(timezone.utc).date()
    ids = set(market_ids or [])
    specs = [spec for spec in all_specs() if not ids or spec.id in ids]
    sources = []
    for spec in specs:
        for source in supplemental_sources(spec.id, registry=registry):
            if source.get("source_type") != "noaa_ghcnh":
                continue
            sources.append(source_validation(spec, source, start, end, thresholds=thresholds))
    counts = {}
    for row in sources:
        state = row.get("promotion_state") or "candidate"
        counts[state] = counts.get(state, 0) + 1
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_window": {"start": start.isoformat(), "end": end.isoformat()},
        "threshold_profiles": {
            f"{unit}:{role}": values
            for (unit, role), values in DEFAULT_THRESHOLD_PROFILES.items()
        },
        "source_count": len(sources),
        "promotion_state_counts": counts,
        "sources": sources,
    }


def load_validation_report(path=DEFAULT_OUT):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != VALIDATION_SCHEMA_VERSION:
        return None
    payload.setdefault("artifact_path", str(path))
    return payload


def validation_row_for_source(validation_report, source_id):
    for row in (validation_report or {}).get("sources") or []:
        if row.get("source_id") == source_id:
            return row
    return None


def promotion_gate_for_source(
    source,
    validation_report=None,
    validation_path=DEFAULT_OUT,
    intended_start=None,
    intended_end=None,
    intended_regime=None,
):
    report = validation_report if validation_report is not None else load_validation_report(validation_path)
    source_id = source.get("source_id")
    if source.get("validation_status") == "retired":
        return {
            "source_id": source_id,
            "status": "FAIL",
            "ok": False,
            "promotion_state": "retired",
            "eligible_for_training": False,
            "eligible_for_source_trust_features": False,
            "reason": "source is retired in the supplemental registry",
            "artifact_path": str(validation_path) if validation_path else None,
        }
    if not report:
        return {
            "source_id": source_id,
            "status": "FAIL",
            "ok": False,
            "promotion_state": "candidate",
            "eligible_for_training": False,
            "eligible_for_source_trust_features": False,
            "reason": "missing current supplemental station validation report",
            "artifact_path": str(validation_path) if validation_path else None,
        }
    row = validation_row_for_source(report, source_id)
    if not row:
        return {
            "source_id": source_id,
            "status": "FAIL",
            "ok": False,
            "promotion_state": "candidate",
            "eligible_for_training": False,
            "eligible_for_source_trust_features": False,
            "reason": "source is absent from supplemental station validation report",
            "artifact_path": report.get("artifact_path") or str(validation_path),
        }
    failures = []
    if row.get("source_fingerprint") != source_fingerprint(source):
        failures.append("validation report source fingerprint is stale")
    window = row.get("validation_window") or {}
    report_start = parse_date(window.get("start"))
    report_end = parse_date(window.get("end"))
    start = parse_date(intended_start)
    end = parse_date(intended_end)
    if start and (not report_start or report_start > start):
        failures.append("validation report starts after the intended use window")
    if end and (not report_end or report_end < end):
        failures.append("validation report ends before the intended use window")
    if intended_regime:
        if intended_regime not in (row.get("validated_weather_regimes") or []):
            failures.append(f"weather regime {intended_regime!r} is not validated")
    state = row.get("promotion_state") or "candidate"
    if state != "validated_supplemental":
        failures.append(f"promotion state is {state}")
    gate_failures = [
        gate.get("name")
        for gate in row.get("gates") or []
        if gate.get("severity") == "hard" and not gate.get("ok")
    ]
    failures.extend(gate_failures)
    ok = not failures
    return {
        "source_id": source_id,
        "status": "PASS" if ok else "FAIL",
        "ok": ok,
        "promotion_state": state,
        "eligible_for_training": ok,
        "eligible_for_source_trust_features": ok,
        "reason": "validated supplemental source" if ok else "; ".join(failures),
        "artifact_path": report.get("artifact_path") or str(validation_path),
        "validated_weather_regimes": row.get("validated_weather_regimes") or [],
        "failures": failures,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def markdown_table(headers, rows):
    rows = list(rows)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value is not None else "-" for value in row) + " |")
    return lines


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def fmt_num(value, digits=3):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def write_report(path, payload):
    path = Path(path)
    rows = []
    for source in payload.get("sources") or []:
        wu_target = (((source.get("references") or {}).get("wu") or {}).get("metrics") or {}).get("target_season") or {}
        metar_target = (((source.get("references") or {}).get("metar") or {}).get("metrics") or {}).get("target_season") or {}
        rows.append([
            source.get("market_id"),
            source.get("source_id"),
            source.get("station_id"),
            source.get("promotion_state"),
            source.get("coverage", {}).get("target_season_missing_day_reduction"),
            fmt_num(source.get("metadata", {}).get("distance_from_canonical_km"), 2),
            wu_target.get("days") or 0,
            fmt_num(wu_target.get("mae")),
            fmt_pct(wu_target.get("bucket_match_rate")),
            metar_target.get("days") or 0,
            fmt_num(metar_target.get("mae")),
            fmt_pct(metar_target.get("bucket_match_rate")),
            ", ".join(source.get("validated_weather_regimes") or []) or "-",
            "; ".join(gate.get("name") for gate in source.get("failures") or []) or "-",
        ])
    lines = [
        "# Supplemental Station Validation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        (
            "Window: "
            f"`{(payload.get('validation_window') or {}).get('start')}` to "
            f"`{(payload.get('validation_window') or {}).get('end')}`"
        ),
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Source ID", "Station", "State", "Added Season Days",
            "Distance Km", "WU Days", "WU MAE", "WU Bucket", "METAR Days",
            "METAR MAE", "METAR Bucket", "Validated Regimes", "Blockers",
        ],
        rows,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate supplemental nearby historical stations.")
    parser.add_argument("--markets", default="", help="Comma-separated market ids; defaults to all markets.")
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--strict", action="store_true", help="Exit 2 unless every source is validated.")
    args = parser.parse_args(argv)

    market_ids = [item.strip() for item in args.markets.split(",") if item.strip()]
    for market_id in market_ids:
        spec_for_id(market_id)
    registry = load_registry(args.registry)
    payload = build_validation_payload(
        market_ids=market_ids,
        start=parse_date(args.start),
        end=parse_date(args.end),
        registry=registry,
    )
    out_path = write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    print(f"Wrote supplemental station validation JSON to {out_path}")
    print(f"Wrote supplemental station validation report to {report_path}")
    print(
        "Promotion states: "
        + ", ".join(
            f"{key}={value}"
            for key, value in sorted((payload.get("promotion_state_counts") or {}).items())
        )
    )
    if args.strict and any(
        row.get("promotion_state") != "validated_supplemental"
        for row in payload.get("sources") or []
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
