"""Bounded single-fetch fan-out for explicitly market-invariant responses."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable


@dataclass(frozen=True)
class FanoutFetchResult:
    value: Any
    source: str
    request_key: str
    cycle_key: str
    fetched: bool
    reused: bool


class MarketInvariantFetchFanout:
    """Coalesce same-process fetches sharing an attested request/cycle key.

    Failures are delivered to all concurrent waiters but are not cached, so a
    later request can retry normally. Completed responses are reusable only
    inside a caller-supplied capture-pass scope, and that cache is bounded
    because national forecast responses can be tens of MiB each.
    """

    def __init__(self, *, max_entries: int = 2):
        self.max_entries = max(1, int(max_entries))
        self._lock = Lock()
        self._completed: OrderedDict[
            tuple[str, str, str, str, str], Any
        ] = OrderedDict()
        self._inflight: dict[tuple[str, str, str, str, str], Future] = {}

    @staticmethod
    def _key(source: str, request_key: str, cycle_key: str) -> tuple[str, str, str]:
        source = str(source or "").strip()
        request_key = str(request_key or "").strip()
        cycle_key = str(cycle_key or "").strip()
        if not source or not request_key or not cycle_key:
            raise ValueError("single-fetch fan-out requires source, request_key, and cycle_key")
        return source, request_key, cycle_key

    def fetch(
        self,
        *,
        source: str,
        request_key: str,
        cycle_key: str,
        fetch_fn: Callable[[], Any],
        scope_key: str | None = None,
    ) -> FanoutFetchResult:
        source, request_key, cycle_key = self._key(source, request_key, cycle_key)
        scope = str(scope_key or "").strip()
        # A completed response may be reused only inside an explicit capture
        # pass. Unscoped calls still coalesce genuinely concurrent requests,
        # but a later call re-fetches so same-URL provider updates stay visible.
        key = ("scoped" if scope else "inflight", scope, source, request_key, cycle_key)
        owner = False
        with self._lock:
            if scope and key in self._completed:
                value = self._completed.pop(key)
                self._completed[key] = value
                return FanoutFetchResult(
                    value,
                    source,
                    request_key,
                    cycle_key,
                    fetched=False,
                    reused=True,
                )
            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                owner = True

        if not owner:
            return FanoutFetchResult(
                future.result(),
                source,
                request_key,
                cycle_key,
                fetched=False,
                reused=True,
            )

        try:
            value = fetch_fn()
        except BaseException as exc:
            future.set_exception(exc)
            with self._lock:
                self._inflight.pop(key, None)
            raise

        future.set_result(value)
        with self._lock:
            self._inflight.pop(key, None)
            if scope:
                self._completed[key] = value
                while len(self._completed) > self.max_entries:
                    self._completed.popitem(last=False)
        return FanoutFetchResult(
            value,
            source,
            request_key,
            cycle_key,
            fetched=True,
            reused=False,
        )

    def clear(self) -> None:
        with self._lock:
            self._completed.clear()

    def completed_entry_count(self) -> int:
        with self._lock:
            return len(self._completed)
