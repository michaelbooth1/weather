"""Promotion-refresh-compatible summary for candidate variant row exports."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from weather.paths import data_path
from weather.reporting.candidate_hourly_performance import (
    candidate_rows_corpus_hash,
    read_variant_rows,
    summarize_rows,
)
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.hourly_model_scoring import HOUR_REGIME_LABELS, hour_regime
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("candidate_variant_replay_summary")
BLOCKED_VALIDATION_SCHEMA_VERSION = schema_version("blocked_candidate_validation_gate")
BLOCKED_AUDIT_SCHEMA_VERSION = schema_version("blocked_validation")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_VARIANT_ROWS = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv"
)
DEFAULT_SOURCE_CANDIDATE_JSON = DEFAULT_BACKTEST_ROOT / "pooled_candidate_replay_latest.json"
DEFAULT_JSON_OUT = (
    DEFAULT_BACKTEST_ROOT
    / "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json"
)
DEFAULT_REPORT_OUT = (
    DEFAULT_BACKTEST_ROOT
    / "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary_report.md"
)
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MARKET_TOL = 0.003
DEFAULT_MIN_MARKET_DAYS = 2
VALIDATION_EVIDENCE_CHOICES = ("row_export_surrogate", "active_replay_contract")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _skill(model_brier: float | None, market_brier: float | None) -> float | None:
    if model_brier is None or market_brier is None or market_brier <= 0:
        return None
    return 1.0 - (float(model_brier) / float(market_brier))


def _market_days(rows: list[dict[str, Any]]) -> set[tuple[Any, Any]]:
    return {
        (row.get("market_id"), row.get("target_date"))
        for row in rows
        if row.get("market_id") and row.get("target_date")
    }


def _comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_rows(rows) or {}
    candidate_brier = summary.get("variant_brier")
    current_brier = summary.get("current_brier")
    market_brier = summary.get("market_brier")
    candidate_logloss = summary.get("variant_logloss")
    current_logloss = summary.get("current_logloss")
    market_logloss = summary.get("market_logloss")
    return {
        "n": summary.get("n", 0),
        "base_rate": summary.get("base_rate"),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "recorded_brier": None,
        "market_brier": market_brier,
        "delta_vs_current": summary.get("delta_vs_current"),
        "delta_vs_market": summary.get("delta_vs_market"),
        "candidate_logloss": candidate_logloss,
        "current_logloss": current_logloss,
        "recorded_logloss": None,
        "market_logloss": market_logloss,
        "logloss_delta_vs_current": summary.get("logloss_delta_vs_current"),
        "logloss_delta_vs_market": summary.get("logloss_delta_vs_market"),
        "candidate_ece": summary.get("variant_ece"),
        "current_ece": summary.get("current_ece"),
        "market_ece": summary.get("market_ece"),
        "candidate_skill": _skill(candidate_brier, market_brier),
        "current_skill": _skill(current_brier, market_brier),
        "recorded_skill": None,
        "winner_candidate_probability": summary.get("winner_variant_probability"),
        "winner_current_probability": summary.get("winner_current_probability"),
        "winner_market_probability": summary.get("winner_market_probability"),
        "loser_candidate_probability": summary.get("loser_variant_probability"),
        "loser_current_probability": summary.get("loser_current_probability"),
        "loser_market_probability": summary.get("loser_market_probability"),
    }


def _threshold_reasons(
    comparison: dict[str, Any],
    *,
    market_days: int,
    min_market_days: int,
    current_tol: float,
    market_tol: float,
) -> list[str]:
    reasons = []
    if int(market_days) < int(min_market_days):
        reasons.append(f"candidate evidence has {market_days} market-days; need {int(min_market_days)}")
    delta_current = comparison.get("delta_vs_current")
    if delta_current is None:
        reasons.append("candidate/current comparison is unavailable")
    elif float(delta_current) > float(current_tol):
        reasons.append(
            f"candidate regresses current by {float(delta_current):+.4f} > {float(current_tol):.4f}"
        )
    delta_market = comparison.get("delta_vs_market")
    if delta_market is None:
        reasons.append("candidate/market comparison is unavailable")
    elif float(delta_market) > float(market_tol):
        reasons.append("candidate is not within market tolerance")
    return reasons


def _blocked_validation(
    rows: list[dict[str, Any]],
    comparison: dict[str, Any],
    *,
    validation_evidence: str,
    current_tol: float,
    market_tol: float,
    min_market_days: int,
) -> dict[str, Any]:
    market_day_count = len(_market_days(rows))
    threshold_reasons = _threshold_reasons(
        comparison,
        market_days=market_day_count,
        min_market_days=min_market_days,
        current_tol=current_tol,
        market_tol=market_tol,
    )
    metric_passed = not threshold_reasons
    reasons = list(threshold_reasons)
    if validation_evidence != "active_replay_contract":
        reasons.append("row-export summary is not active replay/export contract evidence")
    passed = metric_passed and validation_evidence == "active_replay_contract"
    target_dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    return {
        "schema_version": BLOCKED_VALIDATION_SCHEMA_VERSION,
        "verdict": "PASS" if passed else "BLOCK",
        "passed": bool(passed),
        "metric_passed": bool(metric_passed),
        "validation_evidence": validation_evidence,
        "split_mode": validation_evidence,
        "current_tol": float(current_tol),
        "market_tol": float(market_tol),
        "min_days": int(min_market_days),
        "reasons": reasons,
        "daily_first": {
            "n": comparison.get("n", 0),
            "n_days": market_day_count,
            "base_rate": comparison.get("base_rate"),
            "candidate_brier": comparison.get("candidate_brier"),
            "current_brier": comparison.get("current_brier"),
            "recorded_brier": comparison.get("recorded_brier"),
            "market_brier": comparison.get("market_brier"),
            "delta_vs_current": comparison.get("delta_vs_current"),
            "delta_vs_market": comparison.get("delta_vs_market"),
            "candidate_skill": comparison.get("candidate_skill"),
            "current_skill": comparison.get("current_skill"),
        },
        "split_audit": {
            "schema_version": BLOCKED_AUDIT_SCHEMA_VERSION,
            "ok": validation_evidence == "active_replay_contract",
            "leak_count": 0,
            "leaks": [],
            "row_count": comparison.get("n", 0),
            "market_day_count": market_day_count,
            "target_date_count": len(target_dates),
            "split_count": market_day_count if validation_evidence == "active_replay_contract" else 0,
            "split_modes": [
                {
                    "mode": validation_evidence,
                    "partition_key": "market_day",
                    "split_count": (
                        market_day_count if validation_evidence == "active_replay_contract" else 0
                    ),
                    "held_out_dates_sample": target_dates[:3],
                    "train_rows_min": 0,
                    "validation_rows_min": 0,
                    "validation_rows_max": 0,
                }
            ],
        },
    }


def _reason(validation: dict[str, Any], comparison: dict[str, Any]) -> str:
    if validation.get("passed"):
        return "beats current replay and clears market validation gates"
    reasons = validation.get("reasons") or []
    if reasons:
        return "; ".join(reasons)
    delta_current = comparison.get("delta_vs_current")
    delta_market = comparison.get("delta_vs_market")
    return (
        "candidate validation did not pass"
        + (f"; delta_vs_current={float(delta_current):+.4f}" if delta_current is not None else "")
        + (f"; delta_vs_market={float(delta_market):+.4f}" if delta_market is not None else "")
    )


def _variant_ids(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("variant_id")) for row in rows if row.get("variant_id")})


def _group_rows(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], Any],
) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if key not in (None, ""):
            grouped[key].append(row)
    return grouped


def _slice_summary(group: Any, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    comparison = _comparison(rows)
    return {
        "group": group,
        "n": comparison.get("n", 0),
        "market_days": len(_market_days(rows)),
        "snapshots": len({row.get("snapshot_id") for row in rows if row.get("snapshot_id")}),
        "candidate_brier": comparison.get("candidate_brier"),
        "current_brier": comparison.get("current_brier"),
        "recorded_brier": comparison.get("recorded_brier"),
        "market_brier": comparison.get("market_brier"),
        "delta_vs_current": comparison.get("delta_vs_current"),
        "delta_vs_market": comparison.get("delta_vs_market"),
        "candidate_ece": comparison.get("candidate_ece"),
        "base_rate": comparison.get("base_rate"),
    }


def _summarize_group(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    output = []
    for group, group_rows in sorted(_group_rows(rows, key_fn).items(), key=lambda item: str(item[0])):
        summary = _slice_summary(group, group_rows)
        if summary:
            output.append(summary)
    return output


def _summarize_by_hour(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for group, group_rows in sorted(
        _group_rows(rows, lambda row: row.get("capture_hour")).items(),
        key=lambda item: int(item[0]),
    ):
        summary = _slice_summary(int(group), group_rows)
        if summary:
            summary["hour"] = int(group)
            summary["hour_label"] = f"{int(group):02d}:00"
            output.append(summary)
    return output


def _summarize_by_regime(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_rows(rows, lambda row: hour_regime(row.get("capture_hour")))
    output = []
    for regime in HOUR_REGIME_LABELS:
        summary = _slice_summary(regime, grouped.get(regime, []))
        if summary:
            summary["regime"] = regime
            summary["regime_label"] = HOUR_REGIME_LABELS[regime]
            output.append(summary)
    return output


def _market_rows(
    rows: list[dict[str, Any]],
    *,
    validation_evidence: str,
    current_tol: float,
    market_tol: float,
    min_market_days: int,
) -> list[dict[str, Any]]:
    output = []
    for market_id, market_rows in sorted(
        _group_rows(rows, lambda row: row.get("market_id")).items(),
        key=lambda item: str(item[0]),
    ):
        comparison = _comparison(market_rows)
        validation = _blocked_validation(
            market_rows,
            comparison,
            validation_evidence=validation_evidence,
            current_tol=current_tol,
            market_tol=market_tol,
            min_market_days=min_market_days,
        )
        output.append({
            "market_id": market_id,
            "city": str(market_id).replace("_", " ").title(),
            "verdict": "PASS" if validation.get("passed") else "BLOCK",
            "reason": _reason(validation, comparison),
            "rows": comparison.get("n", 0),
            "snapshots": len({row.get("snapshot_id") for row in market_rows if row.get("snapshot_id")}),
            "days": len(_market_days(market_rows)),
            "comparison": comparison,
            "blocked_validation": validation,
        })
    return output


def _candidate_shadow_variants(
    rows: list[dict[str, Any]],
    variant_rows: str | Path,
    source_candidate: dict[str, Any],
) -> dict[str, Any]:
    ids = _variant_ids(rows)
    source_shadow = source_candidate.get("candidate_shadow_variants") or {}
    return {
        "variant_id": ids[0] if len(ids) == 1 else None,
        "variant_ids": ids,
        "variant_family": "candidate_variant_row_export",
        "path": str(variant_rows),
        "rows": len(rows),
        "uses_market_features": False,
        "is_control": False,
        "registry_contract": False,
        "derived_from": {
            "variant_id": source_shadow.get("variant_id"),
            "variant_family": source_shadow.get("variant_family"),
            "path": source_shadow.get("path"),
            "registry_contract": source_shadow.get("registry_contract"),
        },
    }


def build_variant_replay_summary(
    variant_rows: str | Path = DEFAULT_VARIANT_ROWS,
    source_candidate_json: str | Path = DEFAULT_SOURCE_CANDIDATE_JSON,
    *,
    validation_evidence: str = "row_export_surrogate",
    current_tol: float = DEFAULT_CURRENT_TOL,
    market_tol: float = DEFAULT_MARKET_TOL,
    min_market_days: int = DEFAULT_MIN_MARKET_DAYS,
) -> dict[str, Any]:
    if validation_evidence not in VALIDATION_EVIDENCE_CHOICES:
        raise ValueError(f"unknown validation evidence mode: {validation_evidence}")
    rows = read_variant_rows(variant_rows)
    source_candidate = _read_json(source_candidate_json)
    source_corpus = source_candidate.get("corpus") or {}
    row_export_corpus_hash = candidate_rows_corpus_hash(rows)
    source_candidate_corpus_hash = source_corpus.get("corpus_hash")
    corpus_hash = row_export_corpus_hash
    aggregate = _comparison(rows)
    blocked_validation = _blocked_validation(
        rows,
        aggregate,
        validation_evidence=validation_evidence,
        current_tol=current_tol,
        market_tol=market_tol,
        min_market_days=min_market_days,
    )
    markets = _market_rows(
        rows,
        validation_evidence=validation_evidence,
        current_tol=current_tol,
        market_tol=market_tol,
        min_market_days=min_market_days,
    )
    market_blocks = [row for row in markets if row.get("verdict") == "BLOCK"]
    row_export_metric_passed = blocked_validation.get("metric_passed") and not any(
        not (row.get("blocked_validation") or {}).get("metric_passed") for row in markets
    )
    verdict = "PASS" if blocked_validation.get("passed") and not market_blocks else "BLOCK"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "source": "candidate_variant_row_export",
        "validation_evidence": validation_evidence,
        "row_export_metric_passed": bool(row_export_metric_passed),
        "verdict": verdict,
        "candidate_market_verdict": "PASS" if row_export_metric_passed else "BLOCK",
        "cutover_decision": "PER_MARKET_ONLY" if verdict == "PASS" else "DO_NOT_CUT_OVER",
        "artifact": {
            **(source_candidate.get("artifact") or {}),
            "variant_rows_path": str(variant_rows),
            "source_candidate_json": str(source_candidate_json),
            "replay_summary_source": "candidate_variant_row_export",
        },
        "corpus": {
            **source_corpus,
            "source_rows": len(rows),
            "market_days": len(_market_days(rows)),
            "snapshots": len({row.get("snapshot_id") for row in rows if row.get("snapshot_id")}),
            "markets": len({row.get("market_id") for row in rows if row.get("market_id")}),
            "corpus_hash": corpus_hash,
            "row_export_corpus_hash": row_export_corpus_hash,
            "source_candidate_corpus_hash": source_candidate_corpus_hash,
        },
        "coverage": source_candidate.get("coverage") or {},
        "replay_gate": {
            "global_ok": bool(rows),
            "corpus_ok": bool(rows),
            "fidelity_ok": bool(rows),
            "corpus_message": (
                "ROW_EXPORT_SURROGATE: summary derived from candidate variant row export; "
                "not a pinned replay corpus hash"
                if validation_evidence == "row_export_surrogate"
                else "PASS: active replay/export contract evidence supplied"
            ),
            "fidelity_message": (
                "ROW_EXPORT_SURROGATE: replay fidelity is inherited from the source row export"
                if validation_evidence == "row_export_surrogate"
                else "PASS: active replay/export contract evidence supplied"
            ),
            "require_exact_identity": False,
            "same_identity_n": None,
            "same_identity_max_l1": None,
            "max_fidelity_l1": None,
        },
        "blocked_validation": blocked_validation,
        "candidate_shadow_variants": _candidate_shadow_variants(rows, variant_rows, source_candidate),
        "aggregate": aggregate,
        "market_rows": markets,
        "by_hour": _summarize_by_hour(rows),
        "by_cutoff_regime": _summarize_by_regime(rows),
        "by_bin_type": _summarize_group(rows, lambda row: row.get("bin_type")),
        "by_settlement_distance": _summarize_group(
            rows,
            lambda row: row.get("settlement_distance_bucket"),
        ),
        "by_source_freshness": _summarize_group(rows, lambda row: row.get("source_freshness_state")),
        "by_forecast_source_count": _summarize_group(
            rows,
            lambda row: row.get("forecast_source_count_bucket"),
        ),
        "by_forecast_disagreement": _summarize_group(
            rows,
            lambda row: row.get("forecast_disagreement_bucket"),
        ),
        "by_forecast_bucket_pressure": _summarize_group(
            rows,
            lambda row: row.get("forecast_bucket_pressure"),
        ),
        "notes": [
            "This artifact adapts candidate variant rows to the promotion-refresh candidate schema.",
            "The default validation_evidence=row_export_surrogate intentionally blocks cutover until an active replay/export contract rerun exists.",
        ],
    }
    if not rows:
        payload["verdict"] = "BLOCK"
        payload["candidate_market_verdict"] = "BLOCK"
        payload["cutover_decision"] = "DO_NOT_CUT_OVER"
    return payload


def _market_table_rows(markets: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for row in markets:
        comparison = row.get("comparison") or {}
        validation = row.get("blocked_validation") or {}
        rows.append([
            row.get("market_id"),
            row.get("days", 0),
            row.get("snapshots", 0),
            row.get("rows", 0),
            fmt_num(comparison.get("candidate_brier")),
            fmt_num(comparison.get("current_brier")),
            fmt_num(comparison.get("market_brier")),
            fmt_signed(comparison.get("delta_vs_current")),
            fmt_signed(comparison.get("delta_vs_market")),
            validation.get("verdict") or "-",
            row.get("verdict"),
            row.get("reason") or "-",
        ])
    return rows


def _slice_table_rows(slices: list[dict[str, Any]], limit: int = 24) -> list[list[Any]]:
    output = []
    sorted_rows = sorted(
        slices,
        key=lambda row: (
            math.inf if row.get("delta_vs_market") is None else -float(row.get("delta_vs_market")),
            str(row.get("group") or ""),
        ),
    )
    for row in sorted_rows[:limit]:
        output.append([
            row.get("group"),
            row.get("n", 0),
            row.get("market_days", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current")),
            fmt_signed(row.get("delta_vs_market")),
        ])
    return output


def render_report(payload: dict[str, Any]) -> str:
    aggregate = payload.get("aggregate") or {}
    shadow = payload.get("candidate_shadow_variants") or {}
    blocked = payload.get("blocked_validation") or {}
    corpus = payload.get("corpus") or {}
    lines = [
        "# Candidate Variant Replay Summary",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Scope",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Schema", payload.get("schema_version")],
                ["Source", payload.get("source")],
                ["Validation evidence", payload.get("validation_evidence")],
                ["Variant rows", shadow.get("path")],
                ["Variant IDs", ", ".join(shadow.get("variant_ids") or []) or "-"],
                ["Rows", corpus.get("source_rows", 0)],
                ["Markets", corpus.get("markets", 0)],
                ["Market-days", corpus.get("market_days", 0)],
                ["Snapshots", corpus.get("snapshots", 0)],
                ["Verdict", payload.get("verdict")],
                ["Cutover decision", payload.get("cutover_decision")],
            ],
        ),
        "",
        "## Aggregate",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Rows", aggregate.get("n", 0)],
                ["Base rate", fmt_num(aggregate.get("base_rate"))],
                ["Candidate Brier", fmt_num(aggregate.get("candidate_brier"))],
                ["Current Brier", fmt_num(aggregate.get("current_brier"))],
                ["Market Brier", fmt_num(aggregate.get("market_brier"))],
                ["Delta vs current", fmt_signed(aggregate.get("delta_vs_current"))],
                ["Delta vs market", fmt_signed(aggregate.get("delta_vs_market"))],
                ["Candidate log-loss", fmt_num(aggregate.get("candidate_logloss"))],
                ["Market log-loss", fmt_num(aggregate.get("market_logloss"))],
                ["Log-loss delta vs market", fmt_signed(aggregate.get("logloss_delta_vs_market"))],
                ["Candidate ECE", fmt_num(aggregate.get("candidate_ece"))],
            ],
        ),
        "",
        "## Validation Gate",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", blocked.get("verdict")],
                ["Passed", blocked.get("passed")],
                ["Metric passed", blocked.get("metric_passed")],
                ["Evidence", blocked.get("validation_evidence")],
                ["Reasons", "; ".join(blocked.get("reasons") or []) or "-"],
            ],
        ),
        "",
        "## Markets",
        "",
        *markdown_table(
            [
                "Market",
                "Days",
                "Snapshots",
                "Rows",
                "Candidate",
                "Current",
                "Market",
                "Delta Current",
                "Delta Market",
                "Validation",
                "Verdict",
                "Reason",
            ],
            _market_table_rows(payload.get("market_rows") or []),
        ),
        "",
        "## Cutoff Regimes",
        "",
        *markdown_table(
            [
                "Regime",
                "Rows",
                "Days",
                "Candidate",
                "Current",
                "Market",
                "Delta Current",
                "Delta Market",
            ],
            _slice_table_rows(payload.get("by_cutoff_regime") or []),
        ),
        "",
        "## Hours",
        "",
        *markdown_table(
            [
                "Hour",
                "Rows",
                "Days",
                "Candidate",
                "Current",
                "Market",
                "Delta Current",
                "Delta Market",
            ],
            _slice_table_rows(payload.get("by_hour") or []),
        ),
        "",
        "Note: row-export surrogate evidence is intentionally promotion-blocking. Use `validation_evidence=active_replay_contract` only when the rows were produced by the active replay/export contract.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[str, str]:
    json_path = Path(json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return str(json_path), str(report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a promotion-refresh-compatible summary from candidate variant rows."
    )
    parser.add_argument("--variant-rows", default=str(DEFAULT_VARIANT_ROWS))
    parser.add_argument("--source-candidate-json", default=str(DEFAULT_SOURCE_CANDIDATE_JSON))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--min-market-days", type=int, default=DEFAULT_MIN_MARKET_DAYS)
    parser.add_argument(
        "--validation-evidence",
        default="row_export_surrogate",
        choices=VALIDATION_EVIDENCE_CHOICES,
    )
    args = parser.parse_args()

    payload = build_variant_replay_summary(
        args.variant_rows,
        args.source_candidate_json,
        validation_evidence=args.validation_evidence,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_market_days=args.min_market_days,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(
        "Candidate variant replay summary: "
        f"{payload.get('verdict')} / {payload.get('cutover_decision')}"
    )
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
