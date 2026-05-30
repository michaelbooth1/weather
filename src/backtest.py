"""Settlement-scored backtest: score the model AND the market against the
realized WU settlement for each captured market day.

This answers the question model calibration alone cannot: does the model have
edge *over the market price*? It scores the recorded snapshot tapes (which hold
both the model probability and the market yes-price at each capture) against the
realized settlement bucket, and reports:

  * model vs market Brier / log loss (+ Brier skill score),
  * reliability (calibration) for model and market,
  * realized edge / P&L from trading the model's edge to resolution,
  * edge persistence per band.

Settlement is the crux. The market resolves on the WU CYYZ printed daily high, so
the realized bucket is taken from the day's maximum captured ``wu_history_high_c``
(half-up rounded), cross-checked against the local daily summary and overridable
on the command line. Disagreements are reported, not hidden.

CLI:
  python -m src.backtest [folder ...]
      [--snapshots-root data/snapshots]
      [--settle YYYY-MM-DD=BUCKET ...]   # force settlement for a date
      [--thresholds 0.05,0.10,0.15]
      [--out data/backtest/backtest_report.md]
"""
import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import date_from_event_slug

DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_DAILY_SUMMARY = Path("data") / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
DEFAULT_OUT = Path("data") / "backtest" / "backtest_report.md"
COMPLETE_DAY_MIN_ROWS = 18  # daily summary is trusted as settlement only when this full


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def resolve_outcome(kind, value, settlement_bucket):
    """Did this market band resolve YES (1) or NO (0) given the settlement bucket?"""
    if settlement_bucket is None or kind is None or value is None:
        return None
    value = int(value)
    settlement_bucket = int(settlement_bucket)
    if kind == "lte":      # "X C or below"
        return 1 if settlement_bucket <= value else 0
    if kind == "gte":      # "X C or higher"
        return 1 if settlement_bucket >= value else 0
    return 1 if settlement_bucket == value else 0  # exact "X C"


def brier(p, y):
    return (p - y) ** 2


def binary_log_loss(p, y):
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load_daily_summary(path):
    """date -> (bucket, row_count) from the WU daily summary, if present."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            bucket = row.get("max_temp_bucket_c")
            if not d or not bucket:
                continue
            try:
                index[d] = (int(float(bucket)), int(row.get("row_count") or 0))
            except (TypeError, ValueError):
                continue
    return index


def settlement_for_tape(df, target_date, daily_index, overrides):
    """Return (bucket, source, note). Precedence: explicit override > complete
    daily summary > day's max captured wu_history_high_c."""
    iso = target_date.isoformat() if target_date else None
    snapshot_high = None
    if "wu_history_high_c" in df:
        snapshot_high = round_half_up(pd.to_numeric(df["wu_history_high_c"], errors="coerce").max())
    summary = daily_index.get(iso)

    note_bits = []
    if summary is not None and snapshot_high is not None and summary[0] != snapshot_high:
        note_bits.append(
            f"daily_summary={summary[0]} (rows={summary[1]}) disagrees with snapshot high={snapshot_high}")

    if iso in overrides:
        return overrides[iso], "override", "; ".join(note_bits) or "manual override"
    if summary is not None and summary[1] >= COMPLETE_DAY_MIN_ROWS:
        return summary[0], "daily_summary", "; ".join(note_bits)
    if snapshot_high is not None:
        reason = "snapshot wu_history_high (daily summary missing/incomplete)"
        return snapshot_high, "snapshot_high", "; ".join(note_bits) or reason
    if summary is not None:
        return summary[0], "daily_summary(sparse)", "; ".join(note_bits)
    return None, "none", "no settlement available"


def score_rows(rows):
    """Brier + log loss for model and market over a list of dicts with keys
    model_probability, market_yes, outcome."""
    n = len(rows)
    if not n:
        return None
    out = {
        "n": n,
        "model_brier": sum(brier(r["model_probability"], r["outcome"]) for r in rows) / n,
        "market_brier": sum(brier(r["market_yes"], r["outcome"]) for r in rows) / n,
        "model_logloss": sum(binary_log_loss(r["model_probability"], r["outcome"]) for r in rows) / n,
        "market_logloss": sum(binary_log_loss(r["market_yes"], r["outcome"]) for r in rows) / n,
        "base_rate": sum(r["outcome"] for r in rows) / n,
    }
    out["brier_skill_score"] = (
        1.0 - out["model_brier"] / out["market_brier"] if out["market_brier"] > 0 else 0.0
    )
    return out


def reliability(rows, prob_key, n_bins=5):
    """Reliability table: per confidence bin, mean predicted vs realized rate."""
    bins = [[] for _ in range(n_bins)]
    for r in rows:
        p = r[prob_key]
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, r["outcome"]))
    table = []
    for i, b in enumerate(bins):
        if not b:
            continue
        table.append({
            "bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}",
            "n": len(b),
            "pred": sum(p for p, _ in b) / len(b),
            "actual": sum(y for _, y in b) / len(b),
        })
    return table


def pnl_trades(trades):
    """Aggregate a list of per-trade P&L (in [-1, 1] units of one share)."""
    n = len(trades)
    if not n:
        return {"n": 0, "pnl": 0.0, "avg": 0.0, "hit_rate": 0.0}
    total = sum(t for t in trades)
    wins = sum(1 for t in trades if t > 0)
    return {"n": n, "pnl": total, "avg": total / n, "hit_rate": wins / n}


def trade_pnl(model_p, market_yes, market_no, outcome, threshold):
    """P&L of taking the model's edge on one band, held to resolution. Returns
    None if the edge is below threshold (no trade)."""
    edge = model_p - market_yes
    if edge > threshold:                      # model thinks YES underpriced -> buy YES
        return outcome - market_yes
    if edge < -threshold:                     # model thinks YES overpriced -> buy NO
        cost_no = market_no if market_no is not None and not pd.isna(market_no) else (1.0 - market_yes)
        return (1 - outcome) - cost_no
    return None


def backtest_tape(df, settlement_bucket, thresholds):
    """Score one market day's tape. Returns per-row scoring rows, per-threshold
    P&L (per-snapshot and first-entry), and persistence per band."""
    rows = []
    for _, r in df.iterrows():
        mp, my = r.get("model_probability"), r.get("market_yes")
        if pd.isna(mp) or pd.isna(my):
            continue
        outcome = resolve_outcome(r.get("bin_kind"), r.get("bin_value_c"), settlement_bucket)
        if outcome is None:
            continue
        rows.append({
            "snapshot_id": r.get("snapshot_id"),
            "band": r.get("range_label"),
            "bin_kind": r.get("bin_kind"),
            "model_probability": float(mp),
            "market_yes": float(my),
            "market_no": (float(r["market_no"]) if "market_no" in r and not pd.isna(r["market_no"]) else None),
            "outcome": int(outcome),
        })

    per_snapshot = {}
    first_entry = {}
    for thr in thresholds:
        snaps = [trade_pnl(r["model_probability"], r["market_yes"], r["market_no"], r["outcome"], thr)
                 for r in rows]
        per_snapshot[thr] = pnl_trades([t for t in snaps if t is not None])

        # First-entry: one trade per band, at the first snapshot whose edge clears thr.
        seen, entries = set(), []
        for r in rows:
            if r["band"] in seen:
                continue
            t = trade_pnl(r["model_probability"], r["market_yes"], r["market_no"], r["outcome"], thr)
            if t is not None:
                entries.append(t)
                seen.add(r["band"])
        first_entry[thr] = pnl_trades(entries)

    # Persistence per band (using the smallest threshold).
    thr0 = min(thresholds)
    persistence = []
    for band in sorted({r["band"] for r in rows}):
        band_rows = [r for r in rows if r["band"] == band]
        edges = [r["model_probability"] - r["market_yes"] for r in band_rows]
        outcome = band_rows[0]["outcome"]
        frac_pos = sum(1 for e in edges if e > thr0) / len(edges)
        frac_neg = sum(1 for e in edges if e < -thr0) / len(edges)
        mean_edge = sum(edges) / len(edges)
        persistence.append({
            "band": band, "snapshots": len(band_rows), "mean_edge": mean_edge,
            "frac_edge_up": frac_pos, "frac_edge_down": frac_neg, "settled_yes": outcome,
        })
    return rows, per_snapshot, first_entry, persistence


def fmt_pct(x):
    return f"{x * 100:.1f}%"


def write_report(results, out_path, thresholds):
    L = ["# Settlement-Scored Backtest\n",
         f"Generated: {datetime.now():%Y-%m-%d %H:%M}\n",
         f"Market days: {len(results['days'])}  |  Total band-rows scored: {results['total_rows']}\n",
         "\n> Model resolution = WU CYYZ printed daily high. Results over a handful of\n"
         "> market days are **illustrative, not conclusive**; intraday snapshots of the\n"
         "> same day are correlated. The harness scales as more days are captured.\n",
         "\n## Settlement (the crux)\n",
         "| Date | Settlement bucket | Source | Note |",
         "| :--- | :--- | :--- | :--- |"]
    for d in results["days"]:
        L.append(f"| {d['date']} | {d['settlement']} C | {d['source']} | {d['note'] or '-'} |")

    agg = results["aggregate_score"]
    if agg:
        L += ["\n## Model vs Market (settlement-scored, all snapshots)\n",
              "| Metric | Model | Market |",
              "| :--- | :--- | :--- |",
              f"| Brier (lower better) | {agg['model_brier']:.4f} | {agg['market_brier']:.4f} |",
              f"| Log loss (lower better) | {agg['model_logloss']:.4f} | {agg['market_logloss']:.4f} |",
              f"\n**Brier skill score (model vs market): {agg['brier_skill_score']:+.3f}** "
              f"(>0 means the model beats the market). N = {agg['n']} band-rows, "
              f"base rate {fmt_pct(agg['base_rate'])}.\n"]

    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        table = reliability(results["all_rows"], key)
        L += [f"\n### {label} reliability\n",
              "| Confidence bin | N | Mean predicted | Realized |",
              "| :--- | :--- | :--- | :--- |"]
        for t in table:
            L.append(f"| {t['bin']} | {t['n']} | {fmt_pct(t['pred'])} | {fmt_pct(t['actual'])} |")

    L += ["\n## Realized edge / P&L (trade when |model - market| > threshold, hold to resolution)\n",
          "P&L is in shares (max +1 / -1 each). **Per-snapshot** counts every snapshot as a "
          "trade (overcounts correlated intraday signals); **first-entry** takes one trade per "
          "band at the first snapshot that clears the threshold.\n",
          "| Threshold | Per-snapshot trades | Per-snapshot P&L | Avg | Hit rate | First-entry trades | First-entry P&L | Avg |",
          "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for thr in thresholds:
        ps, fe = results["pnl_per_snapshot"][thr], results["pnl_first_entry"][thr]
        L.append(f"| {thr:.2f} | {ps['n']} | {ps['pnl']:+.2f} | {ps['avg']:+.3f} | {fmt_pct(ps['hit_rate'])} "
                 f"| {fe['n']} | {fe['pnl']:+.2f} | {fe['avg']:+.3f} |")

    L += ["\n## Edge persistence per band\n",
          "| Date | Band | Snapshots | Mean edge | % edge up | % edge down | Settled YES? |",
          "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for d in results["days"]:
        for p in d["persistence"]:
            L.append(f"| {d['date']} | {p['band']} | {p['snapshots']} | {p['mean_edge']:+.2f} "
                     f"| {fmt_pct(p['frac_edge_up'])} | {fmt_pct(p['frac_edge_down'])} | {p['settled_yes']} |")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(L) + "\n", encoding="utf-8")


def run_backtest(folders, daily_summary_path, overrides, thresholds, out_path):
    daily_index = load_daily_summary(daily_summary_path)
    days, all_rows = [], []
    pnl_ps = {thr: [] for thr in thresholds}
    pnl_fe = {thr: [] for thr in thresholds}

    for folder in folders:
        tape = Path(folder) / "snapshots_long.csv"
        if not tape.exists():
            print(f"  skip {folder}: no snapshots_long.csv")
            continue
        df = pd.read_csv(tape)
        slug = Path(folder).name
        target_date = date_from_event_slug(slug)
        bucket, source, note = settlement_for_tape(df, target_date, daily_index, overrides)
        rows, per_snap, first_entry, persistence = backtest_tape(df, bucket, thresholds)
        all_rows.extend(rows)
        for thr in thresholds:
            pnl_ps[thr].append(per_snap[thr])
            pnl_fe[thr].append(first_entry[thr])
        days.append({
            "date": target_date.isoformat() if target_date else slug,
            "settlement": bucket, "source": source, "note": note,
            "rows": len(rows), "persistence": persistence,
        })
        print(f"  {slug}: settlement {bucket} C ({source}); {len(rows)} band-rows scored")

    def merge(parts):
        return {
            "n": sum(p["n"] for p in parts),
            "pnl": sum(p["pnl"] for p in parts),
            "hit_rate": (sum(p["hit_rate"] * p["n"] for p in parts) / sum(p["n"] for p in parts))
            if sum(p["n"] for p in parts) else 0.0,
            "avg": (sum(p["pnl"] for p in parts) / sum(p["n"] for p in parts))
            if sum(p["n"] for p in parts) else 0.0,
        }

    results = {
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "aggregate_score": score_rows(all_rows),
        "pnl_per_snapshot": {thr: merge(pnl_ps[thr]) for thr in thresholds},
        "pnl_first_entry": {thr: merge(pnl_fe[thr]) for thr in thresholds},
    }
    write_report(results, out_path, thresholds)
    return results


def main():
    parser = argparse.ArgumentParser(description="Settlement-scored model-vs-market backtest.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under snapshots root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--settle", action="append", default=[],
                        help="Force settlement: YYYY-MM-DD=BUCKET (repeatable).")
    parser.add_argument("--thresholds", default="0.05,0.10,0.15")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    overrides = {}
    for item in args.settle:
        d, _, b = item.partition("=")
        overrides[d.strip()] = int(b)
    thresholds = [float(x) for x in args.thresholds.split(",") if x.strip()]

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Backtesting {len(folders)} market day(s)...")
    results = run_backtest(folders, args.daily_summary, overrides, thresholds, args.out)
    agg = results["aggregate_score"]
    if agg:
        print(f"\nModel Brier {agg['model_brier']:.4f} vs Market {agg['market_brier']:.4f}  "
              f"(skill {agg['brier_skill_score']:+.3f})")
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
