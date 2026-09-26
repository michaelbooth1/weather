"""Small deterministic readers for already decoded captured records. No filesystem IO."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

from maker_core.contracts import utc_time
from weather.market.market_registry import BUILTIN_SPECS


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.utcoffset() is None:
        raise ValueError("captured_timestamp_must_be_aware")
    return result.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def records(rows):
    """Own a detached JSON copy so callers cannot mutate historical inputs."""
    return tuple(json.loads(json.dumps(row, allow_nan=False)) for row in rows)


def latest(rows, as_of, key="captured_at_utc"):
    utc_time(as_of)
    eligible = [(timestamp(r[key]), r) for r in rows if timestamp(r[key]) <= as_of]
    if not eligible:
        raise ValueError("missing_point_in_time_input")
    newest = max(t for t, _ in eligible)
    matches = [r for t, r in eligible if t == newest]
    if len({digest(r) for r in matches}) != 1:
        raise ValueError("conflicting_captured_inputs")
    return matches[0]


def body(row):
    if row.get("http_status") != 200 or row.get("body_stored") is not True:
        raise ValueError("missing_successful_stored_body")
    raw = row["body_utf8"]
    expected = row.get("stored_sha256") if row.get("representation") == "selection_projection" else row.get("response_sha256")
    if hashlib.sha256(raw.encode()).hexdigest() != expected:
        raise ValueError("captured_body_hash_mismatch")
    return json.loads(raw)


def event_identity(slug):
    for spec in BUILTIN_SPECS:
        prefix = spec.slug_prefix + "-"
        if slug.startswith(prefix):
            target = datetime.strptime(slug[len(prefix):], "%B-%d-%Y").date()
            return spec, target
    raise ValueError("unregistered_event")


def band(row):
    kind = row["bin_kind"]
    lo = float(row["bin_value_c"])
    hi_value = row.get("bin_value_hi_c")
    hi = lo if hi_value in (None, "") else float(hi_value)
    if not all(math.isfinite(v) and v.is_integer() for v in (lo, hi)) or hi < lo:
        raise ValueError("invalid_native_integer_band")
    if kind == "lte":
        return -math.inf, lo + .5
    if kind == "gte":
        return lo - .5, math.inf
    if kind != "eq":
        raise ValueError("unknown_band_kind")
    return lo - .5, hi + .5
