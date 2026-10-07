"""Redact the public WU page access token before anything is stored or logged.

The public WU history page injects an ``API_KEY`` runtime global, and the
page-backed collector sends it as the ``apiKey`` query parameter. Owner decision
OD15 (2026-10-06) accepts that free access but forbids persisting the token in
logs, tapes, error rows, status JSON, commits or anything pushed.

Every WU fetch path routes text through :func:`redact_wu_secrets` and every
exception it lets escape through :func:`sanitize_exception`, so ``str(exc)`` and
``traceback.format_exc()`` downstream are already clean. The helpers only rewrite
diagnostic text; they never change what is fetched or parsed.
"""

from __future__ import annotations

import logging
import re

REDACTED = "<redacted>"

# A key name (apiKey, API_KEY, api_key, apikey), an optional closing quote in any
# of the encodings a page, JSON string or URL can carry, a separator, an optional
# opening quote, then the value. The value stops before quotes, separators and
# ``<`` so an already redacted value is never matched again (idempotent).
_QUOTE = r"(?:\\?[\"']|&quot;|&q;|&#34;|&#x22;)"
_SECRET_RE = re.compile(
    r"(api_?key" + _QUOTE + r"?\s*(?:=|:|%3D)\s*" + _QUOTE + r"?)"
    r"([^&\s\"'<>\\),;}\]]+)",
    re.IGNORECASE,
)

HTTP_DEBUG_LOGGERS = ("urllib3", "urllib3.connectionpool", "requests")

_URL_ATTRS = ("url",)
_MAX_EXCEPTION_DEPTH = 16


def redact_wu_secrets(value):
    """Return ``value`` as text with every WU access-token value replaced."""
    if value is None:
        return None
    return _SECRET_RE.sub(lambda match: match.group(1) + REDACTED, str(value))


def _redact_arg(arg, seen, depth):
    if isinstance(arg, str):
        return redact_wu_secrets(arg)
    if isinstance(arg, bytes):
        return redact_wu_secrets(arg.decode("utf-8", "replace")).encode("utf-8")
    if isinstance(arg, BaseException):
        _sanitize(arg, seen, depth + 1)
        return arg
    if isinstance(arg, tuple):
        return tuple(_redact_arg(item, seen, depth) for item in arg)
    if isinstance(arg, list):
        return [_redact_arg(item, seen, depth) for item in arg]
    return arg


def _redact_url_attr(obj, name):
    try:
        value = getattr(obj, name, None)
    except Exception:  # noqa: BLE001 - a diagnostic property must not mask the original failure.
        return
    if isinstance(value, str):
        try:
            setattr(obj, name, redact_wu_secrets(value))
        except Exception:  # noqa: BLE001 - read-only attributes stay as they are.
            return


def _sanitize(exc, seen, depth):
    if exc is None or id(exc) in seen or depth > _MAX_EXCEPTION_DEPTH:
        return
    seen.add(id(exc))
    try:
        exc.args = tuple(_redact_arg(arg, seen, depth) for arg in exc.args)
    except Exception:  # noqa: BLE001 - never replace the caller's failure with ours.
        pass
    for name in _URL_ATTRS:
        _redact_url_attr(exc, name)
    for holder_name in ("request", "response"):
        holder = getattr(exc, holder_name, None)
        if holder is not None:
            _redact_url_attr(holder, "url")
    # urllib3 keeps the wrapped failure on ``reason``; requests keeps it in args.
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        _sanitize(reason, seen, depth + 1)
    _sanitize(exc.__cause__, seen, depth + 1)
    _sanitize(exc.__context__, seen, depth + 1)


def sanitize_exception(exc):
    """Redact the token from ``exc``, its chain and its request/response URLs, in place.

    Returns ``exc`` so callers can write ``raise sanitize_exception(exc)``. The
    exception type, status code and attributes the failure classifier reads are
    unchanged; only text carrying the token is rewritten.
    """
    _sanitize(exc, set(), 0)
    return exc


def pin_http_debug_loggers(level=logging.WARNING):
    """Hold urllib3/requests loggers at ``level`` or above.

    urllib3 logs the full request line, query string included, at DEBUG. Pinning
    these loggers in the WU fetch entry points keeps a root DEBUG configuration
    from writing the token. A logger already at a stricter level is left alone.
    """
    for name in HTTP_DEBUG_LOGGERS:
        logger = logging.getLogger(name)
        if logger.level < level:
            logger.setLevel(level)
