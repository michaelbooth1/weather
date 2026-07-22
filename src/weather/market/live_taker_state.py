"""Authority state, idempotency, and durable evidence primitives for the canary.

The module is intentionally exchange- and credential-free.  It provides the
write-ahead pieces a future reviewed adapter can use without giving a status
file or a dashboard the ability to place an order.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from weather.schema_registry import schema_version


EVIDENCE_SCHEMA_VERSION = schema_version("capital_canary_journal_event")
STATUS_SCHEMA_VERSION = schema_version("capital_canary_status")
GENESIS_HASH = "0" * 64
MAX_JOURNAL_RECORD_BYTES = 1024 * 1024
MAX_STATUS_BYTES = 2 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_KEY_RE = re.compile(r"^capital-canary:[0-9a-f]{64}$")
_DECIMAL_STATUS_FIELD_RE = re.compile(
    r"(?:_usdc|price|quantity|probability|fraction|roi|spread|edge|utilization|pnl)$",
    re.IGNORECASE,
)
_RAW_ACCOUNT_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_REDACTED_ACCOUNT_RE = re.compile(
    r"^(?:acct_[0-9a-f]{16,64}|acct_sha256:[0-9a-f]{64}|sha256:[0-9a-f]{64})$"
)
_SENSITIVE_FIELD_RE = re.compile(
    r"(?:^|[_-])(?:api[_-]?(?:key|secret)|authorization|credential(?:s)?|mnemonic|"
    r"passphrase|password|private[_-]?key|seed[_-]?phrase|signature|signed[_-]?order)(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?(?:key|secret)|authorization|mnemonic|passphrase|password|"
    r"private[_-]?key|seed[_-]?phrase)\s*[:=]\s*([^\s&,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+([^\s]+)")
_SAFE_REDACTED_VALUES = {"<redacted>", "[redacted]", "redacted", "***"}
_SAFE_SECRET_CONTROL_VALUES = {
    "absent",
    "disabled",
    "false",
    "never_read",
    "none",
    "not_available",
    "not_read",
    "not_resolved",
}
_SNAPSHOT_RESERVED_FIELDS = {
    "schema_version",
    "generated_at_utc",
    "sequence",
    "ledger_high_water",
    "status_sha256",
}


class AuthorityState(StrEnum):
    LOCKED = "LOCKED"
    PREFLIGHT = "PREFLIGHT"
    ARMED = "ARMED"
    RECONCILE_ONLY = "RECONCILE_ONLY"
    SCANNING = "SCANNING"
    SUBMITTING = "SUBMITTING"
    EXPOSED = "EXPOSED"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


ALLOWED_TRANSITIONS: Mapping[AuthorityState, frozenset[AuthorityState]] = {
    AuthorityState.LOCKED: frozenset({AuthorityState.PREFLIGHT}),
    AuthorityState.PREFLIGHT: frozenset(
        {AuthorityState.LOCKED, AuthorityState.ARMED, AuthorityState.HALTED}
    ),
    AuthorityState.ARMED: frozenset(
        {AuthorityState.RECONCILE_ONLY, AuthorityState.HALTED}
    ),
    AuthorityState.RECONCILE_ONLY: frozenset(
        {AuthorityState.SCANNING, AuthorityState.PAUSED, AuthorityState.HALTED}
    ),
    AuthorityState.SCANNING: frozenset(
        {AuthorityState.SUBMITTING, AuthorityState.PAUSED, AuthorityState.HALTED}
    ),
    AuthorityState.SUBMITTING: frozenset(
        {AuthorityState.EXPOSED, AuthorityState.HALTED}
    ),
    AuthorityState.EXPOSED: frozenset(
        {AuthorityState.SCANNING, AuthorityState.HALTED}
    ),
    AuthorityState.PAUSED: frozenset(
        {AuthorityState.RECONCILE_ONLY, AuthorityState.HALTED}
    ),
    AuthorityState.HALTED: frozenset({AuthorityState.RECONCILE_ONLY}),
}


class StateTransitionError(ValueError):
    """Raised when code attempts a transition outside the reviewed graph."""


class JournalIntegrityError(RuntimeError):
    """Raised when append-only evidence cannot be proven intact."""


class JournalBusyError(RuntimeError):
    """Raised when another writer already owns the per-journal append lock."""


class CampaignBusyError(RuntimeError):
    """Raised when another process already owns the campaign lifetime lock."""


class DuplicateIntentError(RuntimeError):
    """Raised when an intent key already has a durable reservation."""


class SecretMaterialError(ValueError):
    """Raised without echoing secret material into an exception or log."""


def _utc_iso(value: datetime | str | None = None) -> str:
    if value is None:
        current = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        current = value
    else:
        try:
            current = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be an ISO-8601 datetime") from exc
    if current.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    current = current.astimezone(timezone.utc)
    return current.isoformat().replace("+00:00", "Z")


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Decimal values must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("capital-canary evidence object keys must be strings")
        return {key: _canonical_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(child) for child in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # Artifact writers must not silently accept NaN/Inf or binary money.
        raise TypeError("float values are not accepted in capital-canary evidence")
    raise TypeError(f"unsupported capital-canary evidence type: {type(value).__name__}")


def _canonical_status_value(value: Any, *, path: tuple[str, ...] = ()) -> Any:
    """Normalize status JSON while permitting finite, non-money measurements."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("status float values must be finite")
        if path and _DECIMAL_STATUS_FIELD_RE.search(path[-1]):
            raise TypeError("status money, price, and risk values cannot be floats")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("capital-canary status object keys must be strings")
        return {
            key: _canonical_status_value(child, path=path + (key,))
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_status_value(child, path=path) for child in value]
    return _canonical_value(value)


def canonical_json_bytes(value: Any) -> bytes:
    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _is_unredacted_assignment(value: str) -> bool:
    for pattern in (_SECRET_ASSIGNMENT_RE, _BEARER_RE):
        for match in pattern.finditer(value):
            candidate = match.group(1).strip().lower()
            if candidate not in _SAFE_REDACTED_VALUES:
                return True
    return False


def assert_secret_safe(value: Any) -> None:
    """Reject secret-bearing fields/text without including values in errors."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SENSITIVE_FIELD_RE.search(str(key).strip()):
                safe_control = child is None or child is False
                if isinstance(child, str):
                    safe_control = (
                        child.strip().lower()
                        in _SAFE_REDACTED_VALUES | _SAFE_SECRET_CONTROL_VALUES
                    )
                if not safe_control:
                    raise SecretMaterialError(
                        "capital-canary evidence contains a forbidden secret-bearing field"
                    )
                continue
            assert_secret_safe(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            assert_secret_safe(child)
        return
    if isinstance(value, str) and _is_unredacted_assignment(value):
        raise SecretMaterialError(
            "capital-canary evidence contains unredacted secret-like text"
        )


@dataclass(frozen=True)
class StateTransition:
    sequence: int
    previous_state: AuthorityState
    state: AuthorityState
    reason_code: str
    recorded_at_utc: str

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "event_type": "authority_state_transition",
            "sequence": self.sequence,
            "previous_state": self.previous_state.value,
            "state": self.state.value,
            "reason_code": self.reason_code,
            "recorded_at_utc": self.recorded_at_utc,
            "network_write_phase": self.state is AuthorityState.SUBMITTING,
        }


@dataclass(frozen=True)
class CanaryStateMachine:
    state: AuthorityState = AuthorityState.LOCKED
    sequence: int = 0
    last_transition_at_utc: str | None = None

    def __post_init__(self) -> None:
        try:
            state = AuthorityState(self.state)
        except ValueError as exc:
            raise ValueError("unknown capital-canary authority state") from exc
        object.__setattr__(self, "state", state)
        if isinstance(self.sequence, bool) or int(self.sequence) != self.sequence:
            raise ValueError("state sequence must be a non-negative integer")
        if int(self.sequence) < 0:
            raise ValueError("state sequence must be a non-negative integer")
        object.__setattr__(self, "sequence", int(self.sequence))
        if self.last_transition_at_utc is not None:
            object.__setattr__(
                self,
                "last_transition_at_utc",
                _utc_iso(self.last_transition_at_utc),
            )

    @property
    def in_submission_phase(self) -> bool:
        """Describe phase only; state never grants network-write authority.

        A future adapter must independently revalidate activation, readiness,
        account, release, evidence, freshness, economics, and risk immediately
        before a network write.
        """
        return self.state is AuthorityState.SUBMITTING

    def transition(
        self,
        next_state: AuthorityState | str,
        *,
        reason_code: str,
        recorded_at_utc: datetime | str | None = None,
    ) -> tuple[CanaryStateMachine, StateTransition]:
        try:
            destination = AuthorityState(next_state)
        except ValueError as exc:
            raise StateTransitionError("unknown authority-state destination") from exc
        if destination not in ALLOWED_TRANSITIONS[self.state]:
            raise StateTransitionError(
                f"authority transition {self.state.value} -> {destination.value} is not allowed"
            )
        reason = str(reason_code).strip()
        if not reason:
            raise ValueError("reason_code is required for every authority transition")
        assert_secret_safe(reason)
        timestamp = _utc_iso(recorded_at_utc)
        event = StateTransition(
            sequence=self.sequence + 1,
            previous_state=self.state,
            state=destination,
            reason_code=reason,
            recorded_at_utc=timestamp,
        )
        return (
            CanaryStateMachine(
                state=destination,
                sequence=event.sequence,
                last_transition_at_utc=timestamp,
            ),
            event,
        )


def _required_identity_text(value: Any, *, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is required")
    assert_secret_safe(text)
    return text


def _required_sha256(value: Any, *, field: str) -> str:
    text = _required_identity_text(value, field=field).lower()
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _intent_decimal(value: Any, *, field: str, minimum: Decimal, maximum: Decimal) -> str:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not number.is_finite() or not minimum <= number <= maximum:
        raise ValueError(f"{field} is outside its valid range")
    return _canonical_decimal(number)


def make_idempotency_key(
    *,
    platform: str,
    account_identity_redacted: str,
    event_id: str,
    token_id: str,
    side: str,
    limit_price: Any,
    quantity: Any,
    release_hash: str,
    snapshot_hash: str,
    policy_hash: str,
    sequence: int,
) -> str:
    """Bind an intent to its exact reviewed inputs using canonical JSON."""
    account = _required_identity_text(
        account_identity_redacted,
        field="account_identity_redacted",
    ).lower()
    if _RAW_ACCOUNT_RE.fullmatch(account) or not _REDACTED_ACCOUNT_RE.fullmatch(account):
        raise ValueError("account_identity_redacted must be a supported digest label")
    normalized_side = _required_identity_text(side, field="side").upper()
    if normalized_side not in {"BUY", "BUY_YES"}:
        raise ValueError("the first capital-canary lane permits YES buys only")
    if isinstance(sequence, bool) or int(sequence) != sequence or int(sequence) <= 0:
        raise ValueError("sequence must be a positive integer")
    identity = {
        "platform": _required_identity_text(platform, field="platform").lower(),
        "account_identity_redacted": account,
        "event_id": _required_identity_text(event_id, field="event_id"),
        "token_id": _required_identity_text(token_id, field="token_id"),
        "side": normalized_side,
        "limit_price": _intent_decimal(
            limit_price,
            field="limit_price",
            minimum=Decimal("0.000000000000000001"),
            maximum=Decimal("0.999999999999999999"),
        ),
        "quantity": _intent_decimal(
            quantity,
            field="quantity",
            minimum=Decimal("0.000000000000000001"),
            maximum=Decimal("1000000000"),
        ),
        "release_hash": _required_sha256(release_hash, field="release_hash"),
        "snapshot_hash": _required_sha256(snapshot_hash, field="snapshot_hash"),
        "policy_hash": _required_sha256(policy_hash, field="policy_hash"),
        "sequence": int(sequence),
    }
    return f"capital-canary:{canonical_sha256(identity)}"


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("non-finite JSON number")
        ),
    )
    if not isinstance(value, dict):
        raise ValueError("JSON record must be an object")
    return value


@dataclass(frozen=True)
class JournalVerification:
    valid: bool
    record_count: int
    last_sequence: int
    last_hash: str
    error_code: str | None = None


def verify_hash_chain(path: str | Path) -> JournalVerification:
    """Verify every complete line; a torn final record fails closed."""
    source = Path(path)
    if not source.exists():
        return JournalVerification(True, 0, 0, GENESIS_HASH)
    expected_sequence = 1
    previous_hash = GENESIS_HASH
    try:
        with source.open("rb") as handle:
            while True:
                raw_line = handle.readline(MAX_JOURNAL_RECORD_BYTES + 1)
                if not raw_line:
                    break
                if len(raw_line) > MAX_JOURNAL_RECORD_BYTES:
                    return JournalVerification(
                        False,
                        expected_sequence - 1,
                        expected_sequence - 1,
                        previous_hash,
                        "RECORD_OVERSIZED",
                    )
                if not raw_line.endswith(b"\n"):
                    return JournalVerification(
                        False,
                        expected_sequence - 1,
                        expected_sequence - 1,
                        previous_hash,
                        "TORN_FINAL_RECORD",
                    )
                try:
                    record = _strict_json_object(raw_line)
                    assert_secret_safe(record)
                except SecretMaterialError:
                    return JournalVerification(
                        False,
                        expected_sequence - 1,
                        expected_sequence - 1,
                        previous_hash,
                        "SECRET_BEARING_RECORD",
                    )
                except (UnicodeError, ValueError, json.JSONDecodeError):
                    return JournalVerification(
                        False,
                        expected_sequence - 1,
                        expected_sequence - 1,
                        previous_hash,
                        "MALFORMED_RECORD",
                    )
                if record.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
                    error_code = "SCHEMA_MISMATCH"
                elif record.get("sequence") != expected_sequence:
                    error_code = "SEQUENCE_MISMATCH"
                elif record.get("previous_hash") != previous_hash:
                    error_code = "PREVIOUS_HASH_MISMATCH"
                else:
                    claimed_hash = record.get("record_hash")
                    content = dict(record)
                    content.pop("record_hash", None)
                    try:
                        calculated_hash = canonical_sha256(content)
                    except (TypeError, ValueError):
                        error_code = "MALFORMED_RECORD"
                    else:
                        error_code = (
                            "RECORD_HASH_MISMATCH"
                            if claimed_hash != calculated_hash
                            else None
                        )
                if error_code:
                    return JournalVerification(
                        False,
                        expected_sequence - 1,
                        expected_sequence - 1,
                        previous_hash,
                        error_code,
                    )
                previous_hash = str(record["record_hash"])
                expected_sequence += 1
    except OSError:
        return JournalVerification(
            False,
            expected_sequence - 1,
            expected_sequence - 1,
            previous_hash,
            "READ_ERROR",
        )
    count = expected_sequence - 1
    return JournalVerification(True, count, count, previous_hash)


def _intent_key_already_reserved(path: Path, idempotency_key: str) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("rb") as handle:
            while True:
                raw_line = handle.readline(MAX_JOURNAL_RECORD_BYTES + 1)
                if not raw_line:
                    return False
                if len(raw_line) > MAX_JOURNAL_RECORD_BYTES:
                    raise JournalIntegrityError(
                        "capital-canary journal contains an oversized record"
                    )
                record = _strict_json_object(raw_line)
                record_payload = record.get("payload")
                if (
                    record.get("event_type") in {"intent_reserved", "order_intent_reserved"}
                    and isinstance(record_payload, Mapping)
                    and record_payload.get("idempotency_key")
                    == idempotency_key
                ):
                    return True
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise JournalIntegrityError(
            "capital-canary journal could not be checked for duplicate intent"
        ) from exc


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability; directory handles are not portable."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        handle = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


class CampaignLock:
    """Exclusive lifetime worker lock with no unsafe stale-lock takeover."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._owned = False

    @property
    def owned(self) -> bool:
        return self._owned

    def acquire(self, *, acquired_at_utc: datetime | str | None = None) -> None:
        if self._owned:
            raise CampaignBusyError("capital-canary campaign lock is already owned")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise CampaignBusyError(
                "another capital-canary worker or stale lock requires review"
            ) from exc
        try:
            record = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "lock_type": "campaign_lifetime_worker",
                "pid": os.getpid(),
                "acquired_at_utc": _utc_iso(acquired_at_utc),
            }
            os.write(handle, canonical_json_bytes(record) + b"\n")
            os.fsync(handle)
        except BaseException:
            os.close(handle)
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(handle)
        _fsync_directory(self.path.parent)
        self._owned = True

    def release(self) -> None:
        if not self._owned:
            return
        self.path.unlink()
        _fsync_directory(self.path.parent)
        self._owned = False

    def __enter__(self) -> CampaignLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


class HashChainJournal:
    """Fail-closed, fsynced JSONL appender with a per-append owner lock."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.append.lock")

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        recorded_at_utc: datetime | str | None = None,
    ) -> dict[str, Any]:
        event_name = str(event_type).strip()
        if not event_name:
            raise ValueError("event_type is required")
        if not isinstance(payload, Mapping):
            raise TypeError("journal payload must be a mapping")
        assert_secret_safe(event_name)
        assert_secret_safe(payload)
        canonical_payload = _canonical_value(payload)
        reservation_key: str | None = None
        if event_name in {"intent_reserved", "order_intent_reserved"}:
            candidate_key = canonical_payload.get("idempotency_key")
            if not isinstance(candidate_key, str) or not _IDEMPOTENCY_KEY_RE.fullmatch(
                candidate_key
            ):
                raise ValueError(
                    "intent reservation requires a canonical idempotency_key"
                )
            reservation_key = candidate_key

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_handle = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise JournalBusyError("capital-canary journal already has a writer") from exc
        try:
            os.write(lock_handle, str(os.getpid()).encode("ascii"))
            os.fsync(lock_handle)
            verification = verify_hash_chain(self.path)
            if not verification.valid:
                raise JournalIntegrityError(
                    f"capital-canary journal failed integrity check: {verification.error_code}"
                )
            if reservation_key and _intent_key_already_reserved(
                self.path,
                reservation_key,
            ):
                raise DuplicateIntentError(
                    "capital-canary intent already has a durable reservation"
                )
            record = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "sequence": verification.last_sequence + 1,
                "recorded_at_utc": _utc_iso(recorded_at_utc),
                "event_type": event_name,
                "payload": canonical_payload,
                "previous_hash": verification.last_hash,
            }
            record["record_hash"] = canonical_sha256(record)
            encoded = canonical_json_bytes(record) + b"\n"
            existed = self.path.exists()
            with self.path.open("ab", buffering=0) as handle:
                handle.write(encoded)
                os.fsync(handle.fileno())
            if not existed:
                _fsync_directory(self.path.parent)
            return record
        finally:
            os.close(lock_handle)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class SnapshotVerification:
    valid: bool
    sequence: int | None = None
    ledger_sequence: int | None = None
    ledger_hash: str | None = None
    error_code: str | None = None


def status_content_sha256(payload: Mapping[str, Any]) -> str:
    content = dict(payload)
    content.pop("status_sha256", None)
    try:
        encoded = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("status payload is not canonical-JSON serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_payload(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    with Path(source).open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("status snapshot must be a regular file")
        if before.st_size <= 0 or before.st_size > MAX_STATUS_BYTES:
            raise ValueError("status snapshot size is invalid")
        raw = handle.read(MAX_STATUS_BYTES + 1)
        after = os.fstat(handle.fileno())
    if len(raw) != before.st_size or len(raw) > MAX_STATUS_BYTES:
        raise ValueError("status snapshot size is invalid")
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise ValueError("status snapshot changed during read")
    return _strict_json_object(raw)


def validate_status_snapshot(
    source: str | Path | Mapping[str, Any],
    *,
    journal_path: str | Path | None = None,
) -> SnapshotVerification:
    try:
        payload = _snapshot_payload(source)
        assert_secret_safe(payload)
    except FileNotFoundError:
        return SnapshotVerification(False, error_code="MISSING")
    except SecretMaterialError:
        return SnapshotVerification(False, error_code="SECRET_BEARING_SNAPSHOT")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return SnapshotVerification(False, error_code="MALFORMED")
    if payload.get("schema_version") != STATUS_SCHEMA_VERSION:
        return SnapshotVerification(False, error_code="SCHEMA_MISMATCH")
    sequence = payload.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return SnapshotVerification(False, error_code="SEQUENCE_INVALID")
    ledger = payload.get("ledger_high_water")
    if not isinstance(ledger, Mapping):
        return SnapshotVerification(False, sequence=sequence, error_code="LEDGER_HIGH_WATER_INVALID")
    ledger_sequence = ledger.get("sequence")
    ledger_hash = ledger.get("record_hash")
    if (
        isinstance(ledger_sequence, bool)
        or not isinstance(ledger_sequence, int)
        or ledger_sequence < 0
        or not isinstance(ledger_hash, str)
        or not _SHA256_RE.fullmatch(ledger_hash)
    ):
        return SnapshotVerification(False, sequence=sequence, error_code="LEDGER_HIGH_WATER_INVALID")
    if ledger_sequence > sequence:
        return SnapshotVerification(False, sequence=sequence, error_code="LEDGER_SEQUENCE_AHEAD")
    if (ledger_sequence == 0 and ledger_hash != GENESIS_HASH) or (
        ledger_sequence > 0 and ledger_hash == GENESIS_HASH
    ):
        return SnapshotVerification(
            False,
            sequence=sequence,
            ledger_sequence=ledger_sequence,
            ledger_hash=ledger_hash,
            error_code="LEDGER_HIGH_WATER_INCONSISTENT",
        )
    claimed_hash = payload.get("status_sha256")
    try:
        calculated_hash = status_content_sha256(payload)
    except ValueError:
        return SnapshotVerification(False, sequence=sequence, error_code="MALFORMED")
    if not isinstance(claimed_hash, str) or claimed_hash != calculated_hash:
        return SnapshotVerification(
            False,
            sequence=sequence,
            ledger_sequence=ledger_sequence,
            ledger_hash=ledger_hash,
            error_code="STATUS_HASH_MISMATCH",
        )
    if journal_path is not None:
        journal = verify_hash_chain(journal_path)
        if not journal.valid:
            return SnapshotVerification(
                False,
                sequence=sequence,
                ledger_sequence=ledger_sequence,
                ledger_hash=ledger_hash,
                error_code=f"JOURNAL_{journal.error_code or 'INVALID'}",
            )
        if (
            journal.last_sequence != ledger_sequence
            or journal.last_hash != ledger_hash
        ):
            return SnapshotVerification(
                False,
                sequence=sequence,
                ledger_sequence=ledger_sequence,
                ledger_hash=ledger_hash,
                error_code="LEDGER_HIGH_WATER_MISMATCH",
            )
    return SnapshotVerification(
        True,
        sequence=sequence,
        ledger_sequence=ledger_sequence,
        ledger_hash=ledger_hash,
    )


def verify_status_snapshot(
    source: str | Path | Mapping[str, Any],
    *,
    journal_path: str | Path | None = None,
) -> bool:
    return validate_status_snapshot(source, journal_path=journal_path).valid


def write_status_snapshot(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    sequence: int,
    ledger_hash: str,
    ledger_sequence: int | None = None,
    generated_at_utc: datetime | str | None = None,
) -> dict[str, Any]:
    """Durably replace the canonical status projection and return its content."""
    if not isinstance(payload, Mapping):
        raise TypeError("status payload must be a mapping")
    collisions = _SNAPSHOT_RESERVED_FIELDS.intersection(map(str, payload.keys()))
    if collisions:
        raise ValueError("status payload contains reserved projection fields")
    assert_secret_safe(payload)
    canonical_payload = _canonical_status_value(payload)
    if isinstance(sequence, bool) or int(sequence) != sequence or int(sequence) < 0:
        raise ValueError("sequence must be a non-negative integer")
    sequence = int(sequence)
    ledger_sequence = sequence if ledger_sequence is None else ledger_sequence
    if (
        isinstance(ledger_sequence, bool)
        or int(ledger_sequence) != ledger_sequence
        or int(ledger_sequence) < 0
        or int(ledger_sequence) > sequence
    ):
        raise ValueError("ledger_sequence must be between zero and sequence")
    if not isinstance(ledger_hash, str) or not _SHA256_RE.fullmatch(ledger_hash):
        raise ValueError("ledger_hash must be a lowercase SHA-256 digest")
    if (ledger_sequence == 0 and ledger_hash != GENESIS_HASH) or (
        ledger_sequence > 0 and ledger_hash == GENESIS_HASH
    ):
        raise ValueError("ledger_hash is inconsistent with ledger_sequence")

    snapshot = {
        **canonical_payload,
        "schema_version": STATUS_SCHEMA_VERSION,
        "generated_at_utc": _utc_iso(generated_at_utc),
        "sequence": sequence,
        "ledger_high_water": {
            "sequence": int(ledger_sequence),
            "record_hash": ledger_hash,
        },
    }
    snapshot["status_sha256"] = status_content_sha256(snapshot)
    assert_secret_safe(snapshot)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    )
    try:
        with temporary.open("wb") as handle:
            handle.write(json.dumps(snapshot, indent=2, sort_keys=True).encode("utf-8"))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return snapshot


__all__ = [
    "ALLOWED_TRANSITIONS",
    "AuthorityState",
    "CampaignBusyError",
    "CampaignLock",
    "CanaryStateMachine",
    "DuplicateIntentError",
    "EVIDENCE_SCHEMA_VERSION",
    "GENESIS_HASH",
    "HashChainJournal",
    "JournalBusyError",
    "JournalIntegrityError",
    "JournalVerification",
    "MAX_JOURNAL_RECORD_BYTES",
    "MAX_STATUS_BYTES",
    "STATUS_SCHEMA_VERSION",
    "SecretMaterialError",
    "SnapshotVerification",
    "StateTransition",
    "StateTransitionError",
    "assert_secret_safe",
    "canonical_json_bytes",
    "canonical_sha256",
    "make_idempotency_key",
    "status_content_sha256",
    "validate_status_snapshot",
    "verify_hash_chain",
    "verify_status_snapshot",
    "write_status_snapshot",
]
