"""L5 item 2 (AFD screen): shared fit/serve for the AFD candidate and its matched intercept-only control.

Pre-registered in ``docs/research/l5-afd-preregistration-2026-10-24.md``. Coastal markets only
(san-francisco MTR, los-angeles LOX, seattle SEW, nyc OKX, miami MFL); every other snapshot, and every hour
outside 07-12, is MG-1 verbatim. Inside 07-12 for a coastal market: mu = v2_mean + r, where r is an OLS fit,
per fold on coastal training snapshots at 07-12, of (y - v2_mean) on per-market intercepts (control) or
per-market intercepts plus the AFD features (candidate). The AFD used at a snapshot is the WFO's newest
product with issued_utc <= captured_at_utc - 5 min and no older than 18 h; with none, the AFD features are
0 with ``afd_missing`` = 1. Sigma, floor and availability are MG-1's, so candidate - control is the AFD
features' increment alone.
"""
import numpy as np
import pandas as pd

from weather.reporting.scorecards.free_source_candidates import l5_centre as C

WFO = {"san-francisco": "MTR", "los-angeles": "LOX", "seattle": "SEW", "nyc": "OKX", "miami": "MFL"}
LAG = pd.Timedelta(minutes=5)
MAX_AGE = pd.Timedelta(hours=18)
FEATURES = ("depth_kft", "depth_missing", "stratus_rate", "late_clear", "warm_minus_cool", "afd_missing")
_CACHE = {}


def products():
    if "p" not in _CACHE:
        path = C.root() / "afd_products.parquet"
        df = pd.read_parquet(path)
        df["issued_utc"] = pd.to_datetime(df.issued_utc, utc=True)
        if (df.issued_utc >= pd.Timestamp("2026-09-30", tz="UTC")).any():
            raise AssertionError("AFD product after 2026-09-29")
        _CACHE["p"] = ({w: g.sort_values("issued_utc").reset_index(drop=True) for w, g in df.groupby("wfo")},
                       C.file_sha(path))
    return _CACHE["p"]


def afd_matrix(s):
    by_wfo, _ = products()
    t = pd.to_datetime(s.captured_at_utc, utc=True)
    X = np.zeros((len(s), len(FEATURES)))
    X[:, FEATURES.index("afd_missing")] = 1.0
    for i, (m, ti) in enumerate(zip(s.market.astype(str), t)):
        g = by_wfo.get(WFO.get(m))
        if g is None:
            continue
        j = g.issued_utc.searchsorted(ti - LAG, side="right") - 1
        if j < 0 or ti - g.issued_utc.iloc[j] > MAX_AGE:
            continue
        r = g.iloc[j]
        d = r.marine_depth_ft
        X[i] = [0.0 if np.isnan(d) else d / 1000.0, 1.0 if np.isnan(d) else 0.0, r.stratus_rate, r.late_clear,
                r.warm_minus_cool, 0.0]
    return X


def design(s, with_afd):
    markets = s.market.astype(str).to_numpy()
    cols = [(markets == m).astype(float) for m in WFO]
    if with_afd:
        cols += list(afd_matrix(s).T)
    return np.column_stack(cols)


def fit(train, with_afd, name):
    s = train["snapshots"].reset_index(drop=True)
    y = C.target(train)
    v2 = np.where(C.v2_usable(s), C.num(s, "v2_mean"), np.nan)
    coastal = s.market.astype(str).isin(list(WFO)).to_numpy()
    ok = coastal & C.in_window(s) & np.isfinite(y) & np.isfinite(v2)
    D = design(s[ok].reset_index(drop=True), with_afd)
    coef, *_ = np.linalg.lstsq(D, (y - v2)[ok], rcond=None)
    return {"coef": coef.tolist(), "provenance": {"rule": name, "n_train": int(ok.sum()), "coef": coef.tolist(),
                                                  "afd_products_sha256": products()[1] if with_afd else None}}


def predict(state, snaps, bands, with_afd):
    s = snaps.reset_index(drop=True)
    v2 = C.num(s, "v2_mean")
    coastal = s.market.astype(str).isin(list(WFO)).to_numpy()
    mu = np.full(len(s), np.nan)
    sel = coastal & C.in_window(s)
    if sel.any():
        D = design(s[sel].reset_index(drop=True), with_afd)
        mu[sel] = v2[sel] + D @ np.asarray(state["coef"])
    return C.serve(s, bands, mu)
