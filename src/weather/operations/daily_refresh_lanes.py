"""Promotion/learning lane state for the daily-refresh orchestrator."""

from __future__ import annotations

from collections import Counter
from datetime import date

from weather.operations.daily_refresh_locks import utc_iso
from weather.operations.daily_refresh_registry import (
    COVERAGE_DEPENDENCIES,
    COVERAGE_NOT_APPLICABLE,
    COVERAGE_OWN,
    LANE_LEARNING,
    LANE_PROMOTION,
    STEP_LEARNING_COVERAGE_MODES,
    STEP_LEARNING_COVERAGE_DEPENDENCIES,
    STEP_LANES,
    STEP_ORDER,
    STEP_PROMOTION_GATES,
    STEP_PROMOTION_RECEIPT_POLICIES,
    STAGE_EVIDENCE,
    carried_forward_stage_head,
    carried_forward_steps,
)
from weather.operations.daily_refresh_resources import STAGE_A_ISOLATED_STEPS


PROMOTION_BLOCK_RESULT_STATUSES = frozenset(
    {
        "BLOCK",
        "BLOCKED",
        "BREACH",
        "CRITICAL",
        "ERROR",
        "FAIL",
        "MISSING",
        "MISSING_INPUTS",
        "NO_DATA",
        "SKIPPED",
        "STALE",
    }
)
LEARNING_INCOMPLETE_RESULT_STATUSES = PROMOTION_BLOCK_RESULT_STATUSES | {
    "DEFERRED"
}
LEARNING_COVERAGE_GAP_RESULT_STATUSES = frozenset(
    {"ERROR", "FAIL", "MISSING", "MISSING_INPUTS", "NO_DATA", "STALE"}
)
STEP_RESULT_INCOMPLETE_OVERRIDES = {
    "daily_learning": frozenset({"BLOCK", "BLOCKED", "CRITICAL"}),
    "daily_flow_analysis": frozenset({"BLOCK", "BLOCKED", "MISSING_INPUTS"}),
    "fleet_observability": frozenset({"BLOCK", "CRITICAL", "FAIL"}),
    "ingest_quality_gate": frozenset({"BLOCK", "FAIL"}),
}
TERMINAL_STEP_FAILURE_STATUSES = frozenset({"error", "deferred", "blocked"})


def _latest_step_by_name(steps, name):
    return next(
        (step for step in reversed(steps or []) if step.get("name") == name),
        {},
    )


def step_lane(name):
    return STEP_LANES.get(name)


def resume_carry_state(
    prior,
    current_stage_a,
    *,
    stage,
    resume_from_step,
    requested_target,
    current_stage_a_binding="",
):
    """Resolve target/run-bound receipts for a resumed daily-refresh stage."""
    prior_target = str(
        ((prior.get("config") or {}).get("settled_analysis_target_date"))
        or ""
    )
    prior_stage_gate = (
        (prior.get("config") or {}).get("stage_gate") or {}
    )
    prior_stage_a_binding = str(
        prior_stage_gate.get("stage_a_binding") or ""
    )
    current_stage_a_binding = str(current_stage_a_binding or "")
    target_match = bool(requested_target and prior_target == requested_target)
    stage_a_binding_match = bool(
        stage != STAGE_EVIDENCE
        or (
            current_stage_a_binding
            and prior_stage_a_binding == current_stage_a_binding
        )
    )
    carry_prior = target_match and stage_a_binding_match
    restart_stage = stage == STAGE_EVIDENCE and not carry_prior
    source = current_stage_a if restart_stage else prior
    steps = (
        carried_forward_stage_head(source.get("steps"), stage)
        if restart_stage
        else carried_forward_steps(
            source.get("steps"), resume_from_step
        )
        if carry_prior
        else []
    )
    return {
        "steps": steps,
        "resource_steps": list(source.get("resource_steps") or []),
        "source_started_at_utc": source.get("started_at_utc"),
        "restart_from_stage_start": restart_stage,
        "binding": {
            "status": "PASS" if carry_prior else "BLOCK",
            "requested_target_date": requested_target,
            "prior_target_date": prior_target,
            "current_stage_a_binding": current_stage_a_binding,
            "prior_stage_a_binding": prior_stage_a_binding,
            "reason": (
                ""
                if carry_prior
                else "resume_target_mismatch"
                if not target_match
                else "resume_stage_a_binding_mismatch"
            ),
        },
    }


def _date_text(value):
    text = str(value or "")[:10]
    try:
        date.fromisoformat(text)
    except (TypeError, ValueError):
        return ""
    return text


def _blocker_record(step, result):
    upstream = result.get("upstream_blocker") or {}
    if upstream:
        return dict(upstream)
    return {
        "step": step.get("name"),
        "step_status": step.get("status"),
        "result_status": result.get("status"),
        "root_cause_class": step.get("root_cause_class"),
        "reason": (
            step.get("error")
            or result.get("reason")
            or result.get("detail")
            or (result.get("first_blocker") or {}).get("detail")
            or "promotion_dependency_not_current_and_passing"
        ),
        "target_date": result.get("target_date"),
        "resume_command": result.get("resume_command"),
    }


def promotion_lane_outcome_blocker(
    steps,
    *,
    required_names=None,
    target_date="",
):
    """Return the first current-run receipt that fails promotion closed."""
    if required_names is not None:
        required = set(required_names)
        observed = {
            step.get("name")
            for step in steps or []
            if step.get("status") not in {"planned", "running"}
        }
        for name in STEP_ORDER:
            if name in required and name not in observed:
                return {
                    "step": name,
                    "step_status": "missing",
                    "result_status": "MISSING",
                    "root_cause_class": "promotion_receipt_missing",
                    "reason": "required_current_run_promotion_receipt_missing",
                }
    for step in steps or []:
        name = step.get("name")
        if not STEP_PROMOTION_GATES.get(name, False):
            continue
        step_status = str(step.get("status") or "").lower()
        if step_status in {"planned", "running"}:
            continue
        raw_result = step.get("result")
        result = raw_result if isinstance(raw_result, dict) else {}
        if step.get("lane_blocker") or step_status != "ok":
            return _blocker_record(step, result)
        if result.get("skipped") is True:
            blocker = _blocker_record(step, result)
            blocker.update(
                {
                    "result_status": "SKIPPED",
                    "root_cause_class": "promotion_receipt_skipped",
                    "reason": result.get("reason")
                    or "required_promotion_gate_explicitly_skipped",
                }
            )
            return blocker
        policy = STEP_PROMOTION_RECEIPT_POLICIES[name]
        result_status = str(result.get("status") or "").upper()
        if result_status not in policy["known_statuses"]:
            blocker = _blocker_record(step, result)
            blocker.update(
                {
                    "root_cause_class": "promotion_receipt_unknown_status",
                    "reason": "required_promotion_receipt_status_not_allowlisted",
                    "known_statuses": sorted(policy["known_statuses"]),
                }
            )
            return blocker
        if result_status not in policy["action_statuses"]:
            blocker = _blocker_record(step, result)
            blocker.update(
                {
                    "root_cause_class": "promotion_gate_negative_verdict",
                    "reason": "current_run_promotion_gate_not_actionable",
                    "action_statuses": sorted(policy["action_statuses"]),
                }
            )
            return blocker
        expected_target = _date_text(target_date)
        for field in policy.get("target_fields", ()):
            observed_target = _date_text(result.get(field))
            if expected_target and observed_target != expected_target:
                blocker = _blocker_record(step, result)
                blocker.update(
                    {
                        "root_cause_class": (
                            "promotion_receipt_target_mismatch"
                            if observed_target
                            else "promotion_receipt_target_missing"
                        ),
                        "reason": (
                            "current_run_receipt_target_mismatch"
                            if observed_target
                            else "current_run_receipt_target_missing"
                        ),
                        "target_field": field,
                        "expected_target_date": expected_target,
                        "observed_target_date": observed_target,
                    }
                )
                return blocker
        for field in policy.get("positive_count_fields", ()):
            try:
                positive = float(result.get(field)) > 0
            except (TypeError, ValueError):
                positive = False
            if not positive:
                blocker = _blocker_record(step, result)
                blocker.update(
                    {
                        "root_cause_class": "promotion_receipt_vacuous",
                        "reason": "current_run_receipt_positive_count_missing",
                        "count_field": field,
                        "observed_count": result.get(field),
                    }
                )
                return blocker
    return {}


def settlement_barrier_blocker(steps, *, target_date=""):
    barrier = _latest_step_by_name(steps, "settled_day_analysis_barrier")
    if not barrier:
        return {
            "step": "settled_day_analysis_barrier",
            "step_status": "missing",
            "result_status": "MISSING",
            "root_cause_class": "settlement_barrier_missing",
            "reason": "settlement_barrier_current_run_receipt_missing",
            "expected_target_date": _date_text(target_date),
        }
    result = barrier.get("result") or {}
    result_status = str(result.get("status") or "").upper()
    observed_target = _date_text(result.get("target_date"))
    expected_target = _date_text(target_date)
    if barrier.get("status") != "ok" or result_status != "PASS":
        return _blocker_record(barrier, result)
    if expected_target and observed_target != expected_target:
        blocker = _blocker_record(barrier, result)
        blocker.update(
            {
                "root_cause_class": (
                    "settlement_barrier_target_mismatch"
                    if observed_target
                    else "settlement_barrier_target_missing"
                ),
                "reason": (
                    "settlement_barrier_target_mismatch"
                    if observed_target
                    else "settlement_barrier_target_missing"
                ),
                "expected_target_date": expected_target,
                "observed_target_date": observed_target,
            }
        )
        return blocker
    return {}


def chain_target_settlement_coverage(args, steps):
    """Return authoritative chain-level target settlement coverage."""
    barrier = _latest_step_by_name(steps, "settled_day_analysis_barrier")
    barrier_result = barrier.get("result") or {}
    barrier_status = str(barrier_result.get("status") or "").upper()
    target_date = _date_text(
        getattr(args, "settled_analysis_target_date", "")
        or barrier_result.get("target_date")
    )
    barrier_target = _date_text(barrier_result.get("target_date"))
    promotion_blocker = promotion_lane_outcome_blocker(
        steps,
        target_date=target_date,
    )
    if (
        barrier
        and barrier.get("status") == "ok"
        and barrier_status == "PASS"
        and (not target_date or barrier_target == target_date)
    ):
        coverage_status = "COMPLETE"
        target_included = True
        gap_reason = ""
        blocker_step = ""
    elif barrier:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = (
            "settlement_barrier_target_mismatch"
            if barrier_status == "PASS"
            else "settlement_barrier_not_passing"
        )
        blocker_step = barrier.get("name")
    elif promotion_blocker:
        coverage_status = "UNKNOWN"
        target_included = None
        gap_reason = "promotion_blocked_before_settlement_coverage_known"
        blocker_step = promotion_blocker.get("step") or ""
    else:
        coverage_status = "UNKNOWN"
        target_included = None
        gap_reason = "settlement_barrier_not_yet_observed"
        blocker_step = ""
    return {
        "coverage_status": coverage_status,
        "coverage_basis": "settled_day_analysis_barrier",
        "requested_target_date": target_date,
        "latest_settled_date": "",
        "corpus_date_max": "",
        "target_included": target_included,
        "staleness_days": None,
        "settlement_barrier_status": barrier_status or "NOT_RUN",
        "gap_reason": gap_reason,
        "blocker_step": blocker_step,
        "gap_recorded": coverage_status == "GAPPED",
    }


def _step_dates(result, *, coverage_mode, step_name):
    settled_dates = set()
    corpus_dates = set()
    for value in (
        result.get("latest_settled_date"),
        result.get("latest_settled_label_date"),
        (result.get("scoring_liveness") or {}).get(
            "latest_settled_label_date"
        ),
    ):
        parsed = _date_text(value)
        if parsed:
            settled_dates.add(parsed)
    for value in (
        result.get("corpus_date_max"),
        result.get("date_max"),
        result.get("last_scored_target_date"),
        (result.get("corpus") or {}).get("date_max"),
        (result.get("scoring_liveness") or {}).get("last_scored_target_date"),
    ):
        parsed = _date_text(value)
        if parsed:
            corpus_dates.add(parsed)
    if coverage_mode == COVERAGE_OWN:
        own_target_values = [
            (result.get("evidence_window") or {}).get("window_date_max"),
        ]
        count_field = {
            "runtime_identity_reconciliation": "snapshot_row_count",
            "model_market_disagreement_rehydration": "target_row_count",
        }.get(step_name)
        if count_field:
            try:
                has_target_rows = int(result.get(count_field) or 0) > 0
            except (TypeError, ValueError):
                has_target_rows = False
            if has_target_rows:
                own_target_values.append(result.get("target_date"))
        for value in own_target_values:
            parsed = _date_text(value)
            if parsed:
                corpus_dates.add(parsed)
    elif coverage_mode == COVERAGE_DEPENDENCIES and step_name == "trading_evidence":
        parsed = _date_text(result.get("target_date"))
        if parsed:
            corpus_dates.add(parsed)
    consistency = result.get("input_consistency") or (
        (result.get("input_gate") or {}).get("consistency") or {}
    )
    for check in consistency.get("checks") or []:
        evidence = check.get("evidence") or {}
        if evidence.get("mode") not in {"date_max", "equals"}:
            continue
        parsed = _date_text(evidence.get("observed_target_date"))
        if not parsed:
            continue
        name = str(check.get("name") or "")
        if "date_max" in name or "last_scored_target_date" in name:
            corpus_dates.add(parsed)
    return sorted(settled_dates), sorted(corpus_dates)


def _input_gate_statuses(result):
    statuses = {
        str(result.get("input_gate_status") or "").upper(),
        str(result.get("scoring_liveness_status") or "").upper(),
    }
    for name in ("input_coverage", "input_freshness", "input_consistency"):
        statuses.add(str((result.get(name) or {}).get("status") or "").upper())
    return {status for status in statuses if status}


def step_target_settlement_coverage(args, step, chain_coverage=None):
    """Build coverage from this step's own corpus/gates, then chain fallback."""
    result = step.get("result") or {}
    chain = dict(chain_coverage or {})
    coverage_mode = STEP_LEARNING_COVERAGE_MODES.get(step.get("name"))
    target_date = _date_text(
        getattr(args, "settled_analysis_target_date", "")
        or chain.get("requested_target_date")
    )
    if coverage_mode == COVERAGE_NOT_APPLICABLE:
        return {
            "coverage_status": "NOT_APPLICABLE",
            "coverage_mode": COVERAGE_NOT_APPLICABLE,
            "coverage_basis": COVERAGE_NOT_APPLICABLE,
            "requested_target_date": target_date,
            "latest_settled_date": "",
            "corpus_date_max": "",
            "observed_corpus_dates": [],
            "target_included": None,
            "staleness_days": None,
            "settlement_barrier_status": chain.get(
                "settlement_barrier_status", "NOT_RUN"
            ),
            "gap_reason": "",
            "blocker_step": "",
            "gap_recorded": False,
        }
    settled_dates, corpus_dates = _step_dates(
        result,
        coverage_mode=coverage_mode,
        step_name=step.get("name"),
    )
    own_dates = sorted(set(settled_dates + corpus_dates))
    latest_settled_date = max(settled_dates) if settled_dates else ""
    # The weakest input date is the honest aggregate for a multi-input learner.
    corpus_date_max = min(corpus_dates) if corpus_dates else ""
    input_statuses = _input_gate_statuses(result)
    result_status = str(result.get("status") or "").upper()
    outer_status = str(step.get("status") or "").lower()
    incomplete_input_statuses = sorted(
        input_statuses & LEARNING_INCOMPLETE_RESULT_STATUSES
    )

    if outer_status in TERMINAL_STEP_FAILURE_STATUSES:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "learning_step_not_completed"
        blocker_step = step.get("name") or ""
        basis = "step_execution"
    elif result.get("skipped") is True or result_status == "SKIPPED":
        coverage_status = "UNKNOWN"
        target_included = None
        gap_reason = "learning_step_result_skipped"
        blocker_step = step.get("name") or ""
        basis = "step_result"
    elif result_status in LEARNING_COVERAGE_GAP_RESULT_STATUSES:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "learning_step_result_" + result_status.lower()
        blocker_step = step.get("name") or ""
        basis = "step_result"
    elif chain.get("coverage_status") == "GAPPED":
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = chain.get("gap_reason") or "target_settlement_gap"
        blocker_step = chain.get("blocker_step") or ""
        basis = "chain_gap"
    elif (
        target_date
        and own_dates
        and (coverage_mode != COVERAGE_OWN or corpus_dates)
    ):
        exact_target = all(value == target_date for value in own_dates)
        coverage_status = "COMPLETE" if exact_target else "GAPPED"
        target_included = exact_target
        gap_reason = "" if exact_target else "step_corpus_target_mismatch"
        blocker_step = "" if exact_target else (step.get("name") or "")
        basis = "step_corpus"
    elif incomplete_input_statuses:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "learning_input_gate_" + incomplete_input_statuses[0].lower()
        blocker_step = step.get("name") or ""
        basis = "step_input_gate"
    elif result_status in STEP_RESULT_INCOMPLETE_OVERRIDES.get(
        step.get("name"), frozenset()
    ):
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "learning_step_result_" + result_status.lower()
        blocker_step = step.get("name") or ""
        basis = "step_result"
    else:
        coverage_status = "UNKNOWN"
        target_included = None
        gap_reason = "step_has_no_target_dated_corpus"
        blocker_step = step.get("name") or ""
        basis = "step_corpus"

    staleness_days = None
    weakest_date = corpus_date_max or latest_settled_date
    if target_date and weakest_date:
        staleness_days = max(
            0,
            (
                date.fromisoformat(target_date)
                - date.fromisoformat(weakest_date)
            ).days,
        )
    return {
        "coverage_status": coverage_status,
        "coverage_mode": coverage_mode or "unknown",
        "coverage_basis": basis,
        "requested_target_date": target_date,
        "latest_settled_date": latest_settled_date,
        "corpus_date_max": corpus_date_max,
        "observed_corpus_dates": own_dates,
        "target_included": target_included,
        "staleness_days": staleness_days,
        "settlement_barrier_status": chain.get(
            "settlement_barrier_status", "NOT_RUN"
        ),
        "gap_reason": gap_reason,
        "blocker_step": blocker_step,
        "gap_recorded": coverage_status == "GAPPED",
    }


def dependency_target_settlement_coverage(args, step, steps, chain_coverage):
    """Propagate the weakest current-run receipt from named dependencies."""
    target_date = _date_text(
        getattr(args, "settled_analysis_target_date", "")
        or (chain_coverage or {}).get("requested_target_date")
    )
    dependency_rows = []
    for dependency_name in STEP_LEARNING_COVERAGE_DEPENDENCIES.get(
        step.get("name"), ()
    ):
        dependency = _latest_step_by_name(steps, dependency_name)
        if not dependency:
            dependency_rows.append(
                {
                    "step": dependency_name,
                    "coverage_status": "UNKNOWN",
                    "reason": "named_dependency_receipt_missing",
                }
            )
            continue
        result = dependency.get("result") or {}
        coverage = dict(result.get("target_settlement_coverage") or {})
        if not coverage or coverage.get("coverage_status") == "NOT_APPLICABLE":
            result_status = str(result.get("status") or "").upper()
            settled_dates, corpus_dates = _step_dates(
                result,
                coverage_mode=COVERAGE_DEPENDENCIES,
                step_name=dependency_name,
            )
            dates = sorted(set(settled_dates + corpus_dates))
            if (
                dependency.get("status") in TERMINAL_STEP_FAILURE_STATUSES
                or result.get("skipped") is True
                or result_status in LEARNING_COVERAGE_GAP_RESULT_STATUSES
                or result_status in {"BLOCK", "BLOCKED", "DEFERRED", "SKIPPED"}
            ):
                coverage_status = "GAPPED"
                reason = "named_dependency_not_usable"
            elif (chain_coverage or {}).get("coverage_status") == "GAPPED":
                coverage_status = "GAPPED"
                reason = (chain_coverage or {}).get("gap_reason") or "chain_gap"
            elif target_date and dates:
                coverage_status = (
                    "COMPLETE"
                    if all(value == target_date for value in dates)
                    else "GAPPED"
                )
                reason = (
                    "" if coverage_status == "COMPLETE"
                    else "named_dependency_target_mismatch"
                )
            else:
                coverage_status = "UNKNOWN"
                reason = "named_dependency_has_no_target_proof"
            weakest_date = min(corpus_dates or settled_dates) if dates else ""
            coverage = {
                "coverage_status": coverage_status,
                "corpus_date_max": min(corpus_dates) if corpus_dates else "",
                "latest_settled_date": (
                    max(settled_dates) if settled_dates else ""
                ),
                "staleness_days": (
                    max(
                        0,
                        (
                            date.fromisoformat(target_date)
                            - date.fromisoformat(weakest_date)
                        ).days,
                    )
                    if target_date and weakest_date
                    else None
                ),
                "reason": reason,
            }
        dependency_rows.append(
            {
                "step": dependency_name,
                "coverage_status": coverage.get("coverage_status") or "UNKNOWN",
                "corpus_date_max": coverage.get("corpus_date_max") or "",
                "latest_settled_date": coverage.get("latest_settled_date") or "",
                "staleness_days": coverage.get("staleness_days"),
                "reason": coverage.get("gap_reason") or coverage.get("reason") or "",
            }
        )

    statuses = {row["coverage_status"] for row in dependency_rows}
    current_result = step.get("result") or {}
    current_status = str(current_result.get("status") or "").upper()
    current_unusable = (
        step.get("status") in TERMINAL_STEP_FAILURE_STATUSES
        or current_result.get("skipped") is True
        or current_status in LEARNING_COVERAGE_GAP_RESULT_STATUSES | {"SKIPPED"}
    )
    if current_unusable:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "derived_step_not_usable"
    elif "GAPPED" in statuses:
        coverage_status = "GAPPED"
        target_included = False
        gap_reason = "named_dependency_coverage_gap"
    elif dependency_rows and statuses <= {"COMPLETE"}:
        coverage_status = "COMPLETE"
        target_included = True
        gap_reason = ""
    else:
        coverage_status = "UNKNOWN"
        target_included = None
        gap_reason = "named_dependency_coverage_unknown"
    corpus_dates = [
        row["corpus_date_max"]
        for row in dependency_rows
        if row.get("corpus_date_max")
    ]
    settled_dates = [
        row["latest_settled_date"]
        for row in dependency_rows
        if row.get("latest_settled_date")
    ]
    staleness = [
        row["staleness_days"]
        for row in dependency_rows
        if row.get("staleness_days") is not None
    ]
    blocker = next(
        (
            row["step"]
            for row in dependency_rows
            if row["coverage_status"] in {"GAPPED", "UNKNOWN"}
        ),
        "",
    )
    return {
        "coverage_status": coverage_status,
        "coverage_mode": COVERAGE_DEPENDENCIES,
        "coverage_basis": "named_dependencies",
        "requested_target_date": target_date,
        "latest_settled_date": min(settled_dates) if settled_dates else "",
        "corpus_date_max": min(corpus_dates) if corpus_dates else "",
        "observed_corpus_dates": sorted(set(corpus_dates + settled_dates)),
        "target_included": target_included,
        "staleness_days": max(staleness) if staleness else None,
        "settlement_barrier_status": (chain_coverage or {}).get(
            "settlement_barrier_status", "NOT_RUN"
        ),
        "gap_reason": gap_reason,
        "blocker_step": blocker,
        "gap_recorded": coverage_status == "GAPPED",
        "dependencies": dependency_rows,
    }


def annotate_step_lanes(args, steps):
    chain_coverage = chain_target_settlement_coverage(args, steps)
    for index, step in enumerate(steps or []):
        lane = step_lane(step.get("name"))
        if lane is None:
            continue
        step["lane"] = lane
        step["blocks_promotion"] = STEP_PROMOTION_GATES.get(
            step.get("name"), False
        )
        if (
            step.get("status") == "error"
            and step.get("name") not in STAGE_A_ISOLATED_STEPS
            and step.get("root_cause_class") != "stage_a_isolated_child"
        ):
            step.setdefault("contained_by_lane", True)
            if STEP_PROMOTION_GATES.get(step.get("name"), False):
                step.setdefault("lane_blocker", True)
        if lane == LANE_LEARNING and step.get("status") != "planned":
            result = step.get("result")
            if not isinstance(result, dict):
                result = {"value": result}
                step["result"] = result
            if (
                STEP_LEARNING_COVERAGE_MODES.get(step.get("name"))
                == COVERAGE_DEPENDENCIES
            ):
                result["target_settlement_coverage"] = (
                    dependency_target_settlement_coverage(
                        args,
                        step,
                        (steps or [])[:index],
                        chain_coverage,
                    )
                )
            else:
                result["target_settlement_coverage"] = (
                    step_target_settlement_coverage(args, step, chain_coverage)
                )
    return chain_coverage


def _learning_coverage_rollup(chain_coverage, learning_steps):
    coverages = [
        (step.get("result") or {}).get("target_settlement_coverage") or {}
        for step in learning_steps
        if step.get("status") != "planned"
        and ((step.get("result") or {}).get("target_settlement_coverage") or {}).get(
            "coverage_status"
        )
        != "NOT_APPLICABLE"
    ]
    counts = Counter(
        coverage.get("coverage_status") or "UNKNOWN" for coverage in coverages
    )
    gapped_steps = [
        step.get("name")
        for step in learning_steps
        if ((step.get("result") or {}).get("target_settlement_coverage") or {}).get(
            "coverage_status"
        )
        == "GAPPED"
    ]
    unknown_steps = [
        step.get("name")
        for step in learning_steps
        if ((step.get("result") or {}).get("target_settlement_coverage") or {}).get(
            "coverage_status"
        )
        == "UNKNOWN"
    ]
    rollup = dict(chain_coverage)
    if gapped_steps and rollup.get("coverage_status") != "GAPPED":
        rollup.update(
            {
                "coverage_status": "GAPPED",
                "coverage_basis": "learning_step_rollup",
                "target_included": False,
                "gap_reason": "learning_step_coverage_gap",
                "blocker_step": gapped_steps[0],
                "gap_recorded": True,
            }
        )
    elif unknown_steps and rollup.get("coverage_status") != "GAPPED":
        rollup.update(
            {
                "coverage_status": "UNKNOWN",
                "coverage_basis": "learning_step_rollup",
                "target_included": None,
                "gap_reason": "learning_step_coverage_unknown",
                "blocker_step": unknown_steps[0],
                "gap_recorded": False,
            }
        )
    settled_dates = sorted(
        {
            _date_text(coverage.get("latest_settled_date"))
            for coverage in coverages
            if _date_text(coverage.get("latest_settled_date"))
        }
    )
    corpus_dates = sorted(
        {
            _date_text(coverage.get("corpus_date_max"))
            for coverage in coverages
            if _date_text(coverage.get("corpus_date_max"))
        }
    )
    observed_dates = sorted(
        {
            parsed
            for coverage in coverages
            for value in coverage.get("observed_corpus_dates") or []
            if (parsed := _date_text(value))
        }
    )
    staleness = [
        coverage.get("staleness_days")
        for coverage in coverages
        if coverage.get("staleness_days") is not None
    ]
    rollup.update(
        {
            "latest_settled_date": (
                min(settled_dates) if settled_dates else ""
            ),
            "corpus_date_max": min(corpus_dates) if corpus_dates else "",
            "observed_corpus_dates": observed_dates,
            "staleness_days": max(staleness) if staleness else None,
        }
    )
    rollup["step_coverage_counts"] = dict(sorted(counts.items()))
    rollup["gapped_steps"] = gapped_steps
    rollup["unknown_steps"] = unknown_steps
    return rollup


def _learning_step_incomplete(step):
    if step.get("status") in TERMINAL_STEP_FAILURE_STATUSES:
        return True
    result = step.get("result") or {}
    if result.get("skipped") is True:
        return True
    if _input_gate_statuses(result) & LEARNING_INCOMPLETE_RESULT_STATUSES:
        return True
    result_status = str(result.get("status") or "").upper()
    if result_status in LEARNING_COVERAGE_GAP_RESULT_STATUSES | {"SKIPPED"}:
        return True
    if result_status in STEP_RESULT_INCOMPLETE_OVERRIDES.get(
        step.get("name"), frozenset()
    ):
        return True
    coverage = result.get("target_settlement_coverage") or {}
    return coverage.get("coverage_status") == "GAPPED"


def lane_summary(args, steps):
    chain_coverage = annotate_step_lanes(args, steps)
    promotion_blocker = promotion_lane_outcome_blocker(
        steps,
        target_date=getattr(args, "settled_analysis_target_date", ""),
    )
    barrier = _latest_step_by_name(steps, "settled_day_analysis_barrier")
    barrier_status = str(
        ((barrier.get("result") or {}).get("status") or "")
    ).upper()
    learning_steps = [
        step
        for step in steps or []
        if step_lane(step.get("name")) == LANE_LEARNING
    ]
    learning_incomplete = [
        step for step in learning_steps if _learning_step_incomplete(step)
    ]
    coverage = _learning_coverage_rollup(chain_coverage, learning_steps)
    if learning_steps and all(
        step.get("status") == "planned" for step in learning_steps
    ):
        learning_status = "PLANNED"
    elif not learning_steps:
        learning_status = "NOT_RUN"
    elif learning_incomplete or coverage.get("coverage_status") == "GAPPED":
        learning_status = "PARTIAL"
    elif coverage.get("coverage_status") == "UNKNOWN":
        learning_status = "UNKNOWN"
    elif all(
        step.get("status") not in {"planned", "running"}
        for step in learning_steps
    ):
        learning_status = "COMPLETE"
    else:
        learning_status = "RUNNING"
    promotion_steps = [
        step
        for step in steps or []
        if step_lane(step.get("name")) == LANE_PROMOTION
    ]
    if promotion_blocker:
        promotion_status = "BLOCKED"
    elif promotion_steps and all(
        step.get("status") == "planned" for step in promotion_steps
    ):
        promotion_status = "PLANNED"
    else:
        promotion_status = (
            "PASS" if barrier_status in {"PASS", "OK"} else "OPEN"
        )
    return {
        LANE_PROMOTION: {
            "status": promotion_status,
            "first_blocker": promotion_blocker,
        },
        LANE_LEARNING: {
            "status": learning_status,
            "step_count": len(learning_steps),
            "incomplete_step_count": len(learning_incomplete),
            "incomplete_steps": [
                step.get("name") for step in learning_incomplete
            ],
            "target_settlement_coverage": coverage,
        },
    }


def blocked_promotion_step(name, blocker, args):
    generated = utc_iso()
    return {
        "name": name,
        "lane": LANE_PROMOTION,
        "blocks_promotion": True,
        "lane_blocker": True,
        "contained_by_lane": True,
        "status": "blocked",
        "started_at_utc": generated,
        "finished_at_utc": generated,
        "duration_seconds": 0.0,
        "result": {
            "status": "BLOCK",
            "reason": "promotion_lane_blocked",
            "target_date": getattr(args, "settled_analysis_target_date", "") or "",
            "upstream_blocker": dict(blocker or {}),
            "promotion_not_run": name == "promotion_refresh",
            "hard_stop_lane": LANE_PROMOTION,
        },
    }


def deferred_heavy_step(name, preflight_step):
    generated = utc_iso()
    preflight_result = (preflight_step or {}).get("result") or {}
    lane = step_lane(name)
    return {
        "name": name,
        "lane": lane,
        "blocks_promotion": STEP_PROMOTION_GATES.get(name, False),
        "lane_blocker": STEP_PROMOTION_GATES.get(name, False),
        "contained_by_lane": lane == LANE_PROMOTION,
        "status": "deferred",
        "started_at_utc": generated,
        "finished_at_utc": generated,
        "duration_seconds": 0.0,
        "result": {
            "status": "DEFERRED",
            "reason": (preflight_step or {}).get("name")
            or "heavy_step_preflight",
            "preflight_status": preflight_result.get("status"),
            "preflight_decision": preflight_result.get("decision"),
            "proof_path": preflight_result.get("proof_path"),
            "hard_stop_lane": lane,
        },
    }
