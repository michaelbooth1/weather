"""Settlement labels, settled-day discovery and replay corpora with archived tapes."""
import json
from datetime import date

import pytest

from tests.cold_archive_fixture import SLUG, archive_day, corpus, snapshots_root  # noqa: F401
from weather import cold_archive_locations as locations
from weather.backtesting import settlement_ledger as ledger
from weather.backtesting.replay import load_replay_records
from weather.backtesting.settled_days import discover_settled_folders

TAPE = {"snapshots_long.csv": b"snapshot_id,range_label\ns1,60-61\n"}
REPLAY = {"replay_inputs.jsonl": b'{"snapshot_id": "s1"}\n'}
OTHER = "highest-temperature-in-toronto-on-june-16-2026"


def _label(slug, target, bucket):
    return {"event_slug": slug, "market_id": "toronto", "target_date": target,
            "settlement_bucket": bucket, "quality_grade": "A", "revision_number": 1}


def _finalize(corpus, monkeypatch, labels_csv):
    """Finalize the corpus day and a second day whose label is re-derived."""
    other = snapshots_root(corpus) / OTHER
    other.mkdir(exist_ok=True)
    real = ledger.finalize_folder

    def finalize(folder, **kwargs):
        return _label(OTHER, "2026-06-16", 62) if folder == other else real(folder, **kwargs)

    monkeypatch.setattr(ledger, "finalize_folder", finalize)
    return ledger.finalize_folders([corpus.day, other], labels_csv=labels_csv,
                                   ledger_root=corpus.tmp / "ledger")


def _seed(labels_csv):
    ledger.write_labels_csv(labels_csv, [_label(SLUG, "2026-06-15", 60), _label(OTHER, "2026-06-16", 61)])
    return [line for line in labels_csv.read_bytes().splitlines(keepends=True) if SLUG.encode() in line]


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_archived_day_keeps_its_labels_row_byte_for_byte(corpus, monkeypatch):
    labels_csv = corpus.tmp / "labels.csv"
    archive_day(corpus)
    archived_row = _seed(labels_csv)
    labels = _finalize(corpus, monkeypatch, labels_csv)
    assert [label["event_slug"] for label in labels] == [OTHER]
    lines = labels_csv.read_bytes().splitlines(keepends=True)
    assert [line for line in lines if SLUG.encode() in line] == archived_row
    assert any(OTHER.encode() in line and b",62," in line for line in lines)


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_label_rewrite_is_unchanged_when_nothing_is_archived(corpus, monkeypatch):
    # Parity: a missing tape without a marker is dropped exactly as before.
    labels_csv, expected = corpus.tmp / "labels.csv", corpus.tmp / "expected.csv"
    (corpus.day / "snapshots_long.csv").unlink()
    _seed(labels_csv)
    labels = _finalize(corpus, monkeypatch, labels_csv)
    ledger.write_labels_csv(expected, labels)
    assert labels_csv.read_bytes() == expected.read_bytes()
    assert SLUG.encode() not in labels_csv.read_bytes()


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_settled_discovery_counts_an_archived_tape_as_present(corpus):
    root = snapshots_root(corpus)
    before = discover_settled_folders(root, as_of=date(2026, 7, 1))
    assert before == [corpus.day]
    archive_day(corpus)
    assert discover_settled_folders(root, as_of=date(2026, 7, 1)) == before


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_settled_discovery_unchanged_without_an_archive(corpus):
    (corpus.day / "snapshots_long.csv").unlink()
    assert discover_settled_folders(snapshots_root(corpus), as_of=date(2026, 7, 1)) == []


@pytest.mark.parametrize("corpus", [REPLAY], indirect=True)
def test_archived_replay_corpus_is_never_an_empty_day(corpus):
    archive_day(corpus)
    with pytest.raises(locations.ArchivedInputRequired):
        load_replay_records(corpus.day)


@pytest.mark.parametrize("corpus", [REPLAY], indirect=True)
def test_archived_replay_corpus_reads_its_verified_cache(corpus):
    local = load_replay_records(corpus.day)
    archive_day(corpus, cache=True)
    assert load_replay_records(corpus.day) == local == [json.loads(REPLAY["replay_inputs.jsonl"])]
