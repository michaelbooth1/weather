"""R-ODC PROXY feature source (ledger row 70): the IEM archive adapter, the map swap, and the proof that the default
``rodc-gate2`` path is byte-identical to the bound G2 code at 188d5c382 on the synthetic fixture."""
import gzip
import importlib.util
import json
import math
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from tests.calibration import test_rodc_gate2_synthetic as syn
from weather.calibration import cool_season_audit as cs
from weather.calibration import rodc_gate2 as g
from weather.calibration import rodc_iem_proxy as iem

BASE_COMMIT = "188d5c382ac041a6ae276eebcac2b957463f885a"
REPO = Path(__file__).resolve().parents[2]
NAN = float("nan")


def _write_month(root, icao, year, month, rows):
    p = Path(root) / icao / "hourly" / f"year={year}" / f"month={month:02d}" / "observations.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _row(local, temp, dew, offset="-04:00"):
    return {"valid_time_local": f"{local}:00{offset}", "temp_native": temp, "dewpoint_native": dew,
            "local_date": local[:10], "local_time": local[11:16]}


@pytest.fixture()
def archive(tmp_path):
    _write_month(tmp_path, "katl", 2023, 11, [
        _row("2023-10-31T23:59", 20.0, 10.0),            # the previous day: never in D's window
        _row("2023-11-01T00:52", 46.004, 23.0),
        _row("2023-11-01T03:52", 41.49, 22.6),
        _row("2023-11-01T05:10", None, 30.0),             # no temperature: skipped for the low
        _row("2023-11-01T07:00", 42.5, 24.5),             # exactly h:00 is in the h07 window
        _row("2023-11-01T07:00", 43.0, None),             # same minute, later in the file: the latest row
        _row("2023-11-01T07:01", 30.0, 5.0),              # one minute after h:00: look-ahead, excluded
        _row("2023-11-01T11:52", 39.5, 21.5),
        _row("2023-11-02T00:10", 10.0, 1.0),              # the next day
    ])
    return iem.Archive(tmp_path)


def test_window_is_date_d_and_at_or_before_h00(archive):
    low, dew = archive.features("atlanta", "2023-11-01", 7)
    # mg_serve_core.wu_whole_f (the serve T-group conversion): 41.49 F -> 5.3 C -> 41.54 F -> 42, the window min;
    # 07:01 (30), the previous and the next day are excluded
    assert low == 42.0
    assert math.isnan(dew)  # the latest window row (07:00, second in file order) has no dewpoint


def test_look_ahead_refused_by_construction(archive):
    assert archive.features("atlanta", "2023-11-01", 7)[0] == 42.0  # 07:01 (30 F) is after 07:00
    for hour in (8, 9, 10, 11):
        assert archive.features("atlanta", "2023-11-01", hour)[0] == 30.0  # ... and inside h08's window
    assert archive.features("atlanta", "2023-11-01", 12) == (30.0, 22.0)  # 07:01 and 11:52 now in; 21.5 half_up
    assert archive.features("atlanta", "2023-11-01", 3) == (46.0, 23.0)  # 03:52 is after 03:00


def test_half_up_and_missing_rules(tmp_path):
    _write_month(tmp_path, "klga", 2024, 12, [_row("2024-12-05T06:30", 30.5, -2.5, "-05:00")])
    a = iem.Archive(tmp_path)
    assert a.features("nyc", "2024-12-05", 7) == (31.0, -3.0)  # -2.5 F -> -19.2 C -> -2.56 F
    assert all(math.isnan(x) for x in a.features("nyc", "2024-12-06", 7))  # no window row
    assert all(math.isnan(x) for x in a.features("nyc", "2024-10-05", 7))  # no month file


def test_refuses_dates_outside_the_dev_window(archive):
    for day in ("2026-11-01", "2025-09-29", "2020-12-31"):
        with pytest.raises(iem.IemProxyError, match="dev window"):
            archive.features("atlanta", day, 7)
    with pytest.raises(iem.IemProxyError, match="no archive station"):
        archive.features("toronto", "2023-11-01", 7)


def test_swap_maps_changes_only_the_two_values(archive):
    key = ("atlanta", "2023-11-09", "2023-11-01", 7)
    low_map, dew_map = {key: (99.0, 50.0)}, {key: (50.0, None)}
    low2, dew2, stats = iem.swap_maps(low_map, dew_map, archive)
    assert set(low2) == set(low_map) and set(dew2) == set(dew_map)
    assert low2[key] == (42.0, 50.0) and dew2[key][0] == 50.0 and math.isnan(dew2[key][1])
    assert stats == {"low_n": 1, "low_nan": 0, "low_eq_source": 0, "dew_n": 1, "dew_nan": 1, "dew_eq_source": 1}
    assert iem.provenance(archive)["files_read"] == 1


def test_default_metar_root_is_beside_research_root(tmp_path):
    assert iem.default_metar_root(tmp_path / "data" / "research") == tmp_path / "data" / "metar"


def test_cli_default_feature_source_is_records(monkeypatch):
    seen = {}
    monkeypatch.setattr(g, "gate2", lambda **kw: seen.update(kw) or
                        {"verdict": "x", "headline": {}, "selection": {"g2_selected_folds": 0}, "rows_sha256": "x"})
    base = []
    for flag in ("--nbm-corpus", "--records-root", "--research-root", "--state-0712", "--hrrr-2123", "--sums-2123",
                 "--hrrr-2425", "--land", "--l6-state", "--sm-state", "--mg2-coefficients", "--blend-weights",
                 "--ladder-cache", "--ladder-cache-sha256", "--gate1-json", "--gate1-rows", "--rule",
                 "--rule-sha256", "--commit", "--out"):
        base += [flag, "v"]
    cs.main(["rodc-gate2", *base])
    assert seen["feature_source"] == "records"
    cs.main(["rodc-gate2", *base, "--feature-source", "iem-proxy"])
    assert seen["feature_source"] == "iem-proxy"
    with pytest.raises(SystemExit):
        cs.main(["rodc-gate2", *base, "--feature-source", "other"])


def _base_module(tmp_path):
    try:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{BASE_COMMIT}:src/weather/calibration/rodc_gate2.py"],
                             check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("the base commit is not reachable from this checkout")
    path = tmp_path / "rodc_gate2_base.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("weather.calibration._rodc_gate2_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _patch_like_g(monkeypatch, mod):
    for name in ("sm_nowcast_map", "ladder_cache_manifest", "load_low_map", "load_dew_map"):
        monkeypatch.setattr(mod, name, getattr(g, name))


def test_default_path_is_byte_identical_to_the_bound_g2_code(tmp_path, monkeypatch, syn_planted):
    frame, frozen = syn_planted
    syn._wire(monkeypatch, frame, frozen)
    syn._gate1(tmp_path)
    base = _base_module(tmp_path)
    _patch_like_g(monkeypatch, base)
    monkeypatch.setattr(iem, "Archive", lambda root: pytest.fail("the default path must not read the archive"))
    out = {}
    for tag, mod in (("base", base), ("new", g)):
        d = tmp_path / tag
        d.mkdir()
        mod.gate2(nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H2123",
                  sums_2123="x", hrrr_2425="H2425", land="l", l6_state="l6", sm_state="sm", mg2_coefficients="c",
                  blend_weights="w", ladder_cache="lc", ladder_cache_sha256="c" * 64, gate1_json="g1",
                  gate1_rows=tmp_path / "gate1_rows.csv.gz", rule="rule", rule_sha256="r" * 64,
                  out_path=d / "gate2.json", commit="synthetic")
        out[tag] = (json.loads((d / "gate2.json").read_text(encoding="utf-8")), (d / "gate2_rows.csv.gz").read_bytes())
    (pb, rb), (pn, rn) = out["base"], out["new"]
    assert gzip.decompress(rb) == gzip.decompress(rn)  # the scored rows, byte for byte (gzip header mtime aside)
    assert pb.pop("module_sha256") != pn.pop("module_sha256")  # only the module's own hash may differ
    assert pb == pn and "feature_source" not in pn


def test_iem_proxy_swaps_only_the_columns_and_records_provenance(tmp_path, monkeypatch, syn_planted):
    frame, frozen = syn_planted
    syn._wire(monkeypatch, frame, frozen)
    syn._gate1(tmp_path)
    low, dew = syn._maps(frame)

    class Fake:
        files = {"katl/x": "0" * 64}
        root = tmp_path

        def __init__(self, root):
            pass

        def features(self, m, d, h):
            key = next(k for k in low if k[0] == m and k[2] == d and k[3] == h)
            return low[key][0] - 1.0, 7.0

    monkeypatch.setattr(iem, "Archive", Fake)
    res = g.gate2(
        nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H2123", sums_2123="x",
        hrrr_2425="H2425", land="l", l6_state="l6", sm_state="sm", mg2_coefficients="c", blend_weights="w",
        ladder_cache="lc", ladder_cache_sha256="c" * 64, gate1_json="g1", gate1_rows=tmp_path / "gate1_rows.csv.gz",
        rule="rule", rule_sha256="r" * 64, out_path=tmp_path / "gate2.json", commit="synthetic",
        feature_source="iem-proxy")
    fs = res["feature_source"]
    assert fs["name"] == "iem-proxy" and fs["ledger_row"] == 70 and fs["files_read"] == 1
    assert fs["swap_stats"]["low_n"] == fs["swap_stats"]["dew_n"] == len(frame)
    assert fs["swap_stats"]["low_eq_source"] == 0
    assert res["control"]["pass"]  # gate 1's G1 is untouched by the feature source
    assert res["counts"]["columns_score"]["dewpoint_nan"] == 0
    rows = pd.read_csv(tmp_path / "gate2_rows.csv.gz")
    assert len(rows) == len(frame)


def test_unknown_feature_source_refuses_before_any_output(tmp_path):
    with pytest.raises(g.RodcGate2Error, match="unknown feature source"):
        g.gate2(nbm_corpus="n", records_root="rr", research_root="rs", state_0712="s", hrrr_2123="H", sums_2123="x",
                hrrr_2425="H", land="l", l6_state="l6", sm_state="sm", mg2_coefficients="c", blend_weights="w",
                ladder_cache="lc", ladder_cache_sha256="c" * 64, gate1_json="g1", gate1_rows="r", rule="rule",
                rule_sha256="r" * 64, out_path=tmp_path / "gate2.json", commit="x", feature_source="other")
    assert not (tmp_path / "gate2.json").exists()


@pytest.fixture(scope="module")
def syn_planted():
    frame = syn._frame(True)
    return frame, syn._frozen(frame.drop(columns=["_low", "_dew"]))
