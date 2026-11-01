"""Market reliability by bin: outcome-free presence count and analytic power (lane L21, 2026-11-01).

PRESENCE ONLY. This script never opens labels.parquet and never decodes a price value:

- inputs_snapshots.parquet: only the columns row_key, market, date, target_date, local_hour,
  captured_at_local and n_bands are read (no high_so_far, floor, METAR or guidance column);
- market.parquet: only row_key and band_index are read; price availability for p_market_yes comes
  from the parquet footer's per-row-group null_count statistics, so no price is decoded;
- labels.parquet is never opened.

It counts the population of the DRAFT rule in README.md (one snapshot per market x local target
date x local hour, the last captured in that hour; every band present in market.parquet; local
target date <= 2026-09-29) and computes analytic power at the D3 edge size from those counts.

Usage: python -I presence_count.py <layout_dir> <out_json>
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

DEV_LAST = date(2026, 9, 29)
SNAP_COLS = ["row_key", "market", "date", "target_date", "local_hour", "captured_at_local", "n_bands"]
MARKET_COLS = ["row_key", "band_index"]
FORBIDDEN = {"winner", "settlement_high", "settlement_bucket", "promotion_countable", "high_so_far",
             "trusted_current_max", "guidance_physical_floor", "floor", "floor_bucket", "p_market_yes"}
EDGE = math.sqrt(0.05)          # D3 edge size, 0.2236
Z = 1.959963984540054
BLOCKS = {"00-06": range(0, 7), "07-12": range(7, 13), "13-16": range(13, 17), "17-23": range(17, 24)}
WINDOWS = {"W57_0801_0929": (date(2026, 8, 1), DEV_LAST), "W43_0815_0929": (date(2026, 8, 15), DEV_LAST)}
# Empirical reference (EXHAUSTION_REGISTER section 6, X59 MET-MAX, widest US pooled mr_sweep interval):
# delta +0.0088 [-0.0395, +0.0571], date-clustered, 43 scored dates, all hours 00-23, same layout.
REF_HALF_WIDTH = (0.0571 - (-0.0395)) / 2.0
REF_DATES = 43


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def power(se):
    return phi(EDGE / se - Z)


def mde80(se):
    return (Z + 0.8416212335729143) * se


def main(layout, out):
    layout = Path(layout)
    assert not (set(SNAP_COLS) | set(MARKET_COLS)) & FORBIDDEN
    # --- price availability from footer statistics only (no value decoded)
    mf = pq.ParquetFile(layout / "market.parquet")
    names = mf.schema_arrow.names
    pidx = names.index("p_market_yes")
    nulls, stats_ok = 0, True
    for g in range(mf.metadata.num_row_groups):
        st = mf.metadata.row_group(g).column(pidx).statistics
        if st is None or not st.has_null_count:
            stats_ok = False
            break
        nulls += st.null_count
    market_rows = mf.metadata.num_rows
    mk = pq.read_table(layout / "market.parquet", columns=MARKET_COLS).to_pandas()
    bands_per_key = mk.groupby("row_key").size()
    del mk
    # --- snapshots (presence columns only)
    s = pq.read_table(layout / "inputs_snapshots.parquet", columns=SNAP_COLS).to_pandas()
    s["date"] = s["date"].astype(str)
    s["target_date"] = s["target_date"].astype(str)
    date_mismatch = int((s["date"] != s["target_date"]).sum())
    late = int((s["date"].map(date.fromisoformat) > DEV_LAST).sum())
    s = s[s["date"].map(date.fromisoformat) <= DEV_LAST]
    s["bands_in_market_file"] = s["row_key"].map(bands_per_key).fillna(0).astype(int)
    s["complete"] = s["bands_in_market_file"] == s["n_bands"].astype(int)
    # dedup: last captured snapshot per (market, local target date, local hour); ties -> max row_key
    s = s.sort_values(["market", "date", "local_hour", "captured_at_local", "row_key"])
    sel = s.groupby(["market", "date", "local_hour"], sort=False).tail(1)
    result = {"layout": str(layout), "stats_null_count_available": stats_ok,
              "p_market_yes_null_count_footer": int(nulls) if stats_ok else None,
              "market_rows": int(market_rows), "snapshot_rows_le_0929": int(len(s)),
              "snapshot_rows_after_0929": late, "date_vs_target_date_mismatch": date_mismatch,
              "markets_in_layout": sorted(s["market"].unique().tolist()), "windows": {}}
    for wname, (d0, d1) in WINDOWS.items():
        dd = sel["date"].map(date.fromisoformat)
        w = sel[(dd >= d0) & (dd <= d1)]
        incomplete = int((~w["complete"]).sum())
        w = w[w["complete"]]
        n_dates = w["date"].nunique()
        n_md = w.groupby(["market", "date"]).ngroups
        n_mdh = len(w)
        n_band_rows = int(w["n_bands"].astype(int).sum())
        m_bar = n_md / n_dates if n_dates else 0.0
        tiers = {}
        # T1 empirical: widest register mr_sweep interval, scaled by dates, x sqrt(2) for widest-of-three
        se1 = REF_HALF_WIDTH / Z * math.sqrt(REF_DATES / n_dates) * math.sqrt(2.0)
        tiers["T1_empirical_x59_sqrt2"] = se1
        # T2 conservative: one unit per market-day (all hours and bands fully dependent), deff 2 across markets
        tiers["T2_marketday_deff2"] = math.sqrt(2.0 / n_md)
        # T2b: one unit per market-day, VIF 1 + (M-1) * 0.28 across markets on a date
        vif = 1.0 + (m_bar - 1.0) * 0.28
        tiers["T2b_marketday_icc028"] = math.sqrt(vif / n_md)
        # T3 worst case: one unit per date (everything on a date fully dependent)
        tiers["T3_one_unit_per_date"] = math.sqrt(1.0 / n_dates)
        per_block = {}
        for b, hrs in BLOCKS.items():
            wb = w[w["local_hour"].astype(int).isin(list(hrs))]
            per_block[b] = {"dates": int(wb["date"].nunique()), "market_days": int(wb.groupby(["market", "date"]).ngroups),
                            "market_date_hours": int(len(wb)), "band_rows": int(wb["n_bands"].astype(int).sum())}
        per_market = {m: {"dates": int(g["date"].nunique()), "market_date_hours": int(len(g))}
                      for m, g in w.groupby("market")}
        result["windows"][wname] = {
            "dates": int(n_dates), "markets": int(w["market"].nunique()), "market_days": int(n_md),
            "market_date_hours": int(n_mdh), "band_rows": n_band_rows, "incomplete_ladders_dropped": incomplete,
            "mean_markets_per_date": round(m_bar, 4), "vif_icc028": round(vif, 4),
            "first_date": w["date"].min(), "last_date": w["date"].max(),
            "power": {k: {"se": round(v, 5), "mde80": round(mde80(v), 4), "power_at_edge": round(power(v), 4)}
                      for k, v in tiers.items()},
            "per_block": per_block, "per_market": per_market}
    result["edge"] = round(EDGE, 4)
    Path(out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "windows"}, sort_keys=True))
    for wname, wv in result["windows"].items():
        print(wname, {k: wv[k] for k in ("dates", "markets", "market_days", "market_date_hours", "band_rows",
                                         "incomplete_ladders_dropped")})
        for k, v in wv["power"].items():
            print("  ", k, v)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
