"""Daily log-learning pack for retrain and promotion decisions.

The daily refresh produces several durable artifacts: settlement labels,
promotion/candidate replay outputs, shadow A/B checks, disagreement cases, and
data-quality audits.  This module distills those logs into one compact artifact
that records what was learned, what should feed the next retrain, and what must
block promotion claims until fixed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from weather.io import read_json, write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_learning")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning_report.md"

ARTIFACT_FILES = {
    "daily_refresh_status": "daily_refresh_status.json",
    "ingest_quality_gate": "ingest_quality_gate.json",
    "promotion_refresh": "f_family_promotion_refresh.json",
    "candidate_replay": "pooled_candidate_replay_latest.json",
    "shadow_ab_monitor": "shadow_ab_monitor.json",
    "model_variant_evidence_growth": "model_variant_evidence_growth.json",
    "progress_audit": "progress_audit.json",
    "disagreement_casebook": "disagreement_casebook.json",
    "fleet_observability": "fleet_observability.json",
    "data_layer_audit": "data_layer_audit.json",
    "snapshot_evaluation": "snapshot_evaluation.json",
    "settled_day_freshness": "settled_day_freshness.json",
    "source_family_inventory": "source_family_inventory.json",
}


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_int(value):
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _artifact_record(name, path, payload):
    status = None
    if isinstance(payload, dict):
        raw_status = payload.get("status")
        if isinstance(raw_status, dict):
            status = raw_status.get("status")
        else:
            status = raw_status
    return {
        "name": name,
        "path": str(path),
        "exists": payload is not None,
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        "generated_at_utc": payload.get("generated_at_utc") if isinstance(payload, dict) else None,
        "status": status,
    }


def load_inputs(backtest_root=DEFAULT_BACKTEST_ROOT):
    root = Path(backtest_root)
    payloads = {}
    artifacts = {}
    for name, filename in ARTIFACT_FILES.items():
        path = root / filename
        payload = read_json(path, default=None)
        payloads[name] = payload or {}
        artifacts[name] = _artifact_record(name, path, payload)
    return payloads, artifacts


def _candidate_from_payloads(payloads):
    promotion = payloads.get("promotion_refresh") or {}
    candidate = promotion.get("candidate") or {}
    replay = payloads.get("candidate_replay") or {}
    if candidate:
        return candidate
    if replay:
        return {
            "aggregate": replay.get("aggregate") or {},
            "coverage": replay.get("coverage") or {},
            "verdict": replay.get("verdict"),
            "candidate_market_verdict": replay.get("candidate_market_verdict"),
            "cutover_decision": replay.get("cutover_decision"),
            "blocked_validation": replay.get("blocked_validation") or {},
            "slices": {
                "by_market": replay.get("market_rows") or [],
                "by_cutoff_hour": replay.get("by_hour") or [],
                "by_band_type": replay.get("by_bin_type") or [],
                "by_settlement_distance": replay.get("by_settlement_distance") or [],
                "by_source_freshness": replay.get("by_source_freshness") or [],
            },
        }
    return {}


def _scorecard(payloads, daily_refresh_summary=None):
    daily = payloads.get("daily_refresh_status") or {}
    daily_summary = daily_refresh_summary or daily.get("summary") or {}
    labels = daily_summary.get("labels") or {}
    ingest = first_present(
        daily_summary.get("ingest_quality_gate"),
        payloads.get("ingest_quality_gate"),
    ) or {}
    promotion = payloads.get("promotion_refresh") or {}
    candidate = _candidate_from_payloads(payloads)
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    decisions = promotion.get("decisions") or {}
    shadow = payloads.get("shadow_ab_monitor") or {}
    variant = payloads.get("model_variant_evidence_growth") or {}
    progress = payloads.get("progress_audit") or {}
    casebook = (payloads.get("disagreement_casebook") or {}).get("summary") or {}
    fleet = payloads.get("fleet_observability") or {}
    data_layer = payloads.get("data_layer_audit") or {}
    snapshot_eval = payloads.get("snapshot_evaluation") or {}
    settled_day = payloads.get("settled_day_freshness") or {}
    source_family_inventory = payloads.get("source_family_inventory") or {}
    snapshot_status = snapshot_eval.get("status") or {}
    snapshot_inventory = snapshot_eval.get("snapshot_inventory") or {}
    backlog = snapshot_eval.get("improvement_backlog") or {}

    return {
        "labels": {
            "total": safe_int(labels.get("total")),
            "quality_counts": labels.get("quality_counts") or {},
            "reconciliation_counts": labels.get("reconciliation_counts") or {},
        },
        "ingest_quality_gate": {
            "status": ingest.get("status"),
            "fail_reasons": ingest.get("fail_reasons") or [],
            "warn_reasons": ingest.get("warn_reasons") or [],
        },
        "promotion": {
            "candidate_verdict": candidate.get("verdict") or promotion.get("candidate_verdict"),
            "cutover_decision": candidate.get("cutover_decision") or promotion.get("cutover_decision"),
            "promote_markets": decisions.get("promote_markets") or [],
            "shadow_markets": decisions.get("shadow_markets") or [],
            "blocked_markets": decisions.get("blocked_markets") or [],
            "action_counts": decisions.get("action_counts") or {},
        },
        "corpus": {
            "market_day_count": safe_int(corpus.get("market_day_count")),
            "snapshot_count": safe_int(corpus.get("snapshot_count")),
            "band_row_count": safe_int(corpus.get("band_row_count")),
            "path": corpus.get("path"),
            "corpus_hash": corpus.get("corpus_hash"),
        },
        "candidate": {
            "rows": safe_int(aggregate.get("rows") or aggregate.get("n")),
            "candidate_brier": maybe_float(aggregate.get("candidate_brier")),
            "current_brier": maybe_float(aggregate.get("current_brier")),
            "market_brier": maybe_float(aggregate.get("market_brier")),
            "delta_vs_current": maybe_float(aggregate.get("delta_vs_current")),
            "delta_vs_market": maybe_float(aggregate.get("delta_vs_market")),
            "missing_candidate_rows": safe_int((candidate.get("coverage") or {}).get("missing_candidate_rows")),
            "blocked_validation": candidate.get("blocked_validation") or {},
        },
        "shadow_ab_monitor": {
            "status": shadow.get("status"),
            "summary": shadow.get("summary") or {},
        },
        "model_variant_evidence_growth": {
            "status": variant.get("status"),
            "summary": variant.get("summary") or {},
            "delta_vs_baseline": variant.get("delta_vs_baseline"),
            "evidence_sla": variant.get("evidence_sla") or {},
            "no_growth_reasons": variant.get("no_growth_reasons") or [],
            "trend": variant.get("trend") or [],
        },
        "core_model_trend_claim": progress.get("core_model_trend_claim") or {},
        "casebook": {
            "case_count": safe_int(casebook.get("case_count")),
            "settled_case_count": safe_int(casebook.get("settled_case_count")),
            "open_case_count": safe_int(casebook.get("open_case_count")),
            "model_win_count": safe_int(casebook.get("model_win_count")),
            "model_loss_count": safe_int(casebook.get("model_loss_count")),
            "taxonomy_counts": casebook.get("taxonomy_counts") or {},
        },
        "fleet": {
            "status": fleet.get("status"),
            "summary": fleet.get("summary") or {},
            "live_forward_slo": fleet.get("live_forward_slo") or {},
            "tape_backup": fleet.get("tape_backup") or {},
            "mm_paper_evidence": fleet.get("mm_paper_evidence") or {},
        },
        "data_layer_audit": {
            "gate_status": (data_layer.get("gate_summary") or {}).get("status"),
            "gate_summary": data_layer.get("gate_summary") or {},
            "recommendation_count": len(data_layer.get("recommendations") or []),
            "p0_remediation_count": len(
                [
                    row for row in data_layer.get("remediation_manifest") or []
                    if row.get("priority") == "P0"
                ]
            ),
        },
        "snapshot_evaluation": {
            "status": snapshot_status.get("status"),
            "gate_counts": snapshot_status,
            "snapshot_folders": safe_int(snapshot_inventory.get("folder_count")),
            "snapshots": safe_int(snapshot_inventory.get("snapshot_count")),
            "top_gap_count": len(backlog.get("top_slices") or []),
        },
        "settled_day_freshness": {
            "status": settled_day.get("status"),
            "target_date": settled_day.get("target_date"),
            "summary": settled_day.get("summary") or {},
            "repair_command": settled_day.get("repair_command"),
            "replay_status_repair_command": settled_day.get("replay_status_repair_command"),
        },
        "source_family_inventory": {
            "status": source_family_inventory.get("status"),
            "summary": source_family_inventory.get("summary") or {},
            "promotion_preflight": source_family_inventory.get("promotion_preflight") or {},
        },
    }


def _learning(priority, category, source, signal, action, *, evidence=None, retrain_input=False, blocker=False):
    return {
        "priority": priority,
        "category": category,
        "source": source,
        "signal": signal,
        "action": action,
        "evidence": evidence or {},
        "retrain_input": bool(retrain_input),
        "blocker": bool(blocker),
    }


def _add_gate_learnings(learnings, gates):
    for gate in gates or []:
        status = gate.get("status")
        if status not in {"FAIL", "WARN"}:
            continue
        priority = "P0" if status == "FAIL" and gate.get("severity") == "fail" else "P2"
        learnings.append(_learning(
            priority,
            "validation_gate",
            "snapshot_evaluation",
            f"{gate.get('name')} is {status}: {gate.get('detail') or '-'}",
            gate.get("action") or "Review the failing evaluation gate before promotion.",
            evidence={"gate": gate.get("name"), "status": status},
            blocker=priority == "P0",
        ))


def _add_backlog_learnings(learnings, top_slices):
    for row in (top_slices or [])[:8]:
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


def _add_gap_owner_learnings(learnings, rows):
    for row in (rows or [])[:8]:
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


def _add_data_recommendations(learnings, recommendations):
    for item in (recommendations or [])[:8]:
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


def _add_data_remediations(learnings, remediations, *, report_path=None):
    for item in (remediations or [])[:8]:
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


def _add_variant_alerts(learnings, variant):
    for alert in (variant.get("alerts") or [])[:8]:
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


def _build_learnings(payloads, scorecard, artifacts=None):
    learnings = []
    artifacts = artifacts or {}
    labels_total = scorecard["labels"]["total"]
    corpus = scorecard["corpus"]
    candidate = scorecard["candidate"]
    ingest = scorecard["ingest_quality_gate"]
    data_layer = scorecard["data_layer_audit"]
    settled_day = scorecard["settled_day_freshness"]
    source_family_inventory = scorecard.get("source_family_inventory") or {}
    fleet = scorecard["fleet"]
    shadow = scorecard["shadow_ab_monitor"]
    variant = payloads.get("model_variant_evidence_growth") or {}
    data_payload = payloads.get("data_layer_audit") or {}
    promotion_payload = payloads.get("promotion_refresh") or {}
    snapshot_eval = payloads.get("snapshot_evaluation") or {}
    promotion = scorecard["promotion"]
    casebook = scorecard["casebook"]

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

    if labels_total or corpus.get("market_day_count"):
        learnings.append(_learning(
            "P1",
            "new_training_evidence",
            "market_day_labels_finalize",
            (
                f"{labels_total} labels finalized; corpus has "
                f"{corpus.get('market_day_count')} market-days and {corpus.get('snapshot_count')} snapshots"
            ),
            "Use the refreshed corpus as the next retrain and replay input.",
            evidence={"labels": scorecard["labels"], "corpus": corpus},
            retrain_input=True,
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
    )

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

    _add_data_recommendations(learnings, data_payload.get("recommendations"))
    _add_gate_learnings(learnings, snapshot_eval.get("gates") or [])
    _add_backlog_learnings(learnings, (snapshot_eval.get("improvement_backlog") or {}).get("top_slices") or [])
    _add_gap_owner_learnings(learnings, promotion_payload.get("gap_owner_table") or [])

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

    if shadow.get("status") == "ALERT":
        learnings.append(_learning(
            "P1",
            "shadow_ab",
            "shadow_ab_monitor",
            "Shadow A/B monitor alerted.",
            "Do not broaden rollout until the alerting candidate/current deltas are explained.",
            evidence=shadow,
        ))

    _add_variant_alerts(learnings, variant)
    _add_independent_evidence_sla_learning(learnings, variant)
    _add_core_trend_claim_learning(learnings, scorecard.get("core_model_trend_claim") or {})

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


def _retrain_plan(scorecard, learnings, artifacts, snapshots_root):
    blockers = [row for row in learnings if row.get("blocker")]
    retrain_inputs = [row for row in learnings if row.get("retrain_input")]
    corpus = scorecard["corpus"]
    candidate = scorecard["candidate"]
    snapshot_status = scorecard["snapshot_evaluation"]["status"]
    variant_sla = (scorecard.get("model_variant_evidence_growth") or {}).get("evidence_sla") or {}
    evidence_allows_broad_promotion = variant_sla.get("broad_promotion_claim_allowed")
    if evidence_allows_broad_promotion is None:
        evidence_allows_broad_promotion = True
    live_slo = ((scorecard.get("fleet") or {}).get("live_forward_slo") or {})
    broad_slo_counts = live_slo.get("counts_toward_live_forward_gate")
    first_blocker = blockers[0] if blockers else None
    data_fail = scorecard["data_layer_audit"]["gate_status"] == "FAIL"
    ingest_fail = scorecard["ingest_quality_gate"]["status"] == "FAIL"
    has_corpus = corpus.get("market_day_count", 0) > 0 or scorecard["labels"]["total"] > 0
    training_ready = (
        has_corpus
        and not blockers
        and not data_fail
        and not ingest_fail
        and broad_slo_counts is not False
    )
    promotion_ready = (
        training_ready
        and snapshot_status != "FAIL"
        and not scorecard["promotion"]["blocked_markets"]
        and candidate.get("rows", 0) > 0
        and (candidate.get("delta_vs_current") is None or candidate.get("delta_vs_current") <= 0)
        and candidate.get("missing_candidate_rows", 0) == 0
        and bool(evidence_allows_broad_promotion)
    )
    return {
        "training_ready": bool(training_ready),
        "promotion_ready": bool(promotion_ready),
        "blocker_count": len(blockers),
        "first_uncleared_p0_gate": first_blocker or {},
        "retrain_input_count": len(retrain_inputs),
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
            "rerun_command": live_slo.get("rerun_command"),
            "summary": live_slo.get("summary") or {},
        },
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
):
    payloads, artifacts = load_inputs(backtest_root)
    generated = generated_at_utc or utc_iso()
    daily_generated = (payloads.get("daily_refresh_status") or {}).get("generated_at_utc")
    scorecard = _scorecard(payloads, daily_refresh_summary=daily_refresh_summary)
    learnings = _build_learnings(payloads, scorecard, artifacts=artifacts)
    status = _overall_status(learnings, artifacts)
    summary = {
        "learning_count": len(learnings),
        "blocker_count": sum(1 for row in learnings if row.get("blocker")),
        "high_priority_learning_count": sum(1 for row in learnings if row.get("priority") in {"P0", "P1"}),
        "retrain_input_count": sum(1 for row in learnings if row.get("retrain_input")),
    }
    retrain_plan = _retrain_plan(scorecard, learnings, artifacts, snapshots_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "run_date": run_date or (str(daily_generated)[:10] if daily_generated else str(generated)[:10]),
        "status": status,
        "backtest_root": str(Path(backtest_root)),
        "snapshots_root": str(Path(snapshots_root)),
        "summary": summary,
        "scorecard": scorecard,
        "retrain_plan": retrain_plan,
        "learnings": learnings,
        "input_artifacts": artifacts,
    }


def _scorecard_rows(scorecard):
    labels = scorecard.get("labels") or {}
    corpus = scorecard.get("corpus") or {}
    candidate = scorecard.get("candidate") or {}
    promotion = scorecard.get("promotion") or {}
    casebook = scorecard.get("casebook") or {}
    snapshot_eval = scorecard.get("snapshot_evaluation") or {}
    core_trend = scorecard.get("core_model_trend_claim") or {}
    core_summary = core_trend.get("summary") or {}
    fleet = scorecard.get("fleet") or {}
    live_slo = fleet.get("live_forward_slo") or {}
    live_slo_summary = live_slo.get("summary") or {}
    return [
        ["Labels finalized", labels.get("total")],
        ["Corpus market-days", corpus.get("market_day_count")],
        ["Corpus snapshots", corpus.get("snapshot_count")],
        ["Candidate rows", candidate.get("rows")],
        ["Candidate delta vs current", fmt_signed(candidate.get("delta_vs_current"))],
        ["Candidate delta vs market", fmt_signed(candidate.get("delta_vs_market"))],
        ["Promote markets", ", ".join(promotion.get("promote_markets") or []) or "-"],
        ["Shadow markets", ", ".join(promotion.get("shadow_markets") or []) or "-"],
        ["Blocked markets", ", ".join(promotion.get("blocked_markets") or []) or "-"],
        ["Casebook cases", casebook.get("case_count")],
        ["Model-losing cases", casebook.get("model_loss_count")],
        ["Snapshot evaluation", snapshot_eval.get("status")],
        ["Top gap slices", snapshot_eval.get("top_gap_count")],
        [
            "Broad live-forward SLO",
            (
                f"{live_slo.get('status') or '-'}; "
                f"counts={live_slo.get('counts_toward_live_forward_gate')}; "
                f"first={live_slo_summary.get('first_blocking_market') or '-'}:"
                f"{live_slo_summary.get('first_blocking_gate') or '-'}"
            ),
        ],
        [
            "Core trend claim",
            (
                f"{core_trend.get('status') or '-'}; "
                f"claim_allowed={core_trend.get('claim_allowed')}; "
                f"positive_days={core_summary.get('positive_skill_days')}; "
                f"rolling_daily_first={fmt_signed(core_summary.get('rolling_daily_first_brier_skill'))}"
            ),
        ],
    ]


def _core_trend_report_rows(claim):
    summary = (claim or {}).get("summary") or {}
    return [
        ["Status", (claim or {}).get("status") or "-"],
        ["Claim allowed", (claim or {}).get("claim_allowed")],
        ["Comparable full-market days", summary.get("comparable_day_count")],
        ["Promotion-grade market-days", summary.get("promotion_grade_market_days")],
        ["Positive-skill days", summary.get("positive_skill_days")],
        ["Rolling daily-first skill", fmt_signed(summary.get("rolling_daily_first_brier_skill"))],
        ["Brier skill slope/day", fmt_signed(summary.get("brier_skill_slope_per_day"))],
        ["Latest comparable day", summary.get("latest_comparable_date") or "-"],
        ["Latest comparable skill", fmt_signed(summary.get("latest_comparable_brier_skill"))],
    ]


def _broad_slo_report_rows(live_slo):
    summary = (live_slo or {}).get("summary") or {}
    first = (live_slo or {}).get("first_blocker") or next(
        iter((live_slo or {}).get("recovery_checklist") or []),
        {},
    )
    return [
        ["Status", (live_slo or {}).get("status") or "-"],
        ["Counts toward live-forward gate", (live_slo or {}).get("counts_toward_live_forward_gate")],
        ["Reason", (live_slo or {}).get("reason") or "-"],
        ["Recovery rows", summary.get("recovery_row_count")],
        ["First blocking market", first.get("market_id") or "-"],
        ["First blocking component", first.get("component") or "-"],
        ["First blocking gate", first.get("gate") or "-"],
        ["First owner", first.get("owner") or "-"],
        ["First repair command", first.get("repair_command") or "-"],
        ["Rerun command", (live_slo or {}).get("rerun_command") or first.get("verification_command") or "-"],
    ]


def _broad_slo_recovery_rows(live_slo):
    return [
        [
            row.get("market_id"),
            row.get("component"),
            row.get("gate"),
            row.get("owner"),
            row.get("before"),
            row.get("repair_command"),
            row.get("verification_command"),
        ]
        for row in (live_slo or {}).get("recovery_checklist") or []
    ]


def render_report(payload):
    summary = payload.get("summary") or {}
    scorecard = payload.get("scorecard") or {}
    retrain = payload.get("retrain_plan") or {}
    learnings = payload.get("learnings") or []
    artifacts = payload.get("input_artifacts") or {}
    lines = [
        "# Daily Log Learning",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run date: {payload.get('run_date')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Learnings", summary.get("learning_count", 0)],
            ["Blockers", summary.get("blocker_count", 0)],
            ["High-priority learnings", summary.get("high_priority_learning_count", 0)],
            ["Retrain inputs", summary.get("retrain_input_count", 0)],
            ["Training ready", retrain.get("training_ready")],
            ["Promotion ready", retrain.get("promotion_ready")],
        ],
    )
    lines += ["", "## Scorecard", ""]
    lines += markdown_table(["Area", "Value"], _scorecard_rows(scorecard))
    lines += ["", "## Learnings", ""]
    if learnings:
        lines += markdown_table(
            ["Priority", "Category", "Source", "Signal", "Action"],
            [
                [
                    row.get("priority"),
                    row.get("category"),
                    row.get("source"),
                    row.get("signal"),
                    row.get("action"),
                ]
                for row in learnings[:20]
            ],
        )
    else:
        lines.append("No actionable learnings were found in the available artifacts.")
    lines += ["", "## Retrain Plan", ""]
    first_gate = retrain.get("first_uncleared_p0_gate") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Training ready", retrain.get("training_ready")],
            ["Promotion ready", retrain.get("promotion_ready")],
            ["Blockers", retrain.get("blocker_count")],
            ["First P0 gate", first_gate.get("signal") or "-"],
            ["First P0 action", first_gate.get("action") or "-"],
            ["Retrain inputs", retrain.get("retrain_input_count")],
            ["Snapshots root", retrain.get("snapshots_root")],
        ],
    )
    live_slo = retrain.get("broad_live_forward_slo") or ((scorecard.get("fleet") or {}).get("live_forward_slo") or {})
    if live_slo:
        lines += ["", "## Broad Live-Forward SLO Recovery", ""]
        lines += markdown_table(["Field", "Value"], _broad_slo_report_rows(live_slo))
        recovery_rows = _broad_slo_recovery_rows(live_slo)
        if recovery_rows:
            lines += ["", "Recovery checklist:"]
            lines += markdown_table(
                ["Market", "Component", "Gate", "Owner", "Before", "Repair Command", "Verification"],
                recovery_rows,
            )
    steps = retrain.get("recommended_next_steps") or []
    if steps:
        lines += ["", "## Recommended Next Steps", ""]
        for step in steps[:10]:
            lines.append(f"- {step}")
    core_trend = scorecard.get("core_model_trend_claim") or {}
    if core_trend:
        lines += ["", "## Core Model Trend Claim", ""]
        lines += markdown_table(["Field", "Value"], _core_trend_report_rows(core_trend))
        failures = core_trend.get("threshold_failures") or []
        if failures:
            lines += ["", "Threshold failures:"]
            lines.extend(f"- {failure}" for failure in failures[:8])
        needed = core_trend.get("next_evidence_needed") or []
        if needed:
            lines += ["", "Next evidence needed:"]
            for action in dict.fromkeys(needed):
                lines.append(f"- {action}")
    lines += ["", "## Input Artifacts", ""]
    lines += markdown_table(
        ["Artifact", "Exists", "Status", "Path"],
        [
            [row.get("name"), row.get("exists"), row.get("status"), row.get("path")]
            for _name, row in sorted(artifacts.items())
        ],
    )
    lines.append("")
    return "\n".join(lines)


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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_learning_payload(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=args.run_date or None,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Daily log learning: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0 if payload["status"] != "MISSING_INPUTS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
