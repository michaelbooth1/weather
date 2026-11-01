"""Fail-closed market-local times for Open-Meteo hourly labels in training and backfill readers.

Open-Meteo returns naive hourly labels plus one scalar ``utc_offset_seconds`` per response: the zone's offset
when the request was served, applied to every label (EF §10w). Read as zone wall time, every label on the far
side of a DST change is one hour off, so a summer download of a standard-time date is +1 h. The conversion
itself is ``weather.time.provider_hourly_local_times`` (one implementation, shared with the live fetchers);
this module only adds the training rules. Naive rows are refused, never read as zone wall time, when:

- the response has no usable ``utc_offset_seconds`` (``REFUSED_NO_OFFSET``); or
- the offset is usable but the naive labels are not one uniform series: a label repeats, the series has a gap,
  or an unparseable label sits mid-series (``REFUSED_NOT_FIXED_OFFSET``). The live helper keeps the zone-local
  reading for such series; a training reader cannot tell which hour each label means, so it refuses them.

Every refused row is counted (``refused_row_count``) so a refusal is never silent (item 340, R26).
"""

from __future__ import annotations

import math
from datetime import datetime

from weather.time import provider_hourly_local_times

REFUSED_NO_OFFSET = "open_meteo_utc_offset_seconds_missing"
REFUSED_NOT_FIXED_OFFSET = "open_meteo_labels_not_fixed_offset"


def response_offset_seconds(payload):
    """The payload's own ``utc_offset_seconds`` as whole seconds, or None when absent or unusable."""
    value = payload.get("utc_offset_seconds") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value != int(value) or abs(value) >= 86400:
        return None
    return int(value)


def payload_labels(payload):
    """The raw ``payload["hourly"]["time"]`` labels as a list (empty when absent)."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    labels = hourly.get("time") if isinstance(hourly, dict) else None
    if labels is None or isinstance(labels, (str, bytes, bytearray, dict)):
        return []
    return list(labels)


def payload_local_times(payload, tz):
    """Market-local times aligned index-for-index with ``payload["hourly"]["time"]``. -> (times, refusal).

    Labels carrying their own offset are converted. Naive labels need the response's ``utc_offset_seconds``
    and one uniform series: otherwise every naive label is None and ``refusal`` names why
    (``REFUSED_NO_OFFSET`` or ``REFUSED_NOT_FIXED_OFFSET``); the caller refuses those rows. Unparseable labels
    are None.
    """
    labels = payload_labels(payload)
    offset = response_offset_seconds(payload)
    times = provider_hourly_local_times(labels, tz, offset)
    parsed = [_parse(label) for label in labels]
    naive = [value is not None and value.tzinfo is None for value in parsed]
    if not any(naive):
        return times, None
    if offset is None:
        refusal = REFUSED_NO_OFFSET
    elif not _uniform_series([value for value, is_naive in zip(parsed, naive) if is_naive]):
        refusal = REFUSED_NOT_FIXED_OFFSET
    else:
        return times, None
    return [None if is_naive else value for value, is_naive in zip(times, naive)], refusal


def refused_row_count(payload, local_times, refusal):
    """Rows of ``payload`` a reader refuses: non-empty labels left without a local time by ``refusal``."""
    if refusal is None:
        return 0
    labels = payload_labels(payload)
    return sum(
        1 for index, label in enumerate(labels)
        if label and (index >= len(local_times) or local_times[index] is None)
    )


def _parse(label):
    try:
        return datetime.fromisoformat(str(label).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _uniform_series(naive_labels):
    """True when parsed naive labels never repeat and step uniformly (no gap), as a fixed-offset series does.

    Same rule as the live helper uses to decide a series is fixed-offset; unparseable labels are left out
    first, so one mid-series reads as a gap while one at either end does not.
    """
    if len(set(naive_labels)) != len(naive_labels):
        return False
    return len({later - earlier for earlier, later in zip(naive_labels, naive_labels[1:])}) <= 1
