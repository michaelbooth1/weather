"""R-V MOS/NBE day-max column (rule_rv.md).

Guards: the per-source run choice is the rule's (GFS latest of 06Z/00Z, NAM 00Z, NBE the early 00Z/01Z cycle, never
a 07Z/12Z run), the fixed availability lags and the [-40, 130] F range apply, ``mos_x`` needs two of three sources,
the fetcher drops runtimes after 2026-09-29 and records file shas that the loader enforces, and gates 1a/1b read
inputs only.
"""
import importlib
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

prm = importlib.import_module("weather.calibration.pooled_residual_model")
UTC = timezone.utc
D = date(2023, 8, 20)
FT = datetime(2023, 8, 21, tzinfo=UTC)


def _rt(hour):
    return datetime(2023, 8, 20, hour, tzinfo=UTC)


def test_gfs_takes_the_latest_available_d_bearing_run():
    values = {(_rt(0), FT): 90.0, (_rt(6), FT): 92.0, (_rt(12), FT): 99.0}
    assert prm.rv_source_value(values, "GFS", D, datetime(2023, 8, 20, 17, tzinfo=UTC)) == (92.0, _rt(6))
    # 06Z + 4h30 = 10:30Z: before that only the 00Z run is usable
    assert prm.rv_source_value(values, "GFS", D, datetime(2023, 8, 20, 10, 29, tzinfo=UTC)) == (90.0, _rt(0))


def test_nbe_uses_the_early_cycle_never_07z():
    values = {(_rt(1), FT): 88.0, (_rt(7), FT): 95.0}
    assert prm.rv_source_value(values, "NBE", D, datetime(2023, 8, 20, 20, tzinfo=UTC)) == (88.0, _rt(1))
    assert prm.rv_source_value({(_rt(0), FT): 87.0}, "NBE", D, datetime(2023, 8, 20, 20, tzinfo=UTC))[0] == 87.0


def test_nam_only_00z_and_range_check():
    assert prm.rv_source_value({(_rt(12), FT): 90.0}, "NAM", D, datetime(2023, 8, 21, tzinfo=UTC))[1] is None
    value, run = prm.rv_source_value({(_rt(0), FT): 140.0}, "NAM", D, datetime(2023, 8, 21, tzinfo=UTC))
    assert run is None and value != value


def test_mos_x_needs_two_sources():
    tz = timezone(timedelta(hours=-4))
    one = {("KATL", "GFS"): {(_rt(6), FT): 90.0}}
    assert prm.rv_entry(one, "KATL", D, 13, tz)["mos_x"] != prm.rv_entry(one, "KATL", D, 13, tz)["mos_x"]
    two = {("KATL", "GFS"): {(_rt(6), FT): 90.0}, ("KATL", "NBE"): {(_rt(1), FT): 86.0}}
    entry = prm.rv_entry(two, "KATL", D, 13, tz)
    assert entry["mos_x"] == 88.0 and prm.rv_columns(entry, 87.5)["v_gap"] == 0.5
    named = prm.rv_entry(two, "KATL", D, 13, "America/New_York")  # registry IANA name (EDT on D)
    assert named["mos_x"] == entry["mos_x"] and named["src_GFS"] == entry["src_GFS"]


def test_fetch_drops_post_cutoff_rows_and_loader_enforces_shas(tmp_path):
    body = ("runtime,ftime,model,n_x,txn\n"
            "2026-09-29 00:00:00,2026-09-30 00:00:00,GFS,80,\n"
            "2026-09-30 00:00:00,2026-10-01 00:00:00,GFS,81,\n")
    urls = []

    def opener(url):
        urls.append(url)
        return body

    out = tmp_path / "mos"
    manifest = prm.rv_fetch(out_dir=out, years=[2026], markets=("atlanta",), spacing=0, opener=opener,
                            sleep=lambda s: None)
    assert len(urls) == 3 and all("2026-09-29T23%3A59Z" in u for u in urls)
    kept = (out / "KATL_GFS_2026.csv").read_text(encoding="utf-8").splitlines()[1:]
    assert [ln[:10] for ln in kept] == ["2026-09-29"]  # the 09-30 runtime is dropped; its 09-30 ftime is not a runtime
    table, _ = prm.rv_load(out, years=[2026])
    assert table[("KATL", "GFS")] == {(datetime(2026, 9, 29, tzinfo=UTC), datetime(2026, 9, 30, tzinfo=UTC)): 80.0}
    assert set(manifest["files"]) == {"KATL_GFS_2026.csv", "KATL_NAM_2026.csv", "KATL_NBE_2026.csv"}
    (out / "KATL_GFS_2026.csv").write_text(body, encoding="utf-8")
    with pytest.raises(prm.PooledModelError):
        prm.rv_load(out, years=[2026])


def test_fetch_refuses_after_2026():
    with pytest.raises(prm.PooledModelError):
        prm.rv_fetch_windows([2027])


def test_gates_1a_and_1b():
    stats = {"rows": 100, "rows_covered": 96, "rows_2021": 100, "GFS_2021": 99, "NAM_2021": 97, "NBE_2021": 90}
    g = prm.rv_gate_1a(stats)
    assert g["pass"] and g["per_source_year"]["NBE"]["2021"] == 0.9
    assert not prm.rv_gate_1a({**stats, "rows_covered": 94})["pass"]
    frame = pd.DataFrame({"target_date": ["2021-08-01", "2022-08-01"], "fh": [80.0, 80.0],
                          "src_GFS": [81.0, 84.0], "src_NAM": [81.0, 84.0], "src_NBE": [81.0, 84.0],
                          "v_gap": [1.0, 5.0]})
    assert not prm.rv_gate_1b(frame)["pass"]  # each year is 2.0 F from the pooled 3.0 F
    frame["v_gap"] = [1.0, 4.0]
    assert prm.rv_gate_1b(frame)["pass"]  # 1.5 F is allowed


def test_arms_and_rule_sha_recorded():
    assert set(prm.RV_ARMS) == {"B_N", "P3d_N_fix", "P3d_V", "P3d_I"}
    assert prm.RV_ARMS["P3d_V"]["extra_hgb"] == ("v_gap",)
    assert len(prm.RV_ARMS["P3d_I"]["extra_ols"]) == 10
    assert len(prm.RV_RULE_SHA256) == 64
    json.dumps(prm.RV_SOURCES)
