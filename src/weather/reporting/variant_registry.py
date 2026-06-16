"""Model-variant lifecycle registry helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from weather.paths import config_path

from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_variant_registry")
DEFAULT_REGISTRY_PATH = config_path() / "model_variant_registry.json"


def empty_registry(path=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "path": str(path) if path else None,
        "exists": False,
        "variants": [],
        "by_id": {},
    }


def load_registry(path=DEFAULT_REGISTRY_PATH):
    if path in (None, ""):
        return empty_registry(path)
    path = Path(path)
    if not path.exists():
        return empty_registry(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported model variant registry schema {payload.get('schema_version')!r}"
        )
    variants = payload.get("variants") or []
    by_id = {
        str(row.get("variant_id")): dict(row)
        for row in variants
        if row.get("variant_id")
    }
    output = dict(payload)
    output["path"] = str(path)
    output["exists"] = True
    output["variants"] = variants
    output["by_id"] = by_id
    return output


def registry_entry(registry, variant_id):
    return (registry or {}).get("by_id", {}).get(str(variant_id))


def decorate_variant(metadata, registry=None):
    entry = registry_entry(registry, metadata.get("variant_id")) or {}
    is_control = bool(metadata.get("is_control"))
    lifecycle = entry.get("lifecycle") or ("control" if is_control else "unregistered")
    roles = set(entry.get("roles") or [])
    if is_control:
        roles.add("control")
    if metadata.get("uses_market_features"):
        roles.add("market-informed")
    else:
        roles.add("no-market")
    track = entry.get("track") or (
        "market_informed" if metadata.get("uses_market_features") else "no_market"
    )
    active_for_headline = entry.get("active_for_headline")
    if active_for_headline is None:
        active_for_headline = lifecycle == "active" and not is_control
    return {
        "registry_lifecycle": lifecycle,
        "registry_roles": sorted(roles),
        "registry_track": track,
        "active_for_headline": bool(active_for_headline),
        "registry_roadmap_items": entry.get("roadmap_items") or [],
        "registry_notes": entry.get("notes"),
    }


def registry_summary(variants, registry=None):
    lifecycle_counts = Counter(
        variant.get("registry_lifecycle") or "unregistered"
        for variant in variants
    )
    active = [
        variant for variant in variants
        if variant.get("active_for_headline") and not variant.get("is_control")
    ]
    archived = [
        variant for variant in variants
        if variant.get("registry_lifecycle") in {"archived", "smoke", "alpha"}
    ]
    return {
        "path": (registry or {}).get("path"),
        "schema_version": (registry or {}).get("schema_version"),
        "exists": bool((registry or {}).get("exists")),
        "registered_variant_count": len((registry or {}).get("variants") or []),
        "reported_variant_count": len(variants),
        "active_headline_variant_count": len(active),
        "active_headline_variant_ids": [variant.get("variant_id") for variant in active],
        "archived_or_historical_variant_count": len(archived),
        "unregistered_variant_count": lifecycle_counts.get("unregistered", 0),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
    }
