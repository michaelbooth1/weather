"""Lane L47, K row 112, G2-P (label-parity companion to G2). Pre-registered in g2_freeze.md before any dev row.

G2-P is not a variant. It reuses G2 unchanged: the same frozen W/lam table, the same dev rows (07-12, target dates
2026-08-15..09-29), the same b_train (2021-25, WU era, as frozen) and the same bootstrap. The only change is the 2026
d series behind b_recent: d(m, u) = NBP 07Z mean - the venue-rule label, where the venue-rule label is the
half-up integer of the routine-METAR daily maximum (SPECI excluded; weather.backtesting.venue_rule_labels), instead
of the WU daily high. The mismatch (b_train from WU labels, b_recent from routine-METAR labels) is disclosed and
deliberately not fixed.

Subcommands:
  dseries26p  light, normal environment, only after the coordinator's go. Writes a file in G2's dseries26 schema
              (so `x36_trailing_g2 dev --d26 <file>` consumes it unchanged) from the IEM routine-only files
              fetched by C:/t/L47b/g2/metar_s/fetch_count_v1.py. Every raw file's sha256 is checked against its
              receipt first. Labels outside 2026-07-31..09-28 are refused.
  g1mbb       light. Training era only (G1's g1_rows.jsonl, 2021-25): pooled and per-hour dBrier under the
              date-clustered and the circular moving-block bootstrap (block 7 dates, 2000 draws, seed 20261024), the
              per-year breakdown and leave-one-year-out points. No dev row.
  mbbdev      heavy (loads the dev layout), via -Queue, after G2's dev run. Rebuilds G2's 07-12 covered dR exactly as
              x36_trailing_g2.score_dev does, checks that the date-clustered interval reproduces G2's to 1e-12, and
              adds the moving-block interval (same block, draws and seed).
  compare     light, after both dev runs and mbbdev. Per-date shift difference (G2-P minus G2) on identical row keys,
              dR_P with its interval, and the three-way verdict frozen in g2_freeze.md.
  mechanism   light, training era only (g1_rows.jsonl and G1's dseries). Per year: gain next to the season and
              row-level bias departures; Spearman (n = 5) and OLS slope of gain on departure; the dev prediction
              from a 2026 departure taken from cited X36-v5 figures (not from dev). Not a gate.
  mbbdev also reports the per-month (Aug, Sep) dR under both bootstraps; run it on the G2-P folder as well.
  dseries26L  light (Clarification 4). G2's 2026 d series rebuilt from the dev layout's labels.parquet
              settlement_high (WU), in G2's dseries26 schema, because the WS WU mirror stops at 2026-08-10.
  overlap     light. Exact-equality check of d between two dseries files on their common (m, d) keys (gate iii).

The MBB lives here, not in x36_trailing_g2.py, because any edit to that module changes its sha256 and its dev
subcommand then refuses the freeze table (load_freeze binds the table to the writing module's sha).
x36_trailing_g2.py is loaded by path after a sha256 check and never edited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
G2_SHA256 = "022565ccceba52eed4b617ca031425a81f40dd9d373b08a64ee751dae9e55679"
LABEL_SOURCE = "metar_routine_venue_rule_half_up"
IEM_ROUTINE = 3
BLOCK = 7
DRAWS = 2000
SEED = 20261024
KILL_LINE = -0.0005


class G2PError(RuntimeError):
    """The G2-P step cannot proceed honestly."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_g2():
    path = HERE / "x36_trailing_g2.py"
    if sha256_file(path) != G2_SHA256:
        raise G2PError("x36_trailing_g2.py sha256 mismatch")
    spec = importlib.util.spec_from_file_location("x36_trailing_g2", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["x36_trailing_g2"] = mod
    spec.loader.exec_module(mod)
    return mod


def venue_labels(text, spec, icao, date_ok):
    """{iso date: (venue integer, unit)} from one IEM routine-only CSV; dates failing date_ok are dropped."""
    from weather.backtesting import venue_rule_labels as vrl
    from weather.sources.daily_summary import native_bucket, row_unit

    reports = vrl.reports_from_csv(text, spec, icao, declared_report_type=IEM_ROUTINE)
    out = {}
    for local_date, row in vrl.venue_daily_labels(reports, spec).items():
        if not date_ok(local_date):
            continue
        out[local_date] = (native_bucket(row), row_unit(row))
    return out


def read_receipts(path):
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    by_station = {}
    for r in rows:
        if r["station"] in by_station:
            raise G2PError(f"duplicate receipt for {r['station']}")
        by_station[r["station"]] = r
    return by_station


def shift_differences(rows_g2, rows_p):
    """Per-date summary of shift(G2-P) - shift(G2) on identical (market, snapshot) keys."""
    a = {f"{r['market']}|{r['snapshot_id']}": r for r in rows_g2}
    b = {f"{r['market']}|{r['snapshot_id']}": r for r in rows_p}
    if set(a) != set(b):
        raise G2PError(f"row keys differ: {len(set(a) ^ set(b))} keys")
    per_date = defaultdict(list)
    for k, r in a.items():
        if (r["W"], r["lam"], r["hour"], r["target_date"]) != (b[k]["W"], b[k]["lam"], b[k]["hour"],
                                                                b[k]["target_date"]):
            raise G2PError(f"row {k} differs outside the shift")
        per_date[r["target_date"]].append(float(b[k]["shift"]) - float(r["shift"]))
    dates = {d: {"n": len(v), "mean": sum(v) / len(v), "max_abs": max(abs(x) for x in v)}
             for d, v in sorted(per_date.items())}
    allv = [x for v in per_date.values() for x in v]
    return {"rows": len(allv), "dates": len(dates), "mean": sum(allv) / len(allv),
            "mean_abs": sum(abs(x) for x in allv) / len(allv), "max_abs": max(abs(x) for x in allv),
            "rows_changed": sum(x != 0.0 for x in allv), "per_date": dates}


def three_way_verdict(point, upper_cluster, upper_mbb, p_point):
    """The three-way G2 verdict frozen in g2_freeze.md (replaces the earlier two-way verdict).

    PASS: UB < 0 under BOTH bootstraps AND G2-P point < 0.
    CONSISTENT: point < -0.0005 AND G2-P point < 0, UB not < 0 under both -> history-tier test, no serving claim.
    KILL: point >= -0.0005, or G2-P flips sign (point >= 0).
    Order: the G2-P sign flip kills first; PASS is tested before the point line (an overlap the coordinator is asked
    to confirm: UB < 0 under both with -0.0005 <= point is PASS here).
    """
    if not p_point < 0:
        return "KILL"
    if upper_cluster < 0 and upper_mbb < 0:
        return "PASS"
    if point < KILL_LINE:
        return "CONSISTENT"
    return "KILL"


def cluster_date_weights(dates, draws=DRAWS, seed=SEED):
    """Date-clustered multinomial weights per cell, identical to r0_ols_floor_challenger._date_weights."""
    import numpy as np

    _, di = np.unique(np.asarray(dates), return_inverse=True)
    d = di.max() + 1
    rng = np.random.default_rng(seed)
    return rng.multinomial(d, np.full(d, 1 / d), size=draws)[:, di]


def mbb_date_weights(dates, block=BLOCK, draws=DRAWS, seed=SEED):
    """Circular moving-block bootstrap weights per cell.

    The distinct dates, in calendar order, form one circular sequence of n dates. Each draw concatenates
    ceil(n / block) blocks of `block` consecutive dates (start uniform on 0..n-1, wrapping), truncated to n dates; a
    cell's weight is the number of times its date was drawn. Same interface as cluster_date_weights.
    """
    import numpy as np

    _, di = np.unique(np.asarray(dates), return_inverse=True)
    n = int(di.max()) + 1
    nb = -(-n // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(draws, nb))
    idx = ((starts[:, :, None] + np.arange(block)) % n).reshape(draws, -1)[:, :n]
    w = np.zeros((draws, n), dtype=np.int64)
    np.add.at(w, (np.repeat(np.arange(draws), n), idx.ravel()), 1)
    return w[:, di]


def ratio_ci(w, a, b):
    """Point sum(a)/sum(b) and the 95% percentile interval of (w @ a)/(w @ b), as dev_scorecard.ratio_interval."""
    import numpy as np

    a, b = np.asarray(a, float), np.asarray(b, float)
    num, den = w @ a, w @ b
    boot = np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)
    fin = boot[np.isfinite(boot)]
    return {"estimate": float(a.sum() / b.sum()), "ci95": [float(x) for x in np.quantile(fin, [.025, .975])],
            "valid_draws": int(len(fin))}


def g1_breakdown(rows):
    """G1 training-era dBrier (P3d_T - P3d_N_fix, mean per gate row): pooled and per hour under both bootstraps,
    per year (point, date-clustered CI, MBB CI) and leave-one-year-out points. Descriptive; no dev row."""
    import numpy as np

    rows = [r for r in rows if r["gate"]]
    out = {"n_rows": len(rows), "block": BLOCK, "draws": DRAWS, "seed": SEED, "groups": {}, "years": {},
           "leave_one_year_out": {}}

    def one(rs):
        # Per-date sums: identical to per-row weights (a row's weight is its date's), at draws x dates memory.
        sums, counts = defaultdict(float), defaultdict(int)
        for r in rs:
            sums[r["date"]] += r["P3d_T_brier"] - r["P3d_N_fix_brier"]
            counts[r["date"]] += 1
        ud = sorted(sums)
        a, b = np.array([sums[d] for d in ud]), np.array([counts[d] for d in ud], float)
        return {"n": len(rs), "n_dates": len(ud),
                "cluster": ratio_ci(cluster_date_weights(ud), a, b),
                "mbb": ratio_ci(mbb_date_weights(ud), a, b)}

    out["groups"]["pooled"] = one(rows)
    for h in sorted({r["hour"] for r in rows}):
        out["groups"][f"h{h:02d}"] = one([r for r in rows if r["hour"] == h])
    years = sorted({r["year"] for r in rows})
    for y in years:
        out["years"][str(y)] = one([r for r in rows if r["year"] == y])
        rest = [r for r in rows if r["year"] != y]
        out["leave_one_year_out"][str(y)] = float(np.mean([r["P3d_T_brier"] - r["P3d_N_fix_brier"] for r in rest]))
    return out


def cmd_dseries26p(a):
    g2 = load_g2()
    sys.path.insert(0, str(HERE))
    import x36_v5 as base
    from weather.backtesting import venue_rule_labels as vrl
    from weather.market.market_registry import spec_for_id

    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    if sha256_file(a.dev_corpus) != g2.DEV_CORPUS_SHA256:
        raise G2PError("dev NBM corpus sha mismatch")
    receipts = read_receipts(a.receipts)
    corpus, dropped = [], 0
    for line in Path(a.dev_corpus).read_text(encoding="utf-8").splitlines():
        d = g2.line_date(line)
        if d is None or not g2.label_date_ok(d):
            dropped += 1
            continue
        r = json.loads(line)
        if r["target_date"] != d or r.get("cycle") != "07":
            raise G2PError(f"unexpected corpus row {d} cycle {r.get('cycle')}")
        corpus.append(r)
    labels, files = {}, {}
    for market, icao in base.stations().items():
        rec = receipts.get(icao)
        if rec is None or rec["market"] != market:
            raise G2PError(f"no receipt for {market} {icao}")
        path = Path(a.metar_dir) / Path(rec["path"]).name
        if sha256_file(path) != rec["sha256"]:
            raise G2PError(f"raw METAR sha mismatch for {icao}")
        files[icao] = {"path": str(path), "sha256": rec["sha256"], "bytes": rec["bytes"], "url": rec["url"]}
        spec = spec_for_id(market)
        for d, lab in venue_labels(path.read_text(encoding="utf-8"), spec, icao, g2.label_date_ok).items():
            labels[(market, d)] = lab
    ps = base.pairs(corpus, labels)
    rows = sorted(({"m": p["m"], "d": p["d"], "x": p["x"]} for p in ps), key=lambda r: (r["m"], r["d"]))
    if len({(r["m"], r["d"]) for r in rows}) != len(rows):
        raise G2PError("duplicate d row")
    per_market = defaultdict(int)
    for r in rows:
        per_market[r["m"]] += 1
    res = {"schema": g2.SCHEMA + "/dseries26", "label_source": LABEL_SOURCE,
           "module_sha256": sha256_file(__file__), "g2_module_sha256": G2_SHA256,
           "base_module_sha256": sha256_file(base.__file__), "venue_module_sha256": sha256_file(vrl.__file__),
           "dev_corpus_sha256": g2.DEV_CORPUS_SHA256, "metar_files": files,
           "window": [g2.LABEL_FIRST.isoformat(), g2.LABEL_LAST.isoformat()], "corpus_lines_dropped_by_date": dropped,
           "n_corpus_rows": len(corpus), "n_labels": len(labels), "n_rows": len(rows),
           "per_market": dict(per_market), "rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, sort_keys=True), encoding="utf-8")
    print(json.dumps({"n_rows": len(rows), "per_market": dict(per_market), "dropped": dropped,
                      "sha256": sha256_file(out)}), flush=True)
    return 0


# ------------------------------------------------------------------ dseries26L (Clarification 4, master ruling B)
# The WS WU daily mirror stops at 2026-08-10 (paused 2026-08-12, owner two-host decision), so G2's own dseries26 has
# only 10 dates per market. dseries26L rebuilds G2's 2026 d series from the same WU settlement highs carried by the
# dev layout's labels.parquet (settlement_high), in G2's dseries26 schema, for `x36_trailing_g2 dev --d26 <file>`.
# x36_trailing_g2.py (022565cc) and the freeze table (eb73fc04) are untouched.

LAYOUT_LABELS_SHA256 = "1ea636e9e655670012bc3b5d5ef02aec9feda65cc7839434631bbb09c65f067e"
LAYOUT_LABEL_SOURCE = "layout_labels_settlement_high_wu"
OVERLAP_TOL = 1e-12


def layout_daily_highs(records, markets, date_ok, unit_of):
    """{(market, iso date): (high, unit)} from (market, date, settlement_high) records, one value per market-date.

    Dates failing date_ok are dropped before the value is looked at. Refuses: a market outside ``markets``, a
    non-F market, a non-finite or non-integer high, a high outside -60..140 F, and a high that is not constant
    within its market-date (the layout repeats it on every snapshot row)."""
    import math

    out = {}
    for market, day, value in records:
        day = str(day)[:10]
        if not date_ok(day):
            continue
        if market not in markets:
            raise G2PError(f"layout market not in the station set: {market}")
        unit = unit_of(market)
        if unit != "F":
            raise G2PError(f"non-F market {market}: {unit}")
        v = float(value)
        if not math.isfinite(v) or v != round(v):
            raise G2PError(f"non-integer settlement_high {market} {day}: {value!r}")
        if not -60.0 <= v <= 140.0:
            raise G2PError(f"implausible F settlement_high {market} {day}: {v}")
        prev = out.get((market, day))
        if prev is not None and prev[0] != v:
            raise G2PError(f"settlement_high not constant within {market} {day}: {prev[0]} vs {v}")
        out[(market, day)] = (v, unit)
    return out


def overlap_check(rows_a, rows_b, tol=OVERLAP_TOL):
    """Exact-equality check of d on the (m, d) keys present in both dseries files."""
    a = {(r["m"], r["d"]): float(r["x"]) for r in rows_a}
    b = {(r["m"], r["d"]): float(r["x"]) for r in rows_b}
    keys = sorted(set(a) & set(b))
    diffs = [abs(a[k] - b[k]) for k in keys]
    bad = [{"m": k[0], "d": k[1], "a": a[k], "b": b[k]} for k, x in zip(keys, diffs) if x > tol]
    return {"n_common": len(keys), "dates": sorted({k[1] for k in keys}), "max_abs_diff": max(diffs) if diffs else None,
            "n_mismatch": len(bad), "mismatches": bad[:50], "only_a": len(set(a) - set(b)),
            "only_b": len(set(b) - set(a)), "tol": tol, "pass": bool(keys) and not bad}


def cmd_dseries26L(a):
    g2 = load_g2()
    sys.path.insert(0, str(HERE))
    import x36_v5 as base
    import pandas as pd
    from weather.market.market_registry import spec_for_id

    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    if sha256_file(a.dev_corpus) != g2.DEV_CORPUS_SHA256:
        raise G2PError("dev NBM corpus sha mismatch")
    if sha256_file(a.labels) != LAYOUT_LABELS_SHA256:
        raise G2PError("layout labels.parquet sha mismatch")
    corpus, dropped = [], 0
    for line in Path(a.dev_corpus).read_text(encoding="utf-8").splitlines():
        d = g2.line_date(line)
        if d is None or not g2.label_date_ok(d):
            dropped += 1
            continue
        r = json.loads(line)
        if r["target_date"] != d or r.get("cycle") != "07":
            raise G2PError(f"unexpected corpus row {d} cycle {r.get('cycle')}")
        corpus.append(r)
    frame = pd.read_parquet(a.labels, columns=["date", "market"])
    keep = frame["date"].astype(str).str[:10].map(g2.label_date_ok)
    highs = pd.read_parquet(a.labels, columns=["settlement_high"])["settlement_high"][keep.to_numpy()]
    records = zip(frame["market"][keep], frame["date"][keep], highs)
    labels = layout_daily_highs(records, set(base.stations()), g2.label_date_ok, lambda m: spec_for_id(m).unit)
    ps = base.pairs(corpus, labels)
    rows = sorted(({"m": p["m"], "d": p["d"], "x": p["x"]} for p in ps), key=lambda r: (r["m"], r["d"]))
    if len({(r["m"], r["d"]) for r in rows}) != len(rows):
        raise G2PError("duplicate d row")
    per_market = defaultdict(int)
    for r in rows:
        per_market[r["m"]] += 1
    res = {"schema": g2.SCHEMA + "/dseries26", "label_source": LAYOUT_LABEL_SOURCE,
           "module_sha256": sha256_file(__file__), "g2_module_sha256": G2_SHA256,
           "base_module_sha256": sha256_file(base.__file__), "dev_corpus_sha256": g2.DEV_CORPUS_SHA256,
           "labels_path": str(a.labels), "labels_sha256": LAYOUT_LABELS_SHA256,
           "label_dates": sorted({d for (_, d) in labels}),
           "window": [g2.LABEL_FIRST.isoformat(), g2.LABEL_LAST.isoformat()], "corpus_lines_dropped_by_date": dropped,
           "n_corpus_rows": len(corpus), "n_labels": len(labels), "n_rows": len(rows),
           "per_market": dict(per_market), "rows": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, sort_keys=True), encoding="utf-8")
    print(json.dumps({"n_rows": len(rows), "per_market": dict(per_market), "dropped": dropped,
                      "n_label_dates": len(res["label_dates"]), "sha256": sha256_file(out)}), flush=True)
    return 0


def cmd_overlap(a):
    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    ra = json.loads(Path(a.a).read_text(encoding="utf-8"))
    rb = json.loads(Path(a.b).read_text(encoding="utf-8"))
    res = overlap_check(ra["rows"], rb["rows"])
    res.update({"a": str(a.a), "a_sha256": sha256_file(a.a), "b": str(a.b), "b_sha256": sha256_file(a.b),
                "module_sha256": sha256_file(__file__)})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("n_common", "max_abs_diff", "n_mismatch", "only_a", "only_b", "pass")}),
          flush=True)
    return 0 if res["pass"] else 4


def _jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def month_groups(cell_dates, diff, mkt, cluster_w):
    """Per-month (Aug, Sep) dR on the same cells: point, date-clustered 95% (the run's weights restricted to the
    month) and circular MBB 95% (block 7 over that month's dates). Pre-registered as the input a CONSISTENT result
    needs before promotion to the history-tier test."""
    import numpy as np

    dates = np.asarray(cell_dates)
    diff, mkt = np.asarray(diff, float), np.asarray(mkt, float)
    out = {}
    for name, mm in (("aug", "-08-"), ("sep", "-09-")):
        sel = np.flatnonzero(np.char.find(dates.astype(str), mm) == 4)
        if not len(sel):
            out[name] = None
            continue
        out[name] = {"n_cells": int(len(sel)), "n_dates": int(len(set(dates[sel].tolist()))),
                     "cluster": ratio_ci(np.asarray(cluster_w)[:, sel], diff[sel], mkt[sel]),
                     "mbb": ratio_ci(mbb_date_weights(dates[sel].tolist()), diff[sel], mkt[sel])}
    return out


def _ranks(x):
    """Average ranks (1-based), ties shared."""
    order = sorted(range(len(x)), key=lambda i: x[i])
    ranks = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def ols(x, y):
    """(slope, intercept) of y on x."""
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if not sxx:
        return float("nan"), float("nan")
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sxx
    return slope, my - slope * mx


def mechanism_table(rows, series):
    """Ex-ante mechanism check, training era only. Per year Y (2021-25):
    gain = mean per gate row of P3d_T - P3d_N_fix Brier (G1 out-of-fold);
    season departure per market = mean of d over Y's Aug 1..Sep 29 minus the mean over the other four years (the
    nested baseline G1 uses); pooled_signed = mean over markets, pooled_abs = |pooled_signed|, market_abs = mean of
    |departure| over markets;
    row level, from the gate rows: mean |shift| (applied, F) and mean |shift / lam| over lam > 0 rows (the clipped
    trailing departure |b_recent - b_train|)."""
    rows = [r for r in rows if r["gate"]]
    years = sorted({r["year"] for r in rows})
    by_my = defaultdict(list)
    for m, pts in series.items():
        for d, x in pts:
            by_my[(m, int(d[:4]))].append(x)
    markets = sorted(series)
    table = {}
    for y in years:
        deps = []
        for m in markets:
            cur = by_my[(m, y)]
            rest = [x for yy in years if yy != y for x in by_my[(m, yy)]]
            deps.append(sum(cur) / len(cur) - sum(rest) / len(rest))
        yr = [r for r in rows if r["year"] == y]
        lam_pos = [r for r in yr if r["lam"] > 0]
        signed = sum(deps) / len(deps)
        table[str(y)] = {"gain": sum(r["P3d_T_brier"] - r["P3d_N_fix_brier"] for r in yr) / len(yr),
                         "pooled_signed_departure": signed, "pooled_abs_departure": abs(signed),
                         "market_abs_departure": sum(abs(v) for v in deps) / len(deps),
                         "row_mean_abs_shift": sum(abs(r["shift"]) for r in yr) / len(yr),
                         "row_mean_abs_departure": (sum(abs(r["shift"] / r["lam"]) for r in lam_pos) / len(lam_pos)
                                                    if lam_pos else None),
                         "n_rows": len(yr)}
    gains = [table[str(y)]["gain"] for y in years]
    fits = {}
    for key in ("pooled_abs_departure", "market_abs_departure", "row_mean_abs_departure", "row_mean_abs_shift"):
        xs = [table[str(y)][key] for y in years]
        if any(x is None for x in xs):
            fits[key] = None
            continue
        slope, icpt = ols(xs, gains)
        fits[key] = {"spearman": spearman(xs, gains), "ols_slope": slope, "ols_intercept": icpt, "n": len(years)}
    return {"years": table, "fits": fits}


def mechanism_prediction(fits, departure_2026, key="pooled_abs_departure"):
    f = fits[key]
    return {"regressor": key, "departure_2026": departure_2026,
            "predicted_gain": f["ols_intercept"] + f["ols_slope"] * departure_2026}


def mbb_dev(layout, base_path, arm_path):
    """07-12 dR (P3d_T - P3d_N_fix over market Brier) on G2's covered scope, built exactly as G2's score_dev, under
    the date-clustered weights (must reproduce G2's interval) and the circular moving-block bootstrap."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    g2 = load_g2()
    start_d, end_d = data.check_range(g2.DEV_FIRST.isoformat(), g2.DEV_LAST.isoformat())
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    if not scored or scored[0] < g2.DEV_FIRST.isoformat() or scored[-1] > g2.DEV_LAST.isoformat():
        raise G2PError(f"scored population {scored[:1]}..{scored[-1:]} outside the dev window")
    table = sc.Table(lay, scored)
    market_b = table.brier(table.p_market)
    vec = {}
    for name, path in ((g2.BASE, base_path), (g2.ARM, arm_path)):
        frame, _ = data.distribution_predictions(data.CandidateSpec("distributions", str(path), "2025-12-31", False),
                                                 lay, folds)
        vec[name] = l3._vector(table, frame)
    bb, bt = table.brier(vec[g2.BASE][0]), table.brier(vec[g2.ARM][0])
    cov = vec[g2.BASE][1] & vec[g2.ARM][1]
    mask = cov & (table.local_hour >= 7) & (table.local_hour <= 12)
    idx, c = table.cells(bt, mask)
    _, r_ = table.cells(bb, mask)
    _, m = table.cells(market_b, mask)
    cluster_w = l3._date_weights([k[0] for k in table.keys], g2.DRAWS, g2.SEED)
    cell_dates = [table.keys[i][0] for i in idx]
    months = month_groups(cell_dates, c - r_, m, cluster_w[:, idx])
    return {"n_market_days": int(len(idx)), "n_dates": len(set(cell_dates)),
            "dates": [min(cell_dates), max(cell_dates)],
            "months": months,
            "cluster": sc.ratio_interval(cluster_w[:, idx], c - r_, m),
            "mbb": ratio_ci(mbb_date_weights(cell_dates), c - r_, m)}


def cmd_mbbdev(a):
    g2 = load_g2()
    g1 = g2.load_g1()
    g1.bind_run_env(a.run_env)
    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    run = Path(a.g2_out)
    g2r = json.loads((run / "g2_result.json").read_text(encoding="utf-8"))
    if g2r.get("stopped_at") or "verdict" not in g2r:
        raise G2PError("the G2 run stopped before its gate")
    res = mbb_dev(a.layout, run / f"dev_{g2.BASE}.jsonl", run / f"dev_{g2.ARM}.jsonl")
    v = g2r["verdict"]
    reproduced = (abs(res["cluster"]["estimate"] - v["point"]) <= 1e-12
                  and all(abs(x - y) <= 1e-12 for x, y in zip(res["cluster"]["ci95"], v["ci95"])))
    res.update({"schema": "l47_x36_trailing_g2p/1/mbb_dev", "module_sha256": sha256_file(__file__),
                "g2_out": str(run), "g2_result_sha256": sha256_file(run / "g2_result.json"),
                "cluster_reproduces_g2": reproduced, "block": BLOCK, "draws": DRAWS, "seed": SEED})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"cluster_reproduces_g2": reproduced, "mbb": res["mbb"], "sha256": sha256_file(out)}),
          flush=True)
    return 0 if reproduced else 3


def cmd_g1mbb(a):
    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    g1r = json.loads(Path(a.g1_result).read_text(encoding="utf-8"))
    res = g1_breakdown(_jsonl(a.g1_rows))
    pooled = g1r["summary"]["pooled|brier"]
    if abs(res["groups"]["pooled"]["cluster"]["estimate"] - pooled["estimate"]) > 1e-12:
        raise G2PError("pooled point does not reproduce G1")
    res.update({"schema": "l47_x36_trailing_g2p/1/g1_mbb", "module_sha256": sha256_file(__file__),
                "g1_rows_sha256": sha256_file(a.g1_rows), "g1_result_sha256": sha256_file(a.g1_result),
                "g1_reported_pooled": pooled})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"sha256": sha256_file(out)}), flush=True)
    return 0


def cmd_mechanism(a):
    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    g1 = load_g2().load_g1()
    series, _ = g1.load_series(a.dseries)
    res = mechanism_table(_jsonl(a.g1_rows), series)
    res.update({"schema": "l47_x36_trailing_g2p/1/mechanism", "module_sha256": sha256_file(__file__),
                "g1_rows_sha256": sha256_file(a.g1_rows), "dseries_sha256": sha256_file(a.dseries),
                "prediction": mechanism_prediction(res["fits"], float(a.departure_2026)),
                "prediction_note": "stated before dev opens; not a gate"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"sha256": sha256_file(out)}), flush=True)
    return 0


SUPERSEDED_TWO_WAY_KEYS = ("rule", "pass", "verdict")


def report_gate(gate):
    """A dev run's gate block for compare's report: the statistics, with the G2 module's superseded two-way fields
    (x36_trailing_g2.gate: "PASS only if the dev dR 95% upper bound < 0", else "KILL"; superseded by C1.6) moved under
    ``superseded_two_way`` so the report carries only one verdict, three_way_verdict."""
    out = {k: v for k, v in gate.items() if k not in SUPERSEDED_TWO_WAY_KEYS}
    out["superseded_two_way"] = {k: gate[k] for k in SUPERSEDED_TWO_WAY_KEYS if k in gate}
    return out


def cmd_compare(a):
    out = Path(a.out)
    if out.exists():
        raise G2PError(f"refusing to overwrite {out}")
    g2r = json.loads((Path(a.g2_out) / "g2_result.json").read_text(encoding="utf-8"))
    g2p = json.loads((Path(a.g2p_out) / "g2_result.json").read_text(encoding="utf-8"))
    mbb = json.loads(Path(a.mbb).read_text(encoding="utf-8"))
    for k in ("module_sha256", "freeze"):
        if g2r.get(k) != g2p.get(k):
            raise G2PError(f"G2 and G2-P runs differ in {k}")
    if g2r.get("stopped_at") or g2p.get("stopped_at") or "verdict" not in g2r or "verdict" not in g2p:
        raise G2PError("a dev run stopped before its gate; no comparison")
    if not mbb.get("cluster_reproduces_g2") or mbb.get("g2_result_sha256") != sha256_file(
            Path(a.g2_out) / "g2_result.json"):
        raise G2PError("the MBB file is not for this G2 run")
    diff = shift_differences(_jsonl(Path(a.g2_out) / "g2_rows.jsonl"), _jsonl(Path(a.g2p_out) / "g2_rows.jsonl"))
    gate_g2, gate_p = g2r["verdict"], g2p["verdict"]
    verdict = three_way_verdict(gate_g2["point"], gate_g2["upper"], mbb["mbb"]["ci95"][1], gate_p["point"])
    res = {"schema": "l47_x36_trailing_g2p/1/compare", "module_sha256": sha256_file(__file__),
           "g2_d26_sha256": g2r["inputs"]["d26_sha256"], "g2p_d26_sha256": g2p["inputs"]["d26_sha256"],
           "shift_difference_g2p_minus_g2": diff, "g2_gate": report_gate(gate_g2), "g2_mbb": mbb["mbb"],
           "g2p_gate": report_gate(gate_p), "dR_P": {"point": gate_p["point"], "ci95": gate_p["ci95"]},
           "three_way_verdict": verdict, "verdict_rule": "three_way_verdict (g2_freeze.md C1.6)"}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"three_way_verdict": verdict, "sha256": sha256_file(out)}), flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="x36_trailing_g2p")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dseries26p")
    for k in ("--dev-corpus", "--metar-dir", "--receipts", "--out"):
        d.add_argument(k, required=True)
    g = sub.add_parser("g1mbb")
    for k in ("--g1-rows", "--g1-result", "--out"):
        g.add_argument(k, required=True)
    b = sub.add_parser("mbbdev")
    for k in ("--run-env", "--layout", "--g2-out", "--out"):
        b.add_argument(k, required=True)
    c = sub.add_parser("compare")
    for k in ("--g2-out", "--g2p-out", "--mbb", "--out"):
        c.add_argument(k, required=True)
    k = sub.add_parser("mechanism")
    for name in ("--g1-rows", "--dseries", "--departure-2026", "--out"):
        k.add_argument(name, required=True)
    dl = sub.add_parser("dseries26L")
    for name in ("--dev-corpus", "--labels", "--out"):
        dl.add_argument(name, required=True)
    ov = sub.add_parser("overlap")
    for name in ("--a", "--b", "--out"):
        ov.add_argument(name, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "dseries26L":
        return cmd_dseries26L(a)
    if a.cmd == "overlap":
        return cmd_overlap(a)
    if a.cmd == "mechanism":
        return cmd_mechanism(a)
    return {"dseries26p": cmd_dseries26p, "g1mbb": cmd_g1mbb, "mbbdev": cmd_mbbdev, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
