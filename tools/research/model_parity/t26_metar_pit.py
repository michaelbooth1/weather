"""T26 (spare): PIT re-derivation for C:\\swarm\\data\\iem\\metar from a primary per-object source.

Primary source: aviationweather.gov Data API (`/api/data/metar`, format=json), which carries a
per-report `receiptTime` (AWC ingest time) beside `obsTime`. Fetched by C:\\swarm\\out\\t26\\fetch_awc.py,
obs and receipt strictly < 2026-09-30T00:00Z. AWC keeps about 25 days, so the measured window is
~2026-09-04..09-29 UTC.

No new rule, no scoring. Outputs (C:\\swarm\\out\\t26\\):
- lag_stats.json   receipt - valid distribution per station / type, share > 10 min
- match_stats.json IEM vs AWC row matching, COR handling, temperature agreement
- row_impact.json  snapshots whose PIT METAR state (running max F, latest obs F, any-obs) changes
                   between basis A (valid + 10 min, the manifest) and basis B (measured receipt)
                   and basis C (valid + per-station p99 measured lag) over the whole table.
Development numbers only.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.model_parity import harness as h

OUT = Path(r"C:\swarm\out\t26")
METAR = Path(r"C:\swarm\data\iem\metar")
STATIONS = ["KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"]
CUT = pd.Timestamp("2026-09-30T00:00:00Z")


def half_up(x):
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def iem_temp_f(df):
    c = df["tgroup_c"].where(df["tgroup_c"].notna(), df["main_temp_c"])
    return half_up(c * 1.8 + 32.0)


def load_awc():
    rows = []
    for s in STATIONS:
        for x in json.loads((OUT / "raw" / f"awc_{s}.json").read_text()):
            rows.append({
                "station": s,
                "valid_utc": pd.Timestamp(x["obsTime"], unit="s", tz="UTC"),
                "receipt_utc": pd.Timestamp(x["receiptTime"]),
                "metar_type": x.get("metarType"),
                "raw": x.get("rawOb", ""),
                "temp_c": x.get("temp"),
            })
    a = pd.DataFrame(rows)
    assert (a.valid_utc < CUT).all() and (a.receipt_utc < CUT).all()
    a["is_cor"] = a.raw.str.contains(r"\bCOR\b", regex=True)
    a["lag_min"] = (a.receipt_utc - a.valid_utc).dt.total_seconds() / 60.0
    return a


def load_iem():
    frames = []
    for s in STATIONS:
        d = pd.read_parquet(METAR / f"{s}.parquet")
        d["temp_f"] = iem_temp_f(d)
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def q(x, ps=(0.5, 0.9, 0.95, 0.99, 1.0)):
    x = np.asarray(x, dtype=float)
    return {f"p{int(p*100)}": round(float(np.quantile(x, p)), 2) for p in ps} if len(x) else {}


def lag_stats(a):
    out = {"n": int(len(a)), "window_utc": [str(a.valid_utc.min()), str(a.valid_utc.max())]}
    for name, sub in [("all", a), ("routine", a[a.metar_type == "METAR"]), ("speci", a[a.metar_type == "SPECI"]),
                      ("non_cor", a[~a.is_cor]), ("cor", a[a.is_cor])]:
        out[name] = {"n": int(len(sub)), **q(sub.lag_min),
                     "share_gt10": round(float((sub.lag_min > 10).mean()), 4) if len(sub) else None,
                     "share_gt15": round(float((sub.lag_min > 15).mean()), 4) if len(sub) else None,
                     "share_gt30": round(float((sub.lag_min > 30).mean()), 4) if len(sub) else None,
                     "share_gt60": round(float((sub.lag_min > 60).mean()), 4) if len(sub) else None,
                     "share_lt0": round(float((sub.lag_min < 0).mean()), 4) if len(sub) else None}
    out["per_station_non_cor"] = {s: {"n": int(len(g)), **q(g.lag_min), "share_gt10": round(float((g.lag_min > 10).mean()), 4)}
                                  for s, g in a[~a.is_cor].groupby("station")}
    return out


def match(a, iem):
    lo = a.valid_utc.min().floor("h")
    i = iem[(iem.valid_utc >= lo) & (iem.valid_utc < CUT)].copy()
    # earliest non-COR AWC receipt per (station, valid)
    first = (a[~a.is_cor].sort_values("receipt_utc").groupby(["station", "valid_utc"], as_index=False)
             .agg(receipt_utc=("receipt_utc", "first"), awc_temp_c=("temp_c", "first"), awc_raw=("raw", "first"),
                  n_awc=("raw", "size")))
    anyrec = a.groupby(["station", "valid_utc"], as_index=False).agg(any_receipt=("receipt_utc", "min"),
                                                                       has_cor=("is_cor", "any"))
    m = i.merge(first, on=["station", "valid_utc"], how="left").merge(anyrec, on=["station", "valid_utc"], how="left")
    st = {"iem_rows_in_window": int(len(i)), "iem_non_cor": int((~i.is_cor).sum()),
          "iem_non_cor_matched_to_awc_original": int(((~m.is_cor) & m.receipt_utc.notna()).sum()),
          "iem_non_cor_unmatched": int(((~m.is_cor) & m.receipt_utc.isna()).sum()),
          "iem_cor_rows": int(m.is_cor.sum()),
          "iem_cor_rows_with_awc_original": int((m.is_cor & m.receipt_utc.notna()).sum()),
          "awc_valid_times": int(len(anyrec)),
          "awc_valid_times_absent_in_iem": int(len(anyrec.merge(i[["station", "valid_utc"]].drop_duplicates(),
                                                               how="left", indicator=True).query("_merge=='left_only'")))}
    mm = m[(~m.is_cor) & m.receipt_utc.notna() & m.awc_temp_c.notna()]
    awc_f = half_up(mm.awc_temp_c.astype(float) * 1.8 + 32.0)
    st["temp_f_equal_share"] = round(float((awc_f == mm.temp_f.values).mean()), 5)
    st["temp_f_diff_rows"] = int((awc_f != mm.temp_f.values).sum())
    st["raw_text_equal_share"] = round(float((mm.awc_raw.str.replace(r"^(METAR|SPECI) ", "", regex=True).str.strip()
                                            == mm.metar.str.strip()).mean()), 4)
    um = m[(~m.is_cor) & m.receipt_utc.isna()]
    st["unmatched_examples"] = um[["station", "valid_utc", "report_type", "metar"]].head(8).astype(str).to_dict("records")
    st["unmatched_by_type"] = um.report_type.value_counts().to_dict()
    m["lag_vs_iem_basis_min"] = (m.receipt_utc - m.available_utc).dt.total_seconds() / 60.0
    return m, st


def state(snaps, obs, avail_col):
    """PIT METAR state per snapshot: running max F (target local date), latest obs F, any obs."""
    out = np.full((len(snaps), 3), np.nan)
    for s, g in snaps.groupby("station"):
        o = obs[(obs.station == s) & obs[avail_col].notna()]
        for d, gg in g.groupby("date"):
            od = o[o.local_date.astype(str) == d].sort_values(avail_col)
            if od.empty:
                continue
            av = od[avail_col].values.astype("datetime64[us]")
            tf = od.temp_f.values
            cm = np.fmax.accumulate(np.where(np.isnan(tf), -np.inf, tf))
            t = pd.to_datetime(gg.captured_at_utc, utc=True).values.astype("datetime64[us]")
            k = np.searchsorted(av, t, side="right") - 1
            ok = k >= 0
            idx = gg.index.values
            out[np.searchsorted(snaps.index.values, idx[ok]), 0] = np.where(np.isinf(cm[k[ok]]), np.nan, cm[k[ok]])
            out[np.searchsorted(snaps.index.values, idx[ok]), 1] = tf[k[ok]]
            out[np.searchsorted(snaps.index.values, idx), 2] = ok.astype(float)
    out[np.isnan(out[:, 2]), 2] = 0
    return out


def compare(snaps, sa, sb, label):
    res = {"label": label, "snapshots": int(len(snaps))}
    blocks = ["00-05", "06-09", "10-12", "13-16", "17-23"]
    def diff(i):
        x, y = sa[:, i], sb[:, i]
        return ~((x == y) | (np.isnan(x) & np.isnan(y)))
    dmax, dlast, dany = diff(0), diff(1), diff(2)
    res["running_max_changed"] = int(dmax.sum())
    res["latest_obs_changed"] = int(dlast.sum())
    res["any_obs_changed"] = int(dany.sum())
    res["any_state_changed"] = int((dmax | dlast | dany).sum())
    both = ~np.isnan(sa[:, 0]) & ~np.isnan(sb[:, 0])
    res["running_max_diff_F_when_both"] = {"mean": round(float(np.mean((sa[both, 0] - sb[both, 0]))), 4),
                                           "share_ge1F": round(float(np.mean(np.abs(sa[both, 0] - sb[both, 0]) >= 1)), 5)}
    per = {}
    for b in blocks:
        mk = (snaps.block == b).values
        per[b] = {"snapshots": int(mk.sum()), "running_max_changed": int((dmax & mk).sum()),
                  "latest_obs_changed": int((dlast & mk).sum()), "any_obs_changed": int((dany & mk).sum()),
                  "share_running_max_changed": round(float((dmax & mk).sum() / max(mk.sum(), 1)), 5)}
    res["per_block"] = per
    res["share_running_max_changed"] = round(float(dmax.mean()), 5)
    res["share_any_state_changed"] = round(float((dmax | dlast | dany).mean()), 5)
    return res


def main():
    a = load_awc()
    iem = load_iem()
    ls = lag_stats(a)
    m, ms = match(a, iem)
    ls["receipt_minus_iem_basis_min_matched_non_cor"] = q(m.loc[(~m.is_cor) & m.receipt_utc.notna(), "lag_vs_iem_basis_min"])
    (OUT / "lag_stats.json").write_text(json.dumps(ls, indent=1, default=str))
    (OUT / "match_stats.json").write_text(json.dumps(ms, indent=1, default=str))

    snaps, _ = h.candidate_inputs()
    snaps = snaps.reset_index(drop=True)
    assert snaps.date.max() <= "2026-09-29"
    obs = iem[~iem.is_cor].copy()
    obs = obs.merge(m.loc[~m.is_cor, ["station", "valid_utc", "receipt_utc"]], on=["station", "valid_utc"], how="left")
    # Basis B: measured receipt; unmatched rows inside the AWC window -> excluded (no evidence)
    awc_lo = a.valid_utc.min()
    in_win = obs.valid_utc >= awc_lo
    obs["avail_B"] = obs.receipt_utc.where(in_win, pd.NaT)
    # Basis B': measured receipt; unmatched rows keep valid+10 (lenient)
    obs["avail_Bl"] = obs.receipt_utc.where(obs.receipt_utc.notna(), obs.available_utc)
    # Basis C: valid + per-station measured p99 lag (whole table)
    p99 = a[~a.is_cor].groupby("station").lag_min.quantile(0.99)
    obs["avail_C"] = obs.valid_utc + pd.to_timedelta(obs.station.map(p99).fillna(p99.max()), unit="min")
    obs["avail_A"] = obs.available_utc

    # the snapshot window fully covered by AWC: target dates whose local day starts after awc_lo
    win = snaps[pd.to_datetime(snaps.captured_at_utc, utc=True) >= awc_lo + pd.Timedelta(hours=12)]
    win = win[win.date >= (awc_lo + pd.Timedelta(days=1)).strftime("%Y-%m-%d")].copy()
    sA = state(win, obs, "avail_A")
    sB = state(win, obs, "avail_B")
    sBl = state(win, obs, "avail_Bl")
    full = snaps
    fA = state(full, obs, "avail_A")
    fC = state(full, obs, "avail_C")
    res = {
        "awc_window_valid_utc": [str(a.valid_utc.min()), str(a.valid_utc.max())],
        "measured_window_target_dates": [win.date.min(), win.date.max()],
        "p99_lag_min_per_station": {k: round(float(v), 2) for k, v in p99.items()},
        "A_vs_B_strict_measured_window": compare(win, sA, sB, "A valid+10 vs B measured receipt, unmatched excluded"),
        "A_vs_B_lenient_measured_window": compare(win, sA, sBl, "A valid+10 vs B measured receipt, unmatched keep valid+10"),
        "A_vs_C_full_table": compare(full, fA, fC, "A valid+10 vs C valid+station p99 measured lag"),
        "rows_after_20260929": int((snaps.date > "2026-09-29").sum()),
        "harness_sha256": h.harness_sha256(),
    }
    (OUT / "row_impact.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(ls, indent=1, default=str)[:3000])
    print(json.dumps({k: v for k, v in ms.items() if k != "unmatched_examples"}, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()


def violations():
    """Basis A (valid+10) rows that use an obs not yet received at AWC (receipt > t): the PIT-violation direction.
    State A vs state A' = only obs with avail_A <= t AND receipt <= t (AWC window, matched rows; unmatched kept)."""
    a = load_awc()
    iem = load_iem()
    m, _ = match(a, iem)
    snaps, _ = h.candidate_inputs()
    snaps = snaps.reset_index(drop=True)
    obs = iem[~iem.is_cor].merge(m.loc[~m.is_cor, ["station", "valid_utc", "receipt_utc"]], on=["station", "valid_utc"], how="left")
    awc_lo = a.valid_utc.min()
    win = snaps[snaps.date >= (awc_lo + pd.Timedelta(days=1)).strftime("%Y-%m-%d")].copy()
    # A' availability = max(valid+10, receipt) (receipt unknown -> valid+10)
    obs["avail_Ap"] = obs[["available_utc", "receipt_utc"]].max(axis=1)
    obs["avail_A"] = obs.available_utc
    sA = state(win, obs, "avail_A")
    sAp = state(win, obs, "avail_Ap")
    res = {"definition": "A' = max(valid+10, AWC receipt); differences are rows where basis A used an obs not yet received",
           "pooled": compare(win, sA, sAp, "A vs A'=max(A, receipt)")}
    per_st = {}
    for s in STATIONS:
        mk = (win.station == s).values
        r = compare(win[mk], sA[mk], sAp[mk], s)
        per_st[s] = {k: r[k] for k in ["snapshots", "running_max_changed", "latest_obs_changed", "any_obs_changed",
                                         "share_running_max_changed", "running_max_diff_F_when_both"]}
        per_st[s]["running_max_changed_17_23"] = r["per_block"]["17-23"]["running_max_changed"]
        per_st[s]["running_max_changed_13_16"] = r["per_block"]["13-16"]["running_max_changed"]
    res["per_station"] = per_st
    nonbkf = (win.station != "KBKF").values
    res["pooled_excluding_KBKF"] = compare(win[nonbkf], sA[nonbkf], sAp[nonbkf], "excl KBKF")
    (OUT / "violations.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))
