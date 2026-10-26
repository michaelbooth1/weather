"""Lane L2 rung R-R: RN-1's land-aware point rule on the HRRR 07-12 joiner (inputs only, no outcome join).

Guards: L13's R-R pre-registration (rule_rr.md sha e3d92e1a..., Point rule) - the chosen cell is the land cell of
the stored 3x3 block nearest (fi, fj), ties to the lower index, read as block3x3[chosen] for TMP and TCDC; a block
with no land cell gives k_miss = 1; R-K's nearest-cell reading is unchanged when no point map is given.
"""
import hashlib
import importlib
import json
import math

import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

MARKETS = ("san-francisco", "atlanta")
# KSFO-like: centre (index 4) is water; KATL: all land
STATIONS = {"KSFO": {"market": "san-francisco", "tz": "America/Los_Angeles", "i": 178, "j": 594,
                     "fi": 177.89484086990853, "fj": 594.4963606137516},
            "KATL": {"market": "atlanta", "tz": "America/New_York", "i": 1302, "j": 377,
                     "fi": 1302.2445562292987, "fj": 377.00477929978695}}
MASKS = {"KSFO": [1, 1, 0, 1, 0, 0, 1, 0, 0], "KATL": [1] * 9}


def _dist(s):
    return [math.hypot(s["i"] + k % 3 - 1 - s["fi"], s["j"] + k // 3 - 1 - s["fj"]) for k in range(9)]


def _write_corpus(tmp_path, chosen=None, masks=MASKS):
    (tmp_path / "stations.json").write_text(json.dumps(STATIONS), encoding="utf-8")
    stations_sha = hashlib.sha256((tmp_path / "stations.json").read_bytes()).hexdigest()
    land = {"stations_json_sha256": stations_sha, "stations": {}}
    for icao, s in STATIONS.items():
        land["stations"][icao] = {**{k: s[k] for k in ("i", "j", "fi", "fj")}, "land_block3x3": masks[icao],
                                  "dist_grid_units": _dist(s),
                                  "rn1_chosen_index": (chosen or {"KSFO": 3, "KATL": 4})[icao]}
    path = tmp_path / "land.json"
    path.write_text(json.dumps(land), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_rn1_recomputes_the_land_cell_nearest_the_station_and_refuses_a_disagreeing_file(tmp_path):
    land, sha = _write_corpus(tmp_path)
    point, report = prm.rr_point_rule(land, tmp_path, MARKETS, expected={"land_sha256": sha, "index": {"KSFO": 3}})
    assert point == {"KSFO": 3, "KATL": 4}
    assert report["stations"]["KSFO"]["n_land"] == 4
    with pytest.raises(prm.PooledModelError):  # pinned sha differs
        prm.rr_point_rule(land, tmp_path, MARKETS, expected={"land_sha256": "0" * 64, "index": {"KSFO": 3}})
    land2, sha2 = _write_corpus(tmp_path, chosen={"KSFO": 7, "KATL": 4})  # 7 is water: file disagrees
    with pytest.raises(prm.PooledModelError):
        prm.rr_point_rule(land2, tmp_path, MARKETS, expected={"land_sha256": sha2, "index": {"KSFO": 3}})
    with pytest.raises(prm.PooledModelError):  # the coordinator's reading disagrees with the rule
        prm.rr_point_rule(land, tmp_path, MARKETS, expected={"land_sha256": sha, "index": {}})


def test_rn1_no_land_cell_is_k_miss_and_values_come_from_the_chosen_block_entry(tmp_path):
    masks = {"KSFO": [0] * 9, "KATL": [1] * 9}
    land, sha = _write_corpus(tmp_path, chosen={"KSFO": None, "KATL": 4}, masks=masks)
    point, _ = prm.rr_point_rule(land, tmp_path, MARKETS, expected={"land_sha256": sha, "index": {"KSFO": None}})
    assert point == {"KATL": 4}
    cycle, snap, latest = "2023-08-01T09:00:00+00:00", "2023-08-01T11:00:00+00:00", "2023-08-01T10:10:00+00:00"
    sel = [{"station": icao, "local_date": "2023-08-01", "hour_local": 7, "snapshot_utc": snap, "cycle_utc": cycle,
            "fhs": [2, 3], "latest_available_utc": latest} for icao in ("KATL",)]
    sel.append({"station": "KSFO", "local_date": "2023-08-01", "hour_local": 7,
                "snapshot_utc": "2023-08-01T14:00:00+00:00", "cycle_utc": "2023-08-01T12:00:00+00:00",
                "fhs": [2], "latest_available_utc": "2023-08-01T13:10:00+00:00"})
    with open(tmp_path / "selections.jsonl", "w", encoding="utf-8") as w:
        for s in sel:
            w.write(json.dumps(s) + "\n")
    with open(tmp_path / "manifest.jsonl", "w", encoding="utf-8") as w:
        for fh in (2, 3):
            for var, base in (("TMP", 290.0), ("TCDC", 10.0)):
                block = [base + k for k in range(9)]
                w.write(json.dumps({"cycle_utc": cycle, "fh": fh, "idx_record": f"{prm.RK_VARIABLES[var]}:{fh} hour fcst:",
                                    "key": f"hrrr.20230801/conus/hrrr.t09z.wrfsfcf{fh:02d}.grib2",
                                    "points": {"KATL": {"nearest": block[4], "block3x3": block}}}) + "\n")
    hrrr, stats = prm.rk_hrrr_columns(tmp_path, MARKETS, hours=prm.RR_HOURS, point=point)
    atl = hrrr[("atlanta", "2023-08-01", 7)]
    assert atl["k_miss"] == 0.0 and atl["k_max"] == pytest.approx((294.0 - 273.15) * 9 / 5 + 32)
    assert atl["k_tcdc"] == pytest.approx(14.0)
    assert hrrr[("san-francisco", "2023-08-01", 7)]["reason"] == "no_land_cell"
    assert stats["selection_no_land_cell"] == 1 and stats.get("manifest_nearest_not_block_centre", 0) == 0
    hrrr3, _ = prm.rk_hrrr_columns(tmp_path, MARKETS, hours=prm.RR_HOURS, point={"KATL": 3, "KSFO": 3})
    assert hrrr3[("atlanta", "2023-08-01", 7)]["k_max"] == pytest.approx((293.0 - 273.15) * 9 / 5 + 32)
    nearest, _ = prm.rk_hrrr_columns(tmp_path, MARKETS, hours=prm.RR_HOURS)  # R-K reading, unchanged
    assert nearest[("atlanta", "2023-08-01", 7)]["k_max"] == atl["k_max"]
    dev_only, _ = prm.rk_hrrr_columns(tmp_path, MARKETS, hours=prm.RR_HOURS, point=point,
                                      day_filter=lambda d: d >= "2026-07-30")
    assert dev_only == {}
