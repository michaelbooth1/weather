"""Lane L47, ledger C row 111: X36's own reopen test on NBM v5.0 (raw NBP 07Z mean minus WU high).

Rule: docs/research/x36-v5-reopen-2026-11-01/rule_x36_v5.md (frozen before any label read).
Window 2026-01-01..2026-05-26 only; every entry point refuses a 2026 date outside it (sealed panel
05-27..07-30, dev after). Training-era context reads L9's 2021-25 corpus (history) only.

Subcommands (all light; run directly with the venv python, sha recorded first):
  dates   write the target-date list for the L9 fetcher
  corpus  parse fetched NBP station blocks into corpus rows (parser v2), refusing out-of-window dates
  count   rule 16: inputs and label availability per market x month (+ version); no label values summarised
  fit     the rule's statistics (refuses unless count passed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

FIRST = date(2026, 1, 1)
LAST = date(2026, 5, 26)
V5_FIRST = date(2026, 5, 6)
SEED = 20261024
DRAWS = 2000
TRAIN_YEARS = (2021, 2022, 2023, 2024, 2025)
SCHEMA = "l47_x36_v5/1"


class X36Error(RuntimeError):
    pass


def in_window(day):
    return FIRST <= day <= LAST


def require_window(day, what):
    if not in_window(day):
        raise X36Error(f"refusing {what} dated {day}: window is {FIRST}..{LAST}")


def stations():
    from weather.calibration.ols_floor_ladder import NBM_STATIONS

    return dict(NBM_STATIONS)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wu_path(repo, station):
    return Path(repo) / "data" / "wunderground" / station.lower() / "daily" / "daily_summary.csv"


# ------------------------------------------------------------------ dates / corpus

def cmd_dates(a):
    days, d = [], FIRST
    while d <= LAST:
        days.append(d.isoformat())
        d += timedelta(days=1)
    Path(a.out).write_text("\n".join(days) + "\n", encoding="ascii")
    print(len(days))


def cmd_corpus(a):
    from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax

    rows = []
    for line in Path(a.blocks).read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        day = date.fromisoformat(rec["utc_date"])
        require_window(day, "NBP block")
        obj = rec.get("object")
        for market, station in stations().items():
            base = {"market_id": market, "station_id": station, "target_date": day.isoformat(),
                    "cycle": rec["cycle"], "key": rec["key"],
                    "last_modified": obj and obj["last_modified"], "etag": obj and obj["etag"]}
            block = (rec.get("stations") or {}).get(station)
            if not obj or not block:
                rows.append({**base, "available": False,
                             "reason": "object_missing" if not obj else "station_missing"})
                continue
            p = parse_nbp_station_tmax(block["block"], station, day)
            rows.append({**base, "available": bool(p["available"]), "reason": p.get("reason"),
                         "issued_at": p.get("issued_at"), "valid_time_utc": p.get("valid_time_utc"),
                         "mean": p.get("mean_native"), "sd": p.get("stddev_native"),
                         "parser_version": p.get("parser_version"),
                         "product_version": p.get("product_version"),
                         "block_sha256": hashlib.sha256(block["block"].encode()).hexdigest()})
    rows.sort(key=lambda r: (r["market_id"], r["target_date"], r["cycle"]))
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    out = Path(a.out)
    if out.exists():
        raise X36Error(f"refusing to overwrite {out}")
    out.write_bytes(body)
    print(json.dumps({"rows": len(rows), "sha256": hashlib.sha256(body).hexdigest()}))


# ------------------------------------------------------------------ labels

def load_labels(repo, years_ok, date_ok):
    """{(market, iso date): (native_high or None, unit)} for dates passing date_ok; filters before reading values."""
    from weather.backtesting.venue_rule_labels import read_wu_rows
    from weather.sources.daily_summary import native_high, row_unit

    out = {}
    for market, station in stations().items():
        rows = read_wu_rows(wu_path(repo, station))
        for local_date in rows:
            try:
                day = date.fromisoformat(local_date)
            except ValueError:
                continue
            if day.year not in years_ok or not date_ok(day):
                continue
            row = rows[local_date]
            out[(market, local_date)] = (native_high(row), row_unit(row))
    return out


def window_labels(repo):
    labels = load_labels(repo, {2026}, in_window)
    for (_, d) in labels:
        require_window(date.fromisoformat(d), "label")
    return labels


def load_corpus(path, check_window):
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        d = date.fromisoformat(r["target_date"])
        if check_window:
            require_window(d, "corpus row")
        elif d.year not in TRAIN_YEARS:
            raise X36Error(f"training-era corpus row outside 2021-25: {d}")
    return rows


def version_block(r):
    return f"v{r['product_version']}" if r.get("product_version") else "unknown"


# ------------------------------------------------------------------ count

def cmd_count(a):
    corpus = load_corpus(a.corpus, True)
    labels = window_labels(a.repo)
    cells = defaultdict(lambda: defaultdict(int))
    reasons = defaultdict(int)
    units = defaultdict(int)
    per_market = defaultdict(lambda: defaultdict(int))
    for r in corpus:
        m, d = r["market_id"], r["target_date"]
        key = f"{m}|{d[:7]}|{version_block(r) if r['available'] else 'na'}"
        c = cells[key]
        c["target_dates"] += 1
        c["nbp_available"] += int(bool(r["available"]) and r.get("mean") is not None)
        if not r["available"]:
            reasons[r.get("reason") or "unknown"] += 1
        lab = labels.get((m, d))
        has_label = lab is not None and lab[0] is not None
        if lab is not None:
            units[lab[1]] += 1
        matched = int(has_label and bool(r["available"]) and r.get("mean") is not None)
        c["wu_label_present"] += int(has_label)
        c["matched"] += matched
        per_market[m]["target_dates"] += 1
        per_market[m]["wu_label_present"] += int(has_label)
        per_market[m]["matched"] += matched
    n_dates = (LAST - FIRST).days + 1
    pm = {m: {"target_dates": v["target_dates"], "wu_label_present": v["wu_label_present"],
              "matched": v["matched"], "label_fraction": v["wu_label_present"] / n_dates}
          for m, v in per_market.items()}
    pooled = sum(v["wu_label_present"] for v in per_market.values()) / (n_dates * len(stations()))
    ok = bool(pm) and all(v["label_fraction"] >= 0.80 for v in pm.values()) and pooled >= 0.80
    result = {"schema": SCHEMA, "step": "count", "window": [str(FIRST), str(LAST)],
              "corpus": str(a.corpus), "corpus_sha256": sha256_file(a.corpus),
              "module_sha256": sha256_file(__file__), "cells": {k: dict(v) for k, v in sorted(cells.items())},
              "per_market": pm, "pooled_label_fraction": pooled, "nbp_missing_reasons": dict(reasons),
              "label_units": dict(units), "count_pass": ok and set(units) <= {"F"}}
    Path(a.out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"count_pass": result["count_pass"], "pooled_label_fraction": pooled,
                      "label_units": dict(units), "nbp_missing_reasons": dict(reasons)}))


# ------------------------------------------------------------------ fit

def boot(values, dates, draws=DRAWS, seed=SEED):
    """Mean with a date-clustered 95% percentile interval."""
    import numpy as np

    values = np.asarray(values, float)
    if len(values) == 0:
        return {"n": 0}
    uniq, inv = np.unique(np.asarray(dates), return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    w = np.zeros((draws, len(uniq)))
    for i in range(draws):
        w[i] = np.bincount(idx[i], minlength=len(uniq))
    means = (w @ sums) / (w @ cnts)
    return {"n": int(len(values)), "n_dates": int(len(uniq)), "mean": float(values.mean()),
            "lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5)),
            "mean_abs": float(np.abs(values).mean()), "sd": float(values.std(ddof=1)) if len(values) > 1 else None}


def pairs(corpus, labels):
    out = []
    for r in corpus:
        if not r["available"] or r.get("mean") is None:
            continue
        lab = labels.get((r["market_id"], r["target_date"]))
        if lab is None or lab[0] is None:
            continue
        if lab[1] != "F":
            raise X36Error(f"non-F label for {r['market_id']} {r['target_date']}: {lab[1]}")
        out.append({"m": r["market_id"], "d": r["target_date"], "v": version_block(r),
                    "x": float(r["mean"]) - float(lab[0])})
    return out


def group(ps, keyf):
    g = defaultdict(list)
    for p in ps:
        g[keyf(p)].append(p)
    return {k: boot([p["x"] for p in v], [p["d"] for p in v]) for k, v in sorted(g.items())}


def season(d):
    m = int(d[5:7])
    return "aug_sep" if m in (8, 9) else "oct_dec"


def cmd_fit(a):
    count = json.loads(Path(a.count).read_text(encoding="utf-8"))
    if not count.get("count_pass") or count.get("corpus_sha256") != sha256_file(a.corpus):
        raise X36Error("count did not pass, or the corpus changed since the count; refusing")
    ps = pairs(load_corpus(a.corpus, True), window_labels(a.repo))
    may = [p for p in ps if p["d"][5:7] == "05"]
    res = {"schema": SCHEMA, "step": "fit", "corpus_sha256": count["corpus_sha256"],
           "module_sha256": sha256_file(__file__), "n_pairs": len(ps),
           "primary_per_market": group(ps, lambda p: p["m"]),
           "pooled": boot([p["x"] for p in ps], [p["d"] for p in ps]),
           "per_market_month": group(ps, lambda p: f"{p['m']}|{p['d'][:7]}"),
           "per_market_version": group(ps, lambda p: f"{p['m']}|{p['v']}"),
           "pooled_version": group(ps, lambda p: p["v"]),
           "pooled_month": group(ps, lambda p: p["d"][:7]),
           "may_by_version": group(may, lambda p: f"{p['m']}|{p['v']}"),
           "may_pooled_by_version": group(may, lambda p: p["v"])}
    # within-May contrast, descriptive (difference of means; interval from independent date bootstraps)
    contrast = {}
    for key in sorted({p["m"] for p in may}) + ["pooled"]:
        sel = may if key == "pooled" else [p for p in may if p["m"] == key]
        a5 = [p for p in sel if p["v"] == "v5.0"]
        a4 = [p for p in sel if p["v"] != "v5.0"]
        if a5 and a4:
            contrast[key] = {"v5_minus_v43": (sum(p["x"] for p in a5) / len(a5)) - (sum(p["x"] for p in a4) / len(a4)),
                             "n_v5": len(a5), "n_v43": len(a4)}
    res["may_contrast_v5_minus_v43"] = contrast
    if a.train_corpus:
        train = load_corpus(a.train_corpus, False)
        tl = load_labels(a.repo, set(TRAIN_YEARS), lambda d: True)
        tp = pairs(train, tl)
        res["training_era_context"] = {"corpus_sha256": sha256_file(a.train_corpus), "n_pairs": len(tp),
                                       "per_market_season": group(tp, lambda p: f"{p['m']}|{season(p['d'])}"),
                                       "per_market_version": group(tp, lambda p: f"{p['m']}|{p['v']}"),
                                       "per_market": group(tp, lambda p: p["m"])}
    prim = res["primary_per_market"]
    hits = [m for m, s in prim.items() if s.get("n") and abs(s["mean"]) > 1.0 and (s["lo"] > 0 or s["hi"] < 0)]
    res["decision"] = {"reopen": bool(hits), "markets_beyond_1F_ci_excl_0": hits}
    out = Path(a.out)
    if out.exists():
        raise X36Error(f"refusing to overwrite {out}")
    out.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(res["decision"]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="x36_v5")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("dates"); s.add_argument("--out", required=True); s.set_defaults(f=cmd_dates)
    s = sub.add_parser("corpus"); s.add_argument("--blocks", required=True); s.add_argument("--out", required=True)
    s.set_defaults(f=cmd_corpus)
    s = sub.add_parser("count"); s.add_argument("--corpus", required=True); s.add_argument("--repo", required=True)
    s.add_argument("--out", required=True); s.set_defaults(f=cmd_count)
    s = sub.add_parser("fit"); s.add_argument("--corpus", required=True); s.add_argument("--repo", required=True)
    s.add_argument("--count", required=True); s.add_argument("--train-corpus"); s.add_argument("--out", required=True)
    s.set_defaults(f=cmd_fit)
    a = ap.parse_args(argv)
    a.f(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
