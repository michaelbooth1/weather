from __future__ import annotations

import codecs
import csv
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterable

import requests


SleepFn = Callable[[float], None]
CSV_DIAGNOSTIC_COLUMNS = {
    "_csv_encoding_status",
    "_csv_source_encoding",
    "_csv_source_path",
    "_csv_utf8_decode_error",
}
LEGACY_CSV_ENCODINGS = ("cp1252", "latin-1")
MAX_RETRY_DELAY_SECONDS = 10.0
DEFAULT_SIDECAR_ROTATE_BYTES = 64 * 1024 * 1024
DEFAULT_SIDECAR_ROTATE_ATTEMPTS = 6
DEFAULT_SIDECAR_ROTATE_RETRY_SECONDS = 0.1
ROTATE_BEFORE_APPEND = "before_append"
ROTATE_BEFORE_LAUNCH = "before_launch"


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def http_error_is_retryable(exc):
    """Return whether an idempotent request failed transiently."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        if response is None:
            return False
        return response.status_code == 429 or response.status_code >= 500
    return False


def http_retry_after_response_seconds(response):
    """Parse a response Retry-After header as a non-negative delay."""
    if response is None:
        return None
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value in (None, ""):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(
        0.0,
        (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
    )


def http_retry_after_seconds(exc):
    """Parse Retry-After from an HTTP exception's response."""
    return http_retry_after_response_seconds(getattr(exc, "response", None))


def http_retry_delay_seconds(
    exc,
    attempt,
    base_delay=0.5,
    max_delay=MAX_RETRY_DELAY_SECONDS,
):
    retry_after = http_retry_after_seconds(exc)
    if retry_after is not None:
        return min(float(max_delay), retry_after)
    return min(float(max_delay), base_delay * (2**attempt))


def request_with_retries(
    fn,
    attempts=3,
    base_delay=0.5,
    sleep=time.sleep,
    max_delay=MAX_RETRY_DELAY_SECONDS,
):
    """Run an idempotent request and retry only transient failures."""
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            if not http_error_is_retryable(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                sleep(
                    http_retry_delay_seconds(
                        exc,
                        attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                    )
                )
    raise last


def read_json(path: str | Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


_PRETTY_TOP_LEVEL_FIELD = re.compile(
    rb'^  (?P<key>"(?:\\.|[^"\\])*")\s*:\s*(?P<value>.*?)(?:\r?\n)?$'
)
_PRETTY_SECOND_LEVEL_FIELD = re.compile(
    rb'^    (?P<key>"(?:\\.|[^"\\])*")\s*:\s*(?P<value>.*?)(?:\r?\n)?$'
)


def read_pretty_json_top_level_values(
    path: str | Path,
    fields: Iterable[str],
    *,
    max_line_bytes: int = 64 * 1024,
    max_value_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    """Read selected root values from canonical pretty JSON with bounded RAM.

    Unselected arrays and objects are scanned a physical line at a time and
    never decoded. Selected values are capped independently; an oversized or
    malformed selected value is omitted instead of triggering a whole-file
    fallback. Repository JSON writers use two-space indentation, which makes
    root fields distinguishable from nested fields without building a JSON
    object for the rest of the artifact.
    """

    wanted = {str(field) for field in fields}
    if not wanted:
        return {}
    if max_line_bytes <= 0 or max_value_bytes <= 0:
        raise ValueError("pretty JSON read limits must be positive")
    result: dict[str, Any] = {}
    capture_key: str | None = None
    capture = bytearray()
    capture_valid = True

    def finish_capture() -> None:
        nonlocal capture_key, capture, capture_valid
        if capture_key is not None and capture_valid:
            raw = bytes(capture).strip()
            if raw.endswith(b","):
                raw = raw[:-1].rstrip()
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            else:
                result[capture_key] = value
        capture_key = None
        capture = bytearray()
        capture_valid = True

    try:
        with Path(path).open("rb") as handle:
            while True:
                line = handle.readline(max_line_bytes + 1)
                if not line:
                    finish_capture()
                    break
                oversized = len(line) > max_line_bytes
                if oversized:
                    fragment = line
                    while fragment and not fragment.endswith((b"\n", b"\r")):
                        fragment = handle.readline(max_line_bytes + 1)
                    if capture_key is not None:
                        capture_valid = False
                    continue
                if line.startswith(b"}"):
                    finish_capture()
                    continue
                match = _PRETTY_TOP_LEVEL_FIELD.fullmatch(line)
                if match:
                    finish_capture()
                    try:
                        key = json.loads(match.group("key").decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if key in wanted:
                        capture_key = key
                        raw_value = match.group("value")
                        if len(raw_value) > max_value_bytes:
                            capture_valid = False
                        else:
                            capture.extend(raw_value)
                    continue
                if capture_key is not None:
                    if len(capture) + len(line) > max_value_bytes:
                        capture_valid = False
                    elif capture_valid:
                        capture.extend(line)
    except OSError:
        return {}
    return result


def read_pretty_json_object_values(
    path: str | Path,
    object_field: str,
    fields: Iterable[str],
    *,
    max_line_bytes: int = 64 * 1024,
    max_value_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    """Read selected direct children of one canonical pretty-JSON object.

    This complements :func:`read_pretty_json_top_level_values` for artifacts
    where a bounded summary and a growing row array share a top-level object.
    Unselected children are scanned line by line and never decoded.
    """

    wanted = {str(field) for field in fields}
    if not wanted:
        return {}
    if max_line_bytes <= 0 or max_value_bytes <= 0:
        raise ValueError("pretty JSON read limits must be positive")
    result: dict[str, Any] = {}
    inside_object = False
    object_closed = False
    capture_key: str | None = None
    capture = bytearray()
    capture_valid = True

    def finish_capture() -> None:
        nonlocal capture_key, capture, capture_valid
        if capture_key is not None and capture_valid:
            raw = bytes(capture).strip()
            if raw.endswith(b","):
                raw = raw[:-1].rstrip()
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            else:
                result[capture_key] = value
        capture_key = None
        capture = bytearray()
        capture_valid = True

    try:
        with Path(path).open("rb") as handle:
            while True:
                line = handle.readline(max_line_bytes + 1)
                if not line:
                    finish_capture()
                    break
                oversized = len(line) > max_line_bytes
                if oversized:
                    fragment = line
                    while fragment and not fragment.endswith((b"\n", b"\r")):
                        fragment = handle.readline(max_line_bytes + 1)
                    if capture_key is not None:
                        capture_valid = False
                    continue
                if not inside_object:
                    match = _PRETTY_TOP_LEVEL_FIELD.fullmatch(line)
                    if not match:
                        continue
                    try:
                        key = json.loads(match.group("key").decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    raw_value = match.group("value").lstrip()
                    if key == str(object_field) and raw_value.startswith(b"{"):
                        inside_object = True
                    continue
                if line.startswith(b"  }"):
                    finish_capture()
                    object_closed = True
                    break
                match = _PRETTY_SECOND_LEVEL_FIELD.fullmatch(line)
                if match:
                    finish_capture()
                    try:
                        key = json.loads(match.group("key").decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if key in wanted:
                        capture_key = key
                        raw_value = match.group("value")
                        if len(raw_value) > max_value_bytes:
                            capture_valid = False
                        else:
                            capture.extend(raw_value)
                    continue
                if capture_key is not None:
                    if len(capture) + len(line) > max_value_bytes:
                        capture_valid = False
                    elif capture_valid:
                        capture.extend(line)
    except OSError:
        return {}
    return result if object_closed else {}


def pretty_json_root_is_closed(
    path: str | Path,
    *,
    max_tail_bytes: int = 4096,
) -> bool:
    """Return whether canonical pretty JSON ends with a column-zero root close."""

    if max_tail_bytes <= 0:
        raise ValueError("max_tail_bytes must be positive")
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_tail_bytes))
            lines = handle.read().splitlines()
    except OSError:
        return False
    for line in reversed(lines):
        if line.strip():
            return line.rstrip() == b"}"
    return False


def write_json_atomic(
    path: str | Path,
    payload: Any,
    *,
    retries: int = 20,
    retry_sleep_seconds: float = 0.05,
    sleep_fn: SleepFn = time.sleep,
    trailing_newline: bool = False,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if trailing_newline:
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(retries):
        try:
            tmp.replace(path)
            return path
        except PermissionError:
            if attempt == retries - 1:
                raise
            sleep_fn(retry_sleep_seconds)
    return path


def _json_key_text(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    if key is True:
        return "true"
    if key is False:
        return "false"
    if isinstance(key, (int, float)):
        return str(key)
    raise TypeError(
        "keys must be str, int, float, bool or None, "
        f"not {type(key).__name__}"
    )


def _write_json_streaming_value(handle, value: Any, *, level: int) -> None:
    """Serialize JSON without materializing disk-backed row collections."""

    indent = "  " * level
    child_indent = "  " * (level + 1)
    if isinstance(value, dict):
        if not value:
            handle.write("{}")
            return
        handle.write("{\n")
        for index, key in enumerate(sorted(value)):
            if index:
                handle.write(",\n")
            handle.write(child_indent)
            handle.write(json.dumps(_json_key_text(key)))
            handle.write(": ")
            _write_json_streaming_value(handle, value[key], level=level + 1)
        handle.write(f"\n{indent}}}")
        return
    is_spilled_array = bool(
        getattr(value, "is_spilled_rows", False)
        or getattr(value, "is_spilled_queue_rows", False)
    )
    if isinstance(value, (list, tuple)) or is_spilled_array:
        iterator = iter(value)
        try:
            first = next(iterator)
        except StopIteration:
            handle.write("[]")
            return
        handle.write("[\n")
        handle.write(child_indent)
        _write_json_streaming_value(handle, first, level=level + 1)
        for item in iterator:
            handle.write(",\n")
            handle.write(child_indent)
            _write_json_streaming_value(handle, item, level=level + 1)
        handle.write(f"\n{indent}]")
        return
    encoder = json.JSONEncoder(default=str)
    for chunk in encoder.iterencode(value):
        handle.write(chunk)


def write_json_streaming_atomic(
    path: str | Path,
    payload: Any,
    *,
    retries: int = 20,
    retry_sleep_seconds: float = 0.05,
    sleep_fn: SleepFn = time.sleep,
    trailing_newline: bool = False,
    newline: str | None = "\n",
) -> Path:
    """Atomically stream JSON, including SQLite-backed row-array views."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline=newline) as handle:
            _write_json_streaming_value(handle, payload, level=0)
            if trailing_newline:
                handle.write("\n")
        for attempt in range(retries):
            try:
                tmp.replace(path)
                return path
            except PermissionError:
                if attempt == retries - 1:
                    raise
                sleep_fn(retry_sleep_seconds)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def write_text_atomic(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write a text artifact through a same-directory atomic replacement."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def rotate_sidecar(
    path: str | Path,
    *,
    max_bytes: int | None = None,
    now: datetime | None = None,
    max_attempts: int = DEFAULT_SIDECAR_ROTATE_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_SIDECAR_ROTATE_RETRY_SECONDS,
    sleep_fn: SleepFn = time.sleep,
) -> Path | None:
    """Move an oversized sidecar to a timestamped sibling without deletion."""

    path = Path(path)
    max_bytes = DEFAULT_SIDECAR_ROTATE_BYTES if max_bytes is None else int(max_bytes)
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    max_attempts = int(max_attempts)
    retry_delay_seconds = float(retry_delay_seconds)
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be non-negative")
    try:
        if path.stat().st_size < max_bytes:
            return None
    except FileNotFoundError:
        return None

    rotated_at = now or datetime.now(timezone.utc)
    if rotated_at.tzinfo is None:
        rotated_at = rotated_at.replace(tzinfo=timezone.utc)
    stamp = rotated_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for collision_index in range(1000):
        collision = "" if collision_index == 0 else f".{collision_index}"
        rotated = path.with_name(f"{path.stem}.{stamp}{collision}{path.suffix}")
        if rotated.exists():
            continue
        for attempt in range(max_attempts):
            try:
                path.rename(rotated)
            except FileNotFoundError:
                # Another writer won the rotation race.
                return None
            except FileExistsError:
                # Windows rename is non-overwriting; preserve the sibling and
                # reserve a new collision suffix.
                break
            except PermissionError:
                # Antivirus/indexing can hold a large sidecar briefly. The
                # incident this policy closes was exactly such a transient
                # Windows reopen denial, so a one-shot rename merely moves the
                # same failure to a different syscall.
                if attempt + 1 >= max_attempts:
                    raise
                delay = min(
                    MAX_RETRY_DELAY_SECONDS,
                    retry_delay_seconds * (2 ** attempt),
                )
                sleep_fn(delay)
                continue
            return rotated
    raise RuntimeError(f"could not reserve a rotated sibling for {path}")


def rotated_sidecar_paths(path: str | Path) -> list[Path]:
    """Return timestamped siblings created by :func:`rotate_sidecar`."""

    path = Path(path)
    pattern = re.compile(
        rf"^{re.escape(path.stem)}\.\d{{8}}T\d+Z(?:\.\d+)?{re.escape(path.suffix)}$"
    )
    try:
        siblings = path.parent.iterdir()
    except FileNotFoundError:
        return []
    return sorted(
        candidate
        for candidate in siblings
        if candidate.is_file() and pattern.fullmatch(candidate.name)
    )


def rotate_sidecar_policy(
    policy: dict[str | Path, str],
    *,
    triggers: Iterable[str] | None = None,
    max_bytes: int | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Rotate the selected paths in a declarative managed-loop policy."""

    selected = set(triggers) if triggers is not None else None
    rotations: dict[str, str] = {}
    for raw_path, trigger in policy.items():
        if selected is not None and trigger not in selected:
            continue
        rotated = rotate_sidecar(raw_path, max_bytes=max_bytes, now=now)
        if rotated is not None:
            rotations[str(Path(raw_path))] = str(rotated)
    return rotations


def append_jsonl(path: str | Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if isinstance(payload, list):
            for row in payload:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        else:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
    return path


def append_rotating_jsonl(
    path: str | Path,
    payload: Any,
    *,
    max_bytes: int | None = None,
    now: datetime | None = None,
) -> Path:
    """Rotate an oversized append-opened JSONL sidecar before reopening it."""

    rotate_sidecar(path, max_bytes=max_bytes, now=now)
    return append_jsonl(path, payload)


def writer_lock_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(f".{path.name}.writer.lock")


def _writer_owner_payload(status_path: str | Path, owner: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "pid": os.getpid(),
        "status_path": str(Path(status_path)),
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(owner or {})
    return payload


def file_lock_is_stale(path: str | Path, *, max_age_seconds: float = 120.0) -> bool:
    path = Path(path)
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > max_age_seconds


def acquire_writer_lock(
    status_path: str | Path,
    *,
    owner: dict[str, Any] | None = None,
    attempts: int = 1,
    stale_after_seconds: float = 120.0,
    sleep_seconds: float = 0.1,
    sleep_fn: SleepFn = time.sleep,
) -> dict[str, Any] | None:
    lock_path = writer_lock_path(status_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = _writer_owner_payload(status_path, owner)
            os.write(handle, json.dumps(payload, sort_keys=True).encode("utf-8"))
            return {"handle": handle, "path": str(lock_path), "owner": payload}
        except FileExistsError:
            if file_lock_is_stale(lock_path, max_age_seconds=stale_after_seconds):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if attempt != attempts - 1:
                sleep_fn(sleep_seconds)
    return None


def release_writer_lock(lock: dict[str, Any] | None) -> None:
    if not lock:
        return
    handle = lock.get("handle")
    if handle is not None:
        try:
            os.close(handle)
        except OSError:
            pass
    try:
        Path(lock["path"]).unlink()
    except (FileNotFoundError, KeyError):
        pass


def read_jsonl(path: str | Path, *, skip_invalid: bool = True) -> list[Any]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                if not skip_invalid:
                    raise
    return rows


def _decode_error_payload(exc: UnicodeDecodeError) -> dict[str, Any]:
    return {
        "encoding": exc.encoding,
        "reason": exc.reason,
        "start": exc.start,
        "end": exc.end,
        "object_length": len(exc.object or b""),
    }


def _read_csv_with_encoding(path: Path, encoding: str) -> tuple[list[dict], list[str]]:
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def attach_csv_encoding_provenance(rows: list[dict], diagnostics: dict[str, Any]) -> list[dict]:
    status = diagnostics.get("status") or "unknown"
    if status == "ok":
        return rows
    out = []
    error = diagnostics.get("utf8_decode_error") or diagnostics.get("error") or ""
    for row in rows:
        enriched = dict(row)
        enriched["_csv_encoding_status"] = status
        enriched["_csv_source_encoding"] = diagnostics.get("encoding") or ""
        enriched["_csv_source_path"] = diagnostics.get("path") or ""
        enriched["_csv_utf8_decode_error"] = json.dumps(error, sort_keys=True, default=str) if error else ""
        out.append(enriched)
    return out


def read_csv_rows_with_diagnostics(
    path: str | Path,
    *,
    fallback_encodings: Iterable[str] = LEGACY_CSV_ENCODINGS,
    attach_diagnostics: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    path = Path(path)
    diagnostics: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "status": "missing",
        "encoding": None,
        "row_count": 0,
        "fieldnames": [],
        "legacy_encoding": False,
        "quarantined_row_count": 0,
        "utf8_decode_error": None,
        "error": None,
    }
    if not path.exists():
        return [], diagnostics
    try:
        rows, fieldnames = _read_csv_with_encoding(path, "utf-8-sig")
        diagnostics.update({
            "status": "ok",
            "encoding": "utf-8-sig",
            "row_count": len(rows),
            "fieldnames": fieldnames,
        })
        return rows, diagnostics
    except UnicodeDecodeError as exc:
        diagnostics["utf8_decode_error"] = _decode_error_payload(exc)
    except (OSError, csv.Error) as exc:
        diagnostics.update({"status": "read_error", "error": f"{type(exc).__name__}: {exc}"})
        return [], diagnostics

    for encoding in fallback_encodings:
        try:
            rows, fieldnames = _read_csv_with_encoding(path, encoding)
        except (UnicodeDecodeError, OSError, csv.Error) as exc:
            diagnostics["error"] = f"{type(exc).__name__}: {exc}"
            continue
        diagnostics.update({
            "status": "legacy_encoding",
            "encoding": encoding,
            "row_count": len(rows),
            "fieldnames": fieldnames,
            "legacy_encoding": True,
            "quarantined_row_count": len(rows),
            "error": None,
        })
        if attach_diagnostics:
            rows = attach_csv_encoding_provenance(rows, diagnostics)
        return rows, diagnostics

    diagnostics["status"] = "decode_error"
    return [], diagnostics


def read_csv_rows(path: str | Path, *, attach_diagnostics: bool = False) -> list[dict]:
    rows, _diagnostics = read_csv_rows_with_diagnostics(path, attach_diagnostics=attach_diagnostics)
    return rows


def _validate_utf8_sig_streaming(path: Path, chunk_bytes: int = 1 << 20) -> None:
    """Raise UnicodeDecodeError if the file is not utf-8-sig, retaining nothing."""

    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    with path.open("rb") as raw:
        while True:
            chunk = raw.read(chunk_bytes)
            if not chunk:
                decoder.decode(b"", final=True)
                return
            decoder.decode(chunk)


def iter_csv_rows(
    path: str | Path,
    *,
    fallback_encodings: Iterable[str] = LEGACY_CSV_ENCODINGS,
    attach_diagnostics: bool = False,
) -> Iterable[dict]:
    """Stream CSV rows one dict at a time with bounded memory.

    ``read_csv_rows`` materializes the whole file as a list of dicts, which
    inflates large tapes by an order of magnitude (a 160 MB order tape
    exceeded a 2 GiB private-memory cap on 2026-07-16). This variant first
    validates utf-8-sig decodability in a retention-free pre-pass, then
    yields rows lazily. Files that fail utf-8 decoding fall back to the
    materializing legacy-encoding reader so quarantine/provenance semantics
    stay identical to ``read_csv_rows`` (legacy files are historical and
    small). A malformed row mid-stream raises csv.Error instead of silently
    dropping the tape: partially consumed streams must fail visibly because
    the caller may have already aggregated earlier rows.
    """

    path = Path(path)
    if not path.exists():
        return
    try:
        _validate_utf8_sig_streaming(path)
    except UnicodeDecodeError:
        rows, _diagnostics = read_csv_rows_with_diagnostics(
            path,
            fallback_encodings=fallback_encodings,
            attach_diagnostics=attach_diagnostics,
        )
        yield from rows
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            yield dict(row)


def _bounded_tail_diagnostics(path: Path, max_bytes: int) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "status": "missing",
        "bounded": True,
        "file_size_bytes": 0,
        "captured_mtime_ns": None,
        "max_scan_bytes": max(1, int(max_bytes)),
        "scanned_bytes": 0,
        "read_bytes": 0,
        "header_bytes": 0,
        "boundary_discarded_bytes": 0,
        "stable_during_read": None,
        "reached_start": False,
        "row_count": 0,
        "fieldnames": [],
        "error": None,
    }


def read_csv_tail_rows_with_diagnostics(
    path: str | Path,
    *,
    max_bytes: int,
    max_header_bytes: int = 64 * 1024,
) -> tuple[list[dict], dict[str, Any]]:
    """Read a stable, complete UTF-8 CSV suffix without scaling with file size.

    The first line is read separately as the schema header. When the byte
    window starts inside a record, that record is discarded. Callers must use
    ``reached_start`` plus their batch-boundary contract to decide whether the
    suffix is sufficient; this helper never silently claims a partial suffix
    is the complete tape.
    """

    path = Path(path)
    diagnostics = _bounded_tail_diagnostics(path, max_bytes)
    if not path.exists():
        return [], diagnostics
    try:
        with path.open("rb") as handle:
            initial_stat = os.fstat(handle.fileno())
            file_size = initial_stat.st_size
            diagnostics.update({
                "file_size_bytes": file_size,
                "captured_mtime_ns": initial_stat.st_mtime_ns,
            })
            if file_size <= 0:
                diagnostics.update({"status": "empty", "reached_start": True})
                return [], diagnostics
            header = handle.readline(max(2, int(max_header_bytes)) + 1)
            diagnostics["header_bytes"] = len(header)
            diagnostics["read_bytes"] += len(header)
            if not header.endswith((b"\n", b"\r")):
                diagnostics.update({
                    "status": "invalid_header",
                    "error": "CSV header is missing, incomplete, or exceeds max_header_bytes",
                })
                return [], diagnostics
            header_end = handle.tell()
            if file_size <= header_end:
                diagnostics.update({"status": "empty", "reached_start": True})
                return [], diagnostics
            handle.seek(file_size - 1)
            final_byte = handle.read(1)
            diagnostics["read_bytes"] += len(final_byte)
            if final_byte not in {b"\n", b"\r"}:
                diagnostics.update({
                    "status": "incomplete_tail",
                    "error": "CSV tape does not end at a complete record boundary",
                })
                return [], diagnostics
            window_start = max(header_end, file_size - diagnostics["max_scan_bytes"])
            handle.seek(window_start)
            if window_start > header_end:
                discarded = handle.readline()
                diagnostics["boundary_discarded_bytes"] = len(discarded)
                diagnostics["read_bytes"] += len(discarded)
            data_start = handle.tell()
            payload = handle.read(max(0, file_size - data_start))
            diagnostics.update({
                "scanned_bytes": len(payload),
                "read_bytes": diagnostics["read_bytes"] + len(payload),
                "reached_start": data_start == header_end,
            })
            final_stat = os.fstat(handle.fileno())
            if (
                final_stat.st_size != initial_stat.st_size
                or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
            ):
                diagnostics.update({
                    "status": "concurrent_modification",
                    "stable_during_read": False,
                    "error": "CSV tape changed during the bounded read",
                })
                return [], diagnostics
            diagnostics["stable_during_read"] = True
    except OSError as exc:
        diagnostics.update({"status": "read_error", "error": f"{type(exc).__name__}: {exc}"})
        return [], diagnostics

    try:
        header_text = header.decode("utf-8-sig")
        payload_text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        diagnostics.update({"status": "decode_error", "error": _decode_error_payload(exc)})
        return [], diagnostics

    try:
        header_fields = next(csv.reader([header_text], strict=True), [])
        if not header_fields or any(not str(field).strip() for field in header_fields):
            raise csv.Error("CSV header contains an empty field name")
        if len(set(header_fields)) != len(header_fields):
            raise csv.Error("CSV header contains duplicate field names")
        reader = csv.DictReader(StringIO(payload_text, newline=""), fieldnames=header_fields, strict=True)
        rows = [dict(row) for row in reader]
        malformed = [
            row for row in rows
            if None in row or any(value is None for value in row.values())
        ]
        if malformed:
            raise csv.Error("CSV suffix contains a row that does not match the header")
    except csv.Error as exc:
        diagnostics.update({"status": "malformed_csv", "error": f"csv.Error: {exc}"})
        return [], diagnostics

    diagnostics.update({
        "status": "ok",
        "row_count": len(rows),
        "fieldnames": list(header_fields),
    })
    return rows, diagnostics


def read_jsonl_tail_with_diagnostics(
    path: str | Path,
    *,
    max_bytes: int,
) -> tuple[list[Any], dict[str, Any]]:
    """Read a complete bounded JSONL suffix and reject malformed evidence."""

    path = Path(path)
    diagnostics = _bounded_tail_diagnostics(path, max_bytes)
    if not path.exists():
        return [], diagnostics
    try:
        with path.open("rb") as handle:
            initial_stat = os.fstat(handle.fileno())
            file_size = initial_stat.st_size
            diagnostics.update({
                "file_size_bytes": file_size,
                "captured_mtime_ns": initial_stat.st_mtime_ns,
            })
            if file_size <= 0:
                diagnostics.update({"status": "empty", "reached_start": True})
                return [], diagnostics
            handle.seek(file_size - 1)
            final_byte = handle.read(1)
            diagnostics["read_bytes"] += len(final_byte)
            if final_byte not in {b"\n", b"\r"}:
                diagnostics.update({
                    "status": "incomplete_tail",
                    "error": "JSONL tape does not end at a complete record boundary",
                })
                return [], diagnostics
            window_start = max(0, file_size - diagnostics["max_scan_bytes"])
            handle.seek(window_start)
            if window_start > 0:
                discarded = handle.readline()
                diagnostics["boundary_discarded_bytes"] = len(discarded)
                diagnostics["read_bytes"] += len(discarded)
            data_start = handle.tell()
            payload = handle.read(max(0, file_size - data_start))
            diagnostics.update({
                "scanned_bytes": len(payload),
                "read_bytes": diagnostics["read_bytes"] + len(payload),
                "reached_start": data_start == 0,
            })
            final_stat = os.fstat(handle.fileno())
            if (
                final_stat.st_size != initial_stat.st_size
                or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
            ):
                diagnostics.update({
                    "status": "concurrent_modification",
                    "stable_during_read": False,
                    "error": "JSONL tape changed during the bounded read",
                })
                return [], diagnostics
            diagnostics["stable_during_read"] = True
    except OSError as exc:
        diagnostics.update({"status": "read_error", "error": f"{type(exc).__name__}: {exc}"})
        return [], diagnostics

    try:
        text = payload.decode("utf-8-sig" if diagnostics["reached_start"] else "utf-8")
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        diagnostics.update({"status": "malformed_jsonl", "error": f"{type(exc).__name__}: {exc}"})
        return [], diagnostics
    diagnostics.update({"status": "ok", "row_count": len(rows)})
    return rows, diagnostics


def csv_encoding_issue(diagnostics: dict[str, Any]) -> bool:
    return (diagnostics or {}).get("status") not in {"ok", "missing"}


def strip_csv_diagnostic_columns(row: dict) -> dict:
    return {key: value for key, value in dict(row).items() if key not in CSV_DIAGNOSTIC_COLUMNS}


def normalize_csv_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = (
        value.replace("\u00b0F", " F")
        .replace("\u00b0C", " C")
        .replace("\u2109", " F")
        .replace("\u2103", " C")
        .replace("\u00b0", " deg ")
    )
    return " ".join(normalized.split()) if normalized != value else value


def normalize_csv_row(row: dict) -> dict:
    return {key: normalize_csv_value(value) for key, value in strip_csv_diagnostic_columns(row).items()}


def write_csv_rows(path: str | Path, columns: Iterable[str], rows: Iterable[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(columns)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_csv_row(row))
    return path


def write_csv_rows_atomic(
    path: str | Path,
    columns: Iterable[str],
    rows: Iterable[dict],
) -> Path:
    """Stream a CSV to a sibling temp file, then publish it atomically."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(columns)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(normalize_csv_row(row))
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def append_csv_rows(
    path: str | Path,
    columns: Iterable[str],
    rows: Iterable[dict],
    *,
    write_header_if_missing: bool = True,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(columns)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if write_header_if_missing and not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(normalize_csv_row(row))
    return path
