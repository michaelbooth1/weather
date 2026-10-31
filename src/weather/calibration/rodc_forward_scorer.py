"""R-ODC forward scorer, P1 only (pure, unbound; L8 2026-10-29). Scores the frozen R-ODC forward pre-registration.

Nothing here is served, and it is not in any RELEASE_FILES. It reads forward data only through ``check_look``:

* Embargo: nothing after 2026-09-29 is read before the look. Every read and the verdict refuse unless the look
  context says the look day has come (``today >= look_date``), D0 is the first full local date after the freeze (freeze date + 1; freeze >= 2026-10-30), the look is
  at least 45 days after D0 and on or after the B look receipt, and every date lies in [D0, look_date).
* Denver is excluded (DL 10-23, KDEN vs KBKF), as in test B; a Denver row refuses.

P1, serve parity (no labels): serve = ``odc_metar_features.odc_features`` on the captured snapshot (the capture
host's snapshot store, ``<snapshots root>/<event slug>/replay_inputs.jsonl``, read by ``read_snapshots``) chosen by
``choose_snapshot(rule="last_in_hour")``; research = the training construction on the market's WU history store
(``WundergroundHistoryStore`` at ``spec_for_id(market).data_root``, built as the daily refresh builds it): rows of
local date D with minute_of_day <= h*60, low = min temp_native, dewpoint = dewpoint_native of the latest row.

Countable date: a date >= D0 with at least one non-excluded (market, hour) row, i.e. both the serve and the
research value exist. P1 is scored on the first 45 countable dates; fewer than 45 before the look refuses.
P2 (non-inferiority on dR) was dropped before the freeze (master's ruling, 2026-10-29).

Clarification 1 (master, 2026-10-31, pre-look; ``docs/research/rodc-forward-prereg-2026-10-29/clarification_1.md``,
pinned by ``CLARIFICATION_1_SHA256``): the P1 bounds check compares low, high and current all on the WU whole scale
(``clarified_check_bounds``), and the verdict uses it. The frozen mixed-scale ``odc.check_bounds`` result is kept per
hour as ``refused_frozen`` and disclosed, non-deciding. ``odc_metar_features`` is unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from weather.calibration import odc_metar_features as odc
from weather.model.mg_serve_core import wu_whole_f

EMBARGO_LAST = date(2026, 9, 29)
FREEZE_EARLIEST = date(2026, 10, 30)
N_COUNTABLE = 45
EXCLUDED_MARKETS = frozenset({"denver"})
HOURS = (7, 8, 9, 10, 11, 12)
SNAPSHOT_RULE = "last_in_hour"
REPLAY_INPUTS = "replay_inputs.jsonl"
P1_LIMITS = {"low_so_far": {"exact_min": 0.95, "max_abs": 2.0, "ge2_max": 0.01},
             "dewpoint_c": {"exact_min": 0.97, "max_abs": 5.0, "ge2_max": 0.01}}
P1_EXCLUDED_VOID = 0.10   # more than 10% of the scored rows excluded -> P1 VOID
WU_GAP_VOID = 0.05        # more than 5% of required (market, date) WU days missing after backfill -> VOID
CLARIFICATION_1_PATH = "docs/research/rodc-forward-prereg-2026-10-29/clarification_1.md"
CLARIFICATION_1_SHA256 = "9738ce8d7debbe4722aec21d3964b1abd4c9db4f6963ac1cdece486317b96464"
BOUND_KEYS = ("low_so_far", "high_so_far", "current_temp")


class RodcForwardRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class LookContext:
    freeze_date: date
    d0: date
    look_date: date
    b_receipt_date: date | None
    today: date


def _day(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def first_countable_date(freeze_date):
    """D0 = the first full local date after the freeze: always freeze date + 1, whatever the push hour.

    A date whose 07-12 hours (and possibly its high) had passed when the freeze reached origin never counts.
    """
    return _day(freeze_date) + timedelta(days=1)


def check_look(ctx, *, dates=(), markets=()):
    """Refuse unless the look may happen now and every date/market is in scope. -> sorted unique dates."""
    if not isinstance(ctx, LookContext):
        raise RodcForwardRefused("a LookContext is required")
    if ctx.freeze_date < FREEZE_EARLIEST:
        raise RodcForwardRefused(f"freeze {ctx.freeze_date} is before {FREEZE_EARLIEST}")
    if ctx.d0 != first_countable_date(ctx.freeze_date):
        raise RodcForwardRefused(
            f"D0 {ctx.d0} is not the first full local date after the freeze {ctx.freeze_date}")
    if ctx.look_date < ctx.d0 + timedelta(days=N_COUNTABLE):
        raise RodcForwardRefused(f"look {ctx.look_date} cannot follow {N_COUNTABLE} countable dates from {ctx.d0}")
    if ctx.b_receipt_date is None:
        raise RodcForwardRefused("no B look receipt: the R-ODC look comes after it")
    if ctx.look_date < ctx.b_receipt_date:
        raise RodcForwardRefused(f"look {ctx.look_date} is before the B look receipt {ctx.b_receipt_date}")
    if ctx.today < ctx.look_date:
        raise RodcForwardRefused(f"embargo: today {ctx.today} is before the look {ctx.look_date}")
    bad = sorted(set(markets) & EXCLUDED_MARKETS)
    if bad:
        raise RodcForwardRefused(f"excluded market(s) {bad}")
    days = sorted({_day(d) for d in dates})
    out = [d for d in days if not (ctx.d0 <= d < ctx.look_date)]
    if out:
        raise RodcForwardRefused(f"date(s) outside [D0 {ctx.d0}, look {ctx.look_date}): {out[:3]}")
    return days


# ------------------------------------------------------------------------------------------------ serve side

def snapshots_root():
    from weather.paths import data_path

    return data_path() / "snapshots"


def read_snapshots(market, day, ctx, *, tz, root=None):
    """[{"captured_at": aware local dt, "metar": sources.metar.data}] of ``day``'s captures, in file order, from the
    snapshot store's ``<root>/<event slug>/replay_inputs.jsonl`` (root defaults to ``data_path()/snapshots``; at
    the look it is master's export of that store). A forward read: refused unless ``check_look`` passes. A missing
    event folder gives []."""
    from datetime import datetime

    from weather.market.market_config import event_slug_for_date

    check_look(ctx, dates=[day], markets=[market])
    path = (snapshots_root() if root is None else root) / event_slug_for_date(day, market) / REPLAY_INPUTS
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            snap = json.loads(line)
            raw = snap.get("captured_at_local")
            if not raw:
                continue
            local = datetime.fromisoformat(str(raw)).astimezone(tz)
            if local.date() != day:
                continue
            metar = ((snap.get("sources") or {}).get("metar") or {}).get("data") or {}
            out.append({"captured_at": local, "metar": metar})
    return out


def _levels(metar, day, hour, tz, unit, now):
    """(high_so_far, current_temp) of the chosen snapshot at ``hour``, as ``mg2_p3d_n._observations`` builds them."""
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.model import observed_running_max

    current, _, _ = l3.observations_at_cutoff(metar.get("rows"), day, hour, tz)
    high, _ = observed_running_max.running_max_since_midnight(
        {}, metar, target_date=day, tz=tz, unit=unit, cutoff_hour=hour, now=now, metar_only=True)
    return high, current


# ------------------------------------------------------------------------------------------------ research side

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

def clarified_check_bounds(by_hour):
    """Clarification 1 (a): ``odc.check_bounds`` with low, high and current all mapped to the WU whole scale by
    ``wu_whole_f(v, "half_up")`` first. Monotone, so raw low <= raw high gives rounded low <= rounded high. Raises
    ``odc.OdcMetarRefused`` like the frozen check. -> hours checked."""
    whole = {h: {k: (wu_whole_f(v, "half_up") if k in BOUND_KEYS else v) for k, v in rec.items()}
             for h, rec in by_hour.items()}
    return odc.check_bounds(whole)


def _refuses(check, window):
    try:
        check(window)
    except odc.OdcMetarRefused:
        return True
    return False


def p1_day(market, day, snapshots, wu_rows, ctx, *, tz, unit):
    """P1 records for one (market, date), h07-12, from ``read_snapshots`` and ``read_wu_rows`` output.
    A bound refusal (running min against the previous scored hour) marks that hour: ``refused`` under the clarified
    check (Clarification 1, deciding), ``refused_frozen`` under the frozen ``odc.check_bounds`` (disclosed only)."""
    check_look(ctx, dates=[day], markets=[market])
    captures = [s["captured_at"] for s in snapshots]
    recs, by_hour = [], {}
    for h in HOURS:
        rec = {"market": market, "date": day.isoformat(), "hour": h, "excluded": None, "refused": False,
               "refused_frozen": False}
        i = odc.choose_snapshot(captures, target_date=day, tz=tz, cutoff_hour=h, rule=SNAPSHOT_RULE)
        research = research_features(wu_rows, h)
        if i is None:
            rec["excluded"] = "no_snapshot"
        elif research is None:
            rec["excluded"] = "no_wu_row"
        else:
            metar = snapshots[i]["metar"]
            serve = odc.odc_features(metar, target_date=day, tz=tz, unit=unit, cutoff_hour=h, now=captures[i])
            if serve["reason"]:
                rec["excluded"] = serve["reason"]
            else:
                rec.update(serve_low=serve["low_so_far"], serve_dew=serve["dewpoint_c"],
                           research_low=research["low_so_far"], research_dew=research["dewpoint_c"])
                high, current = _levels(metar, day, h, tz, unit, captures[i])
                by_hour[h] = {"low_so_far": serve["low_so_far"], "high_so_far": high, "current_temp": current}
        recs.append(rec)
    previous = None
    for rec in recs:
        h = rec["hour"]
        if h not in by_hour:
            continue
        window = {h: by_hour[h]}
        if previous is not None:  # running min against the previous hour only; its own bounds were checked
            window[previous] = {"low_so_far": by_hour[previous]["low_so_far"]}
        rec["refused_frozen"] = _refuses(odc.check_bounds, window)
        rec["refused"] = _refuses(clarified_check_bounds, window)
        previous = h
    return recs


def countable_dates(records):
    """Dates with at least one non-excluded (market, hour) row (both serve and research values exist)."""
    return sorted({_day(r["date"]) for r in records if not r["excluded"]})


def _column(recs, serve_key, research_key, limits):
    exact = ge2 = refused = 0
    max_abs = 0.0
    for r in recs:
        s, t = r[serve_key], r[research_key]
        if r["refused"] or (s is None) != (t is None):
            ge2 += 1          # a refusal or a one-sided None is a mismatch in the >= 2 bucket, outside max|diff|
            refused += bool(r["refused"])
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
            "pass": bool(n and ok), "refused": refused, "real_mismatch": ge2 - refused}


def _disclosure(scored, cols):
    """Clarification 1 (d), non-deciding: frozen vs clarified refusal counts, and each column's >= 2 mismatch rate
    with refused hours split out from real mismatches (|diff| >= 2 or a one-sided None)."""
    split = {}
    for name, c in cols.items():
        n = c["n"]
        split[name] = {"refused": c["refused"], "refused_share": c["refused"] / n if n else 0.0,
                       "real_mismatch": c["real_mismatch"], "real_mismatch_share": c["real_mismatch"] / n if n else 0.0}
    return {"non_deciding": True, "clarification": CLARIFICATION_1_PATH,
            "clarification_sha256": CLARIFICATION_1_SHA256,
            "refusals_frozen_check": sum(bool(r.get("refused_frozen")) for r in scored),
            "refusals_clarified_check": sum(bool(r["refused"]) for r in scored), "columns": split}


def p1_verdict(records, wu_present, ctx):
    """P1 on the first 45 countable dates. PASS iff both columns meet P1_LIMITS; VOID when more than 10% of their
    rows are excluded, or more than 5% of the required (market, date) WU days, D0 .. the 45th countable date, are
    missing. ``wu_present``: the (market, date) pairs with WU rows after backfill."""
    markets = sorted({r["market"] for r in records})
    check_look(ctx, dates=[r["date"] for r in records], markets=markets)
    countable = countable_dates(records)
    if len(countable) < N_COUNTABLE:
        raise RodcForwardRefused(f"{len(countable)} countable dates before the look, fewer than {N_COUNTABLE}")
    scored_dates = set(countable[:N_COUNTABLE])
    last = countable[N_COUNTABLE - 1]
    scope = [r for r in records if _day(r["date"]) in scored_dates]
    scored = [r for r in scope if not r["excluded"]]
    excluded = len(scope) - len(scored)
    share = excluded / len(scope)
    span = [ctx.d0 + timedelta(days=k) for k in range((last - ctx.d0).days + 1)]
    gap = wu_gap({(m, d) for m in markets for d in span}, {(m, _day(d)) for m, d in wu_present})
    cols = {"low_so_far": _column(scored, "serve_low", "research_low", P1_LIMITS["low_so_far"]),
            "dewpoint_c": _column(scored, "serve_dew", "research_dew", P1_LIMITS["dewpoint_c"])}
    reasons = {}
    for r in scope:
        if r["excluded"]:
            reasons[r["excluded"]] = reasons.get(r["excluded"], 0) + 1
    if gap["void"] or share > P1_EXCLUDED_VOID:
        verdict = "VOID"
    else:
        verdict = "PASS" if all(c["pass"] for c in cols.values()) else "FAIL"
    return {"verdict": verdict, "countable_dates": len(countable), "last_scored_date": last.isoformat(),
            "rows": len(scope), "excluded": excluded, "excluded_share": share, "excluded_reasons": reasons,
            "wu_gap": gap, "columns": cols, "disclosure": _disclosure(scored, cols)}


def verdict(p1):
    """Prereg section 5: P1 PASS -> eligible as a feature in the next release candidate (that release's own gates
    decide on outcome); FAIL -> R-ODC closes (not servable at parity); VOID -> no verdict."""
    return {"PASS": "ELIGIBLE_FEATURE", "FAIL": "CLOSE_SERVE_INFEASIBLE", "VOID": "VOID"}[p1["verdict"]]
