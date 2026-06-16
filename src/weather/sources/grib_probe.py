"""Source-neutral GRIB2 probe and tiny extraction helpers.

This module intentionally avoids a mandatory GRIB dependency. It can validate
and describe GRIB2 payloads with the standard library, and it wraps ``wgrib2``
for nearest-gridpoint scalar extraction when that CLI is available.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests


GRIB_PROBE_SCHEMA_VERSION = "grib_probe_v0.1"


class GribProbeError(RuntimeError):
    """Base error for GRIB probe failures."""


class GribValidationError(GribProbeError):
    """Raised when a payload is not recognized as GRIB2."""


class GribToolUnavailable(GribProbeError):
    """Raised when nearest extraction needs a missing local GRIB tool."""


@dataclass(frozen=True)
class GribBoundingBox:
    leftlon: float
    rightlon: float
    toplat: float
    bottomlat: float

    def nomads_params(self) -> dict:
        return {
            "leftlon": self.leftlon,
            "rightlon": self.rightlon,
            "toplat": self.toplat,
            "bottomlat": self.bottomlat,
        }


@dataclass(frozen=True)
class GribCachePolicy:
    max_age_minutes: int = 90
    max_bytes: int = 50_000_000
    provider_pause_seconds: float = 0.4
    provider: str = "generic"

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_GRIB_CACHE_POLICY = GribCachePolicy()
PROVIDER_CACHE_POLICIES = {
    "nomads": GribCachePolicy(max_age_minutes=90, max_bytes=250_000_000, provider_pause_seconds=0.4, provider="nomads"),
    "s3": GribCachePolicy(max_age_minutes=180, max_bytes=500_000_000, provider_pause_seconds=0.2, provider="s3"),
    "eccc_datamart": GribCachePolicy(max_age_minutes=180, max_bytes=500_000_000, provider_pause_seconds=0.6, provider="eccc_datamart"),
    "generic": DEFAULT_GRIB_CACHE_POLICY,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def grib_provider_for_url(url: str | None = None, provider: str | None = None) -> str:
    if provider:
        return str(provider).strip().lower()
    host = urlparse(str(url or "")).netloc.lower()
    if "nomads.ncep.noaa.gov" in host:
        return "nomads"
    if "amazonaws.com" in host or host.endswith(".s3.amazonaws.com"):
        return "s3"
    if "dd.weather.gc.ca" in host or "weather.gc.ca" in host:
        return "eccc_datamart"
    return "generic"


def provider_cache_policy(provider: str | None = None, source_url: str | None = None, override: GribCachePolicy | None = None) -> GribCachePolicy:
    if override is not None:
        return override
    key = grib_provider_for_url(source_url, provider=provider)
    return PROVIDER_CACHE_POLICIES.get(key, DEFAULT_GRIB_CACHE_POLICY)


def cache_key_for_request(url: str, params: dict | None = None) -> str:
    query = urlencode(sorted((params or {}).items()), doseq=True)
    raw = f"{url}?{query}" if query else str(url)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_path_for_request(cache_root, url: str, params: dict | None = None, suffix: str = ".bin") -> Path:
    suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
    return Path(cache_root) / f"{cache_key_for_request(url, params=params)}{suffix}"


def cache_entry_fresh(path, policy: GribCachePolicy, now=None) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    now_ts = (now or utc_now()).timestamp()
    max_age = max(0, int(policy.max_age_minutes)) * 60
    age = now_ts - path.stat().st_mtime
    return age <= max_age


def cleanup_grib_cache(cache_root, policy: GribCachePolicy, now=None) -> dict:
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    now = now or utc_now()
    removed = []
    kept = []
    for path in sorted(root.glob("*")):
        if not path.is_file():
            continue
        expired = not cache_entry_fresh(path, policy, now=now)
        if expired:
            removed.append({"path": str(path), "bytes": path.stat().st_size, "reason": "expired"})
            path.unlink()
        else:
            kept.append(path)
    total = sum(path.stat().st_size for path in kept if path.exists())
    max_bytes = max(0, int(policy.max_bytes))
    if max_bytes and total > max_bytes:
        for path in sorted([p for p in kept if p.exists()], key=lambda item: item.stat().st_mtime):
            size = path.stat().st_size
            removed.append({"path": str(path), "bytes": size, "reason": "max_bytes"})
            path.unlink()
            total -= size
            if total <= max_bytes:
                break
    return {
        "cache_root": str(root),
        "policy": policy.as_dict(),
        "removed_count": len(removed),
        "removed_bytes": sum(item["bytes"] for item in removed),
        "remaining_bytes": max(0, total),
        "removed": removed,
    }


def read_cached_payload(cache_root, url: str, params: dict | None, policy: GribCachePolicy, suffix=".bin", now=None):
    path = cache_path_for_request(cache_root, url, params=params, suffix=suffix)
    if cache_entry_fresh(path, policy, now=now):
        return path.read_bytes(), {"cache_hit": True, "cache_path": str(path)}
    return None, {"cache_hit": False, "cache_path": str(path)}


def write_cached_payload(cache_root, url: str, params: dict | None, payload: bytes, suffix=".bin") -> str:
    path = cache_path_for_request(cache_root, url, params=params, suffix=suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return str(path)


def provider_pause(policy: GribCachePolicy, sleep_fn=time.sleep) -> None:
    pause = max(0.0, float(policy.provider_pause_seconds or 0.0))
    if pause:
        sleep_fn(pause)


def payload_hash(payload: bytes) -> str:
    return hashlib.sha1(payload).hexdigest()


def is_grib2(payload: bytes) -> bool:
    """Return True when ``payload`` starts with a GRIB2 indicator section."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < 8:
        return False
    return bytes(payload[:4]) == b"GRIB" and payload[7] == 2


def validate_grib2(payload: bytes) -> None:
    if not is_grib2(payload):
        raise GribValidationError("payload is not a GRIB2 message")


def parse_idx_lines(text: str) -> list[dict]:
    """Parse NCEP/NOMADS ``.idx`` lines.

    Example line::

        1:0:d=2026061520:TMP:2 m above ground:1 hour fcst:
    """
    records = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 3:
            continue
        try:
            message_number = int(parts[0])
            byte_offset = int(parts[1])
        except ValueError:
            continue
        records.append({
            "message_number": message_number,
            "byte_offset": byte_offset,
            "byte_end": None,
            "date_code": parts[2] if len(parts) > 2 else "",
            "variable": parts[3] if len(parts) > 3 else "",
            "level": parts[4] if len(parts) > 4 else "",
            "forecast_step": parts[5] if len(parts) > 5 else "",
            "raw_line": line,
        })
    for index, record in enumerate(records[:-1]):
        record["byte_end"] = records[index + 1]["byte_offset"] - 1
    return records


def select_idx_records(
    records,
    variable: str | None = None,
    level_contains: str | None = None,
    forecast_step_contains: str | None = None,
) -> list[dict]:
    selected = []
    variable_lower = variable.lower() if variable else None
    level_lower = level_contains.lower() if level_contains else None
    step_lower = forecast_step_contains.lower() if forecast_step_contains else None
    for record in records or []:
        if variable_lower and str(record.get("variable") or "").lower() != variable_lower:
            continue
        if level_lower and level_lower not in str(record.get("level") or "").lower():
            continue
        if step_lower and step_lower not in str(record.get("forecast_step") or "").lower():
            continue
        selected.append(dict(record))
    return selected


def _nomads_key(prefix: str, value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")
    return f"{prefix}_{token}"


def build_nomads_subset_params(
    file: str,
    directory: str,
    variables=(),
    levels=(),
    bbox: GribBoundingBox | None = None,
    extra: dict | None = None,
) -> dict:
    params = {"file": file, "dir": directory}
    for variable in variables or ():
        params[_nomads_key("var", variable)] = "on"
    for level in levels or ():
        params[_nomads_key("lev", level)] = "on"
    if bbox is not None:
        params.update(bbox.nomads_params())
    if extra:
        params.update(extra)
    return params


def probe_grib_payload(
    payload: bytes,
    source: str,
    model: str,
    source_url: str,
    idx_text: str | None = None,
    object_key: str | None = None,
    run_time: str | None = None,
    forecast_hour: int | None = None,
    valid_time: str | None = None,
    grid: str | None = None,
    domain: str | None = None,
    fetched_at: str | None = None,
    cache_policy: GribCachePolicy | None = None,
    cache_status: dict | None = None,
) -> dict:
    validate_grib2(payload)
    idx_records = parse_idx_lines(idx_text or "")
    policy = cache_policy or provider_cache_policy(source_url=source_url, provider=source)
    return {
        "schema_version": GRIB_PROBE_SCHEMA_VERSION,
        "source": source,
        "model": model,
        "run_time": run_time,
        "forecast_hour": forecast_hour,
        "valid_time": valid_time,
        "grid": grid,
        "domain": domain,
        "source_url": source_url,
        "object_key": object_key,
        "payload_hash": payload_hash(payload),
        "payload_bytes": len(payload),
        "grib_edition": 2,
        "idx_record_count": len(idx_records),
        "idx_records": idx_records,
        "fetched_at": fetched_at,
        "cache_policy": policy.as_dict(),
        "cache_status": cache_status or {},
    }


def fetch_grib_probe(
    source_url: str,
    idx_url: str | None = None,
    session=None,
    timeout: int = 30,
    cache_root=None,
    cache_policy: GribCachePolicy | None = None,
    provider: str | None = None,
    sleep_fn=time.sleep,
    now=None,
    **metadata,
) -> dict:
    client = session or requests
    source = metadata.get("source") or provider
    policy = provider_cache_policy(provider=source, source_url=source_url, override=cache_policy)
    cache_status = {"provider": policy.provider, "cache_hit": False, "idx_cache_hit": False}
    payload = None
    if cache_root:
        cleanup = cleanup_grib_cache(cache_root, policy, now=now)
        payload, status = read_cached_payload(cache_root, source_url, None, policy, suffix=".grib2", now=now)
        cache_status.update(status)
        cache_status["cleanup"] = {
            "removed_count": cleanup["removed_count"],
            "removed_bytes": cleanup["removed_bytes"],
            "remaining_bytes": cleanup["remaining_bytes"],
        }
    if payload is None:
        provider_pause(policy, sleep_fn=sleep_fn)
        response = client.get(source_url, timeout=timeout)
        response.raise_for_status()
        payload = response.content
        if cache_root:
            cache_status["cache_path"] = write_cached_payload(cache_root, source_url, None, payload, suffix=".grib2")
    idx_text = None
    if idx_url:
        idx_bytes = None
        if cache_root:
            idx_bytes, idx_status = read_cached_payload(cache_root, idx_url, None, policy, suffix=".idx", now=now)
            cache_status["idx_cache_hit"] = idx_status["cache_hit"]
            cache_status["idx_cache_path"] = idx_status["cache_path"]
        if idx_bytes is None:
            provider_pause(policy, sleep_fn=sleep_fn)
            idx_response = client.get(idx_url, timeout=timeout)
            idx_response.raise_for_status()
            idx_text = idx_response.text
            if cache_root:
                cache_status["idx_cache_path"] = write_cached_payload(cache_root, idx_url, None, idx_text.encode("utf-8"), suffix=".idx")
        else:
            idx_text = idx_bytes.decode("utf-8", errors="replace")
    return probe_grib_payload(
        payload,
        source_url=source_url,
        idx_text=idx_text,
        cache_policy=policy,
        cache_status=cache_status,
        **metadata,
    )


def parse_wgrib2_lon_output(text: str) -> float | None:
    for line in str(text or "").splitlines():
        match = re.search(r"\bval=(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", line)
        if match:
            return float(match.group(1))
    return None


def extract_nearest_with_wgrib2(
    grib_path,
    lon: float,
    lat: float,
    match: str,
    wgrib2_path: str | None = None,
    runner=None,
    timeout: int = 30,
) -> dict:
    tool = wgrib2_path or shutil.which("wgrib2")
    if not tool:
        raise GribToolUnavailable("wgrib2 is required for nearest GRIB extraction")
    command = [tool, str(Path(grib_path)), "-match", match, "-lon", str(lon), str(lat)]
    run = runner or subprocess.run
    result = run(command, capture_output=True, text=True, timeout=timeout)
    if getattr(result, "returncode", 0) != 0:
        stderr = getattr(result, "stderr", "") or ""
        raise GribProbeError(f"wgrib2 failed: {stderr.strip()}")
    stdout = getattr(result, "stdout", "") or ""
    value = parse_wgrib2_lon_output(stdout)
    if value is None:
        raise GribProbeError("wgrib2 output did not include a scalar val=")
    return {
        "value": value,
        "lon": lon,
        "lat": lat,
        "match": match,
        "command": command,
        "raw_output": stdout,
    }


def normalize_grib_row(
    source: str,
    model: str,
    field: str,
    value,
    unit: str,
    run_time: str | None = None,
    forecast_hour: int | None = None,
    valid_time: str | None = None,
    grid: str | None = None,
    domain: str | None = None,
    source_url: str | None = None,
    payload_hash_value: str | None = None,
    fetched_at: str | None = None,
    idx_line: str | None = None,
    object_key: str | None = None,
) -> dict:
    return {
        "schema_version": GRIB_PROBE_SCHEMA_VERSION,
        "source": source,
        "model": model,
        "field": field,
        "value": value,
        "unit": unit,
        "run_time": run_time,
        "forecast_hour": forecast_hour,
        "valid_time": valid_time,
        "grid": grid,
        "domain": domain,
        "source_url": source_url,
        "payload_hash": payload_hash_value,
        "fetched_at": fetched_at,
        "idx_line": idx_line,
        "object_key": object_key,
    }
