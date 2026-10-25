"""METAR-labelled corpus builder for candidate cities.

Guards: M1 new-city lane deliverable 3 (2026-10-23) and owner decision
2026-10-23 (new METAR-settled cities labelled from IEM METAR under the venue
rule of weather.backtesting.venue_rule_labels: routine only, SPECI excluded;
a station's scheduled half-hourly routine reports that IEM files as type 4
count, any other type-4 report does not): local date keyed
on observation time in the IANA zone (DST-aware), thin or fetch-edge days never
label, the METAR print cutoff admits nothing after the cutoff and aliases like
the WU rule, and PIT forecast rows after their cutoff are refused.
"""

import dataclasses
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
    return load_candidate_registry()["tokyo"]


def _csv(tmp_path, name, rows):
    """IEM-shaped CSV with raw text; ``t`` is whole C or a (body, tenths) pair."""
    lines = []
    for valid, t in rows:
        body, tenths = (t, None) if not isinstance(t, tuple) else t
        stamp = valid[8:10] + valid[11:13] + valid[14:16]
        remark = f" RMK T{0 if tenths >= 0 else 1}{abs(int(round(tenths * 10))):03d}" if tenths is not None else ""
        lines.append(f"EGLC,{valid},0,{body},EGLC {stamp}Z 25008KT 9999 SCT020 {int(body):02d}/05 Q1012{remark}\n")
    path = tmp_path / name
    path.write_text("station,valid,tmpf,tmpc,metar\n" + "".join(lines), encoding="utf-8")
    return path


def _labels(candidate, routine, special, last_date="2026-09-29"):
    records, counts = corpus.venue_routine_records(routine, special, candidate, last_date=last_date)
    return corpus.daily_labels(records, candidate, last_date=last_date), counts


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
    routine, special = corpus.station_csvs(FIXTURES, candidate.spec.icao)

    labels, counts = _labels(candidate, routine, special)

    assert labels[target_date]["label_native"] == label
    assert labels[target_date]["max_times_local"] == times
    assert labels[target_date]["row_count"] == 48
    assert labels[target_date]["label_complete"] is True
    # The fixture starts mid-evening UTC on 08-09: that local day is a fetch edge.
    assert labels["2026-08-09"]["label_complete"] is False
    assert counts["scheduled_type4_routine"] == counts["routine"] // 2


def test_without_the_schedule_minute_type4_reports_never_label():
    candidate = _candidate("london")
    routine, special = corpus.station_csvs(FIXTURES, "EGLC")
    hourly_only = dataclasses.replace(candidate, iem_special_schedule_minute=None)

    labels, counts = _labels(hourly_only, routine, special)

    assert "scheduled_type4_routine" not in counts
    assert labels["2026-08-10"]["row_count"] == 24
    assert (labels["2026-08-10"]["label_native"], labels["2026-08-10"]["max_times_local"]) == (26, "16:50")


def test_off_schedule_type4_is_a_speci_excluded_from_labels_but_seen_by_cutoff_features(tmp_path):
    candidate = _candidate("london")
    routine = _csv(tmp_path, "r.csv", [("2026-08-10 11:50", 20), ("2026-08-10 12:50", 21)])
    special = _csv(tmp_path, "s.csv", [("2026-08-10 12:20", 22), ("2026-08-10 12:37", 29)])

    records, counts = corpus.venue_routine_records([routine], [special], candidate, last_date="2026-09-29")
    features = corpus.observed_at_cutoff(
        corpus.read_iem_records([routine, special], candidate.spec, last_date="2026-09-29"), "2026-08-10", 14, candidate,
    )

    assert sorted(row["temp_native"] for row in records) == [20, 21, 22]
    assert (counts["scheduled_type4_routine"], counts["special"]) == (1, 1)
    assert features["obs_max_so_far_native"] == 29


def test_t_group_tenths_round_half_up_to_the_venue_whole_degree(tmp_path):
    candidate = _candidate("london")
    routine = _csv(tmp_path, "r.csv", [("2026-08-10 11:50", (20, 20.5)), ("2026-08-10 12:50", (20, 20.4))])

    records, counts = corpus.venue_routine_records([routine], [], candidate, last_date="2026-09-29")

    assert max(row["temp_native"] for row in records) == 20.5
    assert corpus.daily_label(records, "2026-08-10", candidate)["label_native"] == 21
    assert counts["basis_t_group"] == 2


def test_tokyo_day_keys_on_observation_time_not_utc_date():
    candidate = _with_tokyo()
    labels, _ = _labels(candidate, *corpus.station_csvs(FIXTURES, "RJTT"))

    assert (labels["2026-08-10"]["label_native"], labels["2026-08-11"]["label_native"]) == (30, 32)
    assert labels["2026-08-11"]["max_times_local"] == "13:30"
    assert labels["2026-08-10"]["label_complete"] is True


def test_rows_after_last_date_are_dropped_at_read_time(tmp_path):
    candidate = _candidate("london")
    path = _csv(tmp_path, "EGLC_rt3.csv", [("2026-09-29 12:50", 18), ("2026-09-30 12:50", 30)])

    records = corpus.read_iem_records([path], candidate.spec, last_date="2026-09-29")
    labelled, _ = corpus.venue_routine_records([path], [], candidate, last_date="2026-09-29")

    assert {row["local_date"] for row in records} == {"2026-09-29"}
    assert {row["local_date"] for row in labelled} == {"2026-09-29"}


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
    kwargs = dict(market_ids=["london"], metar_root=FIXTURES, pit_corpus_manifest=manifest,
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
        corpus.build(market_ids=["london"], metar_root=FIXTURES, pit_corpus_manifest=manifest,
                     last_date="2026-09-29", publish_root=tmp_path / "out")
    assert not (tmp_path / "out" / "corpora").exists() or not any((tmp_path / "out" / "corpora").iterdir())


def test_build_refuses_a_tampered_pit_corpus_and_non_candidates(tmp_path):
    manifest = _pit_corpus(tmp_path, [_pit_row("2026-08-10", 14, "2026-08-10T13:00:00+00:00")])
    (manifest.parent / "forecast_daily.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(corpus.CorpusBuildError, match="hash does not match"):
        corpus.load_pit_forecast_daily(manifest, ["london"])
    with pytest.raises(corpus.CorpusBuildError, match="not candidate markets"):
        corpus.build(market_ids=["nyc"], metar_root=FIXTURES, pit_corpus_manifest=manifest,
                     last_date="2026-09-29", publish_root=tmp_path / "out")


def _synthetic_rows(n_days=400):
    import random

    rng = random.Random(7)
    rows = []
    start = corpus._parse_date("2023-01-01")
    for k in range(n_days):
        day = (start + corpus.timedelta(days=k)).isoformat()
        truth = 15 + 8 * rng.random()
        forecast = truth + rng.gauss(0, 2.0)
        for hour in (9, 15):
            seen = truth - (3.0 if hour == 9 else 0.3) + rng.gauss(0, 0.3)
            rows.append({
                "market_id": "london", "cutoff_hour_local": hour, "target_date": day, "temperature_unit": "C",
                "forecast_high_native": forecast, "obs_max_so_far_native": seen, "obs_latest_native": seen,
                "label_native": int(truth + 0.5),
            })
    return rows


def test_fit_beats_the_forecast_only_baseline_when_observations_carry_signal():
    result = corpus.fit_and_evaluate(
        _synthetic_rows(), train_through="2023-12-31", test_from="2024-01-01", test_to="2024-02-04",
    )

    late = result["results"]["london|13-16"]
    assert late["ols_minus_baseline_brier"] < 0 and late["ols_minus_baseline_brier_ci95"][1] < 0
    assert late["hgb_minus_baseline_brier"] < 0 and late["hgb_minus_baseline_brier_ci95"][1] < 0
    assert late["n_dates"] == 35
    assert set(result["headline_blocks"]) == {"07-09", "10-12", "07-12"}
    assert "london|07-12" in result["results"]
    assert result["benchmark"].startswith("weather-only")
    assert late["ols_hgb_resid_minus_baseline_brier"] < 0
    assert "ols_hgb_resid_minus_ols_brier_ci95" in late
    assert result["fitted"]["london|15"]["ols_hgb_resid_cv_sd"] > 0


def test_residual_hgb_repairs_what_ols_cannot_fit():
    import random

    rng = random.Random(11)
    rows = []
    start = corpus._parse_date("2023-01-01")
    for k in range(500):
        day = (start + corpus.timedelta(days=k)).isoformat()
        forecast = 10 + 20 * rng.random()
        truth = forecast + (4.0 if forecast > 20 else 0.0) + rng.gauss(0, 0.4)  # a step OLS cannot fit
        rows.append({
            "market_id": "london", "cutoff_hour_local": 8, "target_date": day, "temperature_unit": "C",
            "forecast_high_native": forecast, "obs_max_so_far_native": forecast - 8, "obs_latest_native": forecast - 8,
            "label_native": int(truth + 0.5),
        })
    result = corpus.fit_and_evaluate(rows, train_through="2024-02-29", test_from="2024-03-01", test_to="2024-05-14")

    block = result["results"]["london|07-09"]
    assert block["ols_hgb_resid_minus_ols_brier"] < 0 and block["ols_hgb_resid_minus_ols_brier_ci95"][1] < 0


def test_fit_refuses_evaluation_after_the_development_window():
    with pytest.raises(corpus.CorpusBuildError, match="after 2025-12-31"):
        corpus.fit_and_evaluate(_synthetic_rows(), train_through="2025-09-01", test_from="2025-09-02", test_to="2026-01-01")


def test_band_probabilities_use_venue_ladders():
    edges, width = corpus._band_ladder(77, "F")
    assert width == 2 and 76 in edges and all(edge % 2 == 0 for edge in edges)
    probs = corpus.band_probabilities(76.9, 1.0, edges, width)
    assert abs(sum(probs) - 1.0) < 1e-6
    assert max(probs) == probs[edges.index(76)]


def test_hard_floor_puts_no_mass_below_the_observed_band_and_keeps_total_mass():
    edges, width = corpus._band_ladder(20, "C")
    free = corpus.band_probabilities(18.0, 1.5, edges, width)
    floored = corpus.band_probabilities(18.0, 1.5, edges, width, floor=19)

    assert all(p == 0.0 for edge, p in zip(edges, floored) if edge < 19)
    assert floored[edges.index(19)] > free[edges.index(19)]
    assert abs(sum(floored) - 1.0) < 1e-6
    above = [p for edge, p in zip(edges, free) if edge >= 19]
    ratios = [f / a for f, a, edge in zip(floored, free, edges) if edge >= 20 and a > 1e-9]
    assert max(ratios) - min(ratios) < 1e-9  # a pure renormalisation above the floor band
    assert sum(above) < 1.0


def test_hard_floor_in_fahrenheit_cuts_inside_a_two_degree_band():
    edges, width = corpus._band_ladder(77, "F")
    probs = corpus.band_probabilities(74.0, 2.0, edges, width, floor=77)

    assert probs[edges.index(74)] == 0.0
    assert probs[edges.index(76)] > 0.0  # 77 sits in the 76-77 band
    assert abs(sum(probs) - 1.0) < 1e-6


def test_routine_floor_uses_only_label_rule_reports_by_the_cutoff(tmp_path):
    candidate = _candidate("london")
    routine = _csv(tmp_path, "r.csv", [("2026-08-10 10:50", 20), ("2026-08-10 12:50", 23), ("2026-08-10 13:50", 26)])
    special = _csv(tmp_path, "s.csv", [("2026-08-10 12:37", 29)])
    records, _ = corpus.venue_routine_records([routine], [special], candidate, last_date="2026-09-29")

    at14 = corpus.routine_floor_at_cutoff(records, "2026-08-10", 14, candidate)

    assert (at14["obs_routine_max_so_far_native"], at14["floor_native"]) == (23, 23)
    assert corpus.routine_floor_at_cutoff(records, "2026-08-10", 7, candidate)["floor_native"] is None
