"""Settled-day analysis barrier contracts for daily refresh."""

from __future__ import annotations

from collections import Counter
from datetime import date

from weather.backtesting.settlement_ledger import DEFAULT_LABELS_CSV, DEFAULT_LEDGER_ROOT
from weather.operations import settled_day_freshness
from weather.operations.daily_refresh_locks import as_path, backtest_path, utc_iso, write_json
from weather.schema_registry import schema_version


SETTLED_DAY_ANALYSIS_DEPENDENCIES = (
    {
        "step": "public_wu_settlement_restore",
        "phase": "settlement_source_restoration",
        "critical": True,
        "target_date_fields": ("target_date",),
        "skippable_as_non_critical": False,
    },
    {
        "step": "market_day_labels_finalize",
        "phase": "label_finalization",
        "critical": True,
    },
    {
        "step": "exchange_economics_rule_drift",
        "phase": "exchange_economics_currentness",
        "critical": True,
        "target_date_fields": ("target_date",),
        "skippable_as_non_critical": False,
    },
    {
        "step": "taker_finalization_watchdog",
        "phase": "post_label_taker_finalization",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "taker_edge_permission_map",
        "phase": "post_label_taker_permission_map",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "taker_tail_casebook",
        "phase": "post_label_taker_evidence",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "maker_paper_score",
        "phase": "post_label_maker_evidence",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "settlement_source_audit",
        "phase": "label_provenance_audit",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "trading_evidence",
        "phase": "post_label_trading_evidence",
        "critical": True,
        "target_date_fields": ("target_date", "run_date"),
        "skippable_as_non_critical": True,
    },
    {
        "step": "replay_status_backfill",
        "phase": "settled_day_replay_rehydration",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "hourly_model_performance",
        "phase": "model_skill_scoring",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "ten_minute_model_performance",
        "phase": "model_skill_scoring",
        "critical": True,
        "skippable_as_non_critical": True,
    },
    {
        "step": "price_free_model_learning",
        "phase": "model_skill_scoring",
        "critical": False,
        "skippable_as_non_critical": True,
    },
    {
        "step": "model_market_disagreement_rehydration",
        "phase": "post_label_disagreement_audit_rehydration",
        "critical": True,
        "target_date_fields": ("target_date",),
        "skippable_as_non_critical": True,
    },
)


class SettledDayAnalysisBarrierError(RuntimeError):
    """Raised when final settled-day analysis must not continue."""

    def __init__(self, message, payload):
        super().__init__(message)
        self.payload = dict(payload or {})


def parse_date_arg(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def settled_analysis_target_date(args):
    configured = getattr(args, "settled_analysis_target_date", "") or ""
    if configured:
        return parse_date_arg(configured)
    return settled_day_freshness.target_date_from_args(
        target_date=None,
        as_of=getattr(args, "as_of", None),
    )


def _parse_market_ids(value):
    if not value:
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _dependency_status(step, dependency, target_date):
    result = step.get("result") or {}
    step_status = step.get("status")
    result_status = result.get("status")
    blocker = None
    non_critical = False
    if not step:
        blocker = "step_missing"
    elif step_status == "error":
        blocker = step.get("error") or "step_error"
    elif result_status == "SKIPPED" and dependency.get("skippable_as_non_critical"):
        non_critical = True
    elif result_status == "SKIPPED" and dependency.get("critical"):
        blocker = "step_skipped"
    elif result_status in {"BLOCK", "FAIL", "BREACH", "CRITICAL", "ERROR"} and dependency.get("critical"):
        blocker = f"step_result_status={result_status}"

    observed_dates = []
    for field in dependency.get("target_date_fields") or ():
        value = result.get(field)
        if value:
            observed_dates.append(str(value)[:10])
    mismatched_dates = sorted({value for value in observed_dates if value != target_date})
    if mismatched_dates and dependency.get("critical"):
        blocker = f"target_date_mismatch={','.join(mismatched_dates)} expected={target_date}"

    return {
        "step": dependency["step"],
        "phase": dependency.get("phase"),
        "critical": bool(dependency.get("critical")),
        "step_status": step_status,
        "result_status": result_status,
        "target_date": target_date,
        "observed_target_dates": sorted(set(observed_dates)),
        "non_critical": non_critical,
        "blocker": blocker,
    }


def _label_countability_from_freshness(freshness, finalize_result=None):
    finalize_result = finalize_result or {}
    quality_counts = Counter()
    finalize_quality_counts = finalize_result.get("quality_counts") or {}
    if finalize_quality_counts:
        quality_counts.update({
            key: int(value or 0)
            for key, value in finalize_quality_counts.items()
        })
    else:
        for row in freshness.get("markets") or []:
            grade = row.get("quality_grade")
            if grade:
                quality_counts[str(grade)] += 1

    material_counts = Counter()
    material_available = bool(finalize_result.get("promotion_countability_available"))
    if finalize_result.get("material_coverage_counts"):
        material_counts.update({
            key: int(value or 0)
            for key, value in (finalize_result.get("material_coverage_counts") or {}).items()
        })
    else:
        for row in freshness.get("markets") or []:
            grade = row.get("material_coverage_grade")
            if grade:
                material_available = True
                material_counts[str(grade)] += 1

    if material_available:
        if finalize_result.get("promotion_countability_available"):
            total_labels = int(finalize_result.get("label_count") or 0)
            countable_count = int(finalize_result.get("promotion_countable_label_count") or 0)
            blocked_count = int(finalize_result.get("promotion_blocked_label_count") or 0)
            blocked_sample = finalize_result.get("material_coverage_blocked_sample") or []
        else:
            material_rows = [
                row for row in freshness.get("markets") or []
                if row.get("material_coverage_grade")
            ]
            total_labels = len(material_rows)
            countable_count = sum(1 for row in material_rows if _truthy(row.get("promotion_countable")))
            blocked_rows = [row for row in material_rows if not _truthy(row.get("promotion_countable"))]
            blocked_count = len(blocked_rows)
            blocked_sample = [
                {
                    "event_slug": row.get("event_slug"),
                    "market_id": row.get("market_id"),
                    "target_date": row.get("target_date"),
                    "quality_grade": row.get("quality_grade"),
                    "material_coverage_grade": row.get("material_coverage_grade"),
                    "material_coverage_reason": row.get("material_coverage_reason"),
                    "promotion_countable_reason": row.get("promotion_countable_reason"),
                }
                for row in blocked_rows[:5]
            ]

        partial_count = int(quality_counts.get("partial") or 0)
        promotion_countable = blocked_count == 0
        if promotion_countable:
            status = "promotion_countable"
            if partial_count:
                reason = (
                    f"all selected settled labels are promotion-countable; "
                    f"{partial_count} strict partial label(s) passed material coverage"
                )
            else:
                reason = "all selected settled labels are promotion-countable"
        else:
            status = "diagnostic_only"
            reason = f"{blocked_count} settled label(s) are not material-coverage promotion-countable"
        return {
            "status": status,
            "promotion_countable": promotion_countable,
            "diagnostic_only": not promotion_countable,
            "partial_label_count": partial_count,
            "strict_partial_label_count": partial_count,
            "quality_counts": dict(sorted(quality_counts.items())),
            "material_coverage_counts": dict(sorted(material_counts.items())),
            "material_promotion_countable_label_count": countable_count,
            "material_promotion_blocked_label_count": blocked_count,
            "material_total_label_count": total_labels,
            "material_coverage_blocked_sample": blocked_sample,
            "reason": reason,
        }

    partial_count = int(quality_counts.get("partial") or 0)
    if partial_count:
        status = "diagnostic_only"
        promotion_countable = False
        reason = f"{partial_count} settled label(s) have quality_grade=partial"
    else:
        status = "promotion_countable"
        promotion_countable = True
        reason = "all selected settled labels are promotion-countable"
    return {
        "status": status,
        "promotion_countable": promotion_countable,
        "diagnostic_only": not promotion_countable,
        "partial_label_count": partial_count,
        "strict_partial_label_count": partial_count,
        "quality_counts": dict(sorted(quality_counts.items())),
        "reason": reason,
    }


def _settled_day_resume_command(args):
    command = [
        "python",
        "-m",
        "weather.operations.daily_refresh",
        "run",
        "--resume-from-step",
        "settled_day_analysis_barrier",
        "--backtest-root",
        str(args.backtest_root),
        "--snapshots-root",
        str(args.snapshots_root),
    ]
    if getattr(args, "as_of", None):
        command += ["--as-of", str(args.as_of)]
    target = getattr(args, "settled_analysis_target_date", "") or ""
    if target:
        command += ["--settled-analysis-target-date", str(target)]
    return " ".join(command)


def build_settled_day_analysis_barrier(args, *, steps_so_far=None):
    target = settled_analysis_target_date(args)
    target_date = target.isoformat()
    steps_by_name = {step.get("name"): step for step in steps_so_far or []}
    freshness_payload = settled_day_freshness.build_freshness_payload(
        snapshots_root=getattr(args, "snapshots_root", settled_day_freshness.DEFAULT_SNAPSHOTS_ROOT),
        labels_csv=getattr(args, "labels_csv", DEFAULT_LABELS_CSV),
        ledger_root=getattr(args, "ledger_root", DEFAULT_LEDGER_ROOT),
        target_date=target,
        as_of=getattr(args, "as_of", None),
        market_ids=_parse_market_ids(getattr(args, "markets", "")),
    )
    freshness_json, freshness_report = settled_day_freshness.write_outputs(
        freshness_payload,
        backtest_path(args, "settled_day_freshness.json"),
        backtest_path(args, "settled_day_freshness_report.md"),
    )
    dependencies = [
        _dependency_status(steps_by_name.get(dependency["step"]) or {}, dependency, target_date)
        for dependency in SETTLED_DAY_ANALYSIS_DEPENDENCIES
    ]
    blockers = []
    if freshness_payload.get("status") == "FAIL":
        summary = freshness_payload.get("summary") or {}
        blockers.append({
            "component": "settled_day_freshness",
            "detail": (
                f"{summary.get('incomplete_market_count')} incomplete market(s); "
                f"{summary.get('needs_finalization_count')} need finalization; "
                f"{summary.get('needs_replay_status_repair_count')} need replay-status repair"
            ),
            "repair_command": freshness_payload.get("repair_command"),
            "replay_status_repair_command": freshness_payload.get("replay_status_repair_command"),
        })
    for dependency in dependencies:
        if dependency.get("blocker"):
            blockers.append({
                "component": dependency.get("step"),
                "detail": dependency.get("blocker"),
                "phase": dependency.get("phase"),
                "resume_command": _settled_day_resume_command(args),
            })
    step_order = {
        step.get("name"): index
        for index, step in enumerate(steps_so_far or [])
        if step.get("name")
    }
    restore_index = step_order.get("public_wu_settlement_restore")
    finalize_index = step_order.get("market_day_labels_finalize")
    if restore_index is not None and finalize_index is not None and restore_index > finalize_index:
        blockers.append({
            "component": "public_wu_settlement_restore",
            "detail": "step_order_violation=public_wu_settlement_restore_after_market_day_labels_finalize",
            "phase": "settlement_source_restoration",
            "resume_command": _settled_day_resume_command(args),
        })
    finalize = (steps_by_name.get("market_day_labels_finalize") or {}).get("result") or {}
    countability = _label_countability_from_freshness(freshness_payload, finalize)
    status = "BLOCK" if blockers else ("DIAGNOSTIC_ONLY" if countability.get("diagnostic_only") else "PASS")
    return {
        "schema_version": schema_version("settled_day_analysis_barrier"),
        "generated_at_utc": utc_iso(),
        "status": status,
        "target_date": target_date,
        "dependency_graph": list(SETTLED_DAY_ANALYSIS_DEPENDENCIES),
        "dependencies": dependencies,
        "settled_day_freshness": {
            "status": freshness_payload.get("status"),
            "json_out": as_path(freshness_json),
            "report_out": as_path(freshness_report),
            "summary": freshness_payload.get("summary") or {},
        },
        "label_countability": countability,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "resume_command": _settled_day_resume_command(args),
        "hard_stop_pipeline": bool(blockers),
    }


def run_settled_day_analysis_barrier_step(args):
    if getattr(args, "skip_settled_day_analysis_barrier", False):
        return {"status": "SKIPPED", "reason": "skip_settled_day_analysis_barrier"}
    steps_so_far = getattr(args, "_daily_refresh_steps_so_far", None) or []
    payload = build_settled_day_analysis_barrier(args, steps_so_far=steps_so_far)
    json_out = write_json(backtest_path(args, "settled_day_analysis_barrier.json"), payload)
    payload["json_out"] = as_path(json_out)
    if payload.get("status") == "BLOCK":
        raise SettledDayAnalysisBarrierError(
            f"settled-day analysis barrier blocked target_date={payload.get('target_date')}",
            payload,
        )
    return payload
