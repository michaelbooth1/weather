"""Attribute distribution-stage score deltas from persisted component snapshots."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.model.model_presentation import DRIVER_WATERFALL_STAGES
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("distribution_stage_attribution")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "distribution_stage_attribution.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "distribution_stage_attribution_report.md"
COMPONENT_FILENAME = "components_long.csv"
SETTLEMENT_FILENAME = "settlement.json"
EPSILON = 1e-9

STAGE_ORDER = tuple(key for key, _label in DRIVER_WATERFALL_STAGES)
STAGE_LABELS = dict(DRIVER_WATERFALL_STAGES)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(number)


def label_numbers(value):
    if not value:
        return []
    return [int(match.group(0)) for match in re.finditer(r"(?<!\d)-?\d+", str(value))]


def band_key(row):
    kind = (row.get("bin_kind") or row.get("kind") or "").lower()
    value = maybe_int(row.get("bin_value_c") or row.get("bin_value") or row.get("value"))
    value_hi = maybe_int(row.get("bin_value_hi") or row.get("value_hi"))
    nums = label_numbers(row.get("range_label"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None:
        value_hi = nums[-1] if kind == "eq" and len(nums) >= 2 else value
    return kind, value, value_hi


def band_outcome(row, settlement_bucket):
    if settlement_bucket is None:
        return None
    kind, value, value_hi = band_key(row)
    if value is None:
        return None
    if kind == "lte":
        return int(settlement_bucket <= value)
    if kind == "gte":
        return int(settlement_bucket >= value)
    if value_hi is None:
        value_hi = value
    return int(value <= settlement_bucket <= value_hi)


def binary_logloss(probability, outcome):
    p = max(EPSILON, min(1.0 - EPSILON, float(probability)))
    return -(outcome * math.log(p) + (1 - outcome) * math.log(1.0 - p))


def binary_brier(probability, outcome):
    return (float(probability) - int(outcome)) ** 2


def effective_band_spread(probability):
    p = max(0.0, min(1.0, float(probability)))
    return 4.0 * p * (1.0 - p)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def component_folders(snapshots_root):
    root = Path(snapshots_root)
    if not root.exists():
        return []
    return sorted(folder for folder in root.iterdir() if (folder / COMPONENT_FILENAME).exists())


def _score_component_row(row, folder, settlement):
    probability = maybe_float(row.get("component_probability"))
    settlement_bucket = maybe_int(settlement.get("settlement_bucket"))
    outcome = band_outcome(row, settlement_bucket)
    component_name = row.get("component_name")
    snapshot_id = row.get("snapshot_id")
    if probability is None or outcome is None or not component_name or not snapshot_id:
        return None
    probability = max(0.0, min(1.0, probability))
    kind, value, value_hi = band_key(row)
    return {
        "event_slug": row.get("event_slug") or settlement.get("event_slug") or folder.name,
        "market_id": settlement.get("market_id") or "",
        "target_date": settlement.get("target_date") or "",
        "snapshot_id": snapshot_id,
        "captured_at_local": row.get("captured_at_local") or "",
        "cutoff_hour": row.get("cutoff_hour") or "",
        "active_model_kind": row.get("active_model_kind") or "",
        "stage_regime": row.get("active_model_kind") or "unknown",
        "component_name": component_name,
        "component_label": STAGE_LABELS.get(component_name, component_name),
        "band_kind": kind,
        "band_value": value,
        "band_value_hi": value_hi,
        "outcome": outcome,
        "probability": probability,
        "brier": binary_brier(probability, outcome),
        "logloss": binary_logloss(probability, outcome),
        "effective_band_spread": effective_band_spread(probability),
    }


def attribution_rows_for_folder(folder):
    folder = Path(folder)
    settlement = read_json(folder / SETTLEMENT_FILENAME, default={}) or {}
    if maybe_int(settlement.get("settlement_bucket")) is None:
        return []
    by_snapshot_band = defaultdict(dict)
    component_path = folder / COMPONENT_FILENAME
    with component_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            scored = _score_component_row(row, folder, settlement)
            if not scored:
                continue
            key = (
                scored["snapshot_id"],
                scored["band_kind"],
                scored["band_value"],
                scored["band_value_hi"],
            )
            by_snapshot_band[key][scored["component_name"]] = scored

    rows = []
    for components in by_snapshot_band.values():
        previous = None
        for component_name in STAGE_ORDER:
            current = components.get(component_name)
            if current is None:
                continue
            row = dict(current)
            if previous is None:
                row.update({
                    "previous_component_name": None,
                    "delta_brier": None,
                    "delta_logloss": None,
                    "winner_probability_delta": None,
                    "effective_band_spread_delta": None,
                })
            else:
                row.update({
                    "previous_component_name": previous["component_name"],
                    "delta_brier": row["brier"] - previous["brier"],
                    "delta_logloss": row["logloss"] - previous["logloss"],
                    "winner_probability_delta": (
                        row["probability"] - previous["probability"]
                        if row["outcome"] == 1
                        else None
                    ),
                    "effective_band_spread_delta": (
                        row["effective_band_spread"] - previous["effective_band_spread"]
                    ),
                })
            rows.append(row)
            previous = current
    return rows


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def aggregate_rows(rows, group_key=None):
    groups = defaultdict(list)
    for row in rows:
        key = "all" if group_key is None else row.get(group_key)
        groups[str(key if key not in (None, "") else "-")].append(row)
    output = []
    for key, group in sorted(groups.items()):
        delta_rows = [row for row in group if row.get("delta_brier") is not None]
        output.append({
            "group": key,
            "n": len(group),
            "delta_n": len(delta_rows),
            "mean_brier": mean(row.get("brier") for row in group),
            "mean_logloss": mean(row.get("logloss") for row in group),
            "mean_delta_brier": mean(row.get("delta_brier") for row in delta_rows),
            "mean_delta_logloss": mean(row.get("delta_logloss") for row in delta_rows),
            "mean_winner_probability_delta": mean(
                row.get("winner_probability_delta") for row in delta_rows
            ),
            "mean_effective_band_spread_delta": mean(
                row.get("effective_band_spread_delta") for row in delta_rows
            ),
            "brier_worse_rows": sum(1 for row in delta_rows if row.get("delta_brier", 0.0) > 0),
            "brier_better_rows": sum(1 for row in delta_rows if row.get("delta_brier", 0.0) < 0),
        })
    return output


def net_negative_stages(by_component, min_rows):
    rows = [
        row for row in by_component
        if row.get("delta_n", 0) >= min_rows
        and (
            (row.get("mean_delta_brier") is not None and row["mean_delta_brier"] > 0)
            or (row.get("mean_delta_logloss") is not None and row["mean_delta_logloss"] > 0)
        )
    ]
    return sorted(
        rows,
        key=lambda row: (
            max(0.0, row.get("mean_delta_logloss") or 0.0),
            max(0.0, row.get("mean_delta_brier") or 0.0),
        ),
        reverse=True,
    )


def build_payload(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, *, min_stage_rows=20, now=None):
    rows = []
    folders = component_folders(snapshots_root)
    settled_folders = 0
    for folder in folders:
        folder_rows = attribution_rows_for_folder(folder)
        if folder_rows:
            settled_folders += 1
            rows.extend(folder_rows)

    by_component = aggregate_rows(rows, "component_name")
    negatives = net_negative_stages(by_component, min_rows=min_stage_rows)
    status = "NO_DATA" if not rows else ("ACTIONABLE" if negatives else "OK")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now or utc_now(),
        "snapshots_root": str(Path(snapshots_root)),
        "status": status,
        "folder_count": len(folders),
        "settled_folder_count": settled_folders,
        "attribution_row_count": len(rows),
        "min_stage_rows": min_stage_rows,
        "summary": {
            "status": status,
            "net_negative_stage_count": len(negatives),
            "top_net_negative_stage": negatives[0] if negatives else None,
        },
        "overall": aggregate_rows(rows)[0] if rows else {},
        "by_component": by_component,
        "by_cutoff_hour": aggregate_rows(rows, "cutoff_hour"),
        "by_regime": aggregate_rows(rows, "stage_regime"),
        "by_market": aggregate_rows(rows, "market_id"),
        "net_negative_stages": negatives,
    }


def _metric_row(row):
    return [
        row.get("group"),
        row.get("n"),
        row.get("delta_n"),
        fmt_num(row.get("mean_brier")),
        fmt_num(row.get("mean_logloss")),
        fmt_signed(row.get("mean_delta_brier")),
        fmt_signed(row.get("mean_delta_logloss")),
        fmt_signed(row.get("mean_winner_probability_delta")),
        fmt_signed(row.get("mean_effective_band_spread_delta")),
    ]


def render_report(payload, *, top_n=12):
    lines = [
        "# Distribution Stage Attribution",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Snapshot folders: `{payload.get('folder_count', 0)}`",
        f"Settled folders with component rows: `{payload.get('settled_folder_count', 0)}`",
        f"Attribution rows: `{payload.get('attribution_row_count', 0)}`",
        "",
        (
            "Positive deltas mean the stage worsened score versus the previous "
            "available running stage for the same snapshot and market band."
        ),
        "",
    ]
    headers = [
        "Group",
        "Rows",
        "Delta Rows",
        "Brier",
        "Log Loss",
        "Delta Brier",
        "Delta Log Loss",
        "Winner P Delta",
        "Spread Delta",
    ]
    overall = payload.get("overall") or {}
    if overall:
        lines += ["## Overall", ""]
        lines += markdown_table(headers, [_metric_row(overall)])
        lines.append("")
    negatives = payload.get("net_negative_stages") or []
    lines += ["## Net-Negative Stage Flags", ""]
    if negatives:
        lines += markdown_table(headers, [_metric_row(row) for row in negatives[:top_n]])
    else:
        lines.append("No net-negative stage met the minimum row threshold.")
    lines.append("")
    for title, key in (
        ("By Component", "by_component"),
        ("By Cutoff Hour", "by_cutoff_hour"),
        ("By Regime", "by_regime"),
        ("By Market", "by_market"),
    ):
        rows = payload.get(key) or []
        lines += [f"## {title}", ""]
        rows = sorted(
            rows,
            key=lambda row: (
                row.get("mean_delta_brier") if row.get("mean_delta_brier") is not None else -math.inf,
                row.get("delta_n", 0),
            ),
            reverse=True,
        )
        lines += markdown_table(headers, [_metric_row(row) for row in rows[:top_n]])
        lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--min-stage-rows", type=int, default=20)
    args = parser.parse_args(argv)
    payload = build_payload(args.snapshots_root, min_stage_rows=args.min_stage_rows)
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Distribution stage attribution: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
