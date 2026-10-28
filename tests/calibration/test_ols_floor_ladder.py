"""Lane L9 ladder: PIT NBM selection, the overnight low row set, placebo and bootstrap mechanics.

Guards: the pre-declared rule C:\\t\\l9\\rule.md (PIT selection by S3 LastModified <= cutoff; the
overnight low over high_so_far's exact row set; date-clustered bootstrap).
"""
from datetime import datetime, timezone

import pytest

from tests.host_guard import import_or_skip_on_capture_host

lad = import_or_skip_on_capture_host("weather.calibration.ols_floor_ladder")


def test_overnight_low_uses_high_so_far_rows_and_checks_them():
    rows = [{"minute_of_day": 60, "temp_native": 50.0}, {"minute_of_day": 400, "temp_native": 47.0},
            {"minute_of_day": 420, "temp_native": 55.0}, {"minute_of_day": 430, "temp_native": 40.0}]
    prev = [{"minute_of_day": 1100, "temp_native": 45.0}, {"minute_of_day": 1000, "temp_native": 30.0}]
    low, low_prev = lad.overnight_lows(rows, "2023-11-17", 7, prev, 55.0)
    assert (low, low_prev) == (47.0, 45.0)  # 07:10 row is after the cutoff; 16:40 is before 18:00
    with pytest.raises(lad.LadderError):
        lad.overnight_lows(rows, "2023-11-17", 7, prev, 54.0)


def test_nbm_pit_selection_respects_last_modified():
    lm07 = datetime(2023, 11, 17, 8, 30, tzinfo=timezone.utc)
    lm01 = datetime(2023, 11, 17, 2, 30, tzinfo=timezone.utc)
    table = {("seattle", "2023-11-17"): [("07", lm07, 52.0), ("01", lm01, 51.0)]}
    # 07:00 PST = 15:00Z: 07Z is out.
    assert lad.nbm_at_cutoff(table, "seattle", "2023-11-17", 7, "America/Los_Angeles") == (52.0, "07")
    late = {("seattle", "2023-11-17"): [("07", datetime(2023, 11, 17, 16, 0, tzinfo=timezone.utc), 52.0),
                                        ("01", lm01, 51.0)]}
    assert lad.nbm_at_cutoff(late, "seattle", "2023-11-17", 7, "America/Los_Angeles") == (51.0, "01")
    assert lad.nbm_at_cutoff({}, "seattle", "2023-11-17", 7, "America/Los_Angeles") == (None, None)


def test_placebo_is_deterministic_and_standardish():
    values = [lad.placebo("atlanta", f"2023-11-{d:02d}", h) for d in range(1, 29) for h in range(7, 21)]
    assert values == [lad.placebo("atlanta", f"2023-11-{d:02d}", h) for d in range(1, 29) for h in range(7, 21)]
    mean = sum(values) / len(values)
    assert abs(mean) < 0.2


def test_block_stat_point_is_equal_weight_market_mean():
    rows = []
    for m, delta in (("atlanta", -1.0), ("austin", 0.0)):
        for d in ("2023-11-17", "2023-11-18"):
            rows.append({"market_id": m, "hour": 7, "season": "oct-dec", "validation_date": d,
                         "A_log_loss": 1.0 + delta, "BASE_log_loss": 1.0})
    rows.append({"market_id": "atlanta", "hour": 7, "season": "oct-dec", "validation_date": "2023-11-19",
                 "A_log_loss": 0.0, "BASE_log_loss": 1.0})
    dates = sorted({r["validation_date"] for r in rows})
    w = lad.date_weights(dates, draws=50, seed=1)
    out = lad.block_stat(rows, "A", "BASE", "log_loss", (7,), ("atlanta", "austin"), "pooled", dates, w)
    assert out["D"] == pytest.approx(-0.5)
    assert out["n_markets"] == 2 and out["n_rows"] == 5


def test_arm_features():
    base = lad.BASE_FEATURES
    assert lad.arm_features("N1", base) == base + ("nbm_mean",)
    assert lad.arm_features("N2", base)[0] == "fc_or_nbm"
    assert lad.raw_feature("fc_or_nbm", {"nbm_mean": None, "forecast_high": 70.0}) == 70.0


def test_no_production_code_imports_the_ladder():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    hits = []
    for top in ("src", "app", "scripts"):
        for path in (root / top).rglob("*"):
            if path.suffix not in {".py", ".ps1"} or path.name == "ols_floor_ladder.py":
                continue
            if "ols_floor_ladder" in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(path.relative_to(root).as_posix())
    # Every allowed importer, with its reason; any other module that names the ladder fails this test.
    ws_only = ("WS-only scorer, scores host-exported bundles; cannot import on the capture host by design "
               "(master ruling 2026-10-26)")
    expected = {
        "scripts/ops/workload_admission.ps1": "the workstation allowlist names the module (it admits it)",
        "src/weather/calibration/mg2_p3d_n.py": ws_only,
        "src/weather/calibration/pooled_residual_model.py": "lane L2, lazily, only in its research dev emitters",
        "src/weather/calibration/r0_ols_floor_challenger.py": "lazily, only for its research dev variants",
    }
    assert sorted(hits) == sorted(expected)
