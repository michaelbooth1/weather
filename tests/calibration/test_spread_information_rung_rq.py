"""Lane L15 rung R-Q: GEFS member spread (variant A on P3d_N_fix at 07-12, variant B warm half on MG-1 at 00-06).

Guards: L15 pre-registered rule (C:/t/l15/rule_rq.md, sha 5703f065...) - only the 30 perturbed members enter a
statistic and a row needs at least 25 of them; a member counts only if every step valid on the local target date is
present and available at or before the cutoff; nothing after 2026-09-29 and no other cycle or step is accepted; the
corpus must match its manifest's rows_sha256; centring is per market over the fitting rows and undefined rows get no
modulation; beta = 0 reproduces P3d_N_fix (A) and MG-1 (B) exactly; the two-piece CDF keeps the median and the cold
half; the walk-forward beta and centring use strictly earlier dev dates only.
"""
import hashlib
import importlib
import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

try:
    rs = importlib.import_module("weather.calibration.spread_information_rung")
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

UTC = timezone.utc
TZ = "America/New_York"


def _rows(day, variant="A", members=None, value_k=300.0, avail_shift_h=4.0, drop=None, spread=0.0):
    spec = rs.RQ_VARIANTS[variant]
    d = datetime.fromisoformat(day).date()
    c = d + timedelta(days=spec["day_offset"])
    cycle = datetime(c.year, c.month, c.day, spec["cycle_hour"], tzinfo=UTC)
    members = members or (("gec00",) + rs.RQ_PERTURBED)
    out = []
    for i, member in enumerate(members):
        for fh in spec["fhs"]:
            if drop and (member, fh) in drop:
                continue
            valid = cycle + timedelta(hours=fh)
            out.append({"kind": "message", "status": "ok", "date": day, "member": member, "fh": fh,
                        "key": f"{member}.f{fh:03d}", "cycle_utc": cycle.isoformat(), "valid_utc": valid.isoformat(),
                        "available_utc": (cycle + timedelta(hours=avail_shift_h)).isoformat(),
                        "points": {"atlanta": {"bilinear_k": value_k + spread * i + 0.1 * fh, "corners_k": []}}})
    return out


def _write(tmp_path, rows, manifest=True, bad_sha=False):
    path = tmp_path / "gefs_member_rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if manifest:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        (tmp_path / "manifest.json").write_text(json.dumps({"rows_sha256": "0" * 64 if bad_sha else sha}))
    return tmp_path


def test_load_gefs_checks_manifest_window_and_cycle(tmp_path):
    corpus = _write(tmp_path, _rows("2026-08-10"))
    table, inputs = rs.load_gefs(corpus, "A")
    assert inputs["gefs_rows_sha256"] == inputs["manifest_rows_sha256"]
    assert len(table[("atlanta", "2026-08-10")]) == 31
    with pytest.raises(rs.SpreadRungError):
        rs.load_gefs(_write(tmp_path, _rows("2026-08-10"), bad_sha=True), "A")
    with pytest.raises(rs.SpreadRungError):
        rs.load_gefs(_write(tmp_path, _rows("2026-09-30")), "A")
    with pytest.raises(rs.SpreadRungError):  # a 06Z D row is not variant B's 18Z D-1 cycle
        rs.load_gefs(_write(tmp_path, _rows("2026-08-10")), "B")
    table_b, _ = rs.load_gefs(_write(tmp_path, _rows("2026-08-10", "B")), "B")
    assert ("atlanta", "2026-08-10") in table_b


def test_member_highs_local_date_availability_and_completeness(tmp_path):
    rows = _rows("2026-08-10", drop={("gep05", 12)})
    table, _ = rs.load_gefs(_write(tmp_path, rows), "A")
    day = "2026-08-10"
    early = rs.member_highs(table, "atlanta", day, datetime(2026, 8, 10, 9, tzinfo=UTC), TZ, "A")
    assert early == {}  # every message available at 10Z
    highs = rs.member_highs(table, "atlanta", day, rs.cutoff_utc(day, 7, TZ), TZ, "A")
    assert "gep05" not in highs and len(highs) == 30
    # 06Z f024 is 02:00 EDT on D+1, so the local-date max uses f006..f021 only
    assert highs["gec00"] == pytest.approx(rs.kelvin_to_f(300.0 + 2.1))


def test_spread_statistic_members_floor_and_forms():
    highs = {m: 80.0 + k for k, m in enumerate(rs.RQ_PERTURBED)}
    highs["gec00"] = 500.0  # never enters
    values = [80.0 + k for k in range(30)]
    assert rs.spread_statistic(highs, "sd") == pytest.approx(math.log(float(np.std(values, ddof=1))))
    assert rs.spread_statistic(highs, "warm_half") == pytest.approx(math.log(np.percentile(values, 90)
                                                                             - np.percentile(values, 50)))
    flat = {m: 80.0 for m in rs.RQ_PERTURBED}
    assert rs.spread_statistic(flat, "sd") == pytest.approx(math.log(0.25))
    few = {m: 80.0 + k for k, m in enumerate(rs.RQ_PERTURBED[:24])}
    assert math.isnan(rs.spread_statistic(few, "sd"))


def test_market_centring_and_undefined_rows():
    u = np.array([1.0, 3.0, np.nan, 10.0])
    markets = np.array(["a", "a", "a", "b"])
    ubar = rs.market_means(u, markets)
    assert ubar == {"a": 2.0, "b": 10.0}
    assert rs.centred(u, markets, ubar).tolist() == [-1.0, 1.0, 0.0, 0.0]


def _frame(markets=("atlanta", "nyc"), years=(2021, 2022, 2023, 2024), hour=9, n_days=14, seed=0):
    rng = np.random.default_rng(seed)
    rows, us = [], []
    for market in markets:
        for year in years:
            for d in range(n_days):
                wide = d % 2 == 0
                fh = 80.0 + rng.normal(0, 3)
                y = round(fh + rng.normal(0, 4.0 if wide else 1.0))
                rows.append({"market": market, "centre": "2026-08-23", "season": "aug_sep", "hour": hour,
                             "target_date": f"{year}-08-{10 + d:02d}", "year": year, "y": float(y), "F": fh - 8.0,
                             "fh": fh, "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.5, "doy_cos": 0.8,
                             "x_high_so_far": fh - 8.0, "x_current_temp": fh - 9.0,
                             "market_code": float(prm.R0_MARKETS.index(market))})
                us.append((1.4 if market == "atlanta" else 0.6) + (0.4 if wide else -0.4) if d != 3 else np.nan)
    return pd.DataFrame(rows), np.array(us)


def test_rq_loyo_market_centring_keeps_the_unmodulated_rows_and_finds_signal():
    frame, u = _frame()
    buckets = {m: list(range(60, 105)) for m in ("atlanta", "nyc")}
    rows, betas, dev, diag = rs.rs_loyo(frame, u, buckets, (9,), centring="market", arm="P3d_N_fix_Q")
    ref = prm.rung_loyo(frame, buckets, (9,), arms={"P3d_N_fix": False})
    ref_b = {(r["market"], r["date"]): r["P3d_N_fix_brier"] for r in ref}
    assert max(abs(r["P3d_N_fix_brier"] - ref_b[(r["market"], r["date"])]) for r in rows) < 1e-12
    assert all("P3d_N_fix_Q_brier" in r for r in rows)
    assert set(dev[9]["ubar_all_years"]) == {"atlanta", "nyc"}
    assert dev[9]["ubar_all_years"]["atlanta"] > dev[9]["ubar_all_years"]["nyc"]
    assert all(r["x"] == 0.0 for r in rows if r["date"].endswith("-13"))  # undefined u -> no modulation
    assert dev[9]["beta"] > 0
    summary = rs.loyo_summary(rows, draws=50, arm="P3d_N_fix_Q")
    assert summary["pooled|brier"]["n"] == len(rows)


class _Table:
    """The slice of ``dev_scorecard.Table`` that the MG-1 frame uses."""

    def __init__(self, n_snaps=3):
        self.snaps = pd.DataFrame({
            "v2_mean": [80.4, 72.0, 90.0][:n_snaps], "v2_stddev": [2.0, 0.5, 3.0][:n_snaps],
            "v2_available_at": ["2026-08-10T04:00:00Z"] * n_snaps,
            "captured_at_utc": ["2026-08-10T05:00:00Z"] * n_snaps, "floor": [76.0, np.nan, 70.0][:n_snaps]})
        bands = []
        for s in range(n_snaps):
            edges = list(range(66, 96, 2))
            for i, low in enumerate(edges):
                kind = "lte" if i == 0 else ("gte" if i == len(edges) - 1 else "range")
                bands.append({"row_key": f"r{s}", "band_index": i, "kind": kind, "low": float(low),
                              "high": float(low + 1)})
        self.bands = pd.DataFrame(bands)
        self.n = np.array([len(edges)] * n_snaps)
        self.band_snap = np.repeat(np.arange(n_snaps), self.n)


def _mg1_reference(table):
    from scipy.special import ndtr

    mu, sigma, ok, B = rs.mg1_inputs(table)
    sel = ok[table.band_snap]
    b, snap = table.bands[sel], table.band_snap[sel]
    kind, low, high = b.kind.to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float)
    m, sg, bb = mu[snap], sigma[snap], B[snap]
    up = np.where(kind == "gte", np.inf, high + 0.5)
    lo = np.where((kind == "lte") | (low <= bb), -np.inf, low - 0.5)
    possible = (kind == "gte") | (high >= bb)
    return np.clip(np.where(possible, ndtr((up - m) / sg) - ndtr((lo - m) / sg), 0.0), 0.0, None)


def test_two_piece_at_beta_zero_is_mg1_and_keeps_median_and_cold_half():
    table = _Table()
    mu, sigma, ok, B = rs.mg1_inputs(table)
    frame0 = rs.mg1_two_piece_frame(table, sigma)
    assert np.array_equal(frame0.p.to_numpy(), _mg1_reference(table))
    wide = rs.b_sigma_up(sigma, np.array([0.8, 0.8, -0.8]), 1.0)
    assert np.all(wide >= 1.0) and wide[0] > sigma[0] and wide[2] < sigma[2]
    t = np.array([60.0, 75.0, 80.4, 85.0])
    f0 = rs.two_piece_cdf(t, 80.4, 2.0, 2.0)
    f1 = rs.two_piece_cdf(t, 80.4, 2.0, 4.0)
    assert f1[2] == pytest.approx(0.5) and np.array_equal(f0[:3], f1[:3]) and f1[3] < f0[3]
    assert float(rs.b_sigma_up(np.array([1.0]), np.array([-5.0]), 1.5)[0]) == 1.0  # MG-1's minimum kept


def test_walk_forward_b_uses_only_earlier_dates():
    dates = np.array([f"2026-08-{d:02d}" for d in range(1, 13) for _ in range(2)])
    hours = np.zeros(len(dates), int)
    markets = np.array(["atlanta"] * len(dates))
    u = np.linspace(-1, 1, len(dates))
    covered = np.ones(len(dates), bool)
    calls = []

    def brier_of(beta, x):
        calls.append(beta)
        # rewards beta 1.0 on dates <= 08-10 and beta 0.5 only on later dates
        good = np.where(dates <= "2026-08-10", 1.0, 0.5)
        return np.abs(beta - good)

    betas, ubars = rs.walk_forward_b(dates, hours, markets, u, covered, brier_of, ["2026-08-05", "2026-08-11"],
                                     grid=(0.0, 0.5, 1.0))
    assert betas[(0, "2026-08-05")] == 0.0  # fewer than 10 prior dates
    assert betas[(0, "2026-08-11")] == 1.0  # the later (08-11, 08-12) rows are never seen
    prior = dates < "2026-08-11"
    assert ubars["2026-08-11"]["atlanta"] == pytest.approx(float(u[prior].mean()))


def test_parity_stats_thresholds():
    good = [("atlanta", f"2026-08-{d:02d}", 80.0 + d + 0.2, 80.0 + d) for d in range(1, 20)]
    assert rs.parity_stats(good)["pass"]
    bad = [(m, d, a + 3.0, b) for m, d, a, b in good]
    assert not rs.parity_stats(bad)["pass"]
    assert not rs.parity_stats([])["pass"]
