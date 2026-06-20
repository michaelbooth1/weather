from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SleepFn = Callable[[float], None]
CSV_DIAGNOSTIC_COLUMNS = {
    "_csv_encoding_status",
    "_csv_source_encoding",
    "_csv_source_path",
    "_csv_utf8_decode_error",
}
LEGACY_CSV_ENCODINGS = ("cp1252", "latin-1")


def read_json(path: str | Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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
