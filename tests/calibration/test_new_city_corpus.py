"""METAR-labelled corpus builder for candidate cities.

Guards: M1 new-city lane deliverable 3 (2026-10-23) and owner decision
2026-10-23 (new METAR-settled cities labelled from IEM METAR): local date keyed
on observation time in the IANA zone (DST-aware), thin or fetch-edge days never
label, the METAR print cutoff admits nothing after the cutoff and aliases like
the WU rule, and PIT forecast rows after their cutoff are refused.
"""

import hashlib
import json
from pathlib import Path

import pytest

from weather.calibration import new_city_corpus as corpus
from weather.market.candidate_markets import load_candidate_registry, parse_candidate_registry, CANDIDATE_REGISTRY_PATH


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "new_city_corpus"


def _candidate(market_id):
    return load_candidate_registry()[market_id]


def _with_tokyo():
    payload = json.loads(CANDIDATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    row = dict(payload["markets"][0])
    row.update(id="tokyo", location_id="tokyo", city_label="Tokyo", slug_prefix="highest-temperature-in-tokyo-on",
               timezone="Asia/Tokyo", icao="RJTT", wu_history_id="RJTT:9:JP", lat=35.553, lon=139.781)
    payload["markets"].append(row)
    return parse_candidate_registry(payload)["tokyo"]


def _csv(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("station,valid,tmpf,tmpc\n" + "".join(f"EGLC,{v},0,{t}\n" for v, t in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("market_id", "target_date", "label", "times"),
    [
        ("london", "2026-08-10", 26, "16:20|16:50|17:20"),
        ("london", "2026-08-11", 24, "14:20|14:50|15:20"),
        ("paris", "2026-08-10", 32, "16:00|16:30|17:30|18:00"),
    ],
)
def test_iem_fixture_labels_match_an_independent_local_date_max(market_id, target_date, label, times):
    candidate = _candidate(market_id)
    paths = sorted(FIXTURES.glob(f"{candidate.spec.icao}_rt*.csv"))
    records = corpus.read_iem_records(paths, candidate.spec, last_date="2026-09-29")

    labels = corpus.daily_labels(records, candidate, last_date="2026-09-29")

    assert labels[target_date]["label_native"] == label
    assert labels[target_date]["max_times_local"] == times
    assert labels[target_date]["row_count"] == 48
    assert labels[target_date]["label_complete"] is True
    # The fixture starts mid-evening UTC on 08-09: that local day is a fetch edge.
    assert labels["2026-08-09"]["label_complete"] is False


def test_tokyo_day_keys_on_observation_time_not_utc_date():
    candidate = _with_tokyo()
    records = corpus.read_iem_records(sorted(FIXTURES.glob("RJTT_rt*.csv")), candidate.spec, last_date="2026-09-29")

    labels = corpus.daily_labels(records, candidate, last_date="2026-09-29")

    assert (labels["2026-08-10"]["label_native"], labels["2026-08-11"]["label_native"]) == (30, 32)
    assert labels["2026-08-11"]["max_times_local"] == "13:30"
    assert labels["2026-08-10"]["label_complete"] is True


def test_rows_after_last_date_are_dropped_at_read_time(tmp_path):
    candidate = _candidate("london")
    path = _csv(tmp_path, "EGLC_rt3.csv", [("2026-09-29 12:50", 18), ("2026-09-30 12:50", 30)])

    records = corpus.read_iem_records([path], candidate.spec, last_date="2026-09-29")

    assert {row["local_date"] for row in records} == {"2026-09-29"}


def test_dst_fall_back_day_has_25_hours_and_a_gap_breaks_completeness(tmp_path):
    for market_id in ("london", "paris", "munich", "madrid"):
        start, end = corpus.local_day_bounds_utc("2026-10-25", _candidate(market_id).spec.tz)
        assert (end - start).total_seconds() == 25 * 3600
    candidate = _candidate("london")
    # 2026-10-25 London: BST until 01:00Z, then GMT. Half-hourly reports cover the day,
    # local midnight is 2026-10-24 23:00Z.
    rows = []
    for half_hours in range(0, 50):
        minute = 23 * 60 + 20 + half_hours * 30
        day = 24 + minute // (24 * 60)
        hh, mm = divmod(minute % (24 * 60), 60)
        rows.append((f"2026-10-{day:02d} {hh:02d}:{mm:02d}", 12))
    full = corpus.read_iem_records([_csv(tmp_path, "full.csv", rows)], candidate.spec, last_date="2026-10-26")
    thin = [row for row in full if not ("2026-10-25T05" <= row["valid_time_utc"] < "2026-10-25T09")]

    complete = corpus.daily_label([r for r in full if r["local_date"] == "2026-10-25"], "2026-10-25", candidate)
    gappy = corpus.daily_label([r for r in thin if r["local_date"] == "2026-10-25"], "2026-10-25", candidate)

    assert complete["local_day_hours"] == 25.0
    assert complete["label_complete"] is True
    assert complete["max_gap_minutes"] <= 30
    assert gappy["max_gap_minutes"] == 270.0
    assert gappy["label_complete"] is False


def test_metar_cutoff_admits_nothing_after_the_cutoff_and_aliases_like_wu(tmp_path):
    candidate = _candidate("london")
    path = _csv(tmp_path, "EGLC_rt3.csv", [
        ("2026-08-10 11:20", 20),  # 12:20 BST
        ("2026-08-10 12:50", 22),  # 13:50 BST, 10 min before 14:00
        ("2026-08-10 13:00", 30),  # 14:00 BST exactly
        ("2026-08-10 13:20", 40),  # 14:20 BST, after a 14:00 cutoff
    ])
    rows = corpus.read_iem_records([path], candidate.spec, last_date="2026-09-29")

    at14 = corpus.observed_at_cutoff(rows, "2026-08-10", 14, candidate)
    at13 = corpus.observed_at_cutoff(rows, "2026-08-10", 13, candidate)
    without_on_hour = corpus.observed_at_cutoff(rows[:2], "2026-08-10", 14, candidate)
    early = corpus.observed_at_cutoff(rows[:1], "2026-08-10", 14, candidate)

    assert (at14["obs_rows"], at14["obs_max_so_far_native"], at14["effective_cutoff_hour"]) == (3, 30, 14)
    assert at14["feature_as_of_utc"] == "2026-08-10T13:00:00+00:00"
    assert (at13["obs_rows"], at13["obs_max_so_far_native"], at13["effective_cutoff_hour"]) == (1, 20, 12)
    assert without_on_hour["effective_cutoff_hour"] == 14  # 13:50 aliases up to 14:00
    assert early["effective_cutoff_hour"] == 12
    assert corpus.aliased_minute(13 * 60 + 49, 14, 10) == 13 * 60 + 49  # 11 min: no alias
    assert corpus.aliased_minute(13 * 60 + 50, 13, 10) == 13 * 60 + 50  # beyond the wall cutoff
    with pytest.raises(corpus.CorpusBuildError, match="not in the print-cutoff rule"):
        corpus.observed_at_cutoff(rows, "2026-08-10", 21, candidate)


def _pit_corpus(tmp_path, rows, market_ids=("london",)):
    root = tmp_path / "pit"
    root.mkdir()
    body = "".join(json.dumps(row) + "\n" for row in rows).encode("utf-8")
    (root / "forecast_daily.jsonl").write_bytes(body)
    manifest = {
        "corpus_id": "pit-test",
        "market_ids": list(market_ids),
        "files": {"forecast_daily.jsonl": {"sha256": hashlib.sha256(body).hexdigest()}},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root / "manifest.json"


def _pit_row(target_date, hour, as_of, issue="2026-08-09T00:00:00+00:00", available="2026-08-09T06:00:00+00:00"):
    return {
        "market_id": "london", "target_date": target_date, "cutoff_hour_local": hour,
        "feature_as_of_utc": as_of, "issue_time_utc": issue, "available_at_utc": available,
        "forecast_high_native": 25.4, "temperature_unit": "C", "source_model": "gfs_seamless",
        "lead_days": 1, "derived_row_sha256": "x",
    }


def test_build_joins_complete_labels_and_publishes_content_addressed(tmp_path):
    rows = [
        _pit_row("2026-08-10", 14, "2026-08-10T13:00:00+00:00"),
        _pit_row("2026-08-10", 7, "2026-08-10T06:00:00+00:00"),
        _pit_row("2026-08-09", 14, "2026-08-09T13:00:00+00:00"),  # fetch-edge label
        _pit_row("2026-08-14", 14, "2026-08-14T13:00:00+00:00"),  # no label (fixture ends)
    ]
    manifest = _pit_corpus(tmp_path, rows)
    kwargs = dict(market_ids=["london"], metar_csv_dir=FIXTURES, pit_corpus_manifest=manifest,
                  last_date="2026-09-29", publish_root=tmp_path / "out")

    final, published = corpus.build(**kwargs)

    out = [json.loads(line) for line in (final / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert final.name == published["corpus_id"]
    assert [(row["target_date"], row["cutoff_hour_local"], row["label_native"]) for row in out] == [
        ("2026-08-10", 7, 26), ("2026-08-10", 14, 26),
    ]
    assert all(row["obs_latest_valid_time_utc"] <= row["feature_as_of_utc"] for row in out)
    assert published["rejected"] == {"label_incomplete": 1, "no_label": 1}
    with pytest.raises(corpus.CorpusBuildError, match="never overwritten"):
        corpus.build(**kwargs)


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (_pit_row("2026-08-10", 14, "2026-08-10T14:00:00+00:00"), "cutoff instant disagrees"),
        (_pit_row("2026-08-10", 14, "2026-08-10T13:00:00+00:00", issue="2026-08-10T13:00:01+00:00"), "issue_time_utc after"),
        (_pit_row("2026-08-10", 14, "2026-08-10T13:00:00+00:00", available="2026-08-10T18:00:00+00:00"), "available_at_utc after"),
    ],
)
def test_build_refuses_point_in_time_violations(tmp_path, row, reason):
    manifest = _pit_corpus(tmp_path, [row])

    with pytest.raises(corpus.CorpusBuildError, match=reason):
        corpus.build(market_ids=["london"], metar_csv_dir=FIXTURES, pit_corpus_manifest=manifest,
                     last_date="2026-09-29", publish_root=tmp_path / "out")
    assert not (tmp_path / "out" / "corpora").exists() or not any((tmp_path / "out" / "corpora").iterdir())


def test_build_refuses_a_tampered_pit_corpus_and_non_candidates(tmp_path):
    manifest = _pit_corpus(tmp_path, [_pit_row("2026-08-10", 14, "2026-08-10T13:00:00+00:00")])
    (manifest.parent / "forecast_daily.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(corpus.CorpusBuildError, match="hash does not match"):
        corpus.load_pit_forecast_daily(manifest, ["london"])
    with pytest.raises(corpus.CorpusBuildError, match="not candidate markets"):
        corpus.build(market_ids=["nyc"], metar_csv_dir=FIXTURES, pit_corpus_manifest=manifest,
                     last_date="2026-09-29", publish_root=tmp_path / "out")
