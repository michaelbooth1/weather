"""Bounded, capture-only cache for public Gamma event discovery."""

from copy import deepcopy
import threading
import time


_EVENTS = {}
_LOCK = threading.Lock()
EVENT_TTL_SECONDS = 600.0


def capture_event(client):
    # Bind the resolved date/slug, not a moving 'today' argument. The client
    # type isolates injected transports; callers receive independent objects.
    key = (type(client), client.config.event_slug, str(client.config.target_date))
    now = time.monotonic()
    with _LOCK:
        cached = _EVENTS.get(key)
        if cached and now - cached[0] < EVENT_TTL_SECONDS:
            return deepcopy(cached[1])
    event = client.get_event()  # failures never extend an expired entry
    with _LOCK:
        for expired in [item for item, (at, _) in _EVENTS.items()
                        if now - at >= EVENT_TTL_SECONDS]:
            del _EVENTS[expired]
        if len(_EVENTS) >= 64:
            del _EVENTS[min(_EVENTS, key=lambda item: _EVENTS[item][0])]
        _EVENTS[key] = (now, deepcopy(event))
    return event
