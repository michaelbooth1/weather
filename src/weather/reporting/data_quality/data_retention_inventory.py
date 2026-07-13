"""Data-tree ownership, retention, and disk-budget inventory."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import heapq
import json
import math
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.operations.storage_classes import (
    classification_payload,
    delete_gate_for_storage_class,
    storage_class_contracts_payload,
)
from weather.operations.event_day_manifest import summarize_event_day_manifests
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("data_retention_inventory")
HEADROOM_PROBE_SCHEMA_VERSION = schema_version("data_retention_headroom_probe")
DEFAULT_DATA_ROOT = data_path()
DEFAULT_OUT = DEFAULT_DATA_ROOT / "backtest" / "data_retention_inventory.json"
DEFAULT_REPORT = DEFAULT_DATA_ROOT / "backtest" / "data_retention_inventory_report.md"
DEFAULT_HEADROOM_PROBE_OUT = (
    DEFAULT_DATA_ROOT / "backtest" / "data_retention_headroom_probe.json"
)
DEFAULT_HEADROOM_PROBE_REPORT = (
    DEFAULT_DATA_ROOT / "backtest" / "data_retention_headroom_probe.md"
)
DEFAULT_MIN_FREE_BYTES = 5_000_000_000
DEFAULT_MIN_GROWTH_HEADROOM_DAYS = 30.0
DEFAULT_LOOKBACK_HOURS = 24.0
DEFAULT_TOP_N = 25
DEFAULT_MAX_SOURCE_AGE_HOURS = 168.0


@dataclass(frozen=True)
class DataRetentionPolicy:
    name: str
    owner: str
    patterns: tuple[str, ...]
    durability: str
    local_ttl: str
    archive_ttl: str
    deletion_requirement: str
    regeneration_path: str
    prune_policy: str
    deletion_requires_review: bool = False
    local_delete_allowed: bool = False


POLICIES = (
    DataRetentionPolicy(
        "shared_forecast_payload_cas",
        "collection/sources",
        ("forecast_payload_cas/**",),
        "irreplaceable market-invariant raw forecast response evidence",
        "retain while any per-market forecast manifest references the digest",
        "permanent archive with all referencing manifests",
        "deletion disabled; no current cleanup manifest or generic review can authorize it",
        "not regenerable with the same point-in-time source bytes",
        "inventory only; a future separate contract would need global reachability, restore, hash, and replay proofs before enabling garbage collection",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "snapshots",
        "collection/model/market",
        ("snapshots/**",),
        "irreplaceable live snapshot, feature, source-status, and CLOB evidence",
        "keep active and recent settled days locally; archive older proof-grade folders only after review",
        "permanent external archive for proof-grade live tapes",
        "requires reviewed cleanup manifest before deletion",
        "not regenerable from providers after the fact",
        "delete only from an explicit reviewed manifest; prefer gzip tiering for full-depth books",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "replay_cache",
        "backtesting/calibration",
        ("backtest/replay_cache/**",),
        "rebuildable per-market-day replay rows keyed by pinned corpus inputs and model identity",
        "keep while referenced by active promotion corpora or active variant registry entries",
        "no archive required; cache is disposable when source corpus and artifacts are retained",
        "local deletion allowed for unreferenced model/input keys or cache-schema bumps",
        "rebuild from retained promotion corpus, snapshots, settlements, and model artifacts",
        "prune entries whose event_slug/model identity is no longer referenced by active corpora or registry artifacts",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "backtest",
        "reporting/calibration",
        ("backtest/**",),
        "mixed: promotion corpora and reports are durable; row exports may be rebuildable",
        "keep manifests, reports, promotion corpora, and current evidence; review large row exports after 30 days",
        "retain promotion corpora/manifests permanently; large rebuildable CSVs may be externalized",
        "deletion of promotion corpora requires artifact lineage; generated row exports require paired reports",
        "large row exports can usually be rebuilt from retained corpus, artifact, and report",
        "use backtest_artifact_retention cleanup manifest; never delete orphaned evidence by hand",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "settlements",
        "backtesting/market",
        ("settlements/**",),
        "irreplaceable settlement and label provenance",
        "retain locally with promotion corpora; archive only after review",
        "permanent external archive",
        "requires reviewed cleanup manifest before deletion",
        "not safely regenerable without settlement-source history and manual overrides",
        "delete only from a reviewed manifest",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "mm_runs",
        "market",
        ("mm_runs/**",),
        "irreplaceable market-making paper/live-forward lifecycle evidence",
        "retain locally through active review",
        "permanent external archive for countable live/paper evidence",
        "requires reviewed cleanup manifest before deletion",
        "not regenerable because quote/fill/markout timing is live-only",
        "delete only from a reviewed manifest after promotion windows close",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "taker_runs",
        "market",
        ("taker_runs/**",),
        "irreplaceable taker strategy, fill, and settlement evidence",
        "retain locally through strategy bakeoff and settlement finalization",
        "permanent external archive for countable trading evidence",
        "requires reviewed cleanup manifest before deletion",
        "not regenerable because fills and account snapshots are live-only",
        "delete only from a reviewed manifest",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "ops",
        "operations",
        ("ops/**",),
        "operational reports, status, and local run diagnostics",
        "keep latest statuses and incident evidence; rotate noisy logs after 30 days",
        "archive incident reports with related run evidence",
        "manual review required only for incident evidence; routine status is regenerable",
        "routine health reports are regenerated by daily refresh and fleet observability",
        "rotate only with an incident manifest or after confirming regenerated status exists",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "provider_caches",
        "sources/model",
        (
            "forecast_archive/**",
            "forecast_history/**",
            "cache/**",
            "open_meteo/**",
            "weather_com/**",
            "source_cache/**",
        ),
        "mostly regenerable provider cache; some forecast archives are evidence",
        "keep recent cache within provider TTL; keep forecast archives used by training until archived",
        "archive forecast snapshots that participate in settled replay evidence",
        "cache deletion is allowed when no replay/promotion artifact references it",
        "regenerate from provider only where API history is available; live-issued forecasts may not be recoverable",
        "delete TTL-expired cache only; do not delete archived forecast snapshots without lineage review",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "historical_sources",
        "sources",
        (
            "wunderground/**",
            "metar/**",
            "asos/**",
            "ghcnh/**",
            "noaa_ghcnh/**",
            "power/**",
            "nasa_power/**",
            "meteostat/**",
            "eccc/**",
            "eccc_swob/**",
        ),
        "historical weather source rows and provenance manifests",
        "retain canonical source histories locally; archive raw mirrors only after review",
        "permanent archive for raw/provenance source rows",
        "requires source manifest before raw deletion",
        "some provider history is backfillable, but canonical settled-source provenance is not safely assumed regenerable",
        "delete only duplicate raw mirrors after manifest review",
        deletion_requires_review=True,
    ),
    DataRetentionPolicy(
        "reanalysis",
        "sources/calibration",
        ("reanalysis/**",),
        "large gridded/reanalysis source cache and derived sidecars",
        "retain sidecars and latest cache windows; externalize large raw gridded files when manifest-backed",
        "archive raw pressure/gridded files used by trained artifacts",
        "re-download proof required before removing raw NetCDF/GRIB cache",
        "raw gridded files may be re-downloaded when upstream retains the exact vintage; sidecars are rebuildable",
        "externalize raw files with checksums; rebuild sidecars after re-download",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "logs",
        "operations",
        ("logs/**",),
        "local operational logs",
        "rotate after incident review",
        "archive only incident-linked logs",
        "manual owner review required before deletion",
        "routine logs are not evidence unless referenced by an incident report",
        "rotate with operator approval",
        local_delete_allowed=True,
    ),
)


def _format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while abs(size) >= 1024.0 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} B"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _probe_blocker(code: str, detail: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **evidence}


def _disk_usage_path(root: Path) -> Path:
    candidate = root
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def build_headroom_probe(
    source_inventory: str | Path,
    *,
    root: str | Path | None = None,
    max_source_age_hours: float = DEFAULT_MAX_SOURCE_AGE_HOURS,
    min_growth_headroom_days: float = DEFAULT_MIN_GROWTH_HEADROOM_DAYS,
    min_free_bytes: int | None = None,
    expected_source_sha256: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh disk headroom without walking the data tree.

    The prior full inventory remains the sole source of observed write rate.
    Its exact bytes are read once, hashed, parsed, and validated before the
    current filesystem free-space value is sampled.
    """

    if max_source_age_hours <= 0:
        raise ValueError("max_source_age_hours must be positive")
    if min_growth_headroom_days <= 0:
        raise ValueError("min_growth_headroom_days must be positive")
    if min_free_bytes is not None and min_free_bytes < 0:
        raise ValueError("min_free_bytes cannot be negative")
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    generated_at = generated_at.astimezone(timezone.utc)

    source_path = Path(source_inventory)
    blockers: list[dict[str, Any]] = []
    source_blocker_codes: list[str] = []
    source_bytes: bytes | None = None
    source_hash: str | None = None
    source_payload: dict[str, Any] = {}
    try:
        source_bytes = source_path.read_bytes()
        source_hash = _sha256_bytes(source_bytes)
    except OSError as exc:
        blocker = _probe_blocker(
            "source_inventory_unreadable",
            f"cannot read prior full inventory: {exc}",
            source_path=str(source_path),
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])

    expected_hash = str(expected_source_sha256 or "").strip().lower() or None
    if expected_hash and source_hash != expected_hash:
        blocker = _probe_blocker(
            "source_inventory_hash_mismatch",
            "prior full inventory does not match the pinned SHA-256",
            expected_sha256=expected_hash,
            actual_sha256=source_hash,
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])

    if source_bytes is not None:
        try:
            decoded = json.loads(source_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            blocker = _probe_blocker(
                "source_inventory_malformed",
                f"prior full inventory is not valid JSON: {exc}",
            )
            blockers.append(blocker)
            source_blocker_codes.append(blocker["code"])
        else:
            if isinstance(decoded, dict):
                source_payload = decoded
            else:
                blocker = _probe_blocker(
                    "source_inventory_malformed",
                    "prior full inventory must be a JSON object",
                )
                blockers.append(blocker)
                source_blocker_codes.append(blocker["code"])

    source_mode = str(source_payload.get("mode") or "legacy_full_inventory")
    if source_payload and source_payload.get("schema_version") != SCHEMA_VERSION:
        blocker = _probe_blocker(
            "source_inventory_schema_mismatch",
            "prior inventory schema does not match the active retention inventory schema",
            expected_schema_version=SCHEMA_VERSION,
            actual_schema_version=source_payload.get("schema_version"),
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
    if source_payload and source_mode not in {"full_inventory", "legacy_full_inventory"}:
        blocker = _probe_blocker(
            "source_inventory_not_full",
            "bounded probes cannot be chained as the observed write-rate source",
            source_mode=source_mode,
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])

    summary = source_payload.get("summary")
    source_disk = source_payload.get("disk")
    if source_payload and (
        not isinstance(summary, dict)
        or not isinstance(source_disk, dict)
        or not isinstance(source_payload.get("policy_summaries"), list)
        or not isinstance(source_payload.get("storage_class_summaries"), list)
    ):
        blocker = _probe_blocker(
            "source_inventory_incomplete",
            "prior inventory lacks full-inventory summary/classification surfaces",
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
        summary = summary if isinstance(summary, dict) else {}
        source_disk = source_disk if isinstance(source_disk, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    source_disk = source_disk if isinstance(source_disk, dict) else {}

    source_status = str(source_payload.get("status") or "").strip().upper()
    if source_payload and source_status not in {"PASS", "BLOCK"}:
        blocker = _probe_blocker(
            "source_inventory_status_invalid",
            "prior full inventory must have a terminal PASS or BLOCK status",
            source_status=source_status or None,
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])

    source_generated_at = _parse_utc(source_payload.get("generated_at_utc"))
    source_age_hours = None
    if source_payload and source_generated_at is None:
        blocker = _probe_blocker(
            "source_inventory_timestamp_invalid",
            "prior full inventory requires a timezone-aware generated_at_utc",
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
    elif source_generated_at is not None:
        source_age_hours = (
            generated_at - source_generated_at
        ).total_seconds() / 3600.0
        if source_age_hours < 0:
            blocker = _probe_blocker(
                "source_inventory_from_future",
                "prior inventory generated_at_utc is later than the probe time",
                source_age_hours=source_age_hours,
            )
            blockers.append(blocker)
            source_blocker_codes.append(blocker["code"])
        elif source_age_hours > max_source_age_hours:
            blocker = _probe_blocker(
                "source_inventory_stale",
                "prior full inventory is older than the permitted source age",
                source_age_hours=source_age_hours,
                max_source_age_hours=max_source_age_hours,
            )
            blockers.append(blocker)
            source_blocker_codes.append(blocker["code"])

    lookback_hours = _finite_number(source_payload.get("lookback_hours"))
    recent_bytes = _finite_number(summary.get("recent_bytes"))
    recorded_daily_recent_bytes = _finite_number(source_disk.get("daily_recent_bytes"))
    if lookback_hours is None or lookback_hours <= 0:
        blocker = _probe_blocker(
            "source_lookback_invalid",
            "prior full inventory lookback_hours must be positive",
            lookback_hours=source_payload.get("lookback_hours"),
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
    if recent_bytes is None or recent_bytes <= 0:
        blocker = _probe_blocker(
            "source_recent_write_rate_nonpositive",
            "prior full inventory must contain a positive recent-byte write rate",
            recent_bytes=summary.get("recent_bytes"),
            daily_recent_bytes=source_disk.get("daily_recent_bytes"),
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
    daily_recent_bytes = (
        recent_bytes * 24.0 / lookback_hours
        if recent_bytes is not None
        and recent_bytes > 0
        and lookback_hours is not None
        and lookback_hours > 0
        else None
    )
    if daily_recent_bytes is not None and recorded_daily_recent_bytes is not None:
        derived_daily_rate = daily_recent_bytes
        tolerance = max(1.0, derived_daily_rate * 1e-9)
        if abs(recorded_daily_recent_bytes - derived_daily_rate) > tolerance:
            blocker = _probe_blocker(
                "source_recent_write_rate_inconsistent",
                "prior daily_recent_bytes disagrees with recent_bytes/lookback_hours",
                daily_recent_bytes=recorded_daily_recent_bytes,
                derived_daily_recent_bytes=derived_daily_rate,
                tolerance=tolerance,
            )
            blockers.append(blocker)
            source_blocker_codes.append(blocker["code"])

    source_root_text = str(source_payload.get("root") or "").strip()
    root_path = Path(root) if root is not None else (
        Path(source_root_text) if source_root_text else Path(DEFAULT_DATA_ROOT)
    )
    root_exists = root_path.exists()
    if not root_exists:
        blockers.append(
            _probe_blocker(
                "storage_root_missing",
                "current data root does not exist",
                root=str(root_path),
            )
        )
    if source_payload and not source_root_text:
        blocker = _probe_blocker(
            "source_inventory_root_missing",
            "prior full inventory does not identify its scanned root",
        )
        blockers.append(blocker)
        source_blocker_codes.append(blocker["code"])
    elif source_root_text:
        try:
            same_root = Path(source_root_text).resolve() == root_path.resolve()
        except OSError:
            same_root = False
        if not same_root:
            blocker = _probe_blocker(
                "source_inventory_root_mismatch",
                "prior full inventory was produced for a different data root",
                source_root=source_root_text,
                current_root=str(root_path),
            )
            blockers.append(blocker)
            source_blocker_codes.append(blocker["code"])

    usage = None
    try:
        usage = shutil.disk_usage(_disk_usage_path(root_path))
    except OSError as exc:
        blockers.append(
            _probe_blocker(
                "disk_usage_unavailable",
                f"cannot read current disk usage: {exc}",
                root=str(root_path),
            )
        )

    source_min_free = _finite_number(source_payload.get("min_free_bytes"))
    effective_min_free = int(
        min_free_bytes
        if min_free_bytes is not None
        else source_min_free
        if source_min_free is not None and source_min_free >= 0
        else DEFAULT_MIN_FREE_BYTES
    )
    current_free = int(usage.free) if usage is not None else None
    current_total = int(usage.total) if usage is not None else None
    current_used = int(usage.used) if usage is not None else None
    growth_headroom_days = (
        float(current_free) / daily_recent_bytes
        if current_free is not None
        and daily_recent_bytes is not None
        and daily_recent_bytes > 0
        else None
    )
    growth_shortfall_days = (
        max(0.0, min_growth_headroom_days - growth_headroom_days)
        if growth_headroom_days is not None
        else min_growth_headroom_days
    )
    free_shortfall = (
        max(0, effective_min_free - current_free)
        if current_free is not None
        else effective_min_free
    )
    required_headroom_bytes = (
        daily_recent_bytes * min_growth_headroom_days
        if daily_recent_bytes is not None and daily_recent_bytes > 0
        else None
    )
    headroom_surplus_bytes = (
        current_free - required_headroom_bytes
        if current_free is not None and required_headroom_bytes is not None
        else None
    )
    if current_free is not None and free_shortfall > 0:
        blockers.append(
            _probe_blocker(
                "free_space_below_minimum",
                "current disk free space is below the configured byte floor",
                free_bytes=current_free,
                min_free_bytes=effective_min_free,
            )
        )
    if growth_headroom_days is not None and growth_headroom_days < min_growth_headroom_days:
        blockers.append(
            _probe_blocker(
                "growth_headroom_below_minimum",
                "current free space does not cover the required observed-write-rate window",
                growth_headroom_days=growth_headroom_days,
                min_growth_headroom_days=min_growth_headroom_days,
            )
        )

    source_trustworthy = not source_blocker_codes
    return {
        "schema_version": HEADROOM_PROBE_SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "mode": "bounded_storage_headroom_probe",
        "evidence_contract": "prior_full_inventory_rate_plus_current_disk_free",
        "status": "PASS" if not blockers else "BLOCK",
        "root": str(root_path),
        "root_exists": root_exists,
        "lookback_hours": lookback_hours,
        "min_free_bytes": effective_min_free,
        "min_growth_headroom_days": float(min_growth_headroom_days),
        "max_source_age_hours": float(max_source_age_hours),
        "source_inventory_path": str(source_path),
        "source_inventory_sha256": source_hash,
        "source_inventory": {
            "path": str(source_path),
            "sha256": source_hash,
            "expected_sha256": expected_hash,
            "hash_matches_expected": not expected_hash or source_hash == expected_hash,
            "schema_version": source_payload.get("schema_version"),
            "mode": source_mode,
            "status": source_status or None,
            "generated_at_utc": (
                source_generated_at.isoformat() if source_generated_at else None
            ),
            "age_hours": source_age_hours,
            "max_age_hours": float(max_source_age_hours),
            "lookback_hours": lookback_hours,
            "recent_bytes": recent_bytes,
            "daily_recent_bytes": daily_recent_bytes,
            "trustworthy": source_trustworthy,
            "blocker_codes": source_blocker_codes,
        },
        "disk": {
            "sampled_at_utc": generated_at.isoformat(),
            "total_bytes": current_total,
            "used_bytes": current_used,
            "free_bytes": current_free,
            "free_human": _format_bytes(current_free),
            "free_shortfall_bytes": free_shortfall,
            "free_shortfall_human": _format_bytes(free_shortfall),
            "daily_recent_bytes": (
                int(daily_recent_bytes) if daily_recent_bytes is not None else 0
            ),
            "daily_recent_human": _format_bytes(daily_recent_bytes),
            "growth_headroom_days": growth_headroom_days,
            "growth_headroom_shortfall_days": growth_shortfall_days,
            "required_headroom_bytes": (
                int(required_headroom_bytes)
                if required_headroom_bytes is not None
                else None
            ),
            "headroom_surplus_bytes": (
                int(headroom_surplus_bytes)
                if headroom_surplus_bytes is not None
                else None
            ),
        },
        "summary": {
            "bounded_probe": True,
            "filesystem_walk_performed": False,
            "source_inventory_trustworthy": source_trustworthy,
            "blocker_count": len(blockers),
        },
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
    }


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def classify_data_path(rel_path: str) -> DataRetentionPolicy:
    normalized = rel_path.replace("\\", "/")
    for policy in POLICIES:
        if _matches_any(normalized, policy.patterns):
            return policy
    return DataRetentionPolicy(
        "unclassified",
        "owner-review",
        (),
        "unclassified local data",
        "retain until owner review",
        "none until classified",
        "manual owner review required before deletion",
        "unknown",
        "do not delete until classified",
    )


def _policy_delete_gate(policy: DataRetentionPolicy) -> dict[str, Any]:
    if policy.name == "shared_forecast_payload_cas":
        return {
            "status": "BLOCK",
            "delete_permission": "disabled",
            "detail": policy.deletion_requirement,
        }
    if not policy.deletion_requires_review:
        return {
            "status": "NOT_REQUIRED",
            "delete_permission": "allowed_by_policy_with_manifest" if policy.local_delete_allowed else "retain",
            "detail": policy.deletion_requirement,
        }
    return {
        "status": "REVIEW_REQUIRED",
        "delete_permission": "allowed_only_with_reviewed_manifest",
        "detail": policy.deletion_requirement,
    }


def _newest_mtime(paths: list[dict[str, Any]]) -> str | None:
    if not paths:
        return None
    return max(row["modified_at_utc"] for row in paths)


def _file_row(
    path: Path,
    root: Path,
    policy: DataRetentionPolicy,
    *,
    stat: os.stat_result | None = None,
) -> dict[str, Any]:
    stat = stat or path.stat()
    rel = path.relative_to(root).as_posix()
    return {
        "path": rel,
        "policy": policy.name,
        "owner": policy.owner,
        **classification_payload(rel),
        "bytes": int(stat.st_size),
        "size_human": _format_bytes(stat.st_size),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _storage_summary_row(storage_class: str) -> dict[str, Any]:
    return {
        "storage_class": storage_class,
        "file_count": 0,
        "bytes": 0,
        "size_human": "0 B",
        "new_file_count": 0,
        "new_bytes": 0,
        "new_size_human": "0 B",
        "protected_files": 0,
        "protected_bytes": 0,
        "protected_human": "0 B",
        "artifact_families": set(),
        "delete_gate": {},
    }


def build_payload(
    root: str | Path = DEFAULT_DATA_ROOT,
    *,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    min_growth_headroom_days: float = DEFAULT_MIN_GROWTH_HEADROOM_DAYS,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    root = Path(root)
    generated_at = datetime.now(timezone.utc)
    cutoff = generated_at - timedelta(hours=float(lookback_hours))
    event_day_manifests = summarize_event_day_manifests(root / "snapshots", check_hashes=False)
    usage_path = root if root.exists() else root.parent
    usage = shutil.disk_usage(usage_path)
    policies = {policy.name: policy for policy in POLICIES}
    summaries: dict[str, dict[str, Any]] = {}
    storage_summaries: dict[str, dict[str, Any]] = {}
    top_dirs: dict[str, dict[str, Any]] = {}
    recent_dirs: dict[str, dict[str, Any]] = {}
    largest_file_heap: list[tuple[int, str, dict[str, Any]]] = []
    recent_file_heap: list[tuple[int, str, dict[str, Any]]] = []
    recent_file_count = 0
    recent_bytes = 0
    file_count = 0
    total_bytes = 0

    def retain_top(
        heap: list[tuple[int, str, dict[str, Any]]],
        row: dict[str, Any],
    ) -> None:
        limit = max(0, int(top_n))
        if limit == 0:
            return
        item = (int(row["bytes"]), str(row["path"]), row)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)

    if root.exists():
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                path = Path(dirpath) / filename
                try:
                    stat = path.stat()
                except OSError:
                    continue
                rel = path.relative_to(root).as_posix()
                policy = classify_data_path(rel)
                row = _file_row(path, root, policy, stat=stat)
                file_count += 1
                total_bytes += row["bytes"]
                summary = summaries.setdefault(policy.name, {
                    "policy": policy.name,
                    "owner": policy.owner,
                    "file_count": 0,
                    "bytes": 0,
                    "size_human": "0 B",
                    "largest_file": None,
                    "new_file_count": 0,
                    "new_bytes": 0,
                    "new_size_human": "0 B",
                    "newest_modified_at_utc": None,
                    "delete_gate": {},
                })
                summary["file_count"] += 1
                summary["bytes"] += row["bytes"]
                storage_summary = storage_summaries.setdefault(
                    row["storage_class"],
                    _storage_summary_row(row["storage_class"]),
                )
                storage_summary["file_count"] += 1
                storage_summary["bytes"] += row["bytes"]
                if row.get("protected"):
                    storage_summary["protected_files"] += 1
                    storage_summary["protected_bytes"] += row["bytes"]
                if row.get("artifact_family"):
                    storage_summary["artifact_families"].add(row["artifact_family"])
                if not summary["largest_file"] or row["bytes"] > summary["largest_file"]["bytes"]:
                    summary["largest_file"] = row
                modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                if modified >= cutoff:
                    summary["new_file_count"] += 1
                    summary["new_bytes"] += row["bytes"]
                    storage_summary["new_file_count"] += 1
                    storage_summary["new_bytes"] += row["bytes"]
                    recent_file_count += 1
                    recent_bytes += int(row["bytes"])
                    retain_top(recent_file_heap, row)
                    dir_key = rel.split("/", 1)[0]
                    recent_dir = recent_dirs.setdefault(dir_key, {"path": dir_key, "file_count": 0, "bytes": 0})
                    recent_dir["file_count"] += 1
                    recent_dir["bytes"] += row["bytes"]
                dir_key = rel.split("/", 1)[0]
                top_dir = top_dirs.setdefault(dir_key, {"path": dir_key, "file_count": 0, "bytes": 0})
                top_dir["file_count"] += 1
                top_dir["bytes"] += row["bytes"]
                retain_top(largest_file_heap, row)

    for name, summary in summaries.items():
        policy = policies.get(name) or classify_data_path("")
        summary["size_human"] = _format_bytes(summary["bytes"])
        summary["new_size_human"] = _format_bytes(summary["new_bytes"])
        summary["delete_gate"] = _policy_delete_gate(policy)
        if summary["largest_file"]:
            summary["newest_modified_at_utc"] = _newest_mtime([summary["largest_file"]])

    for storage_class, summary in storage_summaries.items():
        summary["size_human"] = _format_bytes(summary["bytes"])
        summary["new_size_human"] = _format_bytes(summary["new_bytes"])
        summary["protected_human"] = _format_bytes(summary["protected_bytes"])
        summary["artifact_families"] = sorted(summary["artifact_families"])
        summary["delete_gate"] = delete_gate_for_storage_class(storage_class)

    largest_files = [item[2] for item in sorted(largest_file_heap, reverse=True)]
    recent_files = [item[2] for item in sorted(recent_file_heap, reverse=True)]
    largest_dirs = sorted(top_dirs.values(), key=lambda row: row["bytes"], reverse=True)
    new_dirs = sorted(recent_dirs.values(), key=lambda row: row["bytes"], reverse=True)
    for rows in (largest_dirs, new_dirs):
        for row in rows:
            row["size_human"] = _format_bytes(row["bytes"])

    daily_recent_bytes = (
        float(recent_bytes) * 24.0 / float(lookback_hours)
        if float(lookback_hours) > 0.0
        else 0.0
    )
    growth_headroom_days = (
        float(usage.free) / daily_recent_bytes if daily_recent_bytes > 0.0 else None
    )
    growth_headroom_shortfall_days = (
        max(0.0, float(min_growth_headroom_days) - growth_headroom_days)
        if growth_headroom_days is not None
        else 0.0
    )
    free_shortfall = max(0, int(min_free_bytes) - int(usage.free))
    status = "PASS"
    if free_shortfall or growth_headroom_shortfall_days > 0.0:
        status = "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "mode": "full_inventory",
        "evidence_contract": "full_data_tree_retention_inventory",
        "status": status,
        "root": str(root),
        "root_exists": root.exists(),
        "lookback_hours": float(lookback_hours),
        "min_free_bytes": int(min_free_bytes),
        "min_growth_headroom_days": float(min_growth_headroom_days),
        "disk": {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "free_human": _format_bytes(usage.free),
            "free_shortfall_bytes": int(free_shortfall),
            "free_shortfall_human": _format_bytes(free_shortfall),
            "daily_recent_bytes": int(daily_recent_bytes),
            "daily_recent_human": _format_bytes(daily_recent_bytes),
            "growth_headroom_days": growth_headroom_days,
            "growth_headroom_shortfall_days": growth_headroom_shortfall_days,
        },
        "event_day_manifests": event_day_manifests,
        "summary": {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "total_human": _format_bytes(total_bytes),
            "policy_count": len(summaries),
            "storage_class_count": len(storage_summaries),
            "review_required_class_count": sum(
                1
                for row in summaries.values()
                if (row.get("delete_gate") or {}).get("status") == "REVIEW_REQUIRED"
                and row.get("bytes", 0) > 0
            ),
            "recent_file_count": recent_file_count,
            "recent_bytes": recent_bytes,
            "recent_human": _format_bytes(recent_bytes),
        },
        "storage_class_contracts": storage_class_contracts_payload(),
        "storage_class_summaries": sorted(storage_summaries.values(), key=lambda row: row["bytes"], reverse=True),
        "policies": [asdict(policy) for policy in POLICIES],
        "policy_summaries": sorted(summaries.values(), key=lambda row: row["bytes"], reverse=True),
        "largest_directories": largest_dirs[: int(top_n)],
        "recent_directories": new_dirs[: int(top_n)],
        "largest_files": largest_files[: int(top_n)],
        "recent_files": recent_files[: int(top_n)],
    }


def render_headroom_probe_report(payload: dict[str, Any]) -> str:
    source = payload.get("source_inventory") or {}
    disk = payload.get("disk") or {}
    summary = payload.get("summary") or {}
    headroom = disk.get("growth_headroom_days")
    source_age = source.get("age_hours")
    return "\n".join(
        [
            "# Bounded Storage Headroom Probe",
            "",
            f"Generated: {payload.get('generated_at_utc')}",
            f"Status: **{payload.get('status')}**",
            f"Root: `{payload.get('root')}`",
            "",
            "## Evidence Contract",
            "",
            *markdown_table(
                ["Field", "Value"],
                [
                    ["Filesystem walk performed", summary.get("filesystem_walk_performed")],
                    ["Prior full inventory", source.get("path")],
                    ["Prior inventory SHA-256", source.get("sha256")],
                    ["Pinned SHA-256", source.get("expected_sha256") or "-"],
                    ["Pinned hash matches", source.get("hash_matches_expected")],
                    ["Source inventory mode", source.get("mode")],
                    ["Source inventory generated", source.get("generated_at_utc")],
                    [
                        "Source inventory age",
                        "-" if source_age is None else f"{source_age:.1f} hours",
                    ],
                    ["Maximum source age", f"{payload.get('max_source_age_hours')} hours"],
                    ["Source inventory trustworthy", source.get("trustworthy")],
                    ["Observed lookback", f"{source.get('lookback_hours')} hours"],
                    ["Observed recent bytes", _format_bytes(source.get("recent_bytes"))],
                    ["Reused daily write rate", disk.get("daily_recent_human")],
                ],
            ),
            "",
            "## Current Disk Headroom",
            "",
            *markdown_table(
                ["Field", "Value"],
                [
                    ["Current free space", disk.get("free_human")],
                    ["Minimum free space", _format_bytes(payload.get("min_free_bytes"))],
                    ["Free-space shortfall", disk.get("free_shortfall_human")],
                    [
                        "Growth headroom",
                        "-" if headroom is None else f"{headroom:.1f} days",
                    ],
                    [
                        "Minimum growth headroom",
                        f"{payload.get('min_growth_headroom_days')} days",
                    ],
                    [
                        "Required headroom bytes",
                        _format_bytes(disk.get("required_headroom_bytes")),
                    ],
                    [
                        "Headroom surplus bytes",
                        _format_bytes(disk.get("headroom_surplus_bytes")),
                    ],
                ],
            ),
            "",
            "## Blockers",
            "",
            *markdown_table(
                ["Code", "Detail"],
                [
                    [row.get("code"), row.get("detail")]
                    for row in payload.get("blockers") or []
                ],
            ),
            "",
        ]
    )


def render_report(payload: dict[str, Any]) -> str:
    if payload.get("mode") == "bounded_storage_headroom_probe":
        return render_headroom_probe_report(payload)
    summary = payload.get("summary") or {}
    disk = payload.get("disk") or {}
    lines = [
        "# Data Retention Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Root: `{payload.get('root')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Files scanned", summary.get("file_count")],
                ["Total size", summary.get("total_human")],
                ["Recent growth window", f"{payload.get('lookback_hours')} hours"],
                ["Recent bytes", summary.get("recent_human")],
                ["Daily recent-byte rate", disk.get("daily_recent_human")],
                [
                    "Growth headroom",
                    "-"
                    if disk.get("growth_headroom_days") is None
                    else f"{disk.get('growth_headroom_days'):.1f} days",
                ],
                ["Minimum growth headroom", f"{payload.get('min_growth_headroom_days'):.1f} days"],
                ["Free space", disk.get("free_human")],
                ["Free-space shortfall", disk.get("free_shortfall_human")],
                ["Review-required classes", summary.get("review_required_class_count")],
                ["Event-day manifests", (payload.get("event_day_manifests") or {}).get("manifest_count")],
                ["Blocked event-day manifests", (payload.get("event_day_manifests") or {}).get("block_count")],
            ],
        ),
        "",
        "## Storage Class Summary",
        "",
        *markdown_table(
            [
                "Storage Class",
                "Files",
                "Size",
                "New bytes",
                "Protected bytes",
                "Delete gate",
                "Delete permission",
                "Artifact families",
            ],
            [
                [
                    row.get("storage_class"),
                    row.get("file_count"),
                    row.get("size_human"),
                    row.get("new_size_human"),
                    row.get("protected_human"),
                    (row.get("delete_gate") or {}).get("status"),
                    (row.get("delete_gate") or {}).get("delete_permission"),
                    ", ".join((row.get("artifact_families") or [])[:6]),
                ]
                for row in payload.get("storage_class_summaries") or []
            ],
        ),
        "",
        "## Ownership And Retention",
        "",
        *markdown_table(
            ["Class", "Owner", "Files", "Size", "New bytes", "Delete gate", "Delete permission"],
            [
                [
                    row.get("policy"),
                    row.get("owner"),
                    row.get("file_count"),
                    row.get("size_human"),
                    row.get("new_size_human"),
                    (row.get("delete_gate") or {}).get("status"),
                    (row.get("delete_gate") or {}).get("delete_permission"),
                ]
                for row in payload.get("policy_summaries") or []
            ],
        ),
        "",
        "## Largest Directories",
        "",
        *markdown_table(
            ["Directory", "Files", "Size"],
            [[row.get("path"), row.get("file_count"), row.get("size_human")] for row in payload.get("largest_directories") or []],
        ),
        "",
        "## Recent Growth",
        "",
        *markdown_table(
            ["Directory", "Files", "Size"],
            [[row.get("path"), row.get("file_count"), row.get("size_human")] for row in payload.get("recent_directories") or []],
        ),
        "",
        "## Largest Files",
        "",
        *markdown_table(
            ["Path", "Policy", "Storage Class", "Artifact Family", "Size", "Modified"],
            [
                [
                    row.get("path"),
                    row.get("policy"),
                    row.get("storage_class"),
                    row.get("artifact_family"),
                    row.get("size_human"),
                    row.get("modified_at_utc"),
                ]
                for row in payload.get("largest_files") or []
            ],
        ),
        "",
        "## Operator Procedure",
        "",
        "Use the generated class table to pick the owning procedure, then create a reviewed cleanup manifest before removing local files. Prefer tiering or externalization for large historical JSONL/CSV evidence.",
        "",
    ]
    return "\n".join(lines)


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def _run_full_inventory(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Inventory data ownership, retention policy, and disk growth.")
    parser.add_argument("--root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument(
        "--min-growth-headroom-days",
        type=float,
        default=DEFAULT_MIN_GROWTH_HEADROOM_DAYS,
    )
    parser.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args(argv)
    payload = build_payload(
        args.root,
        min_free_bytes=args.min_free_bytes,
        min_growth_headroom_days=args.min_growth_headroom_days,
        lookback_hours=args.lookback_hours,
        top_n=args.top_n,
    )
    out = write_json(args.out, payload)
    report = write_report(args.report, payload)
    print(f"Data retention inventory: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] in {"PASS", "WARN"} else 2


def _run_headroom_probe(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh current storage headroom from a recent hashed full inventory "
            "without walking the data tree."
        )
    )
    parser.add_argument("--source-inventory", required=True)
    parser.add_argument(
        "--root",
        default=None,
        help="Current data root; defaults to the root recorded by the source inventory.",
    )
    parser.add_argument("--out", default=str(DEFAULT_HEADROOM_PROBE_OUT))
    parser.add_argument("--report", default=str(DEFAULT_HEADROOM_PROBE_REPORT))
    parser.add_argument(
        "--max-source-age-hours",
        type=float,
        default=DEFAULT_MAX_SOURCE_AGE_HOURS,
    )
    parser.add_argument(
        "--min-growth-headroom-days",
        type=float,
        default=DEFAULT_MIN_GROWTH_HEADROOM_DAYS,
    )
    parser.add_argument("--min-free-bytes", type=int, default=None)
    parser.add_argument("--expected-source-sha256", default=None)
    args = parser.parse_args(argv)
    if Path(args.source_inventory).resolve() == Path(args.out).resolve():
        parser.error("--out must differ from --source-inventory")
    payload = build_headroom_probe(
        args.source_inventory,
        root=args.root,
        max_source_age_hours=args.max_source_age_hours,
        min_growth_headroom_days=args.min_growth_headroom_days,
        min_free_bytes=args.min_free_bytes,
        expected_source_sha256=args.expected_source_sha256,
    )
    out = write_json(args.out, payload)
    report = write_report(args.report, payload)
    print(f"Data retention headroom probe: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] == "PASS" else 2


def main(argv: list[str] | None = None) -> int:
    command_args = list(sys.argv[1:] if argv is None else argv)
    if command_args[:1] == ["headroom-probe"]:
        return _run_headroom_probe(command_args[1:])
    if command_args[:1] == ["inventory"]:
        command_args = command_args[1:]
    return _run_full_inventory(command_args)


if __name__ == "__main__":
    raise SystemExit(main())
