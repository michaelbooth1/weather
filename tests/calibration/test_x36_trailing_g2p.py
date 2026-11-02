"""Pure pieces of the L47 K row 112 G2-P module (no data, no model, no network)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "research" / "x36_v5_reopen" / "x36_trailing_g2p.py"
_SPEC = importlib.util.spec_from_file_location("x36_trailing_g2p_under_test", _PATH)
g2p = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(g2p)


def test_g2_is_loaded_only_at_its_pinned_sha():
    g2 = g2p.load_g2()
    assert g2.label_date_ok("2026-07-31") and not g2.label_date_ok("2026-07-30")


def test_three_way_verdict_is_the_frozen_text():
    v = g2p.three_way_verdict
    assert v(-0.004, -0.001, -0.0002, -0.003) == "PASS"
    assert v(-0.004, -0.001, +0.0004, -0.003) == "CONSISTENT"
    assert v(-0.004, +0.001, +0.002, -0.003) == "CONSISTENT"
    assert v(-0.0004, +0.001, +0.002, -0.003) == "KILL"
    assert v(-0.0005, +0.001, +0.002, -0.003) == "KILL"
    assert v(-0.004, -0.001, -0.0002, +0.0001) == "KILL"
    assert v(-0.004, -0.001, -0.0002, 0.0) == "KILL"


def test_cluster_weights_match_the_scorecard_helper():
    import numpy as np

    from weather.calibration.r0_ols_floor_challenger import _date_weights

    dates = ["2026-08-15", "2026-08-16", "2026-08-15", "2026-08-17", "2026-08-18"]
    assert np.array_equal(g2p.cluster_date_weights(dates, 50, 7), _date_weights(dates, 50, 7))


def test_mbb_weights_draw_n_dates_in_circular_blocks():
    import numpy as np

    days = [f"2026-08-{d:02d}" for d in range(1, 21)]
    w = g2p.mbb_date_weights(days, block=7, draws=300, seed=1)
    assert w.shape == (300, 20)
    assert (w.sum(axis=1) == 20).all()
    # cells of one date share its weight
    w2 = g2p.mbb_date_weights(days + days[:3], block=7, draws=300, seed=1)
    assert np.array_equal(w2[:, 20:], w2[:, :3])
    # block 1 is an iid date resample: every draw still sums to n
    assert (g2p.mbb_date_weights(days, block=1, draws=50, seed=2).sum(axis=1) == 20).all()


def test_mbb_first_block_is_seven_consecutive_dates():
    import numpy as np

    days = [f"2026-08-{d:02d}" for d in range(1, 15)]
    rng = np.random.default_rng(3)
    start = int(rng.integers(0, 14, size=(1, 2))[0, 0])
    w = g2p.mbb_date_weights(days, block=7, draws=1, seed=3)[0]
    first = [(start + k) % 14 for k in range(7)]
    assert all(w[i] >= 1 for i in first)


def test_ratio_ci_point_is_the_plain_ratio():
    import numpy as np

    w = np.ones((10, 3))
    res = g2p.ratio_ci(w, [1.0, -2.0, 0.5], [1.0, 1.0, 1.0])
    assert res["estimate"] == -0.5 / 3
    assert res["ci95"][0] == res["ci95"][1] == -0.5 / 3


def test_g1_breakdown_uses_gate_rows_only():
    rows = []
    for y in (2021, 2022):
        for d in range(15, 25):
            rows.append({"gate": True, "year": y, "date": f"{y}-08-{d}", "hour": 7,
                         "P3d_T_brier": 0.5, "P3d_N_fix_brier": 0.6 if y == 2021 else 0.5})
    rows.append({"gate": False, "year": 2021, "date": "2021-08-01", "hour": 7, "P3d_N_fix_brier": 9.0})
    res = g2p.g1_breakdown(rows)
    assert res["n_rows"] == 20
    assert abs(res["groups"]["pooled"]["cluster"]["estimate"] - (-0.05)) < 1e-12
    assert abs(res["years"]["2021"]["mbb"]["estimate"] - (-0.1)) < 1e-12
    assert res["leave_one_year_out"]["2021"] == 0.0


def _row(snap, shift, w=7, lam=0.5, hour=7, d="2026-08-20"):
    return {"market": "atlanta", "snapshot_id": snap, "target_date": d, "hour": hour, "W": w, "lam": lam,
            "shift": shift, "available": True}


def test_shift_differences_are_per_date_on_identical_keys():
    a = [_row("s1", 0.5), _row("s2", -0.25, d="2026-08-21")]
    b = [_row("s1", 0.75), _row("s2", -0.25, d="2026-08-21")]
    res = g2p.shift_differences(a, b)
    assert res["rows"] == 2 and res["rows_changed"] == 1
    assert res["per_date"]["2026-08-20"]["mean"] == pytest.approx(0.25)
    assert res["per_date"]["2026-08-21"]["max_abs"] == 0.0


def test_shift_differences_refuse_mismatched_rows():
    with pytest.raises(g2p.G2PError):
        g2p.shift_differences([_row("s1", 0.5)], [_row("s9", 0.5)])
    with pytest.raises(g2p.G2PError):
        g2p.shift_differences([_row("s1", 0.5)], [_row("s1", 0.5, lam=0.25)])


def test_venue_labels_take_the_half_up_routine_max_and_drop_out_of_window_dates():
    from weather.market.market_registry import spec_for_id

    spec = spec_for_id("atlanta")
    lines = ["station,valid,tmpc,metar"]
    # Local Atlanta (EDT, UTC-4). 2026-07-31: max T-group 32.2 C = 89.96 F -> 90. 2026-08-01: one report, then a later day.
    for hh, t, tg in (("12", "30.00", "T03000200"), ("18", "32.20", "T03220200"), ("20", "31.10", "T03110200")):
        lines.append(f"KATL,2026-07-31 {hh}:52,{t},KATL 31{hh}52Z 00000KT 10SM CLR {t[:2]}/20 A3000 RMK AO2 {tg}")
    lines.append("KATL,2026-08-01 18:52,25.00,KATL 011852Z 00000KT 10SM CLR 25/20 A3000 RMK AO2 T02500200")
    lines.append("KATL,2026-08-02 18:52,25.00,KATL 021852Z 00000KT 10SM CLR 25/20 A3000 RMK AO2 T02500200")
    text = "\n".join(lines) + "\n"
    labels = g2p.venue_labels(text, spec, "KATL", lambda d: d <= "2026-07-31")
    assert set(labels) == {"2026-07-31"}
    assert labels["2026-07-31"] == (90, "F")


def test_spearman_and_ols_on_small_samples():
    assert g2p.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert g2p.spearman([1, 2, 2, 4], [1, 2, 3, 4]) == pytest.approx(0.9486832980505138)
    slope, icpt = g2p.ols([0.0, 1.0, 2.0], [1.0, 3.0, 5.0])
    assert slope == pytest.approx(2.0) and icpt == pytest.approx(1.0)


def test_mechanism_table_uses_the_nested_baseline():
    series = {"a": [(f"{y}-08-0{k}", float(y - 2021) + k) for y in range(2021, 2024) for k in (1, 2)]}
    rows = []
    for y, g in ((2021, -0.001), (2022, -0.002), (2023, -0.003)):
        rows.append({"gate": True, "year": y, "lam": 0.5, "shift": 0.25, "P3d_T_brier": 0.5 + g,
                     "P3d_N_fix_brier": 0.5})
        rows.append({"gate": True, "year": y, "lam": 0.0, "shift": 0.0, "P3d_T_brier": 0.5 + g,
                     "P3d_N_fix_brier": 0.5})
    res = g2p.mechanism_table(rows, series)
    # 2021 mean d = 1.5, others (2.5, 3.5) mean 3.0 -> departure -1.5
    assert res["years"]["2021"]["pooled_signed_departure"] == pytest.approx(-1.5)
    assert res["years"]["2022"]["pooled_abs_departure"] == pytest.approx(0.0)
    assert res["years"]["2021"]["row_mean_abs_departure"] == pytest.approx(0.5)
    assert res["years"]["2021"]["row_mean_abs_shift"] == pytest.approx(0.125)
    assert res["years"]["2023"]["gain"] == pytest.approx(-0.003)
    pred = g2p.mechanism_prediction(res["fits"], 1.5)
    f = res["fits"]["pooled_abs_departure"]
    assert pred["predicted_gain"] == pytest.approx(f["ols_intercept"] + 1.5 * f["ols_slope"])


def test_month_groups_split_aug_and_sep():
    import numpy as np

    dates = ["2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02"]
    w = np.ones((5, 4))
    res = g2p.month_groups(dates, [1.0, -1.0, -2.0, 0.0], [1.0, 1.0, 1.0, 1.0], w)
    assert res["aug"]["n_cells"] == 2 and res["aug"]["cluster"]["estimate"] == 0.0
    assert res["sep"]["cluster"]["estimate"] == -1.0 and res["sep"]["n_dates"] == 2
