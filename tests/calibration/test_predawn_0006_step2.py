"""Rule R-PD (lane L3 pre-dawn 00-06) step-2 arithmetic: bucket Brier, stack fit, NBM union, cutoffs."""
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from weather.calibration import predawn_0006 as pd6


def test_bucket_brier_point_mass_and_floor():
    # sigma tiny: all mass on round(mu); label there -> 0, label elsewhere -> 2
    b = pd6.bucket_brier([70.0, 70.0], [1e-6, 1e-6], [60.0, 60.0], [70.0, 71.0])
    assert b[0] == pytest.approx(0.0, abs=1e-12)
    assert b[1] == pytest.approx(2.0, abs=1e-12)
    # mu far below the floor: mass removed below half-up(R), renormalised onto the floor bucket
    b = pd6.bucket_brier([50.0], [1.0], [64.6], [65.0])
    assert b[0] == pytest.approx(0.0, abs=1e-6)
    # label below the floor is outside the support: counts as a full miss of 1 on top of the mass terms
    b = pd6.bucket_brier([70.0], [1e-6], [65.0], [64.0])
    assert b[0] == pytest.approx(2.0, abs=1e-12)


def test_bucket_brier_matches_direct_sum():
    from scipy.stats import norm

    mu, sd, r, y = 72.3, 2.1, 66.4, 73.0
    B = np.floor(r + 0.5)
    k = np.arange(B, B + pd6.SUPPORT)
    up = norm.cdf((k + 0.5 - mu) / sd)
    up[-1] = 1.0
    p = up - norm.cdf((k - 0.5 - mu) / sd)
    p = p / p.sum()
    want = ((p - (k == y)) ** 2).sum()
    assert pd6.bucket_brier([mu], [sd], [r], [y])[0] == pytest.approx(want, rel=1e-12)


def test_stack_fit_clip_and_min_n():
    rng = np.random.default_rng(0)
    n = 300
    x = rng.normal(size=n)
    hours = np.zeros(n, int)
    coef = pd6.stack_fit(0.5 + 2.0 * x, x, hours)          # slope 2 clipped to 1
    a, b, cnt = coef[0]
    assert b == 1.0 and cnt == n
    assert a == pytest.approx(np.mean(0.5 + 2.0 * x - x))
    assert pd6.stack_fit(x[:199], x[:199], hours[:199]) == {}
    mu = pd6.stack_mu(np.array([70.0, 70.0]), np.array([72.0, np.nan]), np.array([0, 0]), {0: (0.5, 1.0, 1)})
    assert mu.tolist() == [72.5, 70.0]


def test_nbm_union_and_cycle_rule(tmp_path):
    def row(cycle, lm, mean):
        return {"available": True, "mean": mean, "sd": 2.0, "market_id": "atlanta", "target_date": "2023-08-05",
                "cycle": cycle, "last_modified": lm}

    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(json.dumps(row("07", "2023-08-05T08:10:00Z", 91.0)) + "\n", encoding="utf-8")
    b.write_text(json.dumps(row("01", "2023-08-05T02:10:00Z", 90.0)) + "\n", encoding="utf-8")
    table = pd6.load_nbm_with_sd([a, b])
    # 03:00 EDT = 07Z: the 07Z object is not yet modified, so 01Z serves
    assert pd6.nbm_at(table, "atlanta", "2023-08-05", 3, "America/New_York")[::2] == (90.0, "01")
    assert pd6.nbm_at(table, "atlanta", "2023-08-05", 5, "America/New_York")[::2] == (91.0, "07")
    c = tmp_path / "c.jsonl"
    c.write_text(json.dumps(row("01", "2023-08-05T02:10:00Z", 89.0)) + "\n", encoding="utf-8")
    with pytest.raises(pd6.PredawnError):
        pd6.load_nbm_with_sd([b, c])


def test_history_queries_are_local_h30():
    q = pd6.history_queries(["2024-08-01"], "America/Chicago")
    assert q.hour.tolist() == list(range(7))
    assert q.t_utc.iloc[0].to_pydatetime() == datetime(2024, 8, 1, 5, 30, tzinfo=timezone.utc)


def test_rule_pin_refuses_other_file(tmp_path):
    other = tmp_path / "rule.md"
    other.write_text("not the rule", encoding="utf-8")
    with pytest.raises(pd6.PredawnError):
        pd6.check_rule(other)


def test_hrrr_analog_max_absent_and_pins(tmp_path, monkeypatch):
    man = [{"status": "ok", "var": "TMP:2 m above ground", "cycle_utc": "c0", "fh": fh,
            "points": {"KATL": {"nearest": 300.0 + fh}}} for fh in (4, 5)]
    sel = [{"station": "KATL", "local_date": "2024-08-01", "hour_local": 0, "cycle_utc": "c0", "fhs": [4, 5],
            "window_truncated_at_f18": False, "depth": 0},
           {"station": "KATL", "local_date": "2024-08-01", "hour_local": 1, "cycle_utc": "c0", "fhs": [5, 6],
            "window_truncated_at_f18": False, "depth": 0}]
    (tmp_path / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in man), encoding="utf-8")
    (tmp_path / "selections.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sel), encoding="utf-8")
    with pytest.raises(pd6.PredawnError):
        pd6.hrrr_analog(tmp_path)
    monkeypatch.setattr(pd6, "HRRR_MANIFEST_SHA256", pd6._sha(tmp_path / "manifest.jsonl"))
    monkeypatch.setattr(pd6, "HRRR_SELECTIONS_SHA256", pd6._sha(tmp_path / "selections.jsonl"))
    frame, stats = pd6.hrrr_analog(tmp_path)
    assert stats["ok"] == 1 and stats["absent_message"] == 1      # fh 6 missing: never imputed
    assert frame.H.iloc[0] == pytest.approx(pd6.k_to_f(305.0))


def test_usable_hrrr_high_refuses_late_fetch():
    import pandas as pd

    s = pd.DataFrame({"hrrr_high": [80.0, 81.0, 82.0], "hrrr_status": ["ok", "ok", "not_captured"],
                      "hrrr_fetched_at": ["2026-08-01T04:00:00+00:00", "2026-08-01T05:00:00+00:00",
                                          "2026-08-01T04:00:00+00:00"],
                      "captured_at_utc": ["2026-08-01T04:10:00+00:00"] * 3})
    got = pd6.usable_hrrr_high(s)
    assert got[0] == 80.0 and np.isnan(got[1]) and np.isnan(got[2])
