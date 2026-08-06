"""Disk-backed run aggregation for maker-paper scoring.

The scheduled maker scorer consumes a bounded selection of run folders, but a
single selection can contain hundreds of MiB of quote-intent CSVs.  This module
keeps only one run's decoded rows in memory at a time and spills the exact
ordered row populations needed by the existing scorer to SQLite.
"""

from __future__ import annotations

import gc
import pickle
import re
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from weather.market.mm_paper_scoring import (
    attach_reward_estimates,
    load_model_variant_quote_rows,
    load_quote_rows,
    quote_legs,
)


def _table_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(value))
    if not name or not name[0].isalpha():
        name = f"rows_{name}"
    return name


def _payload(value: Any) -> sqlite3.Binary:
    return sqlite3.Binary(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


def _restore(value: bytes) -> Any:
    return pickle.loads(value)


def _sort_timestamp(row: dict[str, Any], explicit: Any = None) -> float:
    value = explicit if explicit is not None else row.get("quote_time")
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    return 0.0


class SpilledRows:
    """Re-iterable ordered rows whose payloads live in SQLite, not RAM."""

    is_spilled_rows = True

    def __init__(
        self,
        connection: sqlite3.Connection,
        table: str,
        *,
        iteration_order: str = "source",
    ) -> None:
        self.connection = connection
        self.table = _table_name(table)
        self.iteration_order = iteration_order
        self._count = 0
        self.connection.execute(
            f"CREATE TABLE {self.table} ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_order INTEGER NOT NULL, "
            "sort_time REAL NOT NULL, "
            "sort_id TEXT NOT NULL, "
            "quote_id TEXT NOT NULL, "
            "leg_id TEXT NOT NULL, "
            "event_slug TEXT NOT NULL, "
            "run_id TEXT NOT NULL, "
            "token_id TEXT NOT NULL, "
            "side TEXT NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_quote_id ON {self.table} "
            "(quote_id, source_order, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_sort ON {self.table} "
            "(sort_time, sort_id, sequence)"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_expiry ON {self.table} "
            "(run_id, event_slug, token_id, side, sort_time, sequence)"
        )

    @property
    def _order_sql(self) -> str:
        if self.iteration_order == "sorted":
            return "sort_time, sort_id, sequence"
        return "sequence"

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    @staticmethod
    def _record(
        row: dict[str, Any],
        source_order: int,
        sort_time: Any = None,
        sort_id: str | None = None,
    ) -> tuple[Any, ...]:
        return (
            int(source_order),
            _sort_timestamp(row, sort_time),
            str(sort_id if sort_id is not None else row.get("leg_id") or ""),
            str(row.get("quote_id") or row.get("_quote_id") or ""),
            str(row.get("leg_id") or ""),
            str(row.get("event_slug") or ""),
            str(row.get("run_id") or ""),
            str(row.get("clob_token_id") or ""),
            str(row.get("side") or ""),
            _payload(row),
        )

    def extend(self, rows: Iterable[dict[str, Any]]) -> None:
        start = self._count

        def records() -> Iterator[tuple[Any, ...]]:
            for offset, row in enumerate(rows):
                yield self._record(row, start + offset)

        before = self.connection.total_changes
        self.connection.executemany(
            f"INSERT INTO {self.table} ("
            "source_order, sort_time, sort_id, quote_id, leg_id, event_slug, "
            "run_id, token_id, side, payload"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            records(),
        )
        self._count += self.connection.total_changes - before

    def append(
        self,
        row: dict[str, Any],
        *,
        source_order: int | None = None,
        sort_time: Any = None,
        sort_id: str | None = None,
    ) -> None:
        order = self._count if source_order is None else int(source_order)
        self.connection.execute(
            f"INSERT INTO {self.table} ("
            "source_order, sort_time, sort_id, quote_id, leg_id, event_slug, "
            "run_id, token_id, side, payload"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            self._record(row, order, sort_time=sort_time, sort_id=sort_id),
        )
        self._count += 1

    def __iter__(self) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table} ORDER BY {self._order_sql}"
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def iter_with_sequence(self) -> Iterator[tuple[int, dict[str, Any]]]:
        cursor = self.connection.execute(
            f"SELECT source_order, payload FROM {self.table} "
            "ORDER BY sequence"
        )
        for source_order, payload in cursor:
            yield int(source_order), _restore(payload)

    def iter_sorted(self) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table} "
            "ORDER BY sort_time, sort_id, sequence"
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def update_each(self, update) -> None:
        cursor = self.connection.execute(
            f"SELECT sequence, payload FROM {self.table} ORDER BY sequence"
        )
        for sequence, payload in cursor:
            row = _restore(payload)
            update(row)
            self.connection.execute(
                f"UPDATE {self.table} SET payload = ? WHERE sequence = ?",
                (_payload(row), int(sequence)),
            )
        self.connection.commit()

    def finalize_leg_state(self, config: dict[str, Any]) -> None:
        """Reapply corpus-wide expiry/reward groups after per-run folding."""

        if not self:
            return
        ttl = float(config["quote_ttl_seconds"])

        def write_leg(sequence: int, leg: dict[str, Any], next_time=None) -> None:
            ttl_expiry = leg["quote_time"] + timedelta(seconds=ttl)
            leg["quote_expires_at"] = (
                min(ttl_expiry, next_time)
                if next_time is not None and next_time > leg["quote_time"]
                else ttl_expiry
            )
            self.connection.execute(
                f"UPDATE {self.table} SET payload = ? WHERE sequence = ?",
                (_payload(leg), int(sequence)),
            )

        cursor = self.connection.execute(
            f"SELECT sequence, run_id, event_slug, token_id, side, payload "
            f"FROM {self.table} ORDER BY "
            "run_id, event_slug, token_id, side, sort_time, sequence"
        )
        previous = None
        for sequence, run_id, event_slug, token_id, side, payload in cursor:
            leg = _restore(payload)
            group_key = (run_id, event_slug, token_id, side)
            if previous is not None:
                previous_sequence, previous_key, previous_leg = previous
                write_leg(
                    previous_sequence,
                    previous_leg,
                    leg["quote_time"] if previous_key == group_key else None,
                )
            previous = (int(sequence), group_key, leg)
        if previous is not None:
            write_leg(previous[0], previous[2])
        self.connection.commit()

        def write_reward_group(group: list[tuple[int, dict[str, Any]]]) -> None:
            legs = []
            for _sequence, leg in group:
                leg["quote_row"] = {"min_order_size": leg.get("min_order_size")}
                legs.append(leg)
            attach_reward_estimates(legs, config)
            for sequence, leg in group:
                leg.pop("quote_row", None)
                self.connection.execute(
                    f"UPDATE {self.table} SET payload = ? WHERE sequence = ?",
                    (_payload(leg), int(sequence)),
                )

        reward_group: list[tuple[int, dict[str, Any]]] = []
        reward_quote_id = None
        cursor = self.connection.execute(
            f"SELECT sequence, quote_id, payload FROM {self.table} "
            "ORDER BY quote_id, source_order, sequence"
        )
        for sequence, quote_id, payload in cursor:
            if reward_group and quote_id != reward_quote_id:
                write_reward_group(reward_group)
                reward_group = []
            reward_quote_id = quote_id
            reward_group.append((int(sequence), _restore(payload)))
        if reward_group:
            write_reward_group(reward_group)
        self.connection.commit()

    def event_slugs(self) -> list[str]:
        return [
            str(row[0])
            for row in self.connection.execute(
                f"SELECT event_slug FROM {self.table} "
                "GROUP BY event_slug ORDER BY MIN(sequence)"
            )
        ]

    def iter_event_sorted(self, event_slug: str) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table} WHERE event_slug = ? "
            "ORDER BY sort_time, sort_id, sequence",
            (str(event_slug),),
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def distinct_quote_id_count(self) -> int:
        return int(
            self.connection.execute(
                f"SELECT COUNT(DISTINCT quote_id) FROM {self.table} WHERE quote_id <> ''"
            ).fetchone()[0]
        )

    def new_row_store(self, suffix: str, *, iteration_order: str = "source") -> "SpilledRows":
        return SpilledRows(
            self.connection,
            f"{self.table}_{suffix}",
            iteration_order=iteration_order,
        )

    def new_queue_store(self, suffix: str) -> "SpilledQueueRows":
        return SpilledQueueRows(self.connection, f"{self.table}_{suffix}")

    def new_tape_index(self, suffix: str) -> "SpilledTapeIndex":
        return SpilledTapeIndex(self.connection, f"{self.table}_{suffix}")


class SpilledTapeIndex:
    """Normalized event tapes and global trade capacity stored on disk."""

    def __init__(self, connection: sqlite3.Connection, prefix: str) -> None:
        self.connection = connection
        self.prefix = _table_name(prefix)
        self.trade_table = f"{self.prefix}_trades"
        self.book_table = f"{self.prefix}_books"
        self.mark_table = f"{self.prefix}_marks"
        self.settlement_table = f"{self.prefix}_settlements"
        self.remaining_table = f"{self.prefix}_remaining"
        self.leg_fill_table = f"{self.prefix}_leg_fills"
        for table in (self.trade_table, self.book_table, self.mark_table):
            self.connection.execute(
                f"CREATE TABLE {table} ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "event_slug TEXT NOT NULL, token_id TEXT NOT NULL, "
                "row_time REAL NOT NULL, payload BLOB NOT NULL)"
            )
            self.connection.execute(
                f"CREATE INDEX {table}_lookup ON {table} "
                "(event_slug, token_id, row_time, sequence)"
            )
        self.connection.execute(
            f"CREATE TABLE {self.settlement_table} ("
            "event_slug TEXT PRIMARY KEY, payload BLOB NOT NULL) WITHOUT ROWID"
        )
        self.connection.execute(
            f"CREATE TABLE {self.remaining_table} ("
            "trade_id TEXT PRIMARY KEY, remaining REAL NOT NULL) WITHOUT ROWID"
        )
        self.connection.execute(
            f"CREATE TABLE {self.leg_fill_table} ("
            "leg_id TEXT PRIMARY KEY, filled REAL NOT NULL) WITHOUT ROWID"
        )

    @staticmethod
    def _tape_record(event_slug: str, row: dict[str, Any]) -> tuple[Any, ...]:
        return (
            str(event_slug),
            str(row.get("clob_token_id") or ""),
            _sort_timestamp({}, row.get("time")),
            _payload(row),
        )

    def add_event(
        self,
        event_slug: str,
        trades: Iterable[dict[str, Any]],
        books: Iterable[dict[str, Any]],
        marks: Iterable[dict[str, Any]],
        settlement: dict[str, Any] | None,
    ) -> None:
        event_slug = str(event_slug)
        for trade in trades:
            self.connection.execute(
                f"INSERT INTO {self.trade_table} "
                "(event_slug, token_id, row_time, payload) VALUES (?, ?, ?, ?)",
                self._tape_record(event_slug, trade),
            )
            if trade.get("size") is not None:
                self.connection.execute(
                    f"INSERT INTO {self.remaining_table} (trade_id, remaining) "
                    "VALUES (?, ?) ON CONFLICT(trade_id) DO UPDATE SET "
                    "remaining = excluded.remaining",
                    (str(trade.get("trade_id") or ""), float(trade["size"])),
                )
        for table, rows in ((self.book_table, books), (self.mark_table, marks)):
            self.connection.executemany(
                f"INSERT INTO {table} (event_slug, token_id, row_time, payload) "
                "VALUES (?, ?, ?, ?)",
                (self._tape_record(event_slug, row) for row in rows),
            )
        self.connection.execute(
            f"INSERT OR REPLACE INTO {self.settlement_table} (event_slug, payload) "
            "VALUES (?, ?)",
            (event_slug, _payload(settlement)),
        )
        self.connection.commit()

    def _range_rows(
        self,
        table: str,
        event_slug: str,
        token_id: str,
        start,
        end,
    ) -> list[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {table} WHERE event_slug = ? AND token_id = ? "
            "AND row_time > ? AND row_time <= ? ORDER BY row_time, sequence",
            (
                str(event_slug),
                str(token_id),
                _sort_timestamp({}, start),
                _sort_timestamp({}, end),
            ),
        )
        return [_restore(payload) for (payload,) in cursor]

    def queue_rows(self, leg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        event_slug = str(leg.get("event_slug") or "")
        token_id = str(leg.get("clob_token_id") or "")
        start = _sort_timestamp({}, leg.get("quote_time"))
        nearest = self.connection.execute(
            f"SELECT payload FROM {self.book_table} "
            "WHERE event_slug = ? AND token_id = ? AND row_time <= ? "
            "ORDER BY row_time DESC, sequence DESC LIMIT 1",
            (event_slug, token_id, start),
        ).fetchone()
        books = [_restore(nearest[0])] if nearest else []
        books.extend(
            self._range_rows(
                self.book_table,
                event_slug,
                token_id,
                leg.get("quote_time"),
                leg.get("quote_expires_at"),
            )
        )
        trades = self._range_rows(
            self.trade_table,
            event_slug,
            token_id,
            leg.get("quote_time"),
            leg.get("quote_expires_at"),
        )
        return books, trades

    def trade_rows(self, leg: dict[str, Any]) -> list[dict[str, Any]]:
        return self._range_rows(
            self.trade_table,
            str(leg.get("event_slug") or ""),
            str(leg.get("clob_token_id") or ""),
            leg.get("quote_time"),
            leg.get("quote_expires_at"),
        )

    def remaining(self, trade_id: str) -> float:
        row = self.connection.execute(
            f"SELECT remaining FROM {self.remaining_table} WHERE trade_id = ?",
            (str(trade_id or ""),),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def set_remaining(self, trade_id: str, remaining: float) -> None:
        self.connection.execute(
            f"UPDATE {self.remaining_table} SET remaining = ? WHERE trade_id = ?",
            (float(remaining), str(trade_id or "")),
        )

    def add_leg_fill(self, leg_id: str, fill_size: float) -> float:
        leg_id = str(leg_id or "")
        self.connection.execute(
            f"INSERT INTO {self.leg_fill_table} (leg_id, filled) VALUES (?, ?) "
            "ON CONFLICT(leg_id) DO UPDATE SET filled = filled + excluded.filled",
            (leg_id, float(fill_size)),
        )
        return float(
            self.connection.execute(
                f"SELECT filled FROM {self.leg_fill_table} WHERE leg_id = ?",
                (leg_id,),
            ).fetchone()[0]
        )

    def mark_rows(self, event_slug: str, token_id: str, targets: Iterable[Any]) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for target in targets:
            found = self.connection.execute(
                f"SELECT sequence, payload FROM {self.mark_table} "
                "WHERE event_slug = ? AND token_id = ? AND row_time >= ? "
                "ORDER BY row_time, sequence LIMIT 1",
                (
                    str(event_slug),
                    str(token_id),
                    _sort_timestamp({}, target),
                ),
            ).fetchone()
            if found and int(found[0]) not in seen:
                seen.add(int(found[0]))
                rows.append(_restore(found[1]))
        rows.sort(key=lambda row: row["time"])
        return rows

    def settlement(self, event_slug: str) -> dict[str, Any] | None:
        found = self.connection.execute(
            f"SELECT payload FROM {self.settlement_table} WHERE event_slug = ?",
            (str(event_slug),),
        ).fetchone()
        return _restore(found[0]) if found else None


class SpilledQueueRows:
    """Disk-backed ``dict[leg_id, queue]`` with dict-compatible ordering."""

    is_spilled_queue_rows = True

    def __init__(self, connection: sqlite3.Connection, table: str) -> None:
        self.connection = connection
        self.table = _table_name(table)
        self.connection.execute(
            f"CREATE TABLE {self.table} ("
            "leg_id TEXT PRIMARY KEY, "
            "first_order INTEGER NOT NULL, "
            "payload BLOB NOT NULL, "
            "context BLOB NOT NULL) WITHOUT ROWID"
        )
        self.connection.execute(
            f"CREATE INDEX {self.table}_order ON {self.table} (first_order, leg_id)"
        )

    def __len__(self) -> int:
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0])

    def __bool__(self) -> bool:
        return len(self) > 0

    def upsert(
        self,
        row: dict[str, Any],
        *,
        source_order: int,
        context: dict[str, Any],
    ) -> None:
        self.connection.execute(
            f"INSERT INTO {self.table} (leg_id, first_order, payload, context) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(leg_id) DO UPDATE SET "
            "payload = excluded.payload, context = excluded.context",
            (
                str(row.get("leg_id") or ""),
                int(source_order),
                _payload(row),
                _payload(context),
            ),
        )

    def get(self, leg_id: str) -> dict[str, Any]:
        found = self.connection.execute(
            f"SELECT payload FROM {self.table} WHERE leg_id = ?",
            (str(leg_id or ""),),
        ).fetchone()
        return _restore(found[0]) if found else {}

    def __iter__(self) -> Iterator[dict[str, Any]]:
        cursor = self.connection.execute(
            f"SELECT payload FROM {self.table} ORDER BY first_order, leg_id"
        )
        for (payload,) in cursor:
            yield _restore(payload)

    def iter_with_context(self) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
        cursor = self.connection.execute(
            f"SELECT payload, context FROM {self.table} ORDER BY first_order, leg_id"
        )
        for payload, context in cursor:
            yield _restore(payload), _restore(context)


class QuotedRowsView:
    """Quote rows annotated by an exact disk-backed quote-id membership join."""

    has_quote_leg_marker = True

    def __init__(self, quote_rows: SpilledRows, legs: SpilledRows) -> None:
        self.quote_rows = quote_rows
        self.legs = legs

    def __len__(self) -> int:
        return len(self.quote_rows)

    def __bool__(self) -> bool:
        return bool(self.quote_rows)

    @property
    def quoted_id_count(self) -> int:
        return self.legs.distinct_quote_id_count()

    def __iter__(self) -> Iterator[dict[str, Any]]:
        cursor = self.quote_rows.connection.execute(
            f"SELECT q.payload, CASE WHEN l.quote_id IS NULL THEN 0 ELSE 1 END "
            f"FROM {self.quote_rows.table} AS q "
            f"LEFT JOIN (SELECT DISTINCT quote_id FROM {self.legs.table} "
            "WHERE quote_id <> '') AS l ON l.quote_id = q.quote_id "
            "ORDER BY q.sequence"
        )
        for payload, quoted in cursor:
            row = _restore(payload)
            row["_has_quote_leg"] = bool(quoted)
            yield row


class MakerPaperRunAggregation:
    """Fold one maker run at a time into disk-spilled scorer inputs."""

    def __init__(
        self,
        scratch_root: str | Path | None,
        *,
        config: dict[str, Any],
        include_model_variants: bool,
        include_fill_simulation: bool,
        scoring_input_paths_by_folder: dict[str, dict[str, str]] | None = None,
        scoring_input_bindings_by_folder: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self._scratch = (
            tempfile.TemporaryDirectory(prefix="weather-maker-paper-")
            if scratch_root is None
            else None
        )
        root = Path(self._scratch.name if self._scratch is not None else scratch_root)
        root.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(root / "maker_paper_rows.sqlite3"))
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute("PRAGMA cache_size=-2048")
        self.config = dict(config)
        self.include_model_variants = bool(include_model_variants and include_fill_simulation)
        self.scoring_input_paths_by_folder = (
            None
            if scoring_input_paths_by_folder is None
            else {
                str(Path(folder)): {
                    str(kind): Path(path)
                    for kind, path in paths.items()
                }
                for folder, paths in scoring_input_paths_by_folder.items()
            }
        )
        self.scoring_input_bindings_by_folder = (
            None
            if scoring_input_bindings_by_folder is None
            else {
                str(Path(folder)): {
                    str(kind): dict(binding)
                    for kind, binding in bindings.items()
                }
                for folder, bindings in scoring_input_bindings_by_folder.items()
            }
        )
        self.quote_rows = SpilledRows(self.connection, "base_quotes")
        self.legs = SpilledRows(self.connection, "base_legs")
        self.model_variant_quote_rows = SpilledRows(self.connection, "variant_quotes")
        self.model_variant_legs = SpilledRows(self.connection, "variant_legs")
        self.run_configs: dict[str, dict[str, Any]] = {}
        self.run_count = 0
        self._seen_run_ids = {"base": set(), "variant": set()}
        self._cross_run_state_required = {"base": False, "variant": False}
        self._closed = False

    def __enter__(self) -> "MakerPaperRunAggregation":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def quoted_rows(self) -> QuotedRowsView:
        return QuotedRowsView(self.quote_rows, self.legs)

    @property
    def quoted_model_variant_rows(self) -> QuotedRowsView:
        return QuotedRowsView(self.model_variant_quote_rows, self.model_variant_legs)

    def _input_path_for_kind(self, folder: str | Path, kind: str):
        if self.scoring_input_paths_by_folder is None:
            return None
        folder_key = str(Path(folder))
        try:
            path = self.scoring_input_paths_by_folder[folder_key][kind]
        except KeyError as exc:
            raise ValueError(
                f"missing explicit {kind} maker scoring input path for {folder_key}"
            ) from exc
        return {folder_key: path}

    def _input_binding_for_kind(self, folder: str | Path, kind: str):
        if self.scoring_input_bindings_by_folder is None:
            return None
        folder_key = str(Path(folder))
        try:
            binding = self.scoring_input_bindings_by_folder[folder_key][kind]
        except KeyError as exc:
            raise ValueError(
                f"missing explicit {kind} maker scoring input binding for {folder_key}"
            ) from exc
        return {folder_key: binding}

    def add_run_folder(
        self,
        folder: str | Path,
        *,
        eligibility_by_folder: dict[str, dict[str, Any]],
    ) -> dict[str, int]:
        """Decode, score, spill, and release one run before returning."""

        quote_rows, run_configs = load_quote_rows(
            [folder],
            eligibility_by_folder=eligibility_by_folder,
            input_paths_by_folder=self._input_path_for_kind(folder, "base"),
            input_bindings_by_folder=self._input_binding_for_kind(folder, "base"),
        )
        legs = quote_legs(quote_rows, self.config)
        base_run_ids = {str(leg.get("run_id") or "") for leg in legs}
        if self._seen_run_ids["base"] & base_run_ids:
            self._cross_run_state_required["base"] = True
        self._seen_run_ids["base"].update(base_run_ids)
        self.quote_rows.extend(quote_rows)
        self.legs.extend(legs)
        self.run_configs.update(run_configs)
        counts = {"quote_rows": len(quote_rows), "quote_legs": len(legs)}
        del quote_rows, legs, run_configs
        gc.collect()

        variant_row_count = 0
        variant_leg_count = 0
        if self.include_model_variants:
            variant_rows, _variant_configs = load_model_variant_quote_rows(
                [folder],
                eligibility_by_folder=eligibility_by_folder,
                input_paths_by_folder=self._input_path_for_kind(folder, "model_variant"),
                input_bindings_by_folder=self._input_binding_for_kind(
                    folder,
                    "model_variant",
                ),
            )
            variant_legs = quote_legs(variant_rows, self.config)
            variant_run_ids = {str(leg.get("run_id") or "") for leg in variant_legs}
            if self._seen_run_ids["variant"] & variant_run_ids:
                self._cross_run_state_required["variant"] = True
            self._seen_run_ids["variant"].update(variant_run_ids)
            self.model_variant_quote_rows.extend(variant_rows)
            self.model_variant_legs.extend(variant_legs)
            variant_row_count = len(variant_rows)
            variant_leg_count = len(variant_legs)
            del variant_rows, variant_legs, _variant_configs
            gc.collect()
        self.connection.commit()
        self.run_count += 1
        counts.update(
            {
                "model_variant_quote_rows": variant_row_count,
                "model_variant_quote_legs": variant_leg_count,
            }
        )
        return counts

    def finalize_cross_run_state(self) -> None:
        if self._cross_run_state_required["base"]:
            self.legs.finalize_leg_state(self.config)
        if self._cross_run_state_required["variant"]:
            self.model_variant_legs.finalize_leg_state(self.config)

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


__all__ = [
    "MakerPaperRunAggregation",
    "QuotedRowsView",
    "SpilledQueueRows",
    "SpilledRows",
    "SpilledTapeIndex",
]
