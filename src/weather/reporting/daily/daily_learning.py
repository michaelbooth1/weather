"""Daily log-learning pack for retrain and promotion decisions.

The daily refresh produces several durable artifacts: settlement labels,
promotion/candidate replay outputs, shadow A/B checks, disagreement cases, and
data-quality audits.  This module distills those logs into one compact artifact
that records what was learned, what should feed the next retrain, and what must
block promotion claims until fixed.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from weather.io import write_json_atomic
from weather.reporting.daily import daily_rollup_freshness
from weather.reporting.daily.daily_learning_render import render_report
from weather.reporting.formatting import fmt_num, fmt_signed
from weather.reporting.market.trading_evidence import build_trading_evidence_summary


from weather.reporting.daily.daily_learning_scorecard import *  # noqa: F403


def _learning(priority, category, source, signal, action, *, evidence=None, retrain_input=False, blocker=False):
    evidence = evidence or {}
    return {
        "priority": priority,
        "category": category,
        "source": source,
        "signal": signal,
        "action": action,
        "evidence": evidence,
        "estimated_impact": _estimated_impact(evidence),
        "retrain_input": bool(retrain_input),
        "blocker": bool(blocker),
    }


def _add_input_gate_learnings(learnings, input_gate):
    gate = input_gate or {}
    coverage = gate.get("coverage") or {}
    freshness = gate.get("freshness") or {}
    consistency = gate.get("consistency") or {}
    if coverage.get("status") == "FAIL":
        critical_missing = coverage.get("critical_missing_inputs") or []
        learnings.append(_learning(
            "P0",
            "analysis_input_gate",
            "daily_learning",
            (
                f"Daily analysis input coverage FAIL: present "
                f"{coverage.get('present_count')}/{coverage.get('total_count')}; "
                f"critical missing={', '.join(critical_missing) or '-'}."
            ),
            "Regenerate the missing critical daily-analysis inputs, then rerun daily_learning and daily_flow_analysis.",
            evidence=coverage,
            blocker=True,
        ))
    if freshness.get("status") == "FAIL":
        critical_stale = freshness.get("critical_stale_inputs") or []
        learnings.append(_learning(
            "P0",
            "analysis_input_gate",
            "daily_learning",
            (
                "Daily analysis input freshness FAIL: "
                f"critical stale or unverifiable={', '.join(critical_stale) or '-'}; "
                f"newest={freshness.get('newest_input') or '-'}."
            ),
            "Regenerate stale or timestamp-invalid critical inputs from the current daily refresh, then rerun daily_learning.",
            evidence=freshness,
            blocker=True,
        ))
    if consistency.get("status") == "FAIL":
        failed = consistency.get("failed_invariants") or []
        learnings.append(_learning(
            "P0",
            "input_inconsistency",
            "daily_learning",
            "Daily analysis input inconsistency: " + (", ".join(failed) or "unknown invariant"),
            "Stop using daily-analysis readiness flags until the inconsistent upstream artifacts are regenerated or the schema definition drift is fixed.",
            evidence=consistency,
            blocker=True,
        ))


def _add_gate_learnings(learnings, gates):
    for gate in gates or []:
        status = gate.get("status")
        if status not in {"FAIL", "WARN"}:
            continue
        priority = "P0" if status == "FAIL" else "P2"
        learnings.append(_learning(
            priority,
            "validation_gate",
            "snapshot_evaluation",
            f"{gate.get('name')} is {status}: {gate.get('detail') or '-'}",
            gate.get("action") or "Review the failing evaluation gate before promotion.",
            evidence={"gate": gate.get("name"), "status": status, "severity": gate.get("severity")},
            blocker=priority == "P0",
        ))


def _add_backlog_learnings(learnings, top_slices, truncated_sources=None):
    for row in _capped_sorted_rows(
        top_slices,
        8,
        "snapshot_evaluation.improvement_backlog.top_slices",
        truncated_sources,
    ):
        delta_market = maybe_float(row.get("delta_vs_market"))
        code_effect = maybe_float(row.get("code_effect"))
        if delta_market is None and code_effect is None:
            continue
        priority = "P1" if (delta_market or 0.0) > 0.01 or (code_effect or 0.0) > 0.01 else "P2"
        group = row.get("group") if row.get("group") not in (None, "") else "-"
        learnings.append(_learning(
            priority,
            "model_gap_slice",
            row.get("source") or "snapshot_evaluation",
            f"{row.get('slice') or '-'} / {group} has weighted gap {fmt_num(row.get('excess_brier_rows'), 3)}",
            "Feed this slice into feature analysis, candidate replay, and post-retrain shadow comparison.",
            evidence={
                "slice": row.get("slice"),
                "group": group,
                "rows": row.get("rows"),
                "delta_vs_market": delta_market,
                "code_effect": code_effect,
                "excess_brier_rows": row.get("excess_brier_rows"),
            },
            retrain_input=True,
        ))


def _gap_owner_priority(row):
    return "P1" if row.get("counts_toward_core_skill_claim") else row.get("priority") or "P2"


def _add_gap_owner_learnings(learnings, rows, truncated_sources=None):
    for row in _capped_sorted_rows(
        rows,
        8,
        "promotion_refresh.gap_owner_table",
        truncated_sources,
        priority_func=_gap_owner_priority,
    ):
        priority = "P1" if row.get("counts_toward_core_skill_claim") else "P2"
        learnings.append(_learning(
            priority,
            "market_skill_gap",
            "promotion_refresh",
            (
                f"{row.get('slice')}/{row.get('group')} owner {row.get('owner')} "
                f"weighted gap {fmt_num(row.get('excess_brier_rows'), 2)}"
            ),
            (
                f"Run paired daily-first experiment `{row.get('next_experiment')}`; "
                f"artifact: {row.get('experiment_artifact')}; {row.get('clearance_rule')}"
            ),
            evidence=row,
            retrain_input=bool(row.get("counts_toward_core_skill_claim")),
        ))


def _add_data_recommendations(learnings, recommendations, truncated_sources=None):
    for item in _capped_sorted_rows(
        recommendations,
        8,
        "data_layer_audit.recommendations",
        truncated_sources,
    ):
        priority = str(item.get("priority") or "P2")
        if priority not in {"P0", "P1", "P2", "P3"}:
            priority = "P2"
        detail = first_present(
            item.get("recommendation"),
            item.get("detail"),
            item.get("action"),
            "Review data-layer recommendation.",
        )
        learnings.append(_learning(
            priority,
            "data_quality",
            "data_layer_audit",
            item.get("area") or item.get("name") or "data layer recommendation",
            detail,
            evidence=item,
            blocker=priority == "P0",
        ))


def _add_data_remediations(learnings, remediations, *, report_path=None, truncated_sources=None):
    for item in _capped_sorted_rows(
        remediations,
        8,
        "data_layer_audit.remediation_manifest",
        truncated_sources,
    ):
        priority = str(item.get("priority") or "P1")
        if priority not in {"P0", "P1", "P2", "P3"}:
            priority = "P1"
        command = item.get("command") or "Run data-layer remediation."
        expected = item.get("expected_artifact") or "data-layer artifact"
        report_note = f" Report: {report_path}." if report_path else ""
        learnings.append(_learning(
            priority,
            "data_layer_gate",
            "data_layer_audit",
            (
                f"{item.get('gate') or 'data-layer gate'} is {item.get('status') or priority}: "
                f"{item.get('evidence') or '-'}"
            ),
            f"{command}; expected output: {expected}.{report_note}",
            evidence=item,
            blocker=priority == "P0",
        ))


def _add_variant_alerts(learnings, variant, truncated_sources=None):
    for alert in _capped_sorted_rows(
        variant.get("alerts") or [],
        8,
        "model_variant_evidence_growth.alerts",
        truncated_sources,
        priority_func=lambda row: "P1" if row.get("severity") == "alert" else "P2",
    ):
        severity = alert.get("severity")
        priority = "P1" if severity == "alert" else "P2"
        learnings.append(_learning(
            priority,
            "experiment_evidence",
            "model_variant_evidence_growth",
            alert.get("category") or "variant evidence alert",
            alert.get("action") or alert.get("detail") or "Variant evidence changed.",
            evidence=alert,
            retrain_input=severity == "alert",
        ))


def _add_independent_evidence_sla_learning(learnings, variant):
    sla = variant.get("evidence_sla") or {}
    if sla.get("broad_promotion_claim_allowed") is not False:
        return
    no_growth = variant.get("no_growth_reasons") or []
    first_action = next(
        (
            row.get("action")
            for row in no_growth
            if row.get("status") in {"BLOCK", "WARN"} and row.get("action")
        ),
        "Collect new independent settled market-day evidence before making a broad promotion claim.",
    )
    learnings.append(_learning(
        "P1",
        "independent_evidence_growth",
        "model_variant_evidence_growth",
        "Broad promotion claim is blocked by independent-evidence SLA: "
        + ("; ".join(sla.get("reasons") or []) or "inspect evidence-growth report"),
        first_action,
        evidence={
            "evidence_sla": sla,
            "no_growth_reasons": no_growth[:8],
            "trend": variant.get("trend") or [],
        },
        retrain_input=True,
    ))


def _add_variant_learning_gate_blocker(learnings, gate):
    if (gate or {}).get("status") != "BLOCK":
        return
    first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
    detail = first.get("detail") or "active variant learning evidence is blocked"
    action = (
        first.get("remediation_command")
        or first.get("suggested_command")
        or "Run daily refresh after repairing active variant evidence."
    )
    learnings.append(_learning(
        "P0",
        "variant_learning_operational_gate",
        "daily_refresh_status",
        f"Variant learning operational gate blocked: {detail}",
        action,
        evidence=gate,
        blocker=True,
    ))


def _add_core_trend_claim_learning(learnings, claim):
    if not claim:
        return
    status = claim.get("status")
    if status == "PROVEN":
        learnings.append(_learning(
            "P1",
            "core_model_trend_claim",
            "progress_audit",
            "Core model day-over-day improvement claim is PROVEN by generated thresholds.",
            "Allow the strict trend claim in operator summaries while continuing normal promotion gates.",
            evidence=claim,
            retrain_input=True,
        ))
        return
    if status in {"DIRECTIONAL", "UNPROVEN", "MISSING"}:
        failures = claim.get("threshold_failures") or []
        action = next(iter(claim.get("next_evidence_needed") or []), None)
        learnings.append(_learning(
            "P1" if status == "DIRECTIONAL" else "P2",
            "core_model_trend_claim",
            "progress_audit",
            (
                f"Core model day-over-day claim is {status}; "
                + ("; ".join(failures[:3]) if failures else "thresholds are not satisfied")
            ),
            action or "Do not describe the core model as proven day-over-day improving yet.",
            evidence=claim,
            retrain_input=status == "DIRECTIONAL",
        ))


def _ledger_run_date(row):
    return str((row or {}).get("run_date") or (row or {}).get("generated_at_utc") or "")[:10]


def _ledger_history_values(rows, key, *, run_date=None, limit=14):
    values = []
    for row in rows or []:
        date = _ledger_run_date(row)
        if run_date and date and date >= str(run_date)[:10]:
            continue
        value = maybe_float((row or {}).get(key))
        if value is not None:
            values.append(value)
    return values[-limit:]


def _add_calibration_drift_learnings(learnings, calibration, ledger_rows, *, run_date=None):
    calibration = calibration or {}
    ece = maybe_float(calibration.get("calibration_ece"))
    bias_abs = maybe_float(calibration.get("directional_bias_abs_mean_error"))
    missing = []
    if calibration.get("calibration_status") != "PRESENT":
        missing.append("calibration_ece")
    if calibration.get("directional_bias_status") != "PRESENT":
        missing.append("directional_bias")
    if missing:
        learnings.append(_learning(
            "P2",
            "calibration_monitoring",
            "proper_scoring_reliability_scorecard",
            "Daily calibration monitoring is missing: " + ", ".join(missing),
            "Regenerate proper_scoring_reliability_scorecard before treating calibration drift as green.",
            evidence=calibration,
            retrain_input=False,
            blocker=False,
        ))
        return

    ece_history = _ledger_history_values(
        ledger_rows,
        "model_calibration_ece",
        run_date=run_date,
    )
    if ece is not None and len(ece_history) >= 3:
        baseline = sum(ece_history) / len(ece_history)
        if ece - baseline >= CALIBRATION_ECE_DRIFT_THRESHOLD:
            learnings.append(_learning(
                "P1",
                "calibration_drift",
                "daily_progress_ledger",
                f"Served-model ECE worsened to {fmt_num(ece, 4)} from recent average {fmt_num(baseline, 4)}.",
                "Prioritize calibration repair or retrain diagnostics before claiming model-quality improvement.",
                evidence={
                    **calibration,
                    "recent_average_ece": baseline,
                    "drift_threshold": CALIBRATION_ECE_DRIFT_THRESHOLD,
                    "history_count": len(ece_history),
                },
                retrain_input=True,
            ))

    bias_history = _ledger_history_values(
        ledger_rows,
        "model_directional_bias_abs_mean_error",
        run_date=run_date,
    )
    if bias_abs is not None and len(bias_history) >= 3:
        baseline = sum(bias_history) / len(bias_history)
        if bias_abs - baseline >= CALIBRATION_BIAS_DRIFT_THRESHOLD:
            signed_bias = maybe_float(calibration.get("directional_bias_mean_error")) or 0.0
            direction = "warm" if signed_bias > 0 else "cold"
            learnings.append(_learning(
                "P1",
                "directional_bias_drift",
                "daily_progress_ledger",
                (
                    f"Directional {direction} bias magnitude worsened to {fmt_num(bias_abs, 4)} "
                    f"from recent average {fmt_num(baseline, 4)}."
                ),
                "Inspect warm/cold centering slices and feed the bias into the next retrain prioritization pass.",
                evidence={
                    **calibration,
                    "recent_average_abs_bias": baseline,
                    "drift_threshold": CALIBRATION_BIAS_DRIFT_THRESHOLD,
                    "history_count": len(bias_history),
                },
                retrain_input=True,
            ))


def _build_learnings(payloads, scorecard, artifacts=None, truncated_sources=None, input_gate=None, run_date=None):
    learnings = []
    artifacts = artifacts or {}
    labels_total = scorecard["labels"]["total"]
    corpus = scorecard["corpus"]
    candidate = scorecard["candidate"]
    ingest = scorecard["ingest_quality_gate"]
    data_layer = scorecard["data_layer_audit"]
    settled_root_cause = scorecard.get("settled_day_root_cause") or {}
    settled_day = scorecard["settled_day_freshness"]
    settled_barrier = scorecard.get("settled_day_analysis_barrier") or {}
    label_countability = scorecard.get("label_countability") or {}
    source_family_inventory = scorecard.get("source_family_inventory") or {}
    fleet = scorecard["fleet"]
    shadow = scorecard["shadow_ab_monitor"]
    variant = payloads.get("model_variant_evidence_growth") or {}
    variant_learning_gate = scorecard.get("variant_learning_gate") or {}
    data_payload = payloads.get("data_layer_audit") or {}
    promotion_payload = payloads.get("promotion_refresh") or {}
    hourly_payload = payloads.get("hourly_model_performance") or {}
    hourly = scorecard.get("hourly_model_performance") or {}
    ten_minute = scorecard.get("ten_minute_model_performance") or {}
    price_free = scorecard.get("price_free_model_learning") or {}
    snapshot_eval = payloads.get("snapshot_evaluation") or {}
    promotion = scorecard["promotion"]
    casebook = scorecard["casebook"]
    disagreement_rehydration = scorecard.get("model_market_disagreement_rehydration") or {}
    taker_finalization = scorecard.get("taker_finalization_watchdog") or {}
    taker_tail = scorecard.get("taker_tail_casebook") or {}
    rollup_freshness = scorecard.get("rollup_freshness") or {}
    event_metadata = scorecard.get("event_metadata_validation") or {}
    calibration_monitoring = scorecard.get("calibration_monitoring") or {}
    ledger_rows = payloads.get("daily_progress_ledger") or []

    _add_input_gate_learnings(learnings, input_gate)

    for source, artifact in (
        ("hourly_model_performance", hourly),
        ("ten_minute_model_performance", ten_minute),
        ("price_free_model_learning", price_free),
        ("settled_day_root_cause", settled_root_cause),
    ):
        liveness = artifact.get("scoring_liveness") or {}
        if liveness.get("status") != "BLOCK":
            continue
        first = liveness.get("first_blocker") or {}
        learnings.append(_learning(
            "P0",
            "model_scoring_liveness",
            source,
            first.get("detail")
            or (
                f"{source} last scored {liveness.get('last_scored_target_date')}; "
                f"latest settled label is {liveness.get('latest_settled_label_date')}"
            ),
            first.get("remediation_command")
            or liveness.get("remediation_command")
            or f"Regenerate {source} before consuming model-skill gates.",
            evidence=liveness,
            blocker=True,
        ))

    if event_metadata.get("status") and event_metadata.get("status") != "PASS":
        first = event_metadata.get("first_blocker") or {}
        first_issue = first.get("first_issue") or {}
        learnings.append(_learning(
            "P0",
            "event_metadata_validation",
            "event_metadata_validation",
            (
                f"Event metadata validation is {event_metadata.get('status')} for "
                f"{event_metadata.get('target_date')}: "
                f"{first_issue.get('code') or first.get('reason') or 'inspect event metadata validation'}."
            ),
            first.get("remediation_command")
            or event_metadata.get("refresh_command")
            or event_metadata.get("validation_command")
            or "python -m weather.operations.event_metadata_validation --target-date <YYYY-MM-DD>",
            evidence=event_metadata,
            blocker=True,
        ))

    if rollup_freshness.get("status") == "BLOCK":
        first = next(iter(rollup_freshness.get("blockers") or []), {})
        learnings.append(_learning(
            "P0",
            "daily_rollup_freshness",
            "daily_refresh_status",
            (
                "Daily compact rollup is stale: "
                f"{first.get('rollup') or 'compact rollup'} is "
                f"{first.get('status') or 'BLOCK'} after "
                f"{first.get('latest_required_artifact') or 'a granular artifact'}."
            ),
            rollup_freshness.get("repair_command")
            or "Run daily refresh from the daily_learning step after clearing only verified stale locks.",
            evidence=rollup_freshness,
            blocker=True,
        ))

    if settled_day.get("status") == "FAIL":
        summary = settled_day.get("summary") or {}
        commands = [
            command
            for command in [
                settled_day.get("repair_command"),
                settled_day.get("replay_status_repair_command"),
            ]
            if command
        ]
        learnings.append(_learning(
            "P0",
            "data_freshness",
            "settled_day_freshness",
            (
                f"Settled-day freshness failed for {settled_day.get('target_date')}: "
                f"{summary.get('incomplete_market_count')} incomplete market(s), "
                f"{summary.get('needs_finalization_count')} needing label finalization, "
                f"{summary.get('needs_replay_status_repair_count')} needing replay-status repair."
            ),
            "; ".join(commands) or "Run settled-day freshness repair, then rerun daily learning.",
            evidence=settled_day,
            blocker=True,
        ))
    elif settled_day.get("status") == "WARN":
        summary = settled_day.get("summary") or {}
        learnings.append(_learning(
            "P1",
            "data_freshness",
            "settled_day_freshness",
            (
                f"Settled-day freshness warning for {settled_day.get('target_date')}: "
                f"{summary.get('source_lag_warning_count')} source-lag warning(s)."
            ),
            "Review source-lag provenance before treating the newest labels as official daily-summary settlements.",
            evidence=settled_day,
        ))

    if settled_barrier.get("status") == "BLOCK":
        first = next(iter(settled_barrier.get("blockers") or []), {})
        learnings.append(_learning(
            "P0",
            "settled_day_analysis_barrier",
            "settled_day_analysis_barrier",
            (
                f"Settled-day analysis barrier blocked {settled_barrier.get('target_date')}: "
                f"{first.get('component') or 'dependency'} {first.get('detail') or 'blocked'}."
            ),
            settled_barrier.get("resume_command")
            or "Rerun daily refresh from settled_day_analysis_barrier after finalization completes.",
            evidence=settled_barrier,
            blocker=True,
        ))

    if disagreement_rehydration.get("status") == "BLOCK":
        first = next(iter(disagreement_rehydration.get("blockers") or []), {})
        learnings.append(_learning(
            "P0",
            "disagreement_audit_rehydration",
            "model_market_disagreement_analysis",
            (
                f"Model-market disagreement audit rehydration blocked "
                f"{disagreement_rehydration.get('target_date') or run_date}: "
                f"{first.get('detail') or 'complete-label rows remain unresolved'}."
            ),
            "Rerun daily refresh from model_market_disagreement_rehydration after repairing labels or audit band metadata.",
            evidence=disagreement_rehydration,
            blocker=True,
        ))
    elif disagreement_rehydration.get("status") == "WARN":
        learnings.append(_learning(
            "P1",
            "disagreement_audit_rehydration",
            "model_market_disagreement_analysis",
            (
                f"Model-market disagreement audit rehydration excluded "
                f"{disagreement_rehydration.get('excluded_partial_label_count')} partial-label and "
                f"{disagreement_rehydration.get('excluded_missing_label_count')} missing-label row(s)."
            ),
            "Review excluded disagreement rows before treating them as model-repair evidence.",
            evidence=disagreement_rehydration,
            blocker=False,
        ))

    if label_countability.get("diagnostic_only"):
        learnings.append(_learning(
            "P1",
            "label_countability",
            "settled_day_analysis_barrier",
            (
                f"Target-date labels are diagnostic-only: {label_countability.get('reason')}; "
                "broad promotion evidence is not countable."
            ),
            "Use the day for diagnostic review only; wait for complete labels before broad promotion claims.",
            evidence=label_countability,
            retrain_input=False,
            blocker=False,
        ))

    root_cause_summary = settled_root_cause.get("summary") or {}
    if safe_int(root_cause_summary.get("explanation_snapshot_count")):
        coverage = root_cause_summary.get("explanation_coverage_rate")
        learnings.append(_learning(
            "P1",
            "root_cause_explanation_tape",
            "settled_day_root_cause",
            (
                f"Settled-day root-cause report has explanation tape for "
                f"{root_cause_summary.get('explanation_snapshot_count')} snapshot(s); "
                f"coverage {fmt_num(coverage, 3)}."
            ),
            "Use persisted snapshot_explanations rows for weak-slot diagnosis before rerunning the model.",
            evidence={
                "target_date": settled_root_cause.get("target_date"),
                "summary": root_cause_summary,
            },
            retrain_input=True,
        ))

    if labels_total or corpus.get("market_day_count"):
        evidence_countable = not bool(label_countability.get("diagnostic_only"))
        learnings.append(_learning(
            "P1",
            "new_training_evidence",
            "market_day_labels_finalize",
            (
                f"{labels_total} labels finalized; corpus has "
                f"{corpus.get('market_day_count')} market-days and {corpus.get('snapshot_count')} snapshots"
            ),
            "Use the refreshed corpus as the next retrain and replay input.",
            evidence={
                "labels": scorecard["labels"],
                "corpus": corpus,
                "label_countability": label_countability,
            },
            retrain_input=evidence_countable,
        ))

    if ingest.get("status") == "FAIL":
        learnings.append(_learning(
            "P0",
            "data_quality",
            "ingest_quality_gate",
            "Ingest quality failed.",
            "Block promotion claims until schema, duplicate, impossible-value, or missing-audit failures are fixed.",
            evidence=ingest,
            blocker=True,
        ))
    elif ingest.get("status") == "WARN":
        learnings.append(_learning(
            "P1",
            "data_quality",
            "ingest_quality_gate",
            "Ingest quality warnings were present.",
            "Prioritize gap repair before relying on thin or sparse slices for broad claims.",
            evidence=ingest,
        ))

    data_layer_report = None
    data_artifact = artifacts.get("data_layer_audit") or {}
    if data_artifact.get("path"):
        data_layer_report = str(Path(data_artifact["path"]).with_name("data_layer_audit_report.md"))
    _add_data_remediations(
        learnings,
        data_payload.get("remediation_manifest") or [],
        report_path=data_layer_report,
        truncated_sources=truncated_sources,
    )
    sidecar_eligibility = data_layer.get("sidecar_eligibility") or {}
    sidecar_labels = sidecar_eligibility.get("primary_label_counts") or {}
    backfill_count = int(sidecar_eligibility.get("backfill_candidate_folder_count") or 0)
    active_regressions = int(sidecar_eligibility.get("active_day_sidecar_regression_count") or 0)
    non_reconstructable = sidecar_eligibility.get("non_reconstructable_gap_counts") or {}
    if sidecar_labels and (
        backfill_count
        or active_regressions
        or non_reconstructable
        or len([count for count in sidecar_labels.values() if count]) > 1
    ):
        learnings.append(_learning(
            "P1" if active_regressions else "P2",
            "sidecar_coverage_mix",
            "data_layer_audit",
            (
                "Snapshot sidecar eligibility mix: "
                + ", ".join(f"{key}={value}" for key, value in sorted(sidecar_labels.items()))
            ),
            (
                "Run deterministic sidecar backfills where listed, and keep score-only or "
                "market-event gaps out of broad improvement claims."
            ),
            evidence=sidecar_eligibility,
            blocker=False,
        ))

    if data_layer.get("gate_status") == "FAIL":
        first_p0 = next(
            (
                row for row in data_payload.get("remediation_manifest") or []
                if row.get("priority") == "P0"
            ),
            None,
        )
        if first_p0:
            signal = f"Data-layer audit failed: {first_p0.get('gate')} is {first_p0.get('status')}."
            action = (
                f"{first_p0.get('command')}; expected output: "
                f"{first_p0.get('expected_artifact')}. Report: {data_layer_report or '-'}."
            )
        else:
            signal = "Data-layer audit failed."
            action = "Fix failed data-layer gates before accepting new training or promotion evidence."
        learnings.append(_learning(
            "P0",
            "data_quality",
            "data_layer_audit",
            signal,
            action,
            evidence=data_layer,
            blocker=True,
        ))
    elif data_layer.get("gate_status") == "WARN":
        learnings.append(_learning(
            "P1",
            "data_quality",
            "data_layer_audit",
            "Data-layer audit has warnings.",
            "Treat affected source or coverage slices as lower-confidence until repaired.",
            evidence=data_layer,
        ))

    source_preflight = source_family_inventory.get("promotion_preflight") or {}
    if source_preflight.get("status") == "BLOCK":
        blocked_families = source_preflight.get("blocked_families") or []
        command = source_preflight.get("inventory_command") or "python -m weather.reporting.source_family_inventory"
        ablation_command = source_preflight.get("ablation_command")
        action = command
        if ablation_command:
            action = f"{ablation_command}; then rerun `{command}` before promotion."
        learnings.append(_learning(
            "P0",
            "source_family_preflight",
            "source_family_inventory",
            (
                f"Source-family promotion preflight blocked {len(blocked_families)} "
                f"model-influencing family row(s): {', '.join(blocked_families[:8]) or '-'}."
            ),
            action,
            evidence=source_preflight,
            blocker=True,
        ))

    _add_data_recommendations(learnings, data_payload.get("recommendations"), truncated_sources)
    _add_gate_learnings(learnings, snapshot_eval.get("gates") or [])
    _add_backlog_learnings(
        learnings,
        (snapshot_eval.get("improvement_backlog") or {}).get("top_slices") or [],
        truncated_sources,
    )
    _add_gap_owner_learnings(learnings, promotion_payload.get("gap_owner_table") or [], truncated_sources)

    hourly_gate = hourly.get("hourly_performance_gate") or {}
    if hourly_gate.get("status") == "BLOCK":
        first = hourly_gate.get("first_blocker") or {}
        learnings.append(_learning(
            "P0",
            "hourly_performance_gate",
            "hourly_model_performance",
            f"Hourly performance gate blocked: {first.get('detail') or 'inspect hourly gate blockers'}.",
            first.get("remediation_command") or "Run weather.reporting.hourly.hourly_model_performance and remediate early-hour blockers.",
            evidence=hourly_gate,
            blocker=True,
        ))
    elif hourly_gate.get("status") == "PASS":
        daily = hourly.get("daily_summary") or {}
        learnings.append(_learning(
            "P1",
            "hourly_performance_gate",
            "hourly_model_performance",
            (
                "Hourly performance gate passed; worst hours: "
                + (", ".join(daily.get("worst_hours") or []) or "-")
            ),
            "Keep hour-regime evidence attached to promotion decisions.",
            evidence=hourly_gate,
            retrain_input=True,
        ))

    ten_minute_gate = ten_minute.get("ten_minute_performance_gate") or {}
    if ten_minute_gate.get("status") == "BLOCK":
        first = ten_minute_gate.get("first_blocker") or {}
        weak_slots = (ten_minute.get("weak_slots") or {}).get("slot_labels") or []
        learnings.append(_learning(
            "P0",
            "ten_minute_performance_gate",
            "ten_minute_model_performance",
            (
                f"10-minute weak-slot gate blocked: {first.get('detail') or 'inspect weak-slot blockers'}. "
                f"Weak slots: {', '.join(weak_slots) or '-'}."
            ),
            first.get("remediation_command") or "Run weather.reporting.hourly.ten_minute_model_performance and remediate weak-slot blockers.",
            evidence=ten_minute_gate,
            blocker=True,
        ))
    elif ten_minute_gate.get("status") == "PASS":
        daily = ten_minute.get("daily_summary") or {}
        learnings.append(_learning(
            "P1",
            "ten_minute_performance_gate",
            "ten_minute_model_performance",
            (
                "10-minute weak-slot gate passed; weak slots under watch: "
                + (", ".join(daily.get("weak_slots") or []) or "-")
            ),
            "Keep 10-minute weak-slot evidence attached to candidate promotion decisions.",
            evidence=ten_minute_gate,
            retrain_input=True,
        ))

    registry = hourly_payload.get("remediation_registry") or {}
    for row in _capped_sorted_rows(
        registry.get("rows") or [],
        12,
        "hourly_model_performance.remediation_registry.rows",
        truncated_sources,
        priority_func=lambda item: "P1" if item.get("uses_market_prices") else item.get("priority") or "P2",
    ):
        if row.get("hour_regime") != "early_morning":
            continue
        priority = "P1" if row.get("uses_market_prices") else "P2"
        learnings.append(_learning(
            priority,
            "hourly_remediation_registry",
            "hourly_model_performance",
            (
                f"{row.get('probe_name')} early-hour probe: "
                f"{row.get('interpretation')}."
            ),
            "Track remediation probe deltas across daily runs before using them in promotion readiness.",
            evidence=row,
            retrain_input=not bool(row.get("uses_market_prices")),
        ))

    for row in (registry.get("early_hour_market_deltas") or [])[:12]:
        if row.get("status") != "BLOCK":
            continue
        gates = ", ".join(row.get("blocking_gates") or []) or "early-hour regression"
        learnings.append(_learning(
            "P1",
            "hourly_early_market_delta",
            "hourly_model_performance",
            (
                f"{row.get('market_id')} early-hour model trails market: "
                f"Brier delta {fmt_signed(row.get('brier_delta'))}, "
                f"log-loss delta {fmt_signed(row.get('logloss_delta'))} ({gates})."
            ),
            "Track per-market early-hour deltas daily; prioritize weather-only candidate remediation where blockers persist.",
            evidence=row,
            retrain_input=True,
        ))

    price_free_corpus = price_free.get("corpus") or {}
    price_free_daily = price_free.get("daily_summary") or {}
    price_free_overall = (price_free.get("overall") or {}).get("hourly_checkpoint") or {}
    price_free_rows = safe_int(price_free_corpus.get("hourly_checkpoint_rows"))
    if price_free.get("status") == "OK" and price_free_rows:
        learnings.append(_learning(
            "P1",
            "price_free_model_learning",
            "price_free_model_learning",
            (
                f"Price-free settled diagnostics scored {price_free_corpus.get('scored_market_days')} "
                f"market-day(s) and {price_free_rows} hourly checkpoint row(s) without Polymarket prices; "
                f"top-hit rate {fmt_num(price_free_overall.get('partition_model_top_is_winner_rate'), 3)}."
            ),
            "Use this as diagnostic retrain evidence only; keep market-benchmark promotion claims on hourly_model_performance.",
            evidence={
                "daily_summary": price_free_daily,
                "corpus": price_free_corpus,
                "evidence_classification": price_free.get("evidence_classification") or {},
            },
            retrain_input=True,
        ))

    carryover = price_free.get("current_max_carryover") or {}
    carryover_summary = carryover.get("summary") or {}
    guarded_count = safe_int(carryover_summary.get("risky_or_guarded_count"))
    if guarded_count:
        learnings.append(_learning(
            "P1",
            "current_max_carryover",
            "price_free_model_learning",
            (
                f"Current-max carryover guard marked {guarded_count} snapshot row(s) as "
                "null-before-reset or support-only source-state evidence."
            ),
            "Keep pre-7 AM wu_max_since_7am null and treat large early current-max minus WU-history gaps as support-only until same-day history validates them.",
            evidence={
                "summary": carryover_summary,
                "by_market_hour": carryover.get("by_market_hour") or [],
                "examples": carryover.get("examples") or [],
            },
            retrain_input=True,
        ))

    if candidate.get("rows"):
        blocked_validation = candidate.get("blocked_validation") or {}
        if blocked_validation and not blocked_validation.get("passed"):
            learnings.append(_learning(
                "P0",
                "blocked_validation",
                "promotion_refresh",
                (
                    "Candidate failed daily-first blocked validation: "
                    + ("; ".join(blocked_validation.get("reasons") or []) or "inspect blocked validation gate")
                ),
                "Keep candidate out of promotion until daily-first blocked validation passes without leakage.",
                evidence=blocked_validation,
                blocker=True,
            ))
        delta_current = candidate.get("delta_vs_current")
        if delta_current is not None and delta_current <= 0:
            learnings.append(_learning(
                "P1",
                "candidate_performance",
                "promotion_refresh",
                f"Candidate matched or beat current model by {fmt_signed(delta_current)} Brier.",
                "Keep candidate eligible for promotion/shadow gates and rerun after the next settled labels arrive.",
                evidence=candidate,
                retrain_input=True,
            ))
        elif delta_current is not None:
            learnings.append(_learning(
                "P1",
                "candidate_regression",
                "promotion_refresh",
                f"Candidate trails current model by {fmt_signed(delta_current)} Brier.",
                "Block promotion and inspect top replay slices before retraining or changing serving behavior.",
                evidence=candidate,
            ))
        if candidate.get("delta_vs_market") is not None and candidate.get("delta_vs_market") > 0:
            learnings.append(_learning(
                "P2",
                "market_skill_gap",
                "promotion_refresh",
                f"Candidate trails market by {fmt_signed(candidate.get('delta_vs_market'))} Brier.",
                "Use market-gap slices as targets for feature and calibration work.",
                evidence=candidate,
                retrain_input=True,
            ))

    if promotion.get("blocked_markets"):
        learnings.append(_learning(
            "P1",
            "promotion_decision",
            "promotion_refresh",
            f"Blocked markets: {', '.join(promotion.get('blocked_markets'))}",
            "Keep blocked markets in shadow until their replay and data-quality gates pass.",
            evidence=promotion,
        ))

    early_hour_promotion_blocker = promotion.get("early_hour_promotion_blocker") or {}
    if early_hour_promotion_blocker.get("status") == "BLOCK":
        blockers = early_hour_promotion_blocker.get("blockers") or []
        categories = [row.get("category") for row in blockers if row.get("category")]
        current_gates = early_hour_promotion_blocker.get("current_gates") or {}
        learnings.append(_learning(
            "P0",
            "early_hour_promotion_blocker",
            "promotion_refresh",
            (
                "Early-hour promotion remains fail-closed: "
                f"current hourly={((current_gates.get('hourly') or {}).get('status') or '-')}, "
                f"current 10-minute={((current_gates.get('ten_minute') or {}).get('status') or '-')}; "
                f"blockers={', '.join(categories[:6]) or 'inspect early-hour blocker manifest'}."
            ),
            (
                "Keep the candidate out of promotion until candidate-specific hourly and 10-minute "
                "gates pass with matching variant/corpus lineage, broad replay is within market "
                "tolerance, and production-readiness blockers are clear."
            ),
            evidence=early_hour_promotion_blocker,
            blocker=True,
        ))

    if shadow.get("status") == "ALERT":
        learnings.append(_learning(
            "P1",
            "shadow_ab",
            "shadow_ab_monitor",
            "Shadow A/B monitor alerted.",
            "Do not broaden rollout until the alerting candidate/current deltas are explained.",
            evidence=shadow,
        ))

    _add_variant_alerts(learnings, variant, truncated_sources)
    _add_independent_evidence_sla_learning(learnings, variant)
    _add_variant_learning_gate_blocker(learnings, variant_learning_gate)
    _add_core_trend_claim_learning(learnings, scorecard.get("core_model_trend_claim") or {})
    _add_calibration_drift_learnings(
        learnings,
        calibration_monitoring,
        ledger_rows,
        run_date=run_date,
    )

    live_slo = fleet.get("live_forward_slo") or {}
    mm_paper_evidence = fleet.get("mm_paper_evidence") or {}
    model_review_evidence = ((mm_paper_evidence.get("by_class") or {}).get("model_review_evidence") or {})
    if model_review_evidence.get("countable_market_count"):
        paper_evidence = ((mm_paper_evidence.get("by_class") or {}).get("paper_trading_evidence") or {})
        learnings.append(_learning(
            "P1",
            "live_forward_partial_credit",
            "fleet_observability",
            (
                f"{model_review_evidence.get('countable_market_count')} model-review market(s) and "
                f"{paper_evidence.get('countable_market_count', 0)} paper-trading market(s) count per-market; "
                f"all-selected count is {paper_evidence.get('all_selected_markets_count')}"
            ),
            (
                "Use countable per-market evidence for model review only; keep broad live-forward and "
                "live-trade claims gated until all selected markets and live-pilot gates pass."
            ),
            evidence=mm_paper_evidence,
            retrain_input=True,
        ))
    tape_backup = fleet.get("tape_backup") or {}
    tape_status = tape_backup.get("status")
    if tape_status and tape_status != "OK":
        backup_root = tape_backup.get("backup_root") or "data/tape_backups"
        detail = (
            tape_backup.get("restore_drill_sla_detail")
            or tape_backup.get("manifest_detail")
            or f"status {tape_status}"
        )
        learnings.append(_learning(
            "P0",
            "operational_backup",
            "fleet_observability",
            f"Tape backup status {tape_status}: {detail}",
            (
                "Run `python -m weather.operations.tape_backup run "
                f"--backup-root {backup_root} --verify-checksums`; expected outputs are "
                "`data/backtest/tape_backup_status.json` and "
                "`data/backtest/tape_restore_drill.json`."
            ),
            evidence={"tape_backup": tape_backup},
            blocker=True,
        ))

    if live_slo.get("counts_toward_live_forward_gate") is False:
        first_recovery = (
            live_slo.get("first_blocker")
            or next(iter(live_slo.get("recovery_checklist") or []), {})
        )
        repair_command = first_recovery.get("repair_command") or first_recovery.get("suggested_command")
        verification_command = first_recovery.get("verification_command") or live_slo.get("rerun_command")
        action = "Do not count live-forward evidence until collection SLOs are repaired."
        if repair_command:
            action = repair_command
            if verification_command:
                action += f"; then rerun `{verification_command}` and require PASS before broad countability."
        learnings.append(_learning(
            "P0",
            "collection_health",
            "fleet_observability",
            live_slo.get("reason") or f"Fleet status {fleet.get('status')}",
            action,
            evidence={
                "fleet_status": fleet.get("status"),
                "live_forward_slo": live_slo,
                "first_recovery": first_recovery,
            },
            blocker=True,
        ))
    elif fleet.get("status") == "CRITICAL" and not (tape_status and tape_status != "OK"):
        learnings.append(_learning(
            "P0",
            "collection_health",
            "fleet_observability",
            "Fleet observability has critical alerts.",
            "Do not count live-forward evidence until critical fleet-observability alerts are repaired.",
            evidence=fleet,
            blocker=True,
        ))

    current_soak = fleet.get("current_code_soak") or {}
    if current_soak.get("counts_toward_active_day") is False:
        soak_summary = current_soak.get("summary") or {}
        learnings.append(_learning(
            "P0",
            "current_code_soak",
            "fleet_observability",
            (
                f"Current-code soak is {current_soak.get('status')}: "
                f"{soak_summary.get('first_blocking_loop') or 'cadence_slo'} "
                f"{soak_summary.get('first_blocking_reason') or current_soak.get('cadence_slo_reason') or '-'}"
            ),
            (
                "Restart affected loops on current source, keep restart counts within budget, "
                "and rerun fleet observability after a full active-day cadence proof."
            ),
            evidence=current_soak,
            blocker=True,
        ))

    finalization_summary = taker_finalization.get("summary") or {}
    if finalization_summary.get("sla_breach_count") or finalization_summary.get("pending_finalization_count"):
        breach_count = safe_int(finalization_summary.get("sla_breach_count"))
        pending_count = safe_int(finalization_summary.get("pending_finalization_count"))
        learnings.append(_learning(
            "P0" if breach_count else "P1",
            "taker_settlement_finalization",
            "taker_finalization_watchdog",
            (
                f"Taker settlement finalization has {breach_count} SLA breach(es) "
                f"and {pending_count} pending run(s)."
            ),
            "Run python -m weather.market.taker_bot finalize --watchdog and require fresh settled_pnl plus strategy_bakeoff artifacts before taker-quality claims.",
            evidence=taker_finalization,
            blocker=bool(breach_count),
        ))

    tail_summary = taker_tail.get("summary") or {}
    if tail_summary.get("status") == "BLOCK_BAD_TAIL_SLICES":
        candidates = taker_tail.get("no_go_candidates") or []
        first = candidates[0] if candidates else {}
        learnings.append(_learning(
            "P0",
            "taker_tail_no_go",
            "taker_tail_casebook",
            (
                f"Taker tail casebook found {tail_summary.get('no_go_candidate_count')} no-go tail slice(s); "
                f"first={first.get('slice_key') or '-'}."
            ),
            "Keep matching low-price or market-centered warm-tail slices blocked until repeated settlement-positive out-of-sample evidence clears the no-go list.",
            evidence={
                "summary": tail_summary,
                "first_no_go_candidate": first,
                "no_go_candidates": candidates[:10],
            },
            blocker=True,
        ))

    trading = scorecard.get("trading_evidence") or {}
    mm_trading = trading.get("market_making") or {}
    if mm_trading.get("exists"):
        counts = bool(mm_trading.get("counts_toward_live_forward_gate"))
        priority = "P1" if counts else "P2"
        quote_gate = mm_trading.get("quote_starvation_gate") or {}
        quote_summary = mm_trading.get("quote_starvation") or {}
        learnings.append(_learning(
            priority,
            "market_making_evidence",
            "trading_evidence",
            (
                f"MM run {mm_trading.get('run_id')} mode={mm_trading.get('evidence_mode')} "
                f"quote_rows={mm_trading.get('quote_rows')} "
                f"paper_legs={mm_trading.get('paper_posted_lifecycle_legs')} "
                f"live_permission_rows={mm_trading.get('live_trade_permission_rows')} "
                f"counts={counts}; classification={mm_trading.get('maker_day_classification') or '-'}."
            ),
            (
                "Count MM as broad live-forward evidence only when evidence_mode is "
                "`active_day_live_forward` and all selected markets count."
            ),
            evidence=mm_trading,
            retrain_input=counts,
            blocker=False,
        ))
        if quote_gate.get("status") == "BLOCK":
            learnings.append(_learning(
                "P0",
                "market_making_quote_starvation",
                "trading_evidence",
                (
                    f"MM quote-starvation gate blocked: "
                    f"classification={quote_gate.get('classification')}; "
                    f"selection={mm_trading.get('evidence_selection_status')}; "
                    f"quote_rows={quote_summary.get('quote_permission_rows')} "
                    f"intents={quote_summary.get('total_intents')}."
                ),
                (
                    "Do not count maker evidence until the latest target-date proof run is selected "
                    "and quote starvation is resolved or explained by policy-only no-edge gates."
                ),
                evidence={"quote_starvation": quote_summary, "selection": mm_trading.get("evidence_selection") or {}},
                blocker=True,
            ))
        elif quote_gate.get("status") == "WARN":
            learnings.append(_learning(
                "P1",
                "market_making_quote_starvation",
                "trading_evidence",
                (
                    f"MM quotes were policy-starved: classification={quote_gate.get('classification')}; "
                    f"top gates={(quote_summary.get('reason_taxonomy') or {}).get('top_blocking_gates') or []}."
                ),
                "Treat the maker day as no-quote policy evidence, not quote permission proof.",
                evidence={"quote_starvation": quote_summary},
                blocker=False,
            ))
    taker = trading.get("taker") or {}
    if taker.get("exists"):
        quality = taker.get("quality_gate") or {}
        zero_fill_quality = taker.get("zero_fill_quality_classification")
        taker_starvation_blocker = bool(taker.get("blocks_taker_evidence_countability"))
        zero_fill_blocker = (
            zero_fill_quality in {"infra_blocked", "unscored_stale_labels"}
            or taker_starvation_blocker
        )
        learnings.append(_learning(
            "P0" if zero_fill_blocker else ("P1" if quality.get("sample_ready") else "P2"),
            "taker_strategy_quality",
            "trading_evidence",
            (
                f"Taker run {taker.get('run_id')} fills={taker.get('filled_orders')} "
                f"net_pnl={fmt_signed(taker.get('net_pnl_usdc'))} "
                f"source={taker.get('pnl_source') or '-'} "
                f"evidence={taker.get('pnl_evidence_status') or '-'} "
                f"settled={taker.get('settled_order_count', '-')}/"
                f"{taker.get('unsettled_order_count', '-')} "
                f"tail={taker.get('low_price_tail_fill_count', 0)} "
                f"tail_status={taker.get('tail_fill_quality_status') or '-'} "
                f"reconciliation={taker.get('settlement_reconciliation_status') or '-'} "
                f"root_cause={taker.get('root_cause_class')}; "
                f"zero_fill_quality={zero_fill_quality or '-'}; "
                f"taker_day_classification={taker.get('taker_day_classification') or '-'}; "
                f"evidence_countability={taker.get('taker_evidence_countability_status') or '-'}; "
                f"quality={quality.get('status')}."
            ),
            (
                "Repair stale labels/artifacts, latest-tick starvation, or infrastructure blockers before treating zero-fill days "
                "as no-edge evidence; otherwise require settlement-scored fills, tail-fill quality, "
                "and rolling P&L thresholds before taker strategy-quality claims."
                if zero_fill_blocker else
                "Treat MTM-only paper P&L as provisional; require settlement-scored fills, "
                "tail-fill quality, and rolling P&L thresholds before taker strategy-quality claims."
            ),
            evidence=taker,
            retrain_input=False,
            blocker=quality.get("status") == "BLOCK" or zero_fill_blocker,
        ))

    if casebook.get("model_loss_count"):
        taxonomy_counts = casebook.get("taxonomy_counts") or {}
        top_taxonomies = sorted(taxonomy_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        learnings.append(_learning(
            "P1",
            "casebook_feedback",
            "disagreement_casebook",
            f"{casebook.get('model_loss_count')} settled model-losing disagreement cases.",
            "Turn the top casebook taxonomies into explicit replay slices, features, or guardrails.",
            evidence={"casebook": casebook, "top_taxonomies": top_taxonomies},
            retrain_input=True,
        ))

    return learnings


def _sample_market_day_key(row, index):
    if not isinstance(row, dict):
        return f"sample-{index}"
    return (
        row.get("market_day")
        or row.get("market_day_key")
        or row.get("target_date")
        or row.get("run_date")
        or row.get("date")
        or f"sample-{index}"
    )


def _delta_samples(candidate, key):
    rows = candidate.get("paired_delta_samples") or []
    samples = []
    market_days = set()
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            value = maybe_float(row.get(key))
            if value is None and key == "delta_vs_current":
                value = maybe_float(row.get("delta"))
            if value is None:
                continue
            market_days.add(_sample_market_day_key(row, index))
            samples.append(value)
        else:
            value = maybe_float(row)
            if value is None:
                continue
            market_days.add(f"sample-{index}")
            samples.append(value)
    return samples, market_days


def _bootstrap_mean_ci(values, *, resamples=PROMOTION_BOOTSTRAP_RESAMPLES, level=PROMOTION_CI_LEVEL):
    values = [float(value) for value in values]
    if not values:
        return {"mean": None, "ci_low": None, "ci_high": None}
    if len(values) == 1:
        mean = values[0]
        return {"mean": mean, "ci_low": mean, "ci_high": mean}
    rng = random.Random(1729)
    n = len(values)
    means = []
    for _index in range(int(resamples)):
        sample_total = 0.0
        for _sample_index in range(n):
            sample_total += values[rng.randrange(n)]
        means.append(sample_total / n)
    means.sort()
    alpha = (1.0 - float(level)) / 2.0
    low_index = max(0, min(len(means) - 1, int(alpha * len(means))))
    high_index = max(0, min(len(means) - 1, int((1.0 - alpha) * len(means)) - 1))
    return {
        "mean": sum(values) / n,
        "ci_low": means[low_index],
        "ci_high": means[high_index],
    }


def _promotion_delta_confidence(candidate, key, *, min_market_days=PROMOTION_MIN_INDEPENDENT_MARKET_DAYS):
    values, market_days = _delta_samples(candidate, key)
    ci = _bootstrap_mean_ci(values)
    reasons = []
    if not values:
        reasons.append(f"{key}_paired_samples_missing")
    if len(market_days) < min_market_days:
        reasons.append(f"{key}_independent_market_days_below_{min_market_days}")
    if len(values) < min_market_days:
        reasons.append(f"{key}_sample_count_below_{min_market_days}")
    ci_high = ci.get("ci_high")
    if ci_high is None:
        reasons.append(f"{key}_confidence_interval_missing")
    elif ci_high > 0:
        reasons.append(f"{key}_confidence_interval_upper_above_zero")
    return {
        "metric": key,
        "status": "PASS" if not reasons else "BLOCK",
        "sample_count": len(values),
        "independent_market_day_count": len(market_days),
        "min_independent_market_days": min_market_days,
        "confidence_level": PROMOTION_CI_LEVEL,
        "bootstrap_resamples": PROMOTION_BOOTSTRAP_RESAMPLES,
        "mean_delta": ci.get("mean"),
        "ci_low": ci.get("ci_low"),
        "ci_high": ci.get("ci_high"),
        "reasons": reasons,
    }


def _promotion_confidence(candidate):
    current = _promotion_delta_confidence(candidate, "delta_vs_current")
    market = _promotion_delta_confidence(candidate, "delta_vs_market")
    return {
        "status": current.get("status"),
        "delta_vs_current": current,
        "delta_vs_market": market,
        "promotion_ready": current.get("status") == "PASS",
        "reasons": current.get("reasons") or [],
    }


def _variant_delta_value(delta, *keys):
    if not isinstance(delta, dict):
        return None
    for key in keys:
        value = maybe_float(delta.get(key))
        if value is not None:
            return value
    for value in delta.values():
        if isinstance(value, dict):
            nested = _variant_delta_value(value, *keys)
            if nested is not None:
                return nested
    return None


def _retrain_recommendation(scorecard, learnings, experiment_queue, input_gate):
    reasons = []
    thresholds = {
        "corpus_growth_market_days": RETRAIN_CORPUS_GROWTH_MARKET_DAYS,
        "calibration_ece_drift": CALIBRATION_ECE_DRIFT_THRESHOLD,
        "directional_bias_abs_drift": CALIBRATION_BIAS_DRIFT_THRESHOLD,
    }
    if (input_gate or {}).get("status") == "FAIL":
        return {
            "recommended": False,
            "status": "SCHEDULED_FALLBACK",
            "scheduled_fallback": True,
            "reasons": [
                {
                    "code": "daily_analysis_inputs_not_clean",
                    "detail": "daily analysis inputs are missing, stale, or inconsistent",
                }
            ],
            "thresholds": thresholds,
            "eligible_experiment_count": ((experiment_queue.get("summary") or {}).get("eligible_count") or 0),
            "detail": "Input drift/novelty signals are missing or blocked; keep the existing scheduled retrain behavior.",
        }

    label_countability = scorecard.get("label_countability") or {}
    settled = scorecard.get("settled_day_freshness") or {}
    if (
        label_countability.get("promotion_countable") is not False
        and settled.get("target_date")
        and safe_int((settled.get("summary") or {}).get("complete_market_count")) > 0
    ):
        reasons.append({
            "code": "new_clean_settled_day",
            "detail": f"settled target date {settled.get('target_date')} has clean countable labels",
        })

    delta = (scorecard.get("model_variant_evidence_growth") or {}).get("delta_vs_baseline") or {}
    growth = _variant_delta_value(delta, "market_day_count", "unique_market_day_count", "unique_observation_count")
    if growth is not None and growth >= RETRAIN_CORPUS_GROWTH_MARKET_DAYS:
        reasons.append({
            "code": "corpus_growth",
            "detail": f"variant evidence grew by {fmt_num(growth, 3)} market-day/observation unit(s)",
            "value": growth,
            "threshold": RETRAIN_CORPUS_GROWTH_MARKET_DAYS,
        })

    for row in learnings or []:
        if row.get("category") in {"calibration_drift", "directional_bias_drift"} and row.get("retrain_input"):
            reasons.append({
                "code": row.get("category"),
                "detail": row.get("signal"),
                "priority": row.get("priority"),
            })
        elif (
            row.get("category") in {"market_skill_gap", "model_gap_slice", "hourly_early_market_delta"}
            and row.get("priority") in {"P0", "P1"}
            and row.get("retrain_input")
        ):
            reasons.append({
                "code": "chronic_or_priority_slice",
                "detail": row.get("signal"),
                "priority": row.get("priority"),
            })

    eligible_count = safe_int((experiment_queue.get("summary") or {}).get("eligible_count"))
    if eligible_count:
        reasons.append({
            "code": "eligible_experiment_queue",
            "detail": f"{eligible_count} queued experiment(s) are eligible for nightly execution",
            "value": eligible_count,
        })

    recommended = bool(reasons)
    return {
        "recommended": recommended,
        "status": "RECOMMENDED" if recommended else "NOT_RECOMMENDED",
        "scheduled_fallback": False,
        "reasons": reasons or [{"code": "no_new_drift_or_novelty", "detail": "No clean drift, novelty, chronic-slice, or eligible queue trigger fired."}],
        "thresholds": thresholds,
        "eligible_experiment_count": eligible_count,
        "detail": (
            "Run retrain from explicit drift/novelty triggers."
            if recommended
            else "Retrain is not recommended by drift/novelty signals; default scheduled retrain remains available."
        ),
    }


def _retrain_plan(scorecard, learnings, artifacts, snapshots_root, experiment_queue=None, retrain_recommendation=None):
    blockers = [row for row in learnings if row.get("blocker")]
    retrain_inputs = [row for row in learnings if row.get("retrain_input")]
    corpus = scorecard["corpus"]
    candidate = scorecard["candidate"]
    snapshot_status = scorecard["snapshot_evaluation"]["status"]
    variant_sla = (scorecard.get("model_variant_evidence_growth") or {}).get("evidence_sla") or {}
    label_countability = scorecard.get("label_countability") or {}
    labels_promotion_countable = label_countability.get("promotion_countable")
    if labels_promotion_countable is None:
        labels_promotion_countable = True
    evidence_allows_broad_promotion = variant_sla.get("broad_promotion_claim_allowed")
    if evidence_allows_broad_promotion is None:
        evidence_allows_broad_promotion = True
    live_slo = ((scorecard.get("fleet") or {}).get("live_forward_slo") or {})
    broad_slo_counts = live_slo.get("counts_toward_live_forward_gate")
    first_blocker = blockers[0] if blockers else None
    data_fail = scorecard["data_layer_audit"]["gate_status"] == "FAIL"
    ingest_fail = scorecard["ingest_quality_gate"]["status"] == "FAIL"
    has_corpus = corpus.get("market_day_count", 0) > 0 or scorecard["labels"]["total"] > 0
    candidate_rows = safe_int(candidate.get("rows"))
    delta_vs_current = candidate.get("delta_vs_current")
    delta_vs_market = candidate.get("delta_vs_market")
    candidate_delta_measured = delta_vs_current is not None
    beats_current_model = bool(candidate_delta_measured and delta_vs_current <= 0)
    beats_market = bool(delta_vs_market is not None and delta_vs_market <= 0)
    promotion_confidence = _promotion_confidence(candidate)
    candidate_delta_confident = promotion_confidence.get("promotion_ready") is True
    training_ready = (
        has_corpus
        and not blockers
        and not data_fail
        and not ingest_fail
        and broad_slo_counts is not False
    )
    promotion_checks = {
        "training_ready": bool(training_ready),
        "snapshot_evaluation_not_fail": snapshot_status != "FAIL",
        "no_blocked_markets": not bool(scorecard["promotion"]["blocked_markets"]),
        "candidate_rows_present": candidate_rows > 0,
        "candidate_delta_vs_current_measured": candidate_delta_measured,
        "beats_current_model": beats_current_model,
        "candidate_delta_vs_current_confident": candidate_delta_confident,
        "no_missing_candidate_rows": safe_int(candidate.get("missing_candidate_rows")) == 0,
        "broad_promotion_evidence_allowed": bool(evidence_allows_broad_promotion),
        "labels_promotion_countable": bool(labels_promotion_countable),
    }
    promotion_ready_reasons = [
        name for name, passed in promotion_checks.items()
        if not passed
    ]
    if not candidate_delta_confident:
        promotion_ready_reasons.extend(promotion_confidence.get("reasons") or [])
    promotion_ready = not promotion_ready_reasons
    return {
        "training_ready": bool(training_ready),
        "promotion_ready": bool(promotion_ready),
        "beats_current_model": beats_current_model,
        "beats_market": beats_market,
        "candidate_delta_vs_current_measured": candidate_delta_measured,
        "candidate_delta_vs_market_measured": delta_vs_market is not None,
        "promotion_confidence": promotion_confidence,
        "promotion_ready_checks": promotion_checks,
        "promotion_ready_reasons": promotion_ready_reasons,
        "blocker_count": len(blockers),
        "first_uncleared_p0_gate": first_blocker or {},
        "retrain_input_count": len(retrain_inputs),
        "experiment_queue": {
            "status": (experiment_queue or {}).get("status"),
            "queue_count": ((experiment_queue or {}).get("summary") or {}).get("queue_count"),
            "eligible_count": ((experiment_queue or {}).get("summary") or {}).get("eligible_count"),
            "item301_count": ((experiment_queue or {}).get("summary") or {}).get("item301_count"),
        },
        "retrain_recommendation": retrain_recommendation or {},
        "snapshots_root": str(Path(snapshots_root)),
        "broad_live_forward_slo": {
            "status": live_slo.get("status"),
            "counts_toward_live_forward_gate": broad_slo_counts,
            "reason": live_slo.get("reason"),
            "first_blocker": (
                live_slo.get("first_blocker")
                or next(iter(live_slo.get("recovery_checklist") or []), {})
            ),
            "recovery_checklist": live_slo.get("recovery_checklist") or [],
            "snapshot_cadence_proof": live_slo.get("snapshot_cadence_proof") or {},
            "rerun_command": live_slo.get("rerun_command"),
            "summary": live_slo.get("summary") or {},
        },
        "variant_learning_gate": scorecard.get("variant_learning_gate") or {},
        "label_countability": label_countability,
        "training_inputs": {
            "promotion_corpus": {
                "path": corpus.get("path") or artifacts["promotion_refresh"]["path"],
                "market_day_count": corpus.get("market_day_count"),
                "snapshot_count": corpus.get("snapshot_count"),
                "band_row_count": corpus.get("band_row_count"),
                "corpus_hash": corpus.get("corpus_hash"),
            },
            "settled_labels": scorecard["labels"],
            "candidate_rows": candidate.get("rows"),
            "candidate_delta_vs_current": candidate.get("delta_vs_current"),
            "candidate_delta_vs_market": candidate.get("delta_vs_market"),
        },
        "recommended_next_steps": (
            [
                row.get("action")
                for row in blockers[:5]
                if row.get("action")
            ]
            if blockers
            else [
                "Run nightly retrain on the refreshed corpus.",
                "Replay the candidate against current and market baselines.",
                "Keep promotion gated by snapshot evaluation, shadow A/B, and data-layer status.",
            ] + [
                row.get("action")
                for row in retrain_inputs[:5]
                if row.get("action")
            ]
        ),
    }


def _overall_status(learnings, artifacts):
    if not any(artifacts[name]["exists"] for name in ("daily_refresh_status", "promotion_refresh", "snapshot_evaluation")):
        return "MISSING_INPUTS"
    if any(row.get("blocker") for row in learnings):
        return "BLOCKED"
    if learnings:
        return "ACTIONABLE"
    return "OK"


def build_learning_payload(
    *,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    run_date=None,
    generated_at_utc=None,
    daily_refresh_summary=None,
    rollup_generated_at_overrides=None,
    input_max_skew_hours=INPUT_FRESHNESS_MAX_SKEW_HOURS,
    input_brier_delta_tolerance=INPUT_CONSISTENCY_BRIER_TOLERANCE,
):
    payloads, artifacts = load_inputs(backtest_root)
    data_root = Path(backtest_root).parent
    synthesized_trading_evidence = False
    if not payloads.get("trading_evidence"):
        payloads["trading_evidence"] = build_trading_evidence_summary(
            mm_runs_root=data_root / "mm_runs",
            taker_runs_root=data_root / "taker_runs",
            target_date=run_date,
        )
        synthesized_trading_evidence = True
    generated = generated_at_utc or utc_iso()
    _coerce_in_memory_daily_refresh_input(payloads, artifacts, daily_refresh_summary, generated)
    daily_status_rollup = (
        ((payloads.get("daily_refresh_status") or {}).get("summary") or {}).get("rollup_freshness")
    )
    if rollup_generated_at_overrides is not None or daily_status_rollup:
        rollup_overrides = dict(rollup_generated_at_overrides or {})
        rollup_overrides.setdefault("daily_learning", generated)
        payloads["rollup_freshness"] = daily_rollup_freshness.build_rollup_freshness(
            backtest_root,
            snapshots_root=snapshots_root,
            generated_at_overrides=rollup_overrides,
    )
    daily_generated = (payloads.get("daily_refresh_status") or {}).get("generated_at_utc")
    trading_run_date = _trading_evidence_run_date(payloads.get("trading_evidence") or {})
    effective_run_date = (
        run_date
        or (str(trading_run_date)[:10] if trading_run_date else None)
        or (str(daily_generated)[:10] if daily_generated else str(generated)[:10])
    )
    if synthesized_trading_evidence:
        if not payloads["trading_evidence"].get("run_date"):
            payloads["trading_evidence"]["run_date"] = effective_run_date
        if not payloads["trading_evidence"].get("target_date"):
            payloads["trading_evidence"]["target_date"] = effective_run_date
        payloads["trading_evidence"]["generated_at_utc"] = daily_generated or generated
        record = artifacts.get("trading_evidence") or {}
        artifacts["trading_evidence"] = {
            **record,
            "name": "trading_evidence",
            "exists": True,
            "generated_at_utc": daily_generated or generated,
            "status": payloads["trading_evidence"].get("status"),
            "source": "synthesized_trading_evidence_summary",
        }
    scorecard = _scorecard(payloads, daily_refresh_summary=daily_refresh_summary)
    input_gate = _build_input_gate(
        payloads,
        artifacts,
        scorecard,
        run_date=effective_run_date,
        max_skew_hours=input_max_skew_hours,
        brier_delta_tolerance=input_brier_delta_tolerance,
    )
    scorecard["input_gate"] = input_gate
    truncated_sources = []
    learnings = _build_learnings(
        payloads,
        scorecard,
        artifacts=artifacts,
        truncated_sources=truncated_sources,
        input_gate=input_gate,
        run_date=effective_run_date,
    )
    learnings = _rank_learnings(learnings)
    experiment_queue = _build_experiment_queue(
        learnings,
        payloads,
        artifacts,
        generated_at_utc=generated,
        run_date=effective_run_date,
    )
    retrain_recommendation = _retrain_recommendation(
        scorecard,
        learnings,
        experiment_queue,
        input_gate,
    )
    status = _overall_status(learnings, artifacts)
    summary = {
        "learning_count": len(learnings),
        "blocker_count": sum(1 for row in learnings if row.get("blocker")),
        "high_priority_learning_count": sum(1 for row in learnings if row.get("priority") in {"P0", "P1"}),
        "retrain_input_count": sum(1 for row in learnings if row.get("retrain_input")),
        "experiment_queue_count": (experiment_queue.get("summary") or {}).get("queue_count"),
        "eligible_experiment_count": (experiment_queue.get("summary") or {}).get("eligible_count"),
        "retrain_recommended": retrain_recommendation.get("recommended"),
        "truncated_sources": truncated_sources,
        "input_gate_status": input_gate.get("status"),
        "input_coverage": {
            "present_count": (input_gate.get("coverage") or {}).get("present_count"),
            "total_count": (input_gate.get("coverage") or {}).get("total_count"),
            "missing_count": (input_gate.get("coverage") or {}).get("missing_count"),
            "critical_missing_inputs": (input_gate.get("coverage") or {}).get("critical_missing_inputs") or [],
        },
    }
    retrain_plan = _retrain_plan(
        scorecard,
        learnings,
        artifacts,
        snapshots_root,
        experiment_queue=experiment_queue,
        retrain_recommendation=retrain_recommendation,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "run_date": effective_run_date,
        "status": status,
        "backtest_root": str(Path(backtest_root)),
        "snapshots_root": str(Path(snapshots_root)),
        "summary": summary,
        "input_gate": input_gate,
        "scorecard": scorecard,
        "retrain_plan": retrain_plan,
        "experiment_queue": experiment_queue,
        "learnings": learnings,
        "input_artifacts": artifacts,
    }



def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = write_json_atomic(json_out, payload, trailing_newline=True)
    report_out = Path(report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def build_parser():
    parser = argparse.ArgumentParser(description="Build the daily model log-learning artifact.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--run-date", default="")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--input-max-skew-hours", type=float, default=INPUT_FRESHNESS_MAX_SKEW_HOURS)
    parser.add_argument("--input-brier-delta-tolerance", type=float, default=INPUT_CONSISTENCY_BRIER_TOLERANCE)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_learning_payload(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=args.run_date or None,
        input_max_skew_hours=args.input_max_skew_hours,
        input_brier_delta_tolerance=args.input_brier_delta_tolerance,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Daily log learning: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0 if payload["status"] != "MISSING_INPUTS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
