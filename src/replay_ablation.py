"""Per-source ablation replays: measure each live source's marginal value.

For every captured snapshot in the replay corpus, re-run the current model on
(a) the sources exactly as captured (the baseline control) and (b) the same
sources with one live source knocked out (``ok: False`` -- byte-identical to a
real fetch outage, so every fallback path is exercised). Both are scored
against realized settlement on the recorded market bands.

The matched-row Brier delta (ablated minus baseline) is the source's measured
END-TO-END value: positive means removing the source hurts (it was helping),
negative means the model scores better without it. Because ablation goes
through the full engine -- feature extraction, forecast fallbacks, live
signals, floors, pull, lock-in -- this measures what the source is worth to
the system, not to one component slot.

``all_forecasts`` knocks out Open-Meteo + Weather.com + ECCC citypage together:
single-source forecast ablations are cushioned by fallback to the remaining
forecasts, so the combined variant is the honest value of the forecast layer.

CLI:
  python -m src.replay_ablation [folder ...]
      [--snapshots-root data/snapshots] [--market MARKET]
      [--sources open_meteo,weather_forecast,...] [--include-reconstructed]
      [--out data/backtest/replay_ablation_report.md]
"""
import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    DEFAULT_SNAPSHOTS_ROOT,
    band_value_hi,
    load_daily_summary,
    resolve_outcome,
    safe_float,
    settlement_for_tape,
)
from market_config import date_from_event_slug
from market_registry import REGISTRY
from replay import (
    band_model_probability,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    replay_distribution,
)
from settled_days import folder_market_id
from toronto_model import TorontoHighTempModel

DEFAULT_OUT = Path("data") / "backtest" / "replay_ablation_report.md"
SINGLE_SOURCES = (
    "open_meteo",
    "weather_forecast",
    "eccc_citypage",
    "eccc_swob",
    "metar",
    "wu_current",
)
COMBINED_VARIANTS = {
    "all_forecasts": ("open_meteo", "weather_forecast", "eccc_citypage"),
}


def ablate_sources(sources, names):
    """The captured sources with ``names`` knocked out exactly as a failed
    fetch presents them. Shallow copy: estimate_distribution does not mutate
    source payloads, and untouched entries are shared, not copied."""
    out = dict(sources)
    for name in names:
        if name in out:
            out[name] = {"ok": False, "error": "ablated", "data": {}}
    return out


def variant_names_for_spec(spec, requested):
    """Which ablation variants are meaningful for this market: a variant must
    knock out at least one source the market actually declares."""
    variants = {}
    for name in requested:
        members = COMBINED_VARIANTS.get(name, (name,))
        if any(member in spec.sources for member in members):
            variants[name] = members
    return variants


def run_ablation(folders, requested_sources, include_reconstructed=False):
    models = {}
    daily_indexes = {}
    rows = []
    day_meta = []

    for folder in folders:
        folder = Path(folder)
        tape_path = folder / "snapshots_long.csv"
        if not tape_path.exists():
            continue
        market_id = folder_market_id(folder)
        if market_id is None:
            continue
        spec = REGISTRY[market_id]
        variants = variant_names_for_spec(spec, requested_sources)
        if not variants:
            continue
        records = index_records_by_snapshot(load_replay_records(folder))
        records = {
            snapshot_id: record
            for snapshot_id, record in records.items()
            if include_reconstructed or not is_reconstructed(record)
        }
        if not records:
            continue

        if market_id not in models:
            models[market_id] = TorontoHighTempModel(market_id=market_id)
        if market_id not in daily_indexes:
            daily_indexes[market_id] = load_daily_summary(
                spec.data_root / "daily" / "daily_summary.csv"
            )
        model = models[market_id]

        df = pd.read_csv(tape_path)
        if "snapshot_id" not in df:
            continue
        target_date = date_from_event_slug(folder.name)
        bucket, source, _ = settlement_for_tape(
            df, target_date, daily_indexes[market_id], {}
        )
        if bucket is None:
            print(f"  skip {folder.name}: no settlement")
            continue
        date_label = target_date.isoformat() if target_date else folder.name
        day_key = f"{market_id} {date_label}"
        family = "toronto" if market_id == "toronto" else "us_f"

        scored_snaps = 0
        for snapshot_id, group in df.groupby("snapshot_id"):
            record = records.get(str(snapshot_id))
            if not record or not record.get("sources"):
                continue

            bands = []
            for _, band_series in group.iterrows():
                band = band_series.to_dict()
                outcome = resolve_outcome(
                    band.get("bin_kind"), band.get("bin_value_c"), bucket,
                    value_hi=band_value_hi(band.get("range_label"), band.get("bin_value_c")),
                )
                if outcome is None:
                    continue
                bands.append((band, int(outcome)))
            if not bands:
                continue

            # Baseline first; band probabilities must be read immediately after
            # each replay because bin_probability uses the calibration context
            # estimate_distribution just set on the model.
            base_dist = replay_distribution(model, record)
            if not base_dist:
                continue
            base_probs = [band_model_probability(model, base_dist, band) for band, _ in bands]

            hour = None
            captured = str(bands[0][0].get("captured_at_local") or "")
            if len(captured) >= 13:
                try:
                    hour = int(captured[11:13])
                except ValueError:
                    hour = None

            for variant, members in variants.items():
                variant_record = dict(record)
                variant_record["sources"] = ablate_sources(record["sources"], members)
                variant_dist = replay_distribution(model, variant_record)
                if not variant_dist:
                    continue
                for (band, outcome), base_p in zip(bands, base_probs):
                    variant_p = band_model_probability(model, variant_dist, band)
                    if variant_p is None or base_p is None:
                        continue
                    rows.append({
                        "day": day_key,
                        "family": family,
                        "variant": variant,
                        "hour": hour,
                        "y": outcome,
                        "base_p": base_p,
                        "variant_p": variant_p,
                        "market_yes": safe_float(band.get("market_yes")),
                    })
            scored_snaps += 1

        day_meta.append({
            "day": day_key, "settlement": bucket, "settlement_source": source,
            "snapshots": scored_snaps,
        })
        print(f"  {folder.name}: settlement {bucket} {spec.display_unit} ({source}); "
              f"{scored_snaps} snapshots ablated over {len(variants)} variants")

    return pd.DataFrame(rows), day_meta


def summarize(data):
    """Per-variant pooled scores plus per-day helped/hurt counts."""
    if data.empty:
        return [], {}
    summaries = []
    day_tables = {}
    for variant, sub in data.groupby("variant"):
        base_brier = ((sub["base_p"] - sub["y"]) ** 2).mean()
        variant_brier = ((sub["variant_p"] - sub["y"]) ** 2).mean()
        market_rows = sub.dropna(subset=["market_yes"])
        market_brier = (
            ((market_rows["market_yes"] - market_rows["y"]) ** 2).mean()
            if len(market_rows) else None
        )
        per_day = []
        for day, day_rows in sub.groupby("day"):
            delta = (
                ((day_rows["variant_p"] - day_rows["y"]) ** 2).mean()
                - ((day_rows["base_p"] - day_rows["y"]) ** 2).mean()
            )
            per_day.append({"day": day, "delta": delta, "n": len(day_rows)})
        per_day.sort(key=lambda row: row["delta"])
        day_tables[variant] = per_day
        helped = sum(1 for row in per_day if row["delta"] > 0.0001)
        hurt = sum(1 for row in per_day if row["delta"] < -0.0001)
        by_family = {}
        for family, fam_rows in sub.groupby("family"):
            by_family[family] = (
                ((fam_rows["variant_p"] - fam_rows["y"]) ** 2).mean()
                - ((fam_rows["base_p"] - fam_rows["y"]) ** 2).mean()
            )
        summaries.append({
            "variant": variant,
            "n": len(sub),
            "days": sub["day"].nunique(),
            "base_brier": base_brier,
            "variant_brier": variant_brier,
            "delta": variant_brier - base_brier,
            "market_brier": market_brier,
            "days_source_helped": helped,
            "days_source_hurt": hurt,
            "by_family": by_family,
        })
    summaries.sort(key=lambda row: row["delta"], reverse=True)
    return summaries, day_tables


def fmt(value, decimals=4):
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}"


def write_report(out_path, summaries, day_tables, day_meta, include_reconstructed):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Per-Source Ablation Replay",
        "",
        f"Generated: {generated}",
        "",
        "Each captured snapshot is replayed with the current code on its",
        "captured sources (baseline) and again with one source knocked out",
        "(`ok: False`, identical to a fetch outage). Delta = ablated Brier",
        "minus baseline Brier on matched rows: **positive = the source was",
        "helping** (removing it hurts), negative = the model scored better",
        "without it.",
        "",
        f"Days scored: {len(day_meta)}  |  reconstructed records included: "
        f"{'yes' if include_reconstructed else 'no'}",
        "",
        "## Source Value Summary",
        "",
        "| Variant | Rows | Days | Baseline Brier | Ablated Brier | Delta (source value) | Days helped | Days hurt | Market Brier |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in summaries:
        lines.append(
            f"| {s['variant']} | {s['n']} | {s['days']} | {fmt(s['base_brier'])} "
            f"| {fmt(s['variant_brier'])} | {fmt_signed(s['delta'])} "
            f"| {s['days_source_helped']} | {s['days_source_hurt']} "
            f"| {fmt(s['market_brier'])} |"
        )
    lines += [
        "",
        "## By Family (delta, positive = source helps)",
        "",
        "| Variant | toronto | us_f |",
        "| :--- | ---: | ---: |",
    ]
    for s in summaries:
        toronto = s["by_family"].get("toronto")
        us = s["by_family"].get("us_f")
        lines.append(
            f"| {s['variant']} | {fmt_signed(toronto) if toronto is not None else '-'} "
            f"| {fmt_signed(us) if us is not None else '-'} |"
        )
    lines += ["", "## Largest Per-Day Effects", ""]
    for s in summaries:
        per_day = day_tables.get(s["variant"]) or []
        if not per_day:
            continue
        lines.append(f"### {s['variant']}")
        lines.append("")
        lines.append("| Day | Delta | Rows |")
        lines.append("| :--- | ---: | ---: |")
        extremes = per_day[:3] + ([] if len(per_day) <= 6 else per_day[-3:])
        for row in extremes:
            lines.append(f"| {row['day']} | {fmt_signed(row['delta'])} | {row['n']} |")
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Replay the corpus with each live source knocked out and "
                    "measure the per-source Brier effect.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all with tapes).")
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY),
                        help="Only this market's folders.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--sources", default=",".join(list(SINGLE_SOURCES) + list(COMBINED_VARIANTS)),
                        help="Comma list of sources/combined variants to ablate.")
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    requested = [item.strip() for item in args.sources.split(",") if item.strip()]
    unknown = [
        name for name in requested
        if name not in SINGLE_SOURCES and name not in COMBINED_VARIANTS
    ]
    if unknown:
        raise SystemExit(f"Unknown ablation sources: {', '.join(unknown)}")

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if args.market:
        folders = [f for f in folders if folder_market_id(f) == args.market]
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Ablating {len(requested)} variant(s) over {len(folders)} folder(s)...")
    data, day_meta = run_ablation(
        folders, requested, include_reconstructed=args.include_reconstructed
    )
    if data.empty:
        print("No rows scored (no captured replay inputs?).")
        return
    summaries, day_tables = summarize(data)
    write_report(args.out, summaries, day_tables, day_meta, args.include_reconstructed)
    print(f"\nReport written to {args.out}\n")
    print(f"{'variant':18s} {'rows':>7s} {'base':>8s} {'ablated':>8s} {'delta':>9s}  (positive = source helps)")
    for s in summaries:
        print(f"{s['variant']:18s} {s['n']:7d} {s['base_brier']:8.4f} "
              f"{s['variant_brier']:8.4f} {s['delta']:+9.4f}")


if __name__ == "__main__":
    main()
