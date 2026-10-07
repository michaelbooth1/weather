"""Redact the public WU page access token before anything is stored or logged.

The public WU history page injects an ``API_KEY`` runtime global, and the
page-backed collector sends it as the ``apiKey`` query parameter. Owner decision
OD15 (2026-10-06) accepts that free access but forbids persisting the token in
logs, tapes, error rows, status JSON, commits or anything pushed.

Every WU fetch path routes text through :func:`redact_wu_secrets` and every
exception it lets escape through :func:`sanitize_exception`, so ``str(exc)`` and
``traceback.format_exc()`` downstream are already clean. The helpers only rewrite
diagnostic text; they never change what is fetched or parsed.

Logging: :func:`pin_http_debug_loggers` keeps urllib3's DEBUG request line out,
but urllib3 2.x also logs the full URL at WARNING ("Failed to parse headers
(url=...)", "Retrying (...) after connection broken ... : <url>").
:func:`install_wu_log_redaction` attaches :class:`WuSecretRedactingFilter` to
every urllib3/requests logger that emits records, so those lines are rewritten
before any handler sees them. Callers opt in; installing is idempotent.

Two redaction helpers exist on purpose (finding F7, 2026-10-07):

* ``weather.collection.redaction.redact_sensitive_url_parts`` is the generic
  status-text redactor used by ``snapshot_store``, ``collection_health`` and the
  market-making preflight. It rewrites any secret-like *query parameter*
  (``?key=``, ``&token=``, ``api_key=``, ``password=`` ...) and is imported by
  capture loops, so its behaviour is frozen outside the quiet window.
* This module is WU-specific. It covers the forms the WU page token takes
  beyond a query parameter (JSON ``"apiKey":"..."``, dict reprs, the page
  ``API_KEY`` global, HTML/Angular escapes, once- and twice-URL-encoded and
  JSON ``\u0022`` quotes and separators, ``X-Api-Key`` header spellings) and
  also sanitizes exceptions (including dict and object arguments) and log
  records. Every form ``weather.operations.wu_token_scan`` flags is redacted
  here (a test holds the two in step).

Neither delegates to the other: ``weather.sources`` may not import
``weather.collection``, and changing the collection helper would roll the
capture loops. Converging them is a quiet-window follow-up.
"""

from __future__ import annotations

import logging
import re

REDACTED = "<redacted>"

# A key name (apiKey, API_KEY, api_key, apikey, X-Api-Key), an optional closing
# quote in any of the encodings a page, JSON string or URL can carry (raw,
# backslash-escaped, HTML/Angular entities, ``%22``/``%27`` once or twice
# URL-encoded, JSON ``"``), a separator in the same encodings, an optional
# opening quote, then the value. The value stops before quotes, separators and
# ``<`` so an already redacted value is never matched again (idempotent).
_QUOTE = r"(?:\\?[\"']|&quot;|&q;|&#34;|&#x22;|%(?:25)?2[27]|\\u002[27])"
_SEPARATOR = r"(?:=|:|%(?:25)?3[ad]|&#61;|&#58;|&#x3[ad];|\\u003[ad])"
_SECRET_RE = re.compile(
    r"(api[_-]?key" + _QUOTE + r"?\s*" + _SEPARATOR + r"\s*(?:%20)*" + _QUOTE + r"?)"
    r"([^&\s\"'<>\\),;}\]]+)",
    re.IGNORECASE,
)

HTTP_DEBUG_LOGGERS = ("urllib3", "urllib3.connectionpool", "requests")
# Every logger urllib3 2.x and requests create with ``getLogger(__name__)``. A
# logger-level filter only sees records logged on that exact logger (not records
# propagated from children), so each emitting module is listed. A test compares
# this tuple with the installed urllib3.
HTTP_LOG_REDACTION_LOGGERS = (
    "urllib3",
    "urllib3.connection",
    "urllib3.connectionpool",
    "urllib3.poolmanager",
    "urllib3.response",
    "urllib3.util.retry",
    "urllib3.http2.connection",
    "urllib3.contrib.pyopenssl",
    "urllib3.contrib.emscripten.response",
    "requests",
)

_URL_ATTRS = ("url",)
_MAX_EXCEPTION_DEPTH = 16


def redact_wu_secrets(value):
    """Return ``value`` as text with every WU access-token value replaced."""
    if value is None:
        return None
    return _SECRET_RE.sub(lambda match: match.group(1) + REDACTED, str(value))


def _redact_arg(arg, seen, depth):
    if depth > _MAX_EXCEPTION_DEPTH:
        return _redact_opaque(arg)
    if isinstance(arg, str):
        return redact_wu_secrets(arg)
    if isinstance(arg, bytes):
        return redact_wu_secrets(arg.decode("utf-8", "replace")).encode("utf-8")
    if isinstance(arg, BaseException):
        _sanitize(arg, seen, depth + 1)
        return arg
    if isinstance(arg, tuple):
        return tuple(_redact_arg(item, seen, depth + 1) for item in arg)
    if isinstance(arg, list):
        return [_redact_arg(item, seen, depth + 1) for item in arg]
    if isinstance(arg, dict):
        # F2: ``RuntimeError({"params": {"apiKey": token}})`` renders the dict repr.
        try:
            return {
                _redact_arg(key, seen, depth + 1): _redact_arg(value, seen, depth + 1)
                for key, value in arg.items()
            }
        except Exception:  # noqa: BLE001 - an unhashable redacted key falls back to text.
            return _redact_opaque(arg)
    if isinstance(arg, (set, frozenset)):
        try:
            return type(arg)(_redact_arg(item, seen, depth + 1) for item in arg)
        except Exception:  # noqa: BLE001
            return _redact_opaque(arg)
    if arg is None or isinstance(arg, (bool, int, float)):
        return arg
    return _redact_opaque(arg)


def _redact_opaque(arg):
    """Keep ``arg`` unless its ``str``/``repr`` carries a token; then replace it by redacted text.

    An exception renders an argument through ``str`` (one argument) or ``repr``
    (several), so an arbitrary object holding the token would leak through either.
    """
    try:
        texts = {str(arg), repr(arg)}
    except Exception:  # noqa: BLE001 - an unrenderable object cannot leak through rendering.
        return arg
    for text in texts:
        if redact_wu_secrets(text) != text:
            return redact_wu_secrets(repr(arg))
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


class WuSecretRedactingFilter(logging.Filter):
    """Rewrite a log record so no WU access-token value reaches a handler.

    The fully formatted message is redacted and stored back with its args
    cleared, and an attached exception is sanitized in place. The record is
    never dropped: the filter only changes text.
    """

    def filter(self, record):  # noqa: A003 - logging.Filter API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed record is redacted as raw text.
            message = str(record.msg)
        redacted = redact_wu_secrets(message)
        if redacted != message or record.args:
            record.msg = redacted
            record.args = None
        if record.exc_info and isinstance(record.exc_info[1], BaseException):
            sanitize_exception(record.exc_info[1])
            # Belt and braces for argument types sanitize_exception cannot rewrite:
            # render the traceback now and store the redacted text, which handlers
            # reuse instead of formatting the exception again.
            try:
                record.exc_text = redact_wu_secrets(logging.Formatter().formatException(record.exc_info))
            except Exception:  # noqa: BLE001 - fall back to the handler's own rendering.
                record.exc_text = None
        if record.exc_text:
            record.exc_text = redact_wu_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_wu_secrets(record.stack_info)
        return True


def install_wu_log_redaction(logger_names=HTTP_LOG_REDACTION_LOGGERS, handlers=()):
    """Attach :class:`WuSecretRedactingFilter` to ``logger_names`` and ``handlers``.

    Idempotent: a logger or handler that already carries the filter is left
    alone. ``handlers`` lets an entry point that configures its own handlers
    (for example a root ``StreamHandler``) redact records from any logger.
    Returns the number of filters added.
    """
    added = 0
    targets = [logging.getLogger(name) for name in logger_names] + list(handlers)
    for target in targets:
        if any(isinstance(existing, WuSecretRedactingFilter) for existing in target.filters):
            continue
        target.addFilter(WuSecretRedactingFilter())
        added += 1
    return added
