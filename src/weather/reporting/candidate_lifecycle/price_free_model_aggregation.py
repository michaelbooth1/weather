"""Bounded scratch state for price-free model-learning reports."""

from __future__ import annotations

import json
import math
import pickle
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from weather.scoring.metrics import binary_log_loss, safe_float


SQLITE_PAGE_CACHE_KIB = 2048
PARTITION_FIELDS = (
    "band_count",
    "model_effective_bands",
    "model_norm_entropy",
    "model_top_probability",
    "model_winner_probability",
    "model_winner_rank",
    "model_top_is_winner",
    "model_adjacent_winner_mass",
)


class _CompensatedSum:
    """Streaming equivalent of the active CPython float ``sum`` fast path."""

    def __init__(self) -> None:
        self.total = 0.0
        self.correction = 0.0

    def add(self, value: float) -> None:
        value = float(value)
        if sys.version_info < (3, 12):
            self.total += value
            return
        combined = self.total + value
        if abs(self.total) >= abs(value):
            self.correction += (self.total - combined) + value
        else:
            self.correction += (value - combined) + self.total
        self.total = combined

    def value(self) -> float:
        if (
            sys.version_info >= (3, 12)
            and self.correction
            and math.isfinite(self.correction)
        ):
            return self.total + self.correction
        return self.total


def _configure_scratch_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute(f"PRAGMA cache_size=-{SQLITE_PAGE_CACHE_KIB}")


def _payload(value: Any) -> sqlite3.Binary:
    return sqlite3.Binary(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))


class SpilledRows:
    """Re-iterable source-ordered rows backed by disposable SQLite."""

    is_spilled_rows = True

    def __init__(self, scratch: "PriceFreeScratch", collection: str) -> None:
        self._scratch = scratch
        self.collection = str(collection)

    def __len__(self) -> int:
        return self._scratch.row_count(self.collection)

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self):
        yield from self._scratch.iter_rows(self.collection)

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1:
                return list(self._scratch.iter_rows(self.collection, offset=start, limit=stop - start))
            return [row for position, row in enumerate(self) if position in range(start, stop, step)]
        position = int(index)
        if position < 0:
            position += len(self)
        rows = list(self._scratch.iter_rows(self.collection, offset=position, limit=1))
        if not rows:
            raise IndexError(index)
        return rows[0]

    def append(self, value: Any) -> None:
        self._scratch.append_row(self.collection, value)

    def extend(self, values: Iterable[Any]) -> None:
        self._scratch.extend_rows(self.collection, values)


class PriceFreeScratch:
    """Own the disposable arrays and exact distinct indexes for one build."""

    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="weather-price-free-learning-")
        database = Path(self._temporary_directory.name) / "price_free_learning.sqlite3"
        self.connection = sqlite3.connect(str(database))
        _configure_scratch_connection(self.connection)
        self.connection.executescript(
            """
            CREATE TABLE spilled_rows (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE INDEX spilled_rows_collection_sequence
                ON spilled_rows (collection, sequence);
            CREATE TABLE selected_labels (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                tape_key TEXT NOT NULL UNIQUE,
                market_sort TEXT NOT NULL,
                date_sort TEXT NOT NULL,
                tie_sort TEXT NOT NULL,
                folder TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE INDEX selected_labels_sort
                ON selected_labels (market_sort, date_sort, tie_sort, sequence);
            CREATE TABLE distinct_values (
                scope TEXT NOT NULL,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (scope, kind, value)
            ) WITHOUT ROWID;
            CREATE TABLE partition_rows (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                lane TEXT NOT NULL,
                partition_key TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE INDEX partition_rows_lane_partition_sequence
                ON partition_rows (lane, partition_key, sequence);
            CREATE TABLE hourly_checkpoints (
                checkpoint_key TEXT PRIMARY KEY,
                market_sort TEXT NOT NULL,
                date_sort TEXT NOT NULL,
                band_sort TEXT NOT NULL,
                hour_sort INTEGER NOT NULL,
                timestamp_sort REAL NOT NULL,
                partition_key TEXT NOT NULL,
                payload BLOB NOT NULL
            ) WITHOUT ROWID;
            CREATE INDEX hourly_checkpoints_legacy_order
                ON hourly_checkpoints (market_sort, date_sort, band_sort, hour_sort);
            """
        )
        self._row_counts: Counter[str] = Counter()
        self._hourly_checkpoints_materialized = False
        self._closed = False

    def __enter__(self) -> "PriceFreeScratch":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("price-free learning scratch is closed")

    def rows(self, collection: str) -> SpilledRows:
        self._check_open()
        return SpilledRows(self, collection)

    def append_row(self, collection: str, value: Any) -> None:
        self._check_open()
        self.connection.execute(
            "INSERT INTO spilled_rows (collection, payload) VALUES (?, ?)",
            (str(collection), _payload(value)),
        )
        self._row_counts[str(collection)] += 1

    def extend_rows(self, collection: str, values: Iterable[Any]) -> None:
        self._check_open()
        count = 0

        def encoded():
            nonlocal count
            for value in values:
                count += 1
                yield str(collection), _payload(value)

        self.connection.executemany(
            "INSERT INTO spilled_rows (collection, payload) VALUES (?, ?)",
            encoded(),
        )
        self._row_counts[str(collection)] += count

    def iter_rows(self, collection: str, *, offset: int = 0, limit: int | None = None):
        self._check_open()
        sql = "SELECT payload FROM spilled_rows WHERE collection = ? ORDER BY sequence"
        parameters: list[Any] = [str(collection)]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            parameters.extend([max(0, int(limit)), max(0, int(offset))])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            parameters.append(max(0, int(offset)))
        cursor = self.connection.execute(sql, parameters)
        for (value,) in cursor:
            yield pickle.loads(value)

    def row_count(self, collection: str) -> int:
        self._check_open()
        return int(self._row_counts.get(str(collection), 0))

    def add_selected_label(
        self,
        *,
        tape_key: str,
        folder: Path,
        label: dict[str, Any],
        tie_sort: str = "",
    ) -> bool:
        self._check_open()
        before = self.connection.total_changes
        self.connection.execute(
            "INSERT OR IGNORE INTO selected_labels "
            "(tape_key, market_sort, date_sort, tie_sort, folder, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(tape_key),
                str(label.get("market_id") or ""),
                str(label.get("target_date") or ""),
                str(tie_sort),
                str(folder),
                _payload(dict(label)),
            ),
        )
        return self.connection.total_changes > before

    def selected_label_count(self) -> int:
        self._check_open()
        return int(self.connection.execute("SELECT COUNT(*) FROM selected_labels").fetchone()[0])

    def iter_selected_labels(self):
        self._check_open()
        cursor = self.connection.execute(
            "SELECT folder, payload FROM selected_labels "
            "ORDER BY market_sort, date_sort, tie_sort, sequence"
        )
        for folder, payload in cursor:
            yield {"folder": Path(folder), "label": pickle.loads(payload)}

    @staticmethod
    def _identity(value: Any) -> str:
        return json.dumps(value, default=str, separators=(",", ":"))

    @classmethod
    def _partition_identity(cls, row: dict[str, Any]) -> str:
        return cls._identity(
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("cutoff_hour"),
            ]
        )

    def extend_partition_rows(self, lane: str, rows: Iterable[dict[str, Any]]) -> None:
        """Spill source-ordered rows for later global partition reduction."""

        self._check_open()
        lane = str(lane)
        self.connection.executemany(
            "INSERT INTO partition_rows (lane, partition_key, payload) VALUES (?, ?, ?)",
            (
                (lane, self._partition_identity(row), _payload(row))
                for row in rows
            ),
        )

    def add_hourly_checkpoint(
        self,
        row: dict[str, Any],
        *,
        timestamp_sort: float,
    ) -> None:
        """Retain the legacy earliest row for one market/day/band/hour key."""

        self._check_open()
        hour = int(row.get("cutoff_hour"))
        checkpoint_key = self._identity(
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("band"),
                hour,
            ]
        )
        self.connection.execute(
            """
            INSERT INTO hourly_checkpoints (
                checkpoint_key,
                market_sort,
                date_sort,
                band_sort,
                hour_sort,
                timestamp_sort,
                partition_key,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checkpoint_key) DO UPDATE SET
                timestamp_sort = excluded.timestamp_sort,
                partition_key = excluded.partition_key,
                payload = excluded.payload
            WHERE excluded.timestamp_sort < hourly_checkpoints.timestamp_sort
            """,
            (
                checkpoint_key,
                str(row.get("market_id") or ""),
                str(row.get("target_date") or ""),
                str(row.get("band") or ""),
                hour,
                float(timestamp_sort),
                self._partition_identity(row),
                _payload(row),
            ),
        )

    def iter_hourly_checkpoints(self):
        """Yield retained checkpoint rows in the legacy global key order."""

        self._check_open()
        cursor = self.connection.execute(
            "SELECT payload FROM hourly_checkpoints "
            "ORDER BY market_sort, date_sort, band_sort, hour_sort"
        )
        for (payload,) in cursor:
            yield pickle.loads(payload)

    def materialize_hourly_checkpoint_partitions(self) -> None:
        """Bind retained checkpoints to source-order partition sequences once."""

        self._check_open()
        if self._hourly_checkpoints_materialized:
            return
        self.connection.execute(
            """
            INSERT INTO partition_rows (lane, partition_key, payload)
            SELECT 'checkpoint', partition_key, payload
            FROM hourly_checkpoints
            ORDER BY market_sort, date_sort, band_sort, hour_sort
            """
        )
        self._hourly_checkpoints_materialized = True

    def iter_partition_groups(self, lane: str):
        """Yield one globally reduced partition at a time in legacy order."""

        self._check_open()
        cursor = self.connection.execute(
            """
            WITH ranked AS (
                SELECT
                    sequence,
                    partition_key,
                    payload,
                    MIN(sequence) OVER (PARTITION BY partition_key) AS first_sequence
                FROM partition_rows
                WHERE lane = ?
            )
            SELECT partition_key, payload
            FROM ranked
            ORDER BY first_sequence, sequence
            """,
            (str(lane),),
        )
        current_key: str | None = None
        group: list[dict[str, Any]] = []
        for partition_key, payload in cursor:
            if current_key is not None and partition_key != current_key:
                yield group
                group = []
            current_key = str(partition_key)
            group.append(pickle.loads(payload))
        if group:
            yield group

    def add_distinct(self, scope: str, kind: str, value: Any) -> None:
        self._check_open()
        self.connection.execute(
            "INSERT OR IGNORE INTO distinct_values (scope, kind, value) VALUES (?, ?, ?)",
            (str(scope), str(kind), self._identity(value)),
        )

    def distinct_counts(self, scope: str) -> dict[str, int]:
        self._check_open()
        rows = self.connection.execute(
            "SELECT kind, COUNT(*) FROM distinct_values WHERE scope = ? GROUP BY kind",
            (str(scope),),
        )
        counts = {str(kind): int(count) for kind, count in rows}
        return {
            "market_days": counts.get("market_days", 0),
            "markets": counts.get("markets", 0),
            "snapshots": counts.get("snapshots", 0),
        }

    def commit(self) -> None:
        self._check_open()
        self.connection.commit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.connection.close()
        self._temporary_directory.cleanup()


class ModelScoreAccumulator:
    """Exact sufficient statistics for ``model_score_rows``."""

    def __init__(self, scratch: PriceFreeScratch, scope: str) -> None:
        self.scratch = scratch
        self.scope = str(scope)
        self.n = 0
        self.brier_sum = _CompensatedSum()
        self.logloss_sum = _CompensatedSum()
        self.outcome_sum = 0
        self.model_probability_sum = _CompensatedSum()
        self.winner_count = 0
        self.winner_probability_sum = _CompensatedSum()
        self.loser_count = 0
        self.loser_probability_sum = _CompensatedSum()
        self.ece_bins = [
            [0, _CompensatedSum(), _CompensatedSum()]
            for _ in range(5)
        ]
        self.partition_count = 0
        self.partition_sums: dict[str, _CompensatedSum] = defaultdict(_CompensatedSum)
        self.partition_counts: dict[str, int] = defaultdict(int)

    def update_row(self, row: dict[str, Any]) -> None:
        probability = float(row["model_probability"])
        outcome = int(row["outcome"])
        self.n += 1
        self.brier_sum.add((probability - outcome) ** 2)
        self.logloss_sum.add(binary_log_loss(probability, outcome))
        self.outcome_sum += outcome
        self.model_probability_sum.add(probability)
        if outcome == 1:
            self.winner_count += 1
            self.winner_probability_sum.add(probability)
        elif outcome == 0:
            self.loser_count += 1
            self.loser_probability_sum.add(probability)
        index = min(4, int(max(0.0, min(0.999999, probability)) * 5))
        bucket = self.ece_bins[index]
        bucket[0] += 1
        bucket[1].add(probability)
        bucket[2].add(outcome)
        self.scratch.add_distinct(
            self.scope,
            "market_days",
            [row.get("market_id"), row.get("target_date")],
        )
        if row.get("market_id") not in (None, ""):
            self.scratch.add_distinct(self.scope, "markets", row.get("market_id"))
        if row.get("snapshot_id") not in (None, ""):
            self.scratch.add_distinct(self.scope, "snapshots", row.get("snapshot_id"))

    def update_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.update_row(row)

    def add_partition(self, partition: dict[str, Any]) -> None:
        self.partition_count += 1
        for field in PARTITION_FIELDS:
            value = safe_float(partition.get(field))
            if value is None or math.isnan(value):
                continue
            self.partition_sums[field].add(value)
            self.partition_counts[field] += 1

    def _ece(self) -> float | None:
        if self.n <= 0:
            return None
        return sum(
            (int(bucket[0]) / self.n)
            * abs(bucket[1].value() / int(bucket[0]) - bucket[2].value() / int(bucket[0]))
            for bucket in self.ece_bins
            if int(bucket[0]) > 0
        )

    def finalize(self) -> dict[str, Any] | None:
        if self.n <= 0:
            return None
        distinct = self.scratch.distinct_counts(self.scope)
        summary = {
            "n": self.n,
            "model_brier": self.brier_sum.value() / self.n,
            "model_logloss": self.logloss_sum.value() / self.n,
            "base_rate": self.outcome_sum / self.n,
            "market_days": distinct["market_days"],
            "markets": distinct["markets"],
            "snapshots": distinct["snapshots"],
            "model_ece": self._ece(),
            "mean_model_probability": self.model_probability_sum.value() / self.n,
            "winner_rows": self.winner_count,
            "winner_model_probability": (
                self.winner_probability_sum.value() / self.winner_count
                if self.winner_count
                else None
            ),
            "loser_model_probability": (
                self.loser_probability_sum.value() / self.loser_count
                if self.loser_count
                else None
            ),
        }
        if self.partition_count:
            summary.update(
                {
                    "partition_snapshots": self.partition_count,
                    "partition_mean_band_count": self._partition_mean("band_count"),
                    "partition_model_effective_bands": self._partition_mean("model_effective_bands"),
                    "partition_model_norm_entropy": self._partition_mean("model_norm_entropy"),
                    "partition_model_top_probability": self._partition_mean("model_top_probability"),
                    "partition_model_winner_probability": self._partition_mean("model_winner_probability"),
                    "partition_model_winner_rank": self._partition_mean("model_winner_rank"),
                    "partition_model_top_is_winner_rate": self._partition_mean("model_top_is_winner"),
                    "partition_model_adjacent_winner_mass": self._partition_mean(
                        "model_adjacent_winner_mass"
                    ),
                }
            )
        return summary

    def _partition_mean(self, field: str) -> float | None:
        count = self.partition_counts.get(field, 0)
        return self.partition_sums[field].value() / count if count else None


class CurrentMaxSummaryAccumulator:
    """Exact sufficient statistics for current-max summary rows."""

    def __init__(self) -> None:
        self.n = 0
        self.with_current_max = 0
        self.disposition_counts: Counter[Any] = Counter()
        self.state_counts: Counter[Any] = Counter()
        self.risky_or_guarded_count = 0
        self.early_large_gap_count = 0
        self.gap_count = 0
        self.gap_sum = _CompensatedSum()
        self.max_gap: float | None = None

    def update(self, row: dict[str, Any]) -> None:
        self.n += 1
        self.with_current_max += int(row.get("wu_max_since_7am") is not None)
        disposition = row.get("feature_disposition")
        state = row.get("current_max_state")
        self.disposition_counts[disposition] += 1
        self.state_counts[state] += 1
        self.risky_or_guarded_count += int(disposition in {"null_before_reset", "support_only"})
        self.early_large_gap_count += int(state == "early_current_max_history_gap")
        gap = row.get("gap_to_wu_history")
        if gap is not None:
            number = float(gap)
            self.gap_count += 1
            self.gap_sum.add(number)
            self.max_gap = number if self.max_gap is None else max(self.max_gap, number)

    def finalize(self) -> dict[str, Any]:
        return {
            "snapshot_rows": self.n,
            "with_current_max": self.with_current_max,
            "pre_reset_null_count": self.disposition_counts.get("null_before_reset", 0),
            "support_only_count": self.disposition_counts.get("support_only", 0),
            "validated_count": self.disposition_counts.get("validated", 0),
            "risky_or_guarded_count": self.risky_or_guarded_count,
            "early_large_gap_count": self.early_large_gap_count,
            "max_gap_to_wu_history": self.max_gap,
            "mean_gap_to_wu_history": (
                self.gap_sum.value() / self.gap_count if self.gap_count else None
            ),
            "state_counts": dict(sorted(self.state_counts.items())),
            "feature_disposition_counts": dict(sorted(self.disposition_counts.items())),
        }


class PriceFreeLearningPayload(dict):
    """Payload whose spilled v0.1 arrays remain readable until close."""

    def __init__(self, payload: dict[str, Any], scratch: PriceFreeScratch) -> None:
        super().__init__(payload)
        self._scratch: PriceFreeScratch | None = scratch

    def __enter__(self) -> "PriceFreeLearningPayload":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def materialize(self) -> dict[str, Any]:
        if self._scratch is None:
            raise RuntimeError("price-free learning payload is closed")
        return materialize_price_free_value(dict(self))

    def close(self) -> None:
        scratch = self._scratch
        if scratch is not None:
            self._scratch = None
            scratch.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def materialize_price_free_value(value: Any) -> Any:
    if getattr(value, "is_spilled_rows", False):
        return [materialize_price_free_value(item) for item in value]
    if isinstance(value, dict):
        return {key: materialize_price_free_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize_price_free_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(materialize_price_free_value(item) for item in value)
    return value


__all__ = [
    "CurrentMaxSummaryAccumulator",
    "ModelScoreAccumulator",
    "PriceFreeLearningPayload",
    "PriceFreeScratch",
    "SpilledRows",
    "materialize_price_free_value",
]
