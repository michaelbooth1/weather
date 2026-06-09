"""Forecast-vs-realized tracker.

A standing tool that answers one question as market days settle: when the
*morning* forecasts call a high and the model regresses below it (the HGB's
learned morning skepticism), who is right -- the forecast, the model, or the
market?

For each settled day, at one or more morning cutoffs, it captures:
  * the forecast high per source (Open-Meteo / Weather.com / ECCC) and consensus,
  * the model's and market's probability of *reaching* the forecast, and the
    model's / market's median bucket,
  * the realized WU settlement,
and reports per-source forecast calibration plus a headline verdict framed as
reach-rate calibration: how often the morning forecast is actually reached vs.
how much probability the model gave it. Reached-more-than-expected => the
skepticism is COSTING; reached-less => it is SAVING.

Reusable by design: settled days are auto-discovered (settled_days), cutoffs /
folders / settlement overrides are configurable, the core is pure functions, and
it emits both a markdown report and a JSON summary for downstream automation. It
sharpens automatically as more days settle.

CLI:
  python -m src.forecast_tracker
      [folder ...] [--cutoffs 7,9,11,13] [--verdict-cutoff 9]
      [--settle YYYY-MM-DD=BUCKET ...]
      [--out data/backtest/forecast_vs_realized.md]
      [--json-out data/backtest/forecast_vs_realized.json]
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    capture_minute,
    load_daily_summary,
    round_half_up,
    safe_float,
    settlement_for_tape,
)
from market_config import date_from_event_slug
from market_registry import REGISTRY, spec_for_id
from settled_days import discover_settled_folders, validate_folders_market

DEFAULT_CUTOFFS = (7, 9, 11, 13)
DEFAULT_VERDICT_CUTOFF = 9
DEFAULT_OUT = Path("data") / "backtest" / "forecast_vs_realized.md"
DEFAULT_JSON_OUT = Path("data") / "backtest" / "forecast_vs_realized.json"
CALIBRATION_MARGIN = 0.15  # |reach_rate - model_reach| under this = "calibrated"

FORECAST_SOURCES = {
    "open_meteo": "open_meteo_max_c",
    "weather_com": "weather_forecast_max_c",
    "eccc": "eccc_forecast_high_c",
}


# --- Per-snapshot extraction -------------------------------------------------

def select_snapshot_rows(records, cutoff_hour):
    """The band rows of the first snapshot captured at/after ``cutoff_hour``."""
    by_snapshot = defaultdict(list)
    for row in records:
        by_snapshot[row.get("snapshot_id")].append(row)
    cutoff_minute = cutoff_hour * 60
    best_key = None
    best_minute = None
    for snapshot_id, rows in by_snapshot.items():
        minute = capture_minute(rows[0].get("captured_at_local"))
        if minute is None or minute < cutoff_minute:
            continue
        if best_minute is None or minute < best_minute:
            best_minute, best_key = minute, snapshot_id
    return by_snapshot.get(best_key) if best_key is not None else None


def forecasts_from_rows(rows):
    """Per-source forecast highs (snapshot-level, repeated on each band row) plus
    the consensus (median of available)."""
    head = rows[0]
    out = {}
    for source, column in FORECAST_SOURCES.items():
        out[source] = safe_float(head.get(column))
    available = [value for value in out.values() if value is not None]
    out["consensus"] = statistics.median(available) if available else None
    return out


def band_masses(rows, prob_key):
    """Ordered (value, prob, kind) for a side's bands (lte tail at its boundary,
    eq exact, gte tail at its boundary)."""
    masses = []
    for row in rows:
        value = safe_float(row.get("bin_value_c"))
        prob = safe_float(row.get(prob_key))
        kind = row.get("bin_kind")
        if value is None or prob is None or kind is None:
            continue
        masses.append((value, prob, kind))
    return sorted(masses, key=lambda item: item[0])


def reach_probability(rows, forecast_bucket, prob_key):
    """P(high >= forecast_bucket) implied by one side's band prices.

    Clean when the forecast bucket falls in the eq range or at the gte boundary
    (the usual case, since the market frames bands around the likely high).
    Returns None when it would require splitting the low (lte) tail.
    """
    if forecast_bucket is None:
        return None
    masses = band_masses(rows, prob_key)
    lte_value = next((v for v, _, k in masses if k == "lte"), None)
    if lte_value is not None and forecast_bucket <= lte_value:
        return None  # cannot split the <=L tail
    total = 0.0
    for value, prob, kind in masses:
        if kind == "lte":
            continue  # below the forecast bucket (forecast_bucket > lte_value)
        if kind == "gte":
            total += prob  # >=H fully implies >=forecast_bucket (forecast_bucket <= H typical)
        elif value >= forecast_bucket:
            total += prob
    return min(1.0, total)


def median_bucket(rows, prob_key):
    """The bucket where cumulative probability first reaches 0.5."""
    masses = band_masses(rows, prob_key)
    if not masses:
        return None
    cumulative = 0.0
    for value, prob, _ in masses:
        cumulative += prob
        if cumulative >= 0.5:
            return int(value)
    return int(masses[-1][0])


def day_record(folder, cutoff_hour, daily_index, overrides):
    """One forecast-vs-realized record for a settled day at a cutoff (or None)."""
    tape = Path(folder) / "snapshots_long.csv"
    if not tape.exists():
        return None
    frame = pd.read_csv(tape)
    target_date = date_from_event_slug(Path(folder).name)
    settlement, source, note = settlement_for_tape(frame, target_date, daily_index, overrides)
    if settlement is None:
        return None
    rows = select_snapshot_rows(frame.to_dict("records"), cutoff_hour)
    if not rows:
        return None
    forecasts = forecasts_from_rows(rows)
    forecast_bucket = round_half_up(forecasts["consensus"])
    return {
        "date": target_date.isoformat() if target_date else Path(folder).name,
        "cutoff_hour": cutoff_hour,
        "captured_at_local": rows[0].get("captured_at_local"),
        "settlement": int(settlement),
        "settlement_source": source,
        "settlement_note": note,
        "forecasts": forecasts,
        "forecast_bucket": forecast_bucket,
        "reached": (int(settlement) >= forecast_bucket) if forecast_bucket is not None else None,
        "model_reach": reach_probability(rows, forecast_bucket, "model_probability"),
        "market_reach": reach_probability(rows, forecast_bucket, "market_yes"),
        "model_median": median_bucket(rows, "model_probability"),
        "market_median": median_bucket(rows, "market_yes"),
    }


# --- Aggregation -------------------------------------------------------------

def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def source_calibration(records, source):
    """Signed bias (realized - forecast), MAE, and exact-bucket hit rate for one
    forecast source over the records."""
    errors, hits = [], []
    for record in records:
        forecast = record["forecasts"].get(source)
        if forecast is None:
            continue
        realized = record["settlement"]
        errors.append(realized - forecast)
        hits.append(1.0 if round_half_up(forecast) == realized else 0.0)
    if not errors:
        return None
    return {
        "n": len(errors),
        "bias": _mean(errors),                       # + => forecast under-calls the high
        "mae": _mean([abs(e) for e in errors]),
        "hit_rate": _mean(hits),
    }


def summarize_cutoff(records):
    reach_records = [r for r in records if r["reached"] is not None and r["model_reach"] is not None]
    return {
        "n_days": len(records),
        "sources": {
            source: source_calibration(records, source)
            for source in (*FORECAST_SOURCES, "consensus")
        },
        "reach": {
            "n": len(reach_records),
            "reach_rate": _mean([1.0 if r["reached"] else 0.0 for r in reach_records]),
            "model_reach": _mean([r["model_reach"] for r in reach_records]),
            "market_reach": _mean([r["market_reach"] for r in reach_records]),
        },
        "model_point_mae": _mean([
            abs(r["settlement"] - r["model_median"]) for r in records if r["model_median"] is not None
        ]),
        "market_point_mae": _mean([
            abs(r["settlement"] - r["market_median"]) for r in records if r["market_median"] is not None
        ]),
    }


def verdict(summary):
    """Headline read on whether the model's morning forecast-skepticism is
    costing or saving, from reach-rate calibration."""
    reach = summary["reach"]
    rate, model_reach, market_reach = reach["reach_rate"], reach["model_reach"], reach["market_reach"]
    consensus = summary["sources"].get("consensus") or {}
    bias = consensus.get("bias")
    if rate is None or model_reach is None:
        return {"headline": "INSUFFICIENT DATA", "detail": "no settled days with a computable reach probability yet.", "gap": None}
    gap = rate - model_reach
    if gap > CALIBRATION_MARGIN:
        headline = "SKEPTICISM IS COSTING"
        detail = (
            f"the morning forecast is reached {rate:.0%} of the time, but the model gives it only "
            f"{model_reach:.0%} -- it UNDER-calls the high; trusting the forecast more would help."
        )
    elif gap < -CALIBRATION_MARGIN:
        headline = "SKEPTICISM IS JUSTIFIED"
        detail = (
            f"the forecast is reached only {rate:.0%} of the time, yet the model gives it {model_reach:.0%} "
            f"-- forecasts OVER-call, so discounting them is correct."
        )
    else:
        headline = "MODEL CALIBRATED"
        detail = (
            f"reach-rate {rate:.0%} ~ model's {model_reach:.0%}: the model's morning confidence already "
            f"matches how often the forecast is reached."
        )
    return {
        "headline": headline,
        "detail": detail,
        "gap": gap,
        "reach_rate": rate,
        "model_reach": model_reach,
        "market_reach": market_reach,
        "consensus_bias": bias,
        "n": reach["n"],
    }


def run(folders, cutoffs, daily_summary_path, overrides, verdict_cutoff):
    daily_index = load_daily_summary(daily_summary_path)
    per_cutoff = {}
    all_records = []
    for cutoff in cutoffs:
        records = []
        for folder in folders:
            record = day_record(folder, cutoff, daily_index, overrides)
            if record:
                records.append(record)
        records.sort(key=lambda r: r["date"])
        per_cutoff[cutoff] = {"records": records, "summary": summarize_cutoff(records)}
        all_records.extend(records)
    verdict_summary = (per_cutoff.get(verdict_cutoff) or {}).get("summary")
    return {
        "cutoffs": list(cutoffs),
        "verdict_cutoff": verdict_cutoff,
        "per_cutoff": per_cutoff,
        "verdict": verdict(verdict_summary) if verdict_summary else None,
        "n_days_total": len({r["date"] for r in all_records}),
    }


# --- Reporting ---------------------------------------------------------------

def _pct(value):
    return "-" if value is None else f"{value * 100:.0f}%"


def _num(value, decimals=2, signed=False):
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(":---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def write_report(results, out_path):
    v = results.get("verdict") or {}
    lines = [
        "# Forecast vs Realized Tracker",
        "",
        f"Settled days: {results['n_days_total']}  |  verdict cutoff: {results['verdict_cutoff']:02d}:00",
        "",
        "## Verdict: is the model's morning forecast-skepticism costing or saving?",
        "",
        f"**{v.get('headline', 'INSUFFICIENT DATA')}** -- {v.get('detail', '')}",
        "",
    ]
    if v.get("gap") is not None:
        lines += _table(
            ["Reach-rate (realized >= forecast)", "Model gives", "Market gives", "Consensus bias (realized-forecast)", "N"],
            [[_pct(v.get("reach_rate")), _pct(v.get("model_reach")), _pct(v.get("market_reach")),
              _num(v.get("consensus_bias"), signed=True) + " C", v.get("n")]],
        )
    lines += ["", "> Bias > 0 means the forecast UNDER-calls the realized high; < 0 means it OVER-calls.", ""]

    for cutoff in results["cutoffs"]:
        block = results["per_cutoff"][cutoff]
        summary = block["summary"]
        lines += [f"## Cutoff {cutoff:02d}:00  ({summary['n_days']} days)", ""]
        lines += ["### Forecast source calibration", ""]
        lines += _table(
            ["Source", "N", "Bias (realized-fc)", "MAE", "Exact-bucket hit"],
            [
                [source,
                 (cal or {}).get("n", "-"),
                 _num((cal or {}).get("bias"), signed=True),
                 _num((cal or {}).get("mae")),
                 _pct((cal or {}).get("hit_rate"))]
                for source, cal in summary["sources"].items()
            ],
        )
        reach = summary["reach"]
        lines += [
            "",
            "### Reach calibration & point error",
            "",
        ]
        lines += _table(
            ["Reach-rate", "Model reach", "Market reach", "Model median MAE", "Market median MAE"],
            [[_pct(reach["reach_rate"]), _pct(reach["model_reach"]), _pct(reach["market_reach"]),
              _num(summary["model_point_mae"]), _num(summary["market_point_mae"])]],
        )
        lines += ["", "### Per-day", ""]
        lines += _table(
            ["Date", "Forecast(cons)", "FcBucket", "Realized", "Reached?", "Model reach", "Market reach", "Settle src"],
            [
                [r["date"], _num(r["forecasts"]["consensus"]), r["forecast_bucket"], r["settlement"],
                 "yes" if r["reached"] else "no", _pct(r["model_reach"]), _pct(r["market_reach"]), r["settlement_source"]]
                for r in block["records"]
            ],
        )
        lines.append("")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(results, json_path):
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(results, indent=2, sort_keys=True, default=str), encoding="utf-8")


def parse_overrides(items):
    overrides = {}
    for item in items:
        date_text, _, bucket = item.partition("=")
        overrides[date_text.strip()] = int(bucket)
    return overrides


def main():
    parser = argparse.ArgumentParser(description="Track morning forecast accuracy vs realized settlement.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: auto-discovered settled days).")
    parser.add_argument("--market", default="toronto", choices=sorted(REGISTRY),
                        help="Market whose settled tapes this tracker scores.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=None,
                        help="Daily summary CSV (default: the market's own data root).")
    parser.add_argument("--cutoffs", default=",".join(str(c) for c in DEFAULT_CUTOFFS))
    parser.add_argument("--verdict-cutoff", type=int, default=DEFAULT_VERDICT_CUTOFF)
    parser.add_argument("--settle", action="append", default=[], help="Force settlement: YYYY-MM-DD=BUCKET")
    parser.add_argument("--out", default=None,
                        help="Report path (default: per-market report under data/backtest).")
    parser.add_argument("--json-out", default=None,
                        help="JSON path (default: per-market file under data/backtest).")
    args = parser.parse_args()

    cutoffs = [int(c.strip()) for c in args.cutoffs.split(",") if c.strip()]
    overrides = parse_overrides(args.settle)
    # One market's tapes per verdict: data/snapshots holds all 12 markets.
    spec = spec_for_id(args.market)
    if args.folders:
        folders = args.folders
        validate_folders_market(folders, spec.id)
    else:
        folders = [
            str(f) for f in
            discover_settled_folders(args.snapshots_root, market_id=spec.id)
        ]
    daily_summary = args.daily_summary or spec.data_root / "daily" / "daily_summary.csv"
    out_path = args.out or Path("data") / "backtest" / f"forecast_vs_realized{spec.artifact_suffix}.md"
    json_out_path = args.json_out or Path("data") / "backtest" / f"forecast_vs_realized{spec.artifact_suffix}.json"
    if not folders:
        print("No settled market days found.")
        return

    results = run(folders, cutoffs, daily_summary, overrides, args.verdict_cutoff)
    write_report(results, out_path)
    write_json(results, json_out_path)

    v = results.get("verdict") or {}
    print(f"Settled days: {results['n_days_total']}  (verdict at {args.verdict_cutoff:02d}:00)")
    print(f"VERDICT: {v.get('headline', 'INSUFFICIENT DATA')} -- {v.get('detail', '')}")
    print(f"Report: {out_path}  |  JSON: {json_out_path}")


if __name__ == "__main__":
    main()
