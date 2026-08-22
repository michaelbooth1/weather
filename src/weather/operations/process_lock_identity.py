"""Process-instance identity for fail-closed runtime lock ownership."""

from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


LOCK_OWNER_IDENTITY_FIELD = "owner_process_identity"
LEGACY_LOCK_CLOCK_TOLERANCE_SECONDS = 2.0
LOCK_TRANSACTION_TIMEOUT_SECONDS = 5.0
_SAFE_OBSERVATION_FIELDS = (
    "state",
    "pid",
    "image_path",
    "creation_time_token",
    "creation_time_utc",
    "inspectable",
    "reason",
)


class LockPathTransactionBusy(RuntimeError):
    """Raised when another process is changing the same lock pathname."""


def _safe_process_observation(value, *, pid=None):
    raw = value if isinstance(value, dict) else {}
    safe = {field: raw.get(field) for field in _SAFE_OBSERVATION_FIELDS if field in raw}
    safe.setdefault("pid", pid)
    if "reason" in safe and safe["reason"] is not None:
        safe["reason"] = str(safe["reason"])[:500]
    return safe


def observe_process_identity(pid):
    from weather.operations.supervisor import observe_process

    return _safe_process_observation(observe_process(pid), pid=pid)


@contextlib.contextmanager
def lock_path_transaction(path, *, timeout_seconds=LOCK_TRANSACTION_TIMEOUT_SECONDS):
    """Serialize every compliant mutation of one lock pathname across processes."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    transaction_path = path.with_name(f".{path.name}.transaction.lock")
    handle = transaction_path.open("a+b", buffering=0)
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    acquired = False
    try:
        if transaction_path.stat().st_size == 0:
            handle.write(b"\0")
        while not acquired:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LockPathTransactionBusy(
                        f"lock pathname transaction busy: {path}"
                    ) from exc
                time.sleep(0.01)
        yield
    finally:
        try:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def remove_lock_payload_if_current(path, expected_payload):
    """Remove only the payload classified by the caller's held transaction."""

    path = Path(path)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"removed": False, "reason": "missing_before_remove"}
    except (OSError, json.JSONDecodeError):
        return {"removed": False, "reason": "lock_replaced_or_unreadable"}
    if current != expected_payload:
        return {"removed": False, "reason": "lock_instance_replaced"}
    try:
        path.unlink()
    except FileNotFoundError:
        return {"removed": False, "reason": "missing_before_remove"}
    return {"removed": True, "reason": "verified_lock_instance_removed"}


def current_process_identity():
    observed = observe_process_identity(os.getpid())
    return {
        "pid": os.getpid(),
        "image_path": observed.get("image_path"),
        "creation_time_token": observed.get("creation_time_token"),
    }


def _parse_utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _filetime_utc(token):
    try:
        text = str(token)
        if not text.startswith("win32-filetime:"):
            return None
        ticks = int(text.removeprefix("win32-filetime:"))
        return datetime.fromtimestamp(
            (ticks - 116444736000000000) / 10_000_000,
            timezone.utc,
        )
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def lock_owner_status(detail, *, observe_fn=None):
    """Prove staleness by absence/identity mismatch; inspection failure blocks."""

    legacy = not isinstance(detail, dict) or LOCK_OWNER_IDENTITY_FIELD not in detail
    try:
        pid = int(detail.get("pid"))
    except (AttributeError, TypeError, ValueError):
        return {
            "active": True,
            "running": None,
            "stale": False,
            "stale_reason": "owner_unknown",
            "legacy_lock": legacy,
            "identity_match": None,
            "observation": {},
        }
    if pid <= 0:
        return {
            "active": False,
            "running": False,
            "stale": True,
            "stale_reason": "invalid_pid",
            "legacy_lock": legacy,
            "identity_match": False,
            "observation": {},
        }
    observed = _safe_process_observation(
        (observe_fn or observe_process_identity)(pid),
        pid=pid,
    )
    common = {"legacy_lock": legacy, "observation": observed}
    if observed.get("state") == "not_found":
        return {
            **common,
            "active": False,
            "running": False,
            "stale": True,
            "stale_reason": "dead_pid",
            "identity_match": False,
        }
    if observed.get("state") != "running":
        return {
            **common,
            "active": True,
            "running": None,
            "stale": False,
            "stale_reason": "owner_identity_unknown",
            "identity_match": None,
        }
    if not legacy:
        stored = detail.get(LOCK_OWNER_IDENTITY_FIELD)
        valid = isinstance(stored, dict) and stored.get("pid") == pid
        expected = stored.get("creation_time_token") if valid else None
        actual = observed.get("creation_time_token")
        if not expected or not actual:
            return {
                **common,
                "active": True,
                "running": True,
                "stale": False,
                "stale_reason": "owner_identity_unverifiable",
                "identity_match": None,
            }
        mismatch = expected != actual
        return {
            **common,
            "active": not mismatch,
            "running": True,
            "stale": mismatch,
            "stale_reason": "process_identity_mismatch" if mismatch else "",
            "identity_match": not mismatch,
        }
    recorded = _parse_utc(detail.get("created_at_utc") or detail.get("started_at_utc"))
    created = _filetime_utc(observed.get("creation_time_token"))
    reused = bool(
        recorded
        and created
        and created
        > recorded + timedelta(seconds=LEGACY_LOCK_CLOCK_TOLERANCE_SECONDS)
    )
    image = (
        str(observed.get("image_path") or "")
        .replace("\\", "/")
        .rsplit("/", 1)[-1]
        .casefold()
    )
    wrong_image = bool(image and not image.startswith("python"))
    stale = reused or wrong_image
    reason = "legacy_pid_reused_after_lock" if reused else ""
    if wrong_image and not reason:
        reason = "legacy_owner_image_mismatch"
    return {
        **common,
        "active": not stale,
        "running": True,
        "stale": stale,
        "stale_reason": reason,
        "identity_match": None,
    }
