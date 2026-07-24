"""Shadow/A-B monitoring for promotion decisions and candidate drift."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
from weather.release_contract import (
    SUPPORTED_PROMOTION_AUTHORIZATION_SCHEMA_VERSIONS,
)

from weather.reporting.formatting import (
    fmt_signed,
    markdown_table,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("shadow_ab_monitor")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_CANDIDATE_REPLAY = DEFAULT_BACKTEST_ROOT / "pooled_candidate_replay_latest.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor_report.md"


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decision_by_market(promotion):
    decisions = (
        (promotion.get("promotion_allowlist") or {}).get("markets")
        or (promotion.get("decisions") or {}).get("markets")
        or []
    )
    return {
        str(row.get("market_id")): row
        for row in decisions
        if row.get("market_id")
    }


def candidate_by_market(candidate):
    return {
        str(row.get("market_id")): row
        for row in candidate.get("market_rows") or []
        if row.get("market_id")
    }


def candidate_evidence_accounting(candidate):
    market_rows = candidate.get("market_rows") or []
    scored_rows = sum(int(row.get("rows") or 0) for row in market_rows)
    snapshots = sum(int(row.get("snapshots") or 0) for row in market_rows)
    market_days = sum(int(row.get("days") or 0) for row in market_rows)
    markets = {row.get("market_id") for row in market_rows if row.get("market_id")}
    return {
        "scored_rows": scored_rows,
        "unique_observation_count": scored_rows,
        "snapshot_count": snapshots,
        "market_day_count": market_days,
        "market_count": len(markets),
        "row_multiplier": 1.0 if scored_rows else 0.0,
        "source": "candidate_replay_market_rows",
    }


def serving_blocked_markets(promotion):
    serving = promotion.get("serving_gauntlet") or {}
    blocking = serving.get("blocking_markets") or {}
    if isinstance(blocking, dict):
        return set(blocking)
    if isinstance(blocking, list):
        return {str(item) for item in blocking}
    return set()


def promotion_root_authorized(promotion):
    allowlist = promotion.get("promotion_allowlist") or {}
    return bool(
        str(allowlist.get("schema_version") or "")
        in SUPPORTED_PROMOTION_AUTHORIZATION_SCHEMA_VERSIONS
        and allowlist.get("authorization_schema_supported") is True
        and allowlist.get("authorization_status") == "AUTHORIZED"
        and allowlist.get("serving_or_release_authorization") is True
        and allowlist.get("candidate_serving_allowed") is True
        and allowlist.get("candidate_permission_allowed") is True
    )


def market_monitor_row(
    market_id,
    decision,
    candidate_row,
    serving_blocked,
    current_tol,
    market_tol,
    *,
    root_authorized=False,
):
    comparison = (candidate_row or {}).get("comparison") or {}
    action = (decision or {}).get("action") or "MISSING_DECISION"
    market_authorized = bool(
        root_authorized
        and action == "PROMOTE_CANDIDATE"
        and (decision or {}).get("authorization_schema_supported") is True
        and (decision or {}).get("authorization_status") == "AUTHORIZED"
        and (decision or {}).get("serving_or_release_authorization") is True
        and (decision or {}).get("candidate_serving_allowed") is True
        and (decision or {}).get("candidate_permission_allowed") is True
    )
    candidate_verdict = (candidate_row or {}).get("verdict")
    delta_vs_current = maybe_float(comparison.get("delta_vs_current"))
    delta_vs_market = maybe_float(comparison.get("delta_vs_market"))
    alerts = []
    warnings = []

    if action not in {"PROMOTE_CANDIDATE", "KEEP_SHADOW"}:
        alerts.append(f"promotion action {action}")
    if candidate_verdict == "BLOCK":
        alerts.append("candidate replay verdict BLOCK")
    if market_id in serving_blocked:
        alerts.append("current serving gauntlet blocks this market")
    if delta_vs_current is not None and delta_vs_current > current_tol:
        alerts.append(f"candidate regresses current by {delta_vs_current:.4f}")
    if delta_vs_market is not None and delta_vs_market > market_tol:
        alerts.append(f"candidate trails market by {delta_vs_market:.4f}")
    if not candidate_row:
        warnings.append("missing candidate replay row")
    if action == "KEEP_SHADOW" and not alerts:
        warnings.append((decision or {}).get("reason") or "candidate remains shadow")
    if action == "PROMOTE_CANDIDATE" and not market_authorized and not alerts:
        warnings.append(
            "promotion recommendation is detached and lacks serving/release authorization"
        )

    if alerts:
        status = "ALERT"
    elif market_authorized:
        status = "PROMOTE_READY"
    elif action == "PROMOTE_CANDIDATE":
        status = "RECOMMENDATION_READY"
    else:
        status = "SHADOW"

    return {
        "market_id": market_id,
        "status": status,
        "promotion_action": action,
        "promotion_reason": (decision or {}).get("reason"),
        "promotion_authorized": market_authorized,
        "candidate_verdict": candidate_verdict,
        "days": (candidate_row or {}).get("days"),
        "snapshots": (candidate_row or {}).get("snapshots"),
        "rows": (candidate_row or {}).get("rows"),
        "unique_observations": (candidate_row or {}).get("rows"),
        "candidate_brier": maybe_float(comparison.get("candidate_brier")),
        "current_brier": maybe_float(comparison.get("current_brier")),
        "market_brier": maybe_float(comparison.get("market_brier")),
        "delta_vs_current": delta_vs_current,
        "delta_vs_market": delta_vs_market,
        "alerts": alerts,
        "warnings": warnings,
    }


def global_alerts(promotion, candidate):
    alerts = []
    if not promotion:
        alerts.append("missing promotion refresh artifact")
    if not candidate:
        alerts.append("missing pooled candidate replay artifact")
    replay_gate = candidate.get("replay_gate") or {}
    if replay_gate and not replay_gate.get("global_ok", True):
        alerts.append("candidate replay global gate failed")
    readiness = promotion.get("readiness") or {}
    for blocker in readiness.get("blockers") or []:
        category = blocker.get("category") or "readiness"
        detail = blocker.get("detail") or blocker.get("message") or "open blocker"
        alerts.append(f"{category}: {detail}")
    return alerts


def build_monitor(
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    candidate_replay=DEFAULT_CANDIDATE_REPLAY,
    *,
    current_tol=0.003,
    market_tol=0.003,
):
    promotion = read_json(promotion_refresh)
    candidate = read_json(candidate_replay)
    decisions = decision_by_market(promotion)
    candidates = candidate_by_market(candidate)
    blocked = set((promotion.get("decisions") or {}).get("blocked_markets") or [])
    serving_blocked = serving_blocked_markets(promotion)
    root_authorized = promotion_root_authorized(promotion)
    market_ids = sorted(set(decisions) | set(candidates) | blocked | serving_blocked)
    markets = [
        market_monitor_row(
            market_id,
            decisions.get(market_id),
            candidates.get(market_id),
            serving_blocked,
            current_tol,
            market_tol,
            root_authorized=root_authorized,
        )
        for market_id in market_ids
    ]
    alerts = global_alerts(promotion, candidate)
    evidence = candidate_evidence_accounting(candidate)
    alert_count = len(alerts) + sum(len(row["alerts"]) for row in markets)
    shadow_count = sum(1 for row in markets if row["status"] == "SHADOW")
    promote_ready_count = sum(1 for row in markets if row["status"] == "PROMOTE_READY")
    recommendation_ready_count = sum(
        1 for row in markets if row["status"] == "RECOMMENDATION_READY"
    )
    status = (
        "ALERT"
        if alert_count
        else "WARN"
        if shadow_count or recommendation_ready_count
        else "OK"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "promotion_refresh_path": str(promotion_refresh),
        "promotion_allowlist": {
            "present": bool((promotion.get("promotion_allowlist") or {}).get("markets")),
            "schema_version": (promotion.get("promotion_allowlist") or {}).get("schema_version"),
            "path": (promotion.get("promotion_allowlist") or {}).get("path"),
            "candidate_id": (promotion.get("promotion_allowlist") or {}).get("candidate_id"),
            "authorization_status": (
                promotion.get("promotion_allowlist") or {}
            ).get("authorization_status"),
            "serving_or_release_authorization": root_authorized,
        },
        "candidate_replay_path": str(candidate_replay),
        "thresholds": {
            "current_regression_tol": current_tol,
            "market_gap_tol": market_tol,
        },
        "summary": {
            "market_count": len(markets),
            "promote_ready_markets": promote_ready_count,
            "recommendation_ready_markets": recommendation_ready_count,
            "shadow_markets": shadow_count,
            "alert_markets": sum(1 for row in markets if row["status"] == "ALERT"),
            "alert_count": alert_count,
            "scored_rows": evidence["scored_rows"],
            "unique_observation_count": evidence["unique_observation_count"],
            "snapshot_count": evidence["snapshot_count"],
            "market_day_count": evidence["market_day_count"],
        },
        "evidence_accounting": evidence,
        "global_alerts": alerts,
        "markets": markets,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    allowlist = payload.get("promotion_allowlist") or {}
    lines = [
        "# Shadow/A-B Monitor",
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
            ["Markets", summary.get("market_count", 0)],
            ["Promote-ready", summary.get("promote_ready_markets", 0)],
            [
                "Recommendation-ready (non-authorizing)",
                summary.get("recommendation_ready_markets", 0),
            ],
            ["Shadow", summary.get("shadow_markets", 0)],
            ["Alert markets", summary.get("alert_markets", 0)],
            ["Alerts", summary.get("alert_count", 0)],
            ["Scored rows", summary.get("scored_rows", 0)],
            ["Unique observations", summary.get("unique_observation_count", 0)],
            ["Snapshots", summary.get("snapshot_count", 0)],
            ["Market-days", summary.get("market_day_count", 0)],
            ["Promotion allowlist", allowlist.get("present")],
            ["Allowlist candidate", allowlist.get("candidate_id") or "-"],
            ["Allowlist path", allowlist.get("path") or "-"],
            [
                "Serving/release authorization",
                allowlist.get("serving_or_release_authorization"),
            ],
        ],
    )
    alerts = payload.get("global_alerts") or []
    if alerts:
        lines += ["", "## Global Alerts", ""]
        lines.extend(f"- {alert}" for alert in alerts)

    lines += ["", "## Markets", ""]
    lines += markdown_table(
        [
            "Market", "Status", "Action", "Candidate", "Days", "Unique Obs", "Rows",
            "Delta Current", "Delta Market", "Alerts",
        ],
        [
            [
                row.get("market_id"),
                row.get("status"),
                row.get("promotion_action"),
                row.get("candidate_verdict") or "-",
                row.get("days") if row.get("days") is not None else "-",
                row.get("unique_observations") if row.get("unique_observations") is not None else "-",
                row.get("rows") if row.get("rows") is not None else "-",
                fmt_signed(row.get("delta_vs_current"), 4),
                fmt_signed(row.get("delta_vs_market"), 4),
                "; ".join(row.get("alerts") or row.get("warnings") or []) or "-",
            ]
            for row in payload.get("markets") or []
        ],
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build shadow/A-B drift monitoring from promotion artifacts.")
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--candidate-replay", default=str(DEFAULT_CANDIDATE_REPLAY))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--fail-on-alert", action="store_true")
    args = parser.parse_args(argv)

    payload = build_monitor(
        args.promotion_refresh,
        args.candidate_replay,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
    )
    json_out = write_json(args.json_out, payload)
    report_out = write_report(args.report_out, payload)
    print(f"Shadow/A-B monitor: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    if args.fail_on_alert and payload["status"] == "ALERT":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
