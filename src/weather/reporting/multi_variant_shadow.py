"""Multi-variant shadow scoring and governance.

This module owns the common evidence layer for running several shadow model
variants over the same settled rows. It does not serve a model and does not
select a promotion candidate; it normalizes variant probabilities into a
long-form table, scores paired deltas, and reports experiment-governance issues.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.backtesting.backtest import (
    expected_calibration_error,
    fmt_num,
    fmt_pct,
    fmt_signed,
    group_sort_key,
    markdown_table,
    score_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("multi_variant_shadow")
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "multi_variant_shadow.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "multi_variant_shadow_report.md"
DEFAULT_LONG_OUT = DEFAULT_BACKTEST_ROOT / "multi_variant_shadow_long.csv"
MAX_NON_CONTROL_VARIANTS = 4

LONG_TABLE_COLUMNS = [
    "variant_id",
    "variant_family",
    "uses_market_features",
    "is_control",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "outcome",
    "artifact_hash",
    "postprocess_config_hash",
    "experiment_start_date",
    "captured_at_local",
    "range_label",
    "bin_type",
    "bin_value",
    "cutoff_hour",
]

REQUIRED_FIELDS = [
    "variant_id",
    "variant_family",
    "market_id",
    "target_date",
    "snapshot_id",
    "band_key",
    "probability",
    "current_probability",
    "market_yes",
    "outcome",
]

FLOAT_FIELDS = {
    "probability",
    "current_probability",
    "recorded_probability",
    "market_yes",
    "bin_value",
    "cutoff_hour",
}

BOOL_TRUE = {"1", "true", "yes", "y", "on"}
BOOL_FALSE = {"0", "false", "no", "n", "off", ""}

ALIASES = {
    "probability": ("probability", "candidate_p", "model_probability", "variant_probability"),
    "current_probability": ("current_probability", "replayed_p", "current_p"),
    "recorded_probability": ("recorded_probability", "recorded_p"),
    "market_yes": ("market_yes", "market_probability"),
    "band_key": ("band_key", "range_label"),
    "target_date": ("target_date", "market_date"),
    "cutoff_hour": ("cutoff_hour", "candidate_cutoff_hour"),
    "variant_family": ("variant_family", "family"),
}


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _first_value(row, field):
    for key in ALIASES.get(field, (field,)):
        value = row.get(key)
        if value not in (None, ""):
            return value
    return row.get(field)


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clamp_probability(value):
    value = maybe_float(value)
    if value is None:
        return None
    return max(0.0, min(1.0, value))


def parse_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in BOOL_TRUE:
        return True
    if text in BOOL_FALSE:
        return False
    return bool(default)


def normalize_row(raw, row_number=None):
    """Return a canonical long-table row plus validation errors."""
    errors = []
    out = {}
    for field in LONG_TABLE_COLUMNS:
        value = _first_value(raw, field)
        if field in FLOAT_FIELDS:
            value = maybe_float(value)
        elif field in {"uses_market_features", "is_control"}:
            value = parse_bool(value)
        elif value is not None:
            value = str(value)
        out[field] = value

    if not out["variant_family"]:
        out["variant_family"] = out["variant_id"]
    if out["band_key"] in (None, ""):
        out["band_key"] = out.get("range_label")

    out["probability"] = clamp_probability(out["probability"])
    out["current_probability"] = clamp_probability(out["current_probability"])
    out["recorded_probability"] = clamp_probability(out["recorded_probability"])
    out["market_yes"] = clamp_probability(out["market_yes"])

    outcome = maybe_float(_first_value(raw, "outcome"))
    if outcome is None:
        out["outcome"] = None
    else:
        out["outcome"] = int(round(outcome))
        if out["outcome"] not in {0, 1}:
            errors.append("outcome must be 0 or 1")

    for field in REQUIRED_FIELDS:
        if out.get(field) in (None, ""):
            errors.append(f"missing required field: {field}")

    if row_number is not None:
        out["_row_number"] = row_number
    return out, errors


def normalize_rows(raw_rows):
    rows = []
    errors = []
    for index, raw in enumerate(raw_rows, start=1):
        row, row_errors = normalize_row(raw, row_number=index)
        if row_errors:
            errors.append({
                "row_number": index,
                "variant_id": row.get("variant_id"),
                "errors": row_errors,
            })
            continue
        rows.append(row)
    return rows, errors


def _score_field(rows, probability_field):
    view = []
    for row in rows:
        probability = row.get(probability_field)
        if probability is None:
            continue
        view.append({
            "model_probability": float(probability),
            "market_yes": float(row["market_yes"]),
            "outcome": int(row["outcome"]),
        })
    if not view:
        return None
    return score_rows(view)


def comparison(rows):
    """Variant versus current serving, recorded tape, and market on same rows."""
    variant = _score_field(rows, "probability")
    current = _score_field(rows, "current_probability")
    recorded = _score_field(rows, "recorded_probability")
    if not variant or not current:
        return None
    ece_rows = [
        {"model_probability": row["probability"], "outcome": row["outcome"]}
        for row in rows
        if row.get("probability") is not None
    ]
    output = {
        "n": variant["n"],
        "variant_brier": variant["model_brier"],
        "current_brier": current["model_brier"],
        "recorded_brier": recorded["model_brier"] if recorded else None,
        "market_brier": variant["market_brier"],
        "variant_logloss": variant["model_logloss"],
        "current_logloss": current["model_logloss"],
        "recorded_logloss": recorded["model_logloss"] if recorded else None,
        "market_logloss": variant["market_logloss"],
        "variant_skill": variant["brier_skill_score"],
        "variant_ece": expected_calibration_error(ece_rows, "model_probability"),
        "delta_vs_current": variant["model_brier"] - current["model_brier"],
        "delta_vs_recorded": (
            variant["model_brier"] - recorded["model_brier"]
            if recorded else None
        ),
        "delta_vs_market": variant["model_brier"] - variant["market_brier"],
        "base_rate": variant["base_rate"],
    }
    return output


def daily_first_comparison(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"))].append(row)
    comps = [comparison(group_rows) for group_rows in grouped.values()]
    comps = [comp for comp in comps if comp]
    if not comps:
        return None

    def avg(key):
        values = [comp[key] for comp in comps if comp.get(key) is not None]
        return sum(values) / len(values) if values else None

    return {
        "n_days": len(comps),
        "n": sum(comp.get("n", 0) for comp in comps),
        "variant_brier": avg("variant_brier"),
        "current_brier": avg("current_brier"),
        "recorded_brier": avg("recorded_brier"),
        "market_brier": avg("market_brier"),
        "variant_logloss": avg("variant_logloss"),
        "current_logloss": avg("current_logloss"),
        "market_logloss": avg("market_logloss"),
        "variant_skill": avg("variant_skill"),
        "variant_ece": avg("variant_ece"),
        "delta_vs_current": avg("delta_vs_current"),
        "delta_vs_market": avg("delta_vs_market"),
        "base_rate": avg("base_rate"),
    }


def grouped_comparison(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def variant_metadata(rows):
    first = rows[0] if rows else {}
    return {
        "variant_id": first.get("variant_id"),
        "variant_family": first.get("variant_family"),
        "uses_market_features": bool(first.get("uses_market_features")),
        "is_control": bool(first.get("is_control")),
        "artifact_hash": first.get("artifact_hash"),
        "postprocess_config_hash": first.get("postprocess_config_hash"),
        "experiment_start_date": first.get("experiment_start_date"),
    }


def variant_summary(rows):
    by_variant = defaultdict(list)
    for row in rows:
        by_variant[row["variant_id"]].append(row)
    output = []
    for variant_id, variant_rows in sorted(by_variant.items()):
        metadata = variant_metadata(variant_rows)
        output.append({
            **metadata,
            "rows": len(variant_rows),
            "markets": sorted({row["market_id"] for row in variant_rows}),
            "market_days": len({
                (row["market_id"], row["target_date"])
                for row in variant_rows
            }),
            "aggregate": comparison(variant_rows),
            "daily_first": daily_first_comparison(variant_rows),
            "by_market": grouped_comparison(variant_rows, "market_id"),
            "by_cutoff_hour": grouped_comparison(variant_rows, "cutoff_hour"),
        })
    return output


def governance_issues(rows, variants, max_non_control_variants=MAX_NON_CONTROL_VARIANTS):
    issues = []
    by_family = defaultdict(list)
    for variant in variants:
        if not variant.get("is_control"):
            by_family[variant["variant_family"]].append(variant)
    for family, family_variants in sorted(by_family.items()):
        if len(family_variants) > max_non_control_variants:
            issues.append({
                "severity": "error",
                "category": "variant_limit",
                "detail": (
                    f"{family} has {len(family_variants)} non-control variants; "
                    f"limit is {max_non_control_variants}"
                ),
            })

    for variant in variants:
        missing = [
            field for field in ("artifact_hash", "postprocess_config_hash", "experiment_start_date")
            if not variant.get(field)
        ]
        if missing:
            issues.append({
                "severity": "warning",
                "category": "variant_metadata",
                "variant_id": variant["variant_id"],
                "detail": f"missing immutable metadata: {', '.join(missing)}",
            })

    market_informed = [variant for variant in variants if variant.get("uses_market_features")]
    if market_informed:
        issues.append({
            "severity": "info",
            "category": "track_separation",
            "detail": (
                f"{len(market_informed)} market-informed variant(s) present; "
                "do not use them for no-market weather-model edge claims"
            ),
        })
    return issues


def track_summary(variants):
    tracks = {}
    for track_name, use_market in [
        ("no_market", False),
        ("market_informed", True),
    ]:
        selected = [
            variant for variant in variants
            if bool(variant.get("uses_market_features")) is use_market
        ]
        tracks[track_name] = {
            "variant_count": len(selected),
            "variant_ids": [variant["variant_id"] for variant in selected],
            "best_daily_first_delta_vs_current": _best_delta(selected, "daily_first", "delta_vs_current"),
            "best_daily_first_delta_vs_market": _best_delta(selected, "daily_first", "delta_vs_market"),
        }
    return tracks


def _best_delta(variants, score_key, metric):
    rows = []
    for variant in variants:
        score = variant.get(score_key) or {}
        value = score.get(metric)
        if value is not None:
            rows.append((float(value), variant["variant_id"]))
    if not rows:
        return None
    value, variant_id = min(rows)
    return {"variant_id": variant_id, "value": value}


def build_payload(raw_rows, max_non_control_variants=MAX_NON_CONTROL_VARIANTS):
    raw_rows = list(raw_rows)
    rows, errors = normalize_rows(raw_rows)
    variants = variant_summary(rows)
    issues = governance_issues(
        rows,
        variants,
        max_non_control_variants=max_non_control_variants,
    )
    error_count = len(errors) + sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    status = "ERROR" if error_count else ("WARN" if warning_count else "OK")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "summary": {
            "raw_rows": len(raw_rows),
            "scored_rows": len(rows),
            "variant_count": len(variants),
            "market_count": len({row["market_id"] for row in rows}),
            "market_day_count": len({(row["market_id"], row["target_date"]) for row in rows}),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "limits": {
            "max_non_control_variants_per_family": int(max_non_control_variants),
        },
        "long_table_columns": list(LONG_TABLE_COLUMNS),
        "validation_errors": errors,
        "governance_issues": issues,
        "tracks": track_summary(variants),
        "variants": variants,
        "rows": rows,
    }


def _read_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("rows", "predictions", "variant_rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"{path} is not a JSON array or object with rows/predictions")


def read_prediction_rows(paths):
    rows = []
    for path in paths:
        path = Path(path)
        if path.suffix.lower() == ".jsonl":
            with path.open("r", encoding="utf-8") as handle:
                rows.extend(json.loads(line) for line in handle if line.strip())
        elif path.suffix.lower() == ".json":
            rows.extend(_read_json(path))
        else:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows.extend(dict(row) for row in csv.DictReader(handle))
    return rows


def write_json(path, payload, include_rows=True):
    copy = dict(payload)
    if not include_rows:
        copy.pop("rows", None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(copy, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_long_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LONG_TABLE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in LONG_TABLE_COLUMNS})
    return path


def _variant_rows(variants):
    rows = []
    for variant in variants:
        daily = variant.get("daily_first") or {}
        aggregate = variant.get("aggregate") or {}
        rows.append([
            variant.get("variant_id"),
            variant.get("variant_family"),
            "market" if variant.get("uses_market_features") else "no-market",
            "yes" if variant.get("is_control") else "no",
            variant.get("market_days", 0),
            variant.get("rows", 0),
            fmt_num(daily.get("variant_brier")),
            fmt_num(daily.get("current_brier")),
            fmt_num(daily.get("market_brier")),
            fmt_signed(daily.get("delta_vs_current"), 4),
            fmt_signed(daily.get("delta_vs_market"), 4),
            fmt_num(daily.get("variant_ece")),
            fmt_num(aggregate.get("variant_brier")),
            fmt_signed(aggregate.get("delta_vs_current"), 4),
            fmt_signed(aggregate.get("delta_vs_market"), 4),
        ])
    return rows


def _issue_rows(issues):
    return [
        [
            issue.get("severity"),
            issue.get("category"),
            issue.get("variant_id") or "-",
            issue.get("detail") or "-",
        ]
        for issue in issues
    ]


def _market_rows(variant):
    rows = []
    for item in variant.get("by_market") or []:
        rows.append([
            item.get("group"),
            item.get("n", 0),
            fmt_num(item.get("variant_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_current"), 4),
            fmt_signed(item.get("delta_vs_market"), 4),
            fmt_pct(item.get("base_rate")),
        ])
    return rows


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Multi-Variant Shadow Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Raw rows", summary.get("raw_rows", 0)],
            ["Scored rows", summary.get("scored_rows", 0)],
            ["Variants", summary.get("variant_count", 0)],
            ["Markets", summary.get("market_count", 0)],
            ["Market-days", summary.get("market_day_count", 0)],
            [
                "Max non-control variants/family",
                (payload.get("limits") or {}).get("max_non_control_variants_per_family"),
            ],
            ["Errors", summary.get("error_count", 0)],
            ["Warnings", summary.get("warning_count", 0)],
        ],
    )
    lines += [
        "",
        "## Variant Scores",
        "",
        "Daily-first scores are the primary comparison. Aggregate row-weighted",
        "scores are secondary diagnostics because band rows within a market-day",
        "are correlated.",
        "",
    ]
    lines += markdown_table(
        [
            "Variant", "Family", "Track", "Control", "Days", "Rows",
            "Daily Brier", "Current Brier", "Market Brier",
            "Delta Current", "Delta Market", "ECE",
            "Agg Brier", "Agg Delta Current", "Agg Delta Market",
        ],
        _variant_rows(payload.get("variants") or []),
    )

    issues = payload.get("governance_issues") or []
    errors = payload.get("validation_errors") or []
    if issues or errors:
        lines += ["", "## Governance", ""]
        if issues:
            lines += markdown_table(
                ["Severity", "Category", "Variant", "Detail"],
                _issue_rows(issues),
            )
        if errors:
            lines += ["", "### Validation Errors", ""]
            for error in errors[:50]:
                lines.append(
                    f"- row {error.get('row_number')}: "
                    f"{'; '.join(error.get('errors') or [])}"
                )
            if len(errors) > 50:
                lines.append(f"- ... {len(errors) - 50} more")

    tracks = payload.get("tracks") or {}
    lines += ["", "## Track Separation", ""]
    lines += markdown_table(
        ["Track", "Variants", "Best Delta Current", "Best Delta Market"],
        [
            [
                name,
                ", ".join(track.get("variant_ids") or []) or "-",
                _fmt_best(track.get("best_daily_first_delta_vs_current")),
                _fmt_best(track.get("best_daily_first_delta_vs_market")),
            ]
            for name, track in tracks.items()
        ],
    )

    for variant in payload.get("variants") or []:
        lines += ["", f"## {variant.get('variant_id')} By Market", ""]
        lines += markdown_table(
            [
                "Market", "Rows", "Variant Brier", "Current Brier",
                "Market Brier", "Delta Current", "Delta Market", "Base Rate",
            ],
            _market_rows(variant),
        )
    return "\n".join(lines) + "\n"


def _fmt_best(row):
    if not row:
        return "-"
    return f"{row.get('variant_id')}: {fmt_signed(row.get('value'), 4)}"


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Score a long-form multi-variant shadow prediction table."
    )
    parser.add_argument("predictions", nargs="+", help="CSV, JSON, or JSONL prediction rows.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--long-out", default=str(DEFAULT_LONG_OUT))
    parser.add_argument("--max-non-control-variants", type=int, default=MAX_NON_CONTROL_VARIANTS)
    parser.add_argument("--omit-rows-from-json", action="store_true")
    parser.add_argument("--fail-on-error", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_rows = read_prediction_rows(args.predictions)
    payload = build_payload(
        raw_rows,
        max_non_control_variants=args.max_non_control_variants,
    )
    write_long_csv(args.long_out, payload["rows"])
    write_json(args.json_out, payload, include_rows=not args.omit_rows_from_json)
    write_report(args.report_out, payload)
    print(f"Multi-variant shadow report: {payload['status']}")
    print(f"Long table written to {args.long_out}")
    print(f"JSON written to {args.json_out}")
    print(f"Report written to {args.report_out}")
    if args.fail_on_error and payload["status"] == "ERROR":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
