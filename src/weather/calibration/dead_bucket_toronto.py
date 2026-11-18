r"""Dead-bucket check for Toronto (lane L11, rule r2-toronto): r2 in native whole degrees Celsius. Research only.

Pre-registered in ``C:\t\l11\deadbucket_rule_r2_toronto.md`` (sha256 ``RULE_SHA256``; copy in
``docs/research/market-blend-l11-2026-10-25/``). Everything is native Celsius: the METAR-only running max R(t)
(IEM CYYZ ``tmpc``, or the T-group tenths when a report carries one), H = floor(R + 0.5), bucket edges parsed
from the tape's ``range_label`` with ``weather.units.parse_temperature_band(expected_unit="C")`` and cross-checked
against ``bin_kind`` / ``bin_value`` / ``bin_value_hi`` / ``unit``; WU ``max_temp_native`` (whole C) is the
settlement proxy. No Fahrenheit value is formed anywhere.

Phases::

    fetch    IEM CYYZ (tmpc + raw METAR) -> <out>/toronto_obs.parquet (history windows; --dev adds the dev window)
    history  Aug-Sep 2021-2025 violation rates (X = 2.0% at 16:59), before any dev row
    stage-a-scan / stage-a-report   r2 clarification 1 fills on the Toronto tapes (sha-pinned SHA256SUMS)

The fill, fee, value, latency, print-window, duration, ladder and report logic are r2's, imported from
``weather.calibration.dead_bucket``.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.reporting.scorecards import loss_atlas as la  # refuses import on the capture host

la.refuse_production_import()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from weather.calibration import dead_bucket as db  # noqa: E402
from weather.model.observed_running_max import (  # noqa: E402
    observed_target_date_rows,
    running_max_since_midnight,
)
from weather.reporting.scorecards import dev_scorecard as sc  # noqa: E402
from weather.reporting.scorecards import dev_scorecard_data as data  # noqa: E402
from weather.units import parse_temperature_band  # noqa: E402

RULE_SHA256 = "c754ddab8ed3634c0854444dded9d4831bf4ff955b5efd944fc54f582246ef3d"  # r2-toronto
MARKET = "toronto"
STATION = "CYYZ"
TZ_NAME = "America/Toronto"
UNIT = "C"
SCHEMA_OBS = "dead_bucket_toronto_obs/1"
SCHEMA_HISTORY = "dead_bucket_toronto_history/1"
SCHEMA_A_SCAN = "dead_bucket_toronto_stage_a_scan/1"
SCHEMA_A = "dead_bucket_toronto_stage_a/1"
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
HIST_WINDOWS = tuple((datetime(y, 8, 1, tzinfo=timezone.utc), datetime(y, 10, 1, 12, tzinfo=timezone.utc))
                     for y in db.HIST_YEARS)
DEV_WINDOW = (datetime(2026, 7, 30, tzinfo=timezone.utc), datetime(2026, 9, 30, 4, tzinfo=timezone.utc))
_TGROUP = r" T([01])(\d{3})([01])(\d{3})"


def tz():
    return ZoneInfo(TZ_NAME)


# ----------------------------------------------------------------------------- buckets (native C)

def bucket_from_label(label, kind=None, value=None, value_hi=None, unit=None):
    """(key, high) of a Celsius bucket from its ``range_label``, cross-checked with the bin fields.

    key: ("lte", X) | ("eq", lo, hi) | ("gte", X); high: the upper edge (None for gte). Returns None when the
    label does not parse as Celsius or disagrees with any bin field given.
    """
    band = parse_temperature_band(label, expected_unit=UNIT)
    if band is None:
        return None
    if unit is not None and str(unit).strip() and str(unit).strip().upper().lstrip("\u00b0") != UNIT:
        return None
    if kind is not None and str(kind).strip() and str(kind).strip().lower() != band.kind:
        return None
    v, vh = db._num(value), db._num(value_hi)
    lo, hi = int(band.value), int(band.value_hi)
    if band.kind == "eq":
        if (v is not None and v != lo) or (vh is not None and vh != hi):
            return None
        return ("eq", lo, hi), hi
    if v is not None and v != lo:
        return None
    if band.kind == "lte":
        return ("lte", lo), lo
    return ("gte", lo), None


def settled_yes(key, wu_max):
    """Whole-degree WU max inside the bucket (native C)."""
    if key[0] == "lte":
        return wu_max <= key[1]
    if key[0] == "gte":
        return wu_max >= key[1]
    return key[1] <= wu_max <= key[2]


# ----------------------------------------------------------------------------- observations (native C)

def tgroup_c(metar):
    """T-group tenths of a degree C from a raw METAR, else None."""
    import re

    m = re.search(_TGROUP, f" {metar} ") if isinstance(metar, str) else None
    if not m:
        return None
    return (-1.0 if m.group(1) == "1" else 1.0) * int(m.group(2)) / 10.0


def fetch(out_dir, dev=False, session=None, log=print):
    """IEM CYYZ tmpc + raw METAR for the history windows (and the dev window with ``dev``) -> obs parquet."""
    import requests
    from urllib.parse import urlencode

    from weather.sources.free_screens import common

    session = session or requests.Session()
    out = Path(out_dir)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    receipts = []
    for a, b in HIST_WINDOWS + ((DEV_WINDOW,) if dev else ()):
        params = [("station", STATION), ("data", "tmpc"), ("data", "metar"), ("tz", "Etc/UTC"),
                  ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"),
                  ("report_type", "3"), ("report_type", "4"),
                  ("sts", a.strftime("%Y-%m-%dT%H:%MZ")), ("ets", b.strftime("%Y-%m-%dT%H:%MZ"))]
        url = f"{IEM_URL}?{urlencode(params)}"
        name = raw / f"{STATION}_{a:%Y%m%d%H}_{b:%Y%m%d%H}.csv.gz"
        if not name.is_file():
            resp = common.polite_get(session, url)
            if resp.status_code != 200:
                raise data.Refused(f"refused: IEM status {resp.status_code} for {url}")
            name.write_bytes(gzip.compress(resp.content))
        body = gzip.decompress(name.read_bytes())
        receipts.append({"file": name.name, "sha256": hashlib.sha256(name.read_bytes()).hexdigest(), "url": url,
                         "rows": max(0, body.count(b"\n") - 1)})
        log(f"{name.name} rows={receipts[-1]['rows']}")
    frames = []
    for r in receipts:
        frames.append(pd.read_csv(io.BytesIO(gzip.decompress((raw / r["file"]).read_bytes())), dtype=str))
    t = pd.concat(frames, ignore_index=True)
    obs = pd.DataFrame({"station": t.station, "valid_utc": pd.to_datetime(t.valid, utc=True),
                        "tmpc": pd.to_numeric(t.tmpc, errors="coerce"),
                        "tgroup_c": [tgroup_c(m) for m in t.metar.fillna("")],
                        "is_cor": t.metar.fillna("").str.contains(" COR ", regex=False)})
    obs = obs.dropna(subset=["valid_utc"]).drop_duplicates(["station", "valid_utc"]).sort_values("valid_utc")
    if (obs.valid_utc >= DEV_WINDOW[1]).any():
        raise AssertionError("rows at or after local midnight ending 2026-09-29")
    path = out / "toronto_obs.parquet"
    obs.reset_index(drop=True).to_parquet(path, index=False)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"schema": SCHEMA_OBS, "file": path.name, "sha256": sha, "rows": int(len(obs)), "receipts": receipts,
                "dev_window": bool(dev), "tgroup_share": float(obs.tgroup_c.notna().mean()) if len(obs) else None}
    (out / "toronto_obs_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def load_obs(path, sha):
    actual = db.sha256_file(path)
    if actual != sha:
        raise data.Refused(f"refused: {path} sha256 {actual} != {sha}")
    t = pd.read_parquet(path)
    t = t[~t.is_cor.fillna(False).astype(bool) & (t.valid_utc < pd.Timestamp(DEV_WINDOW[1]))].copy()
    local = t.valid_utc.dt.tz_convert(tz())
    t["local_date"] = local.dt.date
    t = t[t.local_date <= db.DEV_LAST]
    t["year"] = t.valid_utc.dt.year
    t["minute"] = t.valid_utc.dt.minute
    modal = t.groupby("year").minute.agg(lambda s: int(s.value_counts().sort_index().idxmax()))
    t["routine"] = t.minute.to_numpy() == t.year.map(modal).to_numpy()
    return {"tz": tz(), "station": STATION, "modal_minute_by_year": {int(k): int(v) for k, v in modal.items()},
            "days": {d: x for d, x in t.groupby("local_date")}, "sha256": actual}


def rows_c(day, variant="base"):
    """L8 row dicts in native C: temp_native = T-group tenths else tmpc (base/routine), tmpc (tmpf/both)."""
    if day is None or not len(day):
        return []
    if variant in ("routine", "both"):
        day = day[day.routine]
    use_tgroup = variant in ("base", "routine")
    out = []
    for ts, tg, tc in zip(day.valid_utc, day.tgroup_c, day.tmpc):
        v = tg if use_tgroup and tg is not None and not pd.isna(tg) else tc
        if v is None or pd.isna(v):
            continue
        out.append({"obs_time": ts.isoformat(), "temp_native": float(v)})
    return out


def running_c(rows, d, zone, now):
    return running_max_since_midnight(None, {"rows": rows}, target_date=d, tz=zone, unit=UNIT,
                                      cutoff_hour=db.RUNNING_MAX_CUTOFF_HOUR, now=now)


def steps_c(day, d, zone):
    rows = rows_c(day)
    end = db.local_instant(d, 16, 59, zone)
    steps = []
    for r in rows:
        t = datetime.fromisoformat(r["obs_time"]).astimezone(zone)
        if t.date() != d or t > end:
            continue
        h = db.H(running_c(rows, d, zone, t)[0])
        if h is not None:
            steps.append((t, h))
    steps.sort(key=lambda s: s[0])
    return steps


# ----------------------------------------------------------------------------- WU (native C)

def load_wu(wu_root):
    path = Path(wu_root) / "cyyz" / "daily" / "daily_summary.csv"
    w = pd.read_csv(path, usecols=["local_date", "temperature_unit", "row_count", "last_time", "max_temp_native"])
    if set(w.temperature_unit.dropna().unique()) - {UNIT}:
        raise data.Refused(f"refused: {path} is not native Celsius")
    w["local_date"] = pd.to_datetime(w.local_date).dt.date
    w = w[w.local_date <= db.DEV_LAST]
    return w.drop_duplicates("local_date", keep="last").set_index("local_date"), path


def history(obs, wu_root):
    zone = obs["tz"]
    wu, wu_path = load_wu(wu_root)
    wu = wu[[d.year in db.HIST_YEARS and d.month in db.HIST_MONTHS for d in wu.index]]
    counts = {"wu_days": int(len(wu)), "kept": 0, "drop_wu_rows": 0, "drop_metar_rows": 0}
    viol = {c: 0 for c, _, _ in db.CUTOFFS}
    violations = []
    for d, w in wu.iterrows():
        if pd.isna(w.row_count) or int(w.row_count) < db.WU_MIN_ROWS or pd.isna(w.max_temp_native):
            counts["drop_wu_rows"] += 1
            continue
        day = obs["days"].get(d)
        rows = rows_c(day)
        end = db.local_instant(d, 16, 59, zone)
        if len(observed_target_date_rows(None, {"rows": rows}, target_date=d, tz=zone, unit=UNIT,
                                         now=end)) < db.METAR_MIN_ROWS:
            counts["drop_metar_rows"] += 1
            continue
        counts["kept"] += 1
        wu_max = float(w.max_temp_native)
        for c, hh, mm in db.CUTOFFS:
            h = db.H(running_c(rows, d, zone, db.local_instant(d, hh, mm, zone))[0])
            if h is not None and wu_max < h:
                viol[c] += 1
        r, first_minute = running_c(rows, d, zone, end)
        h = db.H(r)
        if h is not None and wu_max < h:
            gone = {}
            for v in ("tmpf", "routine", "both"):  # "tmpf" = whole-degree reported tmpc (no T-group)
                hv = db.H(running_c(rows_c(day, v), d, zone, end)[0])
                gone[v] = hv is None or wu_max >= hv
            violations.append({"date": str(d), "wu_max_c": wu_max, "H_1659_c": h, "R_1659_c": r,
                               "shortfall_c": h - wu_max, "max_minute": first_minute,
                               "wu_last_time": str(w.last_time), "gone": gone,
                               "cause": db.classify(gone, first_minute, w.last_time)})
    rates = {c: (viol[c] / counts["kept"] if counts["kept"] else None) for c in viol}
    causes = {k: sum(v["cause"] == k for v in violations) for k in db.CAUSES}
    excluded = rates[db.DECISIVE] is None or rates[db.DECISIVE] > db.X_EXCLUDE
    return {"station": STATION, "wu_path": str(wu_path), "wu_sha256": db.sha256_file(wu_path), "counts": counts,
            "violations_by_cutoff": viol, "rates": rates, "causes": causes, "violations": violations,
            "excluded": bool(excluded), "modal_minute_by_year": obs["modal_minute_by_year"]}


# ----------------------------------------------------------------------------- stage A

def stream_summary_c(path, t_first, t_last):
    """One pass: every Celsius lte/eq bucket's rows in [t_first, t_last], its tokens and the row counters."""
    csv.field_size_limit(2**31 - 1)
    rows, tokens, highs = {}, {}, {}
    n = {"rows": 0, "bad": 0, "label_mismatch": 0, "gte": 0}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        need = db._SUMMARY_FIELDS + ("range_label", "unit")
        missing = [f for f in need if f not in header]
        if missing:
            raise data.LayoutError(f"{path}: summary columns missing {missing}")
        idx = {name: header.index(name) for name in need}
        for rec in reader:
            n["rows"] += 1
            if len(rec) != len(header) or max(map(len, rec), default=0) > 4096:
                n["bad"] += 1  # torn, merged or oversized row: never used (declared in the rule)
                continue
            parsed = bucket_from_label(rec[idx["range_label"]], rec[idx["bin_kind"]], rec[idx["bin_value"]],
                                       rec[idx["bin_value_hi"]], rec[idx["unit"]])
            if parsed is None:
                n["label_mismatch"] += 1
                continue
            key, high = parsed
            if key[0] == "gte":
                n["gte"] += 1
                continue
            side = rec[idx["outcome"]].strip().lower()
            if side not in ("yes", "no"):
                continue
            highs[key] = high
            tokens[rec[idx["clob_token_id"]].strip()] = (key, side)
            t = db._utc(rec[idx["captured_at_utc"]])
            if t is None or t < t_first or t > t_last:
                continue
            rows.setdefault((key, side), []).append((t, *(db._num(rec[idx[f]]) for f in (
                "best_bid", "best_ask", "bid_depth_1pct", "ask_depth_1pct", "bid_depth_5pct", "ask_depth_5pct"))))
    for v in rows.values():
        v.sort(key=lambda r: r[0])
    return rows, tokens, highs, n


def stage_a_scan(obs, wu, tapes_root, kept):
    zone = obs["tz"]
    events = {d: f for (mk, d), f in db.discover_tape_events(tapes_root).items() if mk == MARKET}
    buckets, days = [], []
    for d_iso, folder in sorted(events.items()):
        dd = date.fromisoformat(d_iso)
        w = wu.loc[dd] if dd in wu.index else None
        info = {"market": MARKET, "date": d_iso, "folder": folder.name}
        if w is None or pd.isna(w.max_temp_native):
            days.append(dict(info, status="no_wu_label"))
            continue
        wu_max = float(w.max_temp_native)
        day = obs["days"].get(dd)
        steps = steps_c(day, dd, zone)
        start, end = db.local_instant(dd, 13, 0, zone), db.local_instant(dd, 16, 59, zone)
        h_end = db.H(running_c(rows_c(day), dd, zone, end)[0])
        rows, tokens, highs, n = stream_summary_c(folder / "order_books_summary.csv", start, end)
        dead = []
        for key, high in sorted(highs.items()):
            if h_end is None or not high < h_end:
                continue
            fd = db.first_dead(steps, float(high))
            dead.append((key, high, fd, max(fd + db.LATENCY, start)))
        if not dead:
            days.append(dict(info, status="no_dead", H_1659_c=h_end, summary=n))
            continue
        t_first = min(en for *_, en in dead)
        prints, n_parts = db.stream_prints(folder, tokens, t_first, end + db.PRINT_WINDOW)
        days.append(dict(info, status="scanned", H_1659_c=h_end, wu_max_c=wu_max, n_dead=len(dead), summary=n,
                         trade_parts=n_parts, prints_kept=len(prints), tokens_matched=len(tokens)))
        for key, high, fd, entry in dead:
            yes = settled_yes(key, wu_max)
            rec = {"market": MARKET, "date": d_iso, "bucket": list(key), "high_c": high,
                   "first_dead": fd.isoformat(), "entry_instant": entry.isoformat(), "settled_yes": bool(yes),
                   "excluded_market": MARKET not in kept, "trade_parts": n_parts}
            qt = db.no_quote(rows, key, entry)
            if qt is None or qt[0] > end:
                buckets.append(dict(rec, status="no_capture"))
                continue
            t_q, q, d1, d5, source = qt
            rec.update(capture_utc=t_q.isoformat(), entry_hour=int(t_q.astimezone(zone).hour), q=q,
                       quote_source=source, depth1=d1, depth5=d5, value=db.value(q))
            if db.value(q) < db.MIN_VALUE:
                buckets.append(dict(rec, status="no_value"))
                continue
            w_end = entry + db.PRINT_WINDOW
            printed = sum(sz for t, k, side, p, sz in prints if k == key and entry <= t <= w_end
                          and ((side == "no" and p <= q + 1e-12) or (side == "yes" and p >= 1.0 - q - 1e-12)))
            stop, t_cur = end, t_q
            while True:
                nxt = db.no_quote(rows, key, t_cur, strict_after=True)
                if nxt is None or nxt[0] > end:
                    break
                if db.value(nxt[1]) < db.MIN_VALUE:
                    stop = nxt[0]
                    break
                t_cur = nxt[0]
            rec.update(printed_shares=printed, duration_min=max(0.0, (stop - entry).total_seconds() / 60.0))
            for stake in db.STAKES:
                for var, filled in db.a_fills(stake, q, d1, d5, printed).items():
                    rec[f"filled_{var}_{int(stake)}"] = filled
                    rec[f"pnl_{var}_{int(stake)}"] = db.a_pnl(filled, q, yes)
            buckets.append(dict(rec, status="traded"))
    return buckets, days


def stage_a_report(buckets, days, dates_all, kept, rate):
    win_a = [d for d in dates_all if d >= db.A_WINDOW_FIRST]
    win_b = [d for d in dates_all if d <= db.BOOK_ONLY_LAST]
    rates = {MARKET: rate}
    members = [MARKET] if MARKET in kept else []

    def block(dates, variant):
        return {"variant": variant,
                "primary_25": db.a_table(buckets, dates, members, rates, variant),
                "ladder": {str(int(s)): db.a_table(buckets, dates, members, rates, variant, stake=s)
                           for s in db.STAKES},
                "expected_loss_25": db.a_table(buckets, dates, members, rates, variant, expected_loss=True),
                "per_hour_25": {str(h): db.a_table(buckets, dates, members, rates, variant, hour=h)
                                for h in (13, 14, 15, 16)}}

    res = {"A_08-10..09-29": block(win_a, db.A_PRIMARY_VARIANT),
           "sensitivity_depth5_08-10..09-29": block(win_a, "print_d5"),
           "sensitivity_book_only_08-10..09-29": block(win_a, "book_d1"),
           "book_only_08-01..08-09_separate": block(win_b, "book_d1")}
    res["A_08-10..09-29"]["reading"] = db.reading_a(res["A_08-10..09-29"]["primary_25"])
    traded = [b for b in buckets if b["status"] == "traded"]
    status = {}
    for b in buckets:
        status[b["status"]] = status.get(b["status"], 0) + 1
    dur = np.array([b["duration_min"] for b in traded], float)
    in_a = [b for b in traded if b["date"] >= db.A_WINDOW_FIRST]
    summ = {"status": status, "traded_08_10_on": len(in_a),
            "traded_with_prints_08_10_on": int(sum(b["printed_shares"] > 0 for b in in_a)),
            "filled_shares_print_d1_25": float(sum(b["filled_print_d1_25"] for b in in_a)),
            "wanted_shares_25": float(sum(25.0 / b["q"] for b in in_a)),
            "traded_settled_yes": int(sum(b["settled_yes"] for b in traded)),
            "duration_min": ({"n": int(len(dur)), "median": float(np.median(dur)),
                              "p90": float(np.quantile(dur, .9))} if len(dur) else {"n": 0}),
            "market_days": {s: int(sum(x["status"] == s for x in days))
                            for s in ("scanned", "no_dead", "no_wu_label")},
            "summary_rows": {k: int(sum(x.get("summary", {}).get(k, 0) for x in days))
                             for k in ("rows", "bad", "label_mismatch", "gte")}}
    return res, summ


# ----------------------------------------------------------------------------- CLI

def _rule():
    if not RULE_SHA256:
        raise data.Refused("refused: the r2-toronto rule sha256 is not recorded in the code yet")
    return RULE_SHA256


def _code():
    return {"code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "dead_bucket_code_sha256": hashlib.sha256(Path(db.__file__).read_bytes()).hexdigest()}


def _history(args):
    actual = db.sha256_file(args.history)
    if actual != args.history_sha256:
        raise data.Refused(f"refused: history sha256 {actual} != {args.history_sha256}")
    hist = json.loads(Path(args.history).read_text(encoding="utf-8"))
    if hist.get("schema") != SCHEMA_HISTORY or hist.get("rule_sha256") != _rule():
        raise data.Refused("refused: history file is not r2-toronto's history phase")
    kept = [] if hist["excluded"] else [MARKET]
    return hist, kept, hist["rates"][db.DECISIVE], actual


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.dead_bucket_toronto")
    ap.add_argument("phase", choices=("fetch", "history", "stage-a-scan", "stage-a-report"))
    ap.add_argument("--dev", action="store_true", help="fetch: also the dev window 2026-07-30..09-29")
    ap.add_argument("--obs")
    ap.add_argument("--obs-sha256")
    ap.add_argument("--wu-root")
    ap.add_argument("--history")
    ap.add_argument("--history-sha256")
    ap.add_argument("--tapes")
    ap.add_argument("--tapes-sha256sums")
    ap.add_argument("--scan")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == "fetch":
            print(json.dumps(fetch(out, dev=args.dev)))
            return 0
        if args.phase == "history":
            obs = load_obs(args.obs, args.obs_sha256)
            payload = dict({"schema": SCHEMA_HISTORY, "rule_sha256": _rule(), "obs_sha256": obs["sha256"],
                            "unit": UNIT, "constants": {"X": db.X_EXCLUDE, "years": db.HIST_YEARS,
                                                        "months": db.HIST_MONTHS, "decisive": db.DECISIVE}},
                           **_code(), **history(obs, args.wu_root))
            name = "toronto_history"
        elif args.phase == "stage-a-scan":
            hist, kept, rate, hsha = _history(args)
            sums = db.sha256_file(Path(args.tapes) / "SHA256SUMS")
            if sums != args.tapes_sha256sums:
                raise data.Refused(f"refused: SHA256SUMS sha256 {sums} != {args.tapes_sha256sums}")
            obs = load_obs(args.obs, args.obs_sha256)
            wu, _ = load_wu(args.wu_root)
            buckets, days = stage_a_scan(obs, wu, args.tapes, kept)
            payload = dict({"schema": SCHEMA_A_SCAN, "rule_sha256": _rule(), "history_sha256": hsha,
                            "obs_sha256": obs["sha256"], "tapes_sha256sums_sha256": sums, "buckets": buckets,
                            "days": days, "dates_all": sorted(x["date"] for x in days)}, **_code())
            name = "toronto_stage_a_scan"
        else:
            hist, kept, rate, hsha = _history(args)
            scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
            if scan.get("schema") != SCHEMA_A_SCAN or scan.get("history_sha256") != hsha:
                raise data.Refused("refused: not an r2-toronto stage-A scan of this history")
            res, summ = stage_a_report(scan["buckets"], scan["days"], scan["dates_all"], kept, rate)
            payload = dict({"schema": SCHEMA_A, "rule_sha256": _rule(), "history_sha256": hsha,
                            "scan_sha256": db.sha256_file(args.scan), "excluded": not kept,
                            "evidence_class": "development (dev window); Toronto stage A (r2-toronto)",
                            "results": res, "summary": summ}, **_code())
            name = "toronto_stage_a"
    except (data.Refused, data.LayoutError) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1, default=str).encode("utf-8")
    (out / f"{name}.json").write_bytes(blob)
    print(json.dumps({"json": str(out / f"{name}.json"), "sha256": hashlib.sha256(blob).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
