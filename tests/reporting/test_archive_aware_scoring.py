"""Scoring, learning and scorecard discovery with archived market-day files."""
import csv
from datetime import datetime, timezone

import pytest

from tests.cold_archive_fixture import SLUG, archive_day, corpus, snapshots_root  # noqa: F401
from weather import cold_archive_locations as locations
from weather.reporting.candidate_lifecycle import price_free_model_learning as price_free
from weather.reporting.hourly.hourly_model_scoring import discover_labeled_folders
from weather.reporting.scorecards import captured_input_parity_evidence as parity
from weather.reporting.scorecards import live_variant_settlement_scorecard as scorecard

TAPE = {"snapshots_long.csv": b"snapshot_id,range_label\ns1,60-61\n"}
VARIANT = {"variant_predictions_long.csv": b"snapshot_id,variant\ns1,base\n"}
CAPTURED = {"replay_inputs.jsonl": b'{"snapshot_id": "s1"}\n'}
MISSING = "highest-temperature-in-toronto-on-june-14-2026"


class Scratch:
    def __init__(self):
        self.selected = []

    def add_selected_label(self, *, tape_key, folder, label, tie_sort):
        self.selected.append(folder.name)
        return True

    def commit(self):
        pass


def _labels(corpus):
    path = corpus.tmp / "labels.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_slug", "market_id", "target_date",
                                                    "quality_grade", "settlement_bucket"])
        writer.writeheader()
        for slug, target in ((SLUG, "2026-06-15"), (MISSING, "2026-06-14")):
            writer.writerow({"event_slug": slug, "market_id": "toronto", "target_date": target,
                             "quality_grade": "A", "settlement_bucket": 60})
    return path


def _discover(corpus):
    return discover_labeled_folders(labels_csv=_labels(corpus), snapshots_root=snapshots_root(corpus),
                                    quality_grades=None)


def _price_free(corpus):
    scratch = Scratch()
    skipped = price_free.discover_labeled_folders_bounded(
        scratch, labels_csv=_labels(corpus), snapshots_root=snapshots_root(corpus), quality_grades=None)
    return scratch.selected, skipped


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_scoring_reports_archived_apart_from_missing_tape(corpus):
    archive_day(corpus)
    selected, skipped = _discover(corpus)
    assert selected == [] and skipped == {"archived": 1, "missing_tape": 1}
    assert _price_free(corpus) == ([], {"archived": 1, "missing_tape": 1})


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_scoring_selection_unchanged_without_an_archive(corpus):
    selected, skipped = _discover(corpus)
    assert [item["folder"] for item in selected] == [corpus.day] and skipped == {"missing_tape": 1}
    assert _price_free(corpus) == ([SLUG], {"missing_tape": 1})


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_scoring_selects_a_verified_restore_and_reads_its_cache(corpus):
    archive_day(corpus, cache=True)
    selected, skipped = _discover(corpus)
    assert [item["folder"] for item in selected] == [corpus.day] and skipped == {"missing_tape": 1}
    rows = price_free.read_csv_rows(corpus.day / "snapshots_long.csv")
    assert rows == [{"snapshot_id": "s1", "range_label": "60-61"}]


@pytest.mark.parametrize("corpus", [TAPE], indirect=True)
def test_price_free_folder_discovery_includes_marker_only_tapes(corpus):
    before = list(price_free._discover_tapes(snapshots_root(corpus)))
    archive_day(corpus)
    assert list(price_free._discover_tapes(snapshots_root(corpus))) == before
    with pytest.raises(locations.ArchivedInputRequired):
        price_free.read_csv_rows(before[0])


@pytest.mark.parametrize("corpus", [VARIANT], indirect=True)
def test_variant_tape_discovery_keeps_archived_tapes_and_refuses_empty_reads(corpus):
    before = scorecard.discover_tapes(snapshots_root(corpus))
    assert before == [corpus.day / "variant_predictions_long.csv"]
    archive_day(corpus)
    assert scorecard.discover_tapes(snapshots_root(corpus)) == before
    with pytest.raises(locations.ArchivedInputRequired):
        scorecard.read_rows(before[0])


@pytest.mark.parametrize("corpus", [VARIANT], indirect=True)
def test_variant_rows_from_cache_keep_the_logical_source_path(corpus):
    path = corpus.day / "variant_predictions_long.csv"
    archive_day(corpus, cache=True)
    rows = scorecard.read_rows(path)
    assert rows == [{"snapshot_id": "s1", "variant": "base", "_source_path": str(path), "_row_number": 2}]


def _fresh(path):
    return parity._require_regular_fresh_file(path, now=datetime.now(timezone.utc),
                                              max_age_hours=48.0, role="captured inputs")


@pytest.mark.parametrize("corpus", [CAPTURED], indirect=True)
def test_parity_evidence_requires_restore_for_archived_inputs(corpus):
    path = corpus.day / "replay_inputs.jsonl"
    assert _fresh(path) == len(CAPTURED["replay_inputs.jsonl"])
    archive_day(corpus)
    with pytest.raises(locations.ArchivedInputRequired):
        _fresh(path)


@pytest.mark.parametrize("corpus", [CAPTURED], indirect=True)
def test_parity_evidence_never_treats_a_restore_cache_as_fresh_capture(corpus):
    archive_day(corpus, cache=True)
    with pytest.raises(parity.CapturedInputParityEvidenceError) as caught:
        _fresh(corpus.day / "replay_inputs.jsonl")
    assert caught.value.code == "captured_inputs_archived"
