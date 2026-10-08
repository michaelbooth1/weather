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
  also sanitizes exceptions (dict, list and tuple arguments that pair a key
  name with a value of any type, other objects, ``__notes__``, filename and
  reason attributes) and log records. Every text form
  ``weather.operations.wu_token_scan`` flags is redacted here, including its
  32-hex safety net (``_HEX32_NEAR_KEY_RE``); a parity test holds the two in step.

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
# ``<`` so an already redacted value is never matched again (idempotent). The
# opening quote is possessive (``?+``, Python 3.11+): when an encoded quote such as
# ``%22`` is present it must be consumed, so a second pass cannot backtrack and
# take the quote itself as a "value".
_QUOTE = r"(?:\\?[\"']|&quot;|&q;|&#34;|&#x22;|%(?:25)?2[27]|\\u002[27])"
_SEPARATOR = r"(?:=|:|%(?:25)?3[ad]|&#61;|&#58;|&#x3[ad];|\\u003[ad])"
_SECRET_RE = re.compile(
    r"(api[_-]?key" + _QUOTE + r"?\s*" + _SEPARATOR + r"(?:\s|%20)*+" + _QUOTE + r"?+)"
    r"([^&\s\"'<>\\),;}\]]+)",
    re.IGNORECASE,
)

# A ``'apiKey', '<value>'`` pair as a tuple or list repr renders it (requests'
# list-of-tuples ``params``): the key, a closing quote, a comma, an opening quote.
_PAIR_RE = re.compile(
    r"(api[_-]?key" + _QUOTE + r"\s*,\s*b?" + _QUOTE + r")([^&\s\"'<>\\),;}\]]+)",
    re.IGNORECASE,
)
# Mirror of the scanner's ``hex32_near_apikey`` safety net: a bare 32-hex run within
# 64 characters after a key name (``apiKey is <hex>``, ``apiKey => <hex>``,
# ``'apiKey': ['<hex>']``). Only the hex run is replaced.
_HEX_START = r"(?:(?<![0-9a-f])|(?<=%[0-9a-f]{2})|(?<=%25[0-9a-f]{2})|(?<=\\u00[0-9a-f]{2}))"
_HEX32_NEAR_KEY_RE = re.compile(
    r"(api[_-]?key.{0,64}?)" + _HEX_START + r"[0-9a-f]{32}(?![0-9a-f])",
    re.IGNORECASE | re.DOTALL,
)
# Unquoted JSON/Python literals and short numbers are kept so ``{"apiKey": null}``
# stays valid JSON; a token is never one of these.
_KEPT_VALUE_RE = re.compile(r"(?:null|none|true|false|\d{1,15})", re.IGNORECASE)

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

# A mapping key or sequence element that names the token (``{"apiKey": v}``,
# ``("apiKey", v)``, ``[b"X-Api-Key", v]``): the value is replaced whole, whatever
# its type, since the value alone carries no key for the text regex to find.
_KEY_NAME_RE = re.compile(r"api[_-]?key", re.IGNORECASE)
_KEY_ELEMENT_RE = re.compile(r"[\w-]{0,32}api[_-]?key", re.IGNORECASE)

# Text attributes an exception renders or a traceback prints: requests/urllib3 URLs,
# ``OSError.filename``/``filename2``/``strerror``, ``URLError.reason`` (a str),
# ``SyntaxError.msg``/``text``.
_TEXT_ATTRS = ("url", "filename", "filename2", "strerror", "winerror", "reason", "msg", "text")
# Bounds nesting of *argument containers* only. The exception graph itself (chains,
# groups, wrapped reasons, exceptions held in arguments) is walked with a worklist
# and the ``seen`` set, with no depth cap (S2): a 40-step retry chain is redacted
# to its bottom.
_MAX_EXCEPTION_DEPTH = 16


class _Walk(set):
    """``id``s of exceptions already sanitized, plus the exceptions still to visit."""

    def __init__(self):
        super().__init__()
        self.pending = []


def _queue(seen, exc):
    pending = getattr(seen, "pending", None)
    if exc is not None and pending is not None and id(exc) not in seen:
        pending.append(exc)


def redact_wu_secrets(value):
    """Return ``value`` as text with every WU access-token value replaced."""
    if value is None:
        return None
    text = _SECRET_RE.sub(_replace_value, str(value))
    text = _PAIR_RE.sub(_replace_value, text)
    return _HEX32_NEAR_KEY_RE.sub(lambda match: match.group(1) + REDACTED, text)


def _replace_value(match):
    if _KEPT_VALUE_RE.fullmatch(match.group(2)):
        return match.group(0)
    return match.group(1) + REDACTED


def _is_key_name(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return isinstance(value, str) and bool(_KEY_ELEMENT_RE.fullmatch(value.strip()))


def _names_key(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return isinstance(value, str) and bool(_KEY_NAME_RE.search(value))


def _redacted_value(value):
    """The placeholder for a value stored under a key name; keeps ``None``/bools/short ints."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) < 10**15:
        return value
    if isinstance(value, bytes):
        return REDACTED.encode("ascii")
    return REDACTED


def _redact_sequence(items, seen, depth):
    """Redact each item; an item right after a key-name element is replaced whole."""
    out = []
    after_key = False
    for item in items:
        out.append(_redacted_value(item) if after_key else _redact_arg(item, seen, depth + 1))
        after_key = _is_key_name(item)
    return out


def _redact_arg(arg, seen, depth):
    if depth > _MAX_EXCEPTION_DEPTH:
        return _redact_opaque(arg)
    if isinstance(arg, str):
        return redact_wu_secrets(arg)
    if isinstance(arg, bytes):
        return redact_wu_secrets(arg.decode("utf-8", "replace")).encode("utf-8")
    if isinstance(arg, BaseException):
        _queue(seen, arg)
        return arg
    if isinstance(arg, tuple):
        return tuple(_redact_sequence(arg, seen, depth))
    if isinstance(arg, list):
        return _redact_sequence(arg, seen, depth)
    if isinstance(arg, dict):
        # F2/MF2: ``RuntimeError({"params": {"apiKey": token}})`` renders the dict repr;
        # a str or bytes key naming the token hides its value of any type.
        try:
            return {
                _redact_arg(key, seen, depth + 1): (
                    _redacted_value(value) if _names_key(key) else _redact_arg(value, seen, depth + 1)
                )
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
    """Keep ``arg`` unless its ``str``/``repr`` carries a token; then replace it by a fixed placeholder.

    An exception renders an argument through ``str`` (one argument) or ``repr``
    (several), so an arbitrary object holding the token would leak through either.
    MF3: the replacement never derives from the object's text, because a repr can
    carry the bare token where no key name is left for the text regex to anchor on.
    """
    try:
        texts = (str(arg), repr(arg))
    except Exception:  # noqa: BLE001 - an unrenderable object cannot leak through rendering.
        return arg
    if any(redact_wu_secrets(text) != text for text in texts):
        return f"<redacted {type(arg).__name__}>"
    return arg


def _redact_text_attr(obj, name):
    try:
        value = getattr(obj, name, None)
    except Exception:  # noqa: BLE001 - a diagnostic property must not mask the original failure.
        return
    if isinstance(value, str):
        redacted = redact_wu_secrets(value)
    elif isinstance(value, bytes):
        redacted = _redact_arg(value, set(), 0)
    else:
        return
    if redacted != value:
        try:
            setattr(obj, name, redacted)
        except Exception:  # noqa: BLE001 - read-only attributes stay as they are.
            return


def _redact_headers_in_place(headers):
    """Redact the values of an ``email.message.Message``-like headers object in place.

    Returns True when ``headers`` is such an object and no longer renders a token;
    False leaves it to the fixed placeholder (not a headers object, or a token
    survives somewhere else, such as a payload).
    """
    if not all(callable(getattr(headers, name, None)) for name in ("items", "get_all", "__delitem__", "__setitem__")):
        return False
    try:
        items = list(headers.items())
        if any(redact_wu_secrets(str(value)) != str(value) for _name, value in items):
            names = []
            for name, _value in items:
                if name.lower() not in (seen_name.lower() for seen_name in names):
                    names.append(name)
            for name in names:
                del headers[name]
            for name, value in items:
                headers[name] = redact_wu_secrets(str(value))
        return _redact_opaque(headers) is headers
    except Exception:  # noqa: BLE001 - fall back to the placeholder.
        return False


def _redact_instance_attrs(exc, seen, depth):
    """Redact text an exception keeps in its own attributes (a custom ``__str__`` may render it)."""
    try:
        items = list(vars(exc).items())
    except TypeError:
        return
    for name, value in items:
        if name.startswith("__") or name in ("request", "response"):
            continue
        if isinstance(value, BaseException):
            _queue(seen, value)
            continue
        if value is None or isinstance(value, (bool, int, float)):
            continue
        if isinstance(value, (str, bytes, dict, list, tuple)):
            redacted = _redact_arg(value, seen, depth + 1)
            changed = redacted != value
        elif _redact_headers_in_place(value):
            continue  # N5: ``HTTPError.hdrs`` stays a usable headers object
        else:
            # Any other object (a dataclass, a config) a custom ``__str__`` may render.
            redacted = _redact_opaque(value)
            changed = redacted is not value
        if changed:
            try:
                setattr(exc, name, redacted)
            except Exception:  # noqa: BLE001
                continue


def _sanitize(exc, seen=None, depth=0):
    """Sanitize ``exc`` and every exception reachable from it, iteratively (no depth cap)."""
    walk = seen if isinstance(seen, _Walk) else _Walk()
    _queue(walk, exc)
    while walk.pending:
        current = walk.pending.pop()
        if current is None or id(current) in walk:
            continue
        walk.add(id(current))
        _sanitize_one(current, walk)


def _sanitize_one(exc, seen):
    depth = 0
    try:
        exc.args = tuple(_redact_arg(arg, seen, depth) for arg in exc.args)
    except Exception:  # noqa: BLE001 - never replace the caller's failure with ours.
        pass
    for name in _TEXT_ATTRS:
        _redact_text_attr(exc, name)
    _redact_instance_attrs(exc, seen, depth)
    notes = getattr(exc, "__notes__", None)
    if isinstance(notes, list):
        try:
            exc.__notes__ = [redact_wu_secrets(note) if isinstance(note, str) else note for note in notes]
        except Exception:  # noqa: BLE001
            pass
    for holder_name in ("request", "response"):
        holder = getattr(exc, holder_name, None)
        if holder is not None:
            _redact_text_attr(holder, "url")
    for inner in getattr(exc, "exceptions", None) or ():
        if isinstance(inner, BaseException):
            _queue(seen, inner)
    # urllib3 keeps the wrapped failure on ``reason``; requests keeps it in args.
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        _queue(seen, reason)
    _queue(seen, exc.__cause__)
    _queue(seen, exc.__context__)


def sanitize_exception(exc):
    """Redact the token from ``exc``, its chain, notes, text attributes and request/response URLs, in place.

    Returns ``exc`` so callers can write ``raise sanitize_exception(exc)``. The
    exception type, status code and attributes the failure classifier reads are
    unchanged; only text carrying the token is rewritten.
    """
    _sanitize(exc)
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
