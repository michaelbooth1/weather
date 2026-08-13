"""Fail-closed authenticated International Polymarket user-stream reader.

The reader is inert until ``run`` or ``start`` is called. Authentication stays
in memory and is never written to its append-only evidence journal.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
import websocket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from weather.market.market_microstructure_constants import CLOB_USER_WS_URL
from weather.market.mm_official_adapter import normalize_official_user_event
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_user_stream_journal")
SUBSCRIPTION_SHAPE = {
    "auth_fields": ["apiKey", "passphrase", "secret"],
    "markets_omitted": True,
    "type": "user",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_websocket_factory(url: str, *, timeout: float):
    return websocket.create_connection(url, timeout=timeout)


def _timeout_exceptions() -> tuple[type[BaseException], ...]:
    return (TimeoutError, websocket.WebSocketTimeoutException)


class OfficialUserStreamReader:
    """One-session account-wide reader with durable, redacted event evidence."""

    def __init__(
        self,
        *,
        api_key: str,
        secret: str,
        passphrase: str,
        maker_address: str,
        condition_id: str,
        token_id: str,
        journal_path: str | Path,
        websocket_factory: Callable[..., Any] | None = None,
        heartbeat_seconds: float = 10.0,
        inbound_silence_seconds: float = 30.0,
        connect_timeout_seconds: float = 15.0,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        auth = {
            "apiKey": str(api_key or ""),
            "secret": str(secret or ""),
            "passphrase": str(passphrase or ""),
        }
        if any(not value for value in auth.values()):
            raise ValueError("user-stream authentication values must be nonempty")
        self._auth = auth
        self.maker_address = str(maker_address or "").strip()
        self.condition_id = str(condition_id or "").strip().lower()
        self.token_id = str(token_id or "").strip()
        if not self.maker_address or not self.condition_id or not self.token_id:
            raise ValueError("user stream requires exact maker, condition, and token scope")
        self.journal_path = Path(journal_path)
        self.websocket_factory = websocket_factory or _default_websocket_factory
        self.heartbeat_seconds = max(1.0, float(heartbeat_seconds))
        self.inbound_silence_seconds = float(inbound_silence_seconds)
        if self.inbound_silence_seconds <= self.heartbeat_seconds:
            raise ValueError("inbound silence deadline must exceed the heartbeat interval")
        self.connect_timeout_seconds = max(1.0, float(connect_timeout_seconds))
        self.monotonic_clock = monotonic_clock or time.monotonic
        self._events: list[dict[str, Any]] = []
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "NOT_STARTED"
        self._last_event_at_utc: str | None = None
        self._last_inbound_at_utc: str | None = None
        self._last_pong_at_utc: str | None = None
        self._failure_type: str | None = None
        self._subscription_sent = False

    def __repr__(self) -> str:
        return (
            "OfficialUserStreamReader("
            f"state={self._state!r}, condition_id={self.condition_id!r}, "
            f"token_id={self.token_id!r}, auth=<redacted>)"
        )

    def _append(self, event_type: str, **fields: Any) -> None:
        row = {
            "schema_version": SCHEMA_VERSION,
            "recorded_at_utc": _utc_iso(),
            "event_type": event_type,
            **fields,
        }
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":"))
        with self._mutex:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def events(self) -> list[dict[str, Any]]:
        with self._mutex:
            return [dict(row) for row in self._events]

    def health(self) -> dict[str, Any]:
        with self._mutex:
            return {
                "state": self._state,
                "event_count": len(self._events),
                "last_event_at_utc": self._last_event_at_utc,
                "last_inbound_at_utc": self._last_inbound_at_utc,
                "last_pong_at_utc": self._last_pong_at_utc,
                "failure_type": self._failure_type,
                "account_wide_subscription": True,
                "secret_values_redacted": True,
                "journal_path": str(self.journal_path),
            }

    def bootstrap_evidence(self) -> dict[str, Any]:
        """Return secret-free, content-bound transport facts for Stage 0."""

        health = self.health()
        journal_sha256 = None
        with self._mutex:
            if self.journal_path.exists():
                journal_sha256 = hashlib.sha256(self.journal_path.read_bytes()).hexdigest()
        shape_bytes = json.dumps(
            SUBSCRIPTION_SHAPE,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "account_wide_subscription_sent": self._subscription_sent,
            "server_pong_observed": health["last_pong_at_utc"] is not None,
            "transport_active": bool(
                self._thread is not None
                and self._thread.is_alive()
                and health["state"] in {
                    "TRANSPORT_CONNECTED_UNPROVEN",
                    "SUBSCRIPTION_PROVEN",
                }
            ),
            "subscription_shape_sha256": hashlib.sha256(shape_bytes).hexdigest(),
            "journal_sha256": journal_sha256,
            "heartbeat_seconds": self.heartbeat_seconds,
            "inbound_silence_seconds": self.inbound_silence_seconds,
            "transport_state": health["state"],
            "secret_values_redacted": True,
        }

    def run(self, *, max_events: int | None = None) -> None:
        if self.journal_path.exists():
            raise RuntimeError("user-stream journal path must not already exist")
        self._state = "CONNECTING"
        self._append(
            "stream_starting",
            account_wide_subscription=True,
            maker_address=self.maker_address,
            condition_id=self.condition_id,
            token_id=self.token_id,
            secret_values_redacted=True,
        )
        websocket = None
        try:
            websocket = self.websocket_factory(
                CLOB_USER_WS_URL,
                timeout=self.connect_timeout_seconds,
            )
            try:
                websocket.settimeout(min(1.0, self.heartbeat_seconds))
            except AttributeError:
                pass
            websocket.send(json.dumps({"auth": self._auth, "type": "user"}))
            with self._mutex:
                self._subscription_sent = True
            self._state = "TRANSPORT_CONNECTED_UNPROVEN"
            self._append("subscription_sent", account_wide_subscription=True)
            last_inbound = self.monotonic_clock()
            last_pong = last_inbound
            next_ping = last_inbound + self.heartbeat_seconds
            while not self._stop.is_set():
                if max_events is not None and len(self.events()) >= int(max_events):
                    break
                if self.monotonic_clock() >= next_ping:
                    websocket.send("PING")
                    next_ping = self.monotonic_clock() + self.heartbeat_seconds
                if self.monotonic_clock() - last_pong > self.inbound_silence_seconds:
                    raise ConnectionError("user stream received no server PONG")
                try:
                    raw = websocket.recv()
                except _timeout_exceptions():
                    if self.monotonic_clock() - last_inbound > self.inbound_silence_seconds:
                        raise ConnectionError("user stream received no inbound server heartbeat")
                    continue
                if raw in (None, "", b""):
                    raise ConnectionError("user stream returned an empty frame")
                last_inbound = self.monotonic_clock()
                inbound_at = _utc_iso()
                with self._mutex:
                    self._last_inbound_at_utc = inbound_at
                if raw in ("PONG", b"PONG"):
                    last_pong = self.monotonic_clock()
                    with self._mutex:
                        self._last_pong_at_utc = inbound_at
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("user stream returned invalid JSON") from exc
                items = payload if isinstance(payload, list) else [payload]
                normalized: list[dict[str, Any]] = []
                for item in items:
                    normalized.extend(normalize_official_user_event(
                        item,
                        maker_address=self.maker_address,
                        condition_id=self.condition_id,
                        token_id=self.token_id,
                    ))
                with self._mutex:
                    self._events.extend(normalized)
                    self._state = "SUBSCRIPTION_PROVEN"
                    self._last_event_at_utc = _utc_iso()
                for row in normalized:
                    self._append("user_event", payload=row)
        except Exception as exc:
            with self._mutex:
                self._state = "FAILED"
                self._failure_type = type(exc).__name__
            self._append("stream_failed", exception_type=type(exc).__name__)
            raise
        finally:
            if websocket is not None:
                try:
                    websocket.close()
                except Exception:
                    pass
            if self._state != "FAILED":
                self._state = "STOPPED"
                self._append("stream_stopped")

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("user stream has already been started")
        self._thread = threading.Thread(
            target=self.run,
            name="polymarket-global-user-stream",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(float(timeout_seconds))
            if self._thread.is_alive():
                raise RuntimeError("user-stream thread did not stop within the timeout")
