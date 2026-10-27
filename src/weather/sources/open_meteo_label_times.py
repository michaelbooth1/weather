"""Fail-closed market-local times for Open-Meteo hourly labels in training and backfill readers.

Open-Meteo returns naive hourly labels plus one scalar ``utc_offset_seconds`` per response: the zone's offset
when the request was served, applied to every label (EF §10w). Read as zone wall time, every label on the far
side of a DST change is one hour off, so a summer download of a standard-time date is +1 h. The conversion
itself is ``weather.time.provider_hourly_local_times`` (one implementation, shared with the live fetchers);
this module only adds the training rule: when a naive label has no usable response offset, the rows are
refused, never read as zone wall time.
"""

from __future__ import annotations

import math
from datetime import datetime

from weather.time import provider_hourly_local_times

REFUSED_NO_OFFSET = "open_meteo_utc_offset_seconds_missing"


def response_offset_seconds(payload):
    """The payload's own ``utc_offset_seconds`` as whole seconds, or None when absent or unusable."""
    value = payload.get("utc_offset_seconds") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value != int(value) or abs(value) >= 86400:
        return None
    return int(value)


def payload_local_times(payload, tz):
    """Market-local times aligned index-for-index with ``payload["hourly"]["time"]``. -> (times, refusal).

    Labels carrying their own offset are converted. Naive labels need the response's ``utc_offset_seconds``:
    without a usable one every naive label is None and ``refusal`` is ``REFUSED_NO_OFFSET`` (the caller refuses
    those rows). Unparseable labels are None.
    """
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    labels = hourly.get("time") if isinstance(hourly, dict) else None
    labels = list(labels or [])
    offset = response_offset_seconds(payload)
    times = provider_hourly_local_times(labels, tz, offset)
    if offset is not None:
        return times, None
    naive = [_is_naive(label) for label in labels]
    if not any(naive):
        return times, None
    return [None if is_naive else value for value, is_naive in zip(times, naive)], REFUSED_NO_OFFSET


def _is_naive(label):
    try:
        return datetime.fromisoformat(str(label).replace("Z", "+00:00")).tzinfo is None
    except (TypeError, ValueError):
        return False
