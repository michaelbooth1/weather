r"""F8-MH S0: outcome-free history count of the regime flag on Oct-Dec 2021-25 (ledger row 104, lane L16).

Spec ``docs/research/f8-mh-forward-2026-10-31/s0_spec.md`` (sha256 pinned in ``f8_mh.S0_SPEC_SHA256``, checked here).
History only (IEM METAR, the X72 frame): no forward date, no label, no price, no daily maximum. Never edited in place;
a change is a new ``_v2`` file.

    python -m tools.research.forward_f8.f8_mh_s0 --out C:\t\l16\f8-s0\<new>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tools.research.forward_f8 import f8_mh as f8

SCHEMA = "f8_mh_s0/1"
OBS_ROOT = Path(r"C:\Users\Michael\Documents\github\weather\data\research\upstream_obs")
OUT_ROOT = Path(r"C:\t\l16\f8-s0")
READ_FROM = datetime(2021, 9, 30, tzinfo=timezone.utc)
READ_BEFORE = datetime(2026, 1, 1, tzinfo=timezone.utc)
YEARS = (2021, 2022, 2023, 2024, 2025)
MONTHS = (10, 11, 12)
DISCLOSURE_MONTHS = (11, 12)
LAG = timedelta(minutes=10)
WINDOW_DATES = (f8.WINDOW_LAST - f8.D0).days + 1 - sum(1 for d in f8.EXCLUDED_DATES if f8.D0 <= d <= f8.WINDOW_LAST)
LAMBDA_MIN_FOR_DATES = 2.0


def load(root=OBS_ROOT):
    import numpy as np
    import pyarrow.parquet as pq

    sel = json.loads((root / "selection.json").read_text(encoding="utf-8"))["markets"]
    tab = pq.read_table(root / "obs.parquet", columns=["station", "role", "valid_utc", "tgroup_f", "tmpf", "is_cor"],
                        filters=[("role", "=", "market"), ("valid_utc", ">=", READ_FROM),
                                 ("valid_utc", "<", READ_BEFORE)])
    obs = tab.to_pandas()
    if len(obs) and (obs.valid_utc.max() >= READ_BEFORE or obs.valid_utc.min() < READ_FROM):
        raise f8.Refused("refused: a row outside the history read window was returned")
    obs = obs[~obs.is_cor].copy()
    obs["temp"] = np.where(np.isfinite(obs.tgroup_f), obs.tgroup_f, obs.tmpf)
    obs = obs[np.isfinite(obs.temp)]
    return obs, sel


def routine(g):
    """Rows at the station-year's modal report minute (``upstream_obs_screen.routine_mask``'s rule)."""
    minute = g.valid_utc.dt.minute
    year = g.valid_utc.dt.year
    modal = minute.groupby(year).agg(lambda m: int(m.mode().iloc[0]))
    return g[(minute == year.map(modal)).to_numpy()]


def market_flags(g, tz):
    """{(local date, hour): flag dict} for the Oct-Dec 2021-25 dates of one market; skipped instants omitted."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    r = routine(g).sort_values("valid_utc")
    local = r.valid_utc.dt.tz_convert(tz)
    by_date = defaultdict(list)
    for t_utc, t_loc, v in zip(r.valid_utc, local, r.temp.to_numpy(float)):
        by_date[t_loc.date()].append((t_utc.to_pydatetime(), t_loc.to_pydatetime(), float(v)))
    out, skipped = {}, 0
    for year in YEARS:
        d = date(year, 10, 1)
        while d.year == year:
            for h in f8.HOURS:
                naive = datetime(d.year, d.month, d.day, h, 30)
                a, b = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
                if a.utcoffset() != b.utcoffset() or a.astimezone(timezone.utc).astimezone(zone).replace(
                        tzinfo=None) != naive:
                    skipped += 1          # ambiguous or non-existent local instant
                    continue
                cut = a.astimezone(timezone.utc)
                seen = {}
                for t_utc, t_loc, v in by_date.get(d, []):
                    if t_utc + LAG <= cut:
                        seen[t_loc] = v
                out[(d.isoformat(), h)] = f8.regime_from_observations(sorted(seen.items()))
            d += timedelta(days=1)
    return out, skipped


def project(flags, months, n_window=WINDOW_DATES):
    """Rule 16 projection from history flags restricted to ``months``."""
    cells = defaultdict(lambda: [0, 0])           # (market, hour) -> [regime dates, evaluable dates]
    regime_by_date = defaultdict(set)
    all_dates = set()
    missing = 0
    for (market, d, h), f in flags.items():
        if int(d[5:7]) not in months:
            continue
        all_dates.add(d)
        cells[(market, h)][1] += 1
        missing += bool(f["missing"])
        if f["regime"]:
            cells[(market, h)][0] += 1
            regime_by_date[d].add((market, h))
    table, mdh, kept_cells = {}, 0.0, set()
    for (market, h), (k, n) in sorted(cells.items()):
        f = k / n if n else 0.0
        lam = f * n_window
        e_kept = lam - lam * math.exp(-lam)
        mdh += e_kept
        if lam >= LAMBDA_MIN_FOR_DATES:
            kept_cells.add((market, h))
        table[f"{market}|{h:02d}"] = {"regime_dates": k, "evaluable_dates": n, "f": f, "lambda": lam,
                                      "expected_kept_dates": e_kept}
    n_hist = len(all_dates)
    share = sum(1 for d in all_dates if regime_by_date.get(d, set()) & kept_cells) / n_hist if n_hist else 0.0
    dates = share * n_window
    snaps = mdh * f8.SNAPS_PER_MARKET_HOUR
    power = f8.projected_power(mdh) if mdh > 0 else None
    return {"months": list(months), "history_dates": n_hist, "window_dates": n_window, "missing_flags": missing,
            "regime_market_hours": sum(v["regime_dates"] for v in table.values()),
            "cells_lambda_ge_2": len(kept_cells), "share_dates_with_regime_in_kept_cells": share,
            "projected_dates": dates, "projected_market_day_hours": mdh, "projected_snapshots": snaps,
            "projected_power_deff2": power, "cells": table}


def verdict(p):
    fail = []
    if p["projected_dates"] < f8.MIN_DATES:
        fail.append(f"dates {p['projected_dates']:.1f} < {f8.MIN_DATES}")
    if p["projected_snapshots"] < f8.MIN_SNAPS:
        fail.append(f"snapshots {p['projected_snapshots']:.0f} < {f8.MIN_SNAPS}")
    if p["projected_power_deff2"] is None or p["projected_power_deff2"] < f8.POWER_MIN:
        fail.append(f"power {p['projected_power_deff2']} < {f8.POWER_MIN}")
    return ("UNTESTABLE (arm closed, no forward date read)" if fail else "S0 PASS (arm stays open)"), fail


def run(out):
    t0 = time.time()
    out = Path(out)
    if out.parent.resolve() != OUT_ROOT.resolve():
        raise f8.Refused(f"refused: --out must be a new folder directly under {OUT_ROOT}")
    docs = f8.check_pinned_docs()
    out.mkdir(parents=True, exist_ok=False)
    inputs = {n: f8.sha256_file(OBS_ROOT / n) for n in ("obs.parquet", "selection.json")}
    obs, sel = load()
    flags, skipped, per_year = {}, {}, Counter()
    us10 = {icao: m for icao, m in sel.items() if m["market"] in f8.MARKETS}
    for icao, m in sorted(us10.items()):
        g = obs[obs.station == icao[1:]]
        mf, skipped[m["market"]] = market_flags(g, m["timezone"])
        for (d, h), f in mf.items():
            flags[(m["market"], d, h)] = f
            per_year[d[:4]] += bool(f["regime"])
    primary = project(flags, MONTHS)
    disclosure = project(flags, DISCLOSURE_MONTHS)
    label, fails = verdict(primary)
    peak = None
    try:
        import psutil

        peak = psutil.Process().memory_info().peak_wset
    except Exception:  # noqa: BLE001 - optional measurement only
        pass
    receipt = {"schema": SCHEMA, "ledger_row": f8.LEDGER_ROW, "script_sha256": f8.sha256_file(__file__),
               "f8_module_sha256": f8.sha256_file(f8.__file__), "pinned_docs": docs,
               "b_import_check": f8.B_IMPORT_CHECK, "inputs": inputs, "markets": sorted(m["market"] for m in
                                                                                         us10.values()),
               "rows_read": int(len(obs)), "read_window_utc": [READ_FROM.isoformat(), READ_BEFORE.isoformat()],
               "skipped_instants": skipped, "regime_market_hours_by_year": dict(sorted(per_year.items())),
               "primary_octdec": primary, "disclosure_novdec_non_deciding": disclosure,
               "thresholds": {"dates": f8.MIN_DATES, "snapshots": f8.MIN_SNAPS, "power": f8.POWER_MIN,
                              "deff": f8.DEFF},
               "verdict": label, "failed": fails, "elapsed_s": round(time.time() - t0, 2), "peak_wset_bytes": peak}
    sha = f8.write_exclusive(out / "s0_receipt.json", receipt)
    print(json.dumps({"verdict": label, "failed": fails, "projected_dates": primary["projected_dates"],
                      "projected_snapshots": primary["projected_snapshots"],
                      "projected_power_deff2": primary["projected_power_deff2"], "receipt_sha256": sha,
                      "elapsed_s": receipt["elapsed_s"], "peak_wset_bytes": peak}))
    return receipt, sha


def main(argv=None):
    p = argparse.ArgumentParser(prog="f8_mh_s0")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        run(args.out)
        return 0
    except f8.Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
