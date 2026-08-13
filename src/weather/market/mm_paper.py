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
import gc
import hashlib
import math
import random
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from weather.market.info_event_calendar import score_event_gate_decisions
from weather.market.clob_recon import (
    DEFAULT_JSON_OUT as DEFAULT_CLOB_RECON,
    build_recon_payload,
    load_recon_payload,
)
from weather.market import exchange_economics
from weather.market.mm_policy import (
    bool_value,
    early_hour_guardrail_state,
    known_edge_record_key,
    known_edge_row_dimensions,
    load_known_edge_map,
    maybe_float,
    normalize_known_edge_field,
    normalize_token,
    parse_time,
    resolve_known_edge_record,
)
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
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    FILL_COLUMNS,
    KNOWN_EDGE_SCHEMA_VERSION,
    MARKOUT_HORIZONS,
    SCHEMA_VERSION,
)
from weather.market.mm_paper_aggregation import MakerPaperRunAggregation

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
    queue_with_context = getattr(variant_queue_rows, "iter_with_context", None)
    leg_by_id = {} if not queue_with_context else None

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
        if leg_by_id is not None:
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

    queue_and_legs = (
        queue_with_context()
        if queue_with_context
        else (
            (queue, leg_by_id.get(queue.get("leg_id")) or queue)
            for queue in variant_queue_rows or []
        )
    )
    for queue, leg in queue_and_legs:
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


def select_run_folders_for_paper(
    candidate_run_folders,
    *,
    explicit_run_folders=False,
    target_date=None,
    latest_n=None,
    evidence_mode=None,
):
    if latest_n is not None and int(latest_n) <= 0:
        raise ValueError("run_folder_latest_n must be a positive integer when provided")
    rows = []
    for folder in candidate_run_folders or []:
        row = _run_folder_freshness_row(folder)
        rows.append({**row, "_path": Path(folder)})

    filtered = rows
    if target_date:
        filtered = [row for row in filtered if str(row.get("target_date") or "") == str(target_date)]
    if evidence_mode:
        filtered = [row for row in filtered if str(row.get("evidence_mode") or "") == str(evidence_mode)]
    filtered = sorted(filtered, key=_run_freshness_sort_key)
    if latest_n is not None:
        filtered = filtered[-int(latest_n):]

    bounded = bool(explicit_run_folders or target_date or latest_n is not None or evidence_mode)
    if explicit_run_folders and (target_date or latest_n is not None or evidence_mode):
        mode = "explicit_filtered"
    elif explicit_run_folders:
        mode = "explicit"
    elif bounded:
        mode = "bounded"
    else:
        mode = "full"

    selected = [row["_path"] for row in filtered]
    selected_rows = []
    for row in filtered:
        selected_rows.append({
            key: value
            for key, value in row.items()
            if key != "_path"
        })
    selection = {
        "schema_version": "mm_paper_run_folder_selection_v0.1",
        "mode": mode,
        "bounded": bounded,
        "warning": "diagnostic_selection_not_full_corpus" if bounded else None,
        "explicit_run_folders": bool(explicit_run_folders),
        "target_date": target_date,
        "evidence_mode": evidence_mode,
        "latest_n": int(latest_n) if latest_n is not None else None,
        "available_run_folders_before_selection": len(rows),
        "candidate_run_folders_after_selection": len(selected),
        "selected_run_folders": [str(path) for path in selected],
        "selected_runs": selected_rows,
    }
    return selected, selection


def _first_finite_value(row, *keys):
    for key in keys:
        value = finite_float(row.get(key))
        if value is not None:
            return value
    return None


def _reward_score_inputs(snapshot_payload, exchange_gate):
    snapshot_payload = snapshot_payload or {}
    rewards = snapshot_payload.get("liquidity_rewards") or {}
    rules = snapshot_payload.get("market_rules") or {}
    return {
        "platform": snapshot_payload.get("platform") or (exchange_gate or {}).get("platform"),
        "formula": rewards.get("formula") or snapshot_payload.get("reward_formula") or "",
        "discount_factor": finite_float(
            rewards.get("discount_factor_default")
            or rewards.get("discount_factor")
            or rewards.get("discountFactor")
        ),
        "target_size": finite_float(
            rewards.get("target_size_default_contracts")
            or rewards.get("target_size")
            or rewards.get("targetSize")
        ),
        "campaign_pool_usdc": finite_float(
            rewards.get("default_category_daily_reward_usd")
            or rewards.get("daily_reward_usd")
            or rewards.get("campaign_pool_usdc")
            or rewards.get("campaignPoolUsd")
        ),
        "min_payout_usdc": finite_float(
            rewards.get("min_payout_usd")
            or rewards.get("min_payout_usdc")
            or rewards.get("minimum_payout_usd")
        ),
        "tick_size": finite_float(rules.get("tick_size") or snapshot_payload.get("tick_size")),
        "min_order_size": finite_float(rules.get("min_order_size") or snapshot_payload.get("min_order_size")),
    }


def _estimated_best_price_for_leg(row, side):
    side = str(side or "").upper()
    if side == "YES_BID":
        explicit = _first_finite_value(row, "best_bid_price", "book_best_bid", "best_bid")
        if explicit is not None:
            return explicit
    elif side == "YES_ASK":
        explicit = _first_finite_value(row, "best_ask_price", "book_best_ask", "best_ask")
        if explicit is not None:
            return explicit
    mid = _first_finite_value(row, "market_mid")
    spread = _first_finite_value(row, "book_spread")
    if mid is None or spread is None:
        return None
    half_spread = max(0.0, float(spread) / 2.0)
    if side == "YES_BID":
        return max(0.0, float(mid) - half_spread)
    if side == "YES_ASK":
        return min(1.0, float(mid) + half_spread)
    return None


def _us_reward_score_for_leg(leg, inputs):
    row = leg.get("quote_row") or leg
    tick_size = _first_finite_value(row, "tick_size") or inputs.get("tick_size")
    min_order_size = _first_finite_value(row, "min_order_size") or inputs.get("min_order_size") or 0.0
    discount = inputs.get("discount_factor")
    price = finite_float(leg.get("quote_price"))
    size = finite_float(leg.get("quote_size"), 0.0) or 0.0
    if tick_size is None or tick_size <= 0:
        return None, "missing_tick_size", None
    if discount is None or discount <= 0:
        return None, "missing_discount_factor", None
    if price is None:
        return None, "missing_quote_price", None
    if size <= 0:
        return 0.0, "zero_quote_size", None
    if size < min_order_size:
        return 0.0, "below_min_order_size", None
    best_price = _estimated_best_price_for_leg(row, leg.get("side"))
    if best_price is None:
        return None, "missing_best_price_or_book_spread", None
    side = str(leg.get("side") or "").upper()
    if side == "YES_BID":
        ticks_from_best = max(0.0, (float(best_price) - float(price)) / float(tick_size))
    elif side == "YES_ASK":
        ticks_from_best = max(0.0, (float(price) - float(best_price)) / float(tick_size))
    else:
        return None, "unsupported_side", None
    tick_count = int(math.ceil(max(0.0, ticks_from_best - 1e-9)))
    return float(size) * (float(discount) ** tick_count), None, tick_count


def reward_competitor_score_from_inputs(config, clob_recon=None):
    config = {**DEFAULT_CONFIG, **(config or {})}
    clob_summary = (clob_recon or {}).get("summary") or {}
    clob_suggestions = (
        (clob_recon or {}).get("policy_parameter_suggestions")
        or clob_summary.get("policy_parameter_suggestions")
        or {}
    )
    recon_score = finite_float(clob_suggestions.get("reward_competitor_q"))
    if recon_score is not None:
        return {
            "score": max(0.0, recon_score),
            "source": "clob_recon_policy_parameter_suggestions.reward_competitor_q",
            "source_available": True,
            "clob_recon_coverage_source": (clob_recon or {}).get("coverage_source"),
            "clob_recon_book_rows": int(clob_summary.get("book_rows") or 0),
            "clob_recon_slice_rows": int(clob_summary.get("slice_rows") or 0),
        }
    config_score = finite_float(config.get("reward_competitor_q"), 0.0)
    return {
        "score": max(0.0, config_score or 0.0),
        "source": "paper_config_reward_competitor_q",
        "source_available": False,
        "clob_recon_coverage_source": (clob_recon or {}).get("coverage_source"),
        "clob_recon_book_rows": int(clob_summary.get("book_rows") or 0),
        "clob_recon_slice_rows": int(clob_summary.get("slice_rows") or 0),
    }


def build_reward_score_diagnostics(
    quote_rows,
    legs,
    exchange_gate=None,
    economics_snapshot=None,
    config=None,
    clob_recon=None,
):
    quote_rows = quote_rows or []
    legs = legs or []
    exchange_gate = exchange_gate or {}
    economics_snapshot = economics_snapshot or {}
    config = {**DEFAULT_CONFIG, **(config or {})}
    inputs = _reward_score_inputs(economics_snapshot, exchange_gate)
    formula = str(inputs.get("formula") or "")
    if str(inputs.get("platform") or "") == exchange_economics.GLOBAL_PLATFORM:
        no_quote_reason_counts = Counter(
            row.get("reason_code") or "NO_QUOTE_UNKNOWN"
            for row in quote_rows
            if not quote_permission(row)
        )
        return {
            "schema_version": "mm_reward_score_diagnostics_v0.2",
            "status": "PASS_ZERO_ASSUMPTION" if exchange_gate.get("ok") else "WARN",
            "score_basis": "liquidity_rewards_excluded_from_primary_pnl",
            "exchange_economics_status": exchange_gate.get("status"),
            "exchange_economics_snapshot_id": exchange_gate.get("snapshot_id"),
            "platform": inputs.get("platform"),
            "formula": formula,
            "quote_rows": len(quote_rows),
            "quote_permission_rows": sum(1 for row in quote_rows if quote_permission(row)),
            "no_quote_rows": sum(1 for row in quote_rows if not quote_permission(row)),
            "quoted_legs": len(legs),
            "positive_score_legs": 0,
            "zero_score_legs": len(legs),
            "unscored_legs": 0,
            "total_reward_score": 0.0,
            "score_to_target_size_fraction": None,
            "score_at_or_above_target_size": False,
            "counterfactual_score_share": 0.0,
            "counterfactual_reward_before_min_payout_usdc": 0.0,
            "counterfactual_reward_usdc": 0.0,
            "counterfactual_reward_status": "PRIMARY_ASSUMPTION_ZERO",
            "actual_payout_evidence": False,
            "does_not_change_pnl": True,
            "payout_evidence_status": "NO_ACTUAL_PAYOUT_EVIDENCE",
            "blocker_counts": {
                "per_condition_reward_scoring_not_used_for_primary_pnl": len(legs),
            },
            "no_quote_reason_counts": dict(no_quote_reason_counts),
            "score_attribution_top_groups": [],
            "scored_legs": [],
        }
    supported = (
        str(inputs.get("platform") or "") == "polymarket_us"
        and "discount_factor" in formula
    )
    blocker_counts = Counter()
    no_quote_reason_counts = Counter(
        row.get("reason_code") or "NO_QUOTE_UNKNOWN"
        for row in quote_rows
        if not quote_permission(row)
    )
    leg_rows = []
    score_groups = defaultdict(lambda: {
        "reward_score": 0.0,
        "quoted_legs": 0,
        "quote_size": 0.0,
    })
    score_sum = 0.0
    positive_legs = 0
    zero_legs = 0
    unscored_legs = 0
    if not supported:
        blocker_counts["unsupported_or_missing_reward_formula"] = len(legs)
    for leg in legs:
        row = leg.get("quote_row") or leg
        if not supported:
            score = None
            blocker = "unsupported_or_missing_reward_formula"
            ticks = None
        else:
            score, blocker, ticks = _us_reward_score_for_leg(leg, inputs)
        if blocker:
            blocker_counts[blocker] += 1
        if score is not None:
            score_sum += max(0.0, float(score))
            if score > 0:
                positive_legs += 1
            else:
                zero_legs += 1
        else:
            unscored_legs += 1
        group_key = (
            row.get("market_id") or leg.get("market_id") or "",
            row.get("range_label") or leg.get("range_label") or "",
            hour_bucket(row.get("generated_at_utc") or row.get("captured_at_utc") or leg.get("quote_time")),
            leg.get("side") or "",
        )
        group = score_groups[group_key]
        group["reward_score"] += max(0.0, float(score or 0.0))
        group["quoted_legs"] += 1
        group["quote_size"] += finite_float(leg.get("quote_size"), 0.0) or 0.0
        if len(leg_rows) < 50:
            leg_rows.append({
                "run_folder": row.get("_run_folder") or leg.get("run_folder"),
                "run_id": row.get("run_id") or leg.get("run_id"),
                "target_date": row.get("target_date") or leg.get("target_date"),
                "market_id": row.get("market_id") or leg.get("market_id"),
                "range_label": row.get("range_label") or leg.get("range_label"),
                "side": leg.get("side"),
                "quote_price": compact_float(leg.get("quote_price")),
                "quote_size": compact_float(leg.get("quote_size")),
                "ticks_from_best_price": ticks,
                "reward_score": compact_float(score),
                "blocker": blocker,
                "reason_code": row.get("reason_code") or leg.get("reason_code"),
                "known_edge_permission": row.get("known_edge_permission") or leg.get("known_edge_permission"),
                "promotion_state": row.get("promotion_state") or leg.get("promotion_state"),
            })
    target_size = inputs.get("target_size")
    campaign_pool = (
        inputs.get("campaign_pool_usdc")
        if inputs.get("campaign_pool_usdc") is not None
        else finite_float(config.get("reward_campaign_pool_usdc"))
    )
    min_payout = (
        inputs.get("min_payout_usdc")
        if inputs.get("min_payout_usdc") is not None
        else finite_float(config.get("reward_min_payout_usdc"), 0.0)
    )
    competitor = reward_competitor_score_from_inputs(config, clob_recon=clob_recon)
    competitor_score = competitor["score"]
    counterfactual_share = None
    counterfactual_before_min = None
    counterfactual_reward = None
    if campaign_pool is not None and competitor_score is not None and score_sum > 0:
        denominator = score_sum + max(0.0, competitor_score)
        counterfactual_share = score_sum / denominator if denominator > 0 else 0.0
        counterfactual_before_min = campaign_pool * counterfactual_share
        counterfactual_reward = (
            counterfactual_before_min
            if counterfactual_before_min >= (min_payout or 0.0)
            else 0.0
        )
    top_groups = []
    for (market_id, range_label, hour_utc, side), row in score_groups.items():
        group_score = row["reward_score"]
        group_share = group_score / score_sum if score_sum > 0 else 0.0
        top_groups.append({
            "market_id": market_id,
            "range_label": range_label,
            "hour_utc": hour_utc,
            "side": side,
            "quoted_legs": row["quoted_legs"],
            "quote_size": compact_float(row["quote_size"]),
            "reward_score": compact_float(group_score),
            "share_of_own_score": compact_float(group_share, digits=8),
            "counterfactual_reward_usdc": compact_float(
                (counterfactual_reward or 0.0) * group_share
                if counterfactual_reward is not None
                else None
            ),
        })
    top_groups = sorted(
        top_groups,
        key=lambda row: (
            -(finite_float(row.get("reward_score"), 0.0) or 0.0),
            row.get("market_id") or "",
            row.get("range_label") or "",
            row.get("side") or "",
        ),
    )[:25]
    return {
        "schema_version": "mm_reward_score_diagnostics_v0.2",
        "status": "PASS" if supported and exchange_gate.get("ok") else "WARN",
        "score_basis": "polymarket_us_discount_factor_ticks_from_best" if supported else "unsupported",
        "exchange_economics_status": exchange_gate.get("status"),
        "exchange_economics_snapshot_id": exchange_gate.get("snapshot_id"),
        "platform": inputs.get("platform"),
        "formula": formula,
        "discount_factor": compact_float(inputs.get("discount_factor")),
        "tick_size": compact_float(inputs.get("tick_size")),
        "min_order_size": compact_float(inputs.get("min_order_size")),
        "target_size_contracts": compact_float(target_size),
        "campaign_pool_usdc": compact_float(campaign_pool),
        "min_payout_usdc": compact_float(min_payout),
        "assumed_competitor_score": compact_float(competitor_score),
        "assumed_competitor_score_source": competitor.get("source"),
        "assumed_competitor_score_has_clob_recon_evidence": bool(competitor.get("source_available")),
        "assumed_competitor_score_clob_recon_coverage_source": competitor.get("clob_recon_coverage_source"),
        "assumed_competitor_score_clob_recon_book_rows": competitor.get("clob_recon_book_rows", 0),
        "assumed_competitor_score_clob_recon_slice_rows": competitor.get("clob_recon_slice_rows", 0),
        "quote_rows": len(quote_rows),
        "quote_permission_rows": sum(1 for row in quote_rows if quote_permission(row)),
        "no_quote_rows": sum(1 for row in quote_rows if not quote_permission(row)),
        "quoted_legs": len(legs),
        "positive_score_legs": positive_legs,
        "zero_score_legs": zero_legs,
        "unscored_legs": unscored_legs,
        "total_reward_score": compact_float(score_sum),
        "score_to_target_size_fraction": compact_float(
            score_sum / target_size if target_size and target_size > 0 else None,
            digits=8,
        ),
        "score_at_or_above_target_size": (
            bool(target_size and score_sum >= target_size)
            if target_size is not None
            else None
        ),
        "counterfactual_score_share": compact_float(counterfactual_share, digits=8),
        "counterfactual_reward_before_min_payout_usdc": compact_float(counterfactual_before_min),
        "counterfactual_reward_usdc": compact_float(counterfactual_reward),
        "counterfactual_reward_status": (
            "COUNTERFACTUAL_ONLY"
            if counterfactual_reward is not None
            else "MISSING_POOL_OR_SCORE"
        ),
        "actual_payout_evidence": False,
        "does_not_change_pnl": True,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "no_quote_reason_counts": dict(sorted(no_quote_reason_counts.items())),
        "score_attribution_top_groups": top_groups,
        "scored_legs": leg_rows,
    }


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


def build_early_hour_guardrail_shadow(fill_rows, quote_rows=None, config=None, quote_exposure=None):
    config = {**DEFAULT_CONFIG, **(config or {})}
    new_row_store = getattr(fill_rows, "new_row_store", None)
    rows = new_row_store("early_hour_guardrail") if new_row_store else []
    base_net_sum = 0.0
    capped_net_sum = 0.0
    market_net_sum = 0.0
    early_base_net_sum = 0.0
    early_capped_net_sum = 0.0
    early_market_net_sum = 0.0
    early_base_loss = 0.0
    early_capped_loss = 0.0
    early_market_loss = 0.0
    early_fill_rows = 0
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
        if base_net is not None and math.isfinite(float(base_net)):
            base_net_sum += float(base_net)
        if capped_net is not None and math.isfinite(float(capped_net)):
            capped_net_sum += float(capped_net)
        if market_net is not None and math.isfinite(float(market_net)):
            market_net_sum += float(market_net)
        is_early = state.get("hourly_trust_band") == "early_00_08"
        if is_early:
            early_fill_rows += 1
            if base_net is not None and math.isfinite(float(base_net)):
                early_base_net_sum += float(base_net)
                early_base_loss -= min(0.0, float(base_net))
            if capped_net is not None and math.isfinite(float(capped_net)):
                early_capped_net_sum += float(capped_net)
                early_capped_loss -= min(0.0, float(capped_net))
            if market_net is not None and math.isfinite(float(market_net)):
                early_market_net_sum += float(market_net)
                early_market_loss -= min(0.0, float(market_net))
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

    quote_exposure = quote_exposure or _guardrail_quote_exposure(quote_rows or [], config)
    status = "NO_FILL_EVIDENCE"
    if rows:
        if not early_fill_rows:
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
        "early_hour_fill_rows": early_fill_rows,
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
        "early_hour_base_loss_usdc": compact_float(early_base_loss),
        "early_hour_capped_loss_usdc": compact_float(early_capped_loss),
        "early_hour_market_aware_loss_usdc": compact_float(early_market_loss),
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
    grouped = defaultdict(
        lambda: {
            "fill_count": 0,
            "share_count": 0.0,
            "markout_n": 0,
            "markout_sum": 0.0,
            "markout_partials": defaultdict(int),
            "markout_square_partials": defaultdict(int),
            "settlement_n": 0,
            "settlement_sum": 0.0,
            "settlement_partials": defaultdict(int),
            "settlement_square_partials": defaultdict(int),
            "net_pnl": 0.0,
            "settlement_pnl": 0.0,
            "example_fill_ids": [],
        }
    )
    for row in fill_rows:
        item = grouped[slice_key(row)]
        item["fill_count"] += 1
        item["share_count"] += finite_float(row.get("fill_size"), 0.0) or 0.0
        markout = finite_float(row.get("markout_30m_per_share"))
        if markout is not None and math.isfinite(float(markout)):
            markout = float(markout)
            item["markout_n"] += 1
            item["markout_sum"] += markout
            numerator, denominator = markout.as_integer_ratio()
            item["markout_partials"][denominator] += numerator
            item["markout_square_partials"][denominator] += numerator * numerator
        settlement = finite_float(row.get("settlement_markout_per_share"))
        if settlement is not None and math.isfinite(float(settlement)):
            settlement = float(settlement)
            item["settlement_n"] += 1
            item["settlement_sum"] += settlement
            numerator, denominator = settlement.as_integer_ratio()
            item["settlement_partials"][denominator] += numerator
            item["settlement_square_partials"][denominator] += numerator * numerator
        item["net_pnl"] += (
            finite_float(row.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0
        )
        item["settlement_pnl"] += finite_float(row.get("settlement_pnl_usdc"), 0.0) or 0.0
        if len(item["example_fill_ids"]) < 5:
            item["example_fill_ids"].append(row.get("fill_id"))

    def moments(item, prefix, z):
        n = int(item[f"{prefix}_n"])
        if not n:
            return None, None, None
        total = float(item[f"{prefix}_sum"])
        average = total / n
        if n < 2:
            return average, average, average
        partials = item[f"{prefix}_partials"]
        square_partials = item[f"{prefix}_square_partials"]
        exact_sum = sum(Fraction(numerator, denominator) for denominator, numerator in partials.items())
        exact_sum_squares = sum(
            Fraction(numerator, denominator * denominator)
            for denominator, numerator in square_partials.items()
        )
        sum_squared_deviations = (
            n * exact_sum_squares - exact_sum * exact_sum
        ) / n
        sample_variance = sum_squared_deviations / (n - 1)
        stdev = math.sqrt(float(sample_variance))
        stderr = stdev / math.sqrt(n)
        return average, average - z * stderr, average + z * stderr

    z = float(config["confidence_z"])
    adjustment_count = max(1, len(grouped))
    slices = []
    for key, item in grouped.items():
        markout_mean, ci_low, ci_high = moments(item, "markout", z)
        settlement_mean, set_low, set_high = moments(item, "settlement", z)
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
            "fill_count": item["fill_count"],
            "share_count": compact_float(item["share_count"]),
            "mean_markout_30m_per_share": compact_float(markout_mean),
            "markout_30m_ci_low": compact_float(ci_low),
            "markout_30m_ci_high": compact_float(ci_high),
            "mean_settlement_markout_per_share": compact_float(settlement_mean),
            "settlement_markout_ci_low": compact_float(set_low),
            "settlement_markout_ci_high": compact_float(set_high),
            "net_pnl_after_fees_incentives_usdc": compact_float(item["net_pnl"]),
            "settlement_pnl_usdc": compact_float(item["settlement_pnl"]),
            "multiple_test_adjustment": "bonferroni_conservative",
            "multiple_test_family_size": adjustment_count,
            "deflated_markout_30m_per_share": compact_float(ci_low),
            "example_fill_ids": item["example_fill_ids"],
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


def _quoted_id_state(quote_rows, legs):
    if getattr(quote_rows, "has_quote_leg_marker", False):
        return None, int(quote_rows.quoted_id_count)
    quoted_ids = {leg["quote_id"] for leg in legs}
    return quoted_ids, len(quoted_ids)


def _row_has_quote_leg(row, quoted_ids):
    if quoted_ids is None:
        return bool(row.get("_has_quote_leg"))
    return row.get("_quote_id") in quoted_ids


class _FilteredRows:
    """Small re-iterable view that does not retain matching source rows."""

    def __init__(self, rows, predicate):
        self.rows = rows
        self.predicate = predicate
        self._count = None

    def __iter__(self):
        return (row for row in self.rows if self.predicate(row))

    def __len__(self):
        if self._count is None:
            self._count = sum(1 for _row in self)
        return self._count

    def __bool__(self):
        return len(self) > 0


def quote_uptime_summary(quote_rows, legs):
    quoted_ids, quoted_id_count = _quoted_id_state(quote_rows, legs)
    no_quote_reasons = Counter()
    quote_permission_markets = Counter()
    quote_permission_cells = Counter()
    first_quote_time = None
    last_quote_time = None
    for row in quote_rows:
        quote_time = parse_time(row.get("generated_at_utc"))
        if quote_time is not None:
            first_quote_time = (
                quote_time if first_quote_time is None else min(first_quote_time, quote_time)
            )
            last_quote_time = (
                quote_time if last_quote_time is None else max(last_quote_time, quote_time)
            )
        if not _row_has_quote_leg(row, quoted_ids):
            no_quote_reasons[row.get("reason_code") or "unknown"] += 1
            continue
        quote_permission_markets[row.get("market_id") or "unknown"] += 1
        quote_permission_cells[
            (
                row.get("market_id") or "unknown",
                row.get("range_label") or "unknown",
                row.get("known_edge_permission") or "unknown",
                row.get("promotion_state") or "unknown",
                row.get("reason_code") or "QUOTE",
            )
        ] += 1
    uptime = quoted_id_count / len(quote_rows) if quote_rows else 0.0
    return {
        "quote_rows": len(quote_rows),
        "quote_permission_rows": quoted_id_count,
        "quote_uptime_fraction": compact_float(uptime),
        "first_quote_time_utc": first_quote_time.isoformat() if first_quote_time else None,
        "last_quote_time_utc": last_quote_time.isoformat() if last_quote_time else None,
        "stale_input_pulls": no_quote_reasons.get("NO_QUOTE_STALE_INPUT", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_BOOK", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_MODEL", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_WATCHER", 0),
        "no_quote_reason_counts": dict(sorted(no_quote_reasons.items())),
        "quote_permission_market_counts": dict(sorted(quote_permission_markets.items())),
        "top_quote_permission_cells": [
            {
                "market_id": market_id,
                "range_label": range_label,
                "known_edge_permission": known_edge_permission,
                "promotion_state": promotion_state,
                "reason_code": reason_code,
                "rows": count,
            }
            for (
                market_id,
                range_label,
                known_edge_permission,
                promotion_state,
                reason_code,
            ), count in quote_permission_cells.most_common(25)
        ],
    }


def quote_blocker_diagnostics(quote_rows, legs, limit=25, known_edge_records=None, known_edge_map_diag=None):
    quoted_ids, quoted_id_count = _quoted_id_state(quote_rows, legs or [])
    blocked_rows = _FilteredRows(
        quote_rows or [],
        lambda row: not _row_has_quote_leg(row, quoted_ids),
    )
    known_edge_records = list(known_edge_records or [])
    known_edge_map_diag = dict(known_edge_map_diag or {})

    def text(row, key, default=""):
        value = row.get(key)
        if value is None or value == "":
            return default
        return str(value)

    def top_counter(counter, keys):
        rows = []
        for key, count in counter.most_common(limit):
            if not isinstance(key, tuple):
                key = (key,)
            row = {name: value for name, value in zip(keys, key)}
            row["rows"] = count
            rows.append(row)
        return rows

    def inferred_known_edge_dimensions(row):
        dimensions = known_edge_row_dimensions(row)
        inferred_band_distance = dimensions.get("band_distance_bucket") or band_distance_bucket(row)
        inferred_book_bucket = dimensions.get("book_imbalance_bucket") or book_imbalance_bucket(
            row.get("book_imbalance_1pct")
        )
        return {
            **dimensions,
            "band_distance_bucket": inferred_band_distance or "",
            "book_imbalance_bucket": inferred_book_bucket or "",
            "casebook_taxonomy": dimensions.get("casebook_taxonomy") or "",
        }

    def inferred_known_edge_row(row):
        dimensions = inferred_known_edge_dimensions(row)
        out = dict(row)
        for key, value in dimensions.items():
            if value:
                out[key] = value
        return out

    def diagnostic_wildcard(field, value):
        token = normalize_known_edge_field(field, value)
        if token in {"", "*", "any", "all"}:
            return True
        return field == "cutoff" and token == "paper_slice"

    def nearest_known_edge_record_gap(dimensions):
        market_id = dimensions.get("market_id") or ""
        same_market = [
            record for record in known_edge_records
            if normalize_token(record.get("market_id")) == market_id
        ]
        wildcard_market = [
            record for record in known_edge_records
            if normalize_token(record.get("market_id")) in {"", "*", "any", "all"}
        ]
        candidates = same_market or wildcard_market
        if not candidates:
            return {
                "record": None,
                "matched_dimension_count": 0,
                "mismatched_dimension_count": 1,
                "mismatched_dimensions": "market_id",
                "record_key": "",
                "record_permission": "",
                "record_reason": "no_market_record",
            }
        fields = (
            "cutoff",
            "hour_utc",
            "band_distance_bucket",
            "band_type",
            "casebook_taxonomy",
            "regime",
            "source_fresh",
            "source_freshness_state",
            "book_imbalance_bucket",
        )
        best = None
        for record in candidates:
            matched = 0
            mismatches = []
            concrete = 0
            for field in fields:
                record_value = normalize_known_edge_field(field, record.get(field))
                if diagnostic_wildcard(field, record_value):
                    continue
                concrete += 1
                row_value = dimensions.get(field) or ""
                if row_value and row_value == record_value:
                    matched += 1
                    continue
                mismatches.append(f"{field}:{row_value or '(missing)'}!={record_value or '(missing)'}")
            score = (matched, -len(mismatches), concrete)
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "record": record,
                    "matched_dimension_count": matched,
                    "mismatched_dimension_count": len(mismatches),
                    "mismatched_dimensions": "; ".join(mismatches[:6]),
                    "record_key": known_edge_record_key(record),
                    "record_permission": record.get("permission") or "no_quote",
                    "record_reason": record.get("reason") or "",
                }
        return best or {}

    market_reason = Counter(
        (
            text(row, "market_id", "unknown"),
            text(row, "reason_code", "NO_QUOTE_UNKNOWN"),
        )
        for row in blocked_rows
    )
    known_edge = Counter(
        (
            text(row, "known_edge_reason", "unknown"),
            text(row, "known_edge_permission", "unknown"),
            text(row, "promotion_state", "unknown"),
        )
        for row in blocked_rows
    )
    event_gate = Counter(
        (
            text(row, "event_gate_status", "unknown"),
            text(row, "event_gate_action", "unknown"),
            text(row, "event_gate_reason_code", "unknown"),
            text(row, "event_gate_event_class", "unknown"),
        )
        for row in blocked_rows
        if (
            text(row, "event_gate_status")
            or text(row, "event_gate_action")
            or text(row, "event_gate_reason_code")
            or text(row, "event_gate_event_class")
        )
    )
    blocker_overlap = Counter(
        (
            text(row, "reason_code", "NO_QUOTE_UNKNOWN"),
            text(row, "event_gate_action", "unknown"),
            text(row, "event_gate_reason_code", "unknown"),
            text(row, "known_edge_permission", "unknown"),
            text(row, "known_edge_reason", "unknown"),
            text(row, "promotion_state", "unknown"),
        )
        for row in blocked_rows
    )
    cells = Counter(
        (
            text(row, "market_id", "unknown"),
            text(row, "range_label", "unknown"),
            text(row, "reason_code", "NO_QUOTE_UNKNOWN"),
            text(row, "known_edge_reason", "unknown"),
            text(row, "promotion_state", "unknown"),
        )
        for row in blocked_rows
    )
    missing_known_edge_dimensions = Counter()
    for row in blocked_rows:
        if text(row, "known_edge_reason") != "missing_known_edge_record":
            continue
        dimensions = known_edge_row_dimensions(row)
        missing_known_edge_dimensions[(
            text(row, "market_id", "unknown"),
            dimensions.get("hour_utc") or "(missing)",
            dimensions.get("band_distance_bucket") or "(missing)",
            dimensions.get("band_type") or "(missing)",
            dimensions.get("casebook_taxonomy") or "(missing)",
            dimensions.get("regime") or "(missing)",
            dimensions.get("source_freshness_state") or "(missing)",
            dimensions.get("book_imbalance_bucket") or "(missing)",
            text(row, "promotion_state", "unknown"),
        )] += 1
    inferred_missing_known_edge_dimensions = Counter()
    inferred_known_edge_record_matches = Counter()
    inferred_known_edge_record_misses = Counter()
    inferred_known_edge_nearest_record_gaps = Counter()
    known_edge_coverage_action_items = Counter()
    known_edge_required_actions = Counter()
    nearest_gap_cache = {}
    inferred_known_edge_record_match_rows = 0
    inferred_known_edge_record_miss_rows = 0
    for row in blocked_rows:
        if text(row, "reason_code") == "NO_QUOTE_KNOWN_EDGE_PERMISSION":
            dimensions = inferred_known_edge_dimensions(row)
            dimension_key = (
                text(row, "market_id", "unknown"),
                dimensions.get("hour_utc") or "(missing)",
                dimensions.get("band_distance_bucket") or "(missing)",
                dimensions.get("band_type") or "(missing)",
                dimensions.get("casebook_taxonomy") or "(missing)",
                dimensions.get("regime") or "(missing)",
                dimensions.get("source_freshness_state") or "(missing)",
                dimensions.get("book_imbalance_bucket") or "(missing)",
                text(row, "known_edge_reason", "unknown"),
                text(row, "known_edge_permission", "unknown"),
                text(row, "promotion_state", "unknown"),
            )
            known_edge_reason = dimension_key[8]
            if known_edge_reason == "missing_known_edge_record":
                inferred_record = (
                    resolve_known_edge_record(inferred_known_edge_row(row), known_edge_records)
                    if known_edge_records
                    else None
                )
                if inferred_record is not None:
                    required_action = "populate_policy_match_dimensions_then_retest"
                    gap = {
                        "record_permission": inferred_record.get("permission") or "no_quote",
                        "record_reason": inferred_record.get("reason") or "",
                        "record_key": known_edge_record_key(inferred_record),
                    }
                else:
                    required_action = "collect_countable_markouts_before_map_change"
                    gap = nearest_gap_cache.get(dimension_key)
                    if gap is None:
                        gap = nearest_known_edge_record_gap(dimensions) if known_edge_records else {}
                        nearest_gap_cache[dimension_key] = gap
            elif known_edge_reason == "promotion_block":
                required_action = "keep_blocked_until_promotion_gate_passes"
                gap = {}
            elif text(row, "known_edge_permission") == "no_quote":
                required_action = "keep_no_quote_until_evidence_upgrade"
                gap = {}
            else:
                required_action = "review_known_edge_permission_blocker"
                gap = {}
            known_edge_required_actions[(
                required_action,
                text(row, "known_edge_reason", "unknown"),
                text(row, "known_edge_permission", "unknown"),
                text(row, "promotion_state", "unknown"),
            )] += 1
            known_edge_coverage_action_items[(
                *dimension_key,
                required_action,
                gap.get("record_permission") or "",
                gap.get("record_reason") or "",
                gap.get("mismatched_dimensions") or "",
                gap.get("record_key") or "",
            )] += 1
        if text(row, "known_edge_reason") != "missing_known_edge_record":
            continue
        dimensions = inferred_known_edge_dimensions(row)
        dimension_key = (
            text(row, "market_id", "unknown"),
            dimensions.get("hour_utc") or "(missing)",
            dimensions.get("band_distance_bucket") or "(missing)",
            dimensions.get("band_type") or "(missing)",
            dimensions.get("casebook_taxonomy") or "(missing)",
            dimensions.get("regime") or "(missing)",
            dimensions.get("source_freshness_state") or "(missing)",
            dimensions.get("book_imbalance_bucket") or "(missing)",
            text(row, "promotion_state", "unknown"),
        )
        inferred_missing_known_edge_dimensions[dimension_key] += 1
        if not known_edge_records:
            continue
        record = resolve_known_edge_record(inferred_known_edge_row(row), known_edge_records)
        if record is None:
            inferred_known_edge_record_misses[dimension_key] += 1
            inferred_known_edge_record_miss_rows += 1
            gap = nearest_gap_cache.get(dimension_key)
            if gap is None:
                gap = nearest_known_edge_record_gap(dimensions)
                nearest_gap_cache[dimension_key] = gap
            inferred_known_edge_nearest_record_gaps[(
                *dimension_key,
                gap.get("record_permission") or "",
                gap.get("record_reason") or "",
                str(gap.get("matched_dimension_count") or 0),
                str(gap.get("mismatched_dimension_count") or 0),
                gap.get("mismatched_dimensions") or "",
                gap.get("record_key") or "",
            )] += 1
            continue
        inferred_known_edge_record_match_rows += 1
        inferred_known_edge_record_matches[(
            *dimension_key,
            record.get("permission") or "no_quote",
            record.get("reason") or "",
            known_edge_record_key(record),
        )] += 1
    reason_counts = Counter(text(row, "reason_code", "NO_QUOTE_UNKNOWN") for row in blocked_rows)
    known_edge_permission_blocked_rows = sum(
        1 for row in blocked_rows
        if text(row, "reason_code") == "NO_QUOTE_KNOWN_EDGE_PERMISSION"
    )
    stale_input_blocked_rows = sum(
        1 for row in blocked_rows
        if text(row, "reason_code") == "NO_QUOTE_STALE_INPUT"
    )
    known_edge_allowed_false_rows = sum(
        1 for row in blocked_rows
        if text(row, "known_edge_allowed").lower() == "false"
    )
    known_edge_state_rows = sum(
        1 for row in blocked_rows
        if (
            text(row, "known_edge_reason")
            or text(row, "known_edge_permission")
            or text(row, "promotion_state")
            or text(row, "known_edge_allowed")
        )
    )

    def event_gate_is_primary_blocker(row):
        reason = text(row, "reason_code")
        if reason == "NO_QUOTE_INFORMATION_EVENT":
            return True
        return reason in {"", "NO_QUOTE_UNKNOWN"} and text(row, "event_gate_action") == "suppress"

    contextual_event_gate_suppressed_rows = sum(
        1 for row in blocked_rows
        if text(row, "event_gate_action") == "suppress"
    )
    event_gate_suppressed_rows = sum(1 for row in blocked_rows if event_gate_is_primary_blocker(row))
    harvest_only_suppressed_by_other_gate_rows = sum(
        1 for row in blocked_rows
        if text(row, "known_edge_permission") == "harvest_only"
        and text(row, "reason_code") != "NO_QUOTE_KNOWN_EDGE_PERMISSION"
        and event_gate_is_primary_blocker(row)
    )
    return {
        "schema_version": "mm_quote_blocker_diagnostics_v0.8",
        "quote_rows": len(quote_rows or []),
        "quote_permission_rows": quoted_id_count,
        "blocked_rows": len(blocked_rows),
        "blocked_fraction": compact_float(len(blocked_rows) / len(quote_rows or []) if quote_rows else 0.0),
        "known_edge_coverage_map": {
            "path": known_edge_map_diag.get("path"),
            "exists": bool(known_edge_map_diag.get("exists")),
            "schema_version": known_edge_map_diag.get("schema_version"),
            "record_count": int(known_edge_map_diag.get("record_count") or 0),
            "diagnostic_only": True,
        },
        "known_edge_blocked_rows": known_edge_permission_blocked_rows,
        "known_edge_permission_blocked_rows": known_edge_permission_blocked_rows,
        "known_edge_allowed_false_rows": known_edge_allowed_false_rows,
        "known_edge_state_rows": known_edge_state_rows,
        "stale_input_blocked_rows": stale_input_blocked_rows,
        "stale_input_rows": stale_input_blocked_rows,
        "inferred_known_edge_record_match_rows": inferred_known_edge_record_match_rows,
        "inferred_known_edge_record_miss_rows": inferred_known_edge_record_miss_rows,
        "harvest_only_suppressed_by_other_gate_rows": harvest_only_suppressed_by_other_gate_rows,
        "event_gate_suppressed_rows": event_gate_suppressed_rows,
        "contextual_event_gate_suppressed_rows": contextual_event_gate_suppressed_rows,
        "reason_counts": dict(sorted(reason_counts.items())),
        "top_market_reasons": top_counter(market_reason, ["market_id", "reason_code"]),
        "top_known_edge_states": top_counter(
            known_edge,
            ["known_edge_reason", "known_edge_permission", "promotion_state"],
        ),
        "top_event_gate_states": top_counter(
            event_gate,
            ["event_gate_status", "event_gate_action", "event_gate_reason_code", "event_gate_event_class"],
        ),
        "top_blocker_overlaps": top_counter(
            blocker_overlap,
            [
                "reason_code",
                "event_gate_action",
                "event_gate_reason_code",
                "known_edge_permission",
                "known_edge_reason",
                "promotion_state",
            ],
        ),
        "top_blocked_cells": top_counter(
            cells,
            ["market_id", "range_label", "reason_code", "known_edge_reason", "promotion_state"],
        ),
        "top_missing_known_edge_dimensions": top_counter(
            missing_known_edge_dimensions,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "promotion_state",
            ],
        ),
        "top_inferred_missing_known_edge_dimensions": top_counter(
            inferred_missing_known_edge_dimensions,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "promotion_state",
            ],
        ),
        "top_inferred_known_edge_record_matches": top_counter(
            inferred_known_edge_record_matches,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "promotion_state",
                "record_permission",
                "record_reason",
                "record_key",
            ],
        ),
        "top_inferred_known_edge_record_misses": top_counter(
            inferred_known_edge_record_misses,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "promotion_state",
            ],
        ),
        "top_inferred_known_edge_nearest_record_gaps": top_counter(
            inferred_known_edge_nearest_record_gaps,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "promotion_state",
                "nearest_record_permission",
                "nearest_record_reason",
                "matched_dimension_count",
                "mismatched_dimension_count",
                "mismatched_dimensions",
                "nearest_record_key",
            ],
        ),
        "top_known_edge_required_actions": top_counter(
            known_edge_required_actions,
            [
                "required_action",
                "known_edge_reason",
                "known_edge_permission",
                "promotion_state",
            ],
        ),
        "top_known_edge_coverage_action_items": top_counter(
            known_edge_coverage_action_items,
            [
                "market_id",
                "hour_utc",
                "band_distance_bucket",
                "band_type",
                "casebook_taxonomy",
                "regime",
                "source_freshness_state",
                "book_imbalance_bucket",
                "known_edge_reason",
                "known_edge_permission",
                "promotion_state",
                "required_action",
                "nearest_record_permission",
                "nearest_record_reason",
                "mismatched_dimensions",
                "nearest_record_key",
            ],
        ),
    }


def selected_economics_target_date(run_configs, quote_rows):
    dates = set()
    for config in (run_configs or {}).values():
        target = str((config or {}).get("target_date") or "").strip()
        if target:
            dates.add(target)
    for row in quote_rows or []:
        target = str((row or {}).get("target_date") or "").strip()
        if target:
            dates.add(target)
    return next(iter(dates)) if len(dates) == 1 else None


def complete_event_gate_score(quote_score, fill_rows):
    quote_score = dict(quote_score or {})
    exception_fill_rows = 0
    negative_markouts = 0
    exception_net = 0.0
    for row in fill_rows or []:
        if (row.get("event_gate_action") or "") != "allow_exception":
            continue
        exception_fill_rows += 1
        markout = finite_float(row.get("markout_30m_per_share"))
        if markout is not None and markout < 0:
            negative_markouts += 1
        exception_net += finite_float(row.get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0
    quote_score["exception_fill_rows"] = exception_fill_rows
    quote_score["exception_negative_markout_fills"] = negative_markouts
    quote_score["exception_net_pnl_after_fees_incentives_usdc"] = compact_float(exception_net)
    return quote_score


def model_variant_paper_bakeoff_summary(
    variant_quote_rows,
    variant_legs,
    variant_fill_rows,
    variant_queue_rows,
    *,
    config=None,
):
    groups = defaultdict(
        lambda: {
            "quote_rows": 0,
            "quote_permission_rows": 0,
            "quote_legs": 0,
            "conservative_fills": 0,
            "queue_estimated_fill_legs": 0,
            "quote_family": None,
            "quote_role": None,
            "leg_family": None,
            "leg_role": None,
            "fill_family": None,
            "fill_role": None,
            "spread_capture_usdc": 0.0,
            "adverse_selection_30m_usdc": 0.0,
            "settlement_pnl_usdc": 0.0,
            "net_pnl_after_fees_incentives_usdc": 0.0,
        }
    )
    for row in variant_quote_rows or []:
        key = (row.get("model_variant_id") or "unknown", row.get("policy_hash") or "")
        group = groups[key]
        if group["quote_rows"] == 0:
            group["quote_family"] = row.get("model_variant_family")
            group["quote_role"] = row.get("model_variant_role")
        group["quote_rows"] += 1
        group["quote_permission_rows"] += int(quote_permission(row))
    queue_lookup = getattr(variant_queue_rows, "get", None)
    queue_by_leg_id = (
        None
        if queue_lookup
        else {row.get("leg_id"): row for row in variant_queue_rows or []}
    )
    for leg in variant_legs or []:
        key = (leg.get("model_variant_id") or "unknown", leg.get("policy_hash") or "")
        group = groups[key]
        if group["quote_legs"] == 0:
            group["leg_family"] = leg.get("model_variant_family")
            group["leg_role"] = leg.get("model_variant_role")
        group["quote_legs"] += 1
        queue = (
            queue_lookup(leg.get("leg_id"))
            if queue_lookup
            else queue_by_leg_id.get(leg.get("leg_id")) or {}
        )
        if (finite_float(queue.get("estimated_fill_size"), 0.0) or 0.0) > 0:
            group["queue_estimated_fill_legs"] += 1
    for fill in variant_fill_rows or []:
        key = (fill.get("model_variant_id") or "unknown", fill.get("policy_hash") or "")
        group = groups[key]
        if group["conservative_fills"] == 0:
            group["fill_family"] = fill.get("model_variant_family")
            group["fill_role"] = fill.get("model_variant_role")
        group["conservative_fills"] += 1
        for field in (
            "spread_capture_usdc",
            "adverse_selection_30m_usdc",
            "settlement_pnl_usdc",
            "net_pnl_after_fees_incentives_usdc",
        ):
            group[field] += finite_float(fill.get(field), 0.0) or 0.0
    rows = []
    for key in sorted(groups):
        variant_id, policy_id = key
        group = groups[key]
        quote_rows = int(group["quote_rows"])
        quote_permission_rows = int(group["quote_permission_rows"])
        row = {
            "model_variant_id": variant_id,
            "model_variant_family": (
                group.get("quote_family")
                or group.get("leg_family")
                or group.get("fill_family")
                or ""
            ),
            "model_variant_role": (
                group.get("quote_role")
                or group.get("leg_role")
                or group.get("fill_role")
                or ""
            ),
            "policy_id": policy_id,
            "quote_rows": quote_rows,
            "quote_permission_rows": quote_permission_rows,
            "quote_permission_rate": (
                compact_float(quote_permission_rows / quote_rows) if quote_rows else 0.0
            ),
            "quote_legs": int(group["quote_legs"]),
            "conservative_fills": int(group["conservative_fills"]),
            "queue_estimated_fill_legs": int(group["queue_estimated_fill_legs"]),
            "net_pnl_after_fees_incentives_usdc": compact_float(
                group["net_pnl_after_fees_incentives_usdc"]
            ),
            "settlement_pnl_usdc": compact_float(group["settlement_pnl_usdc"]),
            "spread_capture_usdc": compact_float(group["spread_capture_usdc"]),
            "adverse_selection_30m_usdc": compact_float(
                group["adverse_selection_30m_usdc"]
            ),
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


def skipped_model_variant_paper_bakeoff_summary(reason="skip_model_variants"):
    return {
        "schema_version": "mm_model_variant_paper_bakeoff_v0.1",
        "status": "SKIPPED",
        "reason": reason,
        "score_basis": "not_run",
        "quote_rows": 0,
        "quote_legs": 0,
        "conservative_fills": 0,
        "queue_estimated_fill_legs": 0,
        "policy_pair_count": 0,
        "model_variant_by_policy": [],
        "clustered_promotion_gate": {
            "status": "SKIPPED",
            "method": "not_run",
            "reason": reason,
            "pair_count": 0,
            "pass_pair_count": 0,
            "pairs": [],
        },
        "promotion_gate": {
            "status": "SKIPPED",
            "method": "not_run",
            "reason": reason,
            "pair_count": 0,
            "pass_pair_count": 0,
            "pairs": [],
        },
    }


def skipped_fill_simulation_diagnostics(legs, reason="skip_fill_simulation"):
    event_slugs = sorted({leg.get("event_slug") for leg in legs or [] if leg.get("event_slug")})
    return {
        event_slug: {
            "status": "SKIPPED",
            "reason": reason,
            "trade_rows": 0,
            "missing_size_trade_rows": 0,
            "book_rows": 0,
            "mark_rows": 0,
            "settlement_available": False,
        }
        for event_slug in event_slugs
    }


def skipped_fill_evidence_completeness(legs, reason="skip_fill_simulation"):
    quote_leg_count = len(legs or [])
    return {
        "schema_version": "mm_fill_evidence_completeness_v0.1",
        "execution_evidence_schema_version": EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "status": "SKIPPED",
        "reason": reason,
        "promotion_grade": False,
        "blockers": ["fill_simulation_skipped"],
        "quote_legs": quote_leg_count,
        "vacuous": quote_leg_count <= 0,
        "strict_trade_through_fill_count": 0,
        "strict_trade_through_filled_shares": 0.0,
        "queue_status_counts": {},
        "missing_size_trade_rows": 0,
        "rejected_execution_evidence_rows": 0,
        "conflicting_execution_evidence_rows": 0,
        "missing_book_queue_legs": 0,
        "missing_trade_size_queue_legs": 0,
        "unresolved_resting_quote_count": len(legs or []),
        "events_without_trade_rows": sorted({leg.get("event_slug") for leg in legs or [] if leg.get("event_slug")}),
        "events_without_book_rows": sorted({leg.get("event_slug") for leg in legs or [] if leg.get("event_slug")}),
        "clob_recon_book_rows": 0,
        "clob_recon_slice_rows": 0,
        "clob_recon_coverage_source": reason,
        "by_market_hour_token": [],
        "event_diagnostics": [
            {
                "event_slug": event_slug,
                "status": "SKIPPED",
                "reason": reason,
                "trade_rows": 0,
                "missing_size_trade_rows": 0,
                "rejected_execution_evidence_rows": 0,
                "conflicting_execution_evidence_rows": 0,
                "book_rows": 0,
                "mark_rows": 0,
                "settlement_available": False,
            }
            for event_slug in sorted({leg.get("event_slug") for leg in legs or [] if leg.get("event_slug")})
        ],
    }


def decisive_resting_check(legs, diagnostics):
    unresolved = []
    unresolved_count = 0
    for leg in legs:
        event_diag = diagnostics.get(leg["event_slug"]) or {}
        if event_diag.get("settlement_available") and leg["quote_expires_at"] > leg["quote_time"]:
            continue
        if not event_diag.get("settlement_available"):
            unresolved_count += 1
            if len(unresolved) < 50:
                unresolved.append({
                    "leg_id": leg["leg_id"],
                    "event_slug": leg["event_slug"],
                    "market_id": leg["market_id"],
                    "reason": "settlement_missing_for_resting_quote_audit",
                })
    return {
        "unresolved_resting_quote_count": unresolved_count,
        "unresolved_resting_quotes": unresolved,
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


BLOCKING_EXECUTION_REJECTION_KEYS = (
    "rejected_invalid_execution_rows",
    "rejected_missing_condition_rows",
    "rejected_invalid_size_rows",
    "rejected_invalid_side_rows",
    "rejected_missing_exchange_time_rows",
    "rejected_negative_latency_rows",
    "rejected_missing_identity_rows",
    "rejected_ambiguous_raw_link_rows",
    "rejected_conflicting_raw_link_rows",
    "rejected_conflicting_raw_link_identity_rows",
    "rejected_invalid_raw_link_exchange_time_rows",
    "rejected_conflicting_raw_link_exchange_time_rows",
)


def fill_evidence_completeness_summary(legs, fill_rows, queue_rows, diagnostics, decisive_resting, clob_recon, config):
    config = {**DEFAULT_CONFIG, **(config or {})}
    quote_leg_count = len(legs or [])
    queue_counts = Counter(row.get("status") or "unknown" for row in queue_rows or [])
    queue_lookup = getattr(queue_rows, "get", None)
    queue_by_leg = (
        None
        if queue_lookup
        else {row.get("leg_id"): row for row in queue_rows or []}
    )
    missing_size_trade_rows = sum(int(row.get("missing_size_trade_rows") or 0) for row in diagnostics.values())
    rejected_execution_evidence_rows = sum(
        int(row.get(key) or 0)
        for row in diagnostics.values()
        for key in BLOCKING_EXECUTION_REJECTION_KEYS
    )
    conflicting_execution_evidence_rows = sum(
        int(row.get("conflicting_representation_rows") or 0)
        for row in diagnostics.values()
    )
    missing_book_queue_legs = queue_counts.get("missing_book", 0)
    missing_trade_size_queue_legs = queue_counts.get("missed_missing_trade_size", 0)
    clob_summary = (clob_recon or {}).get("summary") or {}
    unresolved_count = int((decisive_resting or {}).get("unresolved_resting_quote_count") or 0)
    by_slice = defaultdict(lambda: {
        "quote_legs": 0,
        "quoted_shares": 0.0,
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
            leg.get("range_label") or "",
            hour,
            leg.get("clob_token_id") or "",
            leg.get("side") or "",
        )

    def add_queue_evidence(item, queue):
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

    for leg in legs or []:
        key = key_for_leg(leg)
        item = by_slice[key]
        item["market_id"], item["range_label"], item["hour_utc"], item["clob_token_id"], item["side"] = key
        item["quote_legs"] += 1
        item["quoted_shares"] += finite_float(leg.get("quote_size"), 0.0) or 0.0
        queue = (
            queue_lookup(leg.get("leg_id"))
            if queue_lookup
            else queue_by_leg.get(leg.get("leg_id")) or {}
        )
        add_queue_evidence(item, queue)

    for fill in fill_rows or []:
        fill_hour = hour_bucket(fill.get("fill_time_utc"))
        key = (
            fill.get("market_id") or "",
            fill.get("range_label") or "",
            fill_hour,
            fill.get("clob_token_id") or "",
            fill.get("side") or "",
        )
        item = by_slice[key]
        item["market_id"], item["range_label"], item["hour_utc"], item["clob_token_id"], item["side"] = key
        item["strict_trade_through_fills"] += 1
        item["strict_trade_through_filled_shares"] += finite_float(fill.get("fill_size"), 0.0) or 0.0

    slice_rows = []
    for _, row in sorted(by_slice.items()):
        quote_legs = int(row.get("quote_legs") or 0)
        incomplete = (
            int(row.get("missing_book_queue_legs") or 0)
            + int(row.get("missing_trade_size_queue_legs") or 0)
        )
        slice_rows.append({
            **row,
            "quoted_shares": compact_float(row.get("quoted_shares")),
            "strict_trade_through_filled_shares": compact_float(row.get("strict_trade_through_filled_shares")),
            "queue_estimated_filled_shares": compact_float(row.get("queue_estimated_filled_shares")),
            "incomplete_market_data_leg_fraction": compact_float(incomplete / quote_legs if quote_legs else 0.0),
        })
    slice_rows.sort(
        key=lambda row: (
            int(row.get("missing_book_queue_legs") or 0) + int(row.get("missing_trade_size_queue_legs") or 0),
            finite_float(row.get("incomplete_market_data_leg_fraction"), 0.0) or 0.0,
            int(row.get("quote_legs") or 0),
            row.get("market_id") or "",
            row.get("range_label") or "",
            row.get("hour_utc") or "",
            row.get("side") or "",
        ),
        reverse=True,
    )

    event_rows = []
    for event_slug, row in sorted((diagnostics or {}).items()):
        rejected_rows = sum(
            int(row.get(key) or 0)
            for key in BLOCKING_EXECUTION_REJECTION_KEYS
        )
        event_rows.append({
            "event_slug": event_slug,
            "trade_rows": int(row.get("trade_rows") or 0),
            "missing_size_trade_rows": int(row.get("missing_size_trade_rows") or 0),
            "rejected_execution_evidence_rows": rejected_rows,
            "conflicting_execution_evidence_rows": int(
                row.get("conflicting_representation_rows") or 0
            ),
            "book_rows": int(row.get("book_rows") or 0),
            "mark_rows": int(row.get("mark_rows") or 0),
            "settlement_available": bool(row.get("settlement_available")),
        })
    event_rows.sort(
        key=lambda row: (
            int(row.get("missing_size_trade_rows") or 0),
            1 if int(row.get("trade_rows") or 0) == 0 else 0,
            1 if int(row.get("book_rows") or 0) == 0 else 0,
            row.get("event_slug") or "",
        ),
        reverse=True,
    )

    blockers = []
    if quote_leg_count <= 0:
        blockers.append("no_quote_legs")
    if missing_size_trade_rows > int(config.get("fill_evidence_max_missing_size_trade_rows", 0)):
        blockers.append("missing_size_trade_rows")
    if rejected_execution_evidence_rows > 0:
        blockers.append("rejected_execution_evidence_rows")
    if conflicting_execution_evidence_rows > 0:
        blockers.append("conflicting_execution_evidence_rows")
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
        "execution_evidence_schema_version": EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCK",
        "promotion_grade": not blockers,
        "blockers": blockers,
        "quote_legs": quote_leg_count,
        "vacuous": quote_leg_count <= 0,
        "reason": "no_quote_legs" if quote_leg_count <= 0 else None,
        "strict_trade_through_fill_count": len(fill_rows or []),
        "strict_trade_through_filled_shares": compact_float(sum_field(fill_rows or [], "fill_size")),
        "queue_status_counts": dict(sorted(queue_counts.items())),
        "missing_size_trade_rows": missing_size_trade_rows,
        "rejected_execution_evidence_rows": rejected_execution_evidence_rows,
        "conflicting_execution_evidence_rows": conflicting_execution_evidence_rows,
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


class _DeferredPaperPayload(dict):
    """Payload whose detail rows remain disk-backed until artifact writing."""

    def __init__(self, payload, aggregation):
        super().__init__(payload)
        self._aggregation = aggregation

    def close(self):
        aggregation = self._aggregation
        if aggregation is not None:
            self._aggregation = None
            aggregation.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _build_paper_payload(
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    run_folders=None,
    run_folder_target_date=None,
    run_folder_latest_n=None,
    run_folder_evidence_mode=None,
    selected_run_folders=None,
    selected_run_folder_selection=None,
    scoring_input_paths_by_folder=None,
    scoring_input_bindings_by_folder=None,
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
    known_edge_coverage_map=None,
    include_model_variants=True,
    include_fill_simulation=True,
    stream_run_inputs=True,
    materialize_output_rows=True,
    _spill_cleanup=None,
):
    config = {**DEFAULT_CONFIG, **(config or {})}
    generated_at = generated_at_iso(now)
    discovered_run_folders = discover_run_folders(runs_root, run_folders=run_folders)
    if selected_run_folders is None:
        candidate_run_folders, run_folder_selection = select_run_folders_for_paper(
            discovered_run_folders,
            explicit_run_folders=bool(run_folders),
            target_date=run_folder_target_date,
            latest_n=run_folder_latest_n,
            evidence_mode=run_folder_evidence_mode,
        )
    else:
        candidate_run_folders = [Path(folder) for folder in selected_run_folders]
        run_folder_selection = dict(selected_run_folder_selection or {})
        if not run_folder_selection:
            _, run_folder_selection = select_run_folders_for_paper(
                candidate_run_folders,
                explicit_run_folders=True,
            )
    available_run_folder_count = run_folder_selection.get(
        "available_run_folders_before_selection"
    )
    if available_run_folder_count is None:
        available_run_folder_count = len(discovered_run_folders)
    available_run_folder_count = int(available_run_folder_count)
    run_folders, eligibility_by_folder, excluded_run_folders = split_run_folders_by_eligibility(candidate_run_folders)
    aggregation = None
    if stream_run_inputs:
        aggregation = MakerPaperRunAggregation(
            None,
            config=config,
            include_model_variants=include_model_variants,
            include_fill_simulation=include_fill_simulation,
            scoring_input_paths_by_folder=scoring_input_paths_by_folder,
            scoring_input_bindings_by_folder=scoring_input_bindings_by_folder,
        )
        if _spill_cleanup is not None:
            _spill_cleanup.append(aggregation)
        for folder in run_folders:
            aggregation.add_run_folder(
                folder,
                eligibility_by_folder=eligibility_by_folder,
            )
        aggregation.finalize_cross_run_state()
        quote_rows = aggregation.quoted_rows
        legs = aggregation.legs
        model_variant_quote_rows = aggregation.quoted_model_variant_rows
        model_variant_legs = aggregation.model_variant_legs
        run_configs = aggregation.run_configs
    else:
        base_input_paths = None
        variant_input_paths = None
        base_input_bindings = None
        variant_input_bindings = None
        if scoring_input_paths_by_folder is not None:
            normalized_input_paths = {
                str(Path(folder)): paths
                for folder, paths in scoring_input_paths_by_folder.items()
            }
            try:
                base_input_paths = {
                    str(Path(folder)): normalized_input_paths[str(Path(folder))]["base"]
                    for folder in run_folders
                }
                variant_input_paths = {
                    str(Path(folder)): normalized_input_paths[str(Path(folder))]["model_variant"]
                    for folder in run_folders
                }
            except KeyError as exc:
                raise ValueError("incomplete explicit maker scoring input paths") from exc
        if scoring_input_bindings_by_folder is not None:
            if scoring_input_paths_by_folder is None:
                raise ValueError(
                    "maker scoring input bindings require explicit input paths"
                )
            normalized_input_bindings = {
                str(Path(folder)): bindings
                for folder, bindings in scoring_input_bindings_by_folder.items()
            }
            try:
                base_input_bindings = {
                    str(Path(folder)): normalized_input_bindings[str(Path(folder))]["base"]
                    for folder in run_folders
                }
                variant_input_bindings = {
                    str(Path(folder)): normalized_input_bindings[str(Path(folder))]["model_variant"]
                    for folder in run_folders
                }
            except KeyError as exc:
                raise ValueError(
                    "incomplete explicit maker scoring input bindings"
                ) from exc
        quote_rows, run_configs = load_quote_rows(
            run_folders,
            eligibility_by_folder=eligibility_by_folder,
            input_paths_by_folder=base_input_paths,
            input_bindings_by_folder=base_input_bindings,
        )
        legs = quote_legs(quote_rows, config)
        model_variant_quote_rows = []
        model_variant_legs = []
        if include_model_variants and include_fill_simulation:
            model_variant_quote_rows, _model_variant_run_configs = load_model_variant_quote_rows(
                run_folders,
                eligibility_by_folder=eligibility_by_folder,
                input_paths_by_folder=variant_input_paths,
                input_bindings_by_folder=variant_input_bindings,
            )
            model_variant_legs = quote_legs(model_variant_quote_rows, config)
    quote_row_count = len(quote_rows)
    quote_permission_row_count = sum(1 for row in quote_rows if quote_permission(row))
    live_trade_permission_row_count = sum(
        1 for row in quote_rows if bool_value(row.get("live_trade_permission"), False)
    )
    model_variant_quote_row_count = len(model_variant_quote_rows)
    anti_overfit = anti_overfit_summary(quote_rows, run_configs)
    quote_uptime = quote_uptime_summary(quote_rows, legs)
    quote_exposure = _guardrail_quote_exposure(quote_rows, config)
    event_gate_quote_score = score_event_gate_decisions(quote_rows, fill_rows=[])
    known_edge_coverage_map_path = (
        Path(known_edge_coverage_map)
        if known_edge_coverage_map
        else Path(backtest_root) / DEFAULT_KNOWN_EDGE_OUT.name
    )
    known_edge_coverage_records, known_edge_coverage_diag = load_known_edge_map(known_edge_coverage_map_path)
    blocker_diagnostics = quote_blocker_diagnostics(
        quote_rows,
        legs,
        known_edge_records=known_edge_coverage_records,
        known_edge_map_diag=known_edge_coverage_diag,
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
        or selected_economics_target_date(run_configs, quote_rows)
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
    economics_snapshot = read_json(
        exchange_economics_snapshot_path or exchange_economics.DEFAULT_SNAPSHOT,
        {},
    ) or {}
    base_economics_coverage = exchange_economics.bind_legs_to_market_economics(
        legs,
        economics_snapshot,
        gate=exchange_gate,
    )
    variant_economics_coverage = exchange_economics.bind_legs_to_market_economics(
        model_variant_legs,
        economics_snapshot,
        gate=exchange_gate,
    )
    economics_leg_coverage = {
        "required": bool(exchange_gate.get("required")),
        "platform": economics_snapshot.get("platform"),
        "leg_count": (
            int(base_economics_coverage.get("leg_count") or 0)
            + int(variant_economics_coverage.get("leg_count") or 0)
        ),
        "bound_leg_count": (
            int(base_economics_coverage.get("bound_leg_count") or 0)
            + int(variant_economics_coverage.get("bound_leg_count") or 0)
        ),
        "missing_leg_count": (
            int(base_economics_coverage.get("missing_leg_count") or 0)
            + int(variant_economics_coverage.get("missing_leg_count") or 0)
        ),
        "missing_token_ids": sorted(set(
            list(base_economics_coverage.get("missing_token_ids") or [])
            + list(variant_economics_coverage.get("missing_token_ids") or [])
        ))[:50],
    }
    economics_leg_coverage["ok"] = economics_leg_coverage["missing_leg_count"] == 0
    exchange_gate = exchange_economics.gate_with_leg_coverage(
        exchange_gate,
        economics_leg_coverage,
    )
    active_event_slugs = {leg.get("event_slug") for leg in legs if leg.get("event_slug")}
    if include_fill_simulation:
        clob_recon = load_or_build_clob_recon(
            clob_recon_path,
            snapshots_root,
            active_event_slugs,
            now=now,
        )
    else:
        clob_recon = {
            "schema_version": "clob_book_recon_v0.1",
            "coverage_source": "skip_fill_simulation",
            "summary": {},
        }
    reward_score_diagnostics = build_reward_score_diagnostics(
        quote_rows,
        legs,
        exchange_gate=exchange_gate,
        economics_snapshot=economics_snapshot,
        config=config,
        clob_recon=clob_recon,
    )
    del quote_rows
    gc.collect()
    casebook_event_slugs = {
        leg.get("event_slug")
        for source in (legs or [], model_variant_legs or [])
        for leg in source
        if leg.get("event_slug")
    }
    casebook_index = (
        load_casebook_index(casebook_path, event_slugs=casebook_event_slugs)
        if include_fill_simulation
        else {}
    )
    if include_fill_simulation:
        fill_rows, queue_rows, diagnostics, _ = simulate_conservative_fills(
            legs,
            snapshots_root,
            casebook_index,
            config,
            ledger_root=ledger_root,
        )
    else:
        fill_rows = []
        queue_rows = []
        diagnostics = skipped_fill_simulation_diagnostics(legs)
    if include_model_variants and include_fill_simulation:
        (
            model_variant_fill_rows,
            model_variant_queue_rows,
            model_variant_diagnostics,
            _,
        ) = simulate_conservative_fills(
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
    else:
        model_variant_fill_rows = []
        model_variant_queue_rows = []
        model_variant_diagnostics = {}
        model_variant_bakeoff = skipped_model_variant_paper_bakeoff_summary(
            "skip_model_variants" if not include_model_variants else "skip_fill_simulation"
        )
    queue_summary = Counter(row.get("status") for row in queue_rows)
    slices = build_markout_slices(fill_rows, config)
    early_hour_guardrail_shadow = build_early_hour_guardrail_shadow(
        fill_rows,
        quote_exposure=quote_exposure,
        config=config,
    )
    event_gate_score = complete_event_gate_score(event_gate_quote_score, fill_rows)
    if include_fill_simulation:
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
    else:
        decisive_resting = {
            "status": "SKIPPED",
            "reason": "skip_fill_simulation",
            "unresolved_resting_quote_count": len(legs),
            "unresolved_resting_quotes": [],
        }
        fill_evidence_completeness = skipped_fill_evidence_completeness(legs)
    exchange_fields = exchange_economics.exchange_economics_artifact_fields(exchange_gate)
    def attach_exchange_fields(row):
        row.update({
            "exchange_economics_snapshot_id": exchange_fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": exchange_fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": exchange_fields.get("exchange_economics_evidence_basis"),
        })

    for rows in (fill_rows, model_variant_fill_rows):
        update_each = getattr(rows, "update_each", None)
        if update_each:
            update_each(attach_exchange_fields)
        else:
            for row in rows:
                attach_exchange_fields(row)
    base_gate_status = (
        "OPEN"
        if len(anti_overfit.get("live_forward_days") or []) < int(config["min_edge_allowed_live_days"])
        else "PAPER_DAYS_READY"
    )
    gate_status = "BLOCK" if not exchange_gate.get("ok") else base_gate_status
    summary = {
        "run_folders": len(run_folders),
        "candidate_run_folders": len(candidate_run_folders),
        "available_run_folders_before_selection": available_run_folder_count,
        "bounded_run_selection": run_folder_selection.get("bounded"),
        "run_folder_selection_mode": run_folder_selection.get("mode"),
        "run_folder_selection_warning": run_folder_selection.get("warning"),
        "run_folder_selection": run_folder_selection,
        "excluded_run_folders": len(excluded_run_folders),
        "quote_rows": quote_row_count,
        "quote_permission_rows": quote_permission_row_count,
        "no_quote_rows": max(0, quote_row_count - quote_permission_row_count),
        "quote_permission_rate": compact_float(
            quote_permission_row_count / quote_row_count if quote_row_count else 0.0
        ),
        "live_trade_permission_rows": live_trade_permission_row_count,
        "live_trade_permission_rate": compact_float(
            live_trade_permission_row_count / quote_row_count if quote_row_count else 0.0
        ),
        "quote_legs": len(legs),
        "fill_simulation_included": bool(include_fill_simulation),
        "fill_simulation_status": "RUN" if include_fill_simulation else "SKIPPED",
        "fill_simulation_reason": None if include_fill_simulation else "skip_fill_simulation",
        "model_variant_scoring_included": model_variant_bakeoff.get("status") != "SKIPPED",
        "model_variant_scoring_requested": bool(include_model_variants),
        "model_variant_scoring_status": model_variant_bakeoff.get("status"),
        "model_variant_scoring_reason": model_variant_bakeoff.get("reason"),
        "model_variant_quote_rows": model_variant_quote_row_count,
        "model_variant_quote_legs": len(model_variant_legs),
        "conservative_fills": len(fill_rows),
        "conservative_filled_shares": compact_float(sum_field(fill_rows, "fill_size")),
        "queue_estimated_fill_legs": sum(1 for row in queue_rows if (finite_float(row.get("estimated_fill_size"), 0.0) or 0.0) > 0),
        "queue_estimated_filled_shares": compact_float(sum(finite_float(row.get("estimated_fill_size"), 0.0) or 0.0 for row in queue_rows)),
        "queue_status_counts": dict(sorted(queue_summary.items())),
        "trade_evidence_gaps": {
            "missing_size_trade_rows": sum(row.get("missing_size_trade_rows", 0) for row in diagnostics.values()),
            "rejected_execution_evidence_rows": fill_evidence_completeness.get(
                "rejected_execution_evidence_rows",
                0,
            ),
            "conflicting_execution_evidence_rows": fill_evidence_completeness.get(
                "conflicting_execution_evidence_rows",
                0,
            ),
            "events_without_trade_rows": sorted(
                key for key, row in diagnostics.items() if row.get("trade_rows", 0) == 0
            ),
        },
        "fill_evidence_completeness_status": fill_evidence_completeness.get("status"),
        "fill_evidence_promotion_grade": fill_evidence_completeness.get("promotion_grade"),
        "fill_evidence_blockers": fill_evidence_completeness.get("blockers") or [],
        "fill_evidence_vacuous": fill_evidence_completeness.get("vacuous"),
        "fill_evidence_reason": fill_evidence_completeness.get("reason"),
        "missing_size_trade_rows": fill_evidence_completeness.get("missing_size_trade_rows", 0),
        "rejected_execution_evidence_rows": fill_evidence_completeness.get(
            "rejected_execution_evidence_rows",
            0,
        ),
        "conflicting_execution_evidence_rows": fill_evidence_completeness.get(
            "conflicting_execution_evidence_rows",
            0,
        ),
        "missing_book_queue_legs": fill_evidence_completeness.get("missing_book_queue_legs", 0),
        "unresolved_resting_quote_count": fill_evidence_completeness.get(
            "unresolved_resting_quote_count",
            0,
        ),
        "fill_evidence_completeness": {
            "status": fill_evidence_completeness.get("status"),
            "promotion_grade": fill_evidence_completeness.get("promotion_grade"),
            "blockers": fill_evidence_completeness.get("blockers") or [],
            "vacuous": fill_evidence_completeness.get("vacuous"),
            "reason": fill_evidence_completeness.get("reason"),
            "missing_size_trade_rows": fill_evidence_completeness.get("missing_size_trade_rows", 0),
            "rejected_execution_evidence_rows": fill_evidence_completeness.get(
                "rejected_execution_evidence_rows",
                0,
            ),
            "conflicting_execution_evidence_rows": fill_evidence_completeness.get(
                "conflicting_execution_evidence_rows",
                0,
            ),
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
        "exchange_economics_leg_coverage": economics_leg_coverage,
        "paper_evidence_basis": exchange_gate.get("evidence_basis"),
        **exchange_fields,
        "per_market_live_forward_evidence": per_market_evidence_summary,
        "quote_uptime": quote_uptime,
        "quote_blocker_diagnostics": blocker_diagnostics,
        "event_gate_score": event_gate_score,
        "total_reward_score": reward_score_diagnostics.get("total_reward_score"),
        "counterfactual_reward_usdc": reward_score_diagnostics.get("counterfactual_reward_usdc"),
        "counterfactual_reward_status": reward_score_diagnostics.get("counterfactual_reward_status"),
        "counterfactual_score_share": reward_score_diagnostics.get("counterfactual_score_share"),
        "score_at_or_above_target_size": reward_score_diagnostics.get("score_at_or_above_target_size"),
        "actual_payout_evidence": reward_score_diagnostics.get("actual_payout_evidence"),
        "reward_score_diagnostics": {
            key: value
            for key, value in reward_score_diagnostics.items()
            if key != "scored_legs"
        },
        "clob_recon": clob_recon.get("summary") or {},
        "decisive_resting_audit": decisive_resting,
        "model_variant_bakeoff": {
            "status": model_variant_bakeoff.get("status"),
            "reason": model_variant_bakeoff.get("reason"),
            "score_basis": model_variant_bakeoff.get("score_basis"),
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
        "gate_status_scope": "paper_day_collection_and_exchange_economics_not_live_capital",
        "live_capital_gate_status": "NOT_EVALUATED_BY_MM_PAPER",
        "live_capital_gate_reason": "use weather.market.market_making_readiness; fill evidence, live-forward countability, operator, and platform gates remain separate",
    }
    defer_output_rows = bool(aggregation is not None and not materialize_output_rows)
    if aggregation is not None and materialize_output_rows:
        shadow_rows = early_hour_guardrail_shadow.get("rows") or []
        early_hour_guardrail_shadow = {
            **early_hour_guardrail_shadow,
            "rows": list(shadow_rows),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "runs_root": str(runs_root),
        "snapshots_root": str(snapshots_root),
        "backtest_root": str(backtest_root),
        "run_folder_selection": run_folder_selection,
        "promotion_refresh": str(promotion_refresh),
        "casebook_path": str(casebook_path),
        "exchange_economics_snapshot_path": str(exchange_economics_snapshot_path) if exchange_economics_snapshot_path else None,
        "exchange_economics_gate": exchange_gate,
        "exchange_economics_leg_coverage": economics_leg_coverage,
        **exchange_fields,
        "config": config,
        "summary": summary,
        "clob_recon": clob_recon,
        "fill_evidence_completeness": fill_evidence_completeness,
        "reward_score_diagnostics": reward_score_diagnostics,
        "quote_blocker_diagnostics": blocker_diagnostics,
        "event_diagnostics": diagnostics,
        "run_configs": run_configs,
        "run_folder_eligibility": eligibility_by_folder,
        "per_market_evidence_credits": per_market_evidence_credits,
        "excluded_run_folders": excluded_run_folders,
        "markout_slices": slices,
        "early_hour_guardrail_shadow": early_hour_guardrail_shadow,
        "model_variant_bakeoff": model_variant_bakeoff,
        "model_variant_event_diagnostics": model_variant_diagnostics,
        "model_variant_fills": (
            model_variant_fill_rows if defer_output_rows else list(model_variant_fill_rows)
        ),
        "model_variant_queue_companion": (
            model_variant_queue_rows if defer_output_rows else list(model_variant_queue_rows)
        ),
        "queue_companion": queue_rows if defer_output_rows else list(queue_rows),
        "fills": fill_rows if defer_output_rows else list(fill_rows),
    }
    if aggregation is not None:
        if defer_output_rows:
            return _DeferredPaperPayload(payload, aggregation)
        aggregation.close()
    return payload


def build_paper_payload(*args, **kwargs):
    """Build a paper payload and deterministically clean spill state on errors."""

    spill_cleanup = []
    try:
        return _build_paper_payload(
            *args,
            _spill_cleanup=spill_cleanup,
            **kwargs,
        )
    except BaseException:
        for aggregation in reversed(spill_cleanup):
            aggregation.close()
        raise



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
    try:
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
    except BaseException:
        close_payload = getattr(paper_payload, "close", None)
        if close_payload:
            close_payload()
        raise


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
    parser.add_argument(
        "--run-target-date",
        "--target-date",
        dest="run_target_date",
        default=None,
        help="Score only run folders whose run summary/config target_date matches this date.",
    )
    parser.add_argument(
        "--latest-n",
        type=int,
        default=None,
        help="Score only the latest N run folders after any target-date/evidence-mode filter.",
    )
    parser.add_argument(
        "--evidence-mode",
        default=None,
        help="Score only run folders with this evidence_mode, for example active_day_live_forward.",
    )
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fills-out", default=str(DEFAULT_FILLS_OUT))
    parser.add_argument("--known-edge-out", default=str(DEFAULT_KNOWN_EDGE_OUT))
    parser.add_argument("--known-edge-report-out", default=str(DEFAULT_KNOWN_EDGE_REPORT_OUT))
    parser.add_argument(
        "--known-edge-coverage-map",
        default=None,
        help=(
            "Existing known-edge map used only for quote-blocker coverage diagnostics; "
            "defaults to <backtest-root>/mm_known_edge_map.json."
        ),
    )
    parser.add_argument("--ledger-root", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--exchange-economics-snapshot", default=str(exchange_economics.DEFAULT_SNAPSHOT))
    parser.add_argument("--exchange-economics-target-date", default=None)
    parser.add_argument("--exchange-economics-platform", default=exchange_economics.DEFAULT_PLATFORM)
    parser.add_argument(
        "--skip-model-variants",
        action="store_true",
        help="Skip model-variant bakeoff scoring for faster diagnostic reports; not promotion-grade.",
    )
    parser.add_argument(
        "--skip-fill-simulation",
        action="store_true",
        help="Skip conservative/queue fill simulation for quote/reward diagnostics; not promotion-grade.",
    )
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
        run_folder_target_date=args.run_target_date,
        run_folder_latest_n=args.latest_n,
        run_folder_evidence_mode=args.evidence_mode,
        casebook_path=Path(args.casebook),
        promotion_refresh=Path(args.promotion_refresh),
        config=config,
        now=parse_time(args.now) if args.now else None,
        ledger_root=Path(args.ledger_root) if args.ledger_root else None,
        exchange_economics_snapshot_path=Path(args.exchange_economics_snapshot) if args.exchange_economics_snapshot else None,
        exchange_economics_target_date=args.exchange_economics_target_date,
        exchange_economics_platform=args.exchange_economics_platform,
        known_edge_coverage_map=Path(args.known_edge_coverage_map) if args.known_edge_coverage_map else None,
        include_model_variants=not args.skip_model_variants,
        include_fill_simulation=not args.skip_fill_simulation,
        stream_run_inputs=True,
        materialize_output_rows=False,
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
        f"paper-day gate {summary['gate_status']}, "
        f"live-capital gate {summary['live_capital_gate_status']} -> {args.report_out}"
    )
    return payload


if __name__ == "__main__":
    main()
