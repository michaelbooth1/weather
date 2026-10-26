"""R-Z (lane L3): HRRR 3x3 spread width lever, history-only research module.

Guards: the R-Z rule (``C:/t/l3/rz/rule_rz.md``, sha pinned in the module): z from the 3x3 block's cell-wise
day-max, gamma = 0 reproduces the base sigma exactly, absent cells are never imputed, CYYZ and post-history
selections are dropped, and the workstation offline allowlist admits the module exactly.
"""
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from weather.calibration import rz_hrrr_spread as rz

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.rz_hrrr_spread"


def test_spread_of_cells_uses_population_sd_and_floor():
    z, sd = rz.spread_of_cells([70.0] * 8 + [79.0])
    assert sd == pytest.approx(float(np.std([70.0] * 8 + [79.0])))
    assert z == pytest.approx(math.log(sd))
    z0, sd0 = rz.spread_of_cells([70.0] * 9)
    assert sd0 == 0.0 and z0 == pytest.approx(math.log(rz.SD_FLOOR_F))


def test_gamma_zero_reproduces_base_sigma_exactly():
    s = np.array([0.4, 1.0, 2.5, 3.7])
    z = np.array([-1.0, 0.3, 2.0, 0.0])
    zbar = np.array([0.5, 0.1, -0.2, 0.0])
    assert np.array_equal(rz.sigma_rz(s, z, zbar, 0.0), np.maximum(s, 1.0))
    wide = rz.sigma_rz(s, z, zbar, 1.0)
    assert wide[2] > max(s[2], 1.0) and wide[0] < 1.0


def test_rule_pin_refuses_other_text(tmp_path):
    p = tmp_path / "rule.md"
    p.write_text("not the rule", encoding="utf-8")
    with pytest.raises(rz.RZError):
        rz.check_rule(p)


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_hrrr_spread_cellwise_max_and_absence(tmp_path):
    (tmp_path / "stations.json").write_text(json.dumps({"KAAA": {}, "CYYZ": {}}), encoding="utf-8")
    k = lambda f: (f - 32.0) * 5.0 / 9.0 + 273.15  # noqa: E731
    b1 = [k(70.0)] * 9
    b2 = [k(70.0)] * 8 + [k(79.0)]
    man = [
        {"status": "ok", "var": rz.TMP_VAR, "cycle_utc": "C1", "fh": 1, "points": {"KAAA": {"block3x3": b1},
                                                                                   "CYYZ": {"block3x3": b1}}},
        {"status": "ok", "var": rz.TMP_VAR, "cycle_utc": "C1", "fh": 2, "points": {"KAAA": {"block3x3": b2}}},
        {"status": "ok", "var": "TCDC:entire atmosphere", "cycle_utc": "C1", "fh": 3, "points": {}},
    ]
    sel = [
        {"station": "KAAA", "local_date": "2025-08-01", "hour_local": 7, "cycle_utc": "C1", "fhs": [1, 2]},
        {"station": "KAAA", "local_date": "2025-08-02", "hour_local": 7, "cycle_utc": "C1", "fhs": [1, 3]},
        {"station": "CYYZ", "local_date": "2025-08-01", "hour_local": 7, "cycle_utc": "C1", "fhs": [1]},
        {"station": "KAAA", "local_date": "2026-08-01", "hour_local": 7, "cycle_utc": "C1", "fhs": [1]},
    ]
    mp = _write(tmp_path / "manifest.jsonl", man)
    sp = _write(tmp_path / "selections.jsonl", sel)
    frame, stats, _ = rz.hrrr_spread(tmp_path, mp, sp)
    assert len(frame) == 1 and stats["absent"] == 1 and stats["excluded_station"] == 1
    assert stats["after_history"] == 1
    assert frame.sd9.iloc[0] == pytest.approx(float(np.std([70.0] * 8 + [79.0])), abs=1e-9)
    with pytest.raises(rz.RZError):
        rz.hrrr_spread(tmp_path, "0" * 64, sp)


def test_selection_after_data_window_refuses(tmp_path):
    (tmp_path / "stations.json").write_text(json.dumps({"KAAA": {}}), encoding="utf-8")
    mp = _write(tmp_path / "manifest.jsonl", [])
    sp = _write(tmp_path / "selections.jsonl", [{"station": "KAAA", "local_date": "2026-09-30", "hour_local": 7}])
    with pytest.raises(rz.RZError):
        rz.hrrr_spread(tmp_path, mp, sp)


def _hook():
    spec = importlib.util.spec_from_file_location("rz_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_rz_module_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration.rz_hrrr"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} p0 --research-root r --nbm-corpus n --hrrr-0712 a '
                   f'--hrrr-0006 b --rule x --out o'
    }}, constrained_capture_host=False) is not None


def test_ps1_mirror_lists_the_module():
    text = (ROOT / "scripts" / "ops" / "workload_admission.ps1").read_text(encoding="utf-8")
    assert f'"{MODULE}",' in text
