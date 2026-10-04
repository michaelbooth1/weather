import csv
from datetime import date
import hashlib
import json

import pytest

from weather import io
from weather.projection_io import (
    PROJECTIONS, canonical_rows, explanation_rows, open_projection,
    projection_bytes_view, projection_glob, projection_source, read_projection_frame,
)


@pytest.mark.parametrize("logical,record,expected", [
    ("snapshots_long.csv", {"bands": [{"snapshot_id": "s1", "range_label": "20 C", "p": 0.25}]},
     [{"snapshot_id": "s1", "range_label": "20 C", "p": "0.25"}]),
    ("features_long.csv", {"snapshot_id": "s1", "high": 22.5, "missing": None},
     [{"snapshot_id": "s1", "high": "22.5", "missing": ""}]),
    ("variant_predictions_long.csv", {"snapshot_id": "s1", "variant_id": "base", "p": 0.3},
     [{"snapshot_id": "s1", "variant_id": "base", "p": "0.3"}]),
])
def test_readers_use_canonical_bytes_without_creating_projection(tmp_path, logical, record, expected):
    folder = tmp_path / "event"
    folder.mkdir()
    source = folder / PROJECTIONS[logical]
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    alias = folder / logical
    assert projection_source(alias) == source
    assert list(projection_glob(tmp_path, "*/" + logical)) == [source]
    assert list(canonical_rows(alias)) == expected
    assert io.read_csv_rows(alias) == expected
    assert list(io.iter_csv_rows(alias)) == expected
    with open_projection(alias) as stream:
        assert list(csv.DictReader(stream)) == expected
    with projection_bytes_view(source, source.read_bytes()) as stream:
        assert list(csv.DictReader(stream)) == expected
    assert read_projection_frame(alias).iloc[0]["snapshot_id"] == "s1"
    assert not alias.exists()
    alias.write_text("snapshot_id\nlegacy\n", encoding="utf-8")
    assert projection_source(alias) == alias
    assert list(projection_glob(tmp_path, "*/" + logical)) == [alias]
    assert io.read_csv_rows(alias) == [{"snapshot_id": "legacy"}]


def test_explanations_share_capture_flattening(tmp_path):
    from weather.collection.snapshot_store import SnapshotStore
    base = {"snapshot_id": "s1", "source_hash": "abc"}
    explanation = {"health": {"ok": True, "nested": [1, 2]},
                   "drivers": [{"source": "wu", "weight": 0.4, "missing": None}]}
    expected = SnapshotStore.snapshot_explanation_rows(None, base, explanation)
    assert list(explanation_rows(base, explanation)) == expected
    source = tmp_path / "snapshot_explanations.jsonl"
    source.write_text(json.dumps({**base, "schema_version": "test", "explanations": explanation,
                                  "sections": list(explanation), "row_count": len(expected)}) + "\n")
    assert list(canonical_rows(source)) == [
        {k: "" if v is None else str(v) for k, v in row.items()} for row in expected]


def test_json_only_day_visible_to_discovery_labels_and_archive_reader(tmp_path):
    from weather.backtesting.settled_days import discover_settled_folders
    from weather.reporting.scorecards.snapshot_evaluation import discover_snapshot_folders
    from weather.operations.closed_market_day_archive import read_market_day_artifact
    folder = tmp_path / "highest-temperature-in-toronto-on-july-24-2026"
    folder.mkdir()
    source = folder / "snapshots.jsonl"
    source.write_text(json.dumps({"bands": [{"snapshot_id": "s1", "range_label": "25 C"}]}) + "\n")
    assert discover_settled_folders(tmp_path, as_of=date(2026, 7, 25)) == [folder]
    assert discover_snapshot_folders(tmp_path) == [folder]
    result = read_market_day_artifact(folder, "snapshots_long", prefer_archive=False)
    assert result.frame.iloc[0]["snapshot_id"] == "s1"
    assert result.provenance.source_mode == "canonical_jsonl"
    assert result.provenance.source_file_hash == hashlib.sha256(source.read_bytes()).hexdigest()


def test_bounded_tail_never_scans_or_accepts_partial_json_records(tmp_path):
    source = tmp_path / "snapshots.jsonl"
    records = [{"bands": [{"snapshot_id": str(i), "text": "x" * 128}]} for i in range(20)]
    source.write_text("".join(json.dumps(r) + "\n" for r in records))
    rows, diagnostics = io.read_csv_tail_rows_with_diagnostics(tmp_path / "snapshots_long.csv", max_bytes=1000)
    assert rows[-1]["snapshot_id"] == "19"
    assert diagnostics["read_bytes"] <= 1000
    assert diagnostics["reached_start"] is False
    assert diagnostics["stable_during_read"] is True
    source.write_bytes(source.read_bytes()[:-1])
    rows, diagnostics = io.read_csv_tail_rows_with_diagnostics(source, max_bytes=1000)
    assert rows == [] and diagnostics["status"] == "incomplete_tail"
    with pytest.raises(ValueError, match="incomplete"):
        list(canonical_rows(source))


def test_new_projection_writer_keeps_existing_day_complete(tmp_path):
    from weather.collection.snapshot_store import SnapshotStore
    store = SnapshotStore(root=tmp_path, event_slug="event")
    target = tmp_path / "snapshots_long.csv"
    store.append_projection(target, ["snapshot_id"], [{"snapshot_id": "new"}])
    assert not target.exists()
    target.write_text("snapshot_id\nlegacy\n")
    store.append_projection(target, ["snapshot_id"], [{"snapshot_id": "new"}])
    assert io.read_csv_rows(target) == [{"snapshot_id": "legacy"}, {"snapshot_id": "new"}]
