"""Evidence-growth reporting for model-variant experiments."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

from weather.reporting.formatting import (
    fmt_num,
    markdown_table,
)
from weather.reporting.candidate_lifecycle.multi_variant_shadow import (
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
DEFAULT_PER_SHADOW_MARKET_MIN_MARKET_DAYS = 4
DEFAULT_ROLLING_7D_MIN_MARKET_DAYS = 1


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
        "extra_location_label_row_count",
        "extra_location_day_count",
        "target_local_label_row_count",
    )
    return {
        key: current.get(key, 0) - baseline.get(key, 0)
        for key in keys
    }


def _status_for_no_growth(reason):
    if reason in {
        "independent_evidence_grew",
        "meets_sample_target",
    }:
        return "PASS"
    if reason in {
        "variant_rows_only",
        "market_missing_from_current_evidence",
        "below_shadow_market_sample_target",
    }:
        return "BLOCK"
    return "WARN"


def _remediation(reason, market_id=None):
    market_note = f" for {market_id}" if market_id else ""
    commands = {
        "no_baseline": (
            "experiment governance",
            "Set --baseline-predictions to the prior accepted evidence export before making a broad promotion claim.",
        ),
        "independent_evidence_grew": (
            "promotion refresh",
            "No remediation required; independent evidence increased.",
        ),
        "same_market_days_more_snapshots": (
            "settlement/corpus refresh",
            "Wait for the next settled market-day, or run `python -m weather.operations.daily_refresh run` after settlement.",
        ),
        "variant_rows_only": (
            "settlement/corpus refresh",
            "Do not make a broad promotion claim; add new settled labels or run `python -m weather.operations.daily_refresh run --include-reconstructed` after settlement.",
        ),
        "market_missing_from_current_evidence": (
            "candidate replay",
            "Rerun promotion refresh/candidate replay and inspect missing candidate rows for the affected market.",
        ),
        "below_shadow_market_sample_target": (
            "settlement/corpus refresh",
            "Keep the market in shadow until the per-market sample target is met by complete settled labels.",
        ),
        "no_new_settled_market_day": (
            "settlement/corpus refresh",
            "If the market has settled, run `python -m weather.operations.daily_refresh run`; otherwise wait for settlement.",
        ),
    }
    owner, action = commands.get(reason, commands["no_new_settled_market_day"])
    return {
        "owner": owner,
        "action": action + market_note if market_id and reason == "market_missing_from_current_evidence" else action,
    }


def _market_delta_rows(current_by_market, baseline_by_market=None, shadow_markets=DEFAULT_SHADOW_MARKETS):
    baseline_by_market = baseline_by_market or {}
    market_ids = sorted(set(current_by_market) | set(baseline_by_market))
    shadow_set = set(shadow_markets or [])
    rows = []
    for market_id in market_ids:
        current = current_by_market.get(market_id) or {}
        baseline = baseline_by_market.get(market_id) or {}
        delta = _delta(current, baseline) if baseline else None
        rows.append({
            "market_id": market_id,
            "priority_shadow_market": market_id in shadow_set,
            "current": current,
            "baseline": baseline or None,
            "delta_vs_baseline": delta,
        })
    return rows


def _classify_no_growth(current, baseline, *, market_id=None):
    if not baseline:
        reason = "no_baseline"
    elif not current:
        reason = "market_missing_from_current_evidence"
    else:
        delta = _delta(current, baseline)
        if delta.get("market_day_count", 0) > 0 or delta.get("unique_observation_count", 0) > 0:
            reason = "independent_evidence_grew"
        elif delta.get("snapshot_count", 0) > 0:
            reason = "same_market_days_more_snapshots"
        elif delta.get("scored_rows", 0) > 0:
            reason = "variant_rows_only"
        else:
            reason = "no_new_settled_market_day"
    remediation = _remediation(reason, market_id=market_id)
    return {
        "reason": reason,
        "status": _status_for_no_growth(reason),
        **remediation,
    }


def _no_growth_rows(current, baseline=None, current_by_market=None, baseline_by_market=None):
    rows = []
    overall = _classify_no_growth(current, baseline)
    rows.append({
        "scope": "overall",
        "market_id": "-",
        **overall,
        "delta_vs_baseline": _delta(current, baseline) if baseline else None,
    })
    if baseline_by_market:
        for market_id in sorted(set(current_by_market or {}) | set(baseline_by_market or {})):
            market_current = (current_by_market or {}).get(market_id) or {}
            market_baseline = (baseline_by_market or {}).get(market_id) or {}
            classified = _classify_no_growth(
                market_current,
                market_baseline,
                market_id=market_id,
            )
            rows.append({
                "scope": "market",
                "market_id": market_id,
                **classified,
                "delta_vs_baseline": _delta(market_current, market_baseline) if market_baseline else None,
            })
    return rows


def _parse_target_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _window_rows(rows, days):
    parsed = [
        (row, _parse_target_date(row.get("target_date")))
        for row in rows
    ]
    dates = [target_date for _row, target_date in parsed if target_date is not None]
    if not dates:
        return []
    latest = max(dates)
    start = latest - timedelta(days=max(1, int(days)) - 1)
    return [
        row
        for row, target_date in parsed
        if target_date is not None and start <= target_date <= latest
    ]


def _trend_row(name, current_rows, baseline_rows=None):
    current = evidence_accounting(current_rows)
    baseline = evidence_accounting(baseline_rows or []) if baseline_rows is not None else None
    return {
        "window": name,
        "current": current,
        "baseline": baseline,
        "delta_vs_baseline": _delta(current, baseline),
    }


def _trend_rows(rows, baseline_rows=None):
    return [
        _trend_row("latest_day", _window_rows(rows, 1), _window_rows(baseline_rows or [], 1) if baseline_rows is not None else None),
        _trend_row("rolling_7d", _window_rows(rows, 7), _window_rows(baseline_rows or [], 7) if baseline_rows is not None else None),
        _trend_row("since_baseline", rows, baseline_rows),
    ]


def _sample_target_rows(markets, *, per_shadow_market_min_market_days):
    rows = []
    for row in markets:
        if not row.get("priority_shadow_market"):
            continue
        market_days = int(row.get("market_day_count") or 0)
        missing = max(0, int(per_shadow_market_min_market_days) - market_days)
        status = "PASS" if missing == 0 else "BLOCK"
        reason = "meets_sample_target" if missing == 0 else "below_shadow_market_sample_target"
        remediation = _remediation(reason, market_id=row.get("market_id"))
        rows.append({
            "market_id": row.get("market_id"),
            "market_day_count": market_days,
            "required_market_days": int(per_shadow_market_min_market_days),
            "missing_market_days": missing,
            "status": status,
            "reason": reason,
            **remediation,
        })
    return rows


def _evidence_sla(
    current,
    baseline,
    markets,
    no_growth_reasons,
    *,
    min_unique_observation_increment,
    min_market_day_increment,
    rolling_7d_min_market_days,
    per_shadow_market_min_market_days,
):
    delta = _delta(current, baseline)
    sample_rows = _sample_target_rows(
        markets,
        per_shadow_market_min_market_days=per_shadow_market_min_market_days,
    )
    sample_blocks = [row for row in sample_rows if row.get("status") == "BLOCK"]
    independent_growth_ok = bool(
        baseline
        and delta
        and delta.get("unique_observation_count", 0) >= min_unique_observation_increment
        and delta.get("market_day_count", 0) >= min_market_day_increment
    )
    no_growth_blocks = [
        row for row in no_growth_reasons
        if row.get("scope") == "overall" and row.get("status") == "BLOCK"
    ]
    broad_promotion_allowed = independent_growth_ok and not sample_blocks and not no_growth_blocks
    status = "PASS" if broad_promotion_allowed else "BLOCK"
    reasons = []
    if not baseline:
        reasons.append("missing baseline evidence")
    elif not independent_growth_ok:
        reasons.append(
            "independent evidence growth below daily target: "
            f"unique {delta.get('unique_observation_count', 0)} / {min_unique_observation_increment}, "
            f"market-days {delta.get('market_day_count', 0)} / {min_market_day_increment}"
        )
    if sample_blocks:
        reasons.append(
            "shadow-market sample target unmet for "
            + ", ".join(row.get("market_id") for row in sample_blocks)
        )
    if no_growth_blocks:
        reasons.append("scored rows grew without independent observations")
    return {
        "schema_version": "independent_evidence_sla_v0.1",
        "status": status,
        "broad_promotion_claim_allowed": broad_promotion_allowed,
        "reasons": reasons,
        "daily_target": {
            "unique_observation_increment": int(min_unique_observation_increment),
            "market_day_increment": int(min_market_day_increment),
        },
        "rolling_7d_target": {
            "market_day_increment": int(rolling_7d_min_market_days),
        },
        "per_shadow_market_target": {
            "market_days": int(per_shadow_market_min_market_days),
        },
        "sample_target_rows": sample_rows,
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
    rolling_7d_min_market_days=DEFAULT_ROLLING_7D_MIN_MARKET_DAYS,
    per_shadow_market_min_market_days=DEFAULT_PER_SHADOW_MARKET_MIN_MARKET_DAYS,
):
    rows, errors = normalize_rows(raw_rows)
    baseline = None
    baseline_errors = []
    normalized_baseline_rows = None
    if baseline_rows is not None:
        normalized_baseline_rows, baseline_errors = normalize_rows(baseline_rows)
        baseline = evidence_accounting(normalized_baseline_rows)
    current = evidence_accounting(rows)
    current_by_market = evidence_by_market(rows)
    baseline_by_market = evidence_by_market(normalized_baseline_rows or []) if normalized_baseline_rows is not None else {}
    markets = _market_rows(current_by_market, shadow_markets=shadow_markets)
    market_deltas = _market_delta_rows(
        current_by_market,
        baseline_by_market=baseline_by_market,
        shadow_markets=shadow_markets,
    )
    no_growth_reasons = _no_growth_rows(
        current,
        baseline=baseline,
        current_by_market=current_by_market,
        baseline_by_market=baseline_by_market,
    )
    evidence_sla = _evidence_sla(
        current,
        baseline,
        markets,
        no_growth_reasons,
        min_unique_observation_increment=min_unique_observation_increment,
        min_market_day_increment=min_market_day_increment,
        rolling_7d_min_market_days=rolling_7d_min_market_days,
        per_shadow_market_min_market_days=per_shadow_market_min_market_days,
    )
    alerts = _alerts(
        current,
        baseline=baseline,
        min_unique_observation_increment=min_unique_observation_increment,
        min_market_day_increment=min_market_day_increment,
    )
    if not evidence_sla.get("broad_promotion_claim_allowed"):
        alerts.append({
            "severity": "alert",
            "category": "broad_promotion_claim_blocked",
            "detail": "; ".join(evidence_sla.get("reasons") or []) or "independent evidence SLA is blocked",
            "blocks_broad_promotion": True,
            "action": "Collect new independent settled market-day evidence before making a broad promotion claim.",
        })
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
        "evidence_sla": evidence_sla,
        "baseline": baseline,
        "delta_vs_baseline": _delta(current, baseline),
        "trend": _trend_rows(rows, normalized_baseline_rows),
        "market_deltas": market_deltas,
        "no_growth_reasons": no_growth_reasons,
        "alerts": alerts,
        "validation_errors": errors,
        "baseline_validation_errors": baseline_errors,
        "markets": markets,
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


def _trend_table_rows(trend):
    rows = []
    for row in trend or []:
        current = row.get("current") or {}
        delta = row.get("delta_vs_baseline") or {}
        rows.append([
            row.get("window"),
            current.get("unique_observation_count", 0),
            current.get("market_day_count", 0),
            current.get("snapshot_count", 0),
            delta.get("unique_observation_count", "-"),
            delta.get("market_day_count", "-"),
            delta.get("snapshot_count", "-"),
        ])
    return rows


def _no_growth_table_rows(rows):
    output = []
    for row in rows or []:
        delta = row.get("delta_vs_baseline") or {}
        output.append([
            row.get("scope"),
            row.get("market_id"),
            row.get("status"),
            row.get("reason"),
            delta.get("unique_observation_count", "-"),
            delta.get("market_day_count", "-"),
            row.get("owner"),
            row.get("action"),
        ])
    return output


def _sample_target_table_rows(rows):
    return [
        [
            row.get("market_id"),
            row.get("status"),
            row.get("market_day_count"),
            row.get("required_market_days"),
            row.get("missing_market_days"),
            row.get("owner"),
            row.get("action"),
        ]
        for row in rows or []
    ]


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
            ["Extra-location label rows", summary.get("extra_location_label_row_count", 0)],
            ["Extra-location days", summary.get("extra_location_day_count", 0)],
            ["Target-local label rows", summary.get("target_local_label_row_count", 0)],
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
    sla = payload.get("evidence_sla") or {}
    lines += ["", "## Evidence SLA", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", sla.get("status") or "-"],
            ["Broad promotion claim allowed", sla.get("broad_promotion_claim_allowed")],
            [
                "Daily target",
                (
                    f"{((sla.get('daily_target') or {}).get('unique_observation_increment'))} unique obs, "
                    f"{((sla.get('daily_target') or {}).get('market_day_increment'))} market-day(s)"
                ),
            ],
            [
                "Rolling 7d target",
                f"{((sla.get('rolling_7d_target') or {}).get('market_day_increment'))} market-day(s)",
            ],
            [
                "Per-shadow-market target",
                f"{((sla.get('per_shadow_market_target') or {}).get('market_days'))} market-day(s)",
            ],
            ["Reasons", "; ".join(sla.get("reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Evidence Trend", ""]
    lines += markdown_table(
        [
            "Window",
            "Current Unique Obs",
            "Current Market-days",
            "Current Snapshots",
            "Delta Unique Obs",
            "Delta Market-days",
            "Delta Snapshots",
        ],
        _trend_table_rows(payload.get("trend") or []),
    )
    lines += ["", "## No-Growth Reasons", ""]
    lines += markdown_table(
        [
            "Scope",
            "Market",
            "Status",
            "Reason",
            "Delta Unique Obs",
            "Delta Market-days",
            "Owner",
            "Action",
        ],
        _no_growth_table_rows(payload.get("no_growth_reasons") or []),
    )
    sample_rows = (sla.get("sample_target_rows") or [])
    if sample_rows:
        lines += ["", "## Shadow-Market Sample Targets", ""]
        lines += markdown_table(
            [
                "Market",
                "Status",
                "Market-days",
                "Required",
                "Missing",
                "Owner",
                "Action",
            ],
            _sample_target_table_rows(sample_rows),
        )
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
    parser.add_argument("--rolling-7d-min-market-days", type=int, default=DEFAULT_ROLLING_7D_MIN_MARKET_DAYS)
    parser.add_argument("--per-shadow-market-min-market-days", type=int, default=DEFAULT_PER_SHADOW_MARKET_MIN_MARKET_DAYS)
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
        rolling_7d_min_market_days=args.rolling_7d_min_market_days,
        per_shadow_market_min_market_days=args.per_shadow_market_min_market_days,
    )
    json_out = write_json(args.json_out, payload)
    report_out = write_report(args.report_out, payload)
    print(f"Model variant evidence growth: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
