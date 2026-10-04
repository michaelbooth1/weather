"""Replay-status backfill reuses existing status when raw inputs are archived."""
from datetime import date

import pytest

from tests.cold_archive_fixture import archive_day, corpus  # noqa: F401
from weather import cold_archive_locations as locations
from weather.backtesting.replay import REPLAY_STATUS_FILENAME, REPLAY_STATUS_LONG_FILENAME
from weather.operations import replay_status_backfill as backfill

INPUTS = {
    "replay_inputs.jsonl": b'{"snapshot_id": "s1", "captured_at_utc": "2026-06-15T12:00:00+00:00"}\n',
    "snapshots.jsonl": b'{"snapshot_id": "s1", "captured_at_utc": "2026-06-15T12:00:00+00:00"}\n',
}
AS_OF = date(2026, 7, 1)


def _status_bytes(day):
    return {name: (day / name).read_bytes() for name in (REPLAY_STATUS_FILENAME, REPLAY_STATUS_LONG_FILENAME)}


def _repair(day, **kwargs):
    return backfill.repair_folder(day, as_of_date=AS_OF, **kwargs)


@pytest.mark.parametrize("corpus", [INPUTS], indirect=True)
def test_archived_inputs_reuse_the_cached_status_without_rewriting(corpus):
    written = _repair(corpus.day)
    assert written["action"] == "written"
    before = _status_bytes(corpus.day)
    reused = _repair(corpus.day)
    archive_day(corpus)
    assert _repair(corpus.day) == reused
    assert _repair(corpus.day, incremental=False)["reason"] == "replay_status_exists"
    assert _status_bytes(corpus.day) == before


@pytest.mark.parametrize("corpus", [INPUTS], indirect=True)
def test_archived_inputs_reuse_existing_status_without_a_cache(corpus):
    _repair(corpus.day)
    before = _status_bytes(corpus.day)
    (corpus.day / ".replay_status_cache.json").unlink()
    archive_day(corpus)
    result = _repair(corpus.day)
    assert (result["action"], result["reason"], result["training_ready"]) == (
        "skipped", "replay_status_exists", True)
    # The captured corpus is archived; the snapshot tape is still local and read.
    assert result["archived_inputs"] == ["replay_inputs.jsonl"]
    assert result["replay_input_count"] is None and result["has_raw_replay_evidence"] is True
    assert result["snapshot_count"] == 1
    assert _status_bytes(corpus.day) == before


@pytest.mark.parametrize("corpus", [INPUTS], indirect=True)
def test_archived_inputs_without_status_are_reported_not_written(corpus):
    archive_day(corpus)
    result = _repair(corpus.day)
    assert (result["action"], result["reason"]) == ("archived", "archived_inputs_require_restore")
    assert not (corpus.day / REPLAY_STATUS_LONG_FILENAME).exists()
    with pytest.raises(locations.ArchivedInputRequired):
        _repair(corpus.day, overwrite=True)


@pytest.mark.parametrize("corpus", [INPUTS], indirect=True)
def test_backfill_is_unchanged_when_nothing_is_archived(corpus):
    evidence = backfill.folder_evidence(corpus.day)
    assert "archived_inputs" not in evidence and evidence["replay_input_count"] == 1
    assert backfill.existing_status_summary(corpus.day) == {}
    assert _repair(corpus.day)["action"] == "written"
