"""Inventory checked-in configuration files and freshness policy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import config_path, data_path, relative_to_repo
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("config_inventory")
DEFAULT_CONFIG_ROOT = config_path()
DEFAULT_OUT = data_path("backtest", "config_inventory.json")
DEFAULT_REPORT = data_path("backtest", "config_inventory_report.md")
DEFAULT_LOCATIONS_MAX_AGE_DAYS = 7

CONFIG_POLICIES = {
    "locations.json": {
        "owner": "weather.market",
        "classification": "durable_location_registry",
        "freshness_policy": "review_when_location_station_or_source_plan_changes",
        "max_age_days": None,
        "volatile_fields": [],
    },
    "location_market_events.json": {
        "owner": "weather.operations.location_config_refresh",
        "classification": "generated_snapshot",
        "freshness_policy": "refresh_from_gamma_api",
        "max_age_days": DEFAULT_LOCATIONS_MAX_AGE_DAYS,
        "volatile_fields": [
            "locations[].latest_event_slug",
            "locations[].latest_event_url",
            "locations[].active_events",
        ],
    },
    "markets.json": {
        "owner": "weather.market.market_registry",
        "classification": "deprecated_compatibility_shell",
        "freshness_policy": "empty_external_override_shell",
        "max_age_days": None,
    },
    "model_variant_registry.json": {
        "owner": "weather.reporting.candidate_lifecycle.variant_registry",
        "classification": "hand_authored_registry",
        "freshness_policy": "validate_before_promotion",
        "max_age_days": None,
    },
    "supplemental_stations.json": {
        "owner": "weather.sources.supplemental_stations",
        "classification": "hand_authored_registry",
        "freshness_policy": "review_when_station_or_provenance_changes",
        "max_age_days": None,
    },
    "no_market_extra_locations.json": {
        "owner": "weather.reporting.location_analysis.extra_location_registry",
        "classification": "local_shadow_registry",
        "freshness_policy": "backfill_or_archive_before_training",
        "max_age_days": None,
    },
    "storage_pressure.json": {
        "owner": "weather.market.storage_pressure_policy",
        "classification": "operator_activation_policy",
        "freshness_policy": "default_preserves_current_capture_until_operator_activation",
        "max_age_days": None,
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {"rows": payload}


def generated_time(payload: dict) -> datetime | None:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    for key in ("generated_at_utc", "generated_at_local", "generated_at", "updated_at_utc"):
        value = source.get(key) if key in source else payload.get(key)
        parsed = parse_time(value)
        if parsed is not None:
            return parsed
    event_metadata = payload.get("event_metadata") if isinstance(payload.get("event_metadata"), dict) else {}
    parsed = parse_time(event_metadata.get("last_refreshed_at_utc"))
    if parsed is not None:
        return parsed
    return None


def variant_local_path_issues(payload: dict) -> list[dict]:
    issues = []
    for variant in payload.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        artifact_path = variant.get("artifact_path") or (variant.get("export_contract") or {}).get("artifact_path")
        if not artifact_path or not str(artifact_path).replace("\\", "/").startswith("data/"):
            continue
        roles = {str(role) for role in variant.get("roles") or []}
        shadow_only = variant.get("lifecycle") == "shadow" or "shadow-only" in roles
        if variant.get("lifecycle") == "active" and not shadow_only:
            issues.append({
                "variant_id": variant.get("variant_id"),
                "artifact_path": artifact_path,
                "issue": "active variant artifact_path points at ignored data/",
            })
    return issues


def no_market_extra_location_issues(payload: dict) -> list[dict]:
    issues = []
    for row in payload.get("locations") or []:
        if row.get("archived_at_utc") or row.get("archive_reason"):
            continue
        labeled = int(row.get("independent_labeled_days") or 0)
        forecast = int(row.get("forecast_history_days") or 0)
        observed = int(row.get("observation_days") or 0)
        if row.get("diagnostic_only") and not (labeled or forecast or observed):
            issues.append({
                "location_id": row.get("location_id"),
                "issue": "diagnostic-only location has no backfilled evidence; keep archived or backfill before training",
            })
    return issues


def config_record(path: Path, *, now: datetime, policy: dict) -> dict:
    payload = load_json(path)
    generated = generated_time(payload)
    max_age = policy.get("max_age_days")
    age_days = None
    freshness = "NOT_REQUIRED"
    if generated is not None:
        age_days = (now - generated).total_seconds() / 86400.0
        freshness = "STALE" if max_age is not None and age_days > float(max_age) else "FRESH"
    issues = []
    name = path.name
    if not path.exists():
        issues.append({"issue": "required config file is missing"})
    if name == "model_variant_registry.json":
        issues.extend(variant_local_path_issues(payload))
    elif name == "no_market_extra_locations.json":
        issues.extend(no_market_extra_location_issues(payload))
    elif name == "markets.json" and not payload.get("markets"):
        if payload.get("status") != "deprecated_compatibility_shell":
            issues.append({"issue": "empty market registry without deprecated compatibility-shell status"})
    status = "WARN" if issues or freshness == "STALE" else "PASS"
    return {
        "path": relative_to_repo(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "schema_version": payload.get("schema_version"),
        "owner": policy.get("owner"),
        "classification": policy.get("classification"),
        "freshness_policy": policy.get("freshness_policy"),
        "max_age_days": max_age,
        "generated_at_utc": generated.isoformat() if generated else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "freshness": freshness,
        "volatile_fields": policy.get("volatile_fields") or [],
        "status": status,
        "issues": issues,
    }


def build_config_inventory(
    config_root: str | Path = DEFAULT_CONFIG_ROOT,
    *,
    generated_at_utc: str | None = None,
    now: datetime | None = None,
) -> dict:
    config_root = Path(config_root)
    now = now or utc_now()
    rows = [
        config_record(config_root / name, now=now, policy=policy)
        for name, policy in sorted(CONFIG_POLICIES.items())
    ]
    warning_count = sum(1 for row in rows if row["status"] == "WARN")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or now.isoformat(),
        "config_root": relative_to_repo(config_root),
        "status": "WARN" if warning_count else "PASS",
        "config_count": len(rows),
        "warning_count": warning_count,
        "configs": rows,
    }


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict) -> str:
    lines = [
        "# Config Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "| Config | Classification | Owner | Freshness | Status | Issues |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in payload.get("configs") or []:
        issues = "; ".join(issue.get("issue", "") for issue in row.get("issues") or []) or "-"
        lines.append(
            "| {path} | {classification} | {owner} | {freshness} | {status} | {issues} |".format(
                path=row.get("path"),
                classification=row.get("classification"),
                owner=row.get("owner"),
                freshness=row.get("freshness"),
                status=row.get("status"),
                issues=issues,
            )
        )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inventory config ownership, freshness, and registry hygiene.")
    parser.add_argument("--config-root", default=str(DEFAULT_CONFIG_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_config_inventory(args.config_root)
    write_json(args.out, payload)
    write_report(args.report, payload)
    print(
        "Config inventory: status={status} configs={config_count} warnings={warning_count}".format(
            **payload
        )
    )
    return payload


if __name__ == "__main__":
    main()
