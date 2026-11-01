"""Reanalysis raw-chunk overlap census: overlaps from names, duplicate hours from labels, nothing else read.

Guards: item 340 duplicate-chunk finding (master ruling 2026-11-01): the host counter lists only each market's
raw directory and its year= subdirectories, counts overlapping chunks and duplicate UTC hours, reads labels only
from files ending on or before --max-end-date, and never emits a value. Synthetic tmp_path layouts only.
"""

import json

from tools.research import reanalysis_chunk_overlap_census as census


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


def payload(first_hour, hours, offset=-21600):
    labels = [f"2024-01-31T{first_hour + step:02d}:00" for step in range(hours)]
    return {"utc_offset_seconds": offset, "hourly": {"time": labels, "temperature_2m": [99.5] * hours}}


def layout(tmp_path):
    raw = tmp_path / "reanalysis" / "kord" / "raw"
    write(raw / "year=2024" / "2024-01-01_2024-01-31.json", payload(0, 4))
    write(raw / "year=2024" / "2024-01-31_2024-03-01.json", payload(0, 6))  # shares 01-31 with the first
    write(raw / "year=2024" / "2024-02-01_2024-03-02.json", {"utc_offset_seconds": -21600, "hourly": {"time": []}})
    write(raw / "year=2024" / "2024-12-01_2024-12-31.json", "not json: must stay unread")  # ends after max end
    # Outside the two listed levels: never counted (they would overlap everything if they were).
    write(raw / "year=2024" / "nested" / "2024-01-01_2024-12-31.json", payload(0, 6))
    write(raw / "2024-01-01_2024-12-31.json", payload(0, 6))
    write(tmp_path / "reanalysis" / "klga" / "raw" / "year=2024" / "2024-01-01_2024-12-31.json", payload(0, 6))
    return tmp_path / "reanalysis"


def test_names_give_the_overlapping_pairs_days_and_spans(tmp_path):
    result = census.census(layout(tmp_path), ["kord"])
    row = result["markets"]["kord"]

    assert list(result["markets"]) == ["kord"]
    assert row["chunk_files"] == 4 and row["unnamed_files"] == 0
    assert row["overlapping_file_pairs"] == 2 and row["files_in_an_overlap"] == 3
    assert row["overlap_day_count"] == 31  # 01-31, then 02-01..03-01 (leap February)
    assert row["overlap_days_by_year"] == {"2024": 31}
    assert row["overlap_spans"] == [["2024-01-31", "2024-03-01", 31]]
    assert row["max_chunks_on_one_day"] == 2
    assert result["totals"] == {"chunk_files": 4, "overlapping_file_pairs": 2, "overlap_day_count": 31}


def test_labels_give_duplicate_utc_hours_and_skip_files_after_the_max_end(tmp_path):
    root = layout(tmp_path)
    assert census.main(["--root", str(root), "--markets", "kord", "--read-labels", "--max-end-date", "2024-06-30",
                        "--out", str(tmp_path / "out.json")]) == 0
    result = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    labels = result["markets"]["kord"]["labels"]

    assert labels["files_read"] == 3 and labels["files_skipped_unnamed_or_after_max_end"] == 1
    assert labels["files_unreadable"] == 0 and labels["labels_unplaced"] == 0
    assert labels["distinct_utc_hours"] == 6 and labels["duplicate_hours"] == 4
    assert labels["duplicate_label_day_count"] == 1 and labels["duplicate_label_days_by_year"] == {"2024": 1}
    assert "99.5" not in json.dumps(result)  # no value is ever emitted


def test_the_same_label_under_different_offsets_is_two_hours(tmp_path):
    raw = tmp_path / "reanalysis" / "kord" / "raw" / "year=2024"
    write(raw / "2024-01-01_2024-01-31.json", payload(0, 2, offset=-21600))
    write(raw / "2024-01-31_2024-02-29.json", payload(0, 2, offset=-18000))
    labels = census.census(tmp_path / "reanalysis", ["kord"], read_labels=True,
                           max_end=census.named_range("2024-02-29_2024-02-29")[1])["markets"]["kord"]["labels"]
    assert labels["duplicate_hours"] == 1  # 00:00 at -05:00 is 01:00 at -06:00; only that instant repeats


def test_read_labels_without_a_max_end_date_is_refused(tmp_path, capsys):
    assert census.main(["--root", str(tmp_path), "--read-labels"]) == 2
    assert "--max-end-date" in capsys.readouterr().err
