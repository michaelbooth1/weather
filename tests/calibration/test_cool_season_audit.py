"""CS-1 (lane L3): cool-season transfer audit, history-only research module.

Guards: the CS-1 rule (``C:/t/l3/coolseason/rule_cs.md``, sha pinned in the module): the integer-bucket Brier,
the pre-declared transfer reading, sha-bound state loading and the offline allowlist entry.
"""
import importlib.util
import pickle
import sys
from pathlib import Path

import pytest

from weather.calibration import cool_season_audit as cs

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.cool_season_audit"


def test_brier_from_dist_matches_one_hot_sum():
    dist = {70: 0.2, 71: 0.5, 72: 0.3}
    expected = (0.2 ** 2) + (0.5 - 1) ** 2 + 0.3 ** 2
    assert cs.brier_from_dist(dist, 71) == pytest.approx(expected)
    assert cs.brier_from_dist(dist, 90) == pytest.approx(0.04 + 0.25 + 0.09 + 1.0)


def test_state_load_refuses_other_bytes(tmp_path):
    p = tmp_path / "s.pkl"
    p.write_bytes(pickle.dumps({"a": 1}))
    with pytest.raises(cs.CoolSeasonError):
        cs.load_state(p, "0" * 64)


def test_rule_pin_refuses_other_text(tmp_path):
    p = tmp_path / "rule.md"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(cs.CoolSeasonError):
        cs.check_rule(p)


def test_hook_and_ps1_admit_the_module_exactly():
    spec = importlib.util.spec_from_file_location("cs_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    assert MODULE + "_x" not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} coverage --rule r --out o'
    }}, constrained_capture_host=False) is not None
    text = (ROOT / "scripts" / "ops" / "workload_admission.ps1").read_text(encoding="utf-8")
    assert f'"{MODULE}",' in text


def test_k_extra_is_nan_on_a_miss_and_gaps_against_the_anchor():
    import math

    assert all(math.isnan(x) for x in cs.k_extra(None, 70.0))
    assert all(math.isnan(x) for x in cs.k_extra({"k_max": 80.0, "k_tcdc": 10.0, "k_miss": 1.0}, 70.0))
    assert cs.k_extra({"k_max": 80.0, "k_tcdc": 10.0, "k_miss": 0.0}, 77.5) == [80.0, 2.5, 10.0]


def test_bind_l2_state_refuses_a_failing_control(tmp_path):
    import json

    (tmp_path / "control.json").write_text(json.dumps({"pass": False, "state_sha256": "a" * 64}))
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_l2_state(tmp_path)
    blob = pickle.dumps({"extra_hgb": ["k_max", "k_gap", "k_tcdc"]})
    (tmp_path / "p3d_h_state.pkl").write_bytes(blob)
    import hashlib

    sha = hashlib.sha256(blob).hexdigest()
    (tmp_path / "control.json").write_text(json.dumps({"pass": True, "state_sha256": sha}))
    (tmp_path / "p3d_h_state.json").write_text(json.dumps({"state_sha256": "b" * 64}))
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_l2_state(tmp_path)
    (tmp_path / "p3d_h_state.json").write_text(json.dumps({"state_sha256": sha}))
    state, got, _ = cs.bind_l2_state(tmp_path)
    assert got == sha and state["extra_hgb"] == ["k_max", "k_gap", "k_tcdc"]


def _sums(tmp_path, files, extra_line=None):
    import hashlib

    lines = []
    for name, body in files.items():
        (tmp_path / name).write_bytes(body)
        lines.append(f"{hashlib.sha256(body).hexdigest()}  {name}")
    if extra_line:
        lines.append(extra_line)
    blob = ("\n".join(lines) + "\n").encode()
    (tmp_path / "SHA256SUMS").write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()


def test_bind_sha256sums_binds_listed_files_and_refuses_drift(tmp_path):
    files = {"manifest.jsonl": b"m\n", "selections.jsonl": b"s\n", "stations.json": b"{}"}
    sha = _sums(tmp_path, files)
    assert set(cs.bind_sha256sums(tmp_path, sha)) == set(files)
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_sha256sums(tmp_path, "0" * 64)
    (tmp_path / "selections.jsonl").write_bytes(b"changed\n")
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_sha256sums(tmp_path, sha)


def test_bind_sha256sums_requires_every_corpus_file(tmp_path):
    sha = _sums(tmp_path, {"manifest.jsonl": b"m\n", "stations.json": b"{}"})
    with pytest.raises(cs.CoolSeasonError, match="does not list"):
        cs.bind_sha256sums(tmp_path, sha)


def test_blend_is_the_weighted_union_of_buckets():
    out = cs.blend({70: 1.0}, {70: 0.5, 71: 0.5}, 0.6)
    assert out == pytest.approx({70: 0.8, 71: 0.2})
    assert sum(out.values()) == pytest.approx(1.0)


def test_dist_vector_scores_as_bucket_brier():
    from weather.calibration import rz_hrrr_spread as rz

    for mu, sig, floor_r, y in ((72.3, 2.1, 65.0, 74.0), (60.0, 1.0, 68.4, 68.0), (50.0, 3.0, 40.0, 200.0)):
        d = cs.dist_vector(mu, sig, floor_r)
        assert cs.brier_from_dist(d, y) == pytest.approx(float(rz.bucket_brier([mu], [sig], [floor_r], [y])[0]))


def test_bind_blend_weights_refuses_other_bytes(tmp_path):
    path = tmp_path / "w.json"
    path.write_text('{"control": {"pass": true}}', encoding="utf-8")
    (tmp_path / "w.json.sha256").write_text(cs.BLEND_WEIGHTS_SHA256 + "  w.json\n", encoding="utf-8")
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_blend_weights(path)


def test_rn1_point_map_refuses_an_unregistered_land_file(tmp_path):
    (tmp_path / "land.json").write_text("{}", encoding="utf-8")
    with pytest.raises(cs.CoolSeasonError):
        cs.rn1_point_map(tmp_path / "land.json", tmp_path, {"nyc"})


def test_hrrr_k_columns_reads_the_rn1_block_cell_and_filters_months(tmp_path):
    import json

    stations = {"KSFO": {"market": "san-francisco", "tz": "America/Los_Angeles"},
                "KLGA": {"market": "nyc", "tz": "America/New_York"}}
    (tmp_path / "stations.json").write_text(json.dumps(stations), encoding="utf-8")
    block = [270.0 + k for k in range(9)]
    man = []
    for var, rec in (("TMP", "TMP:2 m above ground"), ("TCDC", "TCDC:entire atmosphere")):
        man.append({"idx_record": f"{rec}:2 hour fcst:", "cycle_utc": "2024-10-10T12:00:00+00:00", "fh": 2,
                    "key": "hrrr.20241010/conus/hrrr.t12z.wrfsfcf02.grib2",
                    "points": {"KSFO": {"nearest": block[4], "block3x3": block}}})
    (tmp_path / "manifest.jsonl").write_text("\n".join(json.dumps(m) for m in man) + "\n", encoding="utf-8")
    sel = [{"station": "KSFO", "local_date": "2024-10-10", "hour_local": 7,
            "snapshot_utc": "2024-10-10T14:00:00+00:00", "cycle_utc": "2024-10-10T12:00:00+00:00", "fhs": [2],
            "latest_available_utc": "2024-10-10T13:30:00+00:00"},
           {"station": "KLGA", "local_date": "2024-10-10", "hour_local": 7,
            "snapshot_utc": "2024-10-10T11:00:00+00:00", "cycle_utc": None, "fhs": []},
           {"station": "KSFO", "local_date": "2024-08-10", "hour_local": 7,
            "snapshot_utc": "2024-08-10T14:00:00+00:00", "cycle_utc": None, "fhs": []}]
    (tmp_path / "selections.jsonl").write_text("\n".join(json.dumps(s) for s in sel) + "\n", encoding="utf-8")
    out, _ = cs.hrrr_k_columns(tmp_path, {"san-francisco", "nyc"}, hours=cs.HOURS_0712, point={"KSFO": 3},
                               months=cs.OCT_DEC)
    ksfo = out[("san-francisco", "2024-10-10", 7)]
    assert ksfo["k_miss"] == 0.0 and ksfo["k_max"] == pytest.approx((273.0 - 273.15) * 9 / 5 + 32)
    assert ksfo["k_tcdc"] == pytest.approx(273.0)
    assert out[("nyc", "2024-10-10", 7)]["reason"] == "no_land_cell"
    assert ("san-francisco", "2024-08-10", 7) not in out


def test_hrrr_k_columns_skips_or_refuses_days_after_2025(tmp_path):
    import json

    (tmp_path / "stations.json").write_text(json.dumps({"KLGA": {"market": "nyc", "tz": "America/New_York"}}),
                                            encoding="utf-8")
    (tmp_path / "manifest.jsonl").write_text("", encoding="utf-8")
    sel = {"station": "KLGA", "local_date": "2026-08-10", "hour_local": 7,
           "snapshot_utc": "2026-08-10T11:00:00+00:00", "cycle_utc": None, "fhs": []}
    (tmp_path / "selections.jsonl").write_text(json.dumps(sel) + "\n", encoding="utf-8")
    out, stats = cs.hrrr_k_columns(tmp_path, {"nyc"}, hours=cs.HOURS_0712, months=cs.AUG_SEP,
                                   skip_after="2025-12-31")
    assert out == {} and stats["skipped_after"] == 1
    with pytest.raises(cs.CoolSeasonError):
        cs.hrrr_k_columns(tmp_path, {"nyc"}, hours=cs.HOURS_0712)


def _rf1(tmp_path, payload):
    import hashlib
    import json

    path = tmp_path / "blend_l6_H_weights.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / "blend_l6_H_weights.json.sha256").write_text(f"{sha}  {path.name}\n", encoding="utf-8")
    return path, sha


def _rf1_payload():
    return {"note_sha256": cs.RF1_NOTE_SHA256,
            "checks": {"1_control": {"pass": True}, "2_identity": {"pass": True}, "3_coverage": {"pass": True}},
            "inputs": {"l6_part": cs.L6_PART_SHA256, "season_nowcasts": cs.SM_DEV_NOWCASTS_SHA256,
                       "partner_vectors": cs.SM_DEV_VECTORS_SHA256},
            "fit_dates": ["2026-08-01", "2026-09-29", 57],
            "weights": {f"h{h:02d}": 0.5 for h in cs.HOURS_0712}}


def test_bind_rf1_weights_accepts_a_passing_season_partner_refit(tmp_path):
    path, sha = _rf1(tmp_path, _rf1_payload())
    weights, info = cs.bind_rf1_weights(path, sha)
    assert weights == {h: 0.5 for h in cs.HOURS_0712} and all(info["checks"].values())
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_rf1_weights(path, "0" * 64)


@pytest.mark.parametrize("breaks", ["check", "stopped", "partner", "note", "history_fit"])
def test_bind_rf1_weights_refuses_a_failed_check_or_another_partner(tmp_path, breaks):
    payload = _rf1_payload()
    if breaks == "check":
        payload["checks"]["3_coverage"]["pass"] = False
    elif breaks == "stopped":
        payload["stopped_at"] = "check 2"
    elif breaks == "partner":
        payload["inputs"]["season_nowcasts"] = cs.L6_DEV_NOWCASTS_SHA256
    elif breaks == "note":
        payload["note_sha256"] = "0" * 64
    else:
        payload["fit_dates"] = ["2025-10-01", "2026-09-29", 120]
    path, sha = _rf1(tmp_path, payload)
    with pytest.raises(cs.CoolSeasonError):
        cs.bind_rf1_weights(path, sha)


def test_compare_runs_on_oct_dec_periods_only():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    rows = [{"market": m, "local_date": f"2024-{mo:02d}-{d:02d}", "hour": 9, "year": 2024, "month": mo}
            for m in ("nyc", "miami") for mo in (10, 11, 12) for d in range(1, 11)]
    f = pd.DataFrame(rows)
    f["mg1"] = rng.uniform(0.5, 0.9, len(f))
    f["arm"] = f.mg1 - 0.05
    out = cs.compare(f, "arm", "mg1", (9,), periods=cs.OCT_DEC_PERIODS)
    assert "aug_sep_in_sample" not in out["periods"] and out["transfer_reading"] is None
    assert out["periods"]["oct_dec"]["by"]["pooled"]["estimate"] < 0


def _scope_frame():
    import pandas as pd

    rows = [("nyc", "2022-10-10", 9), ("nyc", "2024-10-10", 9), ("nyc", "2024-10-15", 9), ("nyc", "2025-11-09", 7),
            ("nyc", "2023-08-08", 9), ("miami", "2025-12-01", 12)]
    f = pd.DataFrame(rows, columns=["market", "local_date", "hour"])
    f["year"] = f.local_date.str[:4].astype(int)
    f["month"] = f.local_date.str[5:7].astype(int)
    return f


def test_oct_dec_scope_keeps_only_2024_25_cycle_present_keys():
    back = {("nyc", "2024-10-10", 9): {"cycle_present": True, "k_miss": 0.0},
            ("nyc", "2024-10-15", 9): {"cycle_present": False, "k_miss": 1.0, "reason": "no_cycle"},
            ("nyc", "2025-11-09", 7): {"cycle_present": True, "k_miss": 1.0, "reason": "message_absent"},
            ("nyc", "2022-10-10", 9): {"cycle_present": True, "k_miss": 0.0}}
    kept, counts = cs.oct_dec_scope(_scope_frame(), back)
    assert set(zip(kept.market, kept.local_date)) == {("nyc", "2024-10-10"), ("nyc", "2025-11-09"),
                                                       ("nyc", "2023-08-08")}
    assert counts == {"oct_dec_rows_read": 5, "oct_dec_2021_23_not_scored": 1, "oct_dec_2024_25_no_cycle_absent": 1,
                      "oct_dec_2024_25_no_selection_absent": 1, "oct_dec_kept": 2, "aug_sep_rows": 1}
    cs.guard_scope(kept)


def test_no_oct_dec_2021_23_row_reaches_a_scorer():
    frame = _scope_frame()
    with pytest.raises(cs.CoolSeasonError, match="2021-23"):
        cs.guard_scope(frame)
    with pytest.raises(cs.CoolSeasonError, match="2021-23"):
        cs.score_0712(frame, state=None, hrrr={}, nmap={}, coef={}, weights={})
    with pytest.raises(cs.CoolSeasonError, match="2021-23"):
        cs.score_sm_blend(frame, state=None, hrrr={}, maps={}, coef={}, weights={})


def test_pair_keys_puts_every_arm_on_one_key_set():
    import numpy as np

    f = _scope_frame()
    f = f[(f.year >= 2024) | (f.month == 8)].reset_index(drop=True)
    f["a"] = [0.5, 0.6, np.nan, 0.7, 0.8]
    f["b"] = [0.4, np.nan, 0.5, 0.6, 0.9]
    f["mg1"] = [0.6, 0.6, 0.6, 0.6, np.nan]
    keys = cs.pair_keys(f, ("a", "b", "mg1"))
    finite = [np.isfinite(f[c].to_numpy(float)) for c in ("a", "b", "mg1")]
    assert all((x == finite[0]).all() for x in finite) and finite[0].sum() == 2
    assert keys["all"]["rows"] == 2 and keys["unpaired_rows_dropped"] == 3
    sha, n = cs.key_set_sha(f[finite[0]])
    assert keys["all"]["sha256"] == sha and n == 2
    assert keys["oct_dec"]["rows"] + keys["aug_sep"]["rows"] == 2
