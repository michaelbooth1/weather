r"""Dead-bucket check (lane L11): is the 13-16 market + rule-4 floor signal worth money? Research only.

Pre-registered in ``C:\t\l11\deadbucket_rule_r2.md`` (sha256 ``RULE_SHA256``: the original rule
``ORIGINAL_RULE_SHA256`` plus dated clarification 1; copies in ``docs/research/market-blend-l11-2026-10-25/``).
No orders, no live-readiness work; International Polymarket venue only; development window only (nothing dated
after 2026-09-29 is read; no 88a, panel or settlement data for 2026-09-30..10-15).

Two phases, run in this order so the exclusion set is fixed before any dev row is read:

    python -m weather.calibration.dead_bucket history --obs <obs.parquet> --wu-root <data\wunderground>
        --out-dir C:\t\l11\db_hist
    python -m weather.calibration.dead_bucket stage-c --obs <obs.parquet> --wu-root <data\wunderground>
        --layout C:\swarm\v3layout --history C:\t\l11\db_hist\dead_bucket_history.json
        --history-sha256 <sha> --out-dir C:\t\l11\db_c

``history``: Aug-Sep 2021-2025 per market, the day-level settlement-proxy violation rate (WU ``max_temp_native``
< H at the cutoff, H = floor(R + 0.5), R the METAR-only running max from L8's ``running_max_since_midnight``),
the excluded set (16:59 rate > X = 2.0%) and the cause of each violation.

``stage-c``: the positive controls first (served 1.774 / 1.526, the floor-only 13-16 PRIMARY5 R 0.9776), then
the dev dead buckets that settled YES with causes, then the GROSS UPPER BOUND (NOT EXECUTABLE): entry at the
first layout snapshot at or after max(first-dead + 60 s, 13:00) within 13:00-16:59 local, NO price
q = 1 - p_market_yes + 0.01, taker fee 0.05 q (1 - q) per share (EF section 10o), unlimited depth, labels
from the layout; $/day summed over non-excluded markets with a date-clustered 95% CI.
``stage-a-scan`` (per market group; up to three in parallel) and ``stage-a-report`` (pools the scans) run
clarification 1's book + trade-print fills on the staged tapes (``--tapes``, its SHA256SUMS sha pinned), streamed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.reporting.scorecards import loss_atlas as la  # refuses import on the capture host

la.refuse_production_import()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from weather.calibration import market_blend as mbl  # noqa: E402
from weather.market.market_registry import REGISTRY  # noqa: E402
from weather.model.observed_running_max import (  # noqa: E402
    observed_target_date_rows,
    running_max_since_midnight,
)
from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402

SCHEMA_HISTORY = "dead_bucket_history/1"
SCHEMA_C = "dead_bucket_stage_c/1"
RULE_SHA256 = "177e9acfd7dc50b60d53bdd236ecef971ebcdf767f9dbf4cd0bd241579b17774"
ORIGINAL_RULE_SHA256 = "a17ed258caaba9a9b0289fe67fbd7d28c83b053f0f33aa9a977093ea401d9663"
# r3 (``C:	\l11\deadbucket_rule_r3.md``): r2 with entry windows outside 13-16 (late primary, early secondary).
RULE_R3_SHA256 = "1abd3f1a8a9c5e30213b87303cdc518932f2ab99020b6eabb5d7dcc42189ae94"
OBS_SHA256 = "37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2"

MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
           "san-francisco", "seattle")
PRIMARY5 = ("atlanta", "austin", "chicago", "dallas", "denver")
UNIT = "F"
X_EXCLUDE = 0.02
HIST_YEARS = (2021, 2022, 2023, 2024, 2025)
HIST_MONTHS = (8, 9)
WU_MIN_ROWS = 20
METAR_MIN_ROWS = 12
CUTOFFS = (("13:00", 13, 0), ("14:00", 14, 0), ("15:00", 15, 0), ("16:00", 16, 0), ("16:59", 16, 59))
DECISIVE = "16:59"
RUNNING_MAX_CUTOFF_HOUR = 17
AVAILABILITY = timedelta(minutes=10)
LATENCY = timedelta(seconds=60)
ENTRY_FIRST = time(13, 0)
ENTRY_LAST = time(16, 59, 59)
# Entry windows: (start hh, mm), (end hh, mm), running-max cutoff hour, history cutoff, entry hours, rule sha.
WINDOWS = {
    "13-16": {"start": (13, 0), "end": (16, 59), "cutoff_hour": 17, "decisive": "16:59",
              "hours": (13, 14, 15, 16), "rule": RULE_SHA256},
    "late": {"start": (17, 0), "end": (20, 59), "cutoff_hour": 21, "decisive": "20:59",
             "hours": (17, 18, 19, 20), "rule": RULE_R3_SHA256},
    "early": {"start": (7, 0), "end": (12, 59), "cutoff_hour": 13, "decisive": "12:59",
              "hours": (7, 8, 9, 10, 11, 12), "rule": RULE_R3_SHA256},
}
R3_EXTRA_CUTOFFS = (("12:59", 12, 59, 13), ("20:59", 20, 59, 21))
SPREAD = 0.01
FEE_RATE = 0.05
MIN_VALUE = 0.005
STAKES = (5.0, 25.0, 100.0)
PRIMARY_STAKE = 25.0
DEV_RANGE = ("2026-08-01", "2026-09-29")
A_WINDOW_FIRST = "2026-08-10"
DEV_LAST = date(2026, 9, 29)
OBS_READ_BEFORE_UTC = pd.Timestamp("2026-09-30T12:00:00Z")  # local 09-29 ends by 07:00Z; later rows dropped
FLOOR_ONLY_EXPECTED = 0.9776
DEAD_KINDS = ("lte", "eq")
CAUSES = ("tgroup_rounding", "non_routine_max", "rounding_and_non_routine", "report_timing", "unexplained")


class ControlFailed(data.Refused):
    exit_code = 7


def fee(q):
    return FEE_RATE * q * (1.0 - q)


def value(q):
    return 1.0 - q - fee(q)


def H(r):
    return None if r is None else int(math.floor(float(r) + 0.5))


def sha256_file(path):
    return data.sha256_file(path)


# ----------------------------------------------------------------------------- observations

def load_obs(path, check_sha=True):
    """Market-station rows (COR dropped) per market, local dates <= 2026-09-29 only."""
    import pyarrow.parquet as pq

    la.screen_input_path(path, "obs")
    if check_sha and sha256_file(path) != OBS_SHA256:
        raise data.Refused(f"refused: {path} sha256 differs from the rule's {OBS_SHA256}")
    t = pq.ParquetFile(path).read(columns=["station", "role", "market", "valid_utc", "tmpf", "tgroup_f",
                                           "is_cor"]).to_pandas()
    t = t[(t.role == "market") & ~t.is_cor.fillna(False).astype(bool) & (t.valid_utc < OBS_READ_BEFORE_UTC)]
    out = {}
    for mk in MARKETS:
        g = t[t.market == mk].sort_values("valid_utc").copy()
        tz = ZoneInfo(REGISTRY[mk].timezone)
        local = g.valid_utc.dt.tz_convert(tz)
        g["local_date"] = local.dt.date
        g = g[g.local_date <= DEV_LAST]
        g["year"] = g.valid_utc.dt.year
        g["minute"] = g.valid_utc.dt.minute
        modal = g.groupby("year").minute.agg(lambda s: int(s.value_counts().sort_index().idxmax()))
        g["routine"] = g.minute.to_numpy() == g.year.map(modal).to_numpy()
        out[mk] = {"tz": tz, "station": str(g.station.iloc[0]) if len(g) else None,
                   "modal_minute_by_year": {int(k): int(v) for k, v in modal.items()},
                   "days": {d: x for d, x in g.groupby("local_date")}}
    return out


def l8_rows(day, variant="base"):
    """L8 row dicts: obs_time = valid_utc; temp_native = tgroup_f else tmpf (base) or tmpf (tmpf variants)."""
    if day is None or not len(day):
        return []
    if variant in ("routine", "both"):
        day = day[day.routine]
    use_tgroup = variant in ("base", "routine")
    rows = []
    for ts, tg, tf in zip(day.valid_utc, day.tgroup_f, day.tmpf):
        v = tg if use_tgroup and tg is not None and not pd.isna(tg) else tf
        if v is None or pd.isna(v):
            continue
        rows.append({"obs_time": ts.isoformat(), "temp_native": float(v)})
    return rows


def local_instant(d, hh, mm, tz, ss=0):
    return datetime.combine(d, time(hh, mm, ss), tz)


def running(rows, d, tz, now, cutoff_hour=RUNNING_MAX_CUTOFF_HOUR):
    return running_max_since_midnight(None, {"rows": rows}, target_date=d, tz=tz, unit=UNIT,
                                      cutoff_hour=cutoff_hour, now=now)


def n_rows_by(rows, d, tz, now):
    return len(observed_target_date_rows(None, {"rows": rows}, target_date=d, tz=tz, unit=UNIT, now=now))


def variant_h(day, d, tz, variant, now):
    return H(running(l8_rows(day, variant), d, tz, now)[0])


def h_steps(day, d, tz, end_hm=(16, 59), cutoff_hour=RUNNING_MAX_CUTOFF_HOUR):
    """[(obs instant local, H)] at every observation <= ``end_hm`` local (default 16:59; H non-decreasing)."""
    rows = l8_rows(day)
    end = local_instant(d, *end_hm, tz)
    steps = []
    for r in rows:
        t = datetime.fromisoformat(r["obs_time"]).astimezone(tz)
        if t.date() != d or t > end:
            continue
        h = H(running(rows, d, tz, t, cutoff_hour)[0])
        if h is not None:
            steps.append((t, h))
    steps.sort(key=lambda s: s[0])
    return steps


def first_dead(steps, edge):
    """First-dead instant of a bucket with upper edge ``edge``: the first obs with H > edge, + 10 min."""
    for t, h in steps:
        if h > edge:
            return t + AVAILABILITY
    return None


def _hhmm_minutes(text):
    try:
        hh, mm = str(text).split(":")[:2]
        return int(hh) * 60 + int(mm)
    except (TypeError, ValueError):
        return None


def classify(gone, first_minute, wu_last_time=None):
    """First match wins: (a) tmpf, (b) routine, (c) both, (d) report timing, (e) unexplained."""
    if gone["tmpf"]:
        return "tgroup_rounding"
    if gone["routine"]:
        return "non_routine_max"
    if gone["both"]:
        return "rounding_and_non_routine"
    last = _hhmm_minutes(wu_last_time) if wu_last_time is not None else None
    if first_minute is not None and (first_minute < 60 or (last is not None and first_minute > last)):
        return "report_timing"
    return "unexplained"


# ----------------------------------------------------------------------------- WU history

def load_wu(wu_root, market):
    path = Path(wu_root) / REGISTRY[market].icao.lower() / "daily" / "daily_summary.csv"
    w = pd.read_csv(path, usecols=["local_date", "row_count", "first_time", "last_time", "max_temp_native"])
    w["local_date"] = pd.to_datetime(w.local_date).dt.date
    w = w[w.local_date <= DEV_LAST]
    return w.drop_duplicates("local_date", keep="last").set_index("local_date"), path


def history(obs, wu_root, extra=()):
    """r2's history; ``extra`` adds (name, hh, mm, running cutoff hour) cutoffs (r3), the kept days unchanged."""
    per_market, violations = {}, []
    for mk in MARKETS:
        o = obs[mk]
        tz = o["tz"]
        wu, wu_path = load_wu(wu_root, mk)
        wu = wu[[d.year in HIST_YEARS and d.month in HIST_MONTHS for d in wu.index]]
        counts = {"wu_days": int(len(wu)), "kept": 0, "drop_wu_rows": 0, "drop_metar_rows": 0}
        viol = {c: 0 for c, _, _ in CUTOFFS}
        viol.update({c: 0 for c, _, _, _ in extra})
        for d, w in wu.iterrows():
            if pd.isna(w.row_count) or int(w.row_count) < WU_MIN_ROWS or pd.isna(w.max_temp_native):
                counts["drop_wu_rows"] += 1
                continue
            day = o["days"].get(d)
            rows = l8_rows(day)
            end = local_instant(d, 16, 59, tz)
            if n_rows_by(rows, d, tz, end) < METAR_MIN_ROWS:
                counts["drop_metar_rows"] += 1
                continue
            counts["kept"] += 1
            wu_max = float(w.max_temp_native)
            for c, hh, mm in CUTOFFS:
                h = H(running(rows, d, tz, local_instant(d, hh, mm, tz))[0])
                if h is not None and wu_max < h:
                    viol[c] += 1
            for c, hh, mm, ch in extra:
                h = H(running(rows, d, tz, local_instant(d, hh, mm, tz), ch)[0])
                if h is not None and wu_max < h:
                    viol[c] += 1
            r, first_minute = running(rows, d, tz, end)
            h = H(r)
            if h is not None and wu_max < h:
                gone = {}
                for v in ("tmpf", "routine", "both"):
                    hv = variant_h(day, d, tz, v, end)
                    gone[v] = hv is None or wu_max >= hv
                violations.append({"market": mk, "date": str(d), "wu_max": wu_max, "H_1659": h, "R_1659": r,
                                   "shortfall": h - wu_max, "max_minute": first_minute,
                                   "wu_last_time": str(w.last_time), "wu_row_count": int(w.row_count),
                                   "gone": gone, "cause": classify(gone, first_minute, w.last_time)})
        rates = {c: (viol[c] / counts["kept"] if counts["kept"] else None) for c in viol}
        causes = {k: 0 for k in CAUSES}
        for v in violations:
            if v["market"] == mk:
                causes[v["cause"]] += 1
        per_market[mk] = {"station": o["station"], "wu_path": str(wu_path), "wu_sha256": sha256_file(wu_path),
                          "modal_minute_by_year": o["modal_minute_by_year"], "counts": counts,
                          "violations": viol, "rates": rates, "causes": causes,
                          "excluded": rates[DECISIVE] is None or rates[DECISIVE] > X_EXCLUDE}
    excluded = sorted(mk for mk, v in per_market.items() if v["excluded"])
    return {"per_market": per_market, "violations": violations, "excluded": excluded,
            "kept_markets": [mk for mk in MARKETS if mk not in excluded]}


# ----------------------------------------------------------------------------- stage C

def summarise(per_date, dates):
    """Mean over ``dates`` of a {date: $} map (missing = 0) with the date-clustered 95% CI and MDE80."""
    x = np.array([per_date.get(d, 0.0) for d in dates], float)
    if not len(x):
        return {"estimate": None, "ci95": [None, None], "n_dates": 0}
    w = sc.crossed_weights(list(dates), ["all"] * len(dates))
    out = sc.ratio_interval(w, x, np.ones_like(x))
    boot = (w @ x) / (w @ np.ones_like(x))
    out.update(sc.mde80(out["estimate"], boot, effect=1.0))
    out["n_dates"] = len(dates)
    out["n_dates_nonzero"] = int(np.count_nonzero(x))
    return out


def layout_market_days(layout):
    snaps = layout.snaps.copy()
    snaps["captured"] = pd.to_datetime(snaps.captured_at_utc, utc=True)
    snaps["date"] = snaps.date.astype(str)
    price = layout.market.set_index(["row_key", "band_index"]).p_market_yes
    bands = layout.bands
    labels = layout.labels.set_index("row_key")
    for (mk, d), s in snaps.groupby(["market", "date"]):
        s = s.sort_values("captured")
        b = bands[bands.row_key.isin(set(s.row_key))]
        geo = b.drop_duplicates(["band_index", "kind", "low", "high"])
        if geo.band_index.duplicated().any():
            raise data.LayoutError(f"{mk} {d}: band geometry changes within the day")
        win = labels.reindex(s.row_key)
        winners = set(win.winner.dropna().astype(int))
        if len(winners) != 1:
            raise data.LayoutError(f"{mk} {d}: {len(winners)} distinct winners")
        sh = win.settlement_high.dropna()
        yield mk, d, s, geo.sort_values("band_index"), price, winners.pop(), (float(sh.iloc[0]) if len(sh) else None)


def stage_c_trades(layout, obs, wu_root, kept):
    trades, settled_yes, dead_counts = [], [], {}
    wu_last = {mk: load_wu(wu_root, mk)[0].last_time.to_dict() for mk in MARKETS}
    for mk, d, s, geo, price, winner, settlement_high in layout_market_days(layout):
        o = obs[mk]
        tz = o["tz"]
        dd = date.fromisoformat(d)
        day = o["days"].get(dd)
        steps = h_steps(day, dd, tz)
        end = local_instant(dd, 16, 59, tz)
        r_end, max_minute = running(l8_rows(day), dd, tz, end)
        h_end = H(r_end)
        local = s.captured.dt.tz_convert(tz)
        in_window = ((local.dt.time >= ENTRY_FIRST) & (local.dt.time <= ENTRY_LAST)).to_numpy()
        variants = None
        n_dead = 0
        for band in geo.itertuples(index=False):
            if band.kind not in DEAD_KINDS or h_end is None or not float(band.high) < h_end:
                continue
            n_dead += 1
            fd = first_dead(steps, float(band.high))
            if fd is None:  # cannot happen: H(16:59) is the last step's H
                raise data.LayoutError(f"{mk} {d}: dead bucket without a first-dead instant")
            bi = int(band.band_index)
            yes = winner == bi
            if yes:
                if variants is None:
                    variants = {v: variant_h(day, dd, tz, v, end) for v in ("tmpf", "routine", "both")}
                gone = {v: hv is None or float(band.high) >= hv for v, hv in variants.items()}
                settled_yes.append({"market": mk, "date": d, "band_index": bi, "kind": band.kind,
                                    "low": band.low, "high": band.high, "H_1659": h_end, "R_1659": r_end,
                                    "settlement_high": settlement_high, "first_dead": fd.isoformat(),
                                    "excluded_market": mk not in kept, "gone": gone,
                                    "cause": classify(gone, max_minute, wu_last[mk].get(dd))})
            entry = max(fd + LATENCY, local_instant(dd, 13, 0, tz))
            rec = {"market": mk, "date": d, "band_index": bi, "kind": band.kind, "high": float(band.high),
                   "first_dead": fd.isoformat(), "entry_instant": entry.isoformat(), "settled_yes": bool(yes),
                   "excluded_market": mk not in kept}
            idx = np.flatnonzero(in_window & (s.captured >= pd.Timestamp(entry)).to_numpy())
            if not len(idx):
                trades.append(dict(rec, status="no_snapshot"))
                continue
            i = int(idx[0])
            p = price.get((s.row_key.iloc[i], bi))
            if p is None or pd.isna(p):
                trades.append(dict(rec, status="no_price"))
                continue
            q = 1.0 - float(p) + SPREAD
            rec.update(snapshot=s.row_key.iloc[i], snapshot_local=local.iloc[i].isoformat(),
                       entry_hour=int(local.iloc[i].hour), p_market_yes=float(p), q=q, value=value(q))
            if value(q) < MIN_VALUE:
                trades.append(dict(rec, status="no_value"))
                continue
            stop = end
            for j in range(i + 1, len(s)):
                tj = local.iloc[j]
                if tj > end:
                    break
                pj = price.get((s.row_key.iloc[j], bi))
                if pj is None or pd.isna(pj) or value(1.0 - float(pj) + SPREAD) < MIN_VALUE:
                    stop = tj
                    break
            rec["duration_min"] = max(0.0, (stop - entry).total_seconds() / 60.0)
            for stake in STAKES:
                shares = stake / q
                fees = shares * fee(q)
                rec[f"pnl_{int(stake)}"] = -stake - fees if yes else shares * (1.0 - q) - fees
            trades.append(dict(rec, status="traded"))
        dead_counts[(mk, d)] = n_dead
    return trades, settled_yes, dead_counts


def pnl_tables(trades, dates, members, rates, stake=PRIMARY_STAKE, expected_loss=False, hour=None):
    per_date = {}
    for t in trades:
        if t["status"] != "traded" or t["market"] not in members or t["date"] not in dates:
            continue
        if hour is not None and t["entry_hour"] != hour:
            continue
        if expected_loss:
            q, rate = t["q"], rates[t["market"]]
            shares = stake / q
            pnl = (1.0 - rate) * shares * (1.0 - q) - rate * stake - shares * fee(q)
        else:
            pnl = t[f"pnl_{int(stake)}"]
        per_date[t["date"]] = per_date.get(t["date"], 0.0) + pnl
    return summarise(per_date, dates)


def stage_c(trades, dates_all, kept, rates):
    windows = {"2026-08-01..09-29": dates_all, "2026-08-10..09-29": [d for d in dates_all if d >= A_WINDOW_FIRST]}
    out = {}
    for wname, dates in windows.items():
        res = {"primary_25": pnl_tables(trades, dates, kept, rates),
               "ladder": {str(int(s)): pnl_tables(trades, dates, kept, rates, stake=s) for s in STAKES},
               "expected_loss_25": pnl_tables(trades, dates, kept, rates, expected_loss=True),
               "primary5_25": pnl_tables(trades, dates, [m for m in PRIMARY5 if m in kept], rates),
               "per_hour_25": {str(h): pnl_tables(trades, dates, kept, rates, hour=h) for h in (13, 14, 15, 16)},
               "per_market_25": {mk: dict(pnl_tables(trades, dates, [mk], rates), excluded=mk not in kept)
                                 for mk in MARKETS}}
        res["reading"] = reading_c(res)
        out[wname] = res
    return out


def reading_c(res):
    up = res["primary_25"]["ci95"][1]
    p100 = res["ladder"]["100"]["estimate"]
    if up is None or p100 is None:
        return "NO TRADES: not worth pursuing on the upper bound"
    if up <= 0 or p100 < 1.0:
        return "NOT WORTH PURSUING (upper bound already fails: $25 upper CI <= 0 or $100 point < $1/day)"
    return "NOT EXCLUDED BY THE UPPER BOUND; A decides (stage C never supports a money claim)"


def trade_summary(trades, kept):
    rows = [t for t in trades if t["market"] in kept]
    status = {}
    for t in rows:
        status[t["status"]] = status.get(t["status"], 0) + 1
    traded = [t for t in rows if t["status"] == "traded"]
    dur = np.array([t["duration_min"] for t in traded], float)
    return {"dead_buckets_kept_markets": len(rows), "status": status,
            "traded_settled_yes": int(sum(t["settled_yes"] for t in traded)),
            "dead_settled_yes": int(sum(t["settled_yes"] for t in rows)),
            "duration_min": ({"n": int(len(dur)), "median": float(np.median(dur)), "mean": float(dur.mean()),
                              "p90": float(np.quantile(dur, .9))} if len(dur) else {"n": 0}),
            "q_traded": ({"median": float(np.median([t["q"] for t in traded])),
                          "min": float(min(t["q"] for t in traded))} if traded else {})}


def controls(layout_path):
    """Served 1.774 / 1.526 and the floor-only 13-16 PRIMARY5 R 0.9776 on market_blend's scored table."""
    start, end = data.check_range(*mbl.RANGE)
    layout = data.load_layout(layout_path, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    score_t = sc.Table(layout, scored)
    served = la.positive_control(score_t)
    fo = next(r for r in mbl.floor_only_rows(score_t) if r["pool"] == "PRIMARY5" and r["group"] == "13-16")
    floor = {"R": fo["R"], "ci95_date": fo.get("ci95_date"), "expected": FLOOR_ONLY_EXPECTED,
             "verdict": "PASS" if round(fo["R"], 4) == FLOOR_ONLY_EXPECTED else "FAIL"}
    out = {"served": served, "floor_only_13_16_primary5": floor}
    if floor["verdict"] != "PASS":
        raise ControlFailed(f"refused: floor-only control failed {floor}")
    return out, layout


# ----------------------------------------------------------------------------- CLI

def _code():
    return {"code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "running_max_sha256": hashlib.sha256(Path(sys.modules[running_max_since_midnight.__module__].__file__)
                                                 .read_bytes()).hexdigest()}


def r3_history_control(res, control_path, control_sha):
    """r3 positive control: r2's rates at 13:00..16:59 and its excluded set reproduce exactly."""
    actual = sha256_file(control_path)
    if actual != control_sha:
        raise data.Refused(f"refused: control history sha256 {actual} != {control_sha}")
    ref = json.loads(Path(control_path).read_text(encoding="utf-8"))
    if ref.get("schema") != SCHEMA_HISTORY or ref.get("rule_sha256") != RULE_SHA256:
        raise data.Refused("refused: control history is not r2's history phase")
    diffs = [(mk, c) for mk in MARKETS for c, _, _ in CUTOFFS
             if ref["per_market"][mk]["rates"][c] != res["per_market"][mk]["rates"][c]]
    if diffs or ref["excluded"] != res["excluded"]:
        raise ControlFailed(f"refused: r3 history does not reproduce r2 {diffs[:5]} {ref['excluded']}")
    return {"r2_history_sha256": actual, "verdict": "PASS", "cutoffs": [c for c, _, _ in CUTOFFS]}


def run_history(args):
    obs = load_obs(args.obs, check_sha=not args.no_obs_sha)
    if args.window_rule == "r3":
        if not (args.control_history and args.control_history_sha256):
            raise data.Refused("refused: r3 history needs --control-history(-sha256) (r2's history)")
        res = history(obs, args.wu_root, extra=R3_EXTRA_CUTOFFS)
        control = r3_history_control(res, args.control_history, args.control_history_sha256)
        by_w = {}
        for w in ("late", "early"):
            dec = WINDOWS[w]["decisive"]
            exc = sorted(mk for mk, v in res["per_market"].items()
                         if v["rates"][dec] is None or v["rates"][dec] > X_EXCLUDE)
            by_w[w] = {"decisive": dec, "excluded": exc, "kept_markets": [mk for mk in MARKETS if mk not in exc]}
        return dict({"schema": SCHEMA_HISTORY, "rule_sha256": RULE_R3_SHA256, "obs_sha256": OBS_SHA256,
                     "control": control, "windows": by_w,
                     "constants": {"X": X_EXCLUDE, "years": HIST_YEARS, "months": HIST_MONTHS,
                                   "wu_min_rows": WU_MIN_ROWS, "metar_min_rows": METAR_MIN_ROWS,
                                   "cutoffs": [c for c, _, _ in CUTOFFS] + [c for c, _, _, _ in R3_EXTRA_CUTOFFS]}},
                    **_code(), **res)
    res = history(obs, args.wu_root)
    return dict({"schema": SCHEMA_HISTORY, "rule_sha256": RULE_SHA256, "obs_sha256": OBS_SHA256,
                 "constants": {"X": X_EXCLUDE, "years": HIST_YEARS, "months": HIST_MONTHS, "wu_min_rows": WU_MIN_ROWS,
                               "metar_min_rows": METAR_MIN_ROWS, "cutoffs": [c for c, _, _ in CUTOFFS],
                               "decisive": DECISIVE}}, **_code(), **res)


def run_stage_c(args):
    hist_path = Path(args.history)
    actual = sha256_file(hist_path)
    if actual != args.history_sha256:
        raise data.Refused(f"refused: history sha256 {actual} != {args.history_sha256}")
    hist = json.loads(hist_path.read_text(encoding="utf-8"))
    if hist.get("schema") != SCHEMA_HISTORY or hist.get("rule_sha256") != RULE_SHA256:
        raise data.Refused("refused: history file is not this rule's history phase")
    kept = hist["kept_markets"]
    rates = {mk: v["rates"][DECISIVE] for mk, v in hist["per_market"].items()}
    la.screen_input_path(args.layout, "layout")
    ctrl, layout = controls(args.layout)  # controls before any dead-bucket row
    obs = load_obs(args.obs, check_sha=not args.no_obs_sha)
    trades, settled_yes, dead_counts = stage_c_trades(layout, obs, args.wu_root, kept)
    dates_all = sorted({str(d) for d in layout.snaps.date.astype(str)})
    yes_by_market = {mk: {"n": 0, "causes": {k: 0 for k in CAUSES}} for mk in MARKETS}
    for r in settled_yes:
        yes_by_market[r["market"]]["n"] += 1
        yes_by_market[r["market"]]["causes"][r["cause"]] += 1
    dead_by_market = {mk: int(sum(v for (m, _), v in dead_counts.items() if m == mk)) for mk in MARKETS}
    return dict({"schema": SCHEMA_C, "rule_sha256": RULE_SHA256, "history_sha256": actual,
                 "layout_manifest_sha256": layout.manifest_sha256, "evidence_class":
                 "development (dev window); stage C = GROSS UPPER BOUND, NOT EXECUTABLE",
                 "constants": {"spread": SPREAD, "fee_rate": FEE_RATE, "min_value": MIN_VALUE, "stakes": STAKES,
                               "latency_s": LATENCY.total_seconds(), "availability_min": 10,
                               "draws": sc.DRAWS, "seed": sc.SEED},
                 "excluded": hist["excluded"], "kept_markets": kept, "controls": ctrl,
                 "dates": {"first": dates_all[0], "last": dates_all[-1], "n": len(dates_all)},
                 "dead_buckets_by_market": dead_by_market, "settled_yes_by_market": yes_by_market,
                 "settled_yes": settled_yes, "trade_summary": trade_summary(trades, kept),
                 "results": stage_c(trades, dates_all, kept, rates), "trades": trades}, **_code())


def _f(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def _ci(ci, d=2):
    return f"[{_f(ci[0], d)}, {_f(ci[1], d)}]" if ci else "n/a"


def render_history(p):
    lines = ["# Dead-bucket history: settlement-proxy violation rates (Aug-Sep 2021-2025)", "",
             f"Rule sha256 `{p['rule_sha256']}`; X = {p['constants']['X']:.1%} at {DECISIVE}. "
             f"Excluded: {', '.join(p['excluded']) or 'none'}.", "",
             "| market | kept days | 13:00 | 14:00 | 15:00 | 16:00 | 16:59 | excluded | causes |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for mk, v in p["per_market"].items():
        r = v["rates"]
        causes = ", ".join(f"{k} {n}" for k, n in v["causes"].items() if n)
        lines.append(f"| {mk} | {v['counts']['kept']} | " + " | ".join(
            "n/a" if r[c] is None else f"{r[c]:.2%}" for c, _, _ in CUTOFFS) + f" | {v['excluded']} | {causes} |")
    if "windows" in p:  # r3: the added cutoffs and the per-window exclusion
        lines += ["", f"r3 control (r2 rates reproduce): {p['control']['verdict']}.", "",
                  "| market | 12:59 | 20:59 |", "| --- | --- | --- |"]
        for mk, v in p["per_market"].items():
            lines.append(f"| {mk} | " + " | ".join("n/a" if v["rates"][c] is None else f"{v['rates'][c]:.2%}"
                                                  for c in ("12:59", "20:59")) + " |")
        for w, x in p["windows"].items():
            lines.append(f"\nWindow {w}: decisive {x['decisive']}, excluded {', '.join(x['excluded']) or 'none'}.")
    return "\n".join(lines) + "\n"


def render_c(p):
    lines = ["# Dead-bucket stage C: GROSS UPPER BOUND (NOT EXECUTABLE)", "",
             f"Rule sha256 `{p['rule_sha256']}`; history `{p['history_sha256']}`; excluded "
             f"{', '.join(p['excluded']) or 'none'}. Controls: served {p['controls']['served']['verdict']}, "
             f"floor-only {p['controls']['floor_only_13_16_primary5']['verdict']} "
             f"(R {p['controls']['floor_only_13_16_primary5']['R']:.4f}).", ""]
    for w, res in p["results"].items():
        lines += [f"## {w}: {res['reading']}", "", "| row | $/day | 95% CI (date) | MDE80 | dates nonzero |",
                  "| --- | --- | --- | --- | --- |"]
        rows = [("$25 primary (kept markets)", res["primary_25"])]
        rows += [(f"${k}", v) for k, v in res["ladder"].items()]
        rows += [("$25 expected-loss", res["expected_loss_25"]), ("$25 PRIMARY5", res["primary5_25"])]
        rows += [(f"$25 entry hour {h}", v) for h, v in res["per_hour_25"].items()]
        rows += [(f"$25 {mk}{' (excluded)' if v['excluded'] else ''}", v) for mk, v in res["per_market_25"].items()]
        for name, v in rows:
            lines.append(f"| {name} | {_f(v['estimate'])} | {_ci(v['ci95'])} | {_f(v.get('mde80'))} | "
                         f"{v.get('n_dates_nonzero', 0)}/{v['n_dates']} |")
        lines.append("")
    lines += ["## Dev dead buckets that settled YES", "", "| market | dead buckets | settled YES | causes |",
              "| --- | --- | --- | --- |"]
    for mk in MARKETS:
        y = p["settled_yes_by_market"][mk]
        lines.append(f"| {mk} | {p['dead_buckets_by_market'][mk]} | {y['n']} | "
                     + ", ".join(f"{k} {n}" for k, n in y["causes"].items() if n) + " |")
    lines += ["", f"Trade summary (kept markets): `{json.dumps(sc._clean(p['trade_summary']))}`", ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- stage A (clarification 1)

SCHEMA_A_SCAN = "dead_bucket_stage_a_scan/1"
SCHEMA_A = "dead_bucket_stage_a/1"
PRINT_WINDOW = timedelta(minutes=5)
A_VARIANTS = ("print_d1", "print_d5", "book_d1")  # primary: print_d1 (trade-print cap + 1% depth)
A_PRIMARY_VARIANT = "print_d1"
BOOK_ONLY_LAST = "2026-08-09"
_SUMMARY_FIELDS = ("captured_at_utc", "bin_kind", "bin_value", "bin_value_hi", "outcome", "clob_token_id",
                   "best_bid", "best_ask", "bid_depth_1pct", "ask_depth_1pct", "bid_depth_5pct", "ask_depth_5pct")


def _num(text):
    try:
        x = float(text)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _utc(text):
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def discover_tape_events(root):
    """{(market, 'YYYY-MM-DD'): folder} for event folders dated <= 2026-09-29 (later folders never opened)."""
    from weather.market.execution_tape_markout import target_date_from_slug
    from weather.market.market_registry import spec_for_slug

    out = {}
    for child in sorted(Path(root).iterdir()):
        if not child.is_dir():
            continue
        spec, d = spec_for_slug(child.name), target_date_from_slug(child.name)
        if spec is None or d is None or d > DEV_LAST:
            continue
        out[(spec.id, d.isoformat())] = child
    return out


def bucket_key(kind, low, high):
    """The book summary's bin identity: lte X -> (lte, X); eq lo-hi -> (eq, lo, hi)."""
    if kind == "lte":
        return ("lte", float(high))
    if kind == "eq":
        return ("eq", float(low), float(high))
    return None


def summary_key(kind, value, value_hi):
    kind = str(kind or "").strip().lower()
    v, vh = _num(value), _num(value_hi)
    if kind == "lte" and v is not None:
        return ("lte", v)
    if kind == "eq" and v is not None and vh is not None:
        return ("eq", v, vh)
    return None


def stream_summary(path, wanted, t_first, t_last):
    """Stream order_books_summary.csv once; keep the wanted buckets' rows inside [t_first, t_last] only.

    Returns ({(key, side): [(t, best_bid, best_ask, bid_d1, ask_d1, bid_d5, ask_d5)]}, {token: (key, side)}, n_rows).
    """
    import csv

    csv.field_size_limit(2**31 - 1)  # captured rows can carry very long fields; values used are short
    rows, tokens, n, bad = {}, {}, 0, 0
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        missing = [f for f in _SUMMARY_FIELDS if f not in header]
        if missing:
            raise data.LayoutError(f"{path}: summary columns missing {missing}")
        idx = {name: header.index(name) for name in _SUMMARY_FIELDS}
        for rec in reader:
            n += 1
            if len(rec) != len(header) or max(map(len, rec), default=0) > 4096:
                bad += 1  # torn, merged or oversized row: never used
                continue
            key = summary_key(rec[idx["bin_kind"]], rec[idx["bin_value"]], rec[idx["bin_value_hi"]])
            if key not in wanted:
                continue
            side = rec[idx["outcome"]].strip().lower()
            if side not in ("yes", "no"):
                continue
            tokens[rec[idx["clob_token_id"]].strip()] = (key, side)
            t = _utc(rec[idx["captured_at_utc"]])
            if t is None or t < t_first or t > t_last:
                continue
            rows.setdefault((key, side), []).append((t, *(_num(rec[idx[f]]) for f in (
                "best_bid", "best_ask", "bid_depth_1pct", "ask_depth_1pct", "bid_depth_5pct", "ask_depth_5pct"))))
    for v in rows.values():
        v.sort(key=lambda r: r[0])
    return rows, tokens, (n, bad)


def stream_prints(folder, tokens, t_first, t_last):
    """Trade prints (last_trade_price) on the wanted tokens in [t_first, t_last]: [(t, key, side, price, size)]."""
    from weather.market.execution_tape_markout import parse_trade_line, trade_part_paths

    out, parts, seen = [], trade_part_paths(Path(folder)), set()
    for path in parts:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                tr, _ = parse_trade_line(line)
                if tr is None or tr["token"] not in tokens or tr["identity"] in seen:
                    continue
                seen.add(tr["identity"])
                t = datetime.fromtimestamp(tr["epoch_seconds"], tz=t_first.tzinfo)
                if t_first <= t <= t_last:
                    key, side = tokens[tr["token"]]
                    out.append((t, key, side, tr["price"], tr["size"]))
    return out, len(parts)


def no_quote(rows, key, t0, strict_after=False):
    """First capture at/after t0: (t, q, depth1, depth5, source), the NO ask, else 1 - the YES bid."""
    def first(side, price_i, d1_i, d5_i):
        for r in rows.get((key, side), []):
            if (r[0] > t0 if strict_after else r[0] >= t0) and r[price_i] is not None:
                return r[0], r[price_i], r[d1_i], r[d5_i]
        return None
    no = first("no", 2, 4, 6)
    yes = first("yes", 1, 3, 5)
    if no is not None and (yes is None or no[0] <= yes[0]):
        return no[0], no[1], no[2] or 0.0, no[3] or 0.0, "no_ask"
    if yes is not None:
        return yes[0], 1.0 - yes[1], yes[2] or 0.0, yes[3] or 0.0, "one_minus_yes_bid"
    return None


def a_fills(stake, q, d1, d5, printed):
    want = stake / q
    return {"print_d1": min(want, d1, printed), "print_d5": min(want, d5, printed), "book_d1": min(want, d1)}


def a_pnl(filled, q, yes):
    return -filled * q - filled * fee(q) if yes else filled * (1.0 - q) - filled * fee(q)


def stage_a_scan(layout, obs, tapes_root, markets, kept, window="13-16"):
    W = WINDOWS[window]
    events = discover_tape_events(tapes_root)
    buckets, days = [], []
    for mk, d, s, geo, price, winner, settlement_high in layout_market_days(layout):
        if mk not in markets:
            continue
        tz = obs[mk]["tz"]
        dd = date.fromisoformat(d)
        day = obs[mk]["days"].get(dd)
        steps = h_steps(day, dd, tz, W["end"], W["cutoff_hour"])
        end = local_instant(dd, *W["end"], tz)
        h_end = H(running(l8_rows(day), dd, tz, end, W["cutoff_hour"])[0])
        dead = []
        for band in geo.itertuples(index=False):
            if band.kind not in DEAD_KINDS or h_end is None or not float(band.high) < h_end:
                continue
            fd = first_dead(steps, float(band.high))
            dead.append((band, fd, max(fd + LATENCY, local_instant(dd, *W["start"], tz))))
        folder = events.get((mk, d))
        info = {"market": mk, "date": d, "n_dead": len(dead), "folder": folder.name if folder else None}
        if not dead or folder is None:
            days.append(dict(info, status="no_dead" if not dead else "no_tape_folder"))
            for band, fd, entry in dead:
                buckets.append({"market": mk, "date": d, "band_index": int(band.band_index),
                                "status": "no_tape_folder", "excluded_market": mk not in kept})
            continue
        wanted = {bucket_key(b.kind, b.low, b.high): (b, fd, en) for b, fd, en in dead}
        t_first = min(en for _, _, en in dead)
        rows, tokens, n_rows = stream_summary(folder / "order_books_summary.csv", set(wanted), t_first, end)
        prints, n_parts = stream_prints(folder, tokens, t_first, end + PRINT_WINDOW)
        n_rows, n_bad = n_rows
        days.append(dict(info, status="scanned", summary_rows=n_rows, summary_bad_rows=n_bad, trade_parts=n_parts, prints_kept=len(prints),
                         tokens_matched=len(tokens)))
        for key, (band, fd, entry) in wanted.items():
            bi = int(band.band_index)
            yes = winner == bi
            rec = {"market": mk, "date": d, "band_index": bi, "kind": band.kind, "high": float(band.high),
                   "first_dead": fd.isoformat(), "entry_instant": entry.isoformat(), "settled_yes": bool(yes),
                   "excluded_market": mk not in kept, "trade_parts": n_parts}
            qt = no_quote(rows, key, entry)
            if qt is None or qt[0] > end:
                buckets.append(dict(rec, status="no_capture"))
                continue
            t_q, q, d1, d5, source = qt
            rec.update(capture_utc=t_q.isoformat(), entry_hour=int(t_q.astimezone(tz).hour), q=q,
                       quote_source=source, depth1=d1, depth5=d5, value=value(q))
            if value(q) < MIN_VALUE:
                buckets.append(dict(rec, status="no_value"))
                continue
            w_end = entry + PRINT_WINDOW
            printed = sum(sz for t, k, side, p, sz in prints if k == key and entry <= t <= w_end
                          and ((side == "no" and p <= q + 1e-12) or (side == "yes" and p >= 1.0 - q - 1e-12)))
            stop, t_cur = end, t_q
            while True:
                nxt = no_quote(rows, key, t_cur, strict_after=True)
                if nxt is None or nxt[0] > end:
                    break
                if value(nxt[1]) < MIN_VALUE:
                    stop = nxt[0]
                    break
                t_cur = nxt[0]
            rec.update(printed_shares=printed, duration_min=max(0.0, (stop - entry).total_seconds() / 60.0))
            for stake in STAKES:
                for var, filled in a_fills(stake, q, d1, d5, printed).items():
                    rec[f"filled_{var}_{int(stake)}"] = filled
                    rec[f"pnl_{var}_{int(stake)}"] = a_pnl(filled, q, yes)
            buckets.append(dict(rec, status="traded"))
    return buckets, days


def a_table(buckets, dates, members, rates, variant, stake=PRIMARY_STAKE, expected_loss=False, hour=None):
    per_date = {}
    for b in buckets:
        if b["status"] != "traded" or b["market"] not in members or b["date"] not in dates:
            continue
        if hour is not None and b["entry_hour"] != hour:
            continue
        filled = b[f"filled_{variant}_{int(stake)}"]
        if expected_loss:
            q, r = b["q"], rates[b["market"]]
            pnl = (1.0 - r) * filled * (1.0 - q) - r * filled * q - filled * fee(q)
        else:
            pnl = b[f"pnl_{variant}_{int(stake)}"]
        per_date[b["date"]] = per_date.get(b["date"], 0.0) + pnl
    return summarise(per_date, dates)


def reading_a(primary):
    lo = primary["ci95"][0]
    if lo is not None and lo > 0:
        return "WORTH AN OWNER DECISION on a forward paper test (lower CI > 0; development evidence)"
    return "NOT WORTH PURSUING (lower CI <= 0)"


def stage_a_report(buckets, days, dates_all, kept, rates, window="13-16"):
    hours = WINDOWS[window]["hours"]
    win_a = [d for d in dates_all if d >= A_WINDOW_FIRST]
    win_b = [d for d in dates_all if d <= BOOK_ONLY_LAST]

    def block(dates, variant):
        return {"variant": variant,
                "primary_25": a_table(buckets, dates, kept, rates, variant),
                "ladder": {str(int(s)): a_table(buckets, dates, kept, rates, variant, stake=s) for s in STAKES},
                "expected_loss_25": a_table(buckets, dates, kept, rates, variant, expected_loss=True),
                "primary5_25": a_table(buckets, dates, [m for m in PRIMARY5 if m in kept], rates, variant),
                "per_hour_25": {str(h): a_table(buckets, dates, kept, rates, variant, hour=h) for h in hours},
                "per_market_25": {mk: dict(a_table(buckets, dates, [mk], rates, variant), excluded=mk not in kept)
                                  for mk in MARKETS}}

    res = {"A_08-10..09-29": block(win_a, A_PRIMARY_VARIANT),
           "sensitivity_depth5_08-10..09-29": block(win_a, "print_d5"),
           "sensitivity_book_only_08-10..09-29": block(win_a, "book_d1"),
           "book_only_08-01..08-09_separate": block(win_b, "book_d1")}
    res["A_08-10..09-29"]["reading"] = reading_a(res["A_08-10..09-29"]["primary_25"])
    kb = [b for b in buckets if b["market"] in kept]
    traded = [b for b in kb if b["status"] == "traded"]
    in_a = [b for b in traded if b["date"] >= A_WINDOW_FIRST]
    status = {}
    for b in kb:
        status[b["status"]] = status.get(b["status"], 0) + 1
    dur = np.array([b["duration_min"] for b in traded], float)
    summ = {"status": status, "traded_08_10_on": len(in_a),
            "traded_with_prints_08_10_on": int(sum(b["printed_shares"] > 0 for b in in_a)),
            "traded_on_days_without_trade_parts_08_10_on": int(sum(b["trade_parts"] == 0 for b in in_a)),
            "filled_shares_print_d1_25": float(sum(b["filled_print_d1_25"] for b in in_a)),
            "wanted_shares_25": float(sum(25.0 / b["q"] for b in in_a)),
            "traded_settled_yes": int(sum(b["settled_yes"] for b in traded)),
            "quote_source": {s: int(sum(b["quote_source"] == s for b in traded))
                             for s in ("no_ask", "one_minus_yes_bid")},
            "duration_min": ({"n": int(len(dur)), "median": float(np.median(dur)),
                              "p90": float(np.quantile(dur, .9))} if len(dur) else {"n": 0}),
            "market_days": {s: int(sum(x["status"] == s for x in days))
                            for s in ("scanned", "no_dead", "no_tape_folder")},
            "scanned_days_without_trade_parts_08_10_on": int(sum(
                x["status"] == "scanned" and x["date"] >= A_WINDOW_FIRST and x["trade_parts"] == 0 for x in days))}
    return res, summ


def _history(args):
    W = WINDOWS[args.window]
    actual = sha256_file(args.history)
    if actual != args.history_sha256:
        raise data.Refused(f"refused: history sha256 {actual} != {args.history_sha256}")
    hist = json.loads(Path(args.history).read_text(encoding="utf-8"))
    if hist.get("schema") != SCHEMA_HISTORY or hist.get("rule_sha256") != W["rule"]:
        raise data.Refused(f"refused: history file is not window {args.window}'s rule history phase")
    kept = hist["kept_markets"] if args.window == "13-16" else hist["windows"][args.window]["kept_markets"]
    rates = {mk: v["rates"][W["decisive"]] for mk, v in hist["per_market"].items()}
    return hist, kept, rates, actual


def _excluded(hist, window):
    return hist["excluded"] if window == "13-16" else hist["windows"][window]["excluded"]


def run_stage_a_scan(args):
    hist, kept, rates, actual = _history(args)
    la.screen_input_path(args.layout, "layout")
    markets = [m.strip() for m in args.markets.split(",")] if args.markets else list(MARKETS)
    unknown = [m for m in markets if m not in MARKETS]
    if unknown:
        raise data.Refused(f"refused: unknown markets {unknown}")
    sums = sha256_file(Path(args.tapes) / "SHA256SUMS")
    if sums != args.tapes_sha256sums:
        raise data.Refused(f"refused: SHA256SUMS sha256 {sums} != {args.tapes_sha256sums}")
    layout = data.load_layout(args.layout, data.DEV_FIRST, data.check_range(*DEV_RANGE)[1])
    obs = load_obs(args.obs, check_sha=not args.no_obs_sha)
    buckets, days = stage_a_scan(layout, obs, args.tapes, markets, kept, args.window)
    return dict({"schema": SCHEMA_A_SCAN, "rule_sha256": WINDOWS[args.window]["rule"], "history_sha256": actual,
                 "window": args.window,
                 "tapes_sha256sums_sha256": sums, "layout_manifest_sha256": layout.manifest_sha256,
                 "markets": markets, "buckets": buckets, "days": days,
                 "dates_all": sorted({str(d) for d in layout.snaps.date.astype(str)})}, **_code())


def run_stage_a_report(args):
    hist, kept, rates, actual = _history(args)
    buckets, days, markets, meta = [], [], [], {}
    for path in args.scans:
        p = json.loads(Path(path).read_text(encoding="utf-8"))
        if (p.get("schema") != SCHEMA_A_SCAN or p.get("rule_sha256") != WINDOWS[args.window]["rule"]
                or p.get("history_sha256") != actual or p.get("window", "13-16") != args.window):
            raise data.Refused(f"refused: {path} is not a stage-A scan of this rule and history")
        for k in ("tapes_sha256sums_sha256", "layout_manifest_sha256", "code_sha256", "dates_all"):
            if meta.setdefault(k, p[k]) != p[k]:
                raise data.Refused(f"refused: scans disagree on {k}")
        if set(markets) & set(p["markets"]):
            raise data.Refused("refused: a market appears in two scans")
        markets += p["markets"]
        buckets += p["buckets"]
        days += p["days"]
        meta.setdefault("scan_sha256", {})[str(path)] = sha256_file(path)
    if sorted(markets) != sorted(MARKETS):
        raise data.Refused(f"refused: scans cover {sorted(markets)}, not the 11 markets")
    res, summ = stage_a_report(buckets, days, meta["dates_all"], kept, rates, args.window)
    W = WINDOWS[args.window]
    return dict({"schema": SCHEMA_A, "rule_sha256": W["rule"], "history_sha256": actual,
                 "window": args.window, "entry_window_local": "%02d:%02d-%02d:%02d" % (*W["start"], *W["end"]),
                 "evidence_class": "development (dev window); stage A = book + trade-print fills (clarification 1)",
                 "excluded": _excluded(hist, args.window), "kept_markets": kept, "results": res, "summary": summ,
                 "constants": {"fee_rate": FEE_RATE, "min_value": MIN_VALUE, "stakes": STAKES,
                               "latency_s": LATENCY.total_seconds(), "print_window_min": 5,
                               "draws": sc.DRAWS, "seed": sc.SEED}}, **meta)


def render_a(p):
    L = [f"# Dead-bucket stage A, window {p.get('window', '13-16')} "
         f"({p.get('entry_window_local', '13:00-16:59')} local): book + trade-print fills (development evidence)", "",
         f"Rule `{p['rule_sha256']}`; history `{p['history_sha256']}`; tapes SHA256SUMS "
         f"`{p['tapes_sha256sums_sha256']}`; excluded {', '.join(p['excluded']) or 'none'}.", ""]
    for w, res in p["results"].items():
        head = f"## {w} (variant {res['variant']})" + (f": {res['reading']}" if "reading" in res else "")
        L += [head, "", "| row | $/day | 95% CI (date) | MDE80 | dates nonzero |", "| --- | --- | --- | --- | --- |"]
        rows = [("$25 primary (kept markets)", res["primary_25"])]
        rows += [(f"${k}", v) for k, v in res["ladder"].items()]
        rows += [("$25 expected-loss", res["expected_loss_25"]), ("$25 PRIMARY5", res["primary5_25"])]
        rows += [(f"$25 entry hour {h}", v) for h, v in res["per_hour_25"].items()]
        rows += [(f"$25 {mk}{' (excluded)' if v['excluded'] else ''}", v) for mk, v in res["per_market_25"].items()]
        for name, v in rows:
            L.append(f"| {name} | {_f(v['estimate'])} | {_ci(v['ci95'])} | {_f(v.get('mde80'))} | "
                     f"{v.get('n_dates_nonzero', 0)}/{v['n_dates']} |")
        L.append("")
    L += [f"Summary: `{json.dumps(sc._clean(p['summary']))}`", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.dead_bucket")
    ap.add_argument("phase", choices=("history", "stage-c", "stage-a-scan", "stage-a-report"))
    ap.add_argument("--tapes")
    ap.add_argument("--tapes-sha256sums")
    ap.add_argument("--markets")
    ap.add_argument("--scans", nargs="*")
    ap.add_argument("--tag", default="all")
    ap.add_argument("--window", choices=tuple(WINDOWS), default="13-16")
    ap.add_argument("--window-rule", choices=("r2", "r3"), default="r2")
    ap.add_argument("--control-history")
    ap.add_argument("--control-history-sha256")
    ap.add_argument("--obs")
    ap.add_argument("--wu-root")
    ap.add_argument("--layout")
    ap.add_argument("--history")
    ap.add_argument("--history-sha256")
    ap.add_argument("--no-obs-sha", action="store_true", help=argparse.SUPPRESS)  # tests only
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    try:
        if args.phase == "history":
            payload, render = run_history(args), render_history
            name = "dead_bucket_history" + ("_r3" if args.window_rule == "r3" else "")
        elif args.phase == "stage-a-scan":
            if not (args.layout and args.history and args.history_sha256 and args.tapes and args.tapes_sha256sums):
                raise data.Refused("refused: stage-a-scan needs --layout, --history(-sha256), --tapes(-sha256sums)")
            sfx = "" if args.window == "13-16" else f"_{args.window}"
            payload, name = run_stage_a_scan(args), f"dead_bucket_stage_a{sfx}_scan_{args.tag}"
            render = lambda p: f"stage-A scan {p['markets']}: {len(p['buckets'])} buckets\n"  # noqa: E731
        elif args.phase == "stage-a-report":
            if not (args.history and args.history_sha256 and args.scans):
                raise data.Refused("refused: stage-a-report needs --history(-sha256) and --scans")
            sfx = "" if args.window == "13-16" else f"_{args.window}"
            payload, name, render = run_stage_a_report(args), f"dead_bucket_stage_a{sfx}", render_a
        else:
            if not (args.layout and args.history and args.history_sha256):
                raise data.Refused("refused: stage-c needs --layout, --history and --history-sha256")
            payload, name, render = run_stage_c(args), "dead_bucket_stage_c", render_c
    except (data.Refused, data.LayoutError, data.LeakageError) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1, default=str).encode("utf-8")
    path = out / f"{name}.json"
    path.write_bytes(blob)
    (out / f"{name}.md").write_text(render(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"json": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                      "excluded": payload.get("excluded")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
