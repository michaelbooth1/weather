import csv
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tarfile

import numpy as np
import pandas as pd
import pytest

from tools.research.missing_information.extract import extract_event, make_snapshot
from tools.research.missing_information.checks import load_frame, check1, check2, check4, tail_selection
from tools.research.missing_information.regimes import check5, observation_tags
from tools.research.missing_information.run import manifest_entries, safe_unpack, scratch_path
from weather.market.market_registry import REGISTRY


def snapshot_rows(sid="one", when="2026-08-01T08:00:00-04:00"):
    rows = []
    for kind, lo, hi, model, market in (("lte", 79, 79, .2, .1), ("eq", 80, 81, .6, .8), ("gte", 82, 82, .2, .1)):
        rows.append({"snapshot_id": sid, "captured_at_local": when, "bin_kind": kind,
                     "bin_value_c": str(lo), "bin_value_hi_c": str(hi), "range_label": f"{lo}-{hi}",
                     "model_probability": str(model), "market_yes": str(market),
                     "station_current_c": "78", "station_max_since_7am_c": "79",
                     "nws_forecast_max_c": "81", "open_meteo_max_c": "80"})
    return rows


def test_extractor_uses_native_units_and_excludes_noncountable_folder(tmp_path):
    folder = tmp_path / "highest-temperature-in-atlanta-on-august-1-2026"
    folder.mkdir()
    label = {"target_date": "2026-08-01", "promotion_countable": False,
             "settlement_bucket": 81, "settlement_high": 81, "settlement_unit": "F"}
    (folder / "settlement.json").write_text(json.dumps(label))
    snapshots, audit = extract_event(folder)
    assert snapshots == []
    assert audit["reason"] == "not_promotion_countable"
    label["promotion_countable"] = True
    (folder / "settlement.json").write_text(json.dumps(label))
    rows = snapshot_rows()
    with (folder / "snapshots_long.csv").open("w", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    snapshots, audit = extract_event(folder)
    assert len(snapshots) == 1
    assert snapshots[0]["station_max_since_7am_c"] == 79
    assert snapshots[0]["winner"] == 1
    assert audit["snapshots"] == 1


def test_off_target_capture_and_missing_probability_refused():
    label = {"settlement_bucket": 81, "settlement_high": 81}
    with pytest.raises(ValueError, match="not_on_target"):
        make_snapshot(snapshot_rows(), {}, label, REGISTRY["atlanta"], "2026-08-02")
    rows = snapshot_rows()
    rows[0]["market_yes"] = ""
    with pytest.raises(ValueError, match="probability"):
        make_snapshot(rows, {}, label, REGISTRY["atlanta"], "2026-08-01")


def fixture_frame(tmp_path):
    path = tmp_path / "snapshots.jsonl"
    with path.open("w") as stream:
        for day in range(1, 9):
            date = f"2026-08-{day:02}"
            for market in ("atlanta", "nyc"):
                for hour in (8, 14, 18):
                    features = {f"nbm_prob_tmax_p{p}": v for p, v in zip((10, 25, 50, 75, 90), (77, 79, 81, 83, 85))}
                    features.update(nbm_prob_tmax_mean=81, nbm_prob_tmax_stddev=3,
                                    forecast_high=81, open_meteo_hrrr_high_delta=1)
                    s = make_snapshot(snapshot_rows(f"{date}-{hour}", f"{date}T{hour:02}:00:00-04:00"), features,
                                      {"settlement_bucket": 81, "settlement_high": 81}, REGISTRY[market], date)
                    s.update(hours_from_peak=hour-14, hours_from_envelope_peak=hour-14)
                    stream.write(json.dumps(s)+"\n")
    return load_frame(path)


def test_analytic_brier_and_identical_pairs_through_all_checks(tmp_path):
    frame = fixture_frame(tmp_path)
    assert frame.model_loss.iloc[0] == pytest.approx(.08)
    assert frame.market_loss.iloc[0] == pytest.approx(.02)
    one = check1(frame)["before_20260823"]
    assert one["by_hour"][8]["raw"]["ratio"]["estimate"] == pytest.approx(4)
    assert one["morning_06_10"]["raw"]["ratio"]["market_days"] == 16
    assert one["lag_by_hour"][8]["censored"] == 16
    two = check2(frame)["before_20260823"]
    assert two["all"]["model_winner_distance"]["estimate"] == 0
    four = check4(frame, tmp_path)
    assert len(four["paired_comparisons"]) == 15
    scores = pd.read_csv(tmp_path / "guidance_paired_snapshot_scores.csv")
    fitted = scores[scores.variant.isin(["nws", "open_meteo", "hrrr"])]
    assert fitted.training_dates.min() == 5
    assert (fitted.latest_training_date < fitted.date).all()
    assert fitted.date.min() == "2026-08-06"
    five = check5(frame, pd.DataFrame(), tmp_path)["before_20260823"]
    assert five["total_days"] == 16
    assert five["tags"]["low_ceiling"]["status"] == "NO_DATA"


def test_weather_tags_preserve_missing_and_circular_wind_direction():
    rows = pd.DataFrame({"utc": pd.to_datetime(["2026-08-01T12:00Z", "2026-08-01T14:00Z"]),
                         "hour": [12, 14], "metar": ["x", "y"], "drct": [350, 10],
                         "dwpf": [70, 60], "alti": [29.9, 30.1], "skyc1": ["BKN", "CLR"],
                         "skyl1": [3000, np.nan], "wxcodes": ["TSRA", ""]})
    tags = observation_tags(rows, False)
    assert tags["wind_shift"] == 0
    assert tags["front_proxy"] == 0
    assert tags["low_ceiling"] == 1
    assert tags["thunder_or_showers"] == 1
    assert tags["coastal_stratus"] is None


def test_manifest_requires_every_exact_archive_and_valid_hash():
    good = {n: "a"*64 for n in ("mi-core.tgz", "mi-tape.tgz", "mi-books-sample.tgz")}
    assert manifest_entries({"archives": good}) == good
    with pytest.raises(ValueError):
        manifest_entries({"archives": {"mi-core.tgz": "a"*64}})


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "/escape", "x\\escape", "x:stream"])
def test_unpack_rejects_unsafe_members(tmp_path, name):
    archive = tmp_path / "test.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo(name)
        member.size = 1
        tar.addfile(member, io.BytesIO(b"x"))
    destination = tmp_path / "scratch"
    destination.mkdir()
    with pytest.raises(ValueError, match="unsafe"):
        safe_unpack(archive, destination)


def test_scratch_guard_rejects_data_and_mirrors(tmp_path):
    with pytest.raises(ValueError):
        scratch_path(tmp_path / "data" / "scratch")
    with pytest.raises(ValueError):
        scratch_path(tmp_path / "weather-mirror" / "scratch")


def test_tail_ranks_excess_while_accumulating_cadence_adjusted_contributions():
    frame = pd.DataFrame({"excess": [1., .9], "weighted": [.1, .9]})
    assert len(tail_selection(frame, "weighted", rank="excess")) == 2
