"""Markdown rendering for daily log-learning reports."""

from __future__ import annotations

from datetime import datetime

from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


def _count_summary(counts):
    counts = counts or {}
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "-"

def _scorecard_rows(scorecard):
    labels = scorecard.get("labels") or {}
    corpus = scorecard.get("corpus") or {}
    candidate = scorecard.get("candidate") or {}
    promotion = scorecard.get("promotion") or {}
    early_hour_promotion = promotion.get("early_hour_promotion_blocker") or {}
    early_hour_current = early_hour_promotion.get("current_gates") or {}
    early_hour_candidate = early_hour_promotion.get("candidate_gates") or {}
    hourly = scorecard.get("hourly_model_performance") or {}
    hourly_gate = hourly.get("hourly_performance_gate") or {}
    hourly_daily = hourly.get("daily_summary") or {}
    early_hour_market_deltas = hourly.get("early_hour_market_deltas") or []
    early_hour_blocked_markets = [
        row for row in early_hour_market_deltas
        if row.get("status") == "BLOCK"
    ]
    ten_minute = scorecard.get("ten_minute_model_performance") or {}
    ten_minute_gate = ten_minute.get("ten_minute_performance_gate") or {}
    ten_minute_daily = ten_minute.get("daily_summary") or {}
    price_free = scorecard.get("price_free_model_learning") or {}
    price_free_daily = price_free.get("daily_summary") or {}
    price_free_carryover = (price_free.get("current_max_carryover") or {}).get("summary") or {}
    casebook = scorecard.get("casebook") or {}
    snapshot_eval = scorecard.get("snapshot_evaluation") or {}
    data_layer = scorecard.get("data_layer_audit") or {}
    sidecar_eligibility = data_layer.get("sidecar_eligibility") or {}
    root_cause = scorecard.get("settled_day_root_cause") or {}
    root_cause_summary = root_cause.get("summary") or {}
    core_trend = scorecard.get("core_model_trend_claim") or {}
    core_summary = core_trend.get("summary") or {}
    fleet = scorecard.get("fleet") or {}
    live_slo = fleet.get("live_forward_slo") or {}
    live_slo_summary = live_slo.get("summary") or {}
    current_soak = fleet.get("current_code_soak") or {}
    current_soak_summary = current_soak.get("summary") or {}
    source_status = fleet.get("source_status_proof") or {}
    source_status_summary = source_status.get("summary") or {}
    trading = scorecard.get("trading_evidence") or {}
    mm_trading = trading.get("market_making") or {}
    taker = trading.get("taker") or {}
    taker_quality = taker.get("quality_gate") or {}
    taker_finalization = scorecard.get("taker_finalization_watchdog") or {}
    taker_finalization_summary = taker_finalization.get("summary") or {}
    taker_tail = scorecard.get("taker_tail_casebook") or {}
    taker_tail_summary = taker_tail.get("summary") or {}
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
        [
            "Early-hour promotion blocker",
            (
                f"{early_hour_promotion.get('status') or '-'}; "
                f"allowed={early_hour_promotion.get('promotion_allowed')}; "
                f"blockers={early_hour_promotion.get('blocker_count', len(early_hour_promotion.get('blockers') or []))}; "
                f"current={((early_hour_current.get('hourly') or {}).get('status') or '-')}/"
                f"{((early_hour_current.get('ten_minute') or {}).get('status') or '-')}; "
                f"candidate={((early_hour_candidate.get('hourly') or {}).get('gate_status') or '-')}/"
                f"{((early_hour_candidate.get('ten_minute') or {}).get('gate_status') or '-')}"
            ),
        ],
        [
            "Hourly performance gate",
            (
                f"{hourly_gate.get('status') or '-'}; "
                f"worst={', '.join(hourly_daily.get('worst_hours') or []) or '-'}"
            ),
        ],
        [
            "10-minute performance gate",
            (
                f"{ten_minute_gate.get('status') or '-'}; "
                f"weak={', '.join(ten_minute_daily.get('weak_slots') or []) or '-'}"
            ),
        ],
        [
            "Early-hour market blockers",
            (
                f"blocked={len(early_hour_blocked_markets)}; "
                f"markets={', '.join(row.get('market_id') for row in early_hour_blocked_markets[:5] if row.get('market_id')) or '-'}"
            ),
        ],
        [
            "Price-free diagnostics",
            (
                f"{price_free.get('status') or '-'}; "
                f"days={price_free_daily.get('scored_market_days', 0)}; "
                f"rows={price_free_daily.get('hourly_checkpoint_rows', 0)}; "
                f"guarded={price_free_carryover.get('risky_or_guarded_count', 0)}"
            ),
        ],
        ["Casebook cases", casebook.get("case_count")],
        ["Model-losing cases", casebook.get("model_loss_count")],
        ["Snapshot evaluation", snapshot_eval.get("status")],
        ["Top gap slices", snapshot_eval.get("top_gap_count")],
        ["Sidecar eligibility mix", _count_summary(sidecar_eligibility.get("primary_label_counts"))],
        [
            "Root-cause explanation tape",
            (
                f"{root_cause.get('status') or '-'}; "
                f"snapshots={root_cause_summary.get('explanation_snapshot_count', 0)}; "
                f"coverage={fmt_num(root_cause_summary.get('explanation_coverage_rate'), 3)}"
            ),
        ],
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
            "Current-code soak",
            (
                f"{current_soak.get('status') or '-'}; "
                f"counts={current_soak.get('counts_toward_active_day')}; "
                f"restarts={current_soak_summary.get('restart_count', '-')}; "
                f"first={current_soak_summary.get('first_blocking_loop') or '-'}"
            ),
        ],
        [
            "Source status proof",
            (
                f"blocked={source_status_summary.get('source_status_blocked_market_count', '-')}; "
                f"live_trade_blocked={source_status_summary.get('live_trade_permission_blocked_market_count', '-')}; "
                f"top={source_status_summary.get('top_degraded_family') or '-'}"
            ),
        ],
        [
            "MM trading evidence",
            (
                f"mode={mm_trading.get('evidence_mode') or '-'}; "
                f"quotes={mm_trading.get('quote_rows', '-')}; "
                f"live_perm={mm_trading.get('live_trade_permission_rows', '-')}; "
                f"counts={mm_trading.get('counts_toward_live_forward_gate')}"
            ),
        ],
        [
            "Taker quality",
            (
                f"{taker_quality.get('status') or '-'}; "
                f"fills={taker.get('filled_orders', '-')}; "
                f"net_pnl={fmt_signed(taker.get('net_pnl_usdc'))}; "
                f"source={taker.get('pnl_source') or '-'}; "
                f"evidence={taker.get('pnl_evidence_status') or '-'}; "
                f"settled={taker.get('settled_order_count', '-')}/"
                f"{taker.get('unsettled_order_count', '-')}; "
                f"tail={taker.get('low_price_tail_fill_count', 0)} "
                f"({taker.get('tail_fill_quality_status') or '-'}); "
                f"root={taker.get('root_cause_class') or '-'}"
            ),
        ],
        [
            "Taker settlement finalization",
            (
                f"{taker_finalization.get('status') or '-'}; "
                f"runs={taker_finalization_summary.get('run_count', '-')}; "
                f"pending={taker_finalization_summary.get('pending_finalization_count', '-')}; "
                f"sla={taker_finalization_summary.get('sla_breach_count', '-')}; "
                f"champion={taker_finalization_summary.get('champion_decision') or '-'}"
            ),
        ],
        [
            "Taker tail casebook",
            (
                f"{taker_tail.get('status') or '-'}; "
                f"tail={taker_tail_summary.get('tail_fill_count', '-')}; "
                f"losing={taker_tail_summary.get('losing_tail_fill_count', '-')}; "
                f"no_go={taker_tail_summary.get('no_go_candidate_count', '-')}"
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


def _short_timestamp(value):
    if value in (None, ""):
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
        return f"{parsed:%H:%M}"
    except ValueError:
        return str(value)


def _format_gap_windows(windows, limit=2):
    rows = []
    for item in (windows or [])[:limit]:
        rows.append(
            f"{_short_timestamp(item.get('after'))}->{_short_timestamp(item.get('before'))} "
            f"({float(item.get('gap_minutes') or 0):.0f}m)"
        )
    if len(windows or []) > limit:
        rows.append("...")
    return "; ".join(rows) or "-"


def _format_source_family_detail(families, limit=2):
    rows = []
    for item in (families or [])[:limit]:
        bits = [
            f"{item.get('family')}:{item.get('status')}",
            f"fallback={item.get('fallback_source_count', 0)}",
            f"rate_limited={item.get('rate_limited_source_count', 0)}",
            f"cooldown={item.get('provider_cooldown_source_count', 0)}",
        ]
        if item.get("max_retry_after_seconds") is not None:
            bits.append(f"retry_after={item.get('max_retry_after_seconds')}s")
        if item.get("max_cache_age_minutes") is not None:
            bits.append(f"cache_age={item.get('max_cache_age_minutes')}m")
        rows.append(" ".join(bits))
    if len(families or []) > limit:
        rows.append("...")
    return "; ".join(rows) or "-"


def _snapshot_cadence_proof_rows(live_slo):
    proof = (live_slo or {}).get("snapshot_cadence_proof") or {}
    return [
        [
            row.get("market_id"),
            row.get("status"),
            ", ".join(row.get("blocking_gates") or []) or "-",
            row.get("snapshot_count"),
            row.get("gap_count"),
            row.get("max_gap_minutes"),
            row.get("root_cause"),
            row.get("recoverable_same_day"),
            _format_gap_windows(row.get("gap_windows") or []),
        ]
        for row in proof.get("markets") or []
    ]


def _source_status_proof_rows(source_status_proof):
    return [
        [
            row.get("market_id"),
            row.get("model_review_allowed"),
            row.get("paper_trading_allowed"),
            row.get("live_trade_permission_allowed"),
            row.get("promotion_readiness_allowed"),
            row.get("affected_family_count"),
            row.get("blocking_family_count"),
            row.get("provider_cooldown_source_count"),
            row.get("top_degraded_family") or "-",
            _format_source_family_detail(row.get("affected_families") or []),
        ]
        for row in (source_status_proof or {}).get("markets") or []
    ]


def _early_hour_market_delta_rows(rows):
    return [
        [
            row.get("market_id"),
            row.get("status"),
            ", ".join(row.get("blocking_gates") or []) or "-",
            row.get("n"),
            row.get("market_days"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_num(row.get("model_logloss")),
            fmt_num(row.get("market_logloss")),
            fmt_signed(row.get("logloss_delta")),
        ]
        for row in rows or []
    ]


def _current_code_soak_rows(soak):
    return [
        [
            row.get("name"),
            row.get("status"),
            row.get("state"),
            row.get("runtime_code_state"),
            row.get("single_writer"),
            row.get("restart_count"),
            row.get("restart_budget"),
            row.get("restart_budget_clears_at_utc") or "-",
            row.get("duplicate_writer_incidents"),
            row.get("diagnostic_duplicate_writer_incidents"),
            row.get("benign_duplicate_writer_blocks"),
            row.get("malformed_lines"),
            "; ".join(row.get("immediate_repair_commands") or []) or "-",
            "; ".join(row.get("blocking_reasons") or []) or "-",
        ]
        for row in (soak or {}).get("loops") or []
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
    early_hour_promotion = ((scorecard.get("promotion") or {}).get("early_hour_promotion_blocker") or {})
    if early_hour_promotion:
        current_gates = early_hour_promotion.get("current_gates") or {}
        candidate_gates = early_hour_promotion.get("candidate_gates") or {}
        broad_replay = early_hour_promotion.get("broad_replay") or {}
        production = early_hour_promotion.get("production_readiness") or {}
        lines += ["", "## Early-Hour Promotion Blocker", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", early_hour_promotion.get("status") or "-"],
                ["Promotion allowed", early_hour_promotion.get("promotion_allowed")],
                ["Blockers", early_hour_promotion.get("blocker_count", 0)],
                ["Current hourly gate", (current_gates.get("hourly") or {}).get("status") or "-"],
                ["Current 10-minute gate", (current_gates.get("ten_minute") or {}).get("status") or "-"],
                ["Candidate hourly gate", (candidate_gates.get("hourly") or {}).get("gate_status") or "-"],
                ["Candidate 10-minute gate", (candidate_gates.get("ten_minute") or {}).get("gate_status") or "-"],
                ["Broad replay within tolerance", broad_replay.get("within_market_tolerance")],
                ["Live-forward SLO", (production.get("live_forward_slo") or {}).get("status") or "-"],
                ["Current-code soak", (production.get("current_code_soak") or {}).get("status") or "-"],
            ],
        )
        blocker_rows = [
            [row.get("category"), row.get("severity"), row.get("detail")]
            for row in early_hour_promotion.get("blockers") or []
        ]
        if blocker_rows:
            lines += markdown_table(["Category", "Severity", "Detail"], blocker_rows[:8])
    rollup_freshness = scorecard.get("rollup_freshness") or {}
    if rollup_freshness:
        lines += [
            "",
            "## Daily Rollup Freshness",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", rollup_freshness.get("status") or "-"],
                ["Latest granular artifact", rollup_freshness.get("latest_required_artifact") or "-"],
                ["Latest granular timestamp", rollup_freshness.get("latest_required_timestamp_utc") or "-"],
                ["Blockers", rollup_freshness.get("blocker_count", 0)],
                ["Repair command", rollup_freshness.get("repair_command") or "-"],
            ],
        )
        if rollup_freshness.get("blockers"):
            lines += [
                "",
                "| Rollup | Status | Latest Granular Artifact | Rollup Timestamp | Granular Timestamp |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for blocker in rollup_freshness.get("blockers") or []:
                lines.append(
                    "| "
                    f"{blocker.get('rollup')} | "
                    f"{blocker.get('status')} | "
                    f"{blocker.get('latest_required_artifact') or '-'} | "
                    f"{blocker.get('rollup_timestamp_utc') or '-'} | "
                    f"{blocker.get('latest_required_timestamp_utc') or '-'} |"
                )
    early_hour_market_deltas = (
        (scorecard.get("hourly_model_performance") or {}).get("early_hour_market_deltas")
        or []
    )
    if early_hour_market_deltas:
        lines += ["", "## Early-Hour Market Deltas", ""]
        lines += markdown_table(
            [
                "Market",
                "Status",
                "Blocking Gates",
                "Rows",
                "Days",
                "Model Brier",
                "Market Brier",
                "Brier Delta",
                "Model LogLoss",
                "Market LogLoss",
                "LogLoss Delta",
            ],
            _early_hour_market_delta_rows(early_hour_market_deltas),
        )
    ten_minute = scorecard.get("ten_minute_model_performance") or {}
    ten_minute_gate = ten_minute.get("ten_minute_performance_gate") or {}
    if ten_minute_gate:
        ten_daily = ten_minute.get("daily_summary") or {}
        candidate_gate = ten_minute.get("candidate_ten_minute_gate") or {}
        first = ten_minute_gate.get("first_blocker") or {}
        lines += ["", "## 10-Minute Weak-Slot Gate", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", ten_minute_gate.get("status") or "-"],
                ["Weak slots", ", ".join(ten_daily.get("weak_slots") or []) or "-"],
                ["Worst slots", ", ".join(ten_daily.get("worst_slots") or []) or "-"],
                ["Candidate gate", candidate_gate.get("status") or "-"],
                ["First blocker", first.get("detail") or "-"],
            ],
        )
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
        cadence_proof = live_slo.get("snapshot_cadence_proof") or {}
        cadence_summary = cadence_proof.get("summary") or {}
        cadence_rows = _snapshot_cadence_proof_rows(live_slo)
        if cadence_proof:
            lines += ["", "Snapshot cadence proof:"]
            lines += markdown_table(
                ["Field", "Value"],
                [
                    ["Status", cadence_summary.get("status") or "-"],
                    [
                        "Snapshot coverage-gap blocked markets",
                        cadence_summary.get("snapshot_coverage_gap_blocked_market_count"),
                    ],
                    ["Total gaps", cadence_summary.get("total_gap_count")],
                    ["Max gap minutes", cadence_summary.get("max_gap_minutes")],
                    ["Recoverable same-day markets", cadence_summary.get("recoverable_same_day_market_count")],
                    [
                        "Nonrecoverable active-day blocked markets",
                        cadence_summary.get("nonrecoverable_active_day_blocked_market_count"),
                    ],
                    ["Clean active day required", cadence_summary.get("clean_active_day_required")],
                    ["Next unblock action", cadence_summary.get("next_unblock_action") or "-"],
                    ["Status command", cadence_proof.get("status_command") or "-"],
                    ["Repair command", cadence_proof.get("repair_command") or "-"],
                    ["Verification command", cadence_proof.get("verification_command") or "-"],
                ],
            )
            if cadence_rows:
                lines += markdown_table(
                    [
                        "Market", "Status", "Blocking Gates", "Snapshots", "Gaps",
                        "Max Gap min", "Root Cause", "Recoverable Same Day", "Gap Windows",
                    ],
                    cadence_rows,
                )
    current_soak = ((scorecard.get("fleet") or {}).get("current_code_soak") or {})
    if current_soak:
        soak_summary = current_soak.get("summary") or {}
        lines += ["", "## Current-Code Soak Proof", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", current_soak.get("status") or "-"],
                ["Counts toward active day", current_soak.get("counts_toward_active_day")],
                ["Restart count", soak_summary.get("restart_count")],
                ["First blocking loop", soak_summary.get("first_blocking_loop") or "-"],
                ["First blocking reason", soak_summary.get("first_blocking_reason") or "-"],
                ["Cadence SLO", current_soak.get("cadence_slo_status") or "-"],
                ["Immediate repair loops", soak_summary.get("immediate_repair_loop_count")],
                ["Aging blocker loops", soak_summary.get("aging_blocker_loop_count")],
                ["First immediate repair", soak_summary.get("first_immediate_repair_command") or "-"],
                ["Latest aging blocker clears", soak_summary.get("latest_aging_blocker_clears_at_utc") or "-"],
                ["Benign duplicate-writer blocks", soak_summary.get("benign_duplicate_writer_block_count")],
                ["Duplicate-writer incidents", soak_summary.get("duplicate_writer_incident_count")],
                ["7d duplicate-writer incidents", soak_summary.get("diagnostic_duplicate_writer_incident_count")],
            ],
        )
        lines += markdown_table(
            [
                "Loop", "Status", "State", "Code", "Single Writer", "Restarts",
                "Budget", "Restarts Clear At", "Dup Incidents", "7d Dup Incidents",
                "Benign Dup Blocks", "Malformed", "Immediate Repair", "Blocking Reasons",
            ],
            _current_code_soak_rows(current_soak),
        )
    trading = scorecard.get("trading_evidence") or {}
    if trading.get("market_making") or trading.get("taker"):
        mm_trading = trading.get("market_making") or {}
        taker = trading.get("taker") or {}
        taker_quality = taker.get("quality_gate") or {}
        taker_finalization = scorecard.get("taker_finalization_watchdog") or {}
        taker_finalization_summary = taker_finalization.get("summary") or {}
        taker_tail = scorecard.get("taker_tail_casebook") or {}
        taker_tail_summary = taker_tail.get("summary") or {}
        lines += ["", "## Trading Evidence", ""]
        lines += markdown_table(
            ["Area", "Value"],
            [
                ["MM run", mm_trading.get("run_id") or "-"],
                ["MM evidence mode", mm_trading.get("evidence_mode") or "-"],
                ["MM evidence reason", mm_trading.get("evidence_mode_reason") or "-"],
                ["MM countable", mm_trading.get("counts_toward_live_forward_gate")],
                ["MM quote rows", mm_trading.get("quote_rows")],
                ["MM paper-posted legs", mm_trading.get("paper_posted_lifecycle_legs")],
                ["MM live-trade permission rows", mm_trading.get("live_trade_permission_rows")],
                ["MM blockers", ", ".join(mm_trading.get("countability_blockers") or []) or "-"],
                ["Taker run", taker.get("run_id") or "-"],
                ["Taker fills", taker.get("filled_orders")],
                ["Taker net P&L", fmt_signed(taker.get("net_pnl_usdc"))],
                ["Taker P&L source", taker.get("pnl_source") or "-"],
                ["Taker P&L evidence", taker.get("pnl_evidence_status") or "-"],
                ["Taker settlement P&L", fmt_signed(taker.get("settlement_pnl_usdc"))],
                ["Taker mark-to-market P&L", fmt_signed(taker.get("mark_to_market_pnl_usdc"))],
                ["Taker settled / unsettled", f"{taker.get('settled_order_count')}/{taker.get('unsettled_order_count')}"],
                [
                    "Taker low-price tail fills",
                    f"{taker.get('low_price_tail_fill_count')} ({taker.get('tail_fill_quality_status') or '-'})",
                ],
                ["Taker MTM can promote", taker.get("mtm_promotion_allowed")],
                ["Taker reconciliation", taker.get("settlement_reconciliation_status") or "-"],
                [
                    "Taker reconciliation warnings",
                    ", ".join(
                        row.get("code") or str(row)
                        for row in taker.get("settlement_reconciliation_warnings") or []
                    ) or "-",
                ],
                ["Taker root cause", taker.get("root_cause_class") or "-"],
                ["Taker quality status", taker_quality.get("status") or "-"],
                ["Taker quality interpretation", taker_quality.get("interpretation") or "-"],
                ["Taker finalization status", taker_finalization.get("status") or "-"],
                ["Taker pending finalization", taker_finalization_summary.get("pending_finalization_count")],
                ["Taker finalization SLA breaches", taker_finalization_summary.get("sla_breach_count")],
                ["Taker champion decision", taker_finalization_summary.get("champion_decision") or "-"],
                ["Taker tail casebook", taker_tail.get("status") or "-"],
                ["Taker tail no-go candidates", taker_tail_summary.get("no_go_candidate_count")],
            ],
        )
    source_status_proof = ((scorecard.get("fleet") or {}).get("source_status_proof") or {})
    if source_status_proof:
        source_summary = source_status_proof.get("summary") or {}
        lines += ["", "## Source Status Proof", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Trading blocked markets", source_summary.get("source_status_blocked_market_count")],
                ["Live-trade blocked markets", source_summary.get("live_trade_permission_blocked_market_count")],
                ["Promotion blocked markets", source_summary.get("promotion_readiness_blocked_market_count")],
                ["Top degraded family", source_summary.get("top_degraded_family") or "-"],
                ["Provider-cooldown sources", source_summary.get("provider_cooldown_source_count")],
            ],
        )
        source_rows = _source_status_proof_rows(source_status_proof)
        if source_rows:
            lines += markdown_table(
                [
                    "Market", "Model Review", "Paper", "Live Trade", "Promotion",
                    "Affected", "Blocking", "Cooldown", "Top Family", "Family Detail",
                ],
                source_rows,
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

