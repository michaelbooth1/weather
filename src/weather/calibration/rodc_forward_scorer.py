"""R-ODC forward scorer (pure, unbound; L8 2026-10-29). Scores the frozen R-ODC forward pre-registration.

Nothing here is served, and it is not in any RELEASE_FILES. It reads forward data only through ``check_look``:

* Embargo: nothing after 2026-09-29 is read before the look. Every read and every verdict refuses unless the look
  context says the look day has come (``today >= look_date``), the look is on or after 2026-12-14 and on or after the
  B look receipt, and every scored date lies in [D0, look_date) with D0 >= the freeze date >= 2026-10-30.
* Denver is excluded from P1 and P2 (DL 10-23, KDEN vs KBKF), as in test B; a Denver row refuses.

P1, serve parity (no labels): serve = ``odc_metar_features.odc_features`` on the captured snapshot chosen by
``choose_snapshot(rule="last_in_hour")``; research = the training construction on the market's WU history store
(``WundergroundHistoryStore`` at ``spec_for_id(market).data_root``, built as the daily refresh builds it): rows of
local date D with minute_of_day <= h*60, low = min temp_native, dewpoint = dewpoint_native of the latest row.

P2, non-inferiority: dR(NEST vs G1) = sum_cell mean(Brier_NEST - Brier_G1) / sum_cell mean(Brier_G1), cells
(local_date, market) over h07-12, date-clustered multinomial weights (``r0_ols_floor_challenger._date_weights``,
2,000 draws, seed 20261027) and ``dev_scorecard.ratio_interval`` -- the gate's ``rz_hrrr_spread._cell_ratio``.
PASS iff the upper 95% bound < MARGIN (+0.0015). The forward per-row Brier frame is supplied by the caller.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date

from weather.calibration import odc_metar_features as odc

EMBARGO_LAST = date(2026, 9, 29)
FREEZE_EARLIEST = date(2026, 10, 30)
LOOK_EARLIEST = date(2026, 12, 14)
EXCLUDED_MARKETS = frozenset({"denver"})
HOURS = (7, 8, 9, 10, 11, 12)
SEED = 20261027
DRAWS = 2000
MARGIN = 0.0015
SNAPSHOT_RULE = "last_in_hour"
P1_LIMITS = {"low_so_far": {"exact_min": 0.95, "max_abs": 2.0, "ge2_max": 0.01},
             "dewpoint_c": {"exact_min": 0.97, "max_abs": 5.0, "ge2_max": 0.01}}
P1_EXCLUDED_VOID = 0.10   # more than 10% of P1 rows excluded -> P1 VOID
WU_GAP_VOID = 0.05        # more than 5% of required (market, date) WU days missing after backfill -> VOID


class RodcForwardRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class LookContext:
    freeze_date: date
    d0: date
    look_date: date
    b_receipt_date: date | None
    today: date


def check_look(ctx, *, dates=(), markets=()):
    """Refuse unless the look may happen now and every date/market is in scope. -> sorted unique dates."""
    if not isinstance(ctx, LookContext):
        raise RodcForwardRefused("a LookContext is required")
    if ctx.freeze_date < FREEZE_EARLIEST:
        raise RodcForwardRefused(f"freeze {ctx.freeze_date} is before {FREEZE_EARLIEST}")
    if ctx.d0 < ctx.freeze_date:
        raise RodcForwardRefused(f"D0 {ctx.d0} is before the freeze {ctx.freeze_date}")
    if ctx.look_date < LOOK_EARLIEST:
        raise RodcForwardRefused(f"look {ctx.look_date} is before {LOOK_EARLIEST}")
    if ctx.b_receipt_date is None:
        raise RodcForwardRefused("no B look receipt: the R-ODC look comes after it")
    if ctx.look_date < ctx.b_receipt_date:
        raise RodcForwardRefused(f"look {ctx.look_date} is before the B look receipt {ctx.b_receipt_date}")
    if ctx.today < ctx.look_date:
        raise RodcForwardRefused(f"embargo: today {ctx.today} is before the look {ctx.look_date}")
    bad = sorted(set(markets) & EXCLUDED_MARKETS)
    if bad:
        raise RodcForwardRefused(f"excluded market(s) {bad}")
    days = sorted({d if isinstance(d, date) else date.fromisoformat(str(d)[:10]) for d in dates})
    out = [d for d in days if not (ctx.d0 <= d < ctx.look_date)]
    if out:
        raise RodcForwardRefused(f"date(s) outside [D0 {ctx.d0}, look {ctx.look_date}): {out[:3]}")
    return days


# ------------------------------------------------------------------------------------------------ WU research side

def wu_store(market):
    """The market's WU history store, exactly as the daily refresh builds it (path from weather.paths)."""
    from weather.market.market_registry import spec_for_id
    from weather.operations.daily_refresh_source_steps import _store_for_wu_restore

    return _store_for_wu_restore(spec_for_id(market))


def _minute(value):
    try:
        h, m = str(value).split(":")[:2]
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def read_wu_rows(market, days, ctx, *, store=None):
    """{date: [{"minute_of_day", "temp_native", "dewpoint_native"}] sorted by minute (file order on ties)}.
    A label read: refused unless ``check_look`` passes. A day absent from the store maps to []."""
    from weather.model.feature_store import row_dewpoint_native, row_temp_native

    days = check_look(ctx, dates=days, markets=[market])
    store = wu_store(market) if store is None else store
    want = {d.isoformat() for d in days}
    out = {d: [] for d in days}
    for year, month in sorted({(d.year, d.month) for d in days}):
        path = store.hourly_root / f"year={year:04d}" / f"month={month:02d}" / "observations.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("local_date") not in want:
                    continue
                minute = _minute(row.get("local_time"))
                if minute is None:
                    continue
                out[date.fromisoformat(row["local_date"])].append(
                    {"minute_of_day": minute, "temp_native": row_temp_native(row),
                     "dewpoint_native": row_dewpoint_native(row)})
    for rows in out.values():
        rows.sort(key=lambda r: r["minute_of_day"])
    return out


def research_features(rows, hour):
    """The training construction (ols_floor_ladder.overnight_lows row set + latest-row dewpoint) or None."""
    kept = [r for r in rows if r["minute_of_day"] <= int(hour) * 60]
    temps = [r["temp_native"] for r in kept if r["temp_native"] is not None]
    if not temps:
        return None
    return {"low_so_far": min(temps), "dewpoint_c": kept[-1]["dewpoint_native"]}


def wu_gap(required, present):
    """Share of required (market, date) WU days with no row after backfill; VOID above WU_GAP_VOID."""
    required = set(required)
    missing = sorted(required - set(present))
    share = len(missing) / len(required) if required else 1.0
    return {"required": len(required), "missing": len(missing), "share": share, "void": share > WU_GAP_VOID,
            "missing_days": [list(map(str, k)) for k in missing[:50]]}


# ------------------------------------------------------------------------------------------------ P1

def p1_day(market, day, snapshots, wu_rows, ctx, *, tz, unit):
    """P1 records for one (market, date), h07-12. ``snapshots``: [{"captured_at": aware dt, "metar": the captured
    sources.metar.data dict, "high_so_far", "current_temp"}] in file order. A bound refusal marks that hour."""
    check_look(ctx, dates=[day], markets=[market])
    captures = [s["captured_at"] for s in snapshots]
    recs, by_hour = [], {}
    for h in HOURS:
        rec = {"market": market, "date": day.isoformat(), "hour": h, "excluded": None, "refused": False}
        i = odc.choose_snapshot(captures, target_date=day, tz=tz, cutoff_hour=h, rule=SNAPSHOT_RULE)
        research = research_features(wu_rows, h)
        if i is None:
            rec["excluded"] = "no_snapshot"
        elif research is None:
            rec["excluded"] = "no_wu_row"
        else:
            serve = odc.odc_features(snapshots[i]["metar"], target_date=day, tz=tz, unit=unit, cutoff_hour=h,
                                     now=captures[i])
            if serve["reason"]:
                rec["excluded"] = serve["reason"]
            else:
                rec.update(serve_low=serve["low_so_far"], serve_dew=serve["dewpoint_c"],
                           research_low=research["low_so_far"], research_dew=research["dewpoint_c"])
                by_hour[h] = {"low_so_far": serve["low_so_far"], "high_so_far": snapshots[i].get("high_so_far"),
                              "current_temp": snapshots[i].get("current_temp")}
        recs.append(rec)
    previous = None
    for rec in recs:
        h = rec["hour"]
        if h not in by_hour:
            continue
        window = {h: by_hour[h]}
        if previous is not None:  # running min against the previous hour only; its own bounds were checked
            window[previous] = {"low_so_far": by_hour[previous]["low_so_far"]}
        try:
            odc.check_bounds(window)
        except odc.OdcMetarRefused:
            rec["refused"] = True
        previous = h
    return recs


def _column(recs, serve_key, research_key, limits):
    exact = ge2 = 0
    max_abs = 0.0
    for r in recs:
        s, t = r[serve_key], r[research_key]
        if r["refused"] or (s is None) != (t is None):
            ge2 += 1          # a refusal or a one-sided None is a mismatch in the >= 2 bucket, outside max|diff|
            continue
        if s is None:
            exact += 1        # both None (dewpoint missing on both sides)
            continue
        d = abs(float(s) - float(t))
        exact += d == 0
        ge2 += d >= 2
        max_abs = max(max_abs, d)
    n = len(recs)
    rate, share = (exact / n, ge2 / n) if n else (0.0, 1.0)
    ok = rate >= limits["exact_min"] and max_abs <= limits["max_abs"] and share <= limits["ge2_max"]
    return {"n": n, "exact": exact, "exact_rate": rate, "max_abs": max_abs, "ge2": ge2, "ge2_share": share,
            "pass": bool(n and ok)}


def p1_verdict(records, gap):
    """P1: PASS iff both columns meet P1_LIMITS; VOID on > 10% excluded rows or a WU gap above the limit."""
    markets = {r["market"] for r in records}
    if markets & EXCLUDED_MARKETS:
        raise RodcForwardRefused(f"excluded market(s) {sorted(markets & EXCLUDED_MARKETS)}")
    scored = [r for r in records if not r["excluded"]]
    excluded = len(records) - len(scored)
    share = excluded / len(records) if records else 1.0
    cols = {"low_so_far": _column(scored, "serve_low", "research_low", P1_LIMITS["low_so_far"]),
            "dewpoint_c": _column(scored, "serve_dew", "research_dew", P1_LIMITS["dewpoint_c"])}
    reasons = {}
    for r in records:
        if r["excluded"]:
            reasons[r["excluded"]] = reasons.get(r["excluded"], 0) + 1
    if gap["void"] or share > P1_EXCLUDED_VOID:
        verdict = "VOID"
    else:
        verdict = "PASS" if all(c["pass"] for c in cols.values()) else "FAIL"
    return {"verdict": verdict, "rows": len(records), "excluded": excluded, "excluded_share": share,
            "excluded_reasons": reasons, "wu_gap": gap, "columns": cols}


# ------------------------------------------------------------------------------------------------ P2

def p2_verdict(frame, ctx):
    """P2 on the caller's forward per-row frame (local_date, market, hour, nest, g1 = per-row Brier).
    Rows where either Brier is non-finite are dropped (paired). PASS iff the upper 95% bound < MARGIN."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc

    if sc.DRAWS != DRAWS:
        raise RodcForwardRefused(f"dev_scorecard.DRAWS {sc.DRAWS} != {DRAWS}")
    f = frame[frame.hour.isin(HOURS)]
    check_look(ctx, dates=f.local_date.astype(str).unique(), markets=f.market.astype(str).unique())
    a, b = f["nest"].to_numpy(float), f["g1"].to_numpy(float)
    ok = np.isfinite(a) & np.isfinite(b)
    if not ok.any():
        raise RodcForwardRefused("no paired P2 rows")
    num, den = (a - b)[ok], b[ok]
    dates = f.local_date.astype(str).str[:10].to_numpy()[ok]
    markets = f.market.astype(str).to_numpy()[ok]
    keys = sorted(set(zip(dates, markets)))
    index = {k: i for i, k in enumerate(keys)}
    cell = np.array([index[k] for k in zip(dates, markets)], int)
    cnt = np.bincount(cell, minlength=len(keys))
    ca = np.bincount(cell, weights=num, minlength=len(keys)) / cnt
    cb = np.bincount(cell, weights=den, minlength=len(keys)) / cnt
    w = l3._date_weights([k[0] for k in keys], DRAWS, SEED)
    res = sc.ratio_interval(w, ca, cb)
    upper = res["ci95"][1]
    if upper is None or not math.isfinite(upper):
        raise RodcForwardRefused("no finite P2 interval")
    return dict(res, margin=MARGIN, verdict="PASS" if upper < MARGIN else "FAIL", superiority=bool(upper < 0),
                n_rows=int(ok.sum()), n_dropped=int((~ok).sum()), n_cells=len(keys),
                n_dates=len({k[0] for k in keys}))


def verdict(p1, p2):
    """Section 5 of the prereg: both PASS -> adoption candidate; P1 VOID -> no verdict; else closes."""
    if p1["verdict"] == "VOID":
        return "VOID"
    if p1["verdict"] == "FAIL":
        return "CLOSE_SERVE_INFEASIBLE"
    return "ADOPTION_CANDIDATE" if p2["verdict"] == "PASS" else "CLOSE_NO_FORWARD_GAIN"
