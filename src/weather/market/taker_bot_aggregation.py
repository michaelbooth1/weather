"""Bounded disk-backed row stores for taker replay and finalization.

The taker tapes are append-only evidence, but historical runs can be much too
large to decode into Python lists.  The helpers in this module keep arbitrary
row payloads in disposable SQLite scratch state while retaining the exact
source, replay, strategy, and drawdown orderings used by the materialized
implementation.

Only scratch databases should use these stores.  Journaling and synchronous
writes are deliberately disabled because the database is rebuilt from the
canonical tapes after an interruption.
"""

from __future__ import annotations

import pickle
import re
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from weather.io import iter_csv_rows
from weather.market.taker_bot_bakeoff_scoring import (
    replay_input_key,
    replay_tick_sort_key,
)
from weather.market.taker_bot_strategy_registry import (
    normalize_order_strategy_fields,
    strategy_id_for_row,
)


SQLITE_PAGE_CACHE_KIB = 2048

_ORDER_SQL = {
    "source": "source_order, sequence",
    "replay": (
        "sort_time, snapshot_id, market_id, event_slug, "
        "source_order, sequence"
    ),
    "strategy": "strategy_order, tick_order, row_order, sequence",
    "drawdown": (
        "generated_at_utc, captured_at_utc, order_id, source_order, sequence"
    ),
}


def _table_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(value))
    if not name or not name[0].isalpha():
        name = f"rows_{name}"
    return name


def _payload(value: Any) -> sqlite3.Binary:
    return sqlite3.Binary(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def _restore(value: bytes) -> Any:
    return pickle.loads(value)


def _text(value: Any) -> str:
    return str(value or "")


def _replay_metadata(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    sort_time, snapshot_id, market_id, event_slug = replay_tick_sort_key(row)
    tick_time = row.get("captured_at_utc") or row.get("generated_at_utc") or ""
    return (
        _text(sort_time),
        _text(tick_time),
        _text(snapshot_id),
        _text(market_id),
        _text(event_slug),
    )


def configure_scratch_connection(connection: sqlite3.Connection) -> None:
    """Apply the bounded, disposable-store SQLite configuration."""

    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute(f"PRAGMA cache_size=-{SQLITE_PAGE_CACHE_KIB}")


def iter_order_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield normalized taker order rows without retaining the tape."""

    for row in iter_csv_rows(path, attach_diagnostics=True):
        yield normalize_order_strategy_fields(row)


class SpilledTakerRowsView:
    """Sized, re-iterable view over a :class:`SpilledTakerRows` table."""

    is_spilled_rows = True

    def __init__(
        self,
        rows: "SpilledTakerRows",
        *,
        where_sql: str = "",
        parameters: Iterable[Any] = (),
        iteration_order: str | None = None,
    ) -> None:
        self.rows = rows
        self.where_sql = str(where_sql or "").strip()
        self.parameters = tuple(parameters)
        self.iteration_order = iteration_order or rows.iteration_order
        if self.iteration_order not in _ORDER_SQL:
            raise ValueError(f"unknown taker row iteration order: {self.iteration_order!r}")

    @property
    def connection(self) -> sqlite3.Connection:
        return self.rows.connection

    @property
    def table(self) -> str:
        return self.rows.table

    @property
    def _where_clause(self) -> str:
        return f" WHERE {self.where_sql}" if self.where_sql else ""

    @property
    def _order_clause(self) -> str:
        return _ORDER_SQL[self.iteration_order]

    def __len__(self) -> int:
        found = self.connection.execute(
            f"SELECT COUNT(*) FROM {self.table}{self._where_clause}",
            self.parameters,
        ).fetchone()
        return int(found[0]) if found else 0

    def __bool__(self) -> bool:
        found = self.connection.execute(
            f"SELECT 1 FROM {self.table}{self._where_clause} LIMIT 1",
            self.parameters,
        ).fetchone()
        return found is not None

    def __iter__(self) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table}{self._where_clause} "
            f"ORDER BY {self._order_clause}",
            self.parameters,
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def iter_with_sequence(self) -> Iterator[tuple[int, dict[str, Any]]]:
        cursor = self.connection.execute(
            f"SELECT source_order, payload FROM {self.table}{self._where_clause} "
            f"ORDER BY {self._order_clause}",
            self.parameters,
        )
        for source_order, payload in cursor:
            yield int(source_order), _restore(payload)

    def materialize(self) -> list[dict[str, Any]]:
        return list(self)


class SpilledTakerRows:
    """Arbitrary taker rows stored as BLOBs with exact indexed order metadata."""

    is_spilled_rows = True

    def __init__(
        self,
        connection: sqlite3.Connection,
        table: str,
        *,
        iteration_order: str = "source",
        compute_replay_keys: bool = False,
    ) -> None:
        if iteration_order not in _ORDER_SQL:
            raise ValueError(f"unknown taker row iteration order: {iteration_order!r}")
        self.connection = connection
        self.table = _table_name(table)
        self.iteration_order = iteration_order
        self.compute_replay_keys = bool(compute_replay_keys)
        self._count = 0
        self._next_source_order = 0
        self.connection.execute(
            f"CREATE TABLE {self.table} ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_order INTEGER NOT NULL, "
            "sort_time TEXT NOT NULL, "
            "tick_time TEXT NOT NULL, "
            "snapshot_id TEXT NOT NULL, "
            "target_date TEXT NOT NULL, "
            "market_id TEXT NOT NULL, "
            "event_slug TEXT NOT NULL, "
            "strategy_order INTEGER NOT NULL, "
            "tick_order INTEGER NOT NULL, "
            "row_order INTEGER NOT NULL, "
            "generated_at_utc TEXT NOT NULL, "
            "captured_at_utc TEXT NOT NULL, "
            "order_id TEXT NOT NULL, "
            "strategy_id TEXT NOT NULL, "
            "model_variant_id TEXT NOT NULL, "
            "order_status TEXT NOT NULL, "
            "pnl_source TEXT NOT NULL, "
            "recommendation TEXT NOT NULL, "
            "replay_key TEXT NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_source ON {self.table} "
            "(source_order, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_replay ON {self.table} "
            "(sort_time, snapshot_id, market_id, event_slug, source_order, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_strategy ON {self.table} "
            "(strategy_order, tick_order, row_order, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_drawdown ON {self.table} "
            "(generated_at_utc, captured_at_utc, order_id, source_order, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_groups ON {self.table} "
            "(strategy_id, target_date, market_id, snapshot_id, source_order)"
        )

    @property
    def next_source_order(self) -> int:
        return self._next_source_order

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.view())

    def iter_with_sequence(self) -> Iterator[tuple[int, dict[str, Any]]]:
        return self.view().iter_with_sequence()

    def _record(
        self,
        row: Mapping[str, Any],
        *,
        source_order: int,
        strategy_order: int,
        tick_order: int,
        row_order: int,
        replay_key_value: str | None,
    ) -> tuple[Any, ...]:
        sort_time, tick_time, snapshot_id, market_id, event_slug = _replay_metadata(row)
        if replay_key_value is None and self.compute_replay_keys:
            replay_key_value = replay_input_key(row)
        return (
            int(source_order),
            sort_time,
            tick_time,
            snapshot_id,
            _text(row.get("target_date")),
            market_id,
            event_slug,
            int(strategy_order),
            int(tick_order),
            int(row_order),
            _text(row.get("generated_at_utc")),
            _text(row.get("captured_at_utc")),
            _text(row.get("order_id")),
            strategy_id_for_row(row),
            _text(row.get("model_variant_id") or row.get("variant_id")),
            _text(row.get("order_status")),
            _text(row.get("pnl_source")),
            _text(row.get("recommendation")),
            _text(replay_key_value),
            _payload(dict(row)),
        )

    @property
    def _insert_sql(self) -> str:
        return (
            f"INSERT INTO {self.table} ("
            "source_order, sort_time, tick_time, snapshot_id, target_date, market_id, event_slug, "
            "strategy_order, tick_order, row_order, generated_at_utc, captured_at_utc, "
            "order_id, strategy_id, model_variant_id, order_status, pnl_source, recommendation, "
            "replay_key, payload"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )

    def append(
        self,
        row: Mapping[str, Any],
        *,
        source_order: int | None = None,
        strategy_order: int = 0,
        tick_order: int = 0,
        row_order: int = 0,
        replay_key_value: str | None = None,
    ) -> int:
        order = self._next_source_order if source_order is None else int(source_order)
        self.connection.execute(
            self._insert_sql,
            self._record(
                row,
                source_order=order,
                strategy_order=strategy_order,
                tick_order=tick_order,
                row_order=row_order,
                replay_key_value=replay_key_value,
            ),
        )
        self._count += 1
        self._next_source_order = max(self._next_source_order, order + 1)
        return order

    def extend(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        strategy_order: int = 0,
        tick_order: int = 0,
    ) -> int:
        start = self._next_source_order
        consumed = 0

        def records() -> Iterator[tuple[Any, ...]]:
            nonlocal consumed
            for offset, row in enumerate(rows):
                consumed = offset + 1
                yield self._record(
                    row,
                    source_order=start + offset,
                    strategy_order=strategy_order,
                    tick_order=tick_order,
                    row_order=offset,
                    replay_key_value=None,
                )

        before = self.connection.total_changes
        self.connection.executemany(self._insert_sql, records())
        inserted = int(self.connection.total_changes - before)
        self._count += inserted
        self._next_source_order = start + consumed
        return inserted

    def view(
        self,
        *,
        where_sql: str = "",
        parameters: Iterable[Any] = (),
        iteration_order: str | None = None,
    ) -> SpilledTakerRowsView:
        return SpilledTakerRowsView(
            self,
            where_sql=where_sql,
            parameters=parameters,
            iteration_order=iteration_order,
        )

    def filtered(
        self,
        *,
        iteration_order: str | None = None,
        **values: Any,
    ) -> SpilledTakerRowsView:
        allowed = {
            "snapshot_id",
            "target_date",
            "market_id",
            "event_slug",
            "strategy_id",
            "model_variant_id",
            "order_status",
            "pnl_source",
            "recommendation",
            "replay_key",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"unsupported taker row filters: {', '.join(unknown)}")
        clauses = [f"{name} = ?" for name in values]
        return self.view(
            where_sql=" AND ".join(clauses),
            parameters=(_text(value) for value in values.values()),
            iteration_order=iteration_order,
        )

    def materialize(self) -> list[dict[str, Any]]:
        return list(self)

    def first(self) -> dict[str, Any] | None:
        found = self.connection.execute(
            f"SELECT payload FROM {self.table} ORDER BY source_order, sequence LIMIT 1"
        ).fetchone()
        return _restore(found[0]) if found else None

    def iter_benchmark_rows(
        self,
    ) -> Iterator[tuple[tuple[str, str, str, str], dict[str, Any]]]:
        """Yield rows in the legacy sorted benchmark-group order."""

        cursor = self.connection.execute(
            f"SELECT strategy_id, target_date, market_id, snapshot_id, payload "
            f"FROM {self.table} ORDER BY "
            "strategy_id, target_date, market_id, snapshot_id, source_order, sequence"
        )
        for strategy_id, target_date, market_id, snapshot_id, payload in cursor:
            yield (
                (strategy_id, target_date, market_id, snapshot_id),
                _restore(payload),
            )

    def new_sibling_store(
        self,
        suffix: str,
        *,
        iteration_order: str = "source",
    ) -> "SpilledTakerRows":
        base = _table_name(f"{self.table}_{suffix}")
        table = base
        sequence = 1
        while self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone():
            sequence += 1
            table = f"{base}_{sequence}"
        return SpilledTakerRows(
            self.connection,
            table,
            iteration_order=iteration_order,
        )


class SpilledReplayIndex:
    """First-wins replay-input index with materialized-compatible tick order."""

    is_spilled_rows = True

    def __init__(self, connection: sqlite3.Connection, table: str = "replay_inputs") -> None:
        self.connection = connection
        self.table = _table_name(table)
        self._count = 0
        self.connection.execute(
            f"CREATE TABLE {self.table} ("
            "replay_key TEXT PRIMARY KEY, "
            "source_order INTEGER NOT NULL, "
            "sort_time TEXT NOT NULL, "
            "tick_time TEXT NOT NULL, "
            "snapshot_id TEXT NOT NULL, "
            "market_id TEXT NOT NULL, "
            "event_slug TEXT NOT NULL, "
            "payload BLOB NOT NULL) WITHOUT ROWID"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_sort ON {self.table} "
            "(sort_time, snapshot_id, market_id, event_slug, source_order, replay_key)"
        )

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    @staticmethod
    def _record(
        row: Mapping[str, Any],
        source_order: int,
        replay_key_value: str | None = None,
    ) -> tuple[Any, ...]:
        key = replay_key_value or replay_input_key(row)
        sort_time, tick_time, snapshot_id, market_id, event_slug = _replay_metadata(row)
        return (
            key,
            int(source_order),
            sort_time,
            tick_time,
            snapshot_id,
            market_id,
            event_slug,
            _payload(dict(row)),
        )

    @property
    def _insert_sql(self) -> str:
        return (
            f"INSERT OR IGNORE INTO {self.table} ("
            "replay_key, source_order, sort_time, tick_time, snapshot_id, "
            "market_id, event_slug, payload"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )

    def add(
        self,
        row: Mapping[str, Any],
        *,
        source_order: int,
        replay_key_value: str | None = None,
    ) -> bool:
        before = self.connection.total_changes
        self.connection.execute(
            self._insert_sql,
            self._record(row, source_order, replay_key_value=replay_key_value),
        )
        inserted = self.connection.total_changes > before
        if inserted:
            self._count += 1
        return inserted

    def __iter__(self) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table} ORDER BY "
            "sort_time, snapshot_id, market_id, event_slug, source_order, replay_key"
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def iter_with_source_order(self) -> Iterator[tuple[int, dict[str, Any]]]:
        cursor = self.connection.execute(
            f"SELECT source_order, payload FROM {self.table} ORDER BY "
            "sort_time, snapshot_id, market_id, event_slug, source_order, replay_key"
        )
        for source_order, payload in cursor:
            yield int(source_order), _restore(payload)

    def iter_ticks(self) -> Iterator[list[dict[str, Any]]]:
        """Yield one adjacent replay tick at a time in exact legacy order."""

        current_key: tuple[str, str] | None = None
        current_rows: list[dict[str, Any]] = []
        for row in self:
            key = (
                _text(row.get("captured_at_utc") or row.get("generated_at_utc")),
                _text(row.get("snapshot_id")),
            )
            if current_key is not None and key != current_key:
                yield current_rows
                current_rows = []
            current_key = key
            current_rows.append(row)
        if current_rows:
            yield current_rows

    def materialize(self) -> list[dict[str, Any]]:
        return list(self)


def materialize_taker_value(value: Any) -> Any:
    """Recursively materialize spilled payload components for compatibility."""

    if isinstance(value, (SpilledTakerRows, SpilledTakerRowsView, SpilledReplayIndex)):
        return [materialize_taker_value(row) for row in value]
    if isinstance(value, Mapping):
        return {key: materialize_taker_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize_taker_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(materialize_taker_value(item) for item in value)
    return value


class TakerRunAggregation:
    """Own the disposable row stores for one taker run and release them together."""

    def __init__(self, scratch_root: str | Path | None = None) -> None:
        self._scratch = (
            tempfile.TemporaryDirectory(prefix="weather-taker-finalization-")
            if scratch_root is None
            else None
        )
        root = Path(self._scratch.name if self._scratch is not None else scratch_root)
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.connection = sqlite3.connect(str(root / "taker_finalization_rows.sqlite3"))
        configure_scratch_connection(self.connection)
        self._stores: dict[str, SpilledTakerRows] = {}
        self.order_rows = self.new_row_store(
            "source_orders",
            compute_replay_keys=True,
        )
        self.replay_inputs = SpilledReplayIndex(self.connection, "replay_inputs")
        self.counterfactual_rows = self.new_row_store(
            "counterfactual_orders",
            compute_replay_keys=True,
        )
        self.generated_rows = self.new_row_store(
            "generated_orders",
            iteration_order="strategy",
            compute_replay_keys=True,
        )
        self.scored_rows = self.new_row_store(
            "scored_orders",
            compute_replay_keys=True,
        )
        self.scored_counterfactual_rows = self.new_row_store(
            "scored_counterfactual_orders",
            compute_replay_keys=True,
        )
        self.budget_ledger = self.new_row_store(
            "budget_ledger",
            iteration_order="strategy",
        )
        self._closed = False

    def __enter__(self) -> "TakerRunAggregation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def new_row_store(
        self,
        name: str,
        *,
        iteration_order: str = "source",
        compute_replay_keys: bool = False,
    ) -> SpilledTakerRows:
        table = _table_name(name)
        existing = self._stores.get(table)
        if existing is not None:
            if (
                existing.iteration_order != iteration_order
                or existing.compute_replay_keys != bool(compute_replay_keys)
            ):
                raise ValueError(f"taker row store {table!r} already has different options")
            return existing
        rows = SpilledTakerRows(
            self.connection,
            table,
            iteration_order=iteration_order,
            compute_replay_keys=compute_replay_keys,
        )
        self._stores[table] = rows
        return rows

    def add_order_rows(self, rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        consumed = 0
        replay_added = 0
        for row in rows:
            source_order = self.order_rows.next_source_order
            key = replay_input_key(row)
            self.order_rows.append(
                row,
                source_order=source_order,
                replay_key_value=key,
            )
            replay_added += int(
                self.replay_inputs.add(
                    row,
                    source_order=source_order,
                    replay_key_value=key,
                )
            )
            consumed += 1
        self.connection.commit()
        return {
            "source_order_rows_added": consumed,
            "source_order_rows": len(self.order_rows),
            "replay_input_rows_added": replay_added,
            "replay_input_rows": len(self.replay_inputs),
        }

    def ingest_order_tape(self, path: str | Path) -> dict[str, Any]:
        counts = self.add_order_rows(iter_order_rows(path))
        return {"path": str(Path(path)), **counts}

    def add_counterfactual_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
    ) -> int:
        inserted = self.counterfactual_rows.extend(rows)
        self.connection.commit()
        return inserted

    def ingest_counterfactual_tape(self, path: str | Path) -> dict[str, Any]:
        inserted = self.add_counterfactual_rows(iter_order_rows(path))
        return {
            "path": str(Path(path)),
            "counterfactual_order_rows_added": inserted,
            "counterfactual_order_rows": len(self.counterfactual_rows),
        }

    def add_generated_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        strategy_order: int,
        tick_order: int,
    ) -> int:
        inserted = self.generated_rows.extend(
            rows,
            strategy_order=strategy_order,
            tick_order=tick_order,
        )
        self.connection.commit()
        return inserted

    def add_budget_ledger_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        strategy_order: int,
        tick_order: int,
    ) -> int:
        inserted = self.budget_ledger.extend(
            rows,
            strategy_order=strategy_order,
            tick_order=tick_order,
        )
        self.connection.commit()
        return inserted

    def commit(self) -> None:
        self.connection.commit()

    def materialize(self, value: Any) -> Any:
        return materialize_taker_value(value)

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            if self._scratch is not None:
                self._scratch.cleanup()
            self._closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class DeferredTakerPayload(dict):
    """Payload whose spilled arrays remain readable until explicit cleanup."""

    def __init__(self, payload: Mapping[str, Any], aggregation: TakerRunAggregation) -> None:
        super().__init__(payload)
        self._aggregation: TakerRunAggregation | None = aggregation

    def __enter__(self) -> "DeferredTakerPayload":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def materialize(self) -> dict[str, Any]:
        aggregation = self._aggregation
        if aggregation is None:
            raise RuntimeError("deferred taker payload is closed")
        return aggregation.materialize(dict(self))

    def iter_scored_rows(self) -> Iterator[dict[str, Any]]:
        """Iterate bounded scored rows while the deferred payload is open."""

        aggregation = self._aggregation
        if aggregation is None:
            raise RuntimeError("deferred taker payload is closed")
        return iter(aggregation.scored_rows)

    def close(self) -> None:
        aggregation = self._aggregation
        if aggregation is not None:
            self._aggregation = None
            aggregation.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


__all__ = [
    "DeferredTakerPayload",
    "SQLITE_PAGE_CACHE_KIB",
    "SpilledReplayIndex",
    "SpilledTakerRows",
    "SpilledTakerRowsView",
    "TakerRunAggregation",
    "configure_scratch_connection",
    "iter_order_rows",
    "materialize_taker_value",
]
