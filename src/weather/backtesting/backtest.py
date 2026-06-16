"""Settlement-scored backtest: score the model AND the market against the
realized WU settlement for each captured market day.

This answers the question model calibration alone cannot: does the model have
edge *over the market price*? It scores recorded snapshot tapes, which hold both
model probabilities and market yes-prices, against the realized settlement
bucket.

Settlement is the crux. The market resolves on the WU CYYZ printed daily high,
so the realized bucket is taken from the day's maximum captured
``wu_history_high_c`` (half-up rounded), cross-checked against the local daily
summary and overridable on the command line. Disagreements are reported, not
hidden.

CLI:
  python -m weather.backtesting.backtest [folder ...]
      [--snapshots-root data/snapshots]
      [--settle YYYY-MM-DD=BUCKET ...]   # force settlement for a date
      [--thresholds 0.05,0.10,0.15]
      [--fixed-cutoffs 9,10,12,13,15,16,17,18,20]
      [--out data/backtest/backtest_report.md]
"""
import argparse
from datetime import datetime
from pathlib import Path

from weather.paths import data_path

import pandas as pd

from weather.backtesting.settlement_io import (
    COMPLETE_DAY_MIN_ROWS,
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    band_value_hi,
    ledger_label_matches_folder,
    load_daily_summary,
    load_market_day_label,
    resolve_outcome,
    round_half_up,
    row_band_value_hi,
    settlement_for_tape,
)
from weather.backtesting.tape_scoring import (
    DEFAULT_FIXED_CUTOFF_HOURS,
    attach_feature_vector,
    backtest_tape,
    bin_type,
    capture_hour,
    capture_minute,
    feature_vector_coverage,
    fixed_cutoff_rows,
    grouped_scores,
    last_pre_close_rows,
    load_feature_vectors,
    parse_snapshot_time,
    timestamp_key,
)
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.reporting.formatting import (
    fmt_group,
    fmt_num,
    fmt_pct,
    fmt_pnl,
    fmt_signed,
    markdown_table,
)
from weather.scoring.metrics import (
    binary_log_loss,
    brier,
    daily_first_score,
    expected_calibration_error,
    group_sort_key,
    grouped_reliability,
    missing,
    reliability,
    safe_float,
    score_rows,
    unique_sorted,
    winner_band_catchup,
)
from weather.scoring.trading import (
    merge_pnl,
    pnl_for_rows,
    pnl_trades,
    trade_pnl,
)

DEFAULT_OUT = data_path() / "backtest" / "backtest_report.md"


def score_table_rows(items):
    rows = []
    for label, score in items:
        if not score:
            continue
        rows.append([
            label,
            score.get("n_days", "-"),
            score.get("n", "-"),
            fmt_num(score.get("model_brier")),
            fmt_num(score.get("market_brier")),
            fmt_signed(score.get("brier_delta")),
            fmt_signed(score.get("brier_skill_score"), 3),
            fmt_num(score.get("model_logloss")),
            fmt_num(score.get("market_logloss")),
            fmt_signed(score.get("logloss_delta")),
            fmt_pct(score.get("base_rate")),
        ])
    return rows


def grouped_score_table_rows(items):
    return [
        [
            fmt_group(item.get("group")),
            item.get("n", "-"),
            fmt_num(item.get("model_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("brier_skill_score"), 3),
            fmt_num(item.get("model_logloss")),
            fmt_num(item.get("market_logloss")),
            fmt_signed(item.get("logloss_delta")),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def reliability_table_rows(items):
    return [
        [
            fmt_group(item.get("group")),
            item.get("bin", "-"),
            item.get("n", "-"),
            fmt_pct(item.get("pred")),
            fmt_pct(item.get("actual")),
        ]
        for item in items
    ]


def collect_model_card(results):
    aggregate = results.get("aggregate_score") or {}
    daily = results.get("daily_first_score") or {}
    model_ece = expected_calibration_error(results.get("all_rows", []), "model_probability")
    market_ece = expected_calibration_error(results.get("all_rows", []), "market_yes")
    return {
        "market_days": len(results.get("days", [])),
        "band_rows": results.get("total_rows", 0),
        "model_versions": ", ".join(results.get("model_versions") or []) or "-",
        "all_snapshot_skill": aggregate.get("brier_skill_score"),
        "daily_first_skill": daily.get("brier_skill_score"),
        "logloss_delta": aggregate.get("logloss_delta"),
        "model_ece": model_ece,
        "market_ece": market_ece,
    }


def write_report(results, out_path, thresholds):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    model_card = collect_model_card(results)
    lines = [
        "# Settlement-Scored Backtest",
        "",
        f"Generated: {generated}",
        "",
        (
            f"Market days: {len(results['days'])}  |  "
            f"Total band-rows scored: {results['total_rows']}"
        ),
        f"Quality filter: {', '.join(results.get('quality_filter') or ['all'])}",
        "",
        "> Model resolution = settlement ledger labels (WU history per registered market),",
        "> with legacy source fallback only for unfinalized tapes. Results over a handful of",
        "> market days are illustrative, not conclusive. Intraday snapshots from the",
        "> same day are correlated, so use the daily-first, last-pre-close, and",
        "> fixed-cutoff sections as the safer accuracy gates.",
        "",
        "## Model Card",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Market days", model_card["market_days"]],
            ["All-snapshot band rows", model_card["band_rows"]],
            ["Model versions", model_card["model_versions"]],
            ["All-snapshot Brier skill vs market", fmt_signed(model_card["all_snapshot_skill"], 3)],
            ["Daily-first Brier skill vs market", fmt_signed(model_card["daily_first_skill"], 3)],
            ["All-snapshot log-loss delta (market - model)", fmt_signed(model_card["logloss_delta"])],
            ["Model ECE", fmt_num(model_card["model_ece"])],
            ["Market ECE", fmt_num(model_card["market_ece"])],
        ],
    )

    lines += [
        "",
        "## Run Inputs And Settlement",
        "",
    ]
    lines += markdown_table(
        [
            "Date",
            "Snapshot tape",
            "Snapshots",
            "Bands",
            "Model versions",
            "Settlement",
            "Source",
            "Quality",
            "Note",
        ],
        [
            [
                day["date"],
                day["tape_path"],
                day["snapshot_count"],
                day["band_count"],
                ", ".join(day.get("model_versions") or []) or "-",
                day.get("settlement_display") or (f"{day['settlement']} C" if day["settlement"] is not None else "-"),
                day["source"],
                day.get("quality_grade") or "-",
                day["note"] or "-",
            ]
            for day in results["days"]
        ],
    )

    feature_coverage = results.get("feature_vector_coverage") or {}
    lines += [
        "",
        "## Feature Vector Coverage",
        "",
    ]
    lines += markdown_table(
        ["Rows", "Rows with features", "Coverage", "Feature schemas"],
        [[
            feature_coverage.get("rows", 0),
            feature_coverage.get("rows_with_features", 0),
            fmt_pct(feature_coverage.get("coverage")),
            ", ".join(feature_coverage.get("schema_versions") or []) or "-",
        ]],
    )
    if feature_coverage.get("rows_with_features"):
        lines += [
            "",
            "### Score By Forecast Gap Feature",
            "",
        ]
        lines += markdown_table(
            [
                "Forecast Gap",
                "Rows",
                "Model Brier",
                "Market Brier",
                "Brier Skill",
                "Model LogLoss",
                "Market LogLoss",
                "LogLoss Delta",
                "Base Rate",
            ],
            grouped_score_table_rows(results.get("score_by_feature_forecast_gap") or []),
        )

    lines += [
        "",
        "## Score Summary",
        "",
    ]
    lines += markdown_table(
        [
            "Scope",
            "Days",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        score_table_rows([
            ("All snapshots", results.get("aggregate_score")),
            ("Daily-first equal-day average", results.get("daily_first_score")),
            ("Last pre-close", results.get("last_pre_close_score")),
        ]),
    )

    lines += [
        "",
        "## Model Vs Market By Target Day",
        "",
    ]
    lines += markdown_table(
        [
            "Date",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_day", [])),
    )

    lines += [
        "",
        "## Model Vs Market By Capture Hour",
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_cutoff", [])),
    )

    lines += [
        "",
        "## Model Vs Market By Market-Bin Type",
        "",
    ]
    lines += markdown_table(
        [
            "Bin Type",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_bin_type", [])),
    )

    lines += [
        "",
        "## Fixed-Cutoff Performance",
        "",
        "Each row uses the first available snapshot at or after the cutoff hour for each day-band.",
        "",
    ]
    lines += markdown_table(
        [
            "Cutoff",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        [
            [
                f"{cutoff:02d}:00",
                score.get("n", "-"),
                fmt_num(score.get("model_brier")),
                fmt_num(score.get("market_brier")),
                fmt_signed(score.get("brier_skill_score"), 3),
                fmt_num(score.get("model_logloss")),
                fmt_num(score.get("market_logloss")),
                fmt_signed(score.get("logloss_delta")),
                fmt_pct(score.get("base_rate")),
            ]
            for cutoff, score in results.get("fixed_cutoff_scores", {}).items()
            if score
        ],
    )

    lines += [
        "",
        "## Realized Edge / P&L",
        "",
        "P&L is in shares (max +1 / -1 each). Per-snapshot overcounts correlated",
        "intraday signals; first-entry takes one trade per day-band at the first",
        "threshold crossing; last-pre-close takes one trade per day-band at the",
        "last available snapshot.",
        "",
    ]
    lines += markdown_table(
        [
            "Threshold",
            "Per-snapshot trades",
            "Per-snapshot P&L",
            "First-entry trades",
            "First-entry P&L",
            "Last-pre-close trades",
            "Last-pre-close P&L",
        ],
        [
            [
                f"{threshold:.2f}",
                results["pnl_per_snapshot"][threshold]["n"],
                fmt_pnl(results["pnl_per_snapshot"][threshold]["pnl"]),
                results["pnl_first_entry"][threshold]["n"],
                fmt_pnl(results["pnl_first_entry"][threshold]["pnl"]),
                results["pnl_last_pre_close"][threshold]["n"],
                fmt_pnl(results["pnl_last_pre_close"][threshold]["pnl"]),
            ]
            for threshold in thresholds
        ],
    )

    lines += [
        "",
        "## Overall Reliability",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} Reliability",
            "",
        ]
        lines += markdown_table(
            ["Confidence bin", "N", "Mean predicted", "Realized"],
            [
                [row["bin"], row["n"], fmt_pct(row["pred"]), fmt_pct(row["actual"])]
                for row in reliability(results["all_rows"], key)
            ],
        )
        lines.append("")

    lines += [
        "## Reliability By Capture Hour",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} By Hour",
            "",
        ]
        lines += markdown_table(
            ["Hour", "Confidence bin", "N", "Mean predicted", "Realized"],
            reliability_table_rows(grouped_reliability(results["all_rows"], key, "cutoff_hour")),
        )
        lines.append("")

    lines += [
        "## Reliability By Market Band",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} By Band",
            "",
        ]
        lines += markdown_table(
            ["Band", "Confidence bin", "N", "Mean predicted", "Realized"],
            reliability_table_rows(grouped_reliability(results["all_rows"], key, "band")),
        )
        lines.append("")

    lines += [
        "## Edge Persistence Per Band",
        "",
    ]
    lines += markdown_table(
        ["Date", "Band", "Snapshots", "Mean edge", "% edge up", "% edge down", "Settled YES?"],
        [
            [
                day["date"],
                item["band"],
                item["snapshots"],
                f"{item['mean_edge']:+.2f}",
                fmt_pct(item["frac_edge_up"]),
                fmt_pct(item["frac_edge_down"]),
                item["settled_yes"],
            ]
            for day in results["days"]
            for item in day["persistence"]
        ],
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_backtest(
    folders,
    daily_summary_path,
    overrides,
    thresholds,
    out_path,
    fixed_cutoffs=DEFAULT_FIXED_CUTOFF_HOURS,
    quality_grades=None,
):
    daily_index = load_daily_summary(daily_summary_path)
    allowed_quality = set(quality_grades or [])
    days, all_rows = [], []
    pnl_ps = {threshold: [] for threshold in thresholds}
    pnl_fe = {threshold: [] for threshold in thresholds}
    per_market_daily_indexes = {}

    for folder in folders:
        tape = Path(folder) / "snapshots_long.csv"
        if not tape.exists():
            print(f"  skip {folder}: no snapshots_long.csv")
            continue
        df = pd.read_csv(tape)
        slug = Path(folder).name
        target_date = date_from_event_slug(slug)
        label = load_market_day_label(Path(folder))
        grade = label.get("quality_grade") if label else "-"
        if allowed_quality and grade not in allowed_quality:
            print(f"  skip {slug}: quality {grade} not in {sorted(allowed_quality)}")
            continue
        spec = spec_for_slug(slug)
        day_daily_index = daily_index
        if spec and Path(daily_summary_path) == DEFAULT_DAILY_SUMMARY:
            if spec.id not in per_market_daily_indexes:
                per_market_daily_indexes[spec.id] = load_daily_summary(
                    spec.data_root / "daily" / "daily_summary.csv"
                )
            day_daily_index = per_market_daily_indexes[spec.id]
        feature_index = load_feature_vectors(folder)
        if label and label.get("settlement_bucket") is not None and not overrides:
            bucket = int(label["settlement_bucket"])
            label_source = "settlement_ledger" if label.get("schema_version") == "settlement_ledger_v1" else "settlement_json"
            source = f"{label_source}:{label.get('settlement_source') or 'unknown'}"
            note = label.get("note") or ""
        else:
            bucket, source, note = settlement_for_tape(df, target_date, day_daily_index, overrides)
        unit = spec.display_unit if spec else "C"
        rows, per_snap, first_entry, persistence = backtest_tape(
            df,
            bucket,
            thresholds,
            target_date=target_date,
            feature_index=feature_index,
        )
        # Settlement is already in the market's native unit (snapshot high).
        settlement_display = f"{bucket} {unit}" if bucket is not None else "-"
        all_rows.extend(rows)
        for threshold in thresholds:
            pnl_ps[threshold].append(per_snap[threshold])
            pnl_fe[threshold].append(first_entry[threshold])

        day_score = score_rows(rows)
        model_versions = unique_sorted(df["model_version"]) if "model_version" in df else []
        snapshot_count = int(df["snapshot_id"].nunique()) if "snapshot_id" in df else 0
        band_count = int(df["range_label"].nunique()) if "range_label" in df else 0
        days.append({
            "date": target_date.isoformat() if target_date else slug,
            "event_slug": slug,
            "folder": str(Path(folder)),
            "tape_path": str(tape),
            "snapshot_count": snapshot_count,
            "band_count": band_count,
            "model_versions": model_versions,
            "settlement": bucket,
            "settlement_display": settlement_display,
            "unit": unit,
            "source": source,
            "note": note,
            "quality_grade": grade,
            "rows": len(rows),
            "score": day_score,
            "persistence": persistence,
        })
        print(f"  {slug}: settlement {settlement_display} ({source}); {len(rows)} band-rows scored")

    last_rows = last_pre_close_rows(all_rows)
    fixed_rows = fixed_cutoff_rows(all_rows, fixed_cutoffs=fixed_cutoffs)

    results = {
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "model_versions": unique_sorted(row.get("model_version") for row in all_rows),
        "aggregate_score": score_rows(all_rows),
        "daily_first_score": daily_first_score(days),
        "last_pre_close_score": score_rows(last_rows),
        "fixed_cutoff_scores": {
            cutoff: score_rows(rows)
            for cutoff, rows in fixed_rows.items()
        },
        "score_by_day": grouped_scores(all_rows, "target_date"),
        "score_by_cutoff": grouped_scores(all_rows, "cutoff_hour"),
        "score_by_bin_type": grouped_scores(all_rows, "bin_type"),
        "score_by_feature_forecast_gap": grouped_scores(all_rows, "feature_forecast_gap_bucket"),
        "feature_vector_coverage": feature_vector_coverage(all_rows),
        "pnl_per_snapshot": {threshold: merge_pnl(pnl_ps[threshold]) for threshold in thresholds},
        "pnl_first_entry": {threshold: merge_pnl(pnl_fe[threshold]) for threshold in thresholds},
        "pnl_last_pre_close": pnl_for_rows(last_rows, thresholds),
        "fixed_cutoffs": tuple(fixed_cutoffs),
        "quality_filter": sorted(allowed_quality),
    }
    write_report(results, out_path, thresholds)
    return results


def parse_csv_numbers(value, type_fn=float):
    return [type_fn(item.strip()) for item in str(value).split(",") if item.strip()]


def main():
    parser = argparse.ArgumentParser(description="Settlement-scored model-vs-market backtest.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under snapshots root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--settle", action="append", default=[],
                        help="Force settlement: YYYY-MM-DD=BUCKET (repeatable).")
    parser.add_argument("--thresholds", default="0.05,0.10,0.15")
    parser.add_argument("--fixed-cutoffs", default=",".join(str(v) for v in DEFAULT_FIXED_CUTOFF_HOURS))
    parser.add_argument("--quality-grades", default="",
                        help="Comma-separated settlement label quality grades to include; empty includes all.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    overrides = {}
    for item in args.settle:
        d, _, b = item.partition("=")
        overrides[d.strip()] = int(b)
    thresholds = parse_csv_numbers(args.thresholds, float)
    fixed_cutoffs = parse_csv_numbers(args.fixed_cutoffs, int)
    quality_grades = [
        item.strip() for item in str(args.quality_grades).split(",")
        if item.strip()
    ]

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Backtesting {len(folders)} market day(s)...")
    results = run_backtest(
        folders,
        args.daily_summary,
        overrides,
        thresholds,
        args.out,
        fixed_cutoffs=fixed_cutoffs,
        quality_grades=quality_grades,
    )
    agg = results["aggregate_score"]
    daily = results["daily_first_score"]
    if agg:
        print(
            f"\nAll-snapshot model Brier {agg['model_brier']:.4f} vs "
            f"market {agg['market_brier']:.4f} (skill {agg['brier_skill_score']:+.3f})"
        )
    if daily:
        print(
            f"Daily-first model Brier {daily['model_brier']:.4f} vs "
            f"market {daily['market_brier']:.4f} (skill {daily['brier_skill_score']:+.3f})"
        )
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
