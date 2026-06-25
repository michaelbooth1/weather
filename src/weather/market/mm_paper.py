"""Paper-trading scorer for market-making quote-intent runs.

The scorer is intentionally offline and evidence-first. Conservative fills are
only credited when recorded trade evidence proves a passive quote was traded
strictly through, with size evidence present. A queue-aware companion uses book
delta evidence to estimate fills/misses, but never replaces the conservative
gate used for promotion.

Ownership note: keep offline scoring orchestration here. Report rendering and
known-edge report formatting belong in ``weather.market.mm_paper_reports``.
Run eligibility and per-market evidence policy belong in
``weather.market.mm_paper_evidence``. Tape ingestion, conservative fill
accounting, queue simulation, and P&L scoring belong in
``weather.market.mm_paper_scoring``.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from weather.market.info_event_calendar import score_event_gate_decisions
from weather.market.clob_recon import (
    DEFAULT_JSON_OUT as DEFAULT_CLOB_RECON,
    build_recon_payload,
    load_recon_payload,
)
from weather.market import exchange_economics
from weather.market.mm_policy import bool_value, early_hour_guardrail_state, maybe_float, parse_time
from weather.market.mm_paper_evidence import (
    COMPATIBLE_RUN_SCHEMA_VERSIONS,
    LIVE_FORWARD_EVIDENCE_CLASSES,
    live_forward_gate_path_for_folder,
    per_market_evidence_credit_rows,
    run_folder_eligibility,
    split_run_folders_by_eligibility,
    summarize_per_market_evidence,
)
from weather.market.mm_paper_constants import (  # noqa: E402
    DEFAULT_BACKTEST_ROOT,
    DEFAULT_CASEBOOK,
    DEFAULT_CONFIG,
    DEFAULT_FILLS_OUT,
    DEFAULT_JSON_OUT,
    DEFAULT_KNOWN_EDGE_OUT,
    DEFAULT_KNOWN_EDGE_REPORT_OUT,
    DEFAULT_PROMOTION_REFRESH,
    DEFAULT_REPORT_OUT,
    DEFAULT_RUNS_ROOT,
    DEFAULT_SNAPSHOTS_ROOT,
    EARLY_HOUR_GUARDRAIL_SHADOW_SCHEMA_VERSION,
    FILL_COLUMNS,
    KNOWN_EDGE_SCHEMA_VERSION,
    MARKOUT_HORIZONS,
    SCHEMA_VERSION,
)

from weather.market.mm_paper_scoring import (  # noqa: E402
    ACTIVE_DAY_EVIDENCE_MODE,
    _path_mtime_iso,
    _run_folder_freshness_row,
    _run_freshness_sort_key,
    attach_expiry,
    attach_reward_estimates,
    band_distance_bucket,
    band_key,
    band_key_text,
    book_imbalance_bucket,
    casebook_for_fill,
    ci_bounds,
    clamp01,
    compact_float,
    compute_fill_financials,
    discover_run_folders,
    fee_equivalent,
    finite_float,
    generated_at_iso,
    group_by_token,
    hour_bucket,
    iso_or_blank,
    label_numbers,
    load_book_rows,
    load_casebook_index,
    load_mark_rows,
    load_model_variant_quote_rows,
    load_quote_rows,
    load_trade_rows,
    maker_paper_score_freshness,
    maker_paper_score_freshness_from_report,
    mark_at,
    mean,
    nearest_row_before,
    queue_ahead_for_leg,
    queue_simulate_leg,
    quote_id,
    quote_legs,
    quote_permission,
    read_csv_rows,
    read_json,
    read_jsonl,
    reward_leg_score,
    rows_between,
    settlement_for_folder,
    settlement_outcome_for_leg,
    simulate_conservative_fills,
    strict_trade_through,
    sum_field,
    summarize_pnl,
    utc_now,
    write_csv,
    write_json,
)

def _model_variant_pair_key(row):
    return (
        row.get("model_variant_id") or "served_current",
        row.get("policy_hash") or row.get("policy_id") or "",
    )


def _market_day_key(row):
    target_date = str(row.get("target_date") or "").strip()
    market_id = str(row.get("market_id") or "").strip()
    if not target_date or not market_id:
        return None
    return target_date, market_id


def _blank_model_variant_cluster(target_date, market_id):
    return {
        "target_date": target_date,
        "market_id": market_id,
        "quote_rows": 0,
        "quote_permission_rows": 0,
        "quote_legs": 0,
        "quoted_shares": 0.0,
        "conservative_fills": 0,
        "filled_shares": 0.0,
        "spread_capture_usdc": 0.0,
        "adverse_selection_30m_usdc": 0.0,
        "settlement_pnl_usdc": 0.0,
        "net_pnl_after_fees_incentives_usdc": 0.0,
        "queue_companion_legs": 0,
        "queue_estimated_fill_legs": 0,
        "queue_estimated_filled_shares": 0.0,
    }


def _cluster_for(clusters, row):
    key = _market_day_key(row)
    if key is None:
        return None
    return clusters[key]


def _cluster_rate(numerator, denominator):
    denominator = float(denominator or 0.0)
    if denominator <= 0:
        return 0.0
    return float(numerator or 0.0) / denominator


def _bootstrap_mean_ci(values, *, alpha=0.05, iterations=1000, seed_text=""):
    values = [float(value or 0.0) for value in values]
    n = len(values)
    total = sum(values)
    mean_value = total / n if n else None
    if not n:
        lower = None
        upper = None
    elif n == 1:
        lower = mean_value
        upper = mean_value
    else:
        digest = hashlib.sha1(seed_text.encode("utf-8")).hexdigest()
        rng = random.Random(int(digest[:16], 16))
        reps = max(100, int(iterations or 1000))
        means = []
        for _ in range(reps):
            means.append(sum(values[rng.randrange(n)] for _index in range(n)) / n)
        means.sort()
        lower_index = max(0, min(len(means) - 1, int(math.floor((float(alpha) / 2.0) * len(means)))))
        upper_index = max(
            0,
            min(len(means) - 1, int(math.ceil((1.0 - float(alpha) / 2.0) * len(means))) - 1),
        )
        lower = means[lower_index]
        upper = means[upper_index]
    return {
        "n": n,
        "total": compact_float(total),
        "mean": compact_float(mean_value),
        "mean_lower": compact_float(lower),
        "mean_upper": compact_float(upper),
        "total_lower": compact_float(lower * n if lower is not None else None),
        "total_upper": compact_float(upper * n if upper is not None else None),
        "alpha": compact_float(alpha, digits=8),
        "bootstrap_iterations": int(iterations or 0),
    }


def _cluster_metric_value(cluster, metric):
    if metric == "fill_rate":
        return _cluster_rate(cluster.get("conservative_fills"), cluster.get("quote_legs"))
    if metric == "queue_estimated_fill_quality":
        return _cluster_rate(cluster.get("queue_estimated_filled_shares"), cluster.get("quoted_shares"))
    return float(cluster.get(metric) or 0.0)


def _model_variant_claim_scope(status, market_count, all_market_min_markets):
    if status != "PASS":
        return "blocked_no_promotion_claim"
    if int(market_count or 0) >= int(all_market_min_markets or 0):
        return "all_market_evidence"
    if int(market_count or 0) == 1:
        return "market_specific_permission"
    return "live_pilot_readiness"


def _collect_model_variant_clusters(variant_quote_rows, variant_legs, variant_fill_rows, variant_queue_rows):
    clusters_by_pair = defaultdict(lambda: defaultdict(lambda: _blank_model_variant_cluster("", "")))
    leg_by_id = {}

    def get_cluster(pair_key, market_day_key):
        target_date, market_id = market_day_key
        cluster = clusters_by_pair[pair_key][market_day_key]
        cluster["target_date"] = target_date
        cluster["market_id"] = market_id
        return cluster

    for row in variant_quote_rows or []:
        market_day = _market_day_key(row)
        if market_day is None:
            continue
        cluster = get_cluster(_model_variant_pair_key(row), market_day)
        cluster["quote_rows"] += 1
        if quote_permission(row):
            cluster["quote_permission_rows"] += 1

    for leg in variant_legs or []:
        leg_by_id[leg.get("leg_id")] = leg
        market_day = _market_day_key(leg)
        if market_day is None:
            continue
        cluster = get_cluster(_model_variant_pair_key(leg), market_day)
        cluster["quote_legs"] += 1
        cluster["quoted_shares"] += finite_float(leg.get("quote_size"), 0.0) or 0.0

    for fill in variant_fill_rows or []:
        market_day = _market_day_key(fill)
        if market_day is None:
            continue
        cluster = get_cluster(_model_variant_pair_key(fill), market_day)
        cluster["conservative_fills"] += 1
        cluster["filled_shares"] += finite_float(fill.get("fill_size"), 0.0) or 0.0
        cluster["spread_capture_usdc"] += finite_float(fill.get("spread_capture_usdc"), 0.0) or 0.0
        cluster["adverse_selection_30m_usdc"] += finite_float(fill.get("adverse_selection_30m_usdc"), 0.0) or 0.0
        cluster["settlement_pnl_usdc"] += finite_float(fill.get("settlement_pnl_usdc"), 0.0) or 0.0
        cluster["net_pnl_after_fees_incentives_usdc"] += (
            finite_float(fill.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0
        )

    for queue in variant_queue_rows or []:
        leg = leg_by_id.get(queue.get("leg_id")) or queue
        market_day = _market_day_key(leg)
        if market_day is None:
            continue
        cluster = get_cluster(_model_variant_pair_key(leg), market_day)
        estimated = finite_float(queue.get("estimated_fill_size"), 0.0) or 0.0
        cluster["queue_companion_legs"] += 1
        if estimated > 0:
            cluster["queue_estimated_fill_legs"] += 1
        cluster["queue_estimated_filled_shares"] += estimated

    return {
        key: {
            cluster_key: {
                **cluster,
                "quoted_shares": compact_float(cluster.get("quoted_shares")),
                "filled_shares": compact_float(cluster.get("filled_shares")),
                "spread_capture_usdc": compact_float(cluster.get("spread_capture_usdc")),
                "adverse_selection_30m_usdc": compact_float(cluster.get("adverse_selection_30m_usdc")),
                "settlement_pnl_usdc": compact_float(cluster.get("settlement_pnl_usdc")),
                "net_pnl_after_fees_incentives_usdc": compact_float(
                    cluster.get("net_pnl_after_fees_incentives_usdc")
                ),
                "queue_estimated_filled_shares": compact_float(cluster.get("queue_estimated_filled_shares")),
            }
            for cluster_key, cluster in pair_clusters.items()
        }
        for key, pair_clusters in clusters_by_pair.items()
    }


def model_variant_clustered_promotion_gate(
    variant_quote_rows,
    variant_legs,
    variant_fill_rows,
    variant_queue_rows,
    *,
    config=None,
):
    config = {**DEFAULT_CONFIG, **(config or {})}
    alpha = float(config.get("model_variant_promotion_alpha", 0.05))
    iterations = int(config.get("model_variant_promotion_bootstrap_iterations", 1000))
    min_clusters = int(config.get("model_variant_promotion_min_market_day_clusters", 10))
    min_target_days = int(config.get("model_variant_promotion_min_target_days", 3))
    min_markets = int(config.get("model_variant_promotion_min_markets", 3))
    all_market_min_markets = int(config.get("model_variant_promotion_all_market_min_markets", 10))
    clusters_by_pair = _collect_model_variant_clusters(
        variant_quote_rows,
        variant_legs,
        variant_fill_rows,
        variant_queue_rows,
    )
    served_by_policy = {
        policy_id: clusters
        for (variant_id, policy_id), clusters in clusters_by_pair.items()
        if variant_id == "served_current"
    }
    comparison_keys = [
        key for key in clusters_by_pair
        if key[0] != "served_current"
    ]
    comparison_count = len(comparison_keys)
    adjusted_alpha = alpha / comparison_count if comparison_count else alpha
    metrics = [
        "net_pnl_after_fees_incentives_usdc",
        "adverse_selection_30m_usdc",
        "settlement_pnl_usdc",
        "fill_rate",
        "queue_estimated_fill_quality",
    ]
    rows = []
    for (variant_id, policy_id), clusters in sorted(clusters_by_pair.items()):
        cluster_rows = [clusters[key] for key in sorted(clusters)]
        target_days = {row.get("target_date") for row in cluster_rows if row.get("target_date")}
        markets = {row.get("market_id") for row in cluster_rows if row.get("market_id")}
        metric_stats = {
            metric: _bootstrap_mean_ci(
                [_cluster_metric_value(row, metric) for row in cluster_rows],
                alpha=adjusted_alpha,
                iterations=iterations,
                seed_text=f"maker-model-variant|{variant_id}|{policy_id}|{metric}",
            )
            for metric in metrics
        }
        served_clusters = served_by_policy.get(policy_id) or {}
        paired_keys = sorted(set(clusters) | set(served_clusters))
        delta_stats = {}
        if variant_id != "served_current":
            for metric in metrics:
                deltas = []
                for key in paired_keys:
                    candidate_cluster = clusters.get(key) or _blank_model_variant_cluster(key[0], key[1])
                    served_cluster = served_clusters.get(key) or _blank_model_variant_cluster(key[0], key[1])
                    deltas.append(
                        _cluster_metric_value(candidate_cluster, metric)
                        - _cluster_metric_value(served_cluster, metric)
                    )
                delta_stats[metric] = _bootstrap_mean_ci(
                    deltas,
                    alpha=adjusted_alpha,
                    iterations=iterations,
                    seed_text=f"maker-model-variant-delta|{variant_id}|{policy_id}|{metric}",
                )
        failed = []
        status = "CONTROL" if variant_id == "served_current" else "PASS"
        if variant_id != "served_current":
            paired_target_days = {key[0] for key in paired_keys if key[0]}
            paired_markets = {key[1] for key in paired_keys if key[1]}
            if not served_clusters:
                failed.append("served_current_baseline_required")
            if len(paired_keys) < min_clusters:
                failed.append("min_market_day_clusters")
            if len(paired_target_days) < min_target_days:
                failed.append("min_independent_target_days")
            if len(paired_markets) < min_markets:
                failed.append("min_independent_markets")
            net_lower = (
                delta_stats.get("net_pnl_after_fees_incentives_usdc") or {}
            ).get("mean_lower")
            if (finite_float(net_lower, 0.0) or 0.0) <= 0:
                failed.append("positive_delta_net_pnl_lower_bound")
            status = "BLOCK" if failed else "PASS"
            target_days = paired_target_days
            markets = paired_markets
        row = {
            "model_variant_id": variant_id,
            "policy_id": policy_id,
            "status": status,
            "failed_gates": failed,
            "claim_scope": _model_variant_claim_scope(status, len(markets), all_market_min_markets),
            "cluster_key": "target_date,market_id",
            "cluster_count": len(paired_keys) if variant_id != "served_current" else len(cluster_rows),
            "independent_target_day_count": len(target_days),
            "independent_market_count": len(markets),
            "quote_rows": sum(int(row.get("quote_rows") or 0) for row in cluster_rows),
            "quote_permission_rows": sum(int(row.get("quote_permission_rows") or 0) for row in cluster_rows),
            "quote_legs": sum(int(row.get("quote_legs") or 0) for row in cluster_rows),
            "conservative_fills": sum(int(row.get("conservative_fills") or 0) for row in cluster_rows),
            "filled_shares": compact_float(sum(finite_float(row.get("filled_shares"), 0.0) or 0.0 for row in cluster_rows)),
            "queue_estimated_fill_legs": sum(
                int(row.get("queue_estimated_fill_legs") or 0) for row in cluster_rows
            ),
            "queue_estimated_filled_shares": compact_float(
                sum(finite_float(row.get("queue_estimated_filled_shares"), 0.0) or 0.0 for row in cluster_rows)
            ),
            "cluster_metrics": metric_stats,
            "delta_vs_served_current_cluster_metrics": delta_stats,
            "clusters": cluster_rows,
        }
        rows.append(row)
    pass_rows = [row for row in rows if row.get("status") == "PASS"]
    return {
        "schema_version": "mm_model_variant_clustered_promotion_gate_v0.1",
        "status": "PASS" if pass_rows else "BLOCK",
        "method": "clustered_market_day_bootstrap",
        "score_basis": "paired_market_day_delta_vs_served_current",
        "cluster_key": "target_date,market_id",
        "alpha": compact_float(alpha, digits=8),
        "multiple_testing_method": "bonferroni_pre_registered_model_variant_policy_pairs",
        "comparison_count": comparison_count,
        "adjusted_alpha": compact_float(adjusted_alpha, digits=8),
        "bootstrap_iterations": iterations,
        "min_market_day_clusters": min_clusters,
        "min_independent_target_days": min_target_days,
        "min_independent_markets": min_markets,
        "all_market_min_markets": all_market_min_markets,
        "pass_pair_count": len(pass_rows),
        "pair_count": len(rows),
        "pairs": rows,
    }


def _quote_row_size(row):
    if not quote_permission(row):
        return 0.0
    return (
        (finite_float(row.get("bid_size"), 0.0) or 0.0)
        + (finite_float(row.get("ask_size"), 0.0) or 0.0)
    )


def _guardrail_variant_multipliers(row, config):
    state = early_hour_guardrail_state(row, config=config, now=row.get("quote_time_utc") or row.get("generated_at_utc"))
    active = state.get("early_hour_guardrail_status") == "active"
    capped_multiplier = float(state.get("early_hour_guardrail_size_multiplier") or 1.0) if active else 1.0
    overlay_edge = state.get("market_aware_overlay_edge")
    min_edge = state.get("early_hour_guardrail_min_edge")
    market_aware_standdown = (
        active
        and overlay_edge is not None
        and min_edge is not None
        and abs(float(overlay_edge)) < float(min_edge)
    )
    market_aware_multiplier = 0.0 if market_aware_standdown else capped_multiplier
    return state, capped_multiplier, market_aware_multiplier, market_aware_standdown


def _scaled(value, multiplier):
    number = finite_float(value)
    if number is None:
        return None
    return number * float(multiplier)


def _sum_non_null(values):
    return sum(float(value) for value in values if value is not None and math.isfinite(float(value)))


def _loss_usdc(values):
    return -sum(min(0.0, float(value)) for value in values if value is not None and math.isfinite(float(value)))


def _guardrail_quote_exposure(quote_rows, config):
    exposure = {
        "quote_rows": len(quote_rows),
        "quote_permission_rows": 0,
        "early_hour_quote_rows": 0,
        "early_hour_active_guardrail_rows": 0,
        "early_hour_override_rows": 0,
        "market_aware_standdown_rows": 0,
        "base_quote_size": 0.0,
        "early_hour_base_quote_size": 0.0,
        "early_hour_capped_quote_size": 0.0,
        "market_aware_guardrail_quote_size": 0.0,
        "live_forward_early_hour_quote_rows": 0,
    }
    for row in quote_rows:
        size = _quote_row_size(row)
        if size <= 0.0:
            continue
        state, capped_multiplier, market_multiplier, standdown = _guardrail_variant_multipliers(row, config)
        exposure["quote_permission_rows"] += 1
        exposure["base_quote_size"] += size
        if state.get("hourly_trust_band") == "early_00_08":
            exposure["early_hour_quote_rows"] += 1
            exposure["early_hour_base_quote_size"] += size
            exposure["early_hour_capped_quote_size"] += size * capped_multiplier
            exposure["market_aware_guardrail_quote_size"] += size * market_multiplier
            if str(row.get("run_mode") or (row.get("_run_config") or {}).get("mode") or "") == "paper-live-forward":
                exposure["live_forward_early_hour_quote_rows"] += 1
        if state.get("early_hour_guardrail_status") == "active":
            exposure["early_hour_active_guardrail_rows"] += 1
        if state.get("early_hour_guardrail_status") == "override_allowed":
            exposure["early_hour_override_rows"] += 1
        if standdown:
            exposure["market_aware_standdown_rows"] += 1
    return {
        key: compact_float(value) if isinstance(value, float) else value
        for key, value in exposure.items()
    }


def build_early_hour_guardrail_shadow(fill_rows, quote_rows=None, config=None):
    config = {**DEFAULT_CONFIG, **(config or {})}
    rows = []
    base_nets = []
    capped_nets = []
    market_nets = []
    early_base_nets = []
    early_capped_nets = []
    early_market_nets = []
    settlement_rows = 0
    live_forward_rows = 0
    for row in fill_rows:
        state, capped_multiplier, market_multiplier, standdown = _guardrail_variant_multipliers(row, config)
        base_net = finite_float(row.get("net_pnl_after_fees_incentives_usdc"))
        capped_net = _scaled(base_net, capped_multiplier)
        market_net = _scaled(base_net, market_multiplier)
        base_settlement = finite_float(row.get("settlement_pnl_usdc"))
        markout_30m = finite_float(row.get("markout_30m_per_share"))
        fill_size = finite_float(row.get("fill_size"), 0.0) or 0.0
        markout_30m_usdc = markout_30m * fill_size if markout_30m is not None else None
        base_nets.append(base_net)
        capped_nets.append(capped_net)
        market_nets.append(market_net)
        is_early = state.get("hourly_trust_band") == "early_00_08"
        if is_early:
            early_base_nets.append(base_net)
            early_capped_nets.append(capped_net)
            early_market_nets.append(market_net)
        if base_settlement is not None:
            settlement_rows += 1
        if str(row.get("run_mode") or "") == "paper-live-forward":
            live_forward_rows += 1
        rows.append({
            "quote_id": row.get("quote_id"),
            "leg_id": row.get("leg_id"),
            "run_mode": row.get("run_mode"),
            "market_id": row.get("market_id"),
            "target_date": row.get("target_date"),
            "hourly_trust_band": state.get("hourly_trust_band"),
            "early_hour_guardrail_status": state.get("early_hour_guardrail_status"),
            "early_hour_guardrail_reason": state.get("early_hour_guardrail_reason"),
            "early_hour_guardrail_size_multiplier": compact_float(capped_multiplier),
            "market_aware_standdown": standdown,
            "market_aware_overlay_probability": compact_float(state.get("market_aware_overlay_probability")),
            "market_aware_overlay_edge": compact_float(state.get("market_aware_overlay_edge")),
            "base_net_pnl_usdc": compact_float(base_net),
            "early_hour_capped_net_pnl_usdc": compact_float(capped_net),
            "market_aware_guardrail_net_pnl_usdc": compact_float(market_net),
            "base_settlement_pnl_usdc": compact_float(base_settlement),
            "base_markout_30m_usdc": compact_float(markout_30m_usdc),
        })

    quote_exposure = _guardrail_quote_exposure(quote_rows or [], config)
    base_net_sum = _sum_non_null(base_nets)
    capped_net_sum = _sum_non_null(capped_nets)
    market_net_sum = _sum_non_null(market_nets)
    early_base_net_sum = _sum_non_null(early_base_nets)
    early_capped_net_sum = _sum_non_null(early_capped_nets)
    early_market_net_sum = _sum_non_null(early_market_nets)
    status = "NO_FILL_EVIDENCE"
    if rows:
        if not early_base_nets:
            status = "NO_EARLY_HOUR_FILLS"
        elif early_market_net_sum > early_base_net_sum:
            status = "REDUCED_EARLY_HOUR_LOSS"
        elif early_capped_net_sum > early_base_net_sum:
            status = "CAPPED_POLICY_REDUCED_EARLY_HOUR_LOSS"
        else:
            status = "NEEDS_MORE_MARKOUT_EVIDENCE"
    summary = {
        "status": status,
        "fill_rows": len(rows),
        "early_hour_fill_rows": len(early_base_nets),
        "settlement_fill_rows": settlement_rows,
        "live_forward_fill_rows": live_forward_rows,
        "base_net_pnl_usdc": compact_float(base_net_sum),
        "capped_policy_net_pnl_usdc": compact_float(capped_net_sum),
        "market_aware_guardrail_net_pnl_usdc": compact_float(market_net_sum),
        "early_hour_base_net_pnl_usdc": compact_float(early_base_net_sum),
        "early_hour_capped_net_pnl_usdc": compact_float(early_capped_net_sum),
        "early_hour_market_aware_net_pnl_usdc": compact_float(early_market_net_sum),
        "early_hour_capped_delta_vs_base_usdc": compact_float(early_capped_net_sum - early_base_net_sum),
        "early_hour_market_aware_delta_vs_base_usdc": compact_float(early_market_net_sum - early_base_net_sum),
        "early_hour_base_loss_usdc": compact_float(_loss_usdc(early_base_nets)),
        "early_hour_capped_loss_usdc": compact_float(_loss_usdc(early_capped_nets)),
        "early_hour_market_aware_loss_usdc": compact_float(_loss_usdc(early_market_nets)),
        "market_overlay_is_risk_only": True,
        "no_market_probability_preserved": True,
        "quote_exposure": quote_exposure,
    }
    return {
        "schema_version": EARLY_HOUR_GUARDRAIL_SHADOW_SCHEMA_VERSION,
        "summary": summary,
        "rows": rows,
    }


def slice_key(row):
    return (
        row.get("market_id") or "unknown",
        hour_bucket(row.get("fill_time_utc")),
        row.get("band_distance_bucket") or "unknown",
        row.get("bin_kind") or "unknown",
        row.get("regime") or "unknown",
        str(row.get("source_fresh")),
        row.get("source_freshness_state") or "unknown",
        row.get("book_imbalance_bucket") or "unknown",
        row.get("casebook_taxonomy") or "unmatched",
    )


def build_markout_slices(fill_rows, config):
    grouped = defaultdict(list)
    for row in fill_rows:
        grouped[slice_key(row)].append(row)
    z = float(config["confidence_z"])
    adjustment_count = max(1, len(grouped))
    slices = []
    for key, rows in grouped.items():
        values_30m = [finite_float(row.get("markout_30m_per_share")) for row in rows]
        ci_low, ci_high = ci_bounds(values_30m, z=z)
        settlement_values = [finite_float(row.get("settlement_markout_per_share")) for row in rows]
        set_low, set_high = ci_bounds(settlement_values, z=z)
        market_id, hour, band_distance, band_type, regime, source_fresh, source_freshness_state, imbalance, taxonomy = key
        slices.append({
            "market_id": market_id,
            "hour_utc": hour,
            "band_distance_bucket": band_distance,
            "band_type": band_type,
            "regime": regime,
            "source_fresh": source_fresh,
            "source_freshness_state": source_freshness_state,
            "book_imbalance_bucket": imbalance,
            "casebook_taxonomy": taxonomy,
            "fill_count": len(rows),
            "share_count": compact_float(sum_field(rows, "fill_size")),
            "mean_markout_30m_per_share": compact_float(mean(values_30m)),
            "markout_30m_ci_low": compact_float(ci_low),
            "markout_30m_ci_high": compact_float(ci_high),
            "mean_settlement_markout_per_share": compact_float(mean(settlement_values)),
            "settlement_markout_ci_low": compact_float(set_low),
            "settlement_markout_ci_high": compact_float(set_high),
            "net_pnl_after_fees_incentives_usdc": compact_float(sum_field(rows, "net_pnl_after_fees_incentives_usdc")),
            "settlement_pnl_usdc": compact_float(sum_field(rows, "settlement_pnl_usdc")),
            "multiple_test_adjustment": "bonferroni_conservative",
            "multiple_test_family_size": adjustment_count,
            "deflated_markout_30m_per_share": compact_float(ci_low),
            "example_fill_ids": [row.get("fill_id") for row in rows[:5]],
        })
    slices.sort(key=lambda row: (row["market_id"], row["hour_utc"], row["band_distance_bucket"], row["casebook_taxonomy"]))
    return slices


def anti_overfit_summary(quote_rows, run_configs):
    run_days = sorted({row.get("target_date") for row in quote_rows if row.get("target_date")})
    policy_hashes = sorted({row.get("policy_hash") for row in quote_rows if row.get("policy_hash")})
    modes = Counter(row.get("run_mode") or (row.get("_run_config") or {}).get("mode") or "unknown" for row in quote_rows)
    split = max(1, int(math.ceil(len(run_days) * 0.7))) if run_days else 0
    return {
        "frozen_replay_days": run_days[:split],
        "heldout_validation_days": run_days[split:],
        "live_forward_days": [
            day for day in run_days
            if any(
                (
                    row.get("target_date") == day
                    and (row.get("run_mode") or (row.get("_run_config") or {}).get("mode")) == "paper-live-forward"
                    and bool_value(row.get("_run_live_forward_gate_counts"), True)
                )
                for row in quote_rows
            )
        ],
        "run_count": len(run_configs),
        "run_modes": dict(sorted(modes.items())),
        "policy_hashes": policy_hashes,
        "locked_policy_params": len(policy_hashes) == 1 if policy_hashes else False,
        "confidence_interval_method": "normal_approximation_by_slice",
        "multiple_test_adjustment": "bonferroni_conservative_ci_floor",
    }


def quote_uptime_summary(quote_rows, legs):
    quoted_ids = {leg["quote_id"] for leg in legs}
    no_quote_reasons = Counter(row.get("reason_code") or "unknown" for row in quote_rows if row["_quote_id"] not in quoted_ids)
    quote_times = [parse_time(row.get("generated_at_utc")) for row in quote_rows]
    quote_times = [ts for ts in quote_times if ts is not None]
    uptime = len(quoted_ids) / len(quote_rows) if quote_rows else 0.0
    return {
        "quote_rows": len(quote_rows),
        "quote_permission_rows": len(quoted_ids),
        "quote_uptime_fraction": compact_float(uptime),
        "first_quote_time_utc": min(quote_times).isoformat() if quote_times else None,
        "last_quote_time_utc": max(quote_times).isoformat() if quote_times else None,
        "stale_input_pulls": no_quote_reasons.get("NO_QUOTE_STALE_INPUT", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_BOOK", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_MODEL", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_WATCHER", 0),
        "no_quote_reason_counts": dict(sorted(no_quote_reasons.items())),
    }


def model_variant_paper_bakeoff_summary(
    variant_quote_rows,
    variant_legs,
    variant_fill_rows,
    variant_queue_rows,
    *,
    config=None,
):
    quote_groups = defaultdict(list)
    leg_groups = defaultdict(list)
    fill_groups = defaultdict(list)
    queue_by_leg_id = {row.get("leg_id"): row for row in variant_queue_rows or []}
    for row in variant_quote_rows or []:
        key = (row.get("model_variant_id") or "unknown", row.get("policy_hash") or "")
        quote_groups[key].append(row)
    for leg in variant_legs or []:
        key = (leg.get("model_variant_id") or "unknown", leg.get("policy_hash") or "")
        leg_groups[key].append(leg)
    for fill in variant_fill_rows or []:
        key = (fill.get("model_variant_id") or "unknown", fill.get("policy_hash") or "")
        fill_groups[key].append(fill)
    rows = []
    all_keys = sorted(set(quote_groups) | set(leg_groups) | set(fill_groups))
    for key in all_keys:
        variant_id, policy_id = key
        quotes = quote_groups.get(key, [])
        legs = leg_groups.get(key, [])
        fills = fill_groups.get(key, [])
        queue_rows = [
            queue_by_leg_id.get(leg.get("leg_id")) or {}
            for leg in legs
            if queue_by_leg_id.get(leg.get("leg_id"))
        ]
        quote_permission_rows = sum(1 for row in quotes if quote_permission(row))
        pnl = summarize_pnl(fills)
        row = {
            "model_variant_id": variant_id,
            "model_variant_family": (
                (quotes[0].get("model_variant_family") if quotes else None)
                or (legs[0].get("model_variant_family") if legs else None)
                or (fills[0].get("model_variant_family") if fills else None)
                or ""
            ),
            "model_variant_role": (
                (quotes[0].get("model_variant_role") if quotes else None)
                or (legs[0].get("model_variant_role") if legs else None)
                or (fills[0].get("model_variant_role") if fills else None)
                or ""
            ),
            "policy_id": policy_id,
            "quote_rows": len(quotes),
            "quote_permission_rows": quote_permission_rows,
            "quote_permission_rate": compact_float(quote_permission_rows / len(quotes)) if quotes else 0.0,
            "quote_legs": len(legs),
            "conservative_fills": len(fills),
            "queue_estimated_fill_legs": sum(
                1 for row in queue_rows
                if (finite_float(row.get("estimated_fill_size"), 0.0) or 0.0) > 0
            ),
            "net_pnl_after_fees_incentives_usdc": pnl.get("net_pnl_after_fees_incentives_usdc"),
            "settlement_pnl_usdc": pnl.get("settlement_pnl_usdc"),
            "spread_capture_usdc": pnl.get("spread_capture_usdc"),
            "adverse_selection_30m_usdc": pnl.get("adverse_selection_30m_usdc"),
        }
        rows.append(row)
    served_by_policy = {
        row["policy_id"]: row
        for row in rows
        if row.get("model_variant_id") == "served_current"
    }
    for row in rows:
        served = served_by_policy.get(row["policy_id"])
        row["delta_net_pnl_vs_served_current_usdc"] = (
            compact_float(
                (finite_float(row.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0)
                - (finite_float(served.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0)
            )
            if served and row.get("model_variant_id") != "served_current"
            else 0.0
        )
        row["delta_conservative_fills_vs_served_current"] = (
            int(row.get("conservative_fills") or 0) - int(served.get("conservative_fills") or 0)
            if served and row.get("model_variant_id") != "served_current"
            else 0
        )
    promotion_gate = model_variant_clustered_promotion_gate(
        variant_quote_rows,
        variant_legs,
        variant_fill_rows,
        variant_queue_rows,
        config=config,
    )
    return {
        "schema_version": "mm_model_variant_paper_bakeoff_v0.1",
        "status": "PASS" if rows else "NO_VARIANT_ROWS",
        "score_basis": "conservative_fill_markout_settlement_counterfactual",
        "quote_rows": len(variant_quote_rows or []),
        "quote_legs": len(variant_legs or []),
        "conservative_fills": len(variant_fill_rows or []),
        "queue_estimated_fill_legs": sum(
            1 for row in variant_queue_rows or []
            if (finite_float(row.get("estimated_fill_size"), 0.0) or 0.0) > 0
        ),
        "policy_pair_count": len(rows),
        "model_variant_by_policy": rows,
        "clustered_promotion_gate": promotion_gate,
        "promotion_gate": promotion_gate,
    }


def decisive_resting_check(legs, diagnostics):
    unresolved = []
    for leg in legs:
        event_diag = diagnostics.get(leg["event_slug"]) or {}
        if event_diag.get("settlement_available") and leg["quote_expires_at"] > leg["quote_time"]:
            continue
        if not event_diag.get("settlement_available"):
            unresolved.append({
                "leg_id": leg["leg_id"],
                "event_slug": leg["event_slug"],
                "market_id": leg["market_id"],
                "reason": "settlement_missing_for_resting_quote_audit",
            })
    return {
        "unresolved_resting_quote_count": len(unresolved),
        "unresolved_resting_quotes": unresolved[:50],
    }


def _clob_recon_has_coverage(payload):
    summary = (payload or {}).get("summary") or {}
    return int(summary.get("book_rows") or 0) > 0 and int(summary.get("slice_rows") or 0) > 0


def load_or_build_clob_recon(clob_recon_path, snapshots_root, event_slugs, now=None):
    payload = load_recon_payload(clob_recon_path)
    if _clob_recon_has_coverage(payload):
        payload["coverage_source"] = "precomputed_clob_recon"
        return payload
    folders = [
        Path(snapshots_root) / slug
        for slug in sorted({str(item) for item in event_slugs or [] if item})
        if (Path(snapshots_root) / slug / "order_books_summary.csv").exists()
    ]
    if not folders:
        payload["coverage_source"] = "missing_precomputed_recon_no_active_book_folders"
        return payload
    try:
        built = build_recon_payload(snapshots_root=snapshots_root, folders=folders, now=now)
    except Exception as exc:  # noqa: BLE001 - paper scoring should still report fill evidence blockers
        payload["coverage_source"] = "auto_recon_failed"
        payload["auto_recon_error"] = f"{type(exc).__name__}: {exc}"
        return payload
    built["coverage_source"] = "auto_built_from_active_maker_snapshot_folders"
    built["precomputed_recon_path"] = str(clob_recon_path)
    built["auto_recon_folder_count"] = len(folders)
    return built


def fill_evidence_completeness_summary(legs, fill_rows, queue_rows, diagnostics, decisive_resting, clob_recon, config):
    config = {**DEFAULT_CONFIG, **(config or {})}
    queue_by_leg = {row.get("leg_id"): row for row in queue_rows or []}
    queue_counts = Counter(row.get("status") or "unknown" for row in queue_rows or [])
    missing_size_trade_rows = sum(int(row.get("missing_size_trade_rows") or 0) for row in diagnostics.values())
    missing_book_queue_legs = queue_counts.get("missing_book", 0)
    missing_trade_size_queue_legs = queue_counts.get("missed_missing_trade_size", 0)
    clob_summary = (clob_recon or {}).get("summary") or {}
    unresolved_count = int((decisive_resting or {}).get("unresolved_resting_quote_count") or 0)
    by_slice = defaultdict(lambda: {
        "quote_legs": 0,
        "strict_trade_through_fills": 0,
        "strict_trade_through_filled_shares": 0.0,
        "missing_book_queue_legs": 0,
        "missing_trade_size_queue_legs": 0,
        "missed_queue_ahead_legs": 0,
        "no_touch_queue_legs": 0,
        "queue_estimated_fill_legs": 0,
        "queue_estimated_filled_shares": 0.0,
    })

    def key_for_leg(leg):
        quote_time = leg.get("quote_time")
        hour = f"{quote_time.hour:02d}:00Z" if quote_time else "unknown"
        return (
            leg.get("market_id") or "",
            hour,
            leg.get("clob_token_id") or "",
        )

    for leg in legs or []:
        key = key_for_leg(leg)
        item = by_slice[key]
        item["market_id"], item["hour_utc"], item["clob_token_id"] = key
        item["quote_legs"] += 1
        queue = queue_by_leg.get(leg.get("leg_id")) or {}
        status = queue.get("status") or "unknown"
        estimated = finite_float(queue.get("estimated_fill_size"), 0.0) or 0.0
        if status == "missing_book":
            item["missing_book_queue_legs"] += 1
        elif status == "missed_missing_trade_size":
            item["missing_trade_size_queue_legs"] += 1
        elif status == "missed_queue_ahead":
            item["missed_queue_ahead_legs"] += 1
        elif status == "no_touch":
            item["no_touch_queue_legs"] += 1
        if estimated > 0:
            item["queue_estimated_fill_legs"] += 1
            item["queue_estimated_filled_shares"] += estimated

    for fill in fill_rows or []:
        fill_hour = hour_bucket(fill.get("fill_time_utc"))
        key = (
            fill.get("market_id") or "",
            fill_hour,
            fill.get("clob_token_id") or "",
        )
        item = by_slice[key]
        item["market_id"], item["hour_utc"], item["clob_token_id"] = key
        item["strict_trade_through_fills"] += 1
        item["strict_trade_through_filled_shares"] += finite_float(fill.get("fill_size"), 0.0) or 0.0

    slice_rows = []
    for key, row in sorted(by_slice.items()):
        quote_legs = int(row.get("quote_legs") or 0)
        incomplete = (
            int(row.get("missing_book_queue_legs") or 0)
            + int(row.get("missing_trade_size_queue_legs") or 0)
        )
        slice_rows.append({
            **row,
            "strict_trade_through_filled_shares": compact_float(row.get("strict_trade_through_filled_shares")),
            "queue_estimated_filled_shares": compact_float(row.get("queue_estimated_filled_shares")),
            "incomplete_market_data_leg_fraction": compact_float(incomplete / quote_legs if quote_legs else 0.0),
        })

    event_rows = []
    for event_slug, row in sorted((diagnostics or {}).items()):
        event_rows.append({
            "event_slug": event_slug,
            "trade_rows": int(row.get("trade_rows") or 0),
            "missing_size_trade_rows": int(row.get("missing_size_trade_rows") or 0),
            "book_rows": int(row.get("book_rows") or 0),
            "mark_rows": int(row.get("mark_rows") or 0),
            "settlement_available": bool(row.get("settlement_available")),
        })

    blockers = []
    if missing_size_trade_rows > int(config.get("fill_evidence_max_missing_size_trade_rows", 0)):
        blockers.append("missing_size_trade_rows")
    if missing_book_queue_legs > int(config.get("fill_evidence_max_missing_book_queue_legs", 0)):
        blockers.append("missing_book_queue_legs")
    if missing_trade_size_queue_legs > int(config.get("fill_evidence_max_missing_trade_size_queue_legs", 0)):
        blockers.append("missing_trade_size_queue_legs")
    if unresolved_count > int(config.get("fill_evidence_max_unresolved_resting_quotes", 0)):
        blockers.append("unresolved_resting_quotes")
    if (
        bool(config.get("fill_evidence_require_clob_recon_coverage", True))
        and legs
        and (
            int(clob_summary.get("book_rows") or 0) <= 0
            or int(clob_summary.get("slice_rows") or 0) <= 0
        )
    ):
        blockers.append("clob_recon_coverage")

    return {
        "schema_version": "mm_fill_evidence_completeness_v0.1",
        "status": "PASS" if not blockers else "BLOCK",
        "promotion_grade": not blockers,
        "blockers": blockers,
        "quote_legs": len(legs or []),
        "strict_trade_through_fill_count": len(fill_rows or []),
        "strict_trade_through_filled_shares": compact_float(sum_field(fill_rows or [], "fill_size")),
        "queue_status_counts": dict(sorted(queue_counts.items())),
        "missing_size_trade_rows": missing_size_trade_rows,
        "missing_book_queue_legs": missing_book_queue_legs,
        "missing_trade_size_queue_legs": missing_trade_size_queue_legs,
        "unresolved_resting_quote_count": unresolved_count,
        "events_without_trade_rows": sorted(
            event_slug for event_slug, row in (diagnostics or {}).items()
            if int(row.get("trade_rows") or 0) == 0
        ),
        "events_without_book_rows": sorted(
            event_slug for event_slug, row in (diagnostics or {}).items()
            if int(row.get("book_rows") or 0) == 0
        ),
        "clob_recon_book_rows": int(clob_summary.get("book_rows") or 0),
        "clob_recon_slice_rows": int(clob_summary.get("slice_rows") or 0),
        "clob_recon_coverage_source": (clob_recon or {}).get("coverage_source"),
        "by_market_hour_token": slice_rows,
        "event_diagnostics": event_rows,
    }


def build_paper_payload(
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    run_folders=None,
    casebook_path=DEFAULT_CASEBOOK,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    config=None,
    now=None,
    ledger_root=None,
    clob_recon_path=DEFAULT_CLOB_RECON,
    exchange_economics_snapshot_path=None,
    exchange_economics_target_date=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    config = {**DEFAULT_CONFIG, **(config or {})}
    generated_at = generated_at_iso(now)
    candidate_run_folders = discover_run_folders(runs_root, run_folders=run_folders)
    run_folders, eligibility_by_folder, excluded_run_folders = split_run_folders_by_eligibility(candidate_run_folders)
    quote_rows, run_configs = load_quote_rows(run_folders, eligibility_by_folder=eligibility_by_folder)
    model_variant_quote_rows, _model_variant_run_configs = load_model_variant_quote_rows(
        run_folders,
        eligibility_by_folder=eligibility_by_folder,
    )
    legs = quote_legs(quote_rows, config)
    model_variant_legs = quote_legs(model_variant_quote_rows, config)
    casebook_index = load_casebook_index(casebook_path)
    fill_rows, queue_rows, diagnostics, leg_fill_sizes = simulate_conservative_fills(
        legs,
        snapshots_root,
        casebook_index,
        config,
        ledger_root=ledger_root,
    )
    model_variant_fill_rows, model_variant_queue_rows, model_variant_diagnostics, _model_variant_leg_fill_sizes = simulate_conservative_fills(
        model_variant_legs,
        snapshots_root,
        casebook_index,
        config,
        ledger_root=ledger_root,
    )
    model_variant_bakeoff = model_variant_paper_bakeoff_summary(
        model_variant_quote_rows,
        model_variant_legs,
        model_variant_fill_rows,
        model_variant_queue_rows,
        config=config,
    )
    queue_summary = Counter(row.get("status") for row in queue_rows)
    slices = build_markout_slices(fill_rows, config)
    early_hour_guardrail_shadow = build_early_hour_guardrail_shadow(
        fill_rows,
        quote_rows=quote_rows,
        config=config,
    )
    anti_overfit = anti_overfit_summary(quote_rows, run_configs)
    event_gate_score = score_event_gate_decisions(quote_rows, fill_rows=fill_rows)
    active_event_slugs = {leg.get("event_slug") for leg in legs if leg.get("event_slug")}
    clob_recon = load_or_build_clob_recon(
        clob_recon_path,
        snapshots_root,
        active_event_slugs,
        now=now,
    )
    decisive_resting = decisive_resting_check(legs, diagnostics)
    fill_evidence_completeness = fill_evidence_completeness_summary(
        legs,
        fill_rows,
        queue_rows,
        diagnostics,
        decisive_resting,
        clob_recon,
        config,
    )
    per_market_evidence_credits = [
        row
        for item in eligibility_by_folder.values()
        if item.get("scoreable")
        for row in item.get("per_market_evidence_credits") or []
    ]
    per_market_evidence_summary = summarize_per_market_evidence(per_market_evidence_credits)
    paper_score_freshness = maker_paper_score_freshness(
        candidate_run_folders,
        run_folders,
        report_generated_at_utc=generated_at,
    )
    economics_target_date = (
        exchange_economics_target_date
        or paper_score_freshness.get("latest_completed_active_day")
        or paper_score_freshness.get("latest_covered_active_day")
    )
    exchange_gate_required = (
        bool(exchange_economics_required)
        if exchange_economics_required is not None
        else (Path(backtest_root) == Path(DEFAULT_BACKTEST_ROOT) or exchange_economics_snapshot_path is not None)
    )
    exchange_gate = exchange_economics.load_exchange_economics_gate(
        exchange_economics_snapshot_path or exchange_economics.DEFAULT_SNAPSHOT,
        economics_target_date,
        platform=exchange_economics_platform,
        now=now or generated_at,
        required=exchange_gate_required,
    )
    exchange_fields = exchange_economics.exchange_economics_artifact_fields(exchange_gate)
    for row in fill_rows:
        row.update({
            "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": exchange_fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": exchange_fields.get("exchange_economics_evidence_basis"),
        })
    for row in model_variant_fill_rows:
        row.update({
            "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": exchange_fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": exchange_fields.get("exchange_economics_evidence_basis"),
        })
    base_gate_status = (
        "OPEN"
        if len(anti_overfit.get("live_forward_days") or []) < int(config["min_edge_allowed_live_days"])
        else "PAPER_DAYS_READY"
    )
    gate_status = "BLOCK" if not exchange_gate.get("ok") else base_gate_status
    summary = {
        "run_folders": len(run_folders),
        "candidate_run_folders": len(candidate_run_folders),
        "excluded_run_folders": len(excluded_run_folders),
        "quote_rows": len(quote_rows),
        "quote_legs": len(legs),
        "model_variant_quote_rows": len(model_variant_quote_rows),
        "model_variant_quote_legs": len(model_variant_legs),
        "conservative_fills": len(fill_rows),
        "conservative_filled_shares": compact_float(sum_field(fill_rows, "fill_size")),
        "queue_estimated_fill_legs": sum(1 for row in queue_rows if (finite_float(row.get("estimated_fill_size"), 0.0) or 0.0) > 0),
        "queue_estimated_filled_shares": compact_float(sum(finite_float(row.get("estimated_fill_size"), 0.0) or 0.0 for row in queue_rows)),
        "queue_status_counts": dict(sorted(queue_summary.items())),
        "trade_evidence_gaps": {
            "missing_size_trade_rows": sum(row.get("missing_size_trade_rows", 0) for row in diagnostics.values()),
            "events_without_trade_rows": sorted(
                key for key, row in diagnostics.items() if row.get("trade_rows", 0) == 0
            ),
        },
        "fill_evidence_completeness": {
            "status": fill_evidence_completeness.get("status"),
            "promotion_grade": fill_evidence_completeness.get("promotion_grade"),
            "blockers": fill_evidence_completeness.get("blockers") or [],
            "missing_size_trade_rows": fill_evidence_completeness.get("missing_size_trade_rows", 0),
            "missing_book_queue_legs": fill_evidence_completeness.get("missing_book_queue_legs", 0),
            "missing_trade_size_queue_legs": fill_evidence_completeness.get(
                "missing_trade_size_queue_legs",
                0,
            ),
            "unresolved_resting_quote_count": fill_evidence_completeness.get(
                "unresolved_resting_quote_count",
                0,
            ),
            "clob_recon_book_rows": fill_evidence_completeness.get("clob_recon_book_rows", 0),
            "clob_recon_slice_rows": fill_evidence_completeness.get("clob_recon_slice_rows", 0),
        },
        "pnl": summarize_pnl(fill_rows),
        "early_hour_guardrail_shadow": early_hour_guardrail_shadow.get("summary") or {},
        "anti_overfit": anti_overfit,
        "paper_score_freshness": paper_score_freshness,
        "paper_score_freshness_status": paper_score_freshness.get("status"),
        "latest_completed_active_day": paper_score_freshness.get("latest_completed_active_day"),
        "latest_covered_active_day": paper_score_freshness.get("latest_covered_active_day"),
        "exchange_economics_gate": exchange_gate,
        "exchange_economics_gate_status": exchange_gate.get("status"),
        "exchange_economics_gate_reason": exchange_gate.get("reason"),
        "paper_evidence_basis": exchange_gate.get("evidence_basis"),
        **exchange_fields,
        "per_market_live_forward_evidence": per_market_evidence_summary,
        "quote_uptime": quote_uptime_summary(quote_rows, legs),
        "event_gate_score": event_gate_score,
        "clob_recon": clob_recon.get("summary") or {},
        "decisive_resting_audit": decisive_resting,
        "model_variant_bakeoff": {
            "status": model_variant_bakeoff.get("status"),
            "quote_rows": model_variant_bakeoff.get("quote_rows", 0),
            "conservative_fills": model_variant_bakeoff.get("conservative_fills", 0),
            "policy_pair_count": model_variant_bakeoff.get("policy_pair_count", 0),
            "promotion_gate_status": (model_variant_bakeoff.get("promotion_gate") or {}).get("status"),
            "promotion_gate_method": (model_variant_bakeoff.get("promotion_gate") or {}).get("method"),
            "promotion_gate_pair_count": (model_variant_bakeoff.get("promotion_gate") or {}).get("pair_count"),
            "promotion_gate_pass_pair_count": (model_variant_bakeoff.get("promotion_gate") or {}).get(
                "pass_pair_count"
            ),
        },
        "gate_status": gate_status,
        "gate_status_without_exchange_economics": base_gate_status,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "runs_root": str(runs_root),
        "snapshots_root": str(snapshots_root),
        "backtest_root": str(backtest_root),
        "promotion_refresh": str(promotion_refresh),
        "casebook_path": str(casebook_path),
        "exchange_economics_snapshot_path": str(exchange_economics_snapshot_path) if exchange_economics_snapshot_path else None,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "config": config,
        "summary": summary,
        "clob_recon": clob_recon,
        "fill_evidence_completeness": fill_evidence_completeness,
        "event_diagnostics": diagnostics,
        "run_configs": run_configs,
        "run_folder_eligibility": eligibility_by_folder,
        "per_market_evidence_credits": per_market_evidence_credits,
        "excluded_run_folders": excluded_run_folders,
        "markout_slices": slices,
        "early_hour_guardrail_shadow": early_hour_guardrail_shadow,
        "model_variant_bakeoff": model_variant_bakeoff,
        "model_variant_event_diagnostics": model_variant_diagnostics,
        "model_variant_fills": model_variant_fill_rows,
        "model_variant_queue_companion": model_variant_queue_rows,
        "queue_companion": queue_rows,
        "fills": fill_rows,
    }



from weather.market.mm_paper_reports import (  # noqa: E402
    build_known_edge_map,
    fmt_num,
    load_promotion_records,
    markdown_table,
    permission_for_record,
    promotion_state_from_action,
    render_known_edge_report,
    render_paper_report,
    source_freshness_gap_records,
)


def write_outputs(
    paper_payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    fills_out=DEFAULT_FILLS_OUT,
    known_edge_out=DEFAULT_KNOWN_EDGE_OUT,
    known_edge_report_out=DEFAULT_KNOWN_EDGE_REPORT_OUT,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
):
    report_out = Path(report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_paper_report(paper_payload), encoding="utf-8")
    fills_path = write_csv(fills_out, FILL_COLUMNS, paper_payload.get("fills") or [])
    known_edge = build_known_edge_map(
        paper_payload,
        promotion_refresh=promotion_refresh,
        config=paper_payload.get("config") or DEFAULT_CONFIG,
    )
    known_json = write_json(known_edge_out, known_edge)
    known_report_out = Path(known_edge_report_out)
    known_report_out.parent.mkdir(parents=True, exist_ok=True)
    known_report_out.write_text(render_known_edge_report(known_edge), encoding="utf-8")
    paper_payload["outputs"] = {
        "json": str(Path(json_out)),
        "report": str(report_out),
        "fills_csv": str(fills_path),
        "known_edge_json": str(known_json),
        "known_edge_report": str(known_report_out),
    }
    json_path = write_json(json_out, paper_payload)
    paper_payload["outputs"]["json"] = str(json_path)
    return paper_payload, known_edge


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value.")
        key, value = item.split("=", 1)
        if key not in DEFAULT_CONFIG:
            raise SystemExit(f"Unknown paper config key {key!r}.")
        default = DEFAULT_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, int):
            config[key] = int(float(value))
        elif isinstance(default, float):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Score market-making paper quote-intent runs.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--run-folder", action="append", default=[], help="Explicit run folder; may be passed more than once.")
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fills-out", default=str(DEFAULT_FILLS_OUT))
    parser.add_argument("--known-edge-out", default=str(DEFAULT_KNOWN_EDGE_OUT))
    parser.add_argument("--known-edge-report-out", default=str(DEFAULT_KNOWN_EDGE_REPORT_OUT))
    parser.add_argument("--ledger-root", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-target-date", default=None)
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    parser.add_argument("--config", action="append", default=[], help="Paper config override, key=value.")
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    backtest_root = Path(args.backtest_root)
    config = parse_config_overrides(args.config)
    payload = build_paper_payload(
        runs_root=Path(args.runs_root),
        snapshots_root=Path(args.snapshots_root),
        backtest_root=backtest_root,
        run_folders=args.run_folder,
        casebook_path=Path(args.casebook),
        promotion_refresh=Path(args.promotion_refresh),
        config=config,
        now=parse_time(args.now) if args.now else None,
        ledger_root=Path(args.ledger_root) if args.ledger_root else None,
        exchange_economics_snapshot_path=Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        exchange_economics_target_date=args.exchange_economics_target_date,
        exchange_economics_platform=args.exchange_economics_platform,
    )
    payload, _known_edge = write_outputs(
        payload,
        json_out=Path(args.json_out),
        report_out=Path(args.report_out),
        fills_out=Path(args.fills_out),
        known_edge_out=Path(args.known_edge_out),
        known_edge_report_out=Path(args.known_edge_report_out),
        promotion_refresh=Path(args.promotion_refresh),
    )
    summary = payload["summary"]
    print(
        "MM paper: "
        f"{summary['conservative_fills']} conservative fills, "
        f"{summary['queue_estimated_fill_legs']} queue-estimated fill legs, "
        f"gate {summary['gate_status']} -> {args.report_out}"
    )
    return payload


if __name__ == "__main__":
    main()
