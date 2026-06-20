"""Ablation summaries and report rendering for feature-model calibration."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime

from weather.model.feature_store import FEATURE_SCHEMA_VERSION


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        try:
            return value.date()
        except (TypeError, ValueError):
            pass
    return date.fromisoformat(str(value)[:10])


def summarize_ablation_by_family(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["family"]].append(row)
    summary = []
    for family, family_rows in sorted(grouped.items()):
        n = sum(row["n"] for row in family_rows)
        if n <= 0:
            continue
        summary.append({
            "family": family,
            "n": n,
            "full_logloss": sum(row["full_logloss"] * row["n"] for row in family_rows) / n,
            "ablated_logloss": sum(row["ablated_logloss"] * row["n"] for row in family_rows) / n,
            "delta_logloss": sum(row["delta_logloss"] * row["n"] for row in family_rows) / n,
            "full_brier": sum(row["full_brier"] * row["n"] for row in family_rows) / n,
            "ablated_brier": sum(row["ablated_brier"] * row["n"] for row in family_rows) / n,
            "delta_brier": sum(row["delta_brier"] * row["n"] for row in family_rows) / n,
        })
    return sorted(summary, key=lambda row: row["delta_logloss"], reverse=True)


MONTH_LABELS = {
    1: "01-Jan",
    2: "02-Feb",
    3: "03-Mar",
    4: "04-Apr",
    5: "05-May",
    6: "06-Jun",
    7: "07-Jul",
    8: "08-Aug",
    9: "09-Sep",
    10: "10-Oct",
    11: "11-Nov",
    12: "12-Dec",
}


def ablation_month_label(value):
    return MONTH_LABELS[_as_date(value).month]


def ablation_season_label(value):
    month = _as_date(value).month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


def summarize_ablation_by_group(rows, group_keys):
    grouped = defaultdict(list)
    for row in rows:
        key = tuple(row.get(group_key) for group_key in group_keys) + (row["family"],)
        grouped[key].append(row)
    summary = []
    for key, group_rows in sorted(grouped.items()):
        n = sum(row["n"] for row in group_rows)
        if n <= 0:
            continue
        group_values = dict(zip(group_keys, key[:-1]))
        summary.append({
            **group_values,
            "family": key[-1],
            "n": n,
            "full_logloss": sum(row["full_logloss"] * row["n"] for row in group_rows) / n,
            "ablated_logloss": sum(row["ablated_logloss"] * row["n"] for row in group_rows) / n,
            "delta_logloss": sum(row["delta_logloss"] * row["n"] for row in group_rows) / n,
            "full_brier": sum(row["full_brier"] * row["n"] for row in group_rows) / n,
            "ablated_brier": sum(row["ablated_brier"] * row["n"] for row in group_rows) / n,
            "delta_brier": sum(row["delta_brier"] * row["n"] for row in group_rows) / n,
        })
    return sorted(summary, key=lambda row: tuple(row.get(key) for key in group_keys) + (row["family"],))


def ablation_table_row(row, include_hour=False):
    prefix = f"| {row['hour']:02d}:00 | " if include_hour else "| "
    return (
        f"{prefix}{row['family']} | {row['n']} | "
        f"{row['full_logloss']:.4f} | {row['ablated_logloss']:.4f} | "
        f"{row['delta_logloss']:+.4f} | {row['full_brier']:.4f} | "
        f"{row['ablated_brier']:.4f} | {row['delta_brier']:+.4f} |"
    )


def ablation_group_table_row(row, group_keys):
    prefix = "".join(f"| {row.get(key)} " for key in group_keys)
    return (
        f"{prefix}| {row['family']} | {row['n']} | "
        f"{row['full_logloss']:.4f} | {row['ablated_logloss']:.4f} | "
        f"{row['delta_logloss']:+.4f} | {row['full_brier']:.4f} | "
        f"{row['ablated_brier']:.4f} | {row['delta_brier']:+.4f} |"
    )


def ablation_observation(hour, val_date, family, full_loss, ablated_loss, full_brier, ablated_brier):
    return {
        "hour": int(hour),
        "month": ablation_month_label(val_date),
        "season": ablation_season_label(val_date),
        "family": family,
        "n": 1,
        "full_logloss": full_loss,
        "ablated_logloss": ablated_loss,
        "delta_logloss": ablated_loss - full_loss,
        "full_brier": full_brier,
        "ablated_brier": ablated_brier,
        "delta_brier": ablated_brier - full_brier,
    }


def feature_family_promotion_decisions(rows, min_rows=100):
    decisions = []
    for row in summarize_ablation_by_family(rows):
        if row["n"] < min_rows:
            decision = "shadow"
            reason = f"needs at least {min_rows} held-out rows"
        elif row["delta_logloss"] > 0.0 and row["delta_brier"] > 0.0:
            decision = "promote"
            reason = "positive held-out log-loss and Brier deltas"
        else:
            decision = "block"
            reason = "non-positive held-out log-loss or Brier delta"
        decisions.append({
            **row,
            "decision": decision,
            "reason": reason,
        })
    return decisions


def _fmt_metric(value):
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def write_item27_feature_value_report(
    spec,
    validation_rows,
    ablation_rows,
    report_path,
    json_path=None,
    n_splits=5,
):
    decisions = feature_family_promotion_decisions(ablation_rows)
    lines = [
        "# Roadmap Item 27: Weather Feature Value Gate",
        "",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Market: `{spec.id}`",
        f"Unit: `{spec.unit}`",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Validation: {n_splits}-fold deterministic day split by target date ordinal",
        "",
        "This report scores held-out target days with settlement-style log-loss "
        "and Brier metrics, then neutralizes one feature family at a time. "
        "Positive ablation deltas mean the family improved held-out score.",
        "",
        "## Held-Out Model Score By Cutoff",
        "",
        "| Cutoff | Rows | Baseline LogLoss | HGB LogLoss | Skill | Baseline Brier | HGB Brier | Skill | Folds | Skipped |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in sorted(validation_rows, key=lambda item: item["hour"]):
        lines.append(
            f"| {row['hour']:02d}:00 | {row['n']} | "
            f"{_fmt_metric(row['baseline_logloss'])} | {_fmt_metric(row['full_logloss'])} | "
            f"{row['delta_logloss_vs_baseline']:+.4f} | "
            f"{_fmt_metric(row['baseline_brier'])} | {_fmt_metric(row['full_brier'])} | "
            f"{row['delta_brier_vs_baseline']:+.4f} | {row['folds']} | {row['skipped_folds']} |"
        )

    lines += [
        "",
        "## Blocked Validation Audit",
        "",
        "The model score above still uses deterministic modulo day folds. "
        "Rows below audit stricter market-day and blocked-date partitions so "
        "feature-value claims are not treated as promotion-grade when the "
        "blocked evidence is missing or leaky.",
        "",
        "| Cutoff | Risk Verdict | Audit OK | Market Days | Target Dates | Splits | Leaks |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in sorted(validation_rows, key=lambda item: item["hour"]):
        audit = row.get("blocked_validation") or {}
        lines.append(
            f"| {row['hour']:02d}:00 | {row.get('leakage_risk_verdict') or '-'} | "
            f"{'PASS' if audit.get('ok') else 'FAIL'} | "
            f"{audit.get('market_day_count', 0)} | {audit.get('target_date_count', 0)} | "
            f"{audit.get('split_count', 0)} | {audit.get('leak_count', 0)} |"
        )

    lines += [
        "",
        "## Feature-Family Promotion Decisions",
        "",
        "Decision is `promote` only when the feature family improves both "
        "held-out log-loss and Brier over the neutralized-family variant.",
        "",
        "| Family | Decision | Rows | Delta LogLoss | Delta Brier | Reason |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in decisions:
        lines.append(
            f"| {row['family']} | {row['decision']} | {row['n']} | "
            f"{row['delta_logloss']:+.4f} | {row['delta_brier']:+.4f} | "
            f"{row['reason']} |"
        )

    lines += [
        "",
        "## Feature-Family Value By Month",
        "",
        "| Month | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in summarize_ablation_by_group(ablation_rows, ["month"]):
        lines.append(ablation_group_table_row(row, ["month"]))

    lines += [
        "",
        "## Feature-Family Value By Season",
        "",
        "| Season | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in summarize_ablation_by_group(ablation_rows, ["season"]):
        lines.append(ablation_group_table_row(row, ["season"]))

    lines += [
        "",
        "## Feature-Family Value By Cutoff And Month",
        "",
        "| Cutoff | Month | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in summarize_ablation_by_group(ablation_rows, ["hour", "month"]):
        lines.append(ablation_group_table_row(row, ["hour", "month"]))

    report_path = os.fspath(report_path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    payload = {
        "schema_version": "item27_feature_value_gate_v0.1",
        "generated_at": datetime.now().isoformat(),
        "market": spec.id,
        "unit": spec.unit,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "validation": {
            "method": "deterministic_day_fold",
            "n_splits": n_splits,
        },
        "validation_rows": validation_rows,
        "promotion_decisions": decisions,
        "by_month": summarize_ablation_by_group(ablation_rows, ["month"]),
        "by_season": summarize_ablation_by_group(ablation_rows, ["season"]),
        "by_hour_month": summarize_ablation_by_group(ablation_rows, ["hour", "month"]),
    }
    if json_path is not None:
        json_path = os.fspath(json_path)
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
    return payload


def write_late_day_continuation_report(spec, validation_rows, ablation_rows, report_path):
    lines = [
        "# Late-Day Continuation Model Validation",
        "",
        f"Market: `{spec.id}` ({spec.unit})",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This report scores the 15:00, 16:00, and 17:00 continuation classifiers directly.",
        "The trained feature set includes `forecast_high` and `forecast_gap`.",
        "",
    ]
    if validation_rows:
        lines += [
            "| Cutoff | Rows | Continuation Rate | LogLoss | Brier | ECE |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in sorted(validation_rows, key=lambda item: item["hour"]):
            lines.append(
                f"| {row['hour']:02d}:00 | {row['n']} | "
                f"{row['event_rate']:.3f} | {row['logloss']:.4f} | "
                f"{row['brier']:.4f} | {row['ece']:.4f} |"
            )
    else:
        lines.append("No late-day validation rows were available.")

    if ablation_rows:
        lines += [
            "",
            "## Feature-Family Ablation",
            "",
            "Positive deltas mean the feature family helped the continuation classifier.",
            "",
            "| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in summarize_ablation_by_family(ablation_rows):
            lines.append(ablation_table_row(row))
        lines += [
            "",
            "## Ablation By Cutoff",
            "",
            "| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in sorted(ablation_rows, key=lambda item: (item["hour"], item["family"])):
            lines.append(ablation_table_row(row, include_hour=True))

    report_path = os.fspath(report_path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path
