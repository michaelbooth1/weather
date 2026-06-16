"""Evidence-growth reporting for model-variant experiments."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

from weather.reporting.formatting import (
    fmt_num,
    markdown_table,
)
from weather.reporting.multi_variant_shadow import (
    evidence_accounting,
    evidence_by_market,
    normalize_rows,
    read_prediction_rows,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_variant_evidence_growth")
DEFAULT_JSON_OUT = data_path() / "backtest" / "model_variant_evidence_growth.json"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "model_variant_evidence_growth_report.md"
DEFAULT_SHADOW_MARKETS = (
    "austin",
    "chicago",
    "dallas",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _family_counts(rows):
    counts = {}
    for row in rows:
        family = row.get("variant_family") or "unknown"
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def _variant_ids(rows):
    return sorted({row.get("variant_id") for row in rows if row.get("variant_id")})


def _market_rows(accounting_by_market, shadow_markets=DEFAULT_SHADOW_MARKETS):
    rows = []
    shadow_set = set(shadow_markets or [])
    for market_id, accounting in sorted(accounting_by_market.items()):
        rows.append({
            "market_id": market_id,
            "priority_shadow_market": market_id in shadow_set,
            **accounting,
        })
    return rows


def _delta(current, baseline):
    if not baseline:
        return None
    keys = (
        "scored_rows",
        "unique_observation_count",
        "snapshot_count",
        "market_day_count",
        "market_count",
        "band_count",
        "settled_label_count",
    )
    return {
        key: current.get(key, 0) - baseline.get(key, 0)
        for key in keys
    }


def _alerts(
    current,
    baseline=None,
    *,
    min_unique_observation_increment=1,
    min_market_day_increment=1,
):
    alerts = []
    if current.get("row_multiplier", 0) > 1.0:
        alerts.append({
            "severity": "warning",
            "category": "variant_rows_not_independent_evidence",
            "detail": (
                "scored variant rows exceed unique observations; this is paired "
                "comparison evidence, not additional labels"
            ),
        })
    if baseline:
        delta = _delta(current, baseline)
        if (
            delta.get("scored_rows", 0) > 0
            and delta.get("unique_observation_count", 0) <= 0
        ):
            alerts.append({
                "severity": "alert",
                "category": "rows_grew_without_independent_evidence",
                "detail": (
                    f"scored rows increased by {delta.get('scored_rows')} while "
                    f"unique observations changed by {delta.get('unique_observation_count')}"
                ),
            })
        if delta.get("unique_observation_count", 0) < min_unique_observation_increment:
            alerts.append({
                "severity": "alert",
                "category": "insufficient_unique_observation_increment",
                "detail": (
                    "unique observation increment "
                    f"{delta.get('unique_observation_count', 0)} is below required "
                    f"{min_unique_observation_increment}"
                ),
            })
        if delta.get("market_day_count", 0) < min_market_day_increment:
            alerts.append({
                "severity": "alert",
                "category": "insufficient_market_day_increment",
                "detail": (
                    f"market-day increment {delta.get('market_day_count', 0)} is below "
                    f"required {min_market_day_increment}"
                ),
            })
    return alerts


def build_payload(
    raw_rows,
    *,
    baseline_rows=None,
    input_paths=None,
    baseline_paths=None,
    shadow_markets=DEFAULT_SHADOW_MARKETS,
    min_unique_observation_increment=1,
    min_market_day_increment=1,
):
    rows, errors = normalize_rows(raw_rows)
    baseline = None
    baseline_errors = []
    if baseline_rows is not None:
        baseline_rows, baseline_errors = normalize_rows(baseline_rows)
        baseline = evidence_accounting(baseline_rows)
    current = evidence_accounting(rows)
    alerts = _alerts(
        current,
        baseline=baseline,
        min_unique_observation_increment=min_unique_observation_increment,
        min_market_day_increment=min_market_day_increment,
    )
    alert_count = sum(1 for alert in alerts if alert["severity"] == "alert")
    warning_count = len(alerts) - alert_count + len(errors) + len(baseline_errors)
    status = "ALERT" if alert_count else ("WARN" if warning_count else "OK")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "input_paths": [str(path) for path in input_paths or []],
        "baseline_paths": [str(path) for path in baseline_paths or []],
        "summary": {
            **current,
            "variant_count": len(_variant_ids(rows)),
            "variant_ids": _variant_ids(rows),
            "source_family_count": len(_family_counts(rows)),
            "source_family_rows": _family_counts(rows),
            "alert_count": alert_count,
            "warning_count": warning_count,
        },
        "minimum_increment_for_broad_promotion_claim": {
            "unique_observations": int(min_unique_observation_increment),
            "market_days": int(min_market_day_increment),
        },
        "baseline": baseline,
        "delta_vs_baseline": _delta(current, baseline),
        "alerts": alerts,
        "validation_errors": errors,
        "baseline_validation_errors": baseline_errors,
        "markets": _market_rows(evidence_by_market(rows), shadow_markets=shadow_markets),
    }


def _market_table_rows(markets):
    rows = []
    for row in markets:
        rows.append([
            row.get("market_id"),
            "yes" if row.get("priority_shadow_market") else "no",
            row.get("market_day_count", 0),
            row.get("snapshot_count", 0),
            row.get("unique_observation_count", 0),
            row.get("settled_label_count", 0),
            row.get("scored_rows", 0),
            fmt_num(row.get("row_multiplier")),
        ])
    return rows


def _delta_rows(delta):
    if not delta:
        return [["-", "-"]]
    return [[key, value] for key, value in delta.items()]


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Model Variant Evidence Growth",
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
            ["Scored rows", summary.get("scored_rows", 0)],
            ["Unique observations", summary.get("unique_observation_count", 0)],
            ["Snapshots", summary.get("snapshot_count", 0)],
            ["Market-days", summary.get("market_day_count", 0)],
            ["Markets", summary.get("market_count", 0)],
            ["Bands", summary.get("band_count", 0)],
            ["Settled labels", summary.get("settled_label_count", 0)],
            ["Row multiplier", fmt_num(summary.get("row_multiplier"))],
            ["Variants", summary.get("variant_count", 0)],
            ["Source families", summary.get("source_family_count", 0)],
            ["Alerts", summary.get("alert_count", 0)],
            ["Warnings", summary.get("warning_count", 0)],
        ],
    )
    lines += ["", "## Delta Vs Baseline", ""]
    minimum = payload.get("minimum_increment_for_broad_promotion_claim") or {}
    lines += [
        "Minimum increment for a new broad promotion claim: "
        f"{minimum.get('unique_observations', 0)} unique observation(s) and "
        f"{minimum.get('market_days', 0)} market-day(s).",
        "",
    ]
    lines += markdown_table(["Metric", "Delta"], _delta_rows(payload.get("delta_vs_baseline")))
    alerts = payload.get("alerts") or []
    if alerts:
        lines += ["", "## Alerts", ""]
        lines += markdown_table(
            ["Severity", "Category", "Detail"],
            [
                [row.get("severity"), row.get("category"), row.get("detail")]
                for row in alerts
            ],
        )
    lines += ["", "## Markets", ""]
    lines += markdown_table(
        [
            "Market",
            "Priority Shadow",
            "Market-days",
            "Snapshots",
            "Unique Obs",
            "Settled Labels",
            "Scored Rows",
            "Row Mult",
        ],
        _market_table_rows(payload.get("markets") or []),
    )
    return "\n".join(lines) + "\n"


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Report independent evidence growth for model-variant runs."
    )
    parser.add_argument("predictions", nargs="+", help="Current variant CSV/JSON/JSONL rows.")
    parser.add_argument("--baseline-predictions", nargs="*", default=None)
    parser.add_argument("--min-unique-observation-increment", type=int, default=1)
    parser.add_argument("--min-market-day-increment", type=int, default=1)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_rows = read_prediction_rows(args.predictions)
    baseline_rows = (
        read_prediction_rows(args.baseline_predictions)
        if args.baseline_predictions else None
    )
    payload = build_payload(
        raw_rows,
        baseline_rows=baseline_rows,
        input_paths=args.predictions,
        baseline_paths=args.baseline_predictions,
        min_unique_observation_increment=args.min_unique_observation_increment,
        min_market_day_increment=args.min_market_day_increment,
    )
    json_out = write_json(args.json_out, payload)
    report_out = write_report(args.report_out, payload)
    print(f"Model variant evidence growth: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
