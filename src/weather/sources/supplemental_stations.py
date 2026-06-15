"""Registry helpers for provenance-labelled nearby historical stations."""
from __future__ import annotations

import json
from pathlib import Path

from weather.paths import CONFIG_ROOT, REPO_ROOT, relative_to_repo


REGISTRY_SCHEMA_VERSION = "supplemental_station_registry_v0.1"
DEFAULT_REGISTRY_PATH = CONFIG_ROOT / "supplemental_stations.json"
REQUIRED_FIELDS = (
    "market_id",
    "source_id",
    "source_type",
    "source_role",
    "station_id",
    "station_name",
    "root_path",
    "latitude",
    "longitude",
    "distance_from_canonical_km",
    "canonical_market_id",
    "canonical_station_id",
    "validation_status",
    "adopted_date_windows",
    "reason_for_adoption",
)


class SupplementalStationRegistryError(ValueError):
    pass


def _repo_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _normalized_root(path):
    return _repo_path(path).resolve()


def _normalize_source(row):
    source = dict(row)
    missing = [field for field in REQUIRED_FIELDS if source.get(field) in (None, "")]
    if missing:
        raise SupplementalStationRegistryError(
            f"supplemental source {source.get('source_id') or '<unknown>'} missing fields: "
            + ", ".join(missing)
        )
    if source.get("source_role") != "supplemental":
        raise SupplementalStationRegistryError(
            f"supplemental source {source['source_id']} has invalid role {source.get('source_role')!r}"
        )
    windows = source.get("adopted_date_windows")
    if not isinstance(windows, list) or not windows:
        raise SupplementalStationRegistryError(
            f"supplemental source {source['source_id']} needs adopted_date_windows"
        )
    for window in windows:
        for field in ("start", "end", "reason"):
            if not isinstance(window, dict) or not window.get(field):
                raise SupplementalStationRegistryError(
                    f"supplemental source {source['source_id']} has incomplete adopted window"
                )
    source["root_path"] = relative_to_repo(_repo_path(source["root_path"]))
    source["root_abs_path"] = str(_normalized_root(source["root_path"]))
    return source


def load_registry(path=DEFAULT_REGISTRY_PATH):
    path = Path(path)
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "sources": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise SupplementalStationRegistryError(
            f"unsupported supplemental station registry schema {payload.get('schema_version')!r}"
        )
    return {
        "schema_version": payload.get("schema_version"),
        "path": str(path),
        "sources": [_normalize_source(row) for row in payload.get("sources") or []],
    }


def supplemental_sources(market_id=None, source_type=None, registry=None):
    payload = registry or load_registry()
    rows = payload.get("sources") or []
    if market_id:
        rows = [row for row in rows if row.get("market_id") == market_id]
    if source_type:
        rows = [row for row in rows if row.get("source_type") == source_type]
    return list(rows)


def source_root(source):
    return _repo_path(source["root_path"])


def canonical_source_root(spec, source_type):
    if source_type == "noaa_ghcnh":
        return REPO_ROOT / "data" / "noaa_ghcnh" / spec.icao.lower()
    raise SupplementalStationRegistryError(f"unsupported supplemental source_type {source_type!r}")


def guard_not_canonical_root(source, spec):
    root = _normalized_root(source["root_path"])
    canonical = canonical_source_root(spec, source["source_type"]).resolve()
    if root == canonical:
        raise SupplementalStationRegistryError(
            f"supplemental source {source['source_id']} points at canonical root {relative_to_repo(canonical)}"
        )
    return True


def source_for_root(spec, root, source_type="noaa_ghcnh", registry=None):
    target = _normalized_root(root)
    for source in supplemental_sources(spec.id, source_type=source_type, registry=registry):
        if _normalized_root(source["root_path"]) == target:
            guard_not_canonical_root(source, spec)
            return source
    return None


def provenance_fields(source, spec):
    if not source:
        return {
            "source_role": "canonical",
            "canonical_market_id": spec.id,
            "supplemental_source_id": "",
            "supplemental_station_id": "",
            "source_distance_from_canonical_km": "",
        }
    guard_not_canonical_root(source, spec)
    return {
        "source_role": "supplemental",
        "canonical_market_id": source.get("canonical_market_id") or spec.id,
        "supplemental_source_id": source.get("source_id"),
        "supplemental_station_id": source.get("station_id"),
        "source_distance_from_canonical_km": source.get("distance_from_canonical_km"),
    }
