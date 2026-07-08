"""Per-market-day replay result cache.

The cache is keyed by immutable corpus inputs plus the replay model identity
and a small explicit row-affecting config fingerprint. It is deliberately not
keyed by a broad source-code hash; row-shape changes must bump the registered
``replay_cache`` schema version.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import write_json_atomic
from weather.paths import data_path
from weather.schema_registry import schema_version


REPLAY_CACHE_SCHEMA_VERSION = schema_version("replay_cache")
DEFAULT_REPLAY_CACHE_ROOT = data_path() / "backtest" / "replay_cache"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def replay_cache_policy(value: str | None) -> dict[str, bool | str]:
    mode = str(value or "read_write").strip().lower().replace("-", "_")
    aliases = {
        "on": "read_write",
        "true": "read_write",
        "1": "read_write",
        "rw": "read_write",
        "read": "read_write",
        "write": "write_only",
        "writeonly": "write_only",
        "write_only": "write_only",
        "off": "off",
        "false": "off",
        "0": "off",
        "none": "off",
    }
    mode = aliases.get(mode, mode)
    if mode not in {"read_write", "write_only", "off"}:
        raise ValueError(f"unknown replay cache mode: {value!r}")
    return {
        "mode": mode,
        "read": mode == "read_write",
        "write": mode in {"read_write", "write_only"},
    }


def cache_root_for_corpus(corpus_path: str | Path, configured_root: str | Path | None = None) -> Path:
    if configured_root:
        return Path(configured_root)
    corpus_path = Path(corpus_path)
    if corpus_path.parent:
        return corpus_path.parent / "replay_cache"
    return DEFAULT_REPLAY_CACHE_ROOT


def entry_inputs_fingerprint(entry: dict[str, Any]) -> str:
    """Fingerprint pinned corpus fields that define one market-day's rows."""
    payload = {
        "event_slug": entry.get("event_slug"),
        "market_id": entry.get("market_id"),
        "target_date": entry.get("target_date"),
        "snapshot_ids": [str(item) for item in (entry.get("snapshot_ids") or [])],
        "replay_record_hashes": entry.get("replay_record_hashes") or {},
        "tape_row_hashes": entry.get("tape_row_hashes") or {},
        "settlement_bucket": entry.get("settlement_bucket"),
        "settlement_high": entry.get("settlement_high"),
        "settlement_unit": entry.get("settlement_unit"),
        "settlement_source": entry.get("settlement_source"),
        "winning_band": entry.get("winning_band"),
        "winning_band_kind": entry.get("winning_band_kind"),
        "winning_band_value": entry.get("winning_band_value"),
        "winning_band_value_hi": entry.get("winning_band_value_hi"),
        "quality_grade": entry.get("quality_grade"),
        "admitted_by": entry.get("admitted_by"),
        "promotion_countable": bool(entry.get("promotion_countable")),
        "promotion_countable_reason": entry.get("promotion_countable_reason"),
        "material_coverage_grade": entry.get("material_coverage_grade"),
        "coverage_clean": bool(entry.get("coverage_clean")),
        "capture_ratio": entry.get("capture_ratio"),
        "max_gap_minutes": entry.get("max_gap_minutes"),
        "coverage_reason": entry.get("coverage_reason"),
        "feature_quality_excluded_snapshot_ids": entry.get("feature_quality_excluded_snapshot_ids") or [],
        "label_hash": entry.get("label_hash"),
    }
    return fingerprint(payload)


def config_fingerprint(config: dict[str, Any]) -> str:
    return fingerprint(config)


def short_fp(value: str) -> str:
    return str(value or "")[:12]


def _safe_component(value: str) -> str:
    text = str(value or "unknown")
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)


@dataclass(frozen=True)
class ReplayCacheKey:
    event_slug: str
    consumer: str
    inputs_fp: str
    model_fp: str
    config_fp: str
    schema_version: str = REPLAY_CACHE_SCHEMA_VERSION

    def metadata(self) -> dict[str, str]:
        return {
            "event_slug": self.event_slug,
            "consumer": self.consumer,
            "inputs_fp": self.inputs_fp,
            "model_fp": self.model_fp,
            "config_fp": self.config_fp,
            "schema_version": self.schema_version,
        }


def key_for_entry(
    entry: dict[str, Any],
    *,
    consumer: str,
    model_fp: str,
    config_fp: str,
) -> ReplayCacheKey:
    return ReplayCacheKey(
        event_slug=str(entry.get("event_slug") or entry.get("folder_name") or "unknown"),
        consumer=_safe_component(consumer),
        inputs_fp=entry_inputs_fingerprint(entry),
        model_fp=str(model_fp or "unknown"),
        config_fp=str(config_fp or "unknown"),
    )


def cache_path(root: str | Path, key: ReplayCacheKey) -> Path:
    filename = (
        f"{_safe_component(key.consumer)}__"
        f"{short_fp(key.model_fp)}__{short_fp(key.inputs_fp)}__{short_fp(key.config_fp)}.json"
    )
    return Path(root) / _safe_component(key.event_slug) / filename


def read_entry(root: str | Path, key: ReplayCacheKey) -> dict[str, Any] | None:
    path = cache_path(root, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != REPLAY_CACHE_SCHEMA_VERSION:
        return None
    if (payload.get("key") or {}) != key.metadata():
        return None
    if not isinstance(payload.get("rows"), list):
        return None
    payload["path"] = str(path)
    return payload


def write_entry(
    root: str | Path,
    key: ReplayCacheKey,
    *,
    rows: list[dict[str, Any]],
    replay_results: dict[str, Any],
    coverage: dict[str, Any],
    diagnostics: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "schema_version": REPLAY_CACHE_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "writer_pid": os.getpid(),
        "key": key.metadata(),
        "metadata": metadata or {},
        "rows": rows,
        "replay_results": replay_results,
        "coverage": coverage,
        "diagnostics": diagnostics,
    }
    return write_json_atomic(cache_path(root, key), payload, trailing_newline=True)


def rows_match(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return canonical_json(left) == canonical_json(right)


def select_sentinel(entries: list[dict[str, Any]], *, consumer: str, seed: str | None = None) -> dict[str, Any] | None:
    if not entries:
        return None
    seed = seed or datetime.now(timezone.utc).date().isoformat()
    index = int(fingerprint({"consumer": consumer, "seed": seed})[:8], 16) % len(entries)
    return entries[index]


def flush_consumer(root: str | Path, consumer: str) -> dict[str, Any]:
    root = Path(root)
    safe_consumer = _safe_component(consumer)
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    if not root.exists():
        return {"removed_count": 0, "removed_paths": [], "errors": []}
    for path in root.glob(f"*/{safe_consumer}__*.json"):
        try:
            path.unlink()
            removed.append(str(path))
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {
        "removed_count": len(removed),
        "removed_paths": removed[:100],
        "errors": errors,
    }
