"""Streaming lineage recovery preserves the materialized tape contract."""

from __future__ import annotations

import gc
import tracemalloc
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from weather.market.worker_release_binding import (
    LINEAGE_FIELDS,
    VERIFIED_RELEASE_IDENTITY_STATUS,
    WorkerReleaseBindingError,
    worker_tape_columns_from_rows,
    worker_tape_summary_fields,
)


BOUND_LINEAGE: dict[str, Any] = {
    "release_id": "release-a",
    "release_manifest_sha256": "a" * 64,
    "release_pointer_sha256": "b" * 64,
    "release_sequence": 7,
    "release_identity_status": VERIFIED_RELEASE_IDENTITY_STATUS,
    "release_identity_reason": "verified active serving bundle",
    "base_model_release_bound": True,
    "base_model_binding_reason": "base model is release-bound",
}


def _row(
    lineage: Mapping[str, Any] = BOUND_LINEAGE,
    **extra: Any,
) -> dict[str, Any]:
    return {**lineage, **extra}


def _generator(rows: Iterable[Mapping[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        yield dict(row)


def _outcome(rows: Iterable[Mapping[str, Any]]) -> tuple[str, Any]:
    try:
        return "return", worker_tape_summary_fields(rows)
    except WorkerReleaseBindingError as exc:
        return "raise", str(exc)


def test_streamed_bound_summary_and_columns_match_materialized_contract() -> None:
    rows = [
        _row(order_id="one"),
        _row(
            release_sequence="7",
            base_model_release_bound="1",
            order_id="two",
        ),
    ]
    expected_lineage = dict(BOUND_LINEAGE)
    expected = {**expected_lineage, "release_identity": expected_lineage}

    assert worker_tape_summary_fields(rows) == expected
    assert worker_tape_summary_fields(_generator(rows)) == expected
    assert worker_tape_columns_from_rows(
        ["order_id"],
        _generator(rows),
    ) == ["order_id", *LINEAGE_FIELDS]


def _partial_rows() -> list[dict[str, Any]]:
    partial = _row()
    partial.pop("release_identity_reason")
    alternate = _row(release_id="release-b")
    return [{}, *[dict(partial) for _ in range(12)], _row(), alternate]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            _partial_rows(),
            "worker tape contains incomplete release lineage at rows "
            "[2, 3, 4, 5, 6, 7, 8, 9, 10, 11]; refusing summary recovery",
        ),
        (
            [_row(), {}, _row(release_id="release-b")],
            "worker tape mixes legacy no-lineage rows with stamped release lineage; "
            "refusing summary recovery",
        ),
        (
            [_row(), _row(release_id="release-b")],
            "worker tape contains mixed release identities; refusing summary recovery",
        ),
    ],
    ids=("partial-precedence", "legacy-bound-mix", "multiple-identities"),
)
def test_streamed_fail_closed_errors_match_materialized_contract(
    rows: list[dict[str, Any]],
    message: str,
) -> None:
    expected = ("raise", message)

    assert _outcome(rows) == expected
    assert _outcome(_generator(rows)) == expected


def _generated_rows(run_count: int, *, rows_per_run: int = 1_000):
    for run_index in range(run_count):
        for row_index in range(rows_per_run):
            yield _row(
                order_id=f"run-{run_index:02d}-row-{row_index:04d}",
                payload=f"{run_index:02d}:{row_index:04d}:" + ("x" * 512),
            )


def _peak_bytes_for_runs(run_count: int) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        columns = worker_tape_columns_from_rows(
            ["order_id", "payload"],
            _generated_rows(run_count),
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert columns == ["order_id", "payload", *LINEAGE_FIELDS]
    return peak


def test_generator_peak_memory_stays_flat_from_five_to_fifty_runs() -> None:
    few_peak = _peak_bytes_for_runs(5)
    many_peak = _peak_bytes_for_runs(50)

    # A materializing implementation retains all 50,000 unique rows.  Streaming
    # recovery retains one identity and at most the current generated row.
    assert many_peak <= few_peak + 256 * 1024
