"""ECMWF ENS station-point adapter and G2 lookup (lane G2): byte-range grouping, interpolation,
point-in-time run choice; the eccodes decode path runs only where eccodes is installed (research venv).

Guards: owner approval 2026-10-23 (lane G2) that eccodes stays a research-only extra (lazy import,
never required by the project venv) and that a source counts only when available at serve.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.sources.free_screens import ecmwf_ens


def test_eccodes_is_imported_lazily_never_at_module_level():
    tree = ast.parse(Path(ecmwf_ens.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name for n in top for a in n.names} | {n.module for n in top if isinstance(n, ast.ImportFrom)}
    assert "eccodes" not in names
    inner = [n for n in ast.walk(tree) if isinstance(n, ast.Import) and any(a.name == "eccodes" for a in n.names)]
    assert len(inner) == 1


def test_clusters_merge_small_gaps_only():
    f = [{"_offset": 0, "_length": 10}, {"_offset": 15, "_length": 10}, {"_offset": 5_000_000, "_length": 10}]
    groups = ecmwf_ens.clusters(f, tol=100)
    assert [[x["_offset"] for x in g] for g in groups] == [[0, 15], [5_000_000]]


def test_bilinear_weights_sum_to_one_and_hit_grid_points_exactly():
    w = ecmwf_ens.bilinear_weights(40.0, -90.0)
    assert sum(x[1] for x in w) == pytest.approx(1.0)
    exact = [x for x in w if x[1] > 0]
    assert exact == [((50 * 4) * 1440 + 90 * 4, 1.0)]       # lat 40 -> row 200, lon -90 -> col 360
    w = ecmwf_ens.bilinear_weights(40.1, -89.9)
    assert len([x for x in w if x[1] > 0]) == 4 and sum(x[1] for x in w) == pytest.approx(1.0)


def test_run_dates_stop_on_the_last_development_day():
    runs = ecmwf_ens.run_dates()
    assert max(runs).isoformat() == "2026-09-29" and min(runs).isoformat() == "2024-08-15"


def test_eccodes_decode_reads_a_station_value():
    eccodes = pytest.importorskip("eccodes")
    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        eccodes.codes_set(h, "Ni", 4)
        eccodes.codes_set(h, "Nj", 3)
        eccodes.codes_set(h, "latitudeOfFirstGridPointInDegrees", 1.0)
        eccodes.codes_set(h, "longitudeOfFirstGridPointInDegrees", 0.0)
        eccodes.codes_set(h, "latitudeOfLastGridPointInDegrees", -1.0)
        eccodes.codes_set(h, "longitudeOfLastGridPointInDegrees", 3.0)
        eccodes.codes_set(h, "iDirectionIncrementInDegrees", 1.0)
        eccodes.codes_set(h, "jDirectionIncrementInDegrees", 1.0)
        eccodes.codes_set_values(h, np.arange(12, dtype=float))
        msg = eccodes.codes_get_message(h)
    finally:
        eccodes.codes_release(h)
    from weather.sources.free_screens.common import Station

    _, vals = ecmwf_ens.decode_points(msg, [Station("x", "KX", "UTC", 0.0, 1.0)])
    assert vals["KX"] == pytest.approx(5.0)                   # row 1, col 1


def test_g2_lookup_uses_only_runs_available_at_the_query(monkeypatch):
    from weather.reporting.scorecards.free_source_candidates import g2_ens

    frame = pd.DataFrame({"station": ["KX", "KX"], "target_date": ["2026-08-02", "2026-08-02"],
                          "run": ["2026-08-01", "2026-08-02"], "ens_mean_f": [80.0, 90.0], "ens_sd_f": [1.0, 2.0],
                          "n_members": [51, 51],
                          "available_utc": pd.to_datetime(["2026-08-01T09:00Z", "2026-08-02T09:00Z"], utc=True)})
    frame["available_utc"] = frame.available_utc.astype("datetime64[us, UTC]")
    monkeypatch.setitem(g2_ens._CACHE, "points", (frame, "sha"))
    mean, sd = g2_ens.lookup(["KX", "KX", "KX"], ["2026-08-02"] * 3,
                             pd.to_datetime(["2026-08-01T08:59Z", "2026-08-02T08:59Z", "2026-08-02T09:00Z"], utc=True))
    assert np.isnan(mean[0]) and mean[1] == 80.0 and mean[2] == 90.0 and sd[2] == 2.0
