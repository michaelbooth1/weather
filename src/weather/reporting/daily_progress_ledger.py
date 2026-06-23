"""Daily progress ledger for broad improvement claims."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.reporting.runtime_identity_evidence import build_runtime_identity_evidence
from weather.reporting.trading_evidence import build_trading_evidence_summary


SCHEMA_VERSION = "daily_progress_ledger_v0.1"
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSONL_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger.jsonl"
DEFAULT_CSV_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger.csv"
DEFAULT_LATEST_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_latest.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_progress_ledger_report.md"
BROAD_MIN_POSITIVE_SKILL_DAYS = 3
BROAD_MIN_PROMOTION_GRADE_MARKET_DAYS = 84
DISK_HEADROOM_RE = re.compile(
    r"free_bytes=(?P<free_bytes>\d+).*?required_free_bytes=(?P<required_free_bytes>\d+)"
)
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


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


def json_field(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(number)


def _artifact(backtest_root, name):
    return read_json(Path(backtest_root) / name)


def _disk_snapshot(backtest_root):
    usage = shutil.disk_usage(Path(backtest_root))
    return {
        "free_bytes": int(usage.free),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
    }


def _disk_preflight_from_failed_step(daily_refresh):
    for step in daily_refresh.get("steps") or []:
        if step.get("name") != "promotion_refresh" or step.get("status") != "error":
            continue
        text = " ".join(str(step.get(key) or "") for key in ("error", "traceback", "root_cause_class"))
        if "disk" not in text.lower() and "headroom" not in text.lower():
            continue
        match = DISK_HEADROOM_RE.search(text)
        if not match:
            return {
                "status": "BLOCK",
                "free_bytes": None,
                "required_free_bytes": None,
                "headroom_bytes": None,
                "insufficient_bytes": None,
            }
        free = maybe_int(match.group("free_bytes"))
        required = maybe_int(match.group("required_free_bytes"))
        return {
            "status": "BLOCK",
            "free_bytes": free,
            "required_free_bytes": required,
            "headroom_bytes": free - required if free is not None and required is not None else None,
            "insufficient_bytes": required - free if free is not None and required is not None else None,
        }
    return None


def _disk_preflight(daily_refresh, backtest_root):
    summary = daily_refresh.get("summary") or {}
    preflights = summary.get("disk_preflight") or {}
    promotion = preflights.get("promotion_refresh") or {}
    if promotion:
        free = maybe_int(promotion.get("free_bytes"))
        required = maybe_int(promotion.get("required_free_bytes"))
        return {
            "status": promotion.get("status"),
            "free_bytes": free,
            "required_free_bytes": required,
            "headroom_bytes": free - required if free is not None and required is not None else None,
            "insufficient_bytes": maybe_int(promotion.get("insufficient_bytes")),
        }
    failed_step_preflight = _disk_preflight_from_failed_step(daily_refresh)
    if failed_step_preflight:
        return failed_step_preflight
    disk = _disk_snapshot(backtest_root)
    return {
        "status": "OBSERVED",
        "free_bytes": disk["free_bytes"],
        "required_free_bytes": None,
        "headroom_bytes": None,
        "insufficient_bytes": None,
    }


def _independent_baseline_status(variant):
    if not variant:
        return "MISSING"
    if variant.get("delta_vs_baseline") is not None:
        return "PRESENT"
    evidence_sla = variant.get("evidence_sla") or {}
    reasons = [str(item).lower() for item in evidence_sla.get("reasons") or []]
    no_growth = variant.get("no_growth_reasons") or []
    no_growth_reasons = [str((item or {}).get("reason") or "").lower() for item in no_growth]
    if any("missing baseline" in reason or "no_baseline" in reason for reason in reasons + no_growth_reasons):
        return "MISSING"
    return "PRESENT" if variant.get("baseline") or variant.get("baseline_paths") else "MISSING"


def _frozen_baseline_status(frozen):
    if not frozen:
        return None
    status = frozen.get("independent_baseline_status")
    if status in {"PRESENT", "MISSING"}:
        return status
    return None


def _quality_counts(daily_refresh):
    return (((daily_refresh.get("summary") or {}).get("labels") or {}).get("quality_counts") or {})


def _daily_refresh_status(daily_refresh):
    if not daily_refresh:
        return "missing"
    return daily_refresh.get("status") or "unknown"


def _scoreboard_status(scoreboard):
    if not scoreboard:
        return "MISSING"
    return ((scoreboard.get("headline") or {}).get("status") or scoreboard.get("status") or "UNKNOWN")


def _scoreboard_first_blocker(scoreboard):
    first = ((scoreboard.get("headline") or {}).get("first_blocker") or {})
    if isinstance(first, dict):
        return first.get("detail") or first.get("category") or ""
    if first:
        return str(first)
    for blocker in scoreboard.get("blockers") or []:
        if isinstance(blocker, dict):
            return blocker.get("detail") or blocker.get("category") or ""
        if blocker:
            return str(blocker)
    return ""


def broad_claim_failures(row):
    failures = []
    if not bool(row.get("model_claim_allowed")):
        failures.append("core_model_trend_claim_not_allowed")
    if row.get("market_beating_objective_status") != "PASS":
        failures.append("market_beating_objective_not_pass")
    if (row.get("model_positive_skill_days") or 0) < BROAD_MIN_POSITIVE_SKILL_DAYS:
        failures.append("positive_skill_days_below_3")
    rolling = row.get("model_rolling_daily_first_brier_skill")
    if rolling is None or rolling < 0:
        failures.append("rolling_daily_first_skill_negative")
    if (row.get("evidence_promotion_grade_market_days") or 0) < BROAD_MIN_PROMOTION_GRADE_MARKET_DAYS:
        failures.append("promotion_grade_market_days_below_84")
    if row.get("ops_live_forward_slo_status") != "PASS":
        failures.append("live_forward_slo_not_pass")
    if row.get("evidence_independent_baseline_status") != "PRESENT":
        failures.append("independent_baseline_missing")
    if row.get("runtime_identity_status") == "BLOCK":
        failures.append(row.get("runtime_identity_blocking_reason") or "runtime_identity_blocked")
    return failures


def build_progress_row(
    *,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    daily_refresh_status=None,
    generated_at_utc=None,
):
    backtest_root = Path(backtest_root)
    daily_refresh = daily_refresh_status or _artifact(backtest_root, "daily_refresh_status.json")
    generated_at = generated_at_utc or utc_iso()
    run_date = str(
        daily_refresh.get("generated_at_utc")
        or daily_refresh.get("finished_at_utc")
        or generated_at
    )[:10]
    progress = _artifact(backtest_root, "progress_audit.json")
    promotion = _artifact(backtest_root, "f_family_promotion_refresh.json")
    fleet = _artifact(backtest_root, "fleet_observability.json")
    variant = _artifact(backtest_root, "model_variant_evidence_growth.json")
    frozen_baseline = _artifact(backtest_root, "frozen_baseline_replay_trend.json")
    snapshot_eval = _artifact(backtest_root, "snapshot_evaluation.json")
    daily_learning = _artifact(backtest_root, "daily_learning.json")
    market_objective = _artifact(backtest_root, "market_beating_objective_scoreboard.json")
    trading = build_trading_evidence_summary(
        mm_runs_root=backtest_root.parent / "mm_runs",
        taker_runs_root=backtest_root.parent / "taker_runs",
    )
    runtime_evidence = build_runtime_identity_evidence(
        snapshots_root=snapshots_root,
        target_date=run_date,
        mm_runs_root=backtest_root.parent / "mm_runs",
        taker_runs_root=backtest_root.parent / "taker_runs",
        reconciliation_path=backtest_root / "runtime_identity_reconciliation.json",
    )
    runtime_snapshots = runtime_evidence.get("snapshots") or {}
    trend = progress.get("core_model_trend_claim") or {}
    trend_summary = trend.get("summary") or {}
    candidate = (promotion.get("candidate") or {})
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    live_slo = fleet.get("live_forward_slo") or {}
    cadence = live_slo.get("snapshot_cadence_proof") or {}
    cadence_summary = cadence.get("summary") or {}
    source_status_summary = ((((fleet.get("collection") or {}).get("source_status_proof") or {}).get("summary")) or {})
    clob = (fleet.get("clob") or {}).get("loop") or {}
    observation = fleet.get("observation_trigger") or {}
    backup = fleet.get("tape_backup") or {}
    current_soak = fleet.get("current_code_soak") or {}
    frozen_status = _frozen_baseline_status(frozen_baseline)
    frozen_overall = frozen_baseline.get("overall") or {}
    frozen_coverage = frozen_baseline.get("coverage") or {}
    disk = _disk_preflight(daily_refresh, backtest_root)
    mm = trading.get("market_making") or {}
    mm_starvation = mm.get("evidence_starvation") or {}
    mm_starvation_latest = mm_starvation.get("latest") or {}
    mm_starvation_owner_source = mm_starvation.get("latest_starved") or mm_starvation_latest
    mm_starvation_recovery_source = (
        mm_starvation.get("latest_unrecovered_starved")
        or mm_starvation.get("latest_starved")
        or mm_starvation_latest
    )
    taker = trading.get("taker") or {}
    taker_quality = taker.get("quality_gate") or {}
    label_quality = _quality_counts(daily_refresh)
    row = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "run_date": run_date,
        "daily_refresh_status": _daily_refresh_status(daily_refresh),
        "daily_refresh_duration_seconds": daily_refresh.get("duration_seconds"),
        "daily_refresh_blockers": json_field([
            {
                "step": step.get("name"),
                "status": step.get("status"),
                "error": step.get("error"),
                "root_cause_class": step.get("root_cause_class"),
            }
            for step in daily_refresh.get("steps") or []
            if step.get("status") == "error"
        ]),
        "model_claim_allowed": bool(trend.get("claim_allowed")),
        "model_claim_status": trend.get("status"),
        "model_rolling_daily_first_brier_skill": maybe_float(trend_summary.get("rolling_daily_first_brier_skill")),
        "model_positive_skill_days": maybe_int(trend_summary.get("positive_skill_days")),
        "model_positive_daily_first_days": maybe_int(trend_summary.get("positive_daily_first_days")),
        "model_minus_market_gap_slope_per_day": maybe_float(trend_summary.get("model_minus_market_brier_slope_per_day")),
        "model_brier_skill_slope_per_day": maybe_float(trend_summary.get("brier_skill_slope_per_day")),
        "candidate_delta_vs_current": maybe_float(aggregate.get("delta_vs_current")),
        "candidate_delta_vs_market": maybe_float(aggregate.get("delta_vs_market")),
        "candidate_verdict": candidate.get("verdict"),
        "candidate_cutover_decision": candidate.get("cutover_decision"),
        "evidence_complete_labels": maybe_int(label_quality.get("complete")),
        "evidence_label_total": maybe_int(((daily_refresh.get("summary") or {}).get("labels") or {}).get("total")),
        "evidence_promotion_grade_market_days": maybe_int(trend_summary.get("promotion_grade_market_days")),
        "evidence_corpus_market_days": maybe_int(corpus.get("market_day_count")),
        "evidence_corpus_snapshots": maybe_int(corpus.get("snapshot_count")),
        "evidence_snapshot_inventory_count": maybe_int(((snapshot_eval.get("snapshot_inventory") or {}).get("snapshot_count"))),
        "evidence_independent_baseline_status": (
            "PRESENT" if frozen_status == "PRESENT" else _independent_baseline_status(variant)
        ),
        "evidence_frozen_baseline_status": frozen_status or "MISSING",
        "evidence_frozen_baseline_id": frozen_baseline.get("baseline_id"),
        "evidence_frozen_baseline_current_code_identity": frozen_baseline.get("current_code_identity"),
        "evidence_frozen_baseline_shared_observations": maybe_int(
            frozen_coverage.get("shared_observations")
        ),
        "evidence_frozen_baseline_shared_market_days": maybe_int(
            frozen_coverage.get("shared_market_days")
        ),
        "evidence_frozen_baseline_brier_delta_current_minus_baseline": maybe_float(
            frozen_overall.get("brier_delta_current_minus_baseline")
        ),
        "evidence_frozen_baseline_brier_delta_current_minus_market": maybe_float(
            frozen_overall.get("brier_delta_current_minus_market")
        ),
        "evidence_variant_sla_status": ((variant.get("evidence_sla") or {}).get("status")),
        "runtime_identity_status": runtime_evidence.get("status"),
        "runtime_identity_mixed": runtime_evidence.get("mixed_runtime_identity"),
        "runtime_identity_count": runtime_evidence.get("runtime_identity_count"),
        "runtime_identity_snapshot_rows": runtime_evidence.get("snapshot_row_count"),
        "runtime_identity_blocking_reason": runtime_evidence.get("blocking_reason"),
        "runtime_identity_reconciliation_status": runtime_evidence.get("reconciliation_status"),
        "runtime_identity_reconciliation_allowed": runtime_evidence.get("reconciliation_allowed"),
        "runtime_identity_segments": json_field(runtime_snapshots.get("segments") or []),
        "runtime_identity_trading_runs": json_field(runtime_evidence.get("trading_runs") or {}),
        "market_beating_objective_status": _scoreboard_status(market_objective),
        "market_beating_objective_first_blocker": _scoreboard_first_blocker(market_objective),
        "market_beating_objective_first_success_lane": (
            (market_objective.get("headline") or {}).get("first_success_lane")
        ),
        "market_beating_weather_only_status": (
            ((market_objective.get("decisions") or {}).get("weather_only_market_beating") or {}).get("status")
        ),
        "market_beating_residual_edge_status": (
            ((market_objective.get("decisions") or {}).get("residual_edge") or {}).get("status")
        ),
        "market_beating_executable_profitability_status": (
            ((market_objective.get("decisions") or {}).get("executable_profitability") or {}).get("status")
        ),
        "market_beating_anti_anchoring_status": ((market_objective.get("anti_anchoring") or {}).get("status")),
        "ops_fleet_status": fleet.get("status"),
        "ops_live_forward_slo_status": live_slo.get("status"),
        "ops_live_forward_slo_counts": live_slo.get("counts_toward_live_forward_gate"),
        "ops_snapshot_gap_count": maybe_int(cadence_summary.get("total_gap_count")),
        "ops_snapshot_max_gap_minutes": maybe_float(cadence_summary.get("max_gap_minutes")),
        "ops_snapshot_gap_blocked_markets": maybe_int(cadence_summary.get("snapshot_coverage_gap_blocked_market_count")),
        "ops_source_status_blocked_markets": maybe_int(source_status_summary.get("source_status_blocked_market_count")),
        "ops_clob_status": clob.get("state"),
        "ops_observation_trigger_status": observation.get("state"),
        "ops_current_code_soak_status": current_soak.get("status"),
        "ops_backup_status": backup.get("status"),
        "ops_disk_preflight_status": disk.get("status"),
        "ops_disk_free_bytes": disk.get("free_bytes"),
        "ops_disk_required_free_bytes": disk.get("required_free_bytes"),
        "ops_disk_headroom_bytes": disk.get("headroom_bytes"),
        "trading_mm_evidence_mode": mm.get("evidence_mode"),
        "trading_mm_counts_toward_live_forward": mm.get("counts_toward_live_forward_gate"),
        "trading_mm_model_review_countable_markets": ((mm.get("model_review_evidence") or {}).get("countable_market_count")),
        "trading_mm_paper_countable_markets": ((mm.get("paper_trading_evidence") or {}).get("countable_market_count")),
        "trading_mm_live_trade_permission_countable_markets": ((mm.get("live_trade_permission_evidence") or {}).get("countable_market_count")),
        "trading_mm_countable_paper_market_day_count": mm_starvation.get("countable_paper_market_day_count"),
        "trading_mm_starved_active_day_streak": mm_starvation.get("starved_active_day_streak"),
        "trading_mm_unrecovered_starved_active_day_streak": mm_starvation.get(
            "unrecovered_starved_active_day_streak"
        ),
        "trading_mm_recovered_starved_active_day_count": mm_starvation.get(
            "recovered_starved_active_day_count"
        ),
        "trading_mm_unrecovered_starved_active_day_count": mm_starvation.get(
            "unrecovered_starved_active_day_count"
        ),
        "trading_mm_recovery_attempted_starved_active_day_count": mm_starvation.get(
            "recovery_attempted_starved_active_day_count"
        ),
        "trading_mm_evidence_starvation_status": mm_starvation.get("status"),
        "trading_mm_preflight_recovery_status": mm_starvation_recovery_source.get(
            "preflight_recovery_closeout_status"
        ),
        "trading_mm_preflight_recovery_attempted": mm_starvation_recovery_source.get(
            "preflight_recovery_attempted"
        ),
        "trading_mm_preflight_recovery_recovered": mm_starvation_recovery_source.get(
            "preflight_recovery_recovered"
        ),
        "trading_mm_preflight_recovery_artifact_path": mm_starvation_recovery_source.get(
            "preflight_recovery_closeout_path"
        ),
        "trading_mm_post_repair_preflight_status": mm_starvation_recovery_source.get(
            "post_repair_preflight_status"
        ),
        "trading_mm_latest_preflight_blocked_market_fraction": mm_starvation_latest.get(
            "preflight_blocked_market_fraction"
        ),
        "trading_mm_current_high_trust_no_quote_count": mm.get("current_high_trust_no_quote_count"),
        "trading_mm_evidence_starvation_owner_items": json_field(
            mm_starvation_owner_source.get("recovery_owner_items") or []
        ),
        "trading_mm_quote_rows": mm.get("quote_rows"),
        "trading_mm_live_trade_permission_rows": mm.get("live_trade_permission_rows"),
        "trading_taker_fills": taker.get("filled_orders"),
        "trading_taker_net_pnl_usdc": taker.get("net_pnl_usdc"),
        "trading_taker_settlement_pnl_usdc": taker.get("settlement_pnl_usdc"),
        "trading_taker_mark_to_market_pnl_usdc": taker.get("mark_to_market_pnl_usdc"),
        "trading_taker_pnl_source": taker.get("pnl_source"),
        "trading_taker_pnl_evidence_status": taker.get("pnl_evidence_status"),
        "trading_taker_settled_orders": taker.get("settled_order_count"),
        "trading_taker_unsettled_orders": taker.get("unsettled_order_count"),
        "trading_taker_reconciliation_status": taker.get("settlement_reconciliation_status"),
        "trading_taker_root_cause": taker.get("root_cause_class"),
        "trading_taker_quality_status": taker_quality.get("status"),
        "trading_taker_strategy_count": taker.get("strategy_count"),
        "trading_taker_best_strategy_id": taker.get("best_strategy_id"),
        "trading_taker_best_strategy_net_pnl_usdc": taker.get("best_strategy_net_pnl_usdc"),
        "trading_taker_best_settlement_scored_strategy_id": taker.get("best_settlement_scored_strategy_id"),
        "trading_taker_strategy_quality_candidate_id": taker.get("strategy_quality_candidate_id"),
        "trading_taker_strategy_quality_candidate_status": taker.get("strategy_quality_candidate_status"),
        "trading_taker_strategy_quality_candidate_net_pnl_usdc": taker.get(
            "strategy_quality_candidate_net_pnl_usdc"
        ),
        "trading_taker_promotion_evidence_basis": taker.get("promotion_evidence_basis"),
        "trading_taker_mtm_promotion_allowed": taker.get("mtm_promotion_allowed"),
        "trading_taker_tail_fill_quality_status": taker.get("tail_fill_quality_status"),
        "trading_taker_low_price_tail_fill_count": taker.get("low_price_tail_fill_count"),
        "trading_taker_low_price_tail_fill_fraction": taker.get("low_price_tail_fill_fraction"),
        "trading_taker_tail_fill_alert_count": taker.get("tail_fill_alert_count"),
        "trading_taker_tail_fill_alerts": json_field(taker.get("tail_fill_alerts") or []),
        "trading_taker_current_high_trust_no_trade_count": taker.get("current_high_trust_no_trade_count"),
        "trading_taker_active_strategy_id": taker.get("active_strategy_id"),
        "trading_taker_active_strategy_lifecycle": taker.get("active_strategy_lifecycle"),
        "trading_taker_active_strategy_lifecycle_status": taker.get("active_strategy_lifecycle_status"),
        "trading_taker_active_strategy_promotion_eligible": taker.get("active_strategy_promotion_eligible"),
        "trading_taker_active_strategy_next_action": taker.get("active_strategy_next_action"),
        "trading_taker_active_strategy_paper_only_reason": taker.get("active_strategy_paper_only_reason"),
        "trading_taker_active_strategy_requalification_route": taker.get(
            "active_strategy_requalification_route"
        ),
        "trading_taker_active_strategy_demotion_code": taker.get("active_strategy_demotion_code"),
        "trading_taker_active_strategy_complete_label_sample_count": taker.get(
            "active_strategy_complete_label_sample_count"
        ),
        "trading_taker_active_strategy_total_label_sample_count": taker.get(
            "active_strategy_total_label_sample_count"
        ),
        "trading_taker_active_strategy_canary_settled_order_count": taker.get(
            "active_strategy_canary_settled_order_count"
        ),
        "trading_taker_active_strategy_canary_min_settled_orders": taker.get(
            "active_strategy_canary_min_settled_orders"
        ),
        "trading_taker_active_strategy_canary_settled_market_count": taker.get(
            "active_strategy_canary_settled_market_count"
        ),
        "trading_taker_active_strategy_canary_min_settled_markets": taker.get(
            "active_strategy_canary_min_settled_markets"
        ),
        "trading_taker_active_strategy_canary_tail_fill_fraction": taker.get(
            "active_strategy_canary_tail_fill_fraction"
        ),
        "trading_taker_active_strategy_canary_max_tail_fill_fraction": taker.get(
            "active_strategy_canary_max_tail_fill_fraction"
        ),
        "trading_taker_active_strategy_canary_age_days": taker.get("active_strategy_canary_age_days"),
        "daily_learning_status": daily_learning.get("status"),
    }
    failures = broad_claim_failures(row)
    row["broad_improvement_claim_allowed"] = not failures
    row["broad_improvement_claim_failures"] = json_field(failures)
    return row


def ledger_columns(row):
    return list(row.keys())


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_date = row.get("run_date")
    rows = [
        existing
        for existing in read_jsonl(path)
        if not run_date or existing.get("run_date") != run_date
    ]
    rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for existing in rows:
            handle.write(json.dumps(existing, sort_keys=True, default=str) + "\n")
    return path


def append_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    run_date = row.get("run_date")
    rows = []
    if path.exists() and path.stat().st_size > 0:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [
                existing
                for existing in csv.DictReader(handle)
                if not run_date or existing.get("run_date") != str(run_date)
            ]
    rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ledger_columns(row), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _avg(rows, key):
    values = [maybe_float(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_report(rows):
    rows = list(rows or [])
    recent7 = rows[-7:]
    recent14 = rows[-14:]
    latest = rows[-1] if rows else {}
    lines = [
        "# Daily Progress Ledger",
        "",
        f"Rows: `{len(rows)}`",
        "",
        "## Latest Claim Gate",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Run date", latest.get("run_date") or "-"],
            ["Broad improvement claim allowed", latest.get("broad_improvement_claim_allowed")],
            ["Claim failures", latest.get("broad_improvement_claim_failures") or "[]"],
            ["Market-beating objective", latest.get("market_beating_objective_status") or "-"],
            ["Market-beating first blocker", latest.get("market_beating_objective_first_blocker") or "-"],
            ["Market-beating success lane", latest.get("market_beating_objective_first_success_lane") or "-"],
            ["Market-beating weather-only", latest.get("market_beating_weather_only_status") or "-"],
            ["Market-beating residual edge", latest.get("market_beating_residual_edge_status") or "-"],
            [
                "Market-beating executable profitability",
                latest.get("market_beating_executable_profitability_status") or "-",
            ],
            ["Market-beating anti-anchoring", latest.get("market_beating_anti_anchoring_status") or "-"],
            ["Rolling daily-first skill", fmt(latest.get("model_rolling_daily_first_brier_skill"))],
            ["Positive skill days", latest.get("model_positive_skill_days")],
            ["Promotion-grade market-days", latest.get("evidence_promotion_grade_market_days")],
            ["Live-forward SLO", latest.get("ops_live_forward_slo_status") or "-"],
            ["Snapshot gaps", latest.get("ops_snapshot_gap_count")],
            ["Source-status blocked markets", latest.get("ops_source_status_blocked_markets")],
            ["Current-code soak", latest.get("ops_current_code_soak_status") or "-"],
            ["Disk preflight", latest.get("ops_disk_preflight_status") or "-"],
            ["Disk headroom bytes", latest.get("ops_disk_headroom_bytes")],
            ["Independent baseline", latest.get("evidence_independent_baseline_status") or "-"],
            ["Frozen baseline", latest.get("evidence_frozen_baseline_status") or "-"],
            ["Frozen baseline id", latest.get("evidence_frozen_baseline_id") or "-"],
            ["Frozen shared observations", fmt(latest.get("evidence_frozen_baseline_shared_observations"))],
            [
                "Frozen Brier current-baseline",
                fmt(latest.get("evidence_frozen_baseline_brier_delta_current_minus_baseline")),
            ],
            ["Runtime identity status", latest.get("runtime_identity_status") or "-"],
            ["Runtime identity mixed", latest.get("runtime_identity_mixed")],
            ["Runtime identity count", latest.get("runtime_identity_count")],
            ["Runtime identity rows", latest.get("runtime_identity_snapshot_rows")],
            ["Runtime identity blocker", latest.get("runtime_identity_blocking_reason") or "-"],
            ["Runtime reconciliation", latest.get("runtime_identity_reconciliation_status") or "-"],
            ["MM evidence mode", latest.get("trading_mm_evidence_mode") or "-"],
            ["MM evidence starvation", latest.get("trading_mm_evidence_starvation_status") or "-"],
            ["MM starved active-day streak", fmt(latest.get("trading_mm_starved_active_day_streak"))],
            ["MM unrecovered starved streak", fmt(latest.get("trading_mm_unrecovered_starved_active_day_streak"))],
            ["MM recovery closeout", latest.get("trading_mm_preflight_recovery_status") or "-"],
            ["MM post-repair preflight", latest.get("trading_mm_post_repair_preflight_status") or "-"],
            ["MM countable paper market-days", fmt(latest.get("trading_mm_countable_paper_market_day_count"))],
            ["MM current-high trust no-quotes", fmt(latest.get("trading_mm_current_high_trust_no_quote_count"))],
            ["Taker quality", latest.get("trading_taker_quality_status") or "-"],
            ["Taker net P&L", fmt(latest.get("trading_taker_net_pnl_usdc"))],
            ["Taker P&L source", latest.get("trading_taker_pnl_source") or "-"],
            ["Taker P&L evidence", latest.get("trading_taker_pnl_evidence_status") or "-"],
            ["Taker settled / unsettled", f"{latest.get('trading_taker_settled_orders')}/{latest.get('trading_taker_unsettled_orders')}"],
            ["Taker reconciliation", latest.get("trading_taker_reconciliation_status") or "-"],
            ["Taker best strategy", latest.get("trading_taker_best_strategy_id") or "-"],
            ["Taker strategy candidate", latest.get("trading_taker_strategy_quality_candidate_id") or "-"],
            [
                "Taker strategy candidate status",
                latest.get("trading_taker_strategy_quality_candidate_status") or "-",
            ],
            ["Taker promotion evidence", latest.get("trading_taker_promotion_evidence_basis") or "-"],
            ["Taker MTM can promote", latest.get("trading_taker_mtm_promotion_allowed")],
            ["Taker tail quality", latest.get("trading_taker_tail_fill_quality_status") or "-"],
            [
                "Taker tail fills",
                (
                    f"{fmt(latest.get('trading_taker_low_price_tail_fill_count'))} "
                    f"({fmt(latest.get('trading_taker_low_price_tail_fill_fraction'))})"
                ),
            ],
            ["Taker tail alerts", fmt(latest.get("trading_taker_tail_fill_alert_count"))],
            ["Taker current-high trust no-trades", fmt(latest.get("trading_taker_current_high_trust_no_trade_count"))],
            ["Taker active strategy", latest.get("trading_taker_active_strategy_id") or "-"],
            ["Taker active lifecycle", latest.get("trading_taker_active_strategy_lifecycle_status") or "-"],
            ["Taker active next action", latest.get("trading_taker_active_strategy_next_action") or "-"],
            ["Taker active paper-only reason", latest.get("trading_taker_active_strategy_paper_only_reason") or "-"],
            ["Taker active demotion code", latest.get("trading_taker_active_strategy_demotion_code") or "-"],
            [
                "Taker canary complete labels",
                (
                    f"{fmt(latest.get('trading_taker_active_strategy_complete_label_sample_count'))}/"
                    f"{fmt(latest.get('trading_taker_active_strategy_total_label_sample_count'))}"
                ),
            ],
            [
                "Taker canary settled orders",
                (
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_settled_order_count'))}/"
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_min_settled_orders'))}"
                ),
            ],
            [
                "Taker canary settled markets",
                (
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_settled_market_count'))}/"
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_min_settled_markets'))}"
                ),
            ],
            [
                "Taker canary tail fraction",
                (
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_tail_fill_fraction'))}/"
                    f"{fmt(latest.get('trading_taker_active_strategy_canary_max_tail_fill_fraction'))}"
                ),
            ],
        ],
    )
    lines += ["", "## 7 And 14 Day Rollup", ""]
    lines += markdown_table(
        ["Window", "Rows", "Claim Days", "Avg Rolling Skill", "Avg Snapshot Gaps", "Latest Taker P&L"],
        [
            [
                "7d",
                len(recent7),
                sum(1 for row in recent7 if row.get("broad_improvement_claim_allowed")),
                fmt(_avg(recent7, "model_rolling_daily_first_brier_skill")),
                fmt(_avg(recent7, "ops_snapshot_gap_count")),
                fmt(latest.get("trading_taker_net_pnl_usdc")),
            ],
            [
                "14d",
                len(recent14),
                sum(1 for row in recent14 if row.get("broad_improvement_claim_allowed")),
                fmt(_avg(recent14, "model_rolling_daily_first_brier_skill")),
                fmt(_avg(recent14, "ops_snapshot_gap_count")),
                fmt(latest.get("trading_taker_net_pnl_usdc")),
            ],
        ],
    )
    lines += ["", "## Recent Rows", ""]
    lines += markdown_table(
        [
            "Date", "Claim", "Market Beat", "Rolling Skill", "Positive Days", "Promo Days",
            "Live SLO", "Snapshot Gaps", "MM Mode", "Taker P&L", "Taker Source",
        ],
        [
            [
                row.get("run_date"),
                row.get("broad_improvement_claim_allowed"),
                row.get("market_beating_objective_status") or "-",
                fmt(row.get("model_rolling_daily_first_brier_skill")),
                row.get("model_positive_skill_days"),
                row.get("evidence_promotion_grade_market_days"),
                row.get("ops_live_forward_slo_status"),
                row.get("ops_snapshot_gap_count"),
                row.get("trading_mm_evidence_mode"),
                fmt(row.get("trading_taker_net_pnl_usdc")),
                row.get("trading_taker_pnl_source") or "-",
            ]
            for row in rows[-14:]
        ],
    )
    lines.append("")
    return "\n".join(lines)


def write_report(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(rows), encoding="utf-8")
    return path


def write_progress_outputs(
    row,
    *,
    jsonl_out=DEFAULT_JSONL_OUT,
    csv_out=DEFAULT_CSV_OUT,
    latest_out=DEFAULT_LATEST_OUT,
    report_out=DEFAULT_REPORT_OUT,
):
    jsonl_path = append_jsonl(jsonl_out, row)
    csv_path = append_csv(csv_out, row)
    latest_path = write_json_atomic(latest_out, row, trailing_newline=True)
    report_path = write_report(report_out, read_jsonl(jsonl_path))
    return {
        "status": "OK",
        "jsonl_out": str(jsonl_path),
        "csv_out": str(csv_path),
        "latest_out": str(latest_path),
        "report_out": str(report_path),
        "market_beating_objective_status": row.get("market_beating_objective_status"),
        "market_beating_objective_first_blocker": row.get("market_beating_objective_first_blocker"),
        "broad_improvement_claim_allowed": row.get("broad_improvement_claim_allowed"),
        "broad_improvement_claim_failures": json.loads(row.get("broad_improvement_claim_failures") or "[]"),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Append one daily progress ledger row.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--jsonl-out", default=str(DEFAULT_JSONL_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--latest-out", default=str(DEFAULT_LATEST_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    row = build_progress_row(backtest_root=args.backtest_root, snapshots_root=args.snapshots_root)
    result = write_progress_outputs(
        row,
        jsonl_out=args.jsonl_out,
        csv_out=args.csv_out,
        latest_out=args.latest_out,
        report_out=args.report_out,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
