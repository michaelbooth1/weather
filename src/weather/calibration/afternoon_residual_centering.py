"""Afternoon post-ramp residual centering artifact.

The artifact learns the residual between a snapshot's model-implied expected
bucket and the settled bucket for local 15:00-18:00 snapshots. Runtime applies
the residual after forecast source debias and ramp dampening, so it corrects
only the remaining afternoon center error.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.artifacts import writable_artifact_path
from weather.backtesting.settled_days import discover_settled_folders
from weather.backtesting.settlement_io import DEFAULT_SNAPSHOTS_ROOT, load_market_day_label
from weather.calibration.forecast_error_model import regime_for_spec
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import all_specs, spec_for_id, spec_for_slug
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version
from weather.scoring.metrics import safe_float


SCHEMA_VERSION = schema_version("afternoon_residual_centering")
DEFAULT_ARTIFACT = writable_artifact_path("afternoon_residual_centering.json")
DEFAULT_REPORT = data_path() / "backtest" / "afternoon_residual_centering_report.md"
AFTERNOON_START_HOUR = 15
AFTERNOON_END_HOUR = 18
DEFAULT_MIN_CONTEXT_N = 4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def capture_hour(row):
    parsed = parse_time(row.get("captured_at_local") or row.get("captured_at_utc"))
    return parsed.hour if parsed else None


def band_midpoint(row):
    value = safe_float(row.get("bin_value_c") or row.get("bin_value") or row.get("value"))
    if value is None:
        return None
    value_hi = safe_float(row.get("bin_value_hi_c") or row.get("bin_value_hi") or row.get("value_hi"))
    if value_hi is None:
        value_hi = value
    return (float(value) + float(value_hi)) / 2.0


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def features_by_snapshot(folder):
    return {
        row.get("snapshot_id"): row
        for row in read_csv_rows(Path(folder) / "features_long.csv")
        if row.get("snapshot_id")
    }


def expected_bucket(rows):
    pairs = []
    for row in rows:
        probability = safe_float(row.get("model_probability"))
        midpoint = band_midpoint(row)
        if probability is None or midpoint is None:
            continue
        if probability < 0:
            continue
        pairs.append((midpoint, probability))
    total = sum(probability for _, probability in pairs)
    if total <= 0:
        return None
    return sum(midpoint * probability for midpoint, probability in pairs) / total


def _forecast_disagreement(snapshot_rows, feature_row):
    for row in snapshot_rows:
        value = safe_float(row.get("forecast_disagreement"))
        if value is not None:
            return value
    return safe_float((feature_row or {}).get("forecast_disagreement"))


def residual_rows_from_folder(folder):
    folder = Path(folder)
    label = load_market_day_label(folder) or {}
    settlement = safe_float(label.get("settlement_bucket") or label.get("settlement_high"))
    if settlement is None:
        return []
    spec = spec_for_slug(folder.name)
    market_id = (label.get("market_id") or (spec.id if spec else None) or "").strip()
    if not market_id:
        return []
    spec = spec_for_id(market_id)
    regime_id = regime_for_spec(spec)
    target_date = str(label.get("target_date") or date_from_event_slug(folder.name) or "")
    features = features_by_snapshot(folder)
    grouped = defaultdict(list)
    for row in read_csv_rows(folder / "snapshots_long.csv"):
        snapshot_id = row.get("snapshot_id")
        if snapshot_id:
            grouped[snapshot_id].append(row)

    rows = []
    for snapshot_id, snapshot_rows in grouped.items():
        hour = capture_hour(snapshot_rows[0])
        if hour is None or hour < AFTERNOON_START_HOUR or hour > AFTERNOON_END_HOUR:
            continue
        expected = expected_bucket(snapshot_rows)
        if expected is None:
            continue
        feature_row = features.get(snapshot_id) or {}
        residual = float(settlement) - expected
        rows.append({
            "market_id": market_id,
            "regime_id": regime_id,
            "target_date": target_date,
            "event_slug": folder.name,
            "snapshot_id": snapshot_id,
            "hour": hour,
            "settlement_bucket": float(settlement),
            "model_expected_bucket": expected,
            "residual": residual,
            "expected_minus_settlement": -residual,
            "forecast_disagreement": _forecast_disagreement(snapshot_rows, feature_row),
        })
    return rows


def discover_training_folders(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, markets=None):
    wanted = set(markets or [spec.id for spec in all_specs()])
    folders = []
    for market_id in sorted(wanted):
        folders.extend(discover_settled_folders(snapshots_root, required_file="snapshots_long.csv", market_id=market_id))
    return sorted(set(folders), key=lambda path: (date_from_event_slug(Path(path).name), Path(path).name))


def context_keys(row):
    market_id = row.get("market_id") or "unknown"
    regime_id = row.get("regime_id") or "unknown"
    hour = int(row.get("hour"))
    return [
        f"market={market_id}|hour={hour}",
        f"market={market_id}|afternoon",
        f"regime={regime_id}|hour={hour}",
        f"regime={regime_id}|afternoon",
        f"global|hour={hour}",
        "global",
    ]


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def summarize_rows(rows):
    residuals = [float(row["residual"]) for row in rows]
    warm_biases = [float(row["expected_minus_settlement"]) for row in rows]
    disagreements = [safe_float(row.get("forecast_disagreement")) for row in rows]
    if not residuals:
        return {}
    return {
        "n": len(residuals),
        "mean_residual": mean(residuals),
        "mean_expected_minus_settlement": mean(warm_biases),
        "mae_expected_minus_settlement": mean(abs(value) for value in warm_biases),
        "rmse_expected_minus_settlement": math.sqrt(mean(value * value for value in warm_biases)),
        "hot_share": mean(1.0 if value > 0 else 0.0 for value in warm_biases),
        "mean_forecast_disagreement": mean(disagreements),
    }


def fit_contexts(rows):
    grouped = defaultdict(list)
    for row in rows:
        for key in context_keys(row):
            grouped[key].append(row)
    return {
        key: summarize_rows(group_rows)
        for key, group_rows in sorted(grouped.items())
        if group_rows
    }


def selected_context(contexts, row, min_n=DEFAULT_MIN_CONTEXT_N):
    for key in context_keys(row):
        context = contexts.get(key)
        if context and int(context.get("n", 0)) >= int(min_n):
            return key, context
    return None, None


def validation_summary(rows, contexts, min_n=DEFAULT_MIN_CONTEXT_N):
    by_market = defaultdict(list)
    before = []
    after = []
    active = 0
    for row in rows:
        key, context = selected_context(contexts, row, min_n=min_n)
        shift = float((context or {}).get("mean_residual") or 0.0)
        if key:
            active += 1
        before_bias = float(row["expected_minus_settlement"])
        after_bias = (float(row["model_expected_bucket"]) + shift) - float(row["settlement_bucket"])
        before.append(before_bias)
        after.append(after_bias)
        by_market[row["market_id"]].append((before_bias, after_bias))
    return {
        "row_count": len(rows),
        "active_row_count": active,
        "mean_bias_before": mean(before),
        "mean_bias_after": mean(after),
        "mae_before": mean(abs(value) for value in before),
        "mae_after": mean(abs(value) for value in after),
        "hot_share_before": mean(1.0 if value > 0 else 0.0 for value in before),
        "hot_share_after": mean(1.0 if value > 0 else 0.0 for value in after),
        "by_market": {
            market_id: {
                "n": len(values),
                "mean_bias_before": mean(before_value for before_value, _ in values),
                "mean_bias_after": mean(after_value for _, after_value in values),
            }
            for market_id, values in sorted(by_market.items())
        },
    }


def build_artifact(rows, folders, generated_at_utc=None):
    contexts = fit_contexts(rows)
    markets = sorted({row["market_id"] for row in rows})
    target_dates = sorted({row["target_date"] for row in rows if row.get("target_date")})
    min_context_n = DEFAULT_MIN_CONTEXT_N
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_now(),
        "component": {
            "enabled": True,
            "start_hour": AFTERNOON_START_HOUR,
            "end_hour": AFTERNOON_END_HOUR,
            "min_context_n": min_context_n,
            "max_abs_shift": 2.0,
            "disagreement_reference": 3.0,
            "spread_sigma_base": 0.75,
            "spread_sigma_per_unit": 0.05,
            "spread_blend_base": 0.0,
            "spread_blend_per_unit": 0.05,
            "spread_blend_max": 0.35,
            "allow_global_fallback": False,
            "global_contexts": "diagnostic_only",
            "context_order": ["market_hour", "market_afternoon", "regime_hour", "regime_afternoon"],
        },
        "training": {
            "rows": len(rows),
            "folder_count": len(folders),
            "markets": markets,
            "market_count": len(markets),
            "target_date_min": target_dates[0] if target_dates else None,
            "target_date_max": target_dates[-1] if target_dates else None,
            "snapshot_folders": [str(Path(folder)) for folder in folders],
        },
        "contexts": contexts,
        "validation": validation_summary(rows, contexts, min_n=min_context_n),
    }


def render_report(artifact):
    validation = artifact.get("validation") or {}
    lines = [
        "# Afternoon Residual Centering",
        "",
        f"Generated: {artifact.get('generated_at_utc')}",
        f"Schema: `{artifact.get('schema_version')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Rows", validation.get("row_count")],
                ["Active rows", validation.get("active_row_count")],
                ["Mean bias before", fmt_num(validation.get("mean_bias_before"), 4)],
                ["Mean bias after", fmt_num(validation.get("mean_bias_after"), 4)],
                ["MAE before", fmt_num(validation.get("mae_before"), 4)],
                ["MAE after", fmt_num(validation.get("mae_after"), 4)],
                ["Hot share before", fmt_num(validation.get("hot_share_before"), 4)],
                ["Hot share after", fmt_num(validation.get("hot_share_after"), 4)],
            ],
        ),
        "",
        "## Market Bias",
        "",
        *markdown_table(
            ["Market", "N", "Before", "After"],
            [
                [
                    market_id,
                    row.get("n"),
                    fmt_num(row.get("mean_bias_before"), 4),
                    fmt_num(row.get("mean_bias_after"), 4),
                ]
                for market_id, row in sorted((validation.get("by_market") or {}).items())
            ],
        ),
        "",
        "## Contexts",
        "",
        *markdown_table(
            ["Context", "N", "Residual", "Warm Bias", "MAE", "Hot Share", "Disagreement"],
            [
                [
                    key,
                    row.get("n"),
                    fmt_num(row.get("mean_residual"), 4),
                    fmt_num(row.get("mean_expected_minus_settlement"), 4),
                    fmt_num(row.get("mae_expected_minus_settlement"), 4),
                    fmt_num(row.get("hot_share"), 4),
                    fmt_num(row.get("mean_forecast_disagreement"), 4),
                ]
                for key, row in sorted((artifact.get("contexts") or {}).items())
                if key.startswith("market=")
            ][:80],
        ),
        "",
    ]
    return "\n".join(lines)


def write_outputs(artifact, artifact_out=DEFAULT_ARTIFACT, report_out=DEFAULT_REPORT):
    artifact_path = Path(artifact_out)
    report_path = Path(report_out)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_path.write_text(render_report(artifact), encoding="utf-8")
    return artifact_path, report_path


def build_from_folders(folders):
    rows = []
    for folder in folders:
        rows.extend(residual_rows_from_folder(folder))
    return rows


def cmd_train(args):
    markets = [item.strip() for item in str(args.markets or "").split(",") if item.strip()] or None
    folders = discover_training_folders(args.snapshots_root, markets=markets)
    rows = build_from_folders(folders)
    if not rows:
        raise SystemExit("No afternoon residual rows found.")
    artifact = build_artifact(rows, folders)
    artifact_path, report_path = write_outputs(artifact, args.artifact, args.report)
    validation = artifact.get("validation") or {}
    print(f"Wrote afternoon residual centering artifact to {artifact_path}")
    print(f"Wrote afternoon residual centering report to {report_path}")
    print(
        "Afternoon mean bias "
        f"{fmt_num(validation.get('mean_bias_before'), 4)} -> {fmt_num(validation.get('mean_bias_after'), 4)}; "
        f"hot share {fmt_num(validation.get('hot_share_before'), 4)} -> {fmt_num(validation.get('hot_share_after'), 4)}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Train afternoon post-ramp residual centering artifact.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--markets", default="", help="Comma-separated market IDs; default all registered markets.")
    train.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    train.add_argument("--report", default=str(DEFAULT_REPORT))
    train.set_defaults(func=cmd_train)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
