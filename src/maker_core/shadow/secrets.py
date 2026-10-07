"""Secret hygiene for the shadow gate: in-memory token set, scanner, sealed writer, logger pins, exception hook.

Implements the OD15 condition (CONSOLIDATED §5: the WU page token never goes into logs, tapes, commits or anything
pushed) as specified by D-shadow-gate-spec-v3.1 §4.8 (rules 1-6), amended by v3.2 §5.2 (patterns, scan before write,
transfer fails closed) and v3.2 §5.3 (mutants MT1-MT6). Module named by v3.1 §14 and bound by v3.1 §2.3.

What this module guarantees:
- The token set lives in memory only. It never prints its values, refuses pickling, and never appears in an
  exception message raised here. Nothing here writes a token, a matched byte range or an exception text.
- ``scan`` reports pattern ids and offsets only (v3.1 §4.8 rule 3: "never the matched bytes").
- ``SealedWriter`` scans serialised bytes **in memory before the first byte reaches disk** (v3.2 §5.2). Temporary
  files (``*.sealing-tmp``) exist only for the atomic rename and only ever hold bytes that passed the scan.
- Pinned loggers and ``http.client`` debug levels are re-checked before every fetch (v3.2 §5.3 MT6).
- Fail closed: any hit refuses the write (``REFUSED (secret_in_output)``); an unavailable exact token defers a
  transfer scan (``transfer_scan_token_unavailable``), never passes it.

Domain-neutral: no ``weather.*`` and no HTTP library import (the maker_core boundary ratchet). URL encoding is
computed here, and ``http.client`` is inspected through ``sys.modules`` only when the process has loaded it.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import traceback

from maker_core.evidence.journal import SecretGuard, canonical_bytes

REDACTED = "<redacted>"
MIN_TOKEN_CHARS = 8
PINNED_LOGGERS = ("urllib3", "urllib3.connectionpool", "requests")  # v3.1 §4.8 rule 5
TEMP_SUFFIX = ".sealing-tmp"  # v3.2 §5.2: the transfer tool never picks up temporary names
INPUT_STORE = "input_store"  # the path class whose writes also get the page-body sniff (v3.2 §5.3 MT1b)
TRANSFER_DEFERRED = "transfer_scan_token_unavailable"  # v3.2 §5.2 rule 4 addition, §10 INCOMPLETE reason

# -- structural patterns (v3.2 §5.2 "Rule 3 'the scan looks for' -- replaced") ------------------------------------
# Key name api[_-]?key, optionally quote-wrapped (", ', backslash-escaped any depth, &quot; &#34; &#x22; &q;, plus the
# single-quote entities as a fail-closed superset); optional whitespace; one separator of = : %3D %3A %253D %253A
# (hex case-insensitive); optional whitespace and quote; then a token-shaped value of 16-128 [A-Za-z0-9].
# The value-shape rule replaces the old placeholder exemption: "<redacted>" and "<page-token>" are not token-shaped.
_KEY = rb"api[_-]?key"
_QUOTE = rb"(?:\\*[\"']|&quot;|&#34;|&#x22;|&q;|&#39;|&#x27;|&apos;)"
_SEP = rb"(?:=|:|%3D|%3A|%253D|%253A)"
_VALUE = rb"[A-Za-z0-9]{16,128}"
STRUCTURAL_PATTERNS = {
    "apikey_value": re.compile(rb"(?i)" + _KEY + _QUOTE + rb"?\s*" + _SEP + rb"\s*" + _QUOTE + rb"?(" + _VALUE + rb")"),
    # WU-T's ``wu_token_scan.PATTERNS["hex32_near_apikey"]`` (3455783db), widened to api[_-]?key.
    "hex32_near_apikey": re.compile(rb"(?is)" + _KEY + rb".{0,64}?(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])"),
}
# v3.2 §5.3 MT1b: the input store refuses a page body even when no token is present (rule 1).
PAGE_BODY_PATTERN = re.compile(rb"(?i)<html|<!doctype\s+html|\bconst\s+data\b|\bAPI_KEY\b")
PAGE_BODY_ID = "page_body"

# -- enumerated error codes (v3.1 §4.8 rule 2) ---------------------------------------------------------------------
FIXED_CODES = frozenset({
    "page_timeout", "page_connection_error", "page_token_not_found", "page_parse_error",
    "api_timeout", "api_connection_error", "api_json_invalid", "api_token_rejected",
    "tls_error", "rate_limited", "unclassified:other",
})
UNCLASSIFIED_ALLOWLIST = frozenset({
    "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError", "OSError", "RuntimeError",
    "InvalidOperation", "UnicodeDecodeError", "PermissionError", "FileNotFoundError", "HTTPError", "URLError",
    "RemoteDisconnected", "IncompleteRead", "ChunkedEncodingError", "ContentDecodingError", "TooManyRedirects",
    "InvalidURL", "InvalidSchema", "MissingSchema", "ProtocolError", "MaxRetryError",
})
_HTTP_CODE = re.compile(r"(?:page|api)_http_[1-5][0-9][0-9]")
_TIMEOUT_CLASSES = frozenset({"Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout", "ReadTimeoutError",
                              "ConnectTimeoutError", "timeout"})
_CONNECTION_CLASSES = frozenset({"ConnectionError", "URLError", "ConnectionRefusedError", "ConnectionResetError",
                                 "ConnectionAbortedError", "NewConnectionError", "RemoteDisconnected",
                                 "ProtocolError", "MaxRetryError", "gaierror"})
_TLS_CLASSES = frozenset({"SSLError", "SSLCertVerificationError", "CertificateError"})


class SecretInOutput(Exception):
    """``REFUSED (secret_in_output)`` (v3.1 §4.8 rule 3; v3.1 §10). Carries the path class and pattern ids only."""

    verdict, reason = "REFUSED", "secret_in_output"

    def __init__(self, path_class, pattern_ids):
        self.path_class = _safe_label(path_class)
        self.pattern_ids = tuple(sorted(set(pattern_ids)))
        super().__init__(f"secret_in_output path_class={self.path_class} patterns={','.join(self.pattern_ids)}")


class HygieneRefusal(SystemExit):
    """The process refuses to start or to fetch (v3.1 §4.8 rule 5; v3.2 §5.3 MT4, MT6).

    A ``SystemExit`` so that a caller's broad ``except Exception`` cannot swallow it; the exit text is the
    enumerated reason only.
    """

    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"REFUSED: {reason}")


class TokenFetchFailed(Exception):
    """An exact-token page fetch failed with an enumerated ``page_*`` code (v3.2 §5.2 rule 4 addition)."""

    def __init__(self, code):
        self.code = code if is_enumerated_code(code) else "unclassified:other"
        super().__init__(self.code)


def _safe_label(value):
    text = str(value)
    return text if re.fullmatch(r"[a-z0-9_]{1,64}", text) else "other"


# -- token set -----------------------------------------------------------------------------------------------------
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-~")


def _percent(value, *, safe=b"/", plus=False):
    """``urllib.parse.quote``/``quote_plus`` equivalent (maker_core may not import ``urllib``)."""
    out = []
    for byte in value.encode("utf-8") if isinstance(value, str) else value:
        if byte in _UNRESERVED or byte in safe:
            out.append(chr(byte))
        elif plus and byte == 0x20:
            out.append("+")
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


class TokenSet:
    """Every token value scraped in this process's lifetime, held in memory only (v3.1 §4.8 "Module").

    Values are never exposed: ``repr``/``str`` give a count, iteration is not provided, and pickling refuses.
    """

    __slots__ = ("_values",)

    def __init__(self, values=()):
        self._values = set()
        for value in values:
            self.add(value)

    def add(self, value):
        if not isinstance(value, str) or not value:
            raise TypeError("token_must_be_nonempty_str")
        if len(value) < MIN_TOKEN_CHARS:
            raise ValueError("token_too_short")
        self._values.add(value)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"<TokenSet n={len(self._values)}>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("token_set_not_serialisable")

    def __getstate__(self):
        raise TypeError("token_set_not_serialisable")

    def _variants(self):
        """(variant id, compiled pattern): raw, URL-encoded (quote, quote_plus), double URL-encoded, JSON- and
        HTML-escaped (v3.2 §5.2 "Exact tokens"). Matching is case-insensitive (percent-encoding hex case)."""
        for value in sorted(self._values):
            forms = {
                "raw": value,
                "url": _percent(value),
                "url_plus": _percent(value, safe=b"", plus=True),
                "url_double": _percent(_percent(value)),
                "json": json.dumps(value)[1:-1],
                "json_ascii": json.dumps(value, ensure_ascii=True)[1:-1],
                "html": html.escape(value, quote=True),
            }
            for name, form in forms.items():
                yield name, re.compile(re.escape(form.encode("utf-8")), re.IGNORECASE)


@dataclass(frozen=True)
class Hit:
    """A scanner finding: pattern id and byte offset, never the matched bytes."""

    pattern_id: str
    offset: int


def scan(data, tokens=None, *, page_body=False):
    """All hits in ``data`` (bytes), sorted by offset then id (v3.2 §5.2). ``tokens`` is a ``TokenSet`` or None."""
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("scan_requires_bytes")
    data = bytes(data)
    hits = set()
    for pattern_id, pattern in STRUCTURAL_PATTERNS.items():
        hits.update(Hit(pattern_id, m.start()) for m in pattern.finditer(data))
    if tokens is not None:
        for variant, pattern in tokens._variants():
            hits.update(Hit("exact_token:" + variant, m.start()) for m in pattern.finditer(data))
    if page_body:
        hits.update(Hit(PAGE_BODY_ID, m.start()) for m in PAGE_BODY_PATTERN.finditer(data))
    return sorted(hits, key=lambda hit: (hit.offset, hit.pattern_id))


# -- redaction helpers -----------------------------------------------------------------------------------------------
def redact_bytes(data, tokens=None):
    """Replace every exact-token form and every structural token value with ``<redacted>``.

    Fails closed: if anything still scans afterwards, the whole value becomes ``<redacted>``.
    """
    data = bytes(data)
    marker = REDACTED.encode()
    if tokens is not None:
        for _, pattern in tokens._variants():
            data = pattern.sub(marker, data)
    for pattern in STRUCTURAL_PATTERNS.values():
        data = pattern.sub(lambda m: m.group(0)[:m.start(1) - m.start(0)] + marker, data)
    return marker if scan(data, tokens) else data


def redact_text(text, tokens=None):
    return redact_bytes(str(text).encode("utf-8", "surrogateescape"), tokens).decode("utf-8", "replace")


# -- enumerated error codes ------------------------------------------------------------------------------------------
def is_enumerated_code(code):
    if not isinstance(code, str):
        return False
    if code in FIXED_CODES or _HTTP_CODE.fullmatch(code):
        return True
    return code.startswith("unclassified:") and code[len("unclassified:"):] in UNCLASSIFIED_ALLOWLIST


def _status(exc):
    for candidate in (getattr(getattr(exc, "response", None), "status_code", None), getattr(exc, "status", None),
                      getattr(exc, "code", None)):
        if isinstance(candidate, int) and not isinstance(candidate, bool) and 100 <= candidate <= 599:
            return candidate
    return None


def error_code(exc, *, channel):
    """The one enumerated code for ``exc`` on ``channel`` ("page" or "api") (v3.1 §4.8 rule 2).

    Never ``str(exc)``, ``repr(exc)``, a traceback, a URL or a query string: only the HTTP status and class names.
    """
    if channel not in ("page", "api"):
        raise ValueError("unknown_channel")
    explicit = getattr(exc, "code", None)
    if isinstance(exc, TokenFetchFailed) and is_enumerated_code(explicit):
        return explicit
    names = {cls.__name__ for cls in type(exc).__mro__}
    status = _status(exc)
    if status == 429:
        return "rate_limited"
    if status is not None:
        if channel == "api" and status in (401, 403):
            return "api_token_rejected"
        return f"{channel}_http_{status}"
    if names & _TLS_CLASSES:
        return "tls_error"
    if names & _TIMEOUT_CLASSES:
        return f"{channel}_timeout"
    if names & _CONNECTION_CLASSES:
        return f"{channel}_connection_error"
    if channel == "api" and "JSONDecodeError" in names:
        return "api_json_invalid"
    name = type(exc).__name__
    return f"unclassified:{name}" if name in UNCLASSIFIED_ALLOWLIST else "unclassified:other"


# -- logger pins and the pre-fetch check (v3.1 §4.8 rule 5; v3.2 §5.3 MT4, MT6) -------------------------------------
def pin_http_loggers():
    for name in PINNED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def check_http_hygiene():
    """Refuse when a pinned logger would emit DEBUG/INFO, or ``http.client`` debug printing is on.

    ``HTTPConnection.debuglevel`` prints request lines with ``print``, bypassing logging (MT6), so it is checked on
    both connection classes. Called at start and before every fetch.
    """
    for name in PINNED_LOGGERS:
        if logging.getLogger(name).isEnabledFor(logging.INFO):
            raise HygieneRefusal("http_logger_verbose")
    client = sys.modules.get("http.client")
    if client is not None:
        for cls_name in ("HTTPConnection", "HTTPSConnection"):
            cls = getattr(client, cls_name, None)
            if cls is not None and getattr(cls, "debuglevel", 0):
                raise HygieneRefusal("http_debuglevel_enabled")


def enforce_http_logger_pins():
    """Process start: pin, then verify. A process whose pins do not hold refuses to start (MT4)."""
    pin_http_loggers()
    check_http_hygiene()


def guarded_fetch(fetch, *args, **kwargs):
    """Run ``fetch`` only after the hygiene check passes; the check runs before **every** fetch (MT6)."""
    check_http_hygiene()
    return fetch(*args, **kwargs)


# -- exception hooks (v3.1 §4.8 rule 5; v3.2 §5.3 MT5) ---------------------------------------------------------------
def redacted_exception_report(exc_type, exc, tb, tokens=None, *, channel="api"):
    """Class name, enumerated code and frames (file:line) only: no message, no locals, no URL."""
    code = error_code(exc, channel=channel) if isinstance(exc, BaseException) else "unclassified:other"
    lines = [f"Uncaught {getattr(exc_type, '__name__', 'Exception')} code={code}"]
    for frame in traceback.extract_tb(tb):
        lines.append(f"  at {redact_text(frame.filename, tokens)}:{frame.lineno}")
    report = "\n".join(lines) + "\n"
    return report if not scan(report.encode("utf-8", "surrogateescape"), tokens) else "Uncaught exception\n"


def install_exception_hooks(tokens=None, *, stream=None):
    """Replace ``sys.excepthook`` and ``threading.excepthook``; returns the previous pair for ``restore``."""
    previous = (sys.excepthook, threading.excepthook)

    def hook(exc_type, exc, tb):
        target = stream if stream is not None else sys.stderr
        target.write(redacted_exception_report(exc_type, exc, tb, tokens))
        target.flush()

    def thread_hook(args):
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook, threading.excepthook = hook, thread_hook
    return previous


def restore_exception_hooks(previous):
    sys.excepthook, threading.excepthook = previous


# -- the sealed writer (v3.1 §4.8 rule 3, replaced by v3.2 §5.2 "scan before write") ---------------------------------
class SealedWriter:
    """Every persisted output passes here; bytes are scanned in memory before the first byte reaches disk.

    On a hit nothing is written and ``SecretInOutput`` names the path class and pattern ids. The alert and the
    ``REFUSED (secret_in_output)`` day verdict are the caller's (v3.1 §4.8 rule 3; v3.1 §10).
    """

    def __init__(self, tokens=None):
        self.tokens = tokens
        self.outputs_scanned = 0  # receipt field secrets.outputs_scanned (v3.1 §13)

    def check(self, data, path_class):
        hits = scan(data, self.tokens, page_body=path_class == INPUT_STORE)
        self.outputs_scanned += 1
        if hits:
            raise SecretInOutput(path_class, [hit.pattern_id for hit in hits])

    def write_new(self, path, data, *, path_class):
        """Create-only: scan, write a temporary sibling from clean bytes, fsync, then rename into place."""
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("sealed_writer_requires_bytes")
        data = bytes(data)
        self.check(data, path_class)
        path = Path(path)
        if path.exists():
            raise FileExistsError("sealed_target_exists")
        temp = path.with_name(path.name + TEMP_SUFFIX)
        path.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return hashlib.sha256(data).hexdigest()

    def append(self, path, record, *, path_class):
        """Append one record (one JSON line): the record is scanned before it is appended."""
        record = bytes(record)
        self.check(record, path_class)
        with Path(path).open("ab") as handle:
            handle.write(record)
            handle.flush()
            os.fsync(handle.fileno())

    def seal_check(self, path, *, path_class):
        """The whole appended file is scanned again at seal; returns its SHA-256."""
        data = Path(path).read_bytes()
        self.check(data, path_class)
        return hashlib.sha256(data).hexdigest()


class ScanningGuard(SecretGuard):
    """A ``Journal`` guard that scans each canonical row in memory before the journal appends it."""

    def __init__(self, writer, path_class):
        super().__init__()
        self.writer, self.path_class = writer, path_class

    def clean(self, value):
        value = super().clean(value)
        self.writer.check(canonical_bytes(value), self.path_class)
        return value


# -- transfer scan at one end (v3.1 §4.8 rule 4; v3.2 §5.2 "Rule 4 addition") ----------------------------------------
@dataclass(frozen=True)
class PackageScan:
    """One end's verdict on a package: ``clean``, ``refused`` (any hit) or ``deferred`` (no exact token)."""

    end: str
    status: str
    files_scanned: int
    hits: tuple = ()
    failure_code: str | None = None
    reason: str | None = None


def scan_package(files: Mapping[str, bytes], *, end: str, fetch_exact_token: Callable[[], str]) -> PackageScan:
    """Scan every file with the structural patterns and with one freshly fetched exact token, held in memory only.

    Each end runs this independently (MT3). The structural scan always runs. A failed token fetch fails closed:
    a structural hit still refuses; otherwise the package is ``deferred`` with ``transfer_scan_token_unavailable``
    and the enumerated failure code: never sent or read without the exact-token scan, never refused for it.
    """
    if end not in ("send", "receive"):
        raise ValueError("unknown_transfer_end")
    tokens, failure = None, None
    try:
        token = fetch_exact_token()
        tokens = TokenSet([token])
        del token
    except TokenFetchFailed as exc:
        failure = exc.code
    except Exception as exc:  # enumerated code only; the exception text is never kept
        failure = error_code(exc, channel="page")
    hits = tuple(sorted({(_safe_name(name), hit.pattern_id) for name, data in sorted(files.items())
                         for hit in scan(data, tokens)}))
    if hits:
        return PackageScan(end, "refused", len(files), hits, failure, "secret_in_output")
    if tokens is None:
        return PackageScan(end, "deferred", len(files), (), failure, TRANSFER_DEFERRED)
    return PackageScan(end, "clean", len(files))


def _safe_name(name):
    return redact_text(name)


__all__ = ["FIXED_CODES", "HygieneRefusal", "INPUT_STORE", "PAGE_BODY_ID", "PINNED_LOGGERS", "PackageScan",
           "REDACTED", "STRUCTURAL_PATTERNS", "ScanningGuard", "SealedWriter", "SecretInOutput", "TRANSFER_DEFERRED",
           "TokenFetchFailed", "TokenSet", "check_http_hygiene", "enforce_http_logger_pins", "error_code",
           "guarded_fetch", "install_exception_hooks", "is_enumerated_code", "pin_http_loggers", "redact_bytes",
           "redact_text", "redacted_exception_report", "restore_exception_hooks", "scan", "scan_package"]
