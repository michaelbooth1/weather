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
# r4-toronto (C:/t/l11/deadbucket_rule_r4_toronto.md): r4 capture-time dating in native C, parse check.
RULE_R4_SHA256 = "12902246a5358df5a2926314465e61dd4d1afaeedd408b994706e5b773c9f061"
TAPES_SUMS_SHA256 = "a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0"
CELSIUS_SANITY_MIN = 0.95
# Clarification 1 (2026-10-25): rule doc sha after the dated clarification; primary unchanged.
RULE_R4_C1_DOC_SHA256 = "46c48626a1204e274e0fb9fa6951b71b587e39310a0f37e41b2d50172c0738bd"
WU_EXTRA_SHA256 = "c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a"
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

def load_wu(wu_root, extra=None, extra_sha256=None):
    """Pinned CYYZ daily summary (rows after 09-29 dropped unparsed), then an optional appended input.

    The appended input (clarification 1) fails closed: sha, header, any date after 09-29, any duplicate
    local_date within it or against the pinned rows, and any non-C unit refuse the run.
    """
    path = Path(wu_root) / "cyyz" / "daily" / "daily_summary.csv"
    cols = ["local_date", "temperature_unit", "row_count", "last_time", "max_temp_native"]
    kept = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        for rec in reader:
            try:
                if date.fromisoformat(str(rec["local_date"])[:10]) > db.DEV_LAST:
                    continue  # rows after 2026-09-29 are never parsed
            except ValueError:
                continue
            kept.append({c: rec.get(c) for c in cols})
    if extra is not None:
        got = db.sha256_file(extra)
        if got != extra_sha256 or got != WU_EXTRA_SHA256:
            raise data.Refused(f"refused: appended WU input sha256 {got} != {WU_EXTRA_SHA256}")
        seen = {str(r["local_date"])[:10] for r in kept}
        with open(extra, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != header:
                raise data.Refused("refused: appended WU input header differs from the pinned file")
            for rec in reader:
                d_ = str(rec["local_date"])[:10]
                try:
                    dd_ = date.fromisoformat(d_)
                except ValueError:
                    raise data.Refused(f"refused: appended WU input has an unparseable local_date {d_!r}")
                if dd_ > db.DEV_LAST:
                    raise data.Refused(f"refused: appended WU input has a row dated {d_} after {db.DEV_LAST}")
                if d_ in seen:
                    raise data.Refused(f"refused: duplicate local_date {d_} across the WU inputs")
                if rec.get("temperature_unit") != UNIT:
                    raise data.Refused(f"refused: appended WU row {d_} is not native Celsius")
                seen.add(d_)
                kept.append({c: rec.get(c) for c in cols})
    w = pd.DataFrame(kept, columns=cols)
    w["row_count"] = pd.to_numeric(w.row_count, errors="coerce")
    w["max_temp_native"] = pd.to_numeric(w.max_temp_native, errors="coerce")
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
    failed, parsed_labels = {}, {}
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
                n["label_mismatch"] += 1  # never coerced: listed in the scan output
                tup = tuple(rec[idx[f]] for f in ("range_label", "bin_kind", "bin_value", "bin_value_hi", "unit"))
                failed[tup] = failed.get(tup, 0) + 1
                continue
            key, high = parsed
            parsed_labels[rec[idx["range_label"]]] = list(key)
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
    n["failed_labels"] = [{"label": k[0], "bin_kind": k[1], "bin_value": k[2], "bin_value_hi": k[3], "unit": k[4],
                           "rows": c} for k, c in sorted(failed.items())]
    n["parsed_labels"] = parsed_labels
    return rows, tokens, highs, n


def label_free_no_ask(rows, key, entry, end, zone):
    """Clarification 1: NO-side asks (own ask only) from entry to 16:59 with value >= the rule minimum."""
    hits = [r for r in rows.get((key, "no"), []) if entry <= r[0] <= end and r[2] is not None
            and db.value(r[2]) >= db.MIN_VALUE]
    if not hits:
        return {"qualifying_snapshots": 0}
    f = hits[0]
    return {"qualifying_snapshots": len(hits), "first_utc": f[0].isoformat(),
            "first_hour": int(f[0].astimezone(zone).hour), "first_ask": f[2], "first_ask_depth_1pct": f[4] or 0.0,
            "first_ask_depth_5pct": f[6] or 0.0, "max_ask_depth_1pct": max(r[4] or 0.0 for r in hits),
            "min_ask": min(r[2] for r in hits)}


def label_free_summary(buckets, days):
    recs = [b["label_free"] for b in buckets if "label_free" in b]
    recs += [x for d in days for x in d.get("label_free") or []]
    q = [r for r in recs if r.get("qualifying_snapshots")]
    hours = {}
    for r in q:
        hours[str(r["first_hour"])] = hours.get(str(r["first_hour"]), 0) + 1
    return {"descriptive_only": True, "dead_buckets": len(recs), "with_qualifying_no_ask": len(q),
            "on_unlabelled_days": int(sum(len(d.get("label_free") or []) for d in days)),
            "sum_first_ask_depth_1pct": float(sum(r["first_ask_depth_1pct"] for r in q)),
            "sum_max_ask_depth_1pct": float(sum(r["max_ask_depth_1pct"] for r in q)),
            "per_first_hour": dict(sorted(hours.items())),
            "examples": sorted(q, key=lambda r: r["first_utc"])[:10]}


def partition_ok(keys):
    """True when the parsed buckets (incl. gte) tile the integers: lte X, eq X+1..., ..., gte Y, no gaps."""
    lte = [k for k in keys if k[0] == "lte"]
    gte = [k for k in keys if k[0] == "gte"]
    eqs = sorted((k[1], k[2]) for k in keys if k[0] == "eq")
    if len(lte) != 1 or len(gte) != 1:
        return False
    nxt = lte[0][1] + 1
    for lo, hi in eqs:
        if lo != nxt or hi < lo:
            return False
        nxt = hi + 1
    return gte[0][1] == nxt


def stage_a_scan(obs, wu, tapes_root, kept, dating="obs", replay_root=None):
    zone = obs["tz"]
    events = {d: f for (mk, d), f in db.discover_tape_events(tapes_root).items() if mk == MARKET}
    replay = ({d: f for (mk, d), f in db.discover_tape_events(Path(replay_root) / "snapshots").items()
               if mk == MARKET} if dating == "capture" else {})
    buckets, days = [], []
    for d_iso, folder in sorted(events.items()):
        dd = date.fromisoformat(d_iso)
        w = wu.loc[dd] if dd in wu.index else None
        info = {"market": MARKET, "date": d_iso, "folder": folder.name}
        wu_max = None if w is None or pd.isna(w.max_temp_native) else float(w.max_temp_native)
        day = obs["days"].get(dd)
        steps = steps_c(day, dd, zone)
        start, end = db.local_instant(dd, 13, 0, zone), db.local_instant(dd, 16, 59, zone)
        h_end = db.H(running_c(rows_c(day), dd, zone, end)[0])
        extra, csteps = {}, None
        if dating == "capture":
            rfolder = replay.get(d_iso)
            if rfolder is not None:
                csteps, bad = db.capture_steps(rfolder / "replay_inputs.jsonl", dd, zone, end,
                                               db.RUNNING_MAX_CUTOFF_HOUR, unit=UNIT)
                hs = [h for _, h in csteps if h is not None]
                extra = {"replay_snapshots": len(csteps), "replay_bad_lines": bad,
                         "non_monotone": db.non_monotone(csteps), "H_s_last_c": hs[-1] if hs else None}
            if not csteps:
                days.append(dict(info, status="no_replay", **extra))
                continue
        rows, tokens, highs, n = stream_summary_c(folder / "order_books_summary.csv", start, end)
        info.update(extra, partition_ok=partition_ok([tuple(k) for k in n["parsed_labels"].values()]))
        dead = []
        for key, high in sorted(highs.items()):
            fd_obs = db.first_dead(steps, float(high)) if h_end is not None and high < h_end else None
            if dating == "capture":
                fd = db.first_dead_capture(csteps, int(high))
                if fd is None:
                    extra["dead_obs_only"] = extra.get("dead_obs_only", 0) + (fd_obs is not None)
                    continue
                x = {"first_dead_obs10": fd_obs.isoformat() if fd_obs else None}
            else:
                if fd_obs is None:
                    continue
                fd, x = fd_obs, {}
            dead.append((key, high, fd, max(fd + db.LATENCY, start), x))
        info["dead_obs_only"] = extra.get("dead_obs_only", 0)
        lf = {tuple(k): label_free_no_ask(rows, k, en, end, zone) for k, _, _, en, _ in dead}
        if wu_max is None:  # no settlement label: label-free measure only, never the primary
            days.append(dict(info, status="no_wu_label", H_1659_c=h_end, summary=n,
                             label_free=[dict(v, bucket=list(k)) for k, v in lf.items()]))
            continue
        if not dead:
            days.append(dict(info, status="no_dead", H_1659_c=h_end, summary=n))
            continue
        t_first = min(d_[3] for d_ in dead)
        prints, n_parts = db.stream_prints(folder, tokens, t_first, end + db.PRINT_WINDOW)
        days.append(dict(info, status="scanned", H_1659_c=h_end, wu_max_c=wu_max, n_dead=len(dead), summary=n,
                         trade_parts=n_parts, prints_kept=len(prints), tokens_matched=len(tokens)))
        for key, high, fd, entry, x in dead:
            yes = settled_yes(key, wu_max)
            rec = dict({"market": MARKET, "date": d_iso, "bucket": list(key), "high_c": high,
                        "first_dead": fd.isoformat(), "entry_instant": entry.isoformat(), "settled_yes": bool(yes),
                        "excluded_market": MARKET not in kept, "trade_parts": n_parts,
                        "label_free": lf[tuple(key)]}, **x)
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
    summ["market_days"]["no_replay"] = int(sum(x["status"] == "no_replay" for x in days))
    summ["parse_check"] = parse_check(days)
    summ["label_free_no_ask"] = label_free_summary(buckets, days)
    if any("first_dead_obs10" in b for b in buckets) or summ["market_days"]["no_replay"]:
        summ["r4"] = r4_controls(buckets, days)
        if summ["r4"]["verdict"] != "PASS":
            res["A_08-10..09-29"]["reading"] = "NOT INTERPRETABLE (r4-toronto control failed)"
    return res, summ


def parse_check(days):
    labels, failed = {}, {}
    for x in days:
        s = x.get("summary") or {}
        labels.update(s.get("parsed_labels") or {})
        for f in s.get("failed_labels") or []:
            k = (f["label"], f["bin_kind"], f["bin_value"], f["bin_value_hi"], f["unit"])
            failed[k] = failed.get(k, 0) + f["rows"]
    bad_days = sorted(x["date"] for x in days if x.get("partition_ok") is False)
    return {"distinct_labels_parsed": len(labels), "parsed": dict(sorted(labels.items())),
            "distinct_failures": len(failed),
            "failures": [{"label": k[0], "bin_kind": k[1], "bin_value": k[2], "bin_value_hi": k[3], "unit": k[4],
                          "rows": c} for k, c in sorted(failed.items())],
            "days_not_a_partition": bad_days, "verdict": "PASS" if not failed and not bad_days else "REPORTED"}


def r4_controls(buckets, days):
    def t(v):
        return datetime.fromisoformat(v) if v else None
    both = [b for b in buckets if b.get("first_dead_obs10") and b.get("first_dead")]
    ok = [b for b in both if t(b["first_dead"]) >= t(b["first_dead_obs10"]) - db.AVAILABILITY]
    share = len(ok) / len(both) if both else None
    lag = np.array([(t(b["first_dead"]) - t(b["first_dead_obs10"]) + db.AVAILABILITY).total_seconds() / 60
                    for b in both], float)
    cmp_days = [x for x in days if x.get("H_s_last_c") is not None and x.get("H_1659_c") is not None]
    near = [x for x in cmp_days if abs(x["H_s_last_c"] - x["H_1659_c"]) <= 1]
    c_share = len(near) / len(cmp_days) if cmp_days else None
    receipt_ok = share is None or share >= db.R4_SANITY_MIN  # no bucket dead under both: nothing to contradict
    celsius_ok = c_share is not None and c_share >= CELSIUS_SANITY_MIN
    return {"receipt_after_obs": {"buckets_dead_both": len(both), "ok": len(ok), "share": share,
                                  "min_share": db.R4_SANITY_MIN, "pass": bool(receipt_ok)},
            "celsius_sanity": {"days": len(cmp_days), "within_1c": len(near), "share": c_share,
                               "min_share": CELSIUS_SANITY_MIN, "pass": bool(celsius_ok),
                               "max_abs_diff_c": max((abs(x["H_s_last_c"] - x["H_1659_c"]) for x in cmp_days),
                                                     default=None)},
            "receipt_minus_obs_min": ({"n": int(len(lag)), "median": float(np.median(lag)),
                                       "p10": float(np.quantile(lag, .1)), "p90": float(np.quantile(lag, .9))}
                                      if len(lag) else {"n": 0}),
            "dead_capture_only": int(sum(1 for b in buckets if b.get("first_dead") and not b.get("first_dead_obs10"))),
            "dead_obs_only": int(sum(x.get("dead_obs_only", 0) for x in days)),
            "non_monotone_steps": int(sum(x.get("non_monotone", 0) for x in days)),
            "replay_bad_lines": int(sum(x.get("replay_bad_lines", 0) for x in days)),
            "verdict": "PASS" if receipt_ok and celsius_ok else "FAIL"}


# ----------------------------------------------------------------------------- CLI

def _rule():
    if not RULE_SHA256:
        raise data.Refused("refused: the r2-toronto rule sha256 is not recorded in the code yet")
    return RULE_SHA256


def _scan_rule(args):
    return RULE_R4_SHA256 if getattr(args, "dating", "obs") == "capture" else _rule()


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
    ap.add_argument("--wu-extra", help="clarification 1: appended CYYZ daily summary (fails closed)")
    ap.add_argument("--wu-extra-sha256")
    ap.add_argument("--history")
    ap.add_argument("--history-sha256")
    ap.add_argument("--tapes")
    ap.add_argument("--tapes-sha256sums")
    ap.add_argument("--scan")
    ap.add_argument("--dating", choices=("obs", "capture"), default="obs", help="capture = rule r4-toronto")
    ap.add_argument("--replay-root")
    ap.add_argument("--replay-sha256sums")
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
            rsums = None
            if args.dating == "capture":
                if sums != TAPES_SUMS_SHA256:
                    raise data.Refused(f"refused: Toronto tapes SHA256SUMS {sums} != the rule's {TAPES_SUMS_SHA256}")
                if not args.replay_root:
                    raise data.Refused("refused: --dating capture needs --replay-root and --replay-sha256sums")
                rsums = db.sha256_file(Path(args.replay_root) / "SHA256SUMS")
                if rsums != args.replay_sha256sums or rsums != db.REPLAY_SUMS_SHA256:
                    raise data.Refused(f"refused: replay SHA256SUMS {rsums} != the rule's {db.REPLAY_SUMS_SHA256}")
            obs = load_obs(args.obs, args.obs_sha256)
            wu, wu_path = load_wu(args.wu_root, args.wu_extra, args.wu_extra_sha256)
            buckets, days = stage_a_scan(obs, wu, args.tapes, kept, args.dating, args.replay_root)
            payload = dict({"schema": SCHEMA_A_SCAN, "rule_sha256": _scan_rule(args), "history_sha256": hsha,
                            "dating": args.dating, "replay_sha256sums_sha256": rsums,
                            "rule_doc_sha256": RULE_R4_C1_DOC_SHA256 if args.wu_extra else None,
                            "wu_inputs": [{"path": str(wu_path), "sha256": db.sha256_file(wu_path)}] + (
                                [{"path": str(args.wu_extra), "sha256": db.sha256_file(args.wu_extra)}]
                                if args.wu_extra else []),
                            "obs_sha256": obs["sha256"], "tapes_sha256sums_sha256": sums, "buckets": buckets,
                            "days": days, "dates_all": sorted(x["date"] for x in days)}, **_code())
            name = "toronto_stage_a" + ("_r4" if args.dating == "capture" else "") + "_scan"
        else:
            hist, kept, rate, hsha = _history(args)
            scan = json.loads(Path(args.scan).read_text(encoding="utf-8"))
            if (scan.get("schema") != SCHEMA_A_SCAN or scan.get("history_sha256") != hsha
                    or scan.get("rule_sha256") != _scan_rule(args) or scan.get("dating", "obs") != args.dating):
                raise data.Refused("refused: not a Toronto stage-A scan of this rule, dating and history")
            res, summ = stage_a_report(scan["buckets"], scan["days"], scan["dates_all"], kept, rate)
            payload = dict({"schema": SCHEMA_A, "rule_sha256": _scan_rule(args), "history_sha256": hsha,
                            "dating": args.dating, "scan_sha256": db.sha256_file(args.scan), "excluded": not kept,
                            "evidence_class": "development (dev window); Toronto stage A (" + (
                                "r4-toronto, capture-dated" if args.dating == "capture" else "r2-toronto") + ")",
                            "results": res, "summary": summ}, **_code())
            name = "toronto_stage_a" + ("_r4" if args.dating == "capture" else "")
    except (data.Refused, data.LayoutError) as exc:
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    blob = json.dumps(sc._clean(payload), sort_keys=True, indent=1, default=str).encode("utf-8")
    (out / f"{name}.json").write_bytes(blob)
    print(json.dumps({"json": str(out / f"{name}.json"), "sha256": hashlib.sha256(blob).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
