"""End-to-end promotion refresh for family-pooled candidates.

This is the Item 33/37 bridge: when more settled market-days appear, one
command refreshes the pinned promotion corpus, location trust, pooled candidate
replay, and per-market promotion decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.backtesting.backtest import fmt_num, fmt_signed, markdown_table
from weather.reporting.location_trust import DEFAULT_OUT as DEFAULT_TRUST_OUT
from weather.reporting.location_trust import score_all_markets
from weather.market.market_registry import all_specs
from weather.calibration.pooled_candidate_replay import (
    DEFAULT_CASEBOOK,
    DEFAULT_MICROSTRUCTURE_ARTIFACT,
    run_pooled_candidate_replay,
)
from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.reporting.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    DEFAULT_QUALITY_GRADES,
    build_promotion_corpus,
    parse_quality_grades,
    write_manifest,
)
from weather.reporting.promotion_gauntlet import DEFAULT_FORECAST_TRACKER, run_promotion_gauntlet
from weather.backtesting.replay_backtest import DEFAULT_BASELINE, FIDELITY_FAITHFUL_L1
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)


SCHEMA_VERSION = "promotion_refresh_v0.1"
DEFAULT_OUT = Path("data") / "backtest" / "f_family_promotion_refresh.json"
DEFAULT_REPORT = Path("data") / "backtest" / "f_family_promotion_refresh_report.md"
DEFAULT_CANDIDATE_REPORT = Path("data") / "backtest" / "pooled_candidate_replay_latest_report.md"
DEFAULT_CANDIDATE_JSON = Path("data") / "backtest" / "pooled_candidate_replay_latest.json"
DEFAULT_CURRENT_REPLAY_REPORT = Path("data") / "backtest" / "pooled_candidate_current_replay_latest_report.md"
DEFAULT_SERVING_GAUNTLET_REPORT = Path("data") / "backtest" / "promotion_gauntlet_latest_report.md"
DEFAULT_SERVING_REPLAY_REPORT = Path("data") / "backtest" / "promotion_replay_latest_report.md"
DEFAULT_FAMILY_UNIT = "F"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _as_path(value):
    return str(Path(value)) if value is not None else None


def _family_specs(family_unit=DEFAULT_FAMILY_UNIT, specs=None):
    source = list(specs) if specs is not None else list(all_specs())
    if str(family_unit or "").lower() == "all":
        return source
    return [spec for spec in source if getattr(spec, "display_unit", None) == family_unit]


def _manifest_summary(manifest, corpus_path):
    summary = manifest.get("summary") or {}
    return {
        "path": str(corpus_path),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "market_day_count": summary.get("market_day_count", 0),
        "snapshot_count": summary.get("snapshot_count", 0),
        "band_row_count": summary.get("band_row_count", 0),
        "identity_record_count": summary.get("identity_record_count", 0),
        "by_market": summary.get("by_market") or {},
        "quality_grades": manifest.get("quality_grades") or [],
        "skipped_count": len(manifest.get("skipped") or []),
        "skipped_by_reason": dict(sorted(
            Counter(item.get("reason") or "unknown" for item in manifest.get("skipped") or []).items()
        )),
    }


def _trust_summary(trust_rows, trust_path, family_ids):
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    family_scores = [
        trust_by_market.get(market_id, {}).get("trust_score")
        for market_id in family_ids
    ]
    family_scores = [score for score in family_scores if score is not None]
    return {
        "path": str(trust_path),
        "market_count": len(trust_rows),
        "family_market_count": len(family_ids),
        "family_min_trust": min(family_scores) if family_scores else None,
        "family_max_trust": max(family_scores) if family_scores else None,
        "by_market": trust_by_market,
    }


def _candidate_summary(candidate_report, candidate_json_path, candidate_report_path):
    aggregate = candidate_report.get("aggregate") or {}
    microstructure = candidate_report.get("microstructure") or {}
    micro_diag = microstructure.get("diagnostics") or {}
    micro_agg = microstructure.get("aggregate") or {}
    micro_gated = microstructure.get("gated") or {}
    micro_gated_agg = micro_gated.get("aggregate") or {}
    bridge = candidate_report.get("conservative_bridge") or {}
    bridge_diag = bridge.get("diagnostics") or {}
    bridge_agg = bridge.get("aggregate") or {}
    market_slices = []
    for row in candidate_report.get("market_rows") or []:
        comparison = row.get("comparison") or {}
        market_slices.append({
            "group": row.get("market_id"),
            "n": comparison.get("n") or row.get("rows") or 0,
            "candidate_brier": comparison.get("candidate_brier"),
            "current_brier": comparison.get("current_brier"),
            "recorded_brier": comparison.get("recorded_brier"),
            "market_brier": comparison.get("market_brier"),
            "delta_vs_current": comparison.get("delta_vs_current"),
            "delta_vs_market": comparison.get("delta_vs_market"),
        })
    return {
        "json_path": _as_path(candidate_json_path),
        "report_path": _as_path(candidate_report_path),
        "verdict": candidate_report.get("verdict"),
        "candidate_market_verdict": candidate_report.get("candidate_market_verdict"),
        "cutover_decision": candidate_report.get("cutover_decision"),
        "artifact": candidate_report.get("artifact") or {},
        "corpus": candidate_report.get("corpus") or {},
        "coverage": candidate_report.get("coverage") or {},
        "replay_gate": candidate_report.get("replay_gate") or {},
        "candidate_shadow_variants": candidate_report.get("candidate_shadow_variants") or {},
        "aggregate": {
            "rows": aggregate.get("n", 0),
            "candidate_brier": aggregate.get("candidate_brier"),
            "current_brier": aggregate.get("current_brier"),
            "recorded_brier": aggregate.get("recorded_brier"),
            "market_brier": aggregate.get("market_brier"),
            "delta_vs_current": aggregate.get("delta_vs_current"),
            "delta_vs_market": aggregate.get("delta_vs_market"),
            "candidate_skill": aggregate.get("candidate_skill"),
        },
        "microstructure": {
            "schema_version": microstructure.get("schema_version"),
            "eligible_rows": micro_diag.get("eligible_rows", 0),
            "predicted_rows": micro_diag.get("predicted_rows", 0),
            "fold_count": micro_diag.get("fold_count", 0),
            "casebook_matched_rows": micro_diag.get("casebook_matched_rows", 0),
            "gated_overlay_rows": micro_diag.get("gated_overlay_rows", 0),
            "gated_base_rows": micro_diag.get("gated_base_rows", 0),
            "artifact_path": micro_diag.get("artifact_path"),
            "gate": microstructure.get("gate") or {},
            "aggregate": {
                "rows": micro_agg.get("n", 0),
                "micro_brier": micro_agg.get("micro_brier"),
                "candidate_brier": micro_agg.get("candidate_brier"),
                "current_brier": micro_agg.get("current_brier"),
                "market_brier": micro_agg.get("market_brier"),
                "delta_vs_candidate": micro_agg.get("delta_vs_candidate"),
                "delta_vs_current": micro_agg.get("delta_vs_current"),
                "delta_vs_market": micro_agg.get("delta_vs_market"),
                "micro_skill": micro_agg.get("micro_skill"),
            },
            "gated_aggregate": {
                "rows": micro_gated_agg.get("n", 0),
                "micro_brier": micro_gated_agg.get("micro_brier"),
                "candidate_brier": micro_gated_agg.get("candidate_brier"),
                "current_brier": micro_gated_agg.get("current_brier"),
                "market_brier": micro_gated_agg.get("market_brier"),
                "delta_vs_candidate": micro_gated_agg.get("delta_vs_candidate"),
                "delta_vs_current": micro_gated_agg.get("delta_vs_current"),
                "delta_vs_market": micro_gated_agg.get("delta_vs_market"),
                "micro_skill": micro_gated_agg.get("micro_skill"),
            },
            "target_slices": microstructure.get("target_slices") or [],
            "gated_target_slices": micro_gated.get("target_slices") or [],
        },
        "conservative_bridge": {
            "schema_version": bridge.get("schema_version"),
            "policy": bridge.get("policy") or {},
            "shadow_variant_rows": bridge_diag.get("shadow_variant_rows", 0),
            "shadow_variant_path": bridge_diag.get("shadow_variant_path"),
            "aggregate": {
                "rows": bridge_agg.get("n", 0),
                "bridge_brier": bridge_agg.get("bridge_brier"),
                "candidate_brier": bridge_agg.get("candidate_brier"),
                "current_brier": bridge_agg.get("current_brier"),
                "market_brier": bridge_agg.get("market_brier"),
                "delta_vs_candidate": bridge_agg.get("delta_vs_candidate"),
                "delta_vs_current": bridge_agg.get("delta_vs_current"),
                "delta_vs_market": bridge_agg.get("delta_vs_market"),
                "bridge_skill": bridge_agg.get("bridge_skill"),
            },
            "by_market": bridge.get("by_market") or [],
        },
        "slices": {
            "by_market": market_slices,
            "by_cutoff_hour": candidate_report.get("by_hour") or [],
            "by_band_type": candidate_report.get("by_bin_type") or [],
            "by_settlement_distance": candidate_report.get("by_settlement_distance") or [],
            "by_clob_taxonomy": micro_gated.get("by_taxonomy") or microstructure.get("by_taxonomy") or [],
            "by_source_freshness": candidate_report.get("by_source_freshness") or [],
        },
    }


def _serving_gauntlet_summary(report, report_path, replay_report_path):
    if not report:
        return None
    return {
        "report_path": _as_path(report_path),
        "replay_report_path": _as_path(replay_report_path),
        "verdict": report.get("verdict"),
        "corpus_ok": report.get("corpus_ok"),
        "fidelity_ok": report.get("fidelity_ok"),
        "baseline_ok": report.get("baseline_ok"),
        "forecast_tracker": report.get("forecast_tracker") or {},
        "market_rows": report.get("market_rows") or [],
        "decomposition": report.get("decomposition") or {},
    }


def _comparison_metrics(comp):
    comp = comp or {}
    return {
        "rows": comp.get("n", 0),
        "candidate_brier": comp.get("candidate_brier"),
        "current_brier": comp.get("current_brier"),
        "recorded_brier": comp.get("recorded_brier"),
        "market_brier": comp.get("market_brier"),
        "delta_vs_current": comp.get("delta_vs_current"),
        "delta_vs_market": comp.get("delta_vs_market"),
        "candidate_skill": comp.get("candidate_skill"),
        "candidate_ece": comp.get("candidate_ece"),
        "base_rate": comp.get("base_rate"),
    }


def _action_for_verdict(verdict):
    if verdict == "PASS":
        return "PROMOTE_CANDIDATE"
    if verdict == "BLOCK":
        return "BLOCK_CANDIDATE"
    return "KEEP_SHADOW"


def _family_title(family_unit):
    if str(family_unit or "").lower() == "all":
        return "All-Market"
    return f"{family_unit or DEFAULT_FAMILY_UNIT}-Family"


def _market_scope_phrase(family_unit):
    if str(family_unit or "").lower() == "all":
        return "market(s)"
    return f"{family_unit or DEFAULT_FAMILY_UNIT} market(s)"


def build_family_decisions(
    manifest,
    trust_rows,
    candidate_report,
    family_unit=DEFAULT_FAMILY_UNIT,
    specs=None,
):
    """Return per-market promotion decisions for a unit family."""
    specs = _family_specs(family_unit, specs=specs)
    family_ids = {spec.id for spec in specs}
    corpus_counts = Counter(
        entry.get("market_id")
        for entry in manifest.get("entries") or []
        if entry.get("market_id") in family_ids
    )
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    candidate_by_market = {
        row.get("market_id"): row
        for row in candidate_report.get("market_rows") or []
        if row.get("market_id")
    }
    replay_gate = candidate_report.get("replay_gate") or {"global_ok": True}
    global_ok = bool(replay_gate.get("global_ok", True))

    decisions = []
    for spec in sorted(specs, key=lambda item: item.id):
        row = candidate_by_market.get(spec.id)
        if row:
            verdict = row.get("verdict") or "BLOCK"
            reason = row.get("reason") or ""
            snapshots = row.get("snapshots", 0)
            band_rows = row.get("rows", 0)
            metrics = _comparison_metrics(row.get("comparison"))
        else:
            verdict = "SHADOW"
            reason = "no pinned candidate rows for this family market"
            snapshots = 0
            band_rows = 0
            metrics = _comparison_metrics(None)

        if verdict == "PASS" and not global_ok:
            verdict = "BLOCK"
            reason = f"global replay gate failed: {replay_gate.get('corpus_message') or replay_gate.get('fidelity_message')}"

        trust = trust_by_market.get(spec.id) or {}
        decisions.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "family_unit": family_unit,
            "action": _action_for_verdict(verdict),
            "verdict": verdict,
            "reason": reason,
            "settled_days_in_corpus": int(corpus_counts.get(spec.id, 0)),
            "candidate_days": row.get("days", 0) if row else 0,
            "candidate_snapshots": snapshots,
            "candidate_band_rows": band_rows,
            "trust_score": trust.get("trust_score"),
            "trust_grade": trust.get("grade"),
            "trust_settled_days": trust.get("settled_days"),
            "metrics": metrics,
        })

    counts = Counter(item["action"] for item in decisions)
    return {
        "family_unit": family_unit,
        "family_market_count": len(specs),
        "global_replay_gate_ok": global_ok,
        "promote_markets": [item["market_id"] for item in decisions if item["action"] == "PROMOTE_CANDIDATE"],
        "shadow_markets": [item["market_id"] for item in decisions if item["action"] == "KEEP_SHADOW"],
        "blocked_markets": [item["market_id"] for item in decisions if item["action"] == "BLOCK_CANDIDATE"],
        "action_counts": dict(sorted(counts.items())),
        "markets": decisions,
    }


def _decision_table_rows(decisions):
    rows = []
    for item in decisions:
        metrics = item.get("metrics") or {}
        rows.append([
            item.get("market_id"),
            item.get("candidate_days"),
            item.get("candidate_snapshots"),
            item.get("candidate_band_rows"),
            f"{item.get('trust_score', '-')}/100 {item.get('trust_grade', '')}".strip(),
            fmt_num(metrics.get("candidate_brier")),
            fmt_num(metrics.get("current_brier")),
            fmt_num(metrics.get("market_brier")),
            fmt_signed(metrics.get("delta_vs_current"), 4),
            fmt_signed(metrics.get("delta_vs_market"), 4),
            item.get("action"),
            item.get("reason") or "-",
        ])
    return rows


def _readiness_market_details(decisions, action):
    market_rows = decisions.get("markets") or []
    details = []
    for item in market_rows:
        if item.get("action") != action:
            continue
        metrics = item.get("metrics") or {}
        details.append({
            "market_id": item.get("market_id"),
            "action": action,
            "reason": item.get("reason") or "-",
            "candidate_brier": metrics.get("candidate_brier"),
            "current_brier": metrics.get("current_brier"),
            "market_brier": metrics.get("market_brier"),
            "delta_vs_current": metrics.get("delta_vs_current"),
            "delta_vs_market": metrics.get("delta_vs_market"),
        })
    if details:
        return details
    fallback_key = "shadow_markets" if action == "KEEP_SHADOW" else "blocked_markets"
    return [
        {
            "market_id": market_id,
            "action": action,
            "reason": "-",
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
        for market_id in decisions.get(fallback_key) or []
    ]


def promotion_readiness(candidate, serving, decisions):
    blockers = []
    market_scope = _market_scope_phrase(decisions.get("family_unit"))
    aggregate = candidate.get("aggregate") or {}
    delta_vs_market = aggregate.get("delta_vs_market")
    if delta_vs_market is not None and delta_vs_market > 0:
        blockers.append({
            "category": "candidate_market_skill",
            "severity": "open",
            "detail": (
                f"aggregate candidate trails market Brier by {delta_vs_market:+.4f}; "
                "do not claim broad Polymarket edge"
            ),
        })
    shadow_details = _readiness_market_details(decisions, "KEEP_SHADOW")
    shadow_markets = [row.get("market_id") for row in shadow_details if row.get("market_id")]
    if shadow_markets:
        blockers.append({
            "category": "per_market_shadow",
            "severity": "open",
            "detail": (
                f"{len(shadow_markets)} {market_scope} remain shadow: "
                f"{', '.join(shadow_markets)}"
            ),
            "market_details": shadow_details,
        })
    blocked_details = _readiness_market_details(decisions, "BLOCK_CANDIDATE")
    blocked_markets = [row.get("market_id") for row in blocked_details if row.get("market_id")]
    if blocked_markets:
        blockers.append({
            "category": "per_market_block",
            "severity": "block",
            "detail": (
                f"{len(blocked_markets)} {market_scope} are blocked: "
                f"{', '.join(blocked_markets)}"
            ),
            "market_details": blocked_details,
        })
    if serving and serving.get("verdict") == "BLOCK":
        blockers.append({
            "category": "current_serving_gauntlet",
            "severity": "block",
            "detail": "current-serving gauntlet is BLOCK; inspect serving market rows before promotion",
        })
    return {
        "status": "READY" if not blockers else "OPEN",
        "blockers": blockers,
        "shadow_market_details": shadow_details,
        "blocked_market_details": blocked_details,
    }


def _readiness_table_rows(readiness):
    blockers = (readiness or {}).get("blockers") or []
    if not blockers:
        return [["ready", "info", "no promotion readiness blockers"]]
    return [
        [row.get("category"), row.get("severity"), row.get("detail")]
        for row in blockers
    ]


def _readiness_market_detail_rows(readiness):
    rows = []
    for item in (readiness or {}).get("shadow_market_details") or []:
        rows.append([
            item.get("market_id"),
            item.get("action"),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_current"), 4),
            fmt_signed(item.get("delta_vs_market"), 4),
            item.get("reason") or "-",
        ])
    for item in (readiness or {}).get("blocked_market_details") or []:
        rows.append([
            item.get("market_id"),
            item.get("action"),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_current"), 4),
            fmt_signed(item.get("delta_vs_market"), 4),
            item.get("reason") or "-",
        ])
    return rows


def _slice_delta_vs_market(row):
    value = row.get("delta_vs_market")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slice_brier(row):
    if row.get("micro_brier") is not None:
        return row.get("micro_brier")
    return row.get("candidate_brier")


def _candidate_gap_driver_rows(candidate, limit=12):
    slices = (candidate or {}).get("slices") or {}
    sources = [
        ("market", slices.get("by_market") or []),
        ("cutoff_hour", slices.get("by_cutoff_hour") or []),
        ("band_type", slices.get("by_band_type") or []),
        ("settlement_distance", slices.get("by_settlement_distance") or []),
        ("clob_taxonomy", slices.get("by_clob_taxonomy") or []),
        ("source_freshness", slices.get("by_source_freshness") or []),
    ]
    rows = []
    for slice_name, items in sources:
        for item in items:
            delta_market = _slice_delta_vs_market(item)
            n = int(item.get("n") or item.get("rows") or 0)
            if delta_market is None or delta_market <= 0 or n <= 0:
                continue
            rows.append({
                "slice": slice_name,
                "group": item.get("group"),
                "rows": n,
                "brier": _slice_brier(item),
                "market_brier": item.get("market_brier"),
                "delta_vs_current": item.get("delta_vs_current"),
                "delta_vs_market": delta_market,
                "excess_brier_rows": delta_market * n,
            })
    rows.sort(key=lambda row: row["excess_brier_rows"], reverse=True)
    return rows[:limit]


def _candidate_source_freshness_rows(candidate):
    slices = (candidate or {}).get("slices") or {}
    rows = []
    for item in slices.get("by_source_freshness") or []:
        delta_market = _slice_delta_vs_market(item)
        n = int(item.get("n") or item.get("rows") or 0)
        if delta_market is None or n <= 0:
            continue
        rows.append({
            "group": item.get("group"),
            "rows": n,
            "brier": _slice_brier(item),
            "market_brier": item.get("market_brier"),
            "delta_vs_current": item.get("delta_vs_current"),
            "delta_vs_market": delta_market,
            "excess_brier_rows": delta_market * n,
        })
    rows.sort(key=lambda row: row["excess_brier_rows"], reverse=True)
    return rows


def _gap_driver_table_rows(rows, include_slice=True):
    output = []
    for row in rows:
        cells = []
        if include_slice:
            cells.append(row.get("slice"))
        cells.extend([
            row.get("group") if row.get("group") not in (None, "") else "-",
            row.get("rows", 0),
            fmt_num(row.get("brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
            fmt_num(row.get("excess_brier_rows")),
        ])
        output.append(cells)
    if output:
        return output
    return [["-", "-", 0, "-", "-", "-", "-", "-"]] if include_slice else [["-", 0, "-", "-", "-", "-", "-"]]


def _serving_table_rows(serving):
    rows = []
    for row in (serving or {}).get("market_rows") or []:
        comp = row.get("comparison") or {}
        rows.append([
            row.get("market_id"),
            row.get("verdict"),
            row.get("rows", 0),
            fmt_num(comp.get("replayed_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            fmt_signed(comp.get("code_effect"), 4),
            row.get("reason") or "-",
        ])
    return rows


def _serving_blocking_source_freshness_rows(serving):
    rows = []
    blocking = ((serving or {}).get("decomposition") or {}).get("blocking_markets") or {}
    for market_id, slices in sorted(blocking.items()):
        for item in (slices or {}).get("by_source_freshness") or []:
            code_effect = item.get("code_effect")
            n = int(item.get("n") or 0)
            try:
                excess = float(code_effect) * n
            except (TypeError, ValueError):
                excess = None
            rows.append([
                market_id,
                item.get("group") if item.get("group") not in (None, "") else "-",
                n,
                fmt_num(item.get("replayed_brier")),
                fmt_num(item.get("recorded_brier")),
                fmt_num(item.get("market_brier")),
                fmt_signed(code_effect, 4),
                fmt_num(excess),
            ])
    return rows


def write_report(path, payload):
    path = Path(path)
    corpus = payload.get("corpus") or {}
    candidate = payload.get("candidate") or {}
    candidate_agg = candidate.get("aggregate") or {}
    replay_gate = candidate.get("replay_gate") or {}
    decisions = payload.get("decisions") or {}
    serving = payload.get("serving_gauntlet")
    readiness = payload.get("readiness") or {}

    lines = [
        f"# {_family_title(payload.get('family_unit'))} Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Family unit: `{payload.get('family_unit')}`",
        "",
        "## Decision Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Candidate verdict", candidate.get("verdict") or "-"],
            ["Candidate market-only verdict", candidate.get("candidate_market_verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Readiness status", readiness.get("status") or "-"],
            ["Promote", ", ".join(decisions.get("promote_markets") or []) or "-"],
            ["Shadow", ", ".join(decisions.get("shadow_markets") or []) or "-"],
            ["Blocked", ", ".join(decisions.get("blocked_markets") or []) or "-"],
        ],
    )
    lines += [
        "",
        "## Promotion Readiness Blockers",
        "",
    ]
    lines += markdown_table(
        ["Category", "Severity", "Detail"],
        _readiness_table_rows(readiness),
    )
    readiness_details = _readiness_market_detail_rows(readiness)
    if readiness_details:
        lines += [
            "",
            "### Shadow/Block Explanation Detail",
            "",
        ]
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Reason",
            ],
            readiness_details,
        )
    lines += [
        "",
        "## Refresh Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Artifact", "Path / Hash"],
        [
            ["Promotion corpus", f"{corpus.get('path')} / {corpus.get('corpus_hash')}"],
            ["Location trust", (payload.get("trust") or {}).get("path") or "-"],
            ["Candidate JSON", candidate.get("json_path") or "-"],
            ["Candidate report", candidate.get("report_path") or "-"],
            ["Serving gauntlet", (serving or {}).get("report_path") or "skipped"],
        ],
    )
    lines += [
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count", 0)],
            ["Pinned snapshots", corpus.get("snapshot_count", 0)],
            ["Band rows", corpus.get("band_row_count", 0)],
            ["Identity records", corpus.get("identity_record_count", 0)],
            ["Skipped folders", corpus.get("skipped_count", 0)],
        ],
    )
    lines += [
        "",
        "## Candidate Replay",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", candidate_agg.get("rows", 0)],
            ["Candidate Brier", fmt_num(candidate_agg.get("candidate_brier"))],
            ["Current Brier", fmt_num(candidate_agg.get("current_brier"))],
            ["Recorded Brier", fmt_num(candidate_agg.get("recorded_brier"))],
            ["Market Brier", fmt_num(candidate_agg.get("market_brier"))],
            ["Delta vs current", fmt_signed(candidate_agg.get("delta_vs_current"), 4)],
            ["Delta vs market", fmt_signed(candidate_agg.get("delta_vs_market"), 4)],
        ],
    )
    gap_drivers = _candidate_gap_driver_rows(candidate)
    lines += [
        "",
        "### Candidate Gap Drivers",
        "",
    ]
    lines += markdown_table(
        [
            "Slice",
            "Group",
            "Rows",
            "Candidate/Micro Brier",
            "Market Brier",
            "Delta Current",
            "Delta Market",
            "Excess Brier Rows",
        ],
        _gap_driver_table_rows(gap_drivers),
    )
    source_freshness_rows = _candidate_source_freshness_rows(candidate)
    if source_freshness_rows:
        lines += [
            "",
            "### Source Freshness Slice",
            "",
        ]
        lines += markdown_table(
            [
                "Group",
                "Rows",
                "Candidate/Micro Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Excess Brier Rows",
            ],
            _gap_driver_table_rows(source_freshness_rows, include_slice=False),
        )
    else:
        lines += [
            "",
            "Source-freshness gap drivers are not available in the candidate replay rows yet.",
        ]
    micro = candidate.get("microstructure") or {}
    micro_agg = micro.get("aggregate") or {}
    micro_gated_agg = micro.get("gated_aggregate") or {}
    micro_gate = micro.get("gate") or {}
    if micro:
        lines += [
            "",
            "## Item 38 Microstructure Shadow Score",
            "",
        ]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Eligible CLOB rows", micro.get("eligible_rows", 0)],
                ["OOF predicted rows", micro.get("predicted_rows", 0)],
                ["OOF folds", micro.get("fold_count", 0)],
                ["Casebook-matched rows", micro.get("casebook_matched_rows", 0)],
                ["Gate allowed taxonomies", ", ".join(micro_gate.get("allowed_taxonomies") or []) or "-"],
                ["Gated overlay rows", micro.get("gated_overlay_rows", 0)],
                ["Gated base-fallback rows", micro.get("gated_base_rows", 0)],
                ["Artifact", micro.get("artifact_path") or "-"],
            ],
        )
        lines += ["", "### Aggregate", ""]
        lines += markdown_table(
            ["Scope", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    "Raw overlay",
                    micro_agg.get("rows", 0),
                    fmt_num(micro_agg.get("micro_brier")),
                    fmt_num(micro_agg.get("candidate_brier")),
                    fmt_num(micro_agg.get("market_brier")),
                    fmt_signed(micro_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_agg.get("delta_vs_market"), 4),
                ],
                [
                    "Taxonomy-gated overlay",
                    micro_gated_agg.get("rows", 0),
                    fmt_num(micro_gated_agg.get("micro_brier")),
                    fmt_num(micro_gated_agg.get("candidate_brier")),
                    fmt_num(micro_gated_agg.get("market_brier")),
                    fmt_signed(micro_gated_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_gated_agg.get("delta_vs_market"), 4),
                ],
            ],
        )
        lines += ["", "### Taxonomy Gate", ""]
        lines += markdown_table(
            ["Taxonomy", "Action", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market", "Reason"],
            [
                [
                    row.get("taxonomy") or "-",
                    "ALLOW" if row.get("allowed") else "BASE",
                    row.get("rows", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                    row.get("reason") or "-",
                ]
                for row in micro_gate.get("decisions") or []
            ],
        )
        lines += ["", "### Raw Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("target_slices") or []
            ],
        )
        lines += ["", "### Gated Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("gated_target_slices") or []
            ],
        )
    lines += [
        "",
        "## Global Replay Gate",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if replay_gate.get("corpus_ok") else "FAIL", replay_gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if replay_gate.get("fidelity_ok") else "FAIL", replay_gate.get("fidelity_message") or "-"],
        ],
    )
    if serving:
        lines += [
            "",
            "## Current-Serving Gauntlet",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", serving.get("verdict") or "-"],
                ["Corpus OK", serving.get("corpus_ok")],
                ["Fidelity OK", serving.get("fidelity_ok")],
                ["Regression OK", serving.get("baseline_ok")],
                ["Forecast tracker", (serving.get("forecast_tracker") or {}).get("message") or "-"],
            ],
        )
        lines += ["", "### Serving Gauntlet Markets", ""]
        lines += markdown_table(
            [
                "Market", "Verdict", "Rows", "Replayed Brier", "Recorded Brier",
                "Market Brier", "Code Effect", "Reason",
            ],
            _serving_table_rows(serving),
        )
        blocking_source_rows = _serving_blocking_source_freshness_rows(serving)
        if blocking_source_rows:
            lines += ["", "### Serving Blocking Source Freshness", ""]
            lines += markdown_table(
                [
                    "Market",
                    "Group",
                    "Rows",
                    "Replayed Brier",
                    "Recorded Brier",
                    "Market Brier",
                    "Code Effect",
                    "Excess Brier Rows",
                ],
                blocking_source_rows,
            )
    lines += [
        "",
        "## Per-Market Decisions",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Snaps", "Rows", "Trust", "Candidate Brier",
            "Current Brier", "Market Brier", "Delta Current",
            "Delta Market", "Action", "Reason",
        ],
        _decision_table_rows(decisions.get("markets") or []),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _serving_gauntlet_args(args, corpus_path):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        baseline=args.baseline,
        no_baseline=args.no_baseline,
        forecast_tracker=args.forecast_tracker,
        out=args.serving_gauntlet_report,
        replay_report=args.serving_replay_report,
        tol=args.tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
    )


def _candidate_args(args, corpus_path, long_job_guard_info=None):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        out=args.candidate_report,
        json_out=args.candidate_json,
        replay_report=args.current_replay_report,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        clob_max_age_seconds=args.clob_max_age_seconds,
        casebook=args.casebook,
        candidate_variant_out=getattr(args, "candidate_variant_out", None) or None,
        candidate_variant_id=getattr(args, "candidate_variant_id", None) or None,
        candidate_variant_family=getattr(args, "candidate_variant_family", None) or None,
        candidate_variant_uses_market_features=bool(
            getattr(args, "candidate_variant_uses_market_features", False)
        ),
        candidate_variant_control=bool(getattr(args, "candidate_variant_control", False)),
        microstructure_artifact=args.microstructure_artifact or None,
        microstructure_min_train_rows=args.microstructure_min_train_rows,
        skip_microstructure_overlay=args.skip_microstructure_overlay,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
        long_job_guard_info=long_job_guard_info,
        fail_on_block=False,
    )


def run_promotion_refresh(args):
    with long_job_guard(
        "promotion_refresh",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=not getattr(args, "disable_long_job_guard", False),
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        return _run_promotion_refresh_guarded(args, long_job_guard_info=guard)


def _run_promotion_refresh_guarded(args, long_job_guard_info=None):
    quality_grades = parse_quality_grades(args.quality_grades)
    manifest = build_promotion_corpus(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        as_of=args.as_of,
        quality_grades=quality_grades,
        include_reconstructed=args.include_reconstructed,
        allow_unsettled=args.allow_unsettled,
        market_id=None,
        min_snapshots=args.min_snapshots,
    )
    corpus_path = write_manifest(manifest, args.corpus_out)

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_path = _write_json(args.trust_out, trust_rows)

    candidate_report = run_pooled_candidate_replay(
        _candidate_args(args, corpus_path, long_job_guard_info=long_job_guard_info)
    )

    serving_report = None
    if not args.skip_serving_gauntlet:
        serving_report = run_promotion_gauntlet(_serving_gauntlet_args(args, corpus_path))

    family_ids = [spec.id for spec in _family_specs(args.family_unit)]
    candidate_summary = _candidate_summary(candidate_report, args.candidate_json, args.candidate_report)
    serving_summary = _serving_gauntlet_summary(
        serving_report,
        args.serving_gauntlet_report,
        args.serving_replay_report,
    )
    decisions = build_family_decisions(
        manifest,
        trust_rows,
        candidate_report,
        family_unit=args.family_unit,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "family_unit": args.family_unit,
        "corpus": _manifest_summary(manifest, corpus_path),
        "trust": _trust_summary(trust_rows, trust_path, family_ids),
        "candidate": candidate_summary,
        "serving_gauntlet": serving_summary,
        "decisions": decisions,
        "readiness": promotion_readiness(candidate_summary, serving_summary, decisions),
        "long_job_guard": long_job_guard_info or {},
    }
    out_path = _write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    return payload, out_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Refresh promotion corpus, trust, pooled replay, and family promotion decisions."
    )
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders; defaults to discovered settled folders.")
    parser.add_argument("--family-unit", default=DEFAULT_FAMILY_UNIT, choices=["F", "all"])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--min-snapshots", type=int, default=1)
    parser.add_argument("--corpus-out", default=str(DEFAULT_CORPUS))
    parser.add_argument("--trust-out", default=str(DEFAULT_TRUST_OUT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument("--current-replay-report", default=str(DEFAULT_CURRENT_REPLAY_REPORT))
    parser.add_argument("--serving-gauntlet-report", default=str(DEFAULT_SERVING_GAUNTLET_REPORT))
    parser.add_argument("--serving-replay-report", default=str(DEFAULT_SERVING_REPLAY_REPORT))
    parser.add_argument("--forecast-tracker", default=str(DEFAULT_FORECAST_TRACKER))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--candidate-variant-out", default="",
                        help="Item-69-compatible candidate variant CSV. Empty string disables variant export.")
    parser.add_argument("--candidate-variant-id", default=None)
    parser.add_argument("--candidate-variant-family", default=None)
    parser.add_argument("--candidate-variant-uses-market-features", action="store_true")
    parser.add_argument("--candidate-variant-control", action="store_true")
    parser.add_argument("--microstructure-artifact", default=str(DEFAULT_MICROSTRUCTURE_ARTIFACT))
    parser.add_argument("--microstructure-min-train-rows", type=int, default=500)
    parser.add_argument("--skip-microstructure-overlay", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    payload, out_path, report_path = run_promotion_refresh(args)
    decisions = payload.get("decisions") or {}
    print(
        "Promotion refresh: "
        f"{len(decisions.get('promote_markets') or [])} promote, "
        f"{len(decisions.get('shadow_markets') or [])} shadow, "
        f"{len(decisions.get('blocked_markets') or [])} blocked"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    if args.fail_on_block and decisions.get("blocked_markets"):
        sys.exit(1)


if __name__ == "__main__":
    main()
