"""Restart-safe incremental persistence for the paper taker loop.

The CSV tapes remain the canonical append-only evidence.  A small SQLite
checkpoint indexes intent keys, retains the bounded set of filled rows needed
by the risk policy, and stores cumulative counters used by tick summaries.
The tape is written before its checkpoint transaction.  On restart only the
uncheckpointed byte tail is replayed into the index; already committed rows
are never reread or rescored by the ordinary tick path.
"""

from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STATE_SCHEMA_VERSION = "taker_incremental_state_v0.1"
STATE_FILENAME = "incremental_state.sqlite3"

# These are evidence budgets, not trading gates.  Breaches stay visible to the
# supervisor/fleet without changing the existing tri-state liveness decision.
DEFAULT_RESOURCE_BUDGETS = {
    "schema_version": "taker_resource_budgets_v0.1",
    "warmup_ticks": 15,
    "private_memory_max_mib": 3072.0,
    "working_set_max_mib": 2560.0,
    "post_warmup_private_slope_mib_per_hour": 16.0,
    "ordinary_tick_tape_read_max_bytes": 8 * 1024 * 1024,
    "ordinary_tick_tape_write_max_bytes": 16 * 1024 * 1024,
    "process_read_max_bytes_per_tick": 512 * 1024 * 1024,
    "process_write_max_bytes_per_tick": 128 * 1024 * 1024,
    "tick_duration_max_seconds": 55.0,
}

BENCHMARK_REFRESH_GROUP_LIMIT = 128
DERIVED_INDEX_VERSION = "refreshable_benchmark_and_no_side_dimensions_1"
PROCESS_INSTANCE_ID = uuid.uuid4().hex


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "active", "pass"}


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _strategy_id(row: dict[str, Any]) -> str:
    return str(row.get("strategy_id") or "raw_edge_control")


def _benchmark_group_parts(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _strategy_id(row),
        str(row.get("target_date") or ""),
        str(row.get("market_id") or ""),
        str(row.get("snapshot_id") or ""),
    )


def _benchmark_group_key(row: dict[str, Any]) -> str:
    return _json(_benchmark_group_parts(row))


def _benchmark_event_key(row: dict[str, Any]) -> str:
    return str(row.get("event_slug") or "") or _json(
        [str(row.get("target_date") or ""), str(row.get("market_id") or "")]
    )


def _benchmark_slice_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("strategy_id") or ""),
        str(row.get("target_date") or ""),
        str(row.get("market_id") or ""),
        str(row.get("snapshot_id") or ""),
    )


def _capture_hour_bucket(row: dict[str, Any]) -> str:
    hour = row.get("capture_hour_local")
    try:
        if hour not in (None, ""):
            return f"{int(float(hour)):02d}"
    except (TypeError, ValueError):
        pass
    value = str(row.get("captured_at_utc") or row.get("generated_at_utc") or "")
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return f"{parsed.astimezone(timezone.utc).hour:02d}Z"
        except ValueError:
            pass
    return "unknown"


def _rows_by_benchmark_group(
    rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        # Legacy/minimal tapes may not carry the group identity required by
        # market_benchmark_scoreboard.  Treating all such rows as one group
        # would grow a single JSON value without bound and still could not be
        # rescored correctly.
        if not all(
            str(row.get(field) or "")
            for field in ("target_date", "market_id", "snapshot_id")
        ):
            continue
        grouped.setdefault(_benchmark_group_key(row), []).append(dict(row))
    return grouped


def _is_filled(row: dict[str, Any]) -> bool:
    return str(row.get("order_status") or "").upper() == "FILLED"


def _is_no_side(row: dict[str, Any]) -> bool:
    return str(row.get("taker_side") or row.get("side") or "").upper() in {
        "NO",
        "NO_BUY",
        "BUY_NO",
    }


def _intent_key(row: dict[str, Any]) -> str:
    value = str(row.get("intent_key") or "")
    if value:
        return value
    # Legacy recovery should still be idempotent even if a very old row lacks
    # the modern intent key.  Hash the complete retained evidence row.
    return "legacy_" + hashlib.sha256(_json(row).encode("utf-8")).hexdigest()[:24]


def _state_file_bytes(path: Path) -> int:
    total = 0
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            total += candidate.stat().st_size
        except OSError:
            pass
    return total


def process_resource_sample() -> dict[str, Any]:
    """Return cheap current-process memory and I/O counters when available."""

    sample: dict[str, Any] = {
        "pid": os.getpid(),
        "process_instance_id": PROCESS_INSTANCE_ID,
        "sampled_at_monotonic": time.monotonic(),
    }
    if os.name != "nt":
        try:
            import resource

            # Linux reports KiB and macOS bytes.  Tests only rely on presence,
            # while the production host follows the Windows branch below.
            rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            sample["working_set_bytes"] = rss * 1024
        except (ImportError, OSError, ValueError):
            pass
        return sample

    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        kernel32.GetProcessIoCounters.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(IO_COUNTERS),
        ]
        kernel32.GetProcessIoCounters.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        memory = PROCESS_MEMORY_COUNTERS_EX()
        memory.cb = ctypes.sizeof(memory)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            sample.update(
                working_set_bytes=int(memory.WorkingSetSize),
                peak_working_set_bytes=int(memory.PeakWorkingSetSize),
                private_bytes=int(memory.PrivateUsage),
                peak_private_bytes=int(memory.PeakPagefileUsage),
            )
        counters = IO_COUNTERS()
        if kernel32.GetProcessIoCounters(handle, ctypes.byref(counters)):
            sample.update(
                process_read_bytes=int(counters.ReadTransferCount),
                process_write_bytes=int(counters.WriteTransferCount),
                process_read_operations=int(counters.ReadOperationCount),
                process_write_operations=int(counters.WriteOperationCount),
            )
    except (AttributeError, OSError, ValueError):
        pass
    return sample


def resource_diagnostics(
    start: dict[str, Any],
    end: dict[str, Any],
    *,
    elapsed_seconds: float,
    tick_number: int,
    tape_io: dict[str, Any],
    budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    budgets = {**DEFAULT_RESOURCE_BUDGETS, **(budgets or {})}
    private_bytes = end.get("private_bytes")
    working_set_bytes = end.get("working_set_bytes")
    peak_private_bytes = end.get("peak_private_bytes")
    peak_working_set_bytes = end.get("peak_working_set_bytes")
    process_read = max(
        0,
        int(end.get("process_read_bytes") or 0) - int(start.get("process_read_bytes") or 0),
    )
    process_write = max(
        0,
        int(end.get("process_write_bytes") or 0) - int(start.get("process_write_bytes") or 0),
    )
    tape_read = int(tape_io.get("tape_bytes_read") or 0)
    tape_write = int(tape_io.get("tape_bytes_written") or 0)
    recovery = bool(tape_io.get("recovery_mode"))
    process_io_available = (
        "process_read_bytes" in start
        and "process_read_bytes" in end
        and "process_write_bytes" in start
        and "process_write_bytes" in end
    )
    checks = {
        "private_memory": (
            None
            if private_bytes is None
            else private_bytes <= float(budgets["private_memory_max_mib"]) * 1024**2
        ),
        "working_set": (
            None
            if working_set_bytes is None
            else working_set_bytes <= float(budgets["working_set_max_mib"]) * 1024**2
        ),
        "peak_private_memory": (
            None
            if peak_private_bytes is None
            else peak_private_bytes <= float(budgets["private_memory_max_mib"]) * 1024**2
        ),
        "peak_working_set": (
            None
            if peak_working_set_bytes is None
            else peak_working_set_bytes <= float(budgets["working_set_max_mib"]) * 1024**2
        ),
        "tape_read": recovery or tape_read <= int(budgets["ordinary_tick_tape_read_max_bytes"]),
        "tape_write": tape_write <= int(budgets["ordinary_tick_tape_write_max_bytes"]),
        "process_read": (
            None
            if not process_io_available
            else process_read <= int(budgets["process_read_max_bytes_per_tick"])
        ),
        "process_write": (
            None
            if not process_io_available
            else process_write <= int(budgets["process_write_max_bytes_per_tick"])
        ),
        "tick_duration": elapsed_seconds <= float(budgets["tick_duration_max_seconds"]),
    }
    failed = [name for name, ok in checks.items() if ok is False]
    return {
        "schema_version": "taker_tick_resource_diagnostics_v0.1",
        "status": "WARN" if failed else "PASS",
        "advisory_only": True,
        "pid": end.get("pid") or start.get("pid"),
        "process_instance_id": (
            end.get("process_instance_id") or start.get("process_instance_id")
        ),
        "tick_number": int(tick_number),
        "observed_at_epoch": time.time(),
        "warmup": int(tick_number) <= int(budgets["warmup_ticks"]),
        "elapsed_seconds": round(float(elapsed_seconds), 6),
        "private_bytes": private_bytes,
        "working_set_bytes": working_set_bytes,
        "peak_working_set_bytes": peak_working_set_bytes,
        "peak_private_bytes": peak_private_bytes,
        "process_read_bytes": process_read,
        "process_write_bytes": process_write,
        "tape_io": tape_io,
        "budgets": budgets,
        "checks": checks,
        "failed_budgets": failed,
        "measurement_rule": (
            "memory is sampled at tick completion; tape I/O counts only incremental tape/checkpoint "
            "work; one-time legacy/tail recovery is labeled and excluded from ordinary read budget"
        ),
    }


def _empty_no_side_counts() -> dict[str, Any]:
    return {
        "no_side_row_count": 0,
        "real_no_book_row_count": 0,
        "real_no_book_depth_eligible_row_count": 0,
        "synthetic_no_book_row_count": 0,
        "stale_no_book_row_count": 0,
        "missing_depth_no_book_row_count": 0,
        "no_side_would_buy_count": 0,
        "countable_no_side_would_buy_count": 0,
        "synthetic_no_book_would_buy_count": 0,
        "stale_no_book_would_buy_count": 0,
        "settled_no_side_would_buy_count": 0,
        "settled_countable_no_side_would_buy_count": 0,
        "no_side_win_count": 0,
        "no_side_loss_count": 0,
        "no_side_spent_usdc": 0.0,
        "no_side_net_pnl_usdc": 0.0,
        "countable_no_side_net_pnl_usdc": 0.0,
        "reason_counts": {},
    }


def _update_no_side_counts(counts: dict[str, Any], row: dict[str, Any]) -> None:
    if not _is_no_side(row):
        return
    counts["no_side_row_count"] += 1
    source = str(row.get("no_book_source") or "")
    real = source == "no_token_book"
    fresh = _truthy(row.get("no_book_fresh"))
    eligible = real and _truthy(row.get("real_no_book_depth_eligible"))
    synthetic = source.startswith("synthetic")
    filled = _is_filled(row)
    settled = str(row.get("pnl_source") or "") in {"settlement", "settlement_finalized"}
    if real:
        counts["real_no_book_row_count"] += 1
    if eligible:
        counts["real_no_book_depth_eligible_row_count"] += 1
    if synthetic:
        counts["synthetic_no_book_row_count"] += 1
    if real and not fresh:
        counts["stale_no_book_row_count"] += 1
    if real and fresh and not eligible:
        counts["missing_depth_no_book_row_count"] += 1
    if filled:
        counts["no_side_would_buy_count"] += 1
        counts["no_side_spent_usdc"] += _number(row.get("total_spent_usdc"))
        counts["no_side_net_pnl_usdc"] += _number(row.get("net_pnl_usdc"))
    if filled and eligible:
        counts["countable_no_side_would_buy_count"] += 1
        counts["countable_no_side_net_pnl_usdc"] += _number(row.get("net_pnl_usdc"))
    if filled and synthetic:
        counts["synthetic_no_book_would_buy_count"] += 1
    if filled and real and not fresh:
        counts["stale_no_book_would_buy_count"] += 1
    if filled and settled:
        counts["settled_no_side_would_buy_count"] += 1
    if filled and settled and eligible:
        counts["settled_countable_no_side_would_buy_count"] += 1
    outcome = _number(row.get("settlement_outcome")) if row.get("settlement_outcome") not in (None, "") else None
    if filled and settled and outcome == 1.0:
        counts["no_side_win_count"] += 1
    elif filled and settled and outcome == 0.0:
        counts["no_side_loss_count"] += 1
    reasons = Counter(counts.get("reason_counts") or {})
    reasons[str(row.get("reason_code") or "unknown")] += 1
    counts["reason_counts"] = dict(reasons)


def _no_side_status(counts: dict[str, Any]) -> str:
    if not counts["no_side_row_count"]:
        return "BLOCK_NO_SIDE_ROWS"
    if not counts["real_no_book_row_count"]:
        return "BLOCK_NO_REAL_NO_BOOK_ROWS"
    if not counts["real_no_book_depth_eligible_row_count"]:
        return "BLOCK_REAL_NO_BOOK_DEPTH"
    if not counts["no_side_would_buy_count"]:
        return "WATCH_NO_SIDE_NO_WOULD_BUY"
    if not counts["countable_no_side_would_buy_count"]:
        return "BLOCK_SYNTHETIC_OR_STALE_NO_BOOK"
    if not counts["settled_countable_no_side_would_buy_count"]:
        return "COLLECTING_UNSETTLED_NO_SIDE"
    return "COLLECTING_SETTLED_NO_SIDE"


def _no_side_slice_payload(
    dimension: str,
    value: str,
    counts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "value": value if value not in (None, "") else "unknown",
        "no_side_row_count": int(counts.get("no_side_row_count") or 0),
        "real_no_book_row_count": int(counts.get("real_no_book_row_count") or 0),
        "real_no_book_depth_eligible_row_count": int(
            counts.get("real_no_book_depth_eligible_row_count") or 0
        ),
        "synthetic_no_book_row_count": int(counts.get("synthetic_no_book_row_count") or 0),
        "stale_no_book_row_count": int(counts.get("stale_no_book_row_count") or 0),
        "no_side_would_buy_count": int(counts.get("no_side_would_buy_count") or 0),
        "countable_no_side_would_buy_count": int(
            counts.get("countable_no_side_would_buy_count") or 0
        ),
        "settled_no_side_would_buy_count": int(
            counts.get("settled_no_side_would_buy_count") or 0
        ),
        "settled_countable_no_side_would_buy_count": int(
            counts.get("settled_countable_no_side_would_buy_count") or 0
        ),
        "win_count": int(counts.get("no_side_win_count") or 0),
        "loss_count": int(counts.get("no_side_loss_count") or 0),
        "spent_usdc": round(_number(counts.get("no_side_spent_usdc")), 6),
        "net_pnl_usdc": round(_number(counts.get("no_side_net_pnl_usdc")), 6),
        "countable_net_pnl_usdc": round(
            _number(counts.get("countable_no_side_net_pnl_usdc")),
            6,
        ),
        "delta_vs_no_trade_net_pnl_usdc": round(
            _number(counts.get("countable_no_side_net_pnl_usdc")),
            6,
        ),
    }


def _refresh_no_side_fill_scores(counts: dict[str, Any], rows: Iterable[dict[str, Any]]) -> None:
    """Refresh the score-dependent portion from the policy-bounded fill set."""

    for key in (
        "no_side_would_buy_count",
        "countable_no_side_would_buy_count",
        "synthetic_no_book_would_buy_count",
        "stale_no_book_would_buy_count",
        "settled_no_side_would_buy_count",
        "settled_countable_no_side_would_buy_count",
        "no_side_win_count",
        "no_side_loss_count",
    ):
        counts[key] = 0
    for key in (
        "no_side_spent_usdc",
        "no_side_net_pnl_usdc",
        "countable_no_side_net_pnl_usdc",
    ):
        counts[key] = 0.0
    for row in rows:
        if not _is_no_side(row) or not _is_filled(row):
            continue
        source = str(row.get("no_book_source") or "")
        real = source == "no_token_book"
        fresh = _truthy(row.get("no_book_fresh"))
        eligible = real and _truthy(row.get("real_no_book_depth_eligible"))
        synthetic = source.startswith("synthetic")
        settled = str(row.get("pnl_source") or "") in {"settlement", "settlement_finalized"}
        counts["no_side_would_buy_count"] += 1
        counts["no_side_spent_usdc"] += _number(row.get("total_spent_usdc"))
        counts["no_side_net_pnl_usdc"] += _number(row.get("net_pnl_usdc"))
        if eligible:
            counts["countable_no_side_would_buy_count"] += 1
            counts["countable_no_side_net_pnl_usdc"] += _number(row.get("net_pnl_usdc"))
        if synthetic:
            counts["synthetic_no_book_would_buy_count"] += 1
        if real and not fresh:
            counts["stale_no_book_would_buy_count"] += 1
        if settled:
            counts["settled_no_side_would_buy_count"] += 1
        if settled and eligible:
            counts["settled_countable_no_side_would_buy_count"] += 1
        outcome = _number(row.get("settlement_outcome")) if row.get("settlement_outcome") not in (None, "") else None
        if settled and outcome == 1.0:
            counts["no_side_win_count"] += 1
        elif settled and outcome == 0.0:
            counts["no_side_loss_count"] += 1


class IncrementalTakerStore:
    """Append-only tape writer and restart checkpoint for one taker run."""

    def __init__(self, run_folder: str | Path):
        self.run_folder = Path(run_folder)
        self.run_folder.mkdir(parents=True, exist_ok=True)
        self.path = self.run_folder / STATE_FILENAME
        self._state_bytes_start = _state_file_bytes(self.path)
        self._io = {
            "tape_bytes_read": 0,
            "tape_bytes_written": 0,
            "checkpoint_bytes_written": 0,
            "recovered_row_count": 0,
            "recovery_mode": False,
            "ordinary_full_history_reads": 0,
            "ordinary_full_history_rewrites": 0,
        }
        self.connection = sqlite3.connect(self.path, timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tapes (
                kind TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                columns_json TEXT NOT NULL,
                committed_bytes INTEGER NOT NULL DEFAULT 0,
                row_count INTEGER NOT NULL DEFAULT 0,
                filled_count INTEGER NOT NULL DEFAULT 0,
                last_tick_key TEXT,
                last_tick_json TEXT
            );
            CREATE TABLE IF NOT EXISTS intents (
                kind TEXT NOT NULL,
                intent_key TEXT NOT NULL,
                PRIMARY KEY (kind, intent_key)
            );
            CREATE TABLE IF NOT EXISTS filled_rows (
                kind TEXT NOT NULL,
                intent_key TEXT NOT NULL,
                row_json TEXT NOT NULL,
                PRIMARY KEY (kind, intent_key)
            );
            CREATE TABLE IF NOT EXISTS strategy_stats (
                kind TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                stale_book_rows INTEGER NOT NULL DEFAULT 0,
                source_stale_rows INTEGER NOT NULL DEFAULT 0,
                reason_counts_json TEXT NOT NULL DEFAULT '{}',
                representative_json TEXT,
                PRIMARY KEY (kind, strategy_id)
            );
            CREATE TABLE IF NOT EXISTS resource_samples (
                tick_number INTEGER PRIMARY KEY,
                observed_at_epoch REAL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS benchmark_groups (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                group_key TEXT NOT NULL,
                event_key TEXT NOT NULL,
                rows_json TEXT NOT NULL,
                score_json TEXT,
                needs_refresh INTEGER NOT NULL DEFAULT 0,
                UNIQUE(kind, group_key)
            );
            CREATE INDEX IF NOT EXISTS benchmark_groups_event_refresh
                ON benchmark_groups(kind, event_key, needs_refresh, sequence);
            CREATE TABLE IF NOT EXISTS latest_tick_rows (
                kind TEXT PRIMARY KEY,
                tick_key TEXT NOT NULL,
                rows_json TEXT NOT NULL
            );
            """
        )
        self._set_meta("schema_version", STATE_SCHEMA_VERSION)
        derived_index_version = self._get_meta("derived_index_version")
        tape_kinds = [
            str(row["kind"])
            for row in self.connection.execute("SELECT kind FROM tapes ORDER BY kind")
        ]
        if derived_index_version != DERIVED_INDEX_VERSION and tape_kinds:
            existing_required = self._get_meta("derived_reindex_required_kinds")
            self._set_meta(
                "derived_reindex_required_kinds",
                tape_kinds if existing_required is None else existing_required,
            )
        else:
            self._set_meta("derived_index_version", DERIVED_INDEX_VERSION)
            self._set_meta("derived_reindex_required_kinds", [])
        self.connection.commit()

    def close(self) -> None:
        if self.connection is None:
            return
        self.connection.commit()
        self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        self.connection.close()
        self.connection = None

    def __enter__(self) -> "IncrementalTakerStore":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _get_meta(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return _loads(row["value"], default) if row else default

    def _set_meta(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT INTO metadata(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, _json(value)),
        )

    def _ensure_tape(self, kind: str, path: Path, columns: Iterable[str]) -> sqlite3.Row:
        columns = list(columns)
        self.connection.execute(
            "INSERT OR IGNORE INTO tapes(kind, path, columns_json) VALUES(?, ?, ?)",
            (kind, str(path), _json(columns)),
        )
        row = self.connection.execute("SELECT * FROM tapes WHERE kind = ?", (kind,)).fetchone()
        if _loads(row["columns_json"], []) != columns:
            raise RuntimeError(f"{kind} incremental checkpoint column contract changed")
        return row

    def prepare_tape(self, kind: str, path: str | Path, columns: Iterable[str]) -> dict[str, Any]:
        path = Path(path)
        row = self._ensure_tape(kind, path, columns)
        committed = int(row["committed_bytes"] or 0)
        try:
            actual = path.stat().st_size
        except OSError:
            actual = 0
        if actual < committed:
            raise RuntimeError(
                f"{kind} tape shrank below its durable checkpoint: {actual} < {committed}; "
                "refusing automatic recovery"
            )
        if actual > committed:
            self._recover_tail(kind, path, list(columns), committed, actual)
        elif actual == 0:
            self._ensure_header(kind, path, list(columns))
        required_reindexes = set(
            self._get_meta("derived_reindex_required_kinds", []) or []
        )
        if kind in required_reindexes:
            self._reindex_derived_tape(kind, path, list(columns))
        return self.tape_stats(kind)

    def _reindex_derived_tape(
        self,
        kind: str,
        path: Path,
        columns: list[str],
    ) -> None:
        """Stream one tape to upgrade refreshable/dimensional derived indexes."""

        if not path.exists():
            raise RuntimeError(
                f"incremental checkpoint migration requires canonical {kind} tape {path}"
            )
        actual = path.stat().st_size
        previous_recovery_kind = self._io.get("recovery_kind")
        self._io["recovery_mode"] = True
        self._io["recovery_kind"] = (
            f"{previous_recovery_kind}_then_derived_index_migration"
            if previous_recovery_kind
            else "derived_index_migration"
        )
        self._io["tape_bytes_read"] += actual
        with self.connection:
            self.connection.execute(
                "DELETE FROM metadata WHERE key = ?",
                (f"no_side:{kind}",),
            )
            self.connection.execute(
                "DELETE FROM latest_tick_rows WHERE kind = ?",
                (kind,),
            )
            if kind == "orders":
                self.connection.execute("DELETE FROM benchmark_groups WHERE kind = 'orders'")
                self.connection.execute("DELETE FROM metadata WHERE key = 'benchmark:orders'")
                self.connection.execute(
                    "DELETE FROM metadata WHERE key = 'benchmark_event_signatures:orders'"
                )
        migrated_rows = 0
        batch: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for source in reader:
                batch.append({column: source.get(column) for column in columns})
                if len(batch) >= 256:
                    with self.connection:
                        self._upsert_benchmark_rows(kind, batch)
                        for row in batch:
                            self._update_no_side(kind, row)
                        self._update_latest_tick_rows(kind, batch)
                    migrated_rows += len(batch)
                    batch = []
            if batch:
                with self.connection:
                    self._upsert_benchmark_rows(kind, batch)
                    for row in batch:
                        self._update_no_side(kind, row)
                    self._update_latest_tick_rows(kind, batch)
                migrated_rows += len(batch)
        with self.connection:
            remaining = sorted(
                set(self._get_meta("derived_reindex_required_kinds", []) or [])
                - {kind}
            )
            self._set_meta("derived_reindex_required_kinds", remaining)
            if not remaining:
                self._set_meta("derived_index_version", DERIVED_INDEX_VERSION)
            self._set_meta(
                f"derived_reindex_completed:{kind}",
                {
                    "row_count": migrated_rows,
                    "tape_bytes_read": actual,
                },
            )
        self._io[f"{kind}_derived_reindexed_row_count"] = migrated_rows

    def _ensure_header(self, kind: str, path: Path, columns: list[str]) -> None:
        if path.exists() and path.stat().st_size:
            return
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        data = buffer.getvalue().encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self.connection.execute(
            "UPDATE tapes SET committed_bytes = ? WHERE kind = ?",
            (len(data), kind),
        )
        self.connection.commit()
        self._io["tape_bytes_written"] += len(data)

    def _recover_tail(
        self,
        kind: str,
        path: Path,
        columns: list[str],
        committed: int,
        actual: int,
    ) -> None:
        self._io["recovery_mode"] = True
        self._io["recovery_kind"] = (
            "legacy_full_stream" if committed == 0 else "uncheckpointed_tail"
        )
        self._io["tape_bytes_read"] += actual - committed
        batch: list[dict[str, Any]] = []
        if committed == 0:
            handle = path.open("r", encoding="utf-8", newline="")
            reader: Iterable[dict[str, Any]] = csv.DictReader(handle)
        else:
            with path.open("rb") as raw_handle:
                raw_handle.seek(committed)
                raw = raw_handle.read(actual - committed)
            if raw and not raw.endswith((b"\n", b"\r")):
                raise RuntimeError(f"{kind} tape has an incomplete uncheckpointed CSV tail")
            handle = None
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), fieldnames=columns)
        try:
            for source in reader:
                normalized = {column: source.get(column) for column in columns}
                batch.append(normalized)
                if len(batch) >= 256:
                    self._ingest(kind, batch, committed_bytes=None)
                    self._io["recovered_row_count"] += len(batch)
                    batch = []
            if batch:
                self._ingest(kind, batch, committed_bytes=None)
                self._io["recovered_row_count"] += len(batch)
        finally:
            if handle is not None:
                handle.close()
        self.connection.execute(
            "UPDATE tapes SET committed_bytes = ? WHERE kind = ?",
            (actual, kind),
        )
        self.connection.commit()

    def has_intent(self, kind: str, intent_key: str) -> bool:
        if not intent_key:
            return False
        return self.connection.execute(
            "SELECT 1 FROM intents WHERE kind = ? AND intent_key = ?",
            (kind, str(intent_key)),
        ).fetchone() is not None

    def _update_no_side(self, kind: str, row: dict[str, Any]) -> None:
        if not _is_no_side(row):
            return
        state = self._get_meta(
            f"no_side:{kind}",
            {
                "overall": _empty_no_side_counts(),
                "by_strategy": {},
                "by_market": {},
                "by_hour": {},
                "strategy_meta": {},
            },
        )
        overall = {**_empty_no_side_counts(), **(state.get("overall") or {})}
        state["overall"] = overall
        by_strategy = state.setdefault("by_strategy", {})
        by_market = state.setdefault("by_market", {})
        by_hour = state.setdefault("by_hour", {})
        strategy_id = _strategy_id(row)
        strategy = {
            **_empty_no_side_counts(),
            **(by_strategy.get(strategy_id) or {}),
        }
        by_strategy[strategy_id] = strategy
        market_id = str(row.get("market_id") or "unknown")
        market = {**_empty_no_side_counts(), **(by_market.get(market_id) or {})}
        by_market[market_id] = market
        hour_key = _capture_hour_bucket(row)
        hour = {**_empty_no_side_counts(), **(by_hour.get(hour_key) or {})}
        by_hour[hour_key] = hour
        state.setdefault("strategy_meta", {})[strategy_id] = {
            "strategy_family": str(row.get("strategy_family") or "unknown"),
        }
        _update_no_side_counts(overall, row)
        _update_no_side_counts(strategy, row)
        _update_no_side_counts(market, row)
        _update_no_side_counts(hour, row)
        self._set_meta(f"no_side:{kind}", state)

    def _update_last_tick(self, kind: str, row: dict[str, Any]) -> None:
        tick_key = str(row.get("generated_at_utc") or row.get("captured_at_utc") or "")
        current = self.connection.execute(
            "SELECT last_tick_key, last_tick_json FROM tapes WHERE kind = ?",
            (kind,),
        ).fetchone()
        if not current or (current["last_tick_key"] and tick_key < current["last_tick_key"]):
            return
        if tick_key != (current["last_tick_key"] or ""):
            tick = {
                "generated_at_utc": row.get("generated_at_utc"),
                "captured_at_utc": row.get("captured_at_utc"),
                "row_count": 0,
                "filled_order_count": 0,
                "spent_usdc": 0.0,
                "reason_counts": {},
                "basis": "incremental_checkpoint",
            }
        else:
            tick = _loads(current["last_tick_json"], {})
        tick["row_count"] = int(tick.get("row_count") or 0) + 1
        tick["filled_order_count"] = int(tick.get("filled_order_count") or 0) + (1 if _is_filled(row) else 0)
        tick["spent_usdc"] = round(_number(tick.get("spent_usdc")) + (_number(row.get("total_spent_usdc")) if _is_filled(row) else 0.0), 6)
        reasons = Counter(tick.get("reason_counts") or {})
        reasons[str(row.get("reason_code") or "unknown")] += 1
        tick["reason_counts"] = dict(sorted(reasons.items()))
        self.connection.execute(
            "UPDATE tapes SET last_tick_key = ?, last_tick_json = ? WHERE kind = ?",
            (tick_key, _json(tick), kind),
        )

    def _update_latest_tick_rows(
        self,
        kind: str,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        by_tick: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            tick_key = str(row.get("generated_at_utc") or row.get("captured_at_utc") or "")
            by_tick.setdefault(tick_key, []).append(dict(row))
        if not by_tick:
            return
        tick_key = max(by_tick)
        incoming = by_tick[tick_key]
        current = self.connection.execute(
            "SELECT tick_key, rows_json FROM latest_tick_rows WHERE kind = ?",
            (kind,),
        ).fetchone()
        if current and str(current["tick_key"] or "") > tick_key:
            return
        if current and str(current["tick_key"] or "") == tick_key:
            merged = list(_loads(current["rows_json"], []))
            seen = {_intent_key(row) for row in merged}
            merged.extend(row for row in incoming if _intent_key(row) not in seen)
        else:
            merged = incoming
        self.connection.execute(
            "INSERT INTO latest_tick_rows(kind, tick_key, rows_json) VALUES(?, ?, ?) "
            "ON CONFLICT(kind) DO UPDATE SET tick_key = excluded.tick_key, rows_json = excluded.rows_json",
            (kind, tick_key, _json(merged)),
        )

    def latest_rows(self, kind: str) -> list[dict[str, Any]]:
        row = self.connection.execute(
            "SELECT rows_json FROM latest_tick_rows WHERE kind = ?",
            (kind,),
        ).fetchone()
        return list(_loads(row["rows_json"], []) if row else [])

    def _upsert_benchmark_rows(
        self,
        kind: str,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        if kind != "orders":
            return
        for group_key, incoming in _rows_by_benchmark_group(rows).items():
            current = self.connection.execute(
                "SELECT rows_json, score_json FROM benchmark_groups WHERE kind = ? AND group_key = ?",
                (kind, group_key),
            ).fetchone()
            merged = list(_loads(current["rows_json"], []) if current else [])
            seen = {_intent_key(row) for row in merged}
            additions = [row for row in incoming if _intent_key(row) not in seen]
            if additions:
                merged.extend(additions)
            if current and not additions:
                continue
            event_key = _benchmark_event_key((merged or incoming)[0])
            self.connection.execute(
                """
                INSERT INTO benchmark_groups(
                    kind, group_key, event_key, rows_json, score_json, needs_refresh
                ) VALUES(?, ?, ?, ?, NULL, 0)
                ON CONFLICT(kind, group_key) DO UPDATE SET
                    event_key = excluded.event_key,
                    rows_json = excluded.rows_json,
                    needs_refresh = CASE
                        WHEN benchmark_groups.score_json IS NULL THEN benchmark_groups.needs_refresh
                        ELSE 1
                    END
                """,
                (kind, group_key, event_key, _json(merged)),
            )

    def _apply_benchmark_groups(
        self,
        kind: str,
        groups: Iterable[dict[str, Any]],
    ) -> int:
        groups = list(groups or [])
        if kind != "orders" or not groups:
            return 0
        current_payload = self.benchmark(kind)
        applied = 0
        for group in groups:
            rows = list(group.get("rows") or [])
            payload = dict(group.get("payload") or {})
            if not rows or not payload:
                continue
            self._upsert_benchmark_rows(kind, rows)
            group_key = str(group.get("group_key") or _benchmark_group_key(rows[0]))
            current = self.connection.execute(
                "SELECT score_json FROM benchmark_groups WHERE kind = ? AND group_key = ?",
                (kind, group_key),
            ).fetchone()
            old_payload = _loads(current["score_json"], {}) if current else {}
            if _json(old_payload) == _json(payload):
                self.connection.execute(
                    "UPDATE benchmark_groups SET rows_json = ?, needs_refresh = 0 "
                    "WHERE kind = ? AND group_key = ?",
                    (_json(rows), kind, group_key),
                )
                continue
            if old_payload:
                current_payload = replace_benchmark_payload(current_payload, old_payload, payload)
            else:
                current_payload = merge_benchmark_payload(current_payload, payload)
            self.connection.execute(
                "UPDATE benchmark_groups SET rows_json = ?, score_json = ?, needs_refresh = 0 "
                "WHERE kind = ? AND group_key = ?",
                (_json(rows), _json(payload), kind, group_key),
            )
            applied += 1
        if applied:
            self._set_meta(f"benchmark:{kind}", current_payload)
        return applied

    def apply_benchmark_groups(
        self,
        kind: str,
        groups: Iterable[dict[str, Any]],
    ) -> int:
        with self.connection:
            return self._apply_benchmark_groups(kind, groups)

    def pending_benchmark_groups(
        self,
        kind: str,
        *,
        limit: int = BENCHMARK_REFRESH_GROUP_LIMIT,
        exclude_event_keys: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded = sorted({str(value) for value in (exclude_event_keys or []) if value})
        exclusion_sql = ""
        parameters: list[Any] = [kind]
        if excluded:
            placeholders = ",".join("?" for _value in excluded)
            exclusion_sql = f" AND event_key NOT IN ({placeholders})"
            parameters.extend(excluded)
        parameters.append(max(1, int(limit)))
        return [
            {
                "group_key": row["group_key"],
                "event_key": row["event_key"],
                "rows": list(_loads(row["rows_json"], [])),
            }
            for row in self.connection.execute(
                "SELECT group_key, event_key, rows_json FROM benchmark_groups "
                "WHERE kind = ? AND (score_json IS NULL OR needs_refresh = 1) "
                f"{exclusion_sql} ORDER BY sequence LIMIT ?",
                parameters,
            )
        ]

    def benchmark_pending_count(self, kind: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM benchmark_groups "
            "WHERE kind = ? AND (score_json IS NULL OR needs_refresh = 1)",
            (kind,),
        ).fetchone()
        return int(row["count"] or 0)

    def benchmark_probe_rows(self, kind: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in self.connection.execute(
            """
            SELECT candidate.rows_json
            FROM benchmark_groups AS candidate
            WHERE candidate.kind = ?
              AND candidate.sequence = (
                  SELECT MAX(latest.sequence)
                  FROM benchmark_groups AS latest
                  WHERE latest.kind = candidate.kind
                    AND latest.event_key = candidate.event_key
              )
            ORDER BY candidate.event_key
            """,
            (kind,),
        ):
            rows.extend(_loads(row["rows_json"], []))
        return rows

    def mark_benchmark_event_signatures(
        self,
        kind: str,
        scored_probe_rows: Iterable[dict[str, Any]],
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in scored_probe_rows:
            grouped.setdefault(_benchmark_event_key(row), []).append(dict(row))
        signatures = dict(self._get_meta(f"benchmark_event_signatures:{kind}", {}) or {})
        changed: list[str] = []
        unavailable_after_finalized: list[str] = []
        with self.connection:
            for event_key, rows in grouped.items():
                explicit = rows[0].get("_benchmark_settlement_signature")
                if isinstance(explicit, dict):
                    signature_source = explicit
                    settlement_present = bool(explicit.get("present"))
                else:
                    signature_source = sorted(
                        (
                            str(row.get("range_label") or ""),
                            str(row.get("bin_kind") or ""),
                            str(row.get("bin_value") or ""),
                            str(row.get("bin_value_hi") or ""),
                            row.get("settlement_outcome"),
                        )
                        for row in rows
                    )
                    settlement_present = None
                signature = hashlib.sha256(
                    _json(signature_source).encode("utf-8")
                ).hexdigest()
                previous_record = signatures.get(event_key)
                if isinstance(previous_record, dict):
                    previous = previous_record.get("digest")
                    previous_present = previous_record.get("settlement_present")
                else:
                    previous = previous_record
                    previous_present = None
                # A temporarily unavailable label must not roll a finalized
                # event back to the unresolved benchmark generation.
                if previous_present is True and settlement_present is False:
                    unavailable_after_finalized.append(event_key)
                    continue
                # The first signature must also force a bounded re-score.  The
                # group payload may have been committed just before a label
                # arrived (or before a crash), so merely recording this first
                # observation would leave that generation stale forever.
                if previous is None or previous != signature:
                    self.connection.execute(
                        "UPDATE benchmark_groups SET needs_refresh = 1 "
                        "WHERE kind = ? AND event_key = ?",
                        (kind, event_key),
                    )
                    if previous is not None:
                        changed.append(event_key)
                signatures[event_key] = {
                    "digest": signature,
                    "settlement_present": settlement_present,
                }
            self._set_meta(f"benchmark_event_signatures:{kind}", signatures)
        return {
            "changed_events": changed,
            "unavailable_after_finalized_events": unavailable_after_finalized,
        }

    def pending_tick(self) -> dict[str, Any]:
        return dict(self._get_meta("pending_tick", {}) or {})

    def save_pending_tick(self, payload: dict[str, Any]) -> None:
        self._set_meta("pending_tick", payload)
        self.connection.commit()

    def clear_pending_tick(self) -> None:
        self.connection.execute("DELETE FROM metadata WHERE key = 'pending_tick'")
        self.connection.commit()

    def _ingest(
        self,
        kind: str,
        rows: Iterable[dict[str, Any]],
        *,
        committed_bytes: int | None,
        benchmark: dict[str, Any] | None = None,
        benchmark_groups: Iterable[dict[str, Any]] | None = None,
    ) -> int:
        inserted = 0
        inserted_rows: list[dict[str, Any]] = []
        with self.connection:
            for row in rows:
                key = _intent_key(row)
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO intents(kind, intent_key) VALUES(?, ?)",
                    (kind, key),
                )
                if cursor.rowcount != 1:
                    continue
                inserted += 1
                inserted_rows.append(dict(row))
                filled = _is_filled(row)
                if filled:
                    self.connection.execute(
                        "INSERT OR REPLACE INTO filled_rows(kind, intent_key, row_json) VALUES(?, ?, ?)",
                        (kind, key, _json(row)),
                    )
                strategy_id = _strategy_id(row)
                existing = self.connection.execute(
                    "SELECT * FROM strategy_stats WHERE kind = ? AND strategy_id = ?",
                    (kind, strategy_id),
                ).fetchone()
                reasons = Counter(_loads(existing["reason_counts_json"], {}) if existing else {})
                reasons[str(row.get("reason_code") or "unknown")] += 1
                stale = int(existing["stale_book_rows"] or 0) if existing else 0
                source = int(existing["source_stale_rows"] or 0) if existing else 0
                if row.get("reason_code") == "NO_TRADE_STALE_BOOK":
                    stale += 1
                if row.get("reason_code") in {"NO_TRADE_SOURCE_STALE", "NO_TRADE_EARLY_HOUR_SOURCE_STATE"}:
                    source += 1
                representative = existing["representative_json"] if existing else None
                if not representative or not filled:
                    representative = _json(row)
                self.connection.execute(
                    """
                    INSERT INTO strategy_stats(
                        kind, strategy_id, row_count, stale_book_rows, source_stale_rows,
                        reason_counts_json, representative_json
                    ) VALUES(?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(kind, strategy_id) DO UPDATE SET
                        row_count = strategy_stats.row_count + 1,
                        stale_book_rows = excluded.stale_book_rows,
                        source_stale_rows = excluded.source_stale_rows,
                        reason_counts_json = excluded.reason_counts_json,
                        representative_json = excluded.representative_json
                    """,
                    (kind, strategy_id, stale, source, _json(dict(reasons)), representative),
                )
                self.connection.execute(
                    "UPDATE tapes SET row_count = row_count + 1, filled_count = filled_count + ? WHERE kind = ?",
                    (1 if filled else 0, kind),
                )
                self._update_last_tick(kind, row)
                self._update_no_side(kind, row)
            self._update_latest_tick_rows(kind, inserted_rows)
            self._upsert_benchmark_rows(kind, inserted_rows)
            if benchmark_groups and inserted:
                self._apply_benchmark_groups(kind, benchmark_groups)
            elif benchmark and inserted:
                current = self._get_meta(f"benchmark:{kind}", {})
                self._set_meta(f"benchmark:{kind}", merge_benchmark_payload(current, benchmark))
            if committed_bytes is not None:
                self.connection.execute(
                    "UPDATE tapes SET committed_bytes = ? WHERE kind = ?",
                    (int(committed_bytes), kind),
                )
        return inserted

    def append_rows(
        self,
        kind: str,
        path: str | Path,
        columns: Iterable[str],
        rows: Iterable[dict[str, Any]],
        *,
        benchmark: dict[str, Any] | None = None,
        benchmark_groups: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        path = Path(path)
        columns = list(columns)
        self.prepare_tape(kind, path, columns)
        materialized = list(rows)
        if not materialized:
            return {"row_count": 0, "bytes_written": 0, "path": str(path)}
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        for row in materialized:
            writer.writerow({column: row.get(column) for column in columns})
        data = buffer.getvalue().encode("utf-8")
        with path.open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        committed = path.stat().st_size
        inserted = self._ingest(
            kind,
            materialized,
            committed_bytes=committed,
            benchmark=benchmark,
            benchmark_groups=benchmark_groups,
        )
        if inserted != len(materialized):
            raise RuntimeError(
                f"{kind} append contained {len(materialized) - inserted} duplicate checkpoint intent(s); "
                "refusing ambiguous evidence"
            )
        self._io["tape_bytes_written"] += len(data)
        return {"row_count": inserted, "bytes_written": len(data), "path": str(path)}

    def filled_rows(self, kind: str) -> list[dict[str, Any]]:
        return [
            _loads(row["row_json"], {})
            for row in self.connection.execute(
                "SELECT row_json FROM filled_rows WHERE kind = ? ORDER BY intent_key",
                (kind,),
            )
        ]

    def representative_rows(self, kind: str) -> list[dict[str, Any]]:
        return [
            _loads(row["representative_json"], {})
            for row in self.connection.execute(
                "SELECT representative_json FROM strategy_stats WHERE kind = ? ORDER BY strategy_id",
                (kind,),
            )
            if row["representative_json"]
        ]

    def strategy_stats(self, kind: str) -> dict[str, dict[str, Any]]:
        return {
            row["strategy_id"]: {
                "row_count": int(row["row_count"] or 0),
                "stale_book_rows": int(row["stale_book_rows"] or 0),
                "source_stale_rows": int(row["source_stale_rows"] or 0),
                "reason_counts": dict(sorted(_loads(row["reason_counts_json"], {}).items())),
            }
            for row in self.connection.execute(
                "SELECT * FROM strategy_stats WHERE kind = ? ORDER BY strategy_id",
                (kind,),
            )
        }

    def tape_stats(self, kind: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM tapes WHERE kind = ?", (kind,)).fetchone()
        if not row:
            return {"row_count": 0, "filled_count": 0, "committed_bytes": 0, "last_nonzero_scored_tick": {}}
        reasons: Counter[str] = Counter()
        for strategy in self.strategy_stats(kind).values():
            reasons.update(strategy.get("reason_counts") or {})
        return {
            "row_count": int(row["row_count"] or 0),
            "filled_count": int(row["filled_count"] or 0),
            "committed_bytes": int(row["committed_bytes"] or 0),
            "reason_counts": dict(sorted(reasons.items())),
            "last_nonzero_scored_tick": _loads(row["last_tick_json"], {}),
        }

    def tape_integrity(self, kind: str, row_kind: str) -> dict[str, Any]:
        stats = self.tape_stats(kind)
        row = self.connection.execute("SELECT path FROM tapes WHERE kind = ?", (kind,)).fetchone()
        return {
            "status": "PASS",
            "path": row["path"] if row else None,
            "row_kind": row_kind,
            "expected_rows": stats["row_count"],
            "actual_rows": stats["row_count"],
            "checkpoint_bytes": stats["committed_bytes"],
            "verification_basis": "incremental_checkpoint_and_append_transaction",
            "detail": f"{row_kind} append checkpoint matches cumulative row count",
        }

    def benchmark(self, kind: str) -> dict[str, Any]:
        return self._get_meta(f"benchmark:{kind}", {})

    def no_side_summary(
        self,
        kind: str,
        *,
        scored_filled_rows: Iterable[dict[str, Any]] | None = None,
        pnl_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self._get_meta(
            f"no_side:{kind}",
            {
                "overall": _empty_no_side_counts(),
                "by_strategy": {},
                "by_market": {},
                "by_hour": {},
                "strategy_meta": {},
            },
        )
        overall = {**_empty_no_side_counts(), **(state.get("overall") or {})}
        by_strategy = {
            strategy_id: {**_empty_no_side_counts(), **counts}
            for strategy_id, counts in (state.get("by_strategy") or {}).items()
        }
        by_market = {
            value: {**_empty_no_side_counts(), **counts}
            for value, counts in (state.get("by_market") or {}).items()
        }
        by_hour = {
            value: {**_empty_no_side_counts(), **counts}
            for value, counts in (state.get("by_hour") or {}).items()
        }
        if scored_filled_rows is not None:
            scored_filled_rows = list(scored_filled_rows)
            _refresh_no_side_fill_scores(overall, scored_filled_rows)
            filled_by_strategy: dict[str, list[dict[str, Any]]] = {}
            filled_by_market: dict[str, list[dict[str, Any]]] = {}
            filled_by_hour: dict[str, list[dict[str, Any]]] = {}
            for row in scored_filled_rows:
                filled_by_strategy.setdefault(_strategy_id(row), []).append(row)
                filled_by_market.setdefault(str(row.get("market_id") or "unknown"), []).append(row)
                filled_by_hour.setdefault(_capture_hour_bucket(row), []).append(row)
            for strategy_id, counts in by_strategy.items():
                _refresh_no_side_fill_scores(counts, filled_by_strategy.get(strategy_id) or [])
            for value, counts in by_market.items():
                _refresh_no_side_fill_scores(counts, filled_by_market.get(value) or [])
            for value, counts in by_hour.items():
                _refresh_no_side_fill_scores(counts, filled_by_hour.get(value) or [])
        for key in (
            "no_side_spent_usdc",
            "no_side_net_pnl_usdc",
            "countable_no_side_net_pnl_usdc",
        ):
            overall[key] = round(_number(overall.get(key)), 6)
        pnl_by_strategy = {
            str(row.get("strategy_id")): row
            for row in (pnl_payload or {}).get("by_strategy") or []
            if row.get("strategy_id")
        }
        strategy_meta = state.get("strategy_meta") or {}
        strategy_rows = []
        for strategy_id, counts in sorted(by_strategy.items()):
            row = _no_side_slice_payload("by_strategy", strategy_id, counts)
            pnl_row = pnl_by_strategy.get(strategy_id) or {}
            market_top = pnl_row.get("market_benchmark_market_top_net_pnl_usdc")
            strategy_net = pnl_row.get("net_pnl_usdc")
            row.update(
                strategy_id=strategy_id,
                strategy_family=(strategy_meta.get(strategy_id) or {}).get("strategy_family") or "unknown",
                strategy_market_top_net_pnl_usdc=market_top,
                strategy_delta_vs_market_top_net_pnl_usdc=(
                    round(_number(strategy_net) - _number(market_top), 6)
                    if strategy_net not in (None, "") and market_top not in (None, "")
                    else None
                ),
                settlement_promotion_gate_status=pnl_row.get("settlement_promotion_gate_status") or "",
                settlement_promotion_failed_gates=pnl_row.get("settlement_promotion_failed_gates") or [],
                status=_no_side_status(counts),
            )
            strategy_rows.append(row)
        market_rows = [
            _no_side_slice_payload("by_market", value, counts)
            for value, counts in sorted(by_market.items())
        ]
        hour_rows = [
            _no_side_slice_payload("by_hour", value, counts)
            for value, counts in sorted(by_hour.items())
        ]
        overall.update(
            status=_no_side_status(overall),
            candidate_basis="NO-side rows generated by two_sided/fade arm",
            countable_evidence_basis="real no-token book depth only",
            synthetic_only_countable=False,
            delta_vs_no_trade_net_pnl_usdc=overall["countable_no_side_net_pnl_usdc"],
            by_strategy=strategy_rows,
            by_market=market_rows,
            by_hour=hour_rows,
            slices={"by_market": market_rows, "by_hour": hour_rows},
            persistence_basis="incremental_checkpoint",
        )
        return overall

    def tick_number(self) -> int:
        value = int(self._get_meta("tick_number", 0) or 0) + 1
        self._set_meta("tick_number", value)
        self.connection.commit()
        return value

    def io_diagnostics(self) -> dict[str, Any]:
        self.connection.commit()
        current = _state_file_bytes(self.path)
        self._io["checkpoint_bytes_written"] = max(0, current - self._state_bytes_start)
        self._io["checkpoint_path"] = str(self.path)
        self._io["checkpoint_size_bytes"] = current
        return dict(self._io)

    def record_resource_diagnostics(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Add a restart-safe post-warmup slope using only two bounded samples."""

        history = self._get_meta("resource_history", {}) or {}
        tick_number = int(payload.get("tick_number") or 0)
        warmup_ticks = int((payload.get("budgets") or {}).get("warmup_ticks") or 0)
        observed = _number(payload.get("observed_at_epoch"))
        private_bytes = payload.get("private_bytes")
        pid = payload.get("pid")
        process_instance_id = payload.get("process_instance_id")
        previous_pid = history.get("pid")
        previous_instance_id = history.get("process_instance_id")
        sample_count = int(history.get("sample_count") or 0) + 1
        restart_count = int(history.get("process_restart_count") or 0)
        first_process_sample = bool(
            (process_instance_id is not None or pid is not None)
            and previous_instance_id is None
            and previous_pid is None
        )
        identity_changed = bool(
            first_process_sample
            or (
                process_instance_id is not None
                and previous_instance_id is not None
                and previous_instance_id != process_instance_id
            )
            or (
                pid is not None
                and previous_pid is not None
                and previous_pid != pid
            )
        )
        if identity_changed:
            if previous_instance_id is not None or previous_pid is not None:
                restart_count += 1
            history = {
                "sample_count": sample_count,
                "process_sample_count": 1,
                "process_restart_count": restart_count,
                "pid": pid,
                "process_instance_id": process_instance_id,
            }
        else:
            history["sample_count"] = sample_count
            history["process_restart_count"] = restart_count
            if pid is not None:
                history["pid"] = pid
                if process_instance_id is not None:
                    history["process_instance_id"] = process_instance_id
                history["process_sample_count"] = int(history.get("process_sample_count") or 0) + 1
            else:
                # Synthetic/non-Windows callers historically keyed warmup to the
                # durable tick number; retain that behavior when no PID exists.
                history["process_sample_count"] = tick_number
        process_sample_count = int(history.get("process_sample_count") or 0)
        payload["warmup"] = process_sample_count <= warmup_ticks
        if private_bytes is not None and observed > 0 and process_sample_count > warmup_ticks:
            if history.get("baseline_epoch") is None:
                history["baseline_epoch"] = observed
                history["baseline_private_bytes"] = int(private_bytes)
            elapsed_hours = max(
                0.0,
                (observed - _number(history.get("baseline_epoch"))) / 3600.0,
            )
            if elapsed_hours > 0:
                slope = (
                    (int(private_bytes) - int(history.get("baseline_private_bytes") or 0))
                    / 1024**2
                    / elapsed_hours
                )
                payload["post_warmup_private_slope_mib_per_hour"] = round(slope, 6)
                limit = float(
                    (payload.get("budgets") or {}).get("post_warmup_private_slope_mib_per_hour")
                    or DEFAULT_RESOURCE_BUDGETS["post_warmup_private_slope_mib_per_hour"]
                )
                payload.setdefault("checks", {})["post_warmup_private_slope"] = slope <= limit
                if slope > limit:
                    failed = payload.setdefault("failed_budgets", [])
                    if "post_warmup_private_slope" not in failed:
                        failed.append("post_warmup_private_slope")
                    payload["status"] = "WARN"
            history["last_epoch"] = observed
            history["last_private_bytes"] = int(private_bytes)
        payload["resource_history"] = {
            "sample_count": history["sample_count"],
            "process_sample_count": process_sample_count,
            "process_restart_count": restart_count,
            "pid": history.get("pid"),
            "process_instance_id": history.get("process_instance_id"),
            "baseline_tick": warmup_ticks + 1,
            "baseline_epoch": history.get("baseline_epoch"),
            "last_epoch": history.get("last_epoch"),
        }
        self._set_meta("resource_history", history)
        self._set_meta("latest_resource_diagnostics", payload)
        self.connection.execute(
            "INSERT OR REPLACE INTO resource_samples(tick_number, observed_at_epoch, payload_json) "
            "VALUES(?, ?, ?)",
            (
                tick_number,
                observed if observed > 0 else None,
                _json(payload),
            ),
        )
        self.connection.commit()
        return payload

    def resource_sample_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS count FROM resource_samples").fetchone()
        return int(row["count"] or 0)


def merge_benchmark_payload(current: dict[str, Any], tick: dict[str, Any]) -> dict[str, Any]:
    """Merge disjoint, intent-deduplicated snapshot benchmark groups."""

    if not current:
        result = json.loads(json.dumps(tick or {}))
        if result:
            result["persistence_basis"] = "incremental_disjoint_snapshot_groups"
            result["slices"] = list((tick or {}).get("slices") or [])[-32:]
            for row in result.get("by_strategy") or []:
                row["recommendations"] = list(row.get("recommendations") or [])[-8:]
            result["slice_retention"] = "latest_32; cumulative summary and by_strategy are exact"
        return result
    if not tick or not (tick.get("slices") or []):
        return current
    result = json.loads(json.dumps(current))
    summary = result.setdefault("summary", {})
    tick_summary = tick.get("summary") or {}
    for key in (
        "opportunity_count",
        "market_smarter_slice_count",
        "no_trade_recommendation_count",
    ):
        summary[key] = int(summary.get(key) or 0) + int(tick_summary.get(key) or 0)
    for key in ("traded_pnl_usdc", "avoided_loss_usdc", "missed_gain_usdc"):
        summary[key] = round(_number(summary.get(key)) + _number(tick_summary.get(key)), 6)
    by_id = {row.get("strategy_id"): row for row in result.get("by_strategy") or []}
    for incoming in tick.get("by_strategy") or []:
        strategy_id = incoming.get("strategy_id")
        target = by_id.setdefault(strategy_id, {"strategy_id": strategy_id, "recommendations": []})
        for key in (
            "opportunity_count",
            "settled_opportunity_count",
            "market_smarter_slice_count",
            "model_beats_market_count",
            "model_beats_no_trade_count",
        ):
            target[key] = int(target.get(key) or 0) + int(incoming.get(key) or 0)
        for key in (
            "traded_pnl_usdc",
            "model_top_net_pnl_usdc",
            "market_top_net_pnl_usdc",
            "no_trade_net_pnl_usdc",
            "avoided_loss_usdc",
            "missed_gain_usdc",
        ):
            target[key] = round(_number(target.get(key)) + _number(incoming.get(key)), 6)
        target["status"] = (
            "BLOCK_MARKET_SMARTER"
            if int(target.get("market_smarter_slice_count") or 0) > 0
            else "PASS"
        )
        target["recommendations"] = [
            *(target.get("recommendations") or []),
            *(incoming.get("recommendations") or []),
        ][-8:]
    result["by_strategy"] = [by_id[key] for key in sorted(by_id)]
    summary["strategy_count"] = len(result["by_strategy"])
    result["slices"] = [
        *(result.get("slices") or []),
        *(tick.get("slices") or []),
    ][-32:]
    result["persistence_basis"] = "incremental_disjoint_snapshot_groups"
    result["slice_retention"] = "latest_32; cumulative summary and by_strategy are exact"
    return result


def replace_benchmark_payload(
    current: dict[str, Any],
    previous_group: dict[str, Any],
    refreshed_group: dict[str, Any],
) -> dict[str, Any]:
    """Replace one benchmark group's additive contribution without a history scan."""

    result = json.loads(json.dumps(current or {}))
    summary = result.setdefault("summary", {})
    previous_summary = previous_group.get("summary") or {}
    for key in (
        "opportunity_count",
        "market_smarter_slice_count",
        "no_trade_recommendation_count",
    ):
        summary[key] = max(0, int(summary.get(key) or 0) - int(previous_summary.get(key) or 0))
    for key in ("traded_pnl_usdc", "avoided_loss_usdc", "missed_gain_usdc"):
        summary[key] = round(_number(summary.get(key)) - _number(previous_summary.get(key)), 6)

    previous_slice_keys = {
        _benchmark_slice_key(row)
        for row in previous_group.get("slices") or []
    }
    result["slices"] = [
        row
        for row in result.get("slices") or []
        if _benchmark_slice_key(row) not in previous_slice_keys
    ]
    by_id = {
        row.get("strategy_id"): row
        for row in result.get("by_strategy") or []
    }
    for outgoing in previous_group.get("by_strategy") or []:
        strategy_id = outgoing.get("strategy_id")
        target = by_id.get(strategy_id)
        if target is None:
            continue
        for key in (
            "opportunity_count",
            "settled_opportunity_count",
            "market_smarter_slice_count",
            "model_beats_market_count",
            "model_beats_no_trade_count",
        ):
            target[key] = max(0, int(target.get(key) or 0) - int(outgoing.get(key) or 0))
        for key in (
            "traded_pnl_usdc",
            "model_top_net_pnl_usdc",
            "market_top_net_pnl_usdc",
            "no_trade_net_pnl_usdc",
            "avoided_loss_usdc",
            "missed_gain_usdc",
        ):
            target[key] = round(_number(target.get(key)) - _number(outgoing.get(key)), 6)
        target["recommendations"] = [
            row
            for row in target.get("recommendations") or []
            if _benchmark_slice_key(row) not in previous_slice_keys
        ]
        target["status"] = (
            "BLOCK_MARKET_SMARTER"
            if int(target.get("market_smarter_slice_count") or 0) > 0
            else "PASS"
        )
    result["by_strategy"] = [by_id[key] for key in sorted(by_id)]
    summary["strategy_count"] = len(result["by_strategy"])
    return merge_benchmark_payload(result, refreshed_group)
