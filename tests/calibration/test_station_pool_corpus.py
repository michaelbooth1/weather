"""Lane L48 station-pooled corpus: frozen kill gate, block bootstrap, cutoff features and corpus integrity.

Guards: rule rule_station_pool.md (sha256 33d5c67a...) section 7 kill conditions, block-3 resampling that never
crosses a year or a date gap, the cutoff feature admits only reports at or before the cutoff, the duck-typed
station spec keeps the Fahrenheit template, and a published corpus whose bytes do not match its sha is refused.
"""
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.host_guard import import_or_skip_on_capture_host

import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")
from weather.calibration import station_pool_corpus as spc  # noqa: E402


def _rows(delta_by_market, years=(2021, 2022, 2023, 2024, 2025), n_days=12, noise=0.0):
    rows = []
    for year in years:
        for d in range(n_days):
            day = (date(year, 8, 1) + timedelta(days=d)).isoformat()
            for market, delta in delta_by_market.items():
                for hour in (7, 8):
                    jitter = noise * (((d * 7 + hour + len(market)) % 5) - 2)
                    rows.append({"hour": hour, "year": year, "market": market, "date": day, "y": 80.0,
                                 "P3d_N_11m_brier": 0.8, "P3d_N_pool_brier": 0.8 + delta + jitter,
                                 "P3d_N_11m_log": 2.0, "P3d_N_pool_log": 2.0 + delta})
    return rows


def test_gate_passes_a_uniform_improvement():
    out = spc.gate(_rows({"atlanta": -0.01, "nyc": -0.01}, noise=0.001))
    assert out["verdict"] == "PASS"
    assert out["d_brier"] == pytest.approx(-0.01, abs=1e-3)
    assert out["wider_upper"] < 0


def test_gate_kills_on_small_point_and_on_one_ci_worse_market():
    assert spc.gate(_rows({"atlanta": -0.0004, "nyc": -0.0004}))["kills"]["1_point_ge_-0.0005"]
    out = spc.gate(_rows({"atlanta": -0.05, "nyc": 0.01}, noise=0.001))
    assert out["d_brier"] < spc.KILL_POINT
    assert out["kills"]["3_market_ci_worse"] == ["nyc"]
    assert out["verdict"] == "KILL"


def test_gate_kills_when_two_years_are_worse():
    rows = _rows({"atlanta": -0.02})
    for r in rows:
        if r["year"] in (2022, 2024):
            r["P3d_N_pool_brier"] = 0.8 + 0.001
    out = spc.gate(rows)
    assert out["kills"]["4_years_d_gt_0_more_than_1"]
    assert out["verdict"] == "KILL"


def test_block3_blocks_stay_inside_a_year_and_skip_gaps():
    rows = _rows({"atlanta": -0.01}, years=(2021, 2022), n_days=5)
    rows = [r for r in rows if r["date"] != "2021-08-03"]  # a gap splits 2021 into 2 + 2 dates
    _, info = spc.block3_ci(rows, "P3d_N_pool", "P3d_N_11m")
    assert info["blocks"] == 3  # only 2022's 08-01..03, 02..04, 03..05
    assert info["blocks_per_draw"] == 3  # ceil(9 dates / 3)


def test_station_candidate_keeps_the_fahrenheit_template():
    cand = spc.station_candidate("KABC", "America/Denver")
    assert cand.spec.icao == "KABC" and cand.spec.id == "kabc"
    assert cand.spec.display_unit == "F" and cand.spec.timezone == "America/Denver"
    assert cand.label_source.complete_day_max_gap_minutes == 180


def test_cutoff_features_admit_only_reports_at_or_before_the_cutoff():
    tz = ZoneInfo("America/New_York")
    day = "2023-08-15"
    local = lambda h, m: datetime(2023, 8, 15, h, m, tzinfo=tz).astimezone(timezone.utc)  # noqa: E731
    by_date = {day: [(local(5, 52), 70.0), (local(6, 52), 75.02), (local(7, 0), 74.12), (local(7, 52), 90.0)]}
    F, cur = spc.cutoff_features(by_date, day, 7, tz)
    assert (F, cur) == (75.0, 74.0)
    assert spc.cutoff_features(by_date, day, 5, tz) == (None, None)
    assert spc.cutoff_features(by_date, "2023-08-16", 12, tz) == (None, None)


def test_published_corpus_is_refused_when_bytes_do_not_match(tmp_path):
    body = json.dumps({"market": "KABC", "year": 2021, "nbm_product_version": "v4.0"}).encode() + b"\n"
    gz = gzip.compress(body, mtime=0)
    sha = hashlib.sha256(gz).hexdigest()
    folder = tmp_path / sha
    folder.mkdir()
    (folder / "rows.jsonl.gz").write_bytes(gz)
    manifest = {"corpus_sha256": sha, "rule_sha256": spc.RULE_SHA256}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    frame, _ = spc.load_pool_frame(folder)
    assert list(frame["market"]) == ["KABC"]
    (folder / "rows.jsonl.gz").write_bytes(gzip.compress(body + body, mtime=0))
    with pytest.raises(spc.StationPoolError):
        spc.load_pool_frame(folder)


def test_season_dates_are_the_300_aug_sep_dates():
    dates = spc.season_dates()
    assert len(dates) == 300 and dates[0] == date(2021, 8, 1) and dates[-1] == date(2025, 9, 29)
