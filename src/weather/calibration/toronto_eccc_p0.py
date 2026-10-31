r"""Toronto native guidance (ECCC GEM, citypage) against the market: P0 (lane L8, 2026-10-30; ledger row 90).

Rule ``docs/research/toronto-eccc-p0-2026-10-30/rule_toronto_eccc_p0.md`` (sha256 ``RULE_SHA256``, on the
ledger branch ``claude/successor-batch-20261030``). Its own arm (K = 2), not pooled with rows 77, 78 or 85-89.

- Population: the row 77 Toronto table. Captured Toronto replay snapshots whose America/Toronto capture date is
  the slug's target date, local hours 07..12, dev dates 2026-08-01..09-29 (burn-in 08-01..08-14, scored
  08-15..09-29). Market m from the pinned Toronto tapes (latest group <= t_c within 600 s, every book_time <= t_c,
  one native-°C partition; displayed price per row 77 clarifications 2, 6 and 6b). METAR floor <= t_c. WU CYYZ
  labels (native integer °C) from two sha-pinned files; every date is before the 10-23 venue rule.
- Candidates (type C, sign +, native °C): ``GEM-SEAMLESS`` = ``eccc_gem.data.day_model_highs.gem_seamless`` and
  ``CITYPAGE-FH`` = ``eccc_citypage.data.forecast_high_native``. Covered iff the source is ``ok``, its
  ``fetched_at`` <= ``captured_at_utc`` and the value is finite in [-40, 50].
- Statistic: ``mr_sweep``'s machinery unchanged (tilt, 20 disagreement placebos, paired date-cluster bootstrap,
  10,000 draws, seed 20261024). BH q = 0.10 over K = 2; survivor iff BH rejects and the Delta lower bound > 0.
  Only a survivor gets the w = 0 identity and the 07-12 w gate.

No network. Writes only under ``--out`` and never overwrites. Every input is sha-pinned. Nothing is converted
to °F. ``selection_check`` is outcome-free: it reads no observation, label or price.

    python -m weather.calibration.loyo_screen toronto-eccc-p0 --out C:/t/l8tor/eccc_p0
    python -m weather.calibration.loyo_screen toronto-eccc-p0 --selection-only --out C:/t/l8tor/eccc_sel
    python -m weather.calibration.loyo_screen toronto-eccc-p0 --controls-only --row77-dir C:/t/l8tor/p0_out
        --out C:/t/l8tor/eccc_ctrl   (one command line)

``--controls-only`` is row 90 amendment 1 (``amendment_1.md``, sha256 ``AMENDMENT_1_SHA256``): the w = 0 identity,
the row 77 reproduction through the ported table at 07-16, and the synthetic positive control (SYN+ / SYN-).
Same pinned inputs and verdict rule; it decides only whether the row 90 KILL stands or row 90 is VOID.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from weather import paths
from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "toronto_eccc_p0/1"
GATE = "TORONTO-ECCC-P0"
RULE_SHA256 = "b8718b46d0244054be26834a0a35d28f0ff2ed45d8056e0393334ce5df4b0b0d"
LEDGER_ROW = 90
AMENDMENT_1_SHA256 = "40b90e72d14285900c883b0b66d7136da87781f3b758e0807785d639acf71141"
ROW77_HOURS = (7, 16)
ROW77_ARMS_SHA256 = "16ba22cfcd14dd7ecb6c53e42237ca5ddceb2f98d2f7865e1849d422ac2ee3d5"
ROW77_RECEIPT_SHA256 = "6baa2703f144fc8bcf0226d6e5542a2ca11903edef83fee89368290037c7876b"
ROW77_TOL = 5e-5
SYN_SEED = 20261031
TZ = "America/Toronto"
MARKET = "toronto"
FIRST, LAST, BURN_LAST = date(2026, 8, 1), date(2026, 9, 29), date(2026, 8, 14)
HOURS = (7, 12)
W_BLOCK = "07-12"
MAX_AGE_S = 600
VALUE_RANGE_C = (-40.0, 50.0)
CANDIDATES = (("GEM-SEAMLESS", "C", 1, "gem", "rc_gem"), ("CITYPAGE-FH", "C", 1, "city", "rc_city"))

_REPO = paths.REPO_ROOT
DEFAULT_REPLAY = paths.DATA_ROOT / "inbox" / "replay-inputs-le0929"
DEFAULT_TAPES = paths.DATA_ROOT / "inbox" / "tapes-toronto-0801-0929"
REPLAY_SUMS_SHA256 = "d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82"
TAPE_SUMS_SHA256 = "a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0"
LABEL_FILES = (
    ("data/wunderground/cyyz/daily/daily_summary.csv",
     "1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1"),
    ("data/inbox/wu-cyyz-0811-0929/daily_summary_cyyz_0811_0929.csv",
     "c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a"),
)
MONTHS = {"july": 7, "august": 8, "september": 9, "october": 10}
SLUG = re.compile(r"^highest-temperature-in-toronto-on-([a-z]+)-(\d+)-2026$")
TGROUP = re.compile(r" T([01])(\d{3})([01])(\d{3})")
S1_BLOCKS = (("00-06", 0, 6), ("07-12", 7, 12), ("13-16", 13, 16), ("17-23", 17, 23))


class TorontoEcccError(mg.GateError):
    """A refused Toronto ECCC P0 run."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sums(path, want):
    """Parse a pinned SHA256SUMS file -> {relative name: sha256}; refuses on a mismatch."""
    got = _sha(path)
    if got != want:
        raise TorontoEcccError(f"{path} sha256 {got} is not the pinned {want}")
    out = {}
    for line in Path(path).read_text(encoding="utf-8").replace("\r", "").splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            out[name.strip().lstrip("*")] = h
    return out


def slug_date(name):
    hit = SLUG.match(name)
    if not hit or hit.group(1) not in MONTHS:
        return None
    return date(2026, MONTHS[hit.group(1)], int(hit.group(2)))


def _fresh_out(out):
    """Refuse an existing non-empty output directory (write only under --out, never overwrite)."""
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise TorontoEcccError(f"refusing to overwrite: {out} exists and is not empty")
    return out


def _guard(d):
    if d > LAST:
        raise TorontoEcccError(f"refused: {d} is after {LAST}")
    return d


# ----------------------------------------------------------------------------- capture-time values

def _value(v):
    f = sw._num(v)
    return f if np.isfinite(f) and VALUE_RANGE_C[0] <= f <= VALUE_RANGE_C[1] else np.nan


def record_values(rec):
    """One replay record -> the two candidate values and their receipts (NaN / None unless the source is ok)."""
    src = rec.get("sources") or {}
    out = {}
    for key, name, getter in (("gem", "eccc_gem", lambda d: (d.get("day_model_highs") or {}).get("gem_seamless")),
                              ("city", "eccc_citypage", lambda d: d.get("forecast_high_native"))):
        s = src.get(name) or {}
        if s.get("ok") is not True:
            out[key], out[f"rc_{key}"] = np.nan, None
            continue
        out[key] = _value(getter(s.get("data") or {}))
        out[f"rc_{key}"] = s.get("fetched_at")
    return out


def metar_temp(row):
    m = TGROUP.search(f" {row.get('raw') or ''} ")
    if m:
        return (-1.0 if m.group(1) == "1" else 1.0) * int(m.group(2)) / 10.0
    v = sw._num(row.get("temp_c"))
    return float(v) if np.isfinite(v) else None


def metar_floor(rec, tc, d, zone):
    """Max METAR temperature (native °C) reported <= t_c on the target date, or None."""
    met = (rec.get("sources") or {}).get("metar") or {}
    rows = ((met.get("data") or {}).get("rows") or []) if met.get("ok") else []
    vals = []
    for r in rows:
        try:
            rt = datetime.fromisoformat(str(r.get("report_time")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if rt.tzinfo is not None and rt <= tc and rt.astimezone(zone).date() == d:
            v = metar_temp(r)
            if v is not None:
                vals.append(v)
    return max(vals) if vals else None


def _replay_files(replay_root, first, last):
    root = Path(replay_root)
    sums = _sums(root / "SHA256SUMS", REPLAY_SUMS_SHA256)
    files = []
    for folder in sorted((root / "snapshots").iterdir()):
        d = slug_date(folder.name)
        if d is None or d < first or d > last:
            continue
        rel = f"snapshots/{folder.name}/replay_inputs.jsonl"
        f = root / rel
        if not f.exists():
            continue
        if rel not in sums or _sha(f) != sums[rel]:
            raise TorontoEcccError(f"replay file {rel} does not match SHA256SUMS")
        files.append((_guard(d), folder.name, f))
    return files


def extract(replay_root, hours=HOURS, first=FIRST, last=LAST, with_floor=True):
    """Stream the Toronto replay records (read only) -> (one row per snapshot, malformed lines, stats).

    Kept: capture date (America/Toronto) == target date and local hour in ``hours``. The last complete record of
    a snapshot id wins. No price or label is read; the METAR floor is read only when ``with_floor``."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(TZ)
    rows, malformed, stats = [], [], defaultdict(int)
    for d, name, f in _replay_files(replay_root, first, last):
        with f.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    malformed.append({"file": name, "line": lineno, "chars": len(line), "error": str(exc)[:120]})
                    continue
                try:
                    tc = datetime.fromisoformat(str(rec["captured_at_utc"]).replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    stats["no_capture_time"] += 1
                    continue
                loc = tc.astimezone(zone)
                if loc.date() != d:
                    stats["capture_not_target_date"] += 1
                    continue
                if not hours[0] <= loc.hour <= hours[1]:
                    continue
                row = {"row_key": f"{MARKET}|{rec.get('snapshot_id')}", "date": d.isoformat(),
                       "captured_at_utc": tc.isoformat(), "local_hour": loc.hour, **record_values(rec)}
                if with_floor:
                    row["F"] = metar_floor(rec, tc, d, zone)
                    row["served"] = {int(k): float(v) for k, v in (rec.get("recorded_distribution") or {}).items()}
                rows.append(row)
                stats["records"] += 1
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise TorontoEcccError(f"no Toronto replay record under {replay_root}")
    n = len(frame)
    frame = frame.drop_duplicates("row_key", keep="last").reset_index(drop=True)
    stats["duplicate_records_dropped"] = n - len(frame)
    return frame, malformed, dict(stats)


def candidate_values(snaps, feats):
    """Per candidate: values on ``snaps`` (NaN where uncovered: no value, no receipt, receipt after capture,
    or a local hour outside the block)."""
    f = feats.set_index("row_key").reindex(snaps.row_key.to_numpy())
    cap = sw._utc(snaps.captured_at_utc)
    hour = snaps.local_hour.to_numpy(int)
    out = {}
    for cid, _, _, col, rc in CANDIDATES:
        v = f[col].to_numpy(float)
        r = sw._utc(f[rc])
        ok = (np.isfinite(v) & ~np.isnat(r) & ~np.isnat(cap) & (r <= cap)
              & (hour >= HOURS[0]) & (hour <= HOURS[1]))
        out[cid] = np.where(ok, v, np.nan)
    return out


# ----------------------------------------------------------------------------- outcome-free selection check

def selection_check(*, replay_root=DEFAULT_REPLAY, out_dir):
    """Reproduce the S1 coverage (all hours, every dev date <= 09-29) without reading an observation, a label or
    a price; writes ``selection_check.json`` (never overwrites)."""
    out = _fresh_out(out_dir)
    target = out / "selection_check.json"
    frame, malformed, stats = extract(replay_root, hours=(0, 23), first=date(2026, 7, 1), last=LAST,
                                      with_floor=False)
    feats = frame[["row_key", "gem", "rc_gem", "city", "rc_city"]]
    cap = sw._utc(frame.captured_at_utc)
    cov = {}
    for cid, _, _, col, rc in CANDIDATES:
        v = feats[col].to_numpy(float)
        r = sw._utc(feats[rc])
        cov[cid] = np.isfinite(v) & ~np.isnat(r) & (r <= cap)
    hour = frame.local_hour.to_numpy(int)
    blocks = {}
    for name, lo, hi in S1_BLOCKS:
        sel = (hour >= lo) & (hour <= hi)
        blocks[name] = {"snapshots": int(sel.sum()), **{f"covered_{c}": int((cov[c] & sel).sum()) for c in cov}}
    per_date = {}
    for d, g in frame.groupby("date"):
        idx = g.index.to_numpy()
        per_date[d] = {"snapshots": int(len(g)), "hours": int(g.local_hour.nunique()),
                       **{f"covered_{c}": int(cov[c][idx].sum()) for c in cov}}
    receipt = {"schema": SCHEMA + "/selection", "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW,
               "reads": "replay key, date, captured_at, hour, source ok/fetched_at and candidate null flags only",
               "module_sha256": ls.sha256_file(__file__),
               "replay_sha256sums_sha256": REPLAY_SUMS_SHA256, "malformed_lines": malformed, "stats": stats,
               "n_dates": len(per_date), "first_date": min(per_date), "last_date": max(per_date),
               "snapshots": int(len(frame)), "per_block": blocks, "per_date": per_date}
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    return receipt


# ----------------------------------------------------------------------------- market (row 77 tape rule)

def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def bin_of(label, kind, value, value_hi, unit):
    """A tape row's bin as (kind, low, high) in native °C; refuses a non-°C unit; None on a parse mismatch."""
    from weather.units import parse_temperature_band

    if str(unit).strip().upper().lstrip("\u00b0") != "C":
        raise TorontoEcccError(f"refused: tape unit {unit!r} is not native C")
    band = parse_temperature_band(label, expected_unit="C")
    if band is None or str(kind).strip().lower() != band.kind:
        return None
    lo, hi = int(band.value), int(band.value_hi)
    v, vh = _f(value), _f(value_hi)
    if v is None or vh is None:
        return None
    if band.kind == "eq" and (v != lo or vh != hi):
        return None
    if band.kind != "eq" and v != lo:
        return None
    return {"lte": ("lte", -999, lo), "gte": ("gte", lo, 999)}.get(band.kind, ("eq", lo, hi))


def displayed(r):
    """Row 77 clarifications 2, 6, 6b: midpoint if the spread (missing side at its bound) <= 0.10, else the
    gamma last trade, else the midpoint."""
    bid, ask, last, mid = (_f(r["best_bid"]), _f(r["best_ask"]), _f(r["gamma_last_trade_price"]),
                           _f(r["midpoint"]))
    bb, aa = (0.0 if bid is None else bid), (1.0 if ask is None else ask)
    if aa - bb <= 0.10 + 1e-12:
        return (bb + aa) / 2
    if last is not None:
        return last
    return mid


TAPE_COLUMNS = ["captured_at_utc", "book_time_utc", "range_label", "bin_kind", "bin_value", "bin_value_hi", "unit",
                "outcome", "best_bid", "best_ask", "midpoint", "gamma_last_trade_price"]


def tape_groups(csv_path):
    t = pd.read_csv(csv_path, usecols=TAPE_COLUMNS, dtype=str, keep_default_na=False)
    return [(datetime.fromisoformat(cap.replace("Z", "+00:00")), g) for cap, g in t.groupby("captured_at_utc",
                                                                                        sort=True)]


def group_vector(g, tc):
    """(bins, p) for one tape group at capture tc, or (None, reason)."""
    bins = {}
    for r in g.to_dict("records"):
        b = bin_of(r["range_label"], r["bin_kind"], r["bin_value"], r["bin_value_hi"], r["unit"])
        if b is None:
            return None, "bin_parse"
        bt = datetime.fromisoformat(r["book_time_utc"].replace("Z", "+00:00"))
        if bt > tc:
            return None, "book_after_capture"
        oc = str(r["outcome"]).strip().lower()
        v = displayed(r)
        if oc == "no" and v is not None and v != _f(r["gamma_last_trade_price"]):
            v = 1 - v
        bins.setdefault(b, {})[oc] = v
    keys = sorted(bins, key=lambda b: (b[1], b[2]))
    if (len(keys) < 2 or keys[0][0] != "lte" or keys[-1][0] != "gte"
            or any(k[0] == "lte" for k in keys[1:]) or any(k[0] == "gte" for k in keys[:-1])
            or any(a[2] + 1 != b[1] for a, b in zip(keys, keys[1:]))):
        return None, "not_partition"
    p = []
    for k in keys:
        yes, no = bins[k].get("yes"), bins[k].get("no")
        v = yes if yes is not None else no
        if v is None:
            return None, "missing_price"
        p.append(v)
    return (keys, p), None


def market_vectors(tapes_root, snaps):
    """Capture-time market vectors per snapshot from the pinned tapes -> ({row_key: (bins, p)}, reasons)."""
    root = Path(tapes_root)
    want = _sums(root / "SHA256SUMS", TAPE_SUMS_SHA256)
    out, reasons = {}, defaultdict(int)
    for d, g in snaps.groupby("date", sort=True):
        dd = _guard(date.fromisoformat(d))
        name = f"highest-temperature-in-toronto-on-{dd.strftime('%B').lower()}-{dd.day}-2026/order_books_summary.csv"
        f = root / name
        if not f.exists():
            reasons["no_tape_file"] += len(g)
            continue
        if name not in want or _sha(f) != want[name]:
            raise TorontoEcccError(f"tape {name} does not match SHA256SUMS")
        groups = tape_groups(f)
        caps = [x[0] for x in groups]
        for rk, cap in zip(g.row_key, g.captured_at_utc):
            tc = datetime.fromisoformat(cap)
            i = bisect.bisect_right(caps, tc) - 1
            got, why = None, "no_group_within_10min"
            while i >= 0 and (tc - caps[i]).total_seconds() <= MAX_AGE_S:
                got, why = group_vector(groups[i][1], tc)
                if got is not None:
                    break
                reasons[f"skip_group:{why}"] += 1
                i -= 1
            if got is None:
                reasons[f"drop:{why}"] += 1
                continue
            out[rk] = got
    return out, dict(reasons)


# ----------------------------------------------------------------------------- labels and the table

def load_labels(repo_root=_REPO, files=LABEL_FILES):
    """WU CYYZ daily maxima (native integer °C) for FIRST..LAST from the sha-pinned files."""
    out = {}
    for rel, want in files:
        path = Path(repo_root) / rel
        got = _sha(path)
        if got != want:
            raise TorontoEcccError(f"label file {rel} sha256 {got} is not the pinned {want}")
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                d = row.get("local_date") or ""
                if len(d) != 10 or d < FIRST.isoformat() or d > LAST.isoformat():
                    continue
                if row.get("temperature_unit") != "C":
                    raise TorontoEcccError(f"refused: label unit {row.get('temperature_unit')!r} on {d}")
                v = row.get("max_temp_native")
                if v in (None, ""):
                    continue
                f = float(v)
                if f != int(f) or (d in out and out[d] != int(f)):
                    raise TorontoEcccError(f"refused: bad or conflicting label on {d}")
                out[d] = int(f)
    return out


def build_layout(snaps, mk, labels):
    """The row 77 in-memory Toronto layout -> (layout, drops)."""
    from weather.reporting.scorecards import dev_scorecard_data as data

    rows, bands, labs, mkt, drops = [], [], [], [], defaultdict(int)
    for s in snaps.itertuples(index=False):
        if s.row_key not in mk:
            drops["no_m"] += 1
            continue
        if s.date not in labels:
            drops["no_label"] += 1
            continue
        keys, p = mk[s.row_key]
        y = labels[s.date]
        win = [i for i, (_, lo, hi) in enumerate(keys) if lo <= y <= hi]
        if len(win) != 1:
            drops["label_not_in_one_bin"] += 1
            continue
        served = [sum(v for k, v in s.served.items() if lo <= int(k) <= hi) for _, lo, hi in keys]
        rows.append({"row_key": s.row_key, "date": s.date, "captured_at_utc": s.captured_at_utc,
                     "local_hour": s.local_hour, "market": MARKET, "n_bands": len(keys),
                     "guidance_physical_floor": np.nan, "high_so_far": np.nan if s.F is None else s.F,
                     "trusted_current_max": np.nan})
        for i, (kind, lo, hi) in enumerate(keys):
            bands.append({"row_key": s.row_key, "band_index": i, "kind": kind, "low": lo, "high": hi,
                          "p_served": served[i], "date": s.date})
            mkt.append({"row_key": s.row_key, "band_index": i, "date": s.date, "p_market_yes": p[i]})
        labs.append({"row_key": s.row_key, "date": s.date, "winner": win[0]})
    if not rows:
        raise TorontoEcccError("no snapshot has a market vector and a label")
    S = pd.DataFrame(rows).sort_values(["date", "captured_at_utc", "row_key"], kind="mergesort")
    S = S.reset_index(drop=True)
    order = {rk: i for i, rk in enumerate(S.row_key)}
    B = pd.DataFrame(bands)
    B["_o"] = B.row_key.map(order)
    B = B.sort_values(["_o", "band_index"], kind="mergesort").drop(columns="_o").reset_index(drop=True)
    lay = data.Layout(snaps=S, bands=B, labels=pd.DataFrame(labs), market=pd.DataFrame(mkt),
                      manifest_sha256="in-memory (row 77 Toronto table)", file_sha256={},
                      label_source="WU CYYZ (pinned label files)", dates=sorted(S.date.unique()))
    return lay, dict(drops)


def build_tables(replay_root, tapes_root, repo_root=_REPO, hours=HOURS):
    """Snapshots, market vectors, labels and the fit / score tables (local ``hours``; 07-12 unless a control)."""
    from weather.reporting.scorecards import dev_scorecard as sc

    snaps, malformed, stats = extract(replay_root, hours=hours)
    mk, reasons = market_vectors(tapes_root, snaps)
    labels = load_labels(repo_root)
    lay, drops = build_layout(snaps, mk, labels)
    dates = sorted(lay.dates)
    burn = [d for d in dates if d <= BURN_LAST.isoformat()]
    scored = [d for d in dates if d > BURN_LAST.isoformat()]
    if not burn or not scored or scored[-1] > LAST.isoformat():
        raise TorontoEcccError("burn-in must precede the scored dates, and nothing may be scored after 2026-09-29")
    meta = {"extract_stats": stats, "malformed": malformed, "market_reasons": reasons, "table_drops": drops}
    return snaps, sc.Table(lay, burn + scored), sc.Table(lay, scored), burn, scored, meta


# ----------------------------------------------------------------------------- the run

def decide(results, ids):
    adj, reject = sw.bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    for cid, q, rj in zip(ids, adj, reject):
        r = results[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"], r["bh_reject"] = float(q), bool(rj)
        r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["verdict"] = "SURVIVE" if r["survive"] else ("UNTESTABLE" if not r["testable"] else "KILL")
    return results


def run(*, out_dir, replay_root=DEFAULT_REPLAY, tapes_root=DEFAULT_TAPES, repo_root=_REPO, allow_dirty=False):
    """P0 for K = 2, BH, the w gate only for a survivor; writes the receipt, rows and features."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = _fresh_out(out_dir)
    if mg.BLOCKS.get(W_BLOCK) != HOURS:
        raise TorontoEcccError("mr_gate.BLOCKS must carry the 07-12 block")
    snaps, fit_t, score_t, burn, scored, meta = build_tables(replay_root, tapes_root, repo_root)
    if set(fit_t.markets) != {MARKET}:
        raise TorontoEcccError("the population is Toronto only")
    feats = snaps[["row_key", "gem", "rc_gem", "city", "rc_city"]]
    out.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(out / "features.parquet", index=False)
    values = candidate_values(fit_t.snaps, feats)
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(scored)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    results, kept, rows = {}, {}, []
    for cid, kind, sign, _, _ in CANDIDATES:
        res, vecs = sw.p0_candidate(cid, kind, sign, values[cid], fit_t, score_t, geo, counts, score_dates, donors)
        rows += res.pop("_rows", [])
        results[cid] = res
        if vecs is not None:
            kept[cid] = vecs
    ids = [c[0] for c in CANDIDATES]
    decide(results, ids)
    controls = {}
    for cid in [c for c in ids if results[c]["survive"]]:
        vec = kept[cid]
        controls[f"w0_identity_{cid}"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
        if controls[f"w0_identity_{cid}"]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, W_BLOCK, fit_t, score_t, vec["c_fit"], vec["covered"],
                              p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}

    lines = [sw.line_for(results[c]) for c in ids]
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "development (dev window, provisional; kill-only)",
               "module_sha256": {"toronto_eccc_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                                 "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(),
               "inputs": {"replay_sha256sums_sha256": REPLAY_SUMS_SHA256, "tape_sha256sums_sha256": TAPE_SUMS_SHA256,
                          "label_files": {rel: sha for rel, sha in LABEL_FILES},
                          "features_parquet_sha256": ls.sha256_file(out / "features.parquet")},
               "units": "native C, 1 C buckets; no conversion",
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "local_hours": list(HOURS),
                              "n_fit_snapshots": int(len(fit_t.snaps)), "n_score_snapshots": int(len(score_t.snaps))},
               "table_meta": meta,
               "constants": {"k": len(CANDIDATES), "draws": sw.DRAWS, "seed": sw.SEED,
                             "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q,
                             "sigma2_floor": sw.SIGMA2_FLOOR, "min_dates": sw.MIN_DATES,
                             "min_snapshots": sw.MIN_SNAPS, "w_block": W_BLOCK, "max_tape_age_s": MAX_AGE_S,
                             "value_range_c": list(VALUE_RANGE_C)},
               "controls": controls, "results": results, "lines": lines}
    (out / "toronto_eccc_p0_rows.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n" for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "toronto_eccc_p0_rows.jsonl")
    (out / "toronto_eccc_p0.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                              encoding="utf-8")
    return receipt


# ----------------------------------------------------------------------------- amendment 1: controls only

def _close(got, want, tol=ROW77_TOL):
    return got is not None and want is not None and abs(float(got) - float(want)) < tol


def inject_vectors(fit_t, vectors):
    """Row 77's injection: band vectors on the snapshots they cover (floor-impossible bands 0, renormalised to 1),
    the market elsewhere -> (c_fit, covered)."""
    m_fit = fit_t.p_market
    c_fit = m_fit.copy()
    covered = np.zeros(len(fit_t.snaps), bool)
    for i, rk in enumerate(fit_t.snaps.row_key):
        v = vectors.get(rk)
        if v is None:
            continue
        if len(v) != fit_t.n[i]:
            raise TorontoEcccError(f"band count mismatch for {rk}")
        c_fit[fit_t.offsets[i]:fit_t.offsets[i] + fit_t.n[i]] = v
        covered[i] = True
    c_fit = np.where(fit_t.impossible, 0.0, c_fit)
    tot = np.bincount(fit_t.band_snap, weights=c_fit, minlength=len(fit_t.snaps))
    c_fit = np.where(covered[fit_t.band_snap], c_fit / np.where(tot > 0, tot, 1.0)[fit_t.band_snap], m_fit)
    return c_fit, covered


def vector_p0(fit_t, score_t, c_fit, covered, scored, counts, donors):
    """Row 77's P0 for a band-vector candidate: placebos, population, paired Delta and the c-deranged rho."""
    from weather.calibration import market_blend as mb

    cov_float = np.repeat(covered.astype(float), fit_t.n)
    placebos, donor_ok = [], np.ones(len(fit_t.snaps), bool)
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(fit_t, c_fit, seed, donors[seed])
        dcov = cov_float[donors[seed][0]]
        donor_ok &= np.bincount(fit_t.band_snap, weights=dcov, minlength=len(fit_t.snaps)) == fit_t.n
        placebos.append(pl)
    pop = mb.restrict_snap(fit_t, score_t, covered & donor_ok)
    band = pop[score_t.band_snap]
    m, e = score_t.p_market, score_t.y - score_t.p_market
    didx = np.searchsorted(scored, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    nd = len(scored)
    c = mb.restrict(fit_t, score_t, c_fit)
    sums_c = sw.date_sums((c - m)[band], e[band], didx[band], nd)
    sums_pl = [sw.date_sums((mb.restrict(fit_t, score_t, p) - m)[band], e[band], didx[band], nd) for p in placebos]
    p0 = sw.paired_delta(sums_c, sums_pl, counts)
    a_fit = c_fit[donors[sw.PLACEBO_SEEDS[0]][0]]
    sums_a = sw.date_sums((mb.restrict(fit_t, score_t, a_fit) - m)[band], e[band], didx[band], nd)
    return {"coverage": {"fit_snapshots": int(len(covered)), "fit_covered": int(covered.sum()),
                         "population_snapshots": int(pop.sum()), "population_dates": int((sums_c[0] > 0).sum()),
                         "score_snapshots": int(len(score_t.snaps))},
            "p0": {k: v for k, v in p0.items() if k != "rho_pl_by_seed"},
            "diagnostic_rho": float(mg._rho(*sums_a.sum(axis=1)))}


def row77_reproduction(replay_root, tapes_root, repo_root, row77_dir):
    """Control 2: rebuild the 07-16 table and reproduce row 77's printed P0 lines from its own arm vectors."""
    arms_path, rec_path = Path(row77_dir) / "arms.json", Path(row77_dir) / "receipt.json"
    for path, want_sha in ((arms_path, ROW77_ARMS_SHA256), (rec_path, ROW77_RECEIPT_SHA256)):
        if _sha(path) != want_sha:
            raise TorontoEcccError(f"{path} sha256 is not the pinned {want_sha}")
    arms = json.loads(arms_path.read_text(encoding="utf-8"))["c"]
    want = json.loads(rec_path.read_text(encoding="utf-8"))
    _, fit_t, score_t, _, scored, meta = build_tables(replay_root, tapes_root, repo_root, hours=ROW77_HOURS)
    score_dates = np.array(scored)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    checks = {"n_fit_snapshots": (int(len(fit_t.snaps)), want["n_fit_snapshots"]),
              "n_score_snapshots": (int(len(score_t.snaps)), want["n_score_snapshots"]),
              "n_scored_dates": (len(scored), want["scored_dates"][2])}
    stat_diffs, arms_out = {}, {}
    for a in ("A", "B"):
        c_fit, covered = inject_vectors(fit_t, {rk: v[a] for rk, v in arms.items() if v.get(a) is not None})
        got = vector_p0(fit_t, score_t, c_fit, covered, score_dates, counts, donors)
        exp = want["results"][a]
        arms_out[a] = got
        for k in ("fit_covered", "fit_snapshots", "population_snapshots", "population_dates", "score_snapshots"):
            checks[f"{a}.{k}"] = (got["coverage"][k], exp["coverage"][k])
        pairs = {"rho_c": (got["p0"]["rho_c"], exp["p0"]["rho_c"]),
                 "rho_pl_mean": (got["p0"]["rho_pl_mean"], exp["p0"]["rho_pl_mean"]),
                 "delta": (got["p0"]["delta"], exp["p0"]["delta"]),
                 "ci95_lo": (got["p0"]["ci95"][0], exp["p0"]["ci95"][0]),
                 "ci95_hi": (got["p0"]["ci95"][1], exp["p0"]["ci95"][1]),
                 "p_one_sided": (got["p0"]["p_one_sided"], exp["p0"]["p_one_sided"]),
                 "deranged_rho": (got["diagnostic_rho"], exp["diagnostic_c_deranged"]["rho"])}
        for k, (g, w) in pairs.items():
            ok = _close(g, w)
            stat_diffs[f"{a}.{k}"] = {"got": g, "expected": w,
                                      "abs_diff": None if g is None or w is None else abs(float(g) - float(w)),
                                      "ok": ok}
    counts_ok = all(g == w for g, w in checks.values())
    stats_ok = all(v["ok"] for v in stat_diffs.values())
    diffs = [v["abs_diff"] for v in stat_diffs.values() if v["abs_diff"] is not None]
    return {"verdict": "PASS" if counts_ok and stats_ok else "FAIL", "hours": list(ROW77_HOURS),
            "counts": {k: {"got": g, "expected": w, "ok": g == w} for k, (g, w) in checks.items()},
            "stats": stat_diffs, "max_abs_diff": max(diffs) if diffs else None,
            "tolerance": ROW77_TOL, "arms": arms_out, "table_meta": meta,
            "inputs": {"arms_json": ROW77_ARMS_SHA256, "receipt_json": ROW77_RECEIPT_SHA256}}


def synthetic_values(fit_t, labels, geo, seed=SYN_SEED):
    """SYN+ and SYN- values per fit snapshot: mu +/- (r + eps), r = Y - mu, eps ~ N(0, sd(r)^2)."""
    mu = geo["mu"]
    y = np.array([labels[d] for d in fit_t.snaps.date.astype(str)], float)
    r = y - mu
    sigma = float(np.std(r))
    eps = np.random.default_rng(seed).normal(0.0, sigma, len(r))
    return ({"SYN+": mu + (r + eps), "SYN-": mu - (r + eps)},
            {"sigma_r": sigma, "mean_r": float(np.mean(r)), "seed": seed, "n": int(len(r))})


def controls_only(*, out_dir, row77_dir, replay_root=DEFAULT_REPLAY, tapes_root=DEFAULT_TAPES, repo_root=_REPO,
                  allow_dirty=False):
    """Row 90 amendment 1: controls 1-3; writes ``toronto_eccc_p0_controls.json`` (never overwrites)."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb

    out = _fresh_out(out_dir)
    if mg.BLOCKS.get(W_BLOCK) != HOURS:
        raise TorontoEcccError("mr_gate.BLOCKS must carry the 07-12 block")
    snaps, fit_t, score_t, burn, scored, meta = build_tables(replay_root, tapes_root, repo_root)
    if set(fit_t.markets) != {MARKET}:
        raise TorontoEcccError("the population is Toronto only")
    feats = snaps[["row_key", "gem", "rc_gem", "city", "rc_city"]]
    values = candidate_values(fit_t.snaps, feats)
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(scored)
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    # control 1 on the real candidates (P0 recomputed only to obtain c_fit; reported against the first run)
    c1, real = {}, {}
    for cid, kind, sign, _, _ in CANDIDATES:
        res, vecs = sw.p0_candidate(cid, kind, sign, values[cid], fit_t, score_t, geo, counts, score_dates, donors)
        real[cid] = {"delta": res["p0"]["delta"], "rho_c": res["p0"]["rho_c"]}
        c1[cid] = (mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vecs["c_fit"])) if vecs is not None
                   else {"verdict": "FAIL", "reason": "untestable"})

    # control 3
    syn_vals, syn_meta = synthetic_values(fit_t, load_labels(repo_root), geo)
    syn, kept = {}, {}
    for cid in ("SYN+", "SYN-"):
        res, vecs = sw.p0_candidate(cid, "C", 1, syn_vals[cid], fit_t, score_t, geo, counts, score_dates, donors)
        res.pop("_rows", None)
        res.pop("placebo_meta", None)
        syn[cid] = res
        kept[cid] = vecs
    decide(syn, ["SYN+", "SYN-"])
    plus, minus = syn["SYN+"], syn["SYN-"]
    if kept["SYN+"] is not None:
        c1["SYN+"] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, kept["SYN+"]["c_fit"]))
        g = mg.gate_candidate("SYN+", W_BLOCK, fit_t, score_t, kept["SYN+"]["c_fit"], kept["SYN+"]["covered"],
                              p_placebo_fit=kept["SYN+"]["pl0_fit"])
        plus["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "rows": g["rows"],
                          "w": {"summary": g["w"]["summary"], "checks": g["w"]["checks"]}}
    else:
        c1["SYN+"] = {"verdict": "FAIL", "reason": "SYN+ untestable"}
    plus_ok = bool(plus.get("survive") and plus["p0"]["delta"] is not None and plus["p0"]["delta"] > 0
                   and c1["SYN+"]["verdict"] == "PASS" and plus.get("w_gate", {}).get("verdict") == "PASS (w)")
    minus_ok = bool(minus.get("testable") and minus["p0"]["delta"] is not None and minus["p0"]["delta"] < 0)
    control3 = {"verdict": "PASS" if plus_ok and minus_ok else "FAIL", "SYN+_pass": plus_ok, "SYN-_pass": minus_ok,
                "synthetic": syn_meta, "results": syn}
    control1 = {"verdict": "PASS" if all(v["verdict"] == "PASS" for v in c1.values()) else "FAIL", "by_candidate": c1}

    # control 2
    control2 = row77_reproduction(replay_root, tapes_root, repo_root, row77_dir)

    controls = {"1_w0_identity": control1, "2_row77_reproduction": control2, "3_synthetic_positive": control3}
    all_pass = all(c["verdict"] == "PASS" for c in controls.values())
    outcome = "ROW 90 KILL STANDS" if all_pass else "ROW 90 VOID"
    md = control2["max_abs_diff"]
    lines = [f"control 1 w=0 identity: {control1['verdict']}",
             f"control 2 row 77 reproduction (07-16): {control2['verdict']} (max |diff| "
             f"{'n/a' if md is None else format(md, '.2e')})",
             f"control 3 synthetic: {control3['verdict']} (SYN+ {sw.line_for(plus)}; SYN- {sw.line_for(minus)})",
             outcome]
    receipt = {"schema": SCHEMA + "/controls", "gate": GATE, "rule_sha256": RULE_SHA256,
               "amendment_1_sha256": AMENDMENT_1_SHA256, "ledger_row": LEDGER_ROW, "code": code,
               "module_sha256": {"toronto_eccc_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                                 "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
               "inputs": {"replay_sha256sums_sha256": REPLAY_SUMS_SHA256, "tape_sha256sums_sha256": TAPE_SUMS_SHA256,
                          "label_files": {rel: sha for rel, sha in LABEL_FILES}},
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "n_fit_snapshots": int(len(fit_t.snaps)),
                              "n_score_snapshots": int(len(score_t.snaps))},
               "table_meta": meta, "real_candidates_recomputed": real, "controls": controls, "outcome": outcome,
               "lines": lines}
    out.mkdir(parents=True, exist_ok=True)
    (out / "toronto_eccc_p0_controls.json").write_text(
        json.dumps(receipt, indent=1, sort_keys=True, default=mg._default), encoding="utf-8")
    return receipt
