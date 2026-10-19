"""Synthetic checks for the lever-5 stage replay (no captured data)."""
import json
from datetime import datetime, timezone

import pytest

from tools.research.model_edge_lever5 import stage_replay as l5
from weather.model.toronto_model import TorontoHighTempModel

READINGS = ((7, 22.0), (11, 28.0), (13, 30.0), (15, 31.7), (17, 30.0), (19, 27.8), (21, 25.6))
FEATURE = {84: 0.1, 86: 0.2, 88: 0.3, 89: 0.2, 90: 0.1, 92: 0.1}


def _factory(market_id):
    model = TorontoHighTempModel(market_id=market_id)
    model.calibrated_weights = None
    model.predict_feature_distribution = lambda sources, cutoff_hour, now: (dict(FEATURE), "hgb")
    model.predict_late_day_continuation = lambda sources, cutoff_hour, now: None
    return model


def _record(sid, hour, target="2026-09-20"):
    model = TorontoHighTempModel(market_id="atlanta", target_date=target)
    y, m, d = (int(p) for p in target.split("-"))
    payload = [{
        "reportTime": datetime(y, m, d, h, 52, tzinfo=model.spec.tz)
        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temp": t, "icaoId": "KATL",
    } for h, t in READINGS if h <= hour]
    rows = model.parse_metar_payload(payload)
    metar = {"station_id": "KATL", "rows": rows, "latest": rows[-1], "target_date_match": True,
             "temp_native": rows[-1]["temp_native"], "temp_c": rows[-1]["temp_native"],
             "max_since_7am_native": model.station_max_since_7am_from_rows(rows),
             "same_day_max_native": max(r["temp_native"] for r in rows)}
    nbm = {"available": True, "station_id": "KATL", "target_date": target,
           "percentiles": {"10": 85.0, "25": 87.0, "50": 89.0, "75": 91.0, "90": 93.0},
           "mean_native": 89.0, "stddev_native": 2.5}
    return {"snapshot_id": sid, "target_date": target,
            "built_at": datetime(y, m, d, hour, 55, tzinfo=model.spec.tz).isoformat(),
            "sources": {"metar": {"ok": True, "data": metar},
                        "nbm_probabilistic_tmax": {"ok": True, "data": nbm}}}


def test_nbm_never_reaches_post_processing_and_centering_acts_only_in_window(tmp_path):
    folder = tmp_path / "snaps" / "highest-temperature-in-atlanta-on-september-20-2026"
    folder.mkdir(parents=True)
    with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
        for hour in (9, 16, 21):
            handle.write(json.dumps(_record(f"s{hour}", hour)) + "\n")
    summary = l5.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "out.jsonl",
                     list(l5.VARIANTS), model_factory=_factory)
    assert summary["snapshots"] == 3 and summary["nbm_present_snapshots"] == 3
    for variant in ("nbm_removed", "nbm_perturbed", "wu_residual_repointed",
                    "metar_live_signal_repointed", "intraday_tail_repointed"):
        block = summary["variants"][variant]["all"]
        assert block["errors"] == 0 and block["max_tv"] == 0.0, variant
    rows = {r["hour"]: r for r in map(json.loads, (tmp_path / "out.jsonl").read_text().splitlines())}
    assert rows[9]["variants"]["centering_reenabled"]["tv"] == 0.0
    assert rows[21]["variants"]["centering_reenabled"]["tv"] == 0.0


def test_out_of_window_dates_are_refused(tmp_path):
    with pytest.raises(l5.Refused):
        l5.compare_record(_factory("atlanta"), _record("late", 21, target="2026-09-30"),
                          "atlanta", ["nbm_removed"])
