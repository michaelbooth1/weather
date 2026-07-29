"""Streaming readers and deterministic rebuilds for full-depth CLOB books.

The canonical full-book representation is ``order_books.jsonl``.  Expanded
CSV and gzip CSV are analysis projections.  Callers use this boundary so
tiering an old ``order_books_long.csv`` cannot strand a full-book corpus read.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from weather.io import normalize_csv_row, open_tiered_text, resolve_tiered_text
from weather.market.market_microstructure_constants import BOOK_LEVEL_COLUMNS


RAW_BOOK_FILENAME = "order_books.jsonl"
GZIP_RAW_BOOK_FILENAME = "order_books.jsonl.gz"
GZIP_LONG_FILENAME = "order_books_long.csv.gz"
LONG_FILENAME = "order_books_long.csv"
ACCEPTED_REPRESENTATIONS = (
    "raw_jsonl",
    "raw_jsonl_gzip",
    "gzip_csv",
    "csv",
)


@dataclass(frozen=True)
class FullBookReadProvenance:
    representation: str
    path: str
    canonical: bool
    fallback_reason: str | None = None


def _as_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("captured_at_utc must include a timezone")
    return parsed


def level_rows_from_raw_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the writer's expanded rows from one canonical raw record."""

    from weather.market.market_microstructure_capture import order_book_level_rows

    if not isinstance(record, dict):
        raise ValueError("raw order-book record must be an object")
    book = record.get("book")
    token = record.get("token")
    if not isinstance(book, dict) or not isinstance(token, dict):
        raise ValueError("raw order-book record requires object book and token fields")
    capture_id = str(record.get("capture_id") or "")
    if not capture_id:
        raise ValueError("raw order-book record requires capture_id")
    captured_at = _as_datetime(record.get("captured_at_utc"))
    return order_book_level_rows(book, token, captured_at, capture_id)


def iter_raw_jsonl_level_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    path = Path(path)
    with open_tiered_text(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
                rows = level_rows_from_raw_record(record)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid canonical order-book row at {path}:{line_number}: {exc}"
                ) from exc
            yield from rows


def _csv_handle(path: Path):
    return open_tiered_text(
        path,
        encoding="utf-8-sig",
        newline="",
    )


def iter_long_csv_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    path = Path(path)
    with _csv_handle(path) as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(BOOK_LEVEL_COLUMNS):
            raise ValueError(
                f"unexpected order-book long header at {path}: "
                f"{reader.fieldnames!r}"
            )
        yield from reader


def resolve_full_book_representation(
    folder: str | Path,
    *,
    preference: Iterable[str] = ACCEPTED_REPRESENTATIONS,
) -> FullBookReadProvenance:
    folder = Path(folder)
    paths = {
        "raw_jsonl": folder / RAW_BOOK_FILENAME,
        "raw_jsonl_gzip": folder / GZIP_RAW_BOOK_FILENAME,
        "gzip_csv": folder / GZIP_LONG_FILENAME,
        "csv": folder / LONG_FILENAME,
    }
    preference = tuple(preference)
    unknown = [value for value in preference if value not in paths]
    if unknown:
        raise ValueError(f"unknown full-book representations: {unknown}")

    # Historical capture could recreate the plain long projection after an
    # older prefix had already been tiered. A simultaneous pair therefore has
    # to prove byte equality even when the canonical raw tape is preferred;
    # otherwise silently selecting either half can exclude settlement.
    if paths["gzip_csv"].exists() or paths["csv"].exists():
        resolve_tiered_text(paths["csv"])

    # Do the same for the canonical warm representation. The resolver consumes
    # and compares a transitional plain+gzip pair before any iterator is
    # returned, so a caller cannot observe rows from divergent evidence.
    if paths["raw_jsonl"].exists() or paths["raw_jsonl_gzip"].exists():
        resolve_tiered_text(paths["raw_jsonl"])

    for index, representation in enumerate(preference):
        path = paths[representation]
        if path.is_file():
            return FullBookReadProvenance(
                representation=representation,
                path=str(path),
                canonical=representation
                in {"raw_jsonl", "raw_jsonl_gzip"},
                fallback_reason=(
                    None
                    if index == 0
                    else f"preferred representations unavailable: {','.join(preference[:index])}"
                ),
            )
    raise FileNotFoundError(
        f"no accepted full-book representation under {folder}: "
        f"{', '.join(path.name for path in paths.values())}"
    )


def iter_full_book_rows(
    folder: str | Path,
    *,
    preference: Iterable[str] = ACCEPTED_REPRESENTATIONS,
) -> tuple[Iterator[dict[str, Any]], FullBookReadProvenance]:
    provenance = resolve_full_book_representation(folder, preference=preference)
    if provenance.representation in {"raw_jsonl", "raw_jsonl_gzip"}:
        rows = iter_raw_jsonl_level_rows(provenance.path)
    else:
        rows = iter_long_csv_rows(provenance.path)
    return rows, provenance


def rebuild_long_csv(
    raw_jsonl: str | Path,
    output_csv: str | Path,
) -> dict[str, Any]:
    """Materialize one deterministic projection without touching its source."""

    raw_jsonl = Path(raw_jsonl)
    output_csv = Path(output_csv)
    if output_csv.exists():
        raise FileExistsError(f"refusing to overwrite rebuild output: {output_csv}")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_csv.with_name(f".{output_csv.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"refusing to overwrite rebuild temporary: {temporary}")
    row_count = 0
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=BOOK_LEVEL_COLUMNS,
                extrasaction="ignore",
                restval="",
            )
            writer.writeheader()
            for row in iter_raw_jsonl_level_rows(raw_jsonl):
                writer.writerow(normalize_csv_row(row))
                row_count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_csv)
    except BaseException:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise
    return {
        "canonical_source": str(raw_jsonl),
        "rebuilt_projection": str(output_csv),
        "row_count": row_count,
        "accepted_read_representations": list(ACCEPTED_REPRESENTATIONS),
    }
