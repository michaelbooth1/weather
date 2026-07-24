"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.calibration.pooled_candidate_scoring import ATTRIBUTION_FEATURE_FIELDS
from weather.reporting.serving_gates.model_scoring_liveness import apply_liveness_to_gate, gate_has_liveness_blocker
from weather.reporting.promotion.readers import *  # noqa: F403
from weather.reporting.source_gates.physical_feature_family_ratchet import (
    physical_feature_family_ratchet_operational_contract,
)
from weather.reporting.source_gates.source_family_contracts import (
    source_family_inventory_operational_contract,
)
from weather.schema_registry import schema_version

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

EARLY_HOUR_PROMOTION_BLOCKER_SCHEMA_VERSION = schema_version("early_hour_promotion_blocker")
PROMOTION_ALLOWLIST_SCHEMA_VERSION = schema_version("promotion_allowlist")
SOURCE_MISSINGNESS_LOCATION_GATE_SCHEMA_VERSION = schema_version("source_missingness_location_gate")
DEFAULT_SOURCE_MISSINGNESS_BOTTOM_MARKETS = ("miami", "nyc", "seattle")

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
            blocked_validation = row.get("blocked_validation") or {}
        else:
            verdict = "SHADOW"
            reason = "no pinned candidate rows for this family market"
            snapshots = 0
            band_rows = 0
            metrics = _comparison_metrics(None)
            blocked_validation = {}

        if verdict == "PASS" and not global_ok:
            verdict = "BLOCK"
            reason = f"global replay gate failed: {replay_gate.get('corpus_message') or replay_gate.get('fidelity_message')}"
        if verdict == "PASS" and blocked_validation and not blocked_validation.get("passed"):
            verdict = "BLOCK"
            detail = "; ".join(blocked_validation.get("reasons") or []) or "blocked validation failed"
            reason = f"blocked validation failed: {detail}"

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
            "blocked_validation": blocked_validation,
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


def _candidate_identity(candidate):
    candidate = candidate or {}
    shadow = candidate.get("candidate_shadow_variants") or {}
    active_contract = shadow.get("active_registry_contract") or {}
    artifact = candidate.get("artifact") or {}
    return (
        shadow.get("variant_id")
        or active_contract.get("variant_id")
        or artifact.get("artifact_id")
        or artifact.get("path")
        or candidate.get("json_path")
        or "unknown_candidate"
    )


def _candidate_cutover_allowed(candidate):
    candidate = candidate or {}
    validation_evidence = (
        candidate.get("validation_evidence")
        or (candidate.get("blocked_validation") or {}).get("validation_evidence")
    )
    if validation_evidence == "row_export_surrogate":
        return False
    verdict = str(candidate.get("verdict") or "").upper()
    cutover = str(candidate.get("cutover_decision") or "").upper()
    blocked_verdicts = {"BLOCK", "FAIL", "FAILED", "ERROR"}
    blocked_cutovers = {"DO_NOT_CUT_OVER", "BLOCK", "BLOCKED"}
    return verdict not in blocked_verdicts and cutover not in blocked_cutovers


def _candidate_cutover_blocker(candidate):
    candidate = candidate or {}
    validation_evidence = (
        candidate.get("validation_evidence")
        or (candidate.get("blocked_validation") or {}).get("validation_evidence")
    )
    if validation_evidence == "row_export_surrogate":
        return "candidate evidence is row_export_surrogate preview-only; active_replay_contract is required for serving"
    verdict = candidate.get("verdict") or "missing"
    cutover = candidate.get("cutover_decision") or "missing"
    return f"candidate cutover is not allowed: verdict={verdict}, cutover={cutover}"


def _allowlist_row(
    item,
    *,
    candidate_id,
    generated_at_utc,
    readiness_status,
    candidate_cutover_allowed=True,
    candidate_cutover_blocker="",
):
    metrics = item.get("metrics") or {}
    action = item.get("action") or "BLOCK_CANDIDATE"
    action_promotes = action == "PROMOTE_CANDIDATE"
    readiness_allowed = readiness_status == "READY"
    candidate_recommendation_eligible = (
        action_promotes and candidate_cutover_allowed and readiness_allowed
    )
    # promotion_allowlist_v0.1 is a detached reporting projection.  The
    # source-family scan closure is not yet runtime-verifiable, so this schema
    # must never claim serving permission even when every cached readiness
    # signal agrees.  Preserve recommendation eligibility separately for audit.
    candidate_allowed = False
    reason = item.get("reason") or "-"
    blocker_reason = reason
    if action_promotes and not candidate_cutover_allowed:
        blocker_reason = candidate_cutover_blocker or "candidate cutover is not allowed"
    elif action_promotes and not readiness_allowed:
        blocker_reason = (
            "promotion readiness must be READY before candidate permission; "
            f"observed={readiness_status or 'MISSING'}"
        )
    elif candidate_recommendation_eligible:
        blocker_reason = (
            "promotion_allowlist_v0.1 is detached, non-authorizing evidence; "
            "a runtime-verifiable authorization envelope is required"
        )
    return {
        "market_id": item.get("market_id"),
        "candidate_id": candidate_id,
        "generated_at_utc": generated_at_utc,
        "action": action,
        "verdict": item.get("verdict"),
        "effective_promotion_state": "PASS" if candidate_allowed else ("BLOCK" if action == "BLOCK_CANDIDATE" else "SHADOW"),
        "candidate_cutover_allowed": bool(candidate_cutover_allowed),
        "candidate_cutover_blocker": "" if candidate_cutover_allowed else candidate_cutover_blocker,
        "readiness_status": readiness_status or "MISSING",
        "readiness_required_status": "READY",
        "readiness_permission_allowed": readiness_allowed,
        "candidate_recommendation_eligible": candidate_recommendation_eligible,
        "authorization_schema_supported": False,
        "authorization_status": "NON_AUTHORIZING_SCHEMA",
        "serving_or_release_authorization": False,
        "candidate_serving_allowed": candidate_allowed,
        "candidate_permission_allowed": candidate_allowed,
        "serving_behavior": "candidate" if candidate_allowed else "current_or_shadow",
        "permission_behavior": "candidate_candidate_only" if candidate_allowed else "current_or_harvest_only",
        "blocker_reason": blocker_reason,
        "reason": reason,
        "candidate_brier": metrics.get("candidate_brier"),
        "current_brier": metrics.get("current_brier"),
        "market_brier": metrics.get("market_brier"),
        "delta_vs_current": metrics.get("delta_vs_current"),
        "delta_vs_market": metrics.get("delta_vs_market"),
        "candidate_days": item.get("candidate_days"),
        "candidate_snapshots": item.get("candidate_snapshots"),
        "candidate_band_rows": item.get("candidate_band_rows"),
        "settled_days_in_corpus": item.get("settled_days_in_corpus"),
        "trust_score": item.get("trust_score"),
        "trust_grade": item.get("trust_grade"),
        "blocked_validation": item.get("blocked_validation") or {},
    }


def build_promotion_allowlist(
    decisions,
    candidate,
    *,
    readiness=None,
    family_unit=DEFAULT_FAMILY_UNIT,
    generated_at_utc=None,
    path=None,
):
    generated_at_utc = generated_at_utc or _utc_now()
    candidate = candidate or {}
    candidate_id = _candidate_identity(candidate)
    readiness = readiness if isinstance(readiness, dict) else {}
    readiness_status = readiness.get("status") or "MISSING"
    candidate_cutover_allowed = _candidate_cutover_allowed(candidate)
    candidate_cutover_blocker = "" if candidate_cutover_allowed else _candidate_cutover_blocker(candidate)
    rows = [
        _allowlist_row(
            item,
            candidate_id=candidate_id,
            generated_at_utc=generated_at_utc,
            readiness_status=readiness_status,
            candidate_cutover_allowed=candidate_cutover_allowed,
            candidate_cutover_blocker=candidate_cutover_blocker,
        )
        for item in decisions.get("markets") or []
        if item.get("market_id")
    ]
    rows = sorted(rows, key=lambda row: row.get("market_id") or "")
    action_counts = Counter(row.get("action") for row in rows)
    promote_markets = [row["market_id"] for row in rows if row.get("action") == "PROMOTE_CANDIDATE"]
    shadow_markets = [row["market_id"] for row in rows if row.get("action") == "KEEP_SHADOW"]
    blocked_markets = [row["market_id"] for row in rows if row.get("action") == "BLOCK_CANDIDATE"]
    return {
        "schema_version": PROMOTION_ALLOWLIST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "path": _as_path(path) if path else None,
        "family_unit": family_unit,
        "candidate_id": candidate_id,
        "candidate_verdict": candidate.get("verdict"),
        "candidate_cutover_decision": candidate.get("cutover_decision"),
        "candidate_json_path": candidate.get("json_path"),
        "candidate_report_path": candidate.get("report_path"),
        "readiness_status": readiness_status,
        "readiness_required_status": "READY",
        "readiness_permission_allowed": readiness_status == "READY",
        "readiness_blocker_count": len(readiness.get("blockers") or []),
        "candidate_recommendation_eligible": any(
            row.get("candidate_recommendation_eligible") is True for row in rows
        ),
        "authorization_schema_supported": False,
        "authorization_status": "NON_AUTHORIZING_SCHEMA",
        "serving_or_release_authorization": False,
        "candidate_permission_allowed": any(
            row.get("candidate_permission_allowed") is True for row in rows
        ),
        "candidate_serving_allowed": any(
            row.get("candidate_serving_allowed") is True for row in rows
        ),
        "policy": {
            "candidate_serving_allowed_action": "PROMOTE_CANDIDATE",
            "candidate_cutover_required": "candidate verdict must not be BLOCK and cutover_decision must not be DO_NOT_CUT_OVER",
            "non_promote_behavior": "current_or_shadow",
            "permission_gate": (
                "promotion_allowlist_v0.1 is detached and non-authorizing; "
                "candidate_permission_allowed is always false"
            ),
        },
        "summary": {
            "market_count": len(rows),
            "promote_count": len(promote_markets),
            "shadow_count": len(shadow_markets),
            "blocked_count": len(blocked_markets),
            "action_counts": dict(sorted(action_counts.items())),
        },
        "promote_markets": promote_markets,
        "shadow_markets": shadow_markets,
        "blocked_markets": blocked_markets,
        "markets": rows,
    }


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_shadow_variant_rows(path):
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _scored_probability_rows(rows):
    scored = []
    for row in rows or []:
        outcome = _safe_float(row.get("outcome"))
        candidate = _safe_float(row.get("probability"))
        market = _safe_float(row.get("market_yes"))
        if outcome is None or candidate is None or market is None:
            continue
        scored.append(row)
    return scored


def _probability_summary(rows):
    rows = _scored_probability_rows(rows)
    if not rows:
        return {
            "n": 0,
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
    candidate_errors = []
    current_errors = []
    market_errors = []
    for row in rows:
        outcome = _safe_float(row.get("outcome"))
        candidate = _safe_float(row.get("probability"))
        current = _safe_float(row.get("current_probability"))
        market = _safe_float(row.get("market_yes"))
        candidate_errors.append((candidate - outcome) ** 2)
        if current is not None:
            current_errors.append((current - outcome) ** 2)
        market_errors.append((market - outcome) ** 2)
    candidate_brier = sum(candidate_errors) / len(candidate_errors)
    current_brier = sum(current_errors) / len(current_errors) if current_errors else None
    market_brier = sum(market_errors) / len(market_errors)
    return {
        "n": len(rows),
        "candidate_brier": candidate_brier,
        "current_brier": current_brier,
        "market_brier": market_brier,
        "delta_vs_current": (
            candidate_brier - current_brier
            if current_brier is not None
            else None
        ),
        "delta_vs_market": candidate_brier - market_brier,
    }


def _decoded_missingness(row):
    return sorted(
        field
        for field in ATTRIBUTION_FEATURE_FIELDS
        if row.get(field) in (None, "")
    )


def _missingness_decodes(rows):
    decoded = {}
    counts = Counter()
    markets = defaultdict(set)
    for row in rows or []:
        hash_value = row.get("feature_missingness_hash") or "missingness_unknown"
        counts[hash_value] += 1
        market_id = row.get("market_id")
        if market_id:
            markets[hash_value].add(market_id)
        decoded.setdefault(hash_value, _decoded_missingness(row))
    return [
        {
            "feature_missingness_hash": hash_value,
            "rows": counts[hash_value],
            "markets": sorted(markets[hash_value]),
            "missing_features": decoded.get(hash_value) or [],
            "missing_feature_count": len(decoded.get(hash_value) or []),
        }
        for hash_value, _count in counts.most_common()
    ]


def _grouped_variant_rows(rows, keys):
    groups = defaultdict(list)
    for row in rows or []:
        key = tuple(row.get(field) or "unknown" for field in keys)
        groups[key].append(row)
    output = []
    for key, group_rows in sorted(groups.items(), key=lambda item: item[0]):
        summary = _probability_summary(group_rows)
        output.append({
            **{field: value for field, value in zip(keys, key)},
            **summary,
        })
    output.sort(key=lambda row: (row.get("delta_vs_market") is None, -(row.get("delta_vs_market") or 0.0)))
    return output


def _slice_status(row, market_tolerance, min_rows):
    n = int(row.get("n") or 0)
    delta = row.get("delta_vs_market")
    if n < int(min_rows):
        return "SPARSE"
    if delta is None:
        return "MISSING"
    if float(delta) > float(market_tolerance):
        return "BLOCK"
    return "PASS"


def _slice_blocker(category, row, detail):
    return {
        "category": category,
        "severity": "block",
        "market_id": row.get("market_id"),
        "detail": detail,
        "evidence": row,
    }


def build_source_missingness_location_gate(
    candidate,
    *,
    bottom_markets=DEFAULT_SOURCE_MISSINGNESS_BOTTOM_MARKETS,
    market_tolerance=0.003,
    min_rows=30,
):
    candidate = candidate or {}
    variant_path = (candidate.get("candidate_shadow_variants") or {}).get("path")
    rows = _read_shadow_variant_rows(variant_path)
    scored = _scored_probability_rows(rows)
    bottom = {str(market) for market in bottom_markets or []}
    source_rows = _grouped_variant_rows(scored, ("market_id", "source_freshness_state"))
    source_count_rows = _grouped_variant_rows(scored, ("market_id", "forecast_source_count_bucket"))
    missingness_rows = _grouped_variant_rows(scored, ("market_id", "feature_missingness_hash"))
    decodes = _missingness_decodes(scored)
    decode_by_hash = {row["feature_missingness_hash"]: row for row in decodes}
    blockers = []
    if not variant_path or not scored:
        blockers.append({
            "category": "source_missingness_shadow_export_missing",
            "severity": "block",
            "market_id": None,
            "detail": "candidate shadow variant export with source/missingness context is required",
            "evidence": {
                "candidate_shadow_variant_path": _as_path(variant_path) if variant_path else None,
                "row_count": len(scored),
            },
        })

    for row in source_rows:
        row["status"] = _slice_status(row, market_tolerance, min_rows)
        if (
            row.get("market_id") in bottom
            and row.get("source_freshness_state") == "all_fresh"
            and row["status"] == "BLOCK"
        ):
            blockers.append(_slice_blocker(
                "bottom_market_all_fresh_market_gap",
                row,
                (
                    f"{row.get('market_id')} all-fresh candidate trails market by "
                    f"{row.get('delta_vs_market'):+.4f} > {float(market_tolerance):.4f}"
                ),
            ))

    for row in source_count_rows:
        row["status"] = _slice_status(row, market_tolerance, min_rows)
        if (
            row.get("market_id") in bottom
            and row.get("forecast_source_count_bucket") == "two_sources"
            and row["status"] == "BLOCK"
        ):
            blockers.append(_slice_blocker(
                "bottom_market_two_source_market_gap",
                row,
                (
                    f"{row.get('market_id')} two-source candidate trails market by "
                    f"{row.get('delta_vs_market'):+.4f} > {float(market_tolerance):.4f}"
                ),
            ))

    for row in missingness_rows:
        row["status"] = _slice_status(row, market_tolerance, min_rows)
        decoded = decode_by_hash.get(row.get("feature_missingness_hash")) or {}
        row["missing_features"] = decoded.get("missing_features") or []
        row["missing_feature_count"] = decoded.get("missing_feature_count", 0)
        if row.get("market_id") in bottom and row["status"] == "BLOCK":
            blockers.append(_slice_blocker(
                "bottom_market_high_impact_missingness",
                row,
                (
                    f"{row.get('market_id')} missingness hash "
                    f"{row.get('feature_missingness_hash')} trails market by "
                    f"{row.get('delta_vs_market'):+.4f} > {float(market_tolerance):.4f}"
                ),
            ))

    return {
        "schema_version": SOURCE_MISSINGNESS_LOCATION_GATE_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCK",
        "candidate_shadow_variant_path": _as_path(variant_path) if variant_path else None,
        "market_tolerance": float(market_tolerance),
        "min_rows": int(min_rows),
        "bottom_markets": sorted(bottom),
        "summary": {
            "row_count": len(scored),
            "market_source_freshness_slice_count": len(source_rows),
            "market_forecast_source_count_slice_count": len(source_count_rows),
            "market_feature_missingness_slice_count": len(missingness_rows),
            "decoded_missingness_hash_count": len(decodes),
            "blocker_count": len(blockers),
        },
        "blockers": blockers,
        "first_blocker": blockers[0] if blockers else None,
        "market_source_freshness": source_rows,
        "market_forecast_source_count": source_count_rows,
        "market_feature_missingness": missingness_rows,
        "missingness_hash_decodes": decodes,
    }


def _decision_table_rows(decisions):
    rows = []
    for item in decisions:
        metrics = item.get("metrics") or {}
        blocked = item.get("blocked_validation") or {}
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
            blocked.get("verdict") or "-",
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


def _candidate_ten_minute_variant_ids(candidate_ten_minute_performance):
    payload = candidate_ten_minute_performance or {}
    ids = set()
    for value in payload.get("variant_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    for key in ("candidate_ten_minute_performance", "candidate_item147"):
        nested = payload.get(key) or {}
        for value in nested.get("variant_ids") or []:
            if value not in (None, ""):
                ids.add(str(value))
    gate = payload.get("candidate_ten_minute_gate") or {}
    for value in gate.get("variant_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    return ids


def _is_green_status(status):
    return status in {"PASS", "OK", "READY"}


def _freshness_gate(name, status, detail, *, path=None, severity="block", evidence=None):
    status = status or "MISSING"
    ok = _is_green_status(status)
    return {
        "name": name,
        "status": status,
        "ok": ok,
        "severity": "pass" if ok else severity,
        "detail": detail,
        "path": path,
        "evidence": evidence or {},
    }


def build_evidence_freshness_gate(
    *,
    settled_day_freshness=None,
    data_layer_audit=None,
    ingest_quality_gate=None,
    fleet_observability=None,
    daily_learning=None,
    disk_headroom=None,
):
    """Build the countability gate for location promotion evidence."""
    gates = []
    settled = settled_day_freshness or {}
    settled_summary = settled.get("summary") or {}
    gates.append(_freshness_gate(
        "settled_day_freshness",
        settled.get("status"),
        (
            "settled-day freshness must be PASS before location validation counts; "
            f"target={settled.get('target_date') or '-'}, "
            f"incomplete={settled_summary.get('incomplete_market_count')}, "
            f"missing_replay_status={settled_summary.get('missing_replay_status_count')}"
        ),
        path=settled.get("path"),
        evidence={
            "summary": settled_summary,
            "repair_command": settled.get("repair_command"),
            "replay_status_repair_command": settled.get("replay_status_repair_command"),
        },
    ))

    data_layer = data_layer_audit or {}
    data_summary = data_layer.get("gate_summary") or {}
    gates.append(_freshness_gate(
        "data_layer_audit",
        data_summary.get("status") or data_layer.get("status"),
        (
            "data-layer audit gate must be PASS before location validation counts; "
            f"fail={data_summary.get('fail_count')}, warn={data_summary.get('warn_count')}"
        ),
        path=data_layer.get("path"),
        evidence={
            "gate_summary": data_summary,
            "recommendation_count": data_layer.get("recommendation_count"),
            "p0_remediation_count": data_layer.get("p0_remediation_count"),
        },
    ))

    ingest = ingest_quality_gate or {}
    ingest_reasons = ingest.get("fail_reasons") or ingest.get("warn_reasons") or []
    gates.append(_freshness_gate(
        "ingest_quality_gate",
        ingest.get("status"),
        (
            "ingest quality gate must be PASS before location validation counts"
            + (f": {ingest_reasons[0]}" if ingest_reasons else "")
        ),
        path=ingest.get("path"),
        evidence={
            "summary": ingest.get("summary") or {},
            "fail_reasons": ingest.get("fail_reasons") or [],
            "warn_reasons": ingest.get("warn_reasons") or [],
        },
    ))

    fleet = fleet_observability or {}
    fleet_summary = fleet.get("summary") or {}
    gates.append(_freshness_gate(
        "fleet_observability",
        fleet.get("status"),
        (
            "fleet observability must be OK/PASS before location validation counts; "
            f"live_forward={fleet_summary.get('live_forward_slo_status') or '-'}, "
            f"critical_alerts={fleet_summary.get('critical_alerts')}"
        ),
        path=fleet.get("path"),
        evidence={"summary": fleet_summary},
    ))

    clob_books = fleet.get("clob_books") or {}
    gates.append(_freshness_gate(
        "clob_book_freshness",
        clob_books.get("status"),
        (
            "CLOB book freshness must be PASS before market-informed location evidence counts"
            + (
                f"; blocked={', '.join(clob_books.get('blocked_markets') or [])}"
                if clob_books.get("blocked_markets")
                else ""
            )
        ),
        path=fleet.get("path"),
        evidence=clob_books,
    ))

    learning = daily_learning or {}
    learning_summary = learning.get("summary") or {}
    gates.append(_freshness_gate(
        "daily_learning",
        learning.get("status"),
        (
            "daily-learning rollup must be OK before promotion/readiness evidence counts; "
            f"blockers={learning_summary.get('blocker_count')}"
        ),
        path=learning.get("path"),
        evidence={
            "summary": learning_summary,
            "training_ready": (learning.get("retrain_plan") or {}).get("training_ready"),
            "promotion_ready": (learning.get("retrain_plan") or {}).get("promotion_ready"),
        },
    ))

    disk = disk_headroom or {}
    gates.append(_freshness_gate(
        "artifact_disk_headroom",
        disk.get("status"),
        (
            "artifact disk headroom must satisfy the configured reserve before "
            "promotion/readiness exports count; "
            f"free_bytes={disk.get('free_bytes')}, min_free_bytes={disk.get('min_free_bytes')}"
        ),
        path=disk.get("path"),
        evidence=disk,
    ))

    blockers = [gate for gate in gates if not gate.get("ok")]
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "counts_for_location_validation": not blockers,
        "gate_count": len(gates),
        "blocked_gate_count": len(blockers),
        "gates": gates,
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
    }


def _gate_status(report, key):
    return ((report or {}).get(key) or {}).get("status")


def _gate_first_detail(report, key):
    gate = (report or {}).get(key) or {}
    first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
    return first.get("detail") or ""


def _variant_ids(report, gate_key=None):
    ids = set()
    for value in (report or {}).get("variant_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    if gate_key:
        gate = (report or {}).get(gate_key) or {}
        for value in gate.get("variant_ids") or []:
            if value not in (None, ""):
                ids.add(str(value))
    return ids


def _corpus_hash(report):
    report = report or {}
    for section in (
        report,
        report.get("candidate_item147") or {},
        report.get("candidate_ten_minute_performance") or {},
    ):
        value = (section.get("corpus") or {}).get("corpus_hash") or section.get("corpus_hash")
        if value:
            return value
    return None


def _parse_generated_at(value):
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_status(report, *, now=None, max_age_hours=72):
    generated = _parse_generated_at((report or {}).get("generated_at_utc"))
    if generated is None:
        return {
            "status": "MISSING",
            "generated_at_utc": (report or {}).get("generated_at_utc"),
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now.astimezone(timezone.utc) - generated).total_seconds() / 3600.0)
    return {
        "status": "PASS" if age_hours <= max_age_hours else "STALE",
        "generated_at_utc": generated.isoformat(),
        "age_hours": round(age_hours, 3),
        "max_age_hours": max_age_hours,
    }


def _lineage_check(
    *,
    report,
    gate_key,
    expected_variant_id,
    expected_corpus_hash,
    now=None,
    max_age_hours=72,
):
    variants = _variant_ids(report, gate_key)
    report_hash = _corpus_hash(report)
    freshness = _freshness_status(report, now=now, max_age_hours=max_age_hours)
    return {
        "gate_status": _gate_status(report, gate_key) or "MISSING",
        "variant_ids": sorted(variants),
        "expected_variant_id": expected_variant_id,
        "variant_match": bool(expected_variant_id and expected_variant_id in variants),
        "corpus_hash": report_hash,
        "expected_corpus_hash": expected_corpus_hash,
        "corpus_match": bool(report_hash and expected_corpus_hash and report_hash == expected_corpus_hash),
        "freshness": freshness,
        "first_blocker_detail": _gate_first_detail(report, gate_key),
    }


def _append_blocker(blockers, category, detail, *, evidence=None):
    blockers.append({
        "category": category,
        "severity": "block",
        "detail": detail,
        "evidence": evidence or {},
    })


def build_early_hour_promotion_blocker(
    *,
    candidate,
    hourly_performance=None,
    candidate_hourly_performance=None,
    ten_minute_performance=None,
    candidate_ten_minute_performance=None,
    fleet_observability=None,
    market_tolerance=0.003,
    now=None,
    max_candidate_report_age_hours=72,
):
    candidate = candidate or {}
    candidate_shadow = candidate.get("candidate_shadow_variants") or {}
    candidate_variant_id = candidate_shadow.get("variant_id")
    active_contract = candidate_shadow.get("active_registry_contract") or {}
    candidate_corpus_hash = (candidate.get("corpus") or {}).get("corpus_hash")
    aggregate = candidate.get("aggregate") or {}
    delta_vs_market = aggregate.get("delta_vs_market")
    try:
        delta_vs_market_value = float(delta_vs_market)
    except (TypeError, ValueError):
        delta_vs_market_value = None

    hourly_status = _gate_status(hourly_performance, "hourly_performance_gate") or "MISSING"
    ten_minute_status = _gate_status(ten_minute_performance, "ten_minute_performance_gate") or "MISSING"
    hourly_lineage = _lineage_check(
        report=candidate_hourly_performance,
        gate_key="candidate_hourly_gate",
        expected_variant_id=candidate_variant_id,
        expected_corpus_hash=candidate_corpus_hash,
        now=now,
        max_age_hours=max_candidate_report_age_hours,
    )
    ten_minute_lineage = _lineage_check(
        report=candidate_ten_minute_performance,
        gate_key="candidate_ten_minute_gate",
        expected_variant_id=candidate_variant_id,
        expected_corpus_hash=candidate_corpus_hash,
        now=now,
        max_age_hours=max_candidate_report_age_hours,
    )
    broad_replay = {
        "variant_id": candidate_variant_id,
        "active_registry_contract_present": bool(active_contract),
        "corpus_hash": candidate_corpus_hash,
        "delta_vs_market": delta_vs_market_value,
        "market_tolerance": float(market_tolerance),
        "within_market_tolerance": (
            delta_vs_market_value is not None
            and delta_vs_market_value <= float(market_tolerance)
        ),
    }
    fleet_summary = (fleet_observability or {}).get("summary") or {}
    live_forward_slo = (fleet_observability or {}).get("live_forward_slo") or {}
    clean_day_countability = (fleet_observability or {}).get("clean_active_day_countability") or {}
    early_hour_coverage = (
        (fleet_observability or {}).get("early_hour_coverage_proof")
        or clean_day_countability.get("early_hour_coverage_proof")
        or {}
    )
    early_hour_summary = early_hour_coverage.get("summary") or {}
    production_readiness = {
        "live_forward_slo_status": (
            live_forward_slo.get("status")
            or fleet_summary.get("live_forward_slo_status")
            or "MISSING"
        ),
        "current_code_soak_status": (
            fleet_summary.get("current_code_soak_status")
            or ((fleet_observability or {}).get("current_code_soak") or {}).get("status")
            or "MISSING"
        ),
        "clean_active_day_countability_status": (
            clean_day_countability.get("status")
            or fleet_summary.get("clean_active_day_countability_status")
            or "MISSING"
        ),
        "counts_toward_early_hour_evidence": (
            clean_day_countability.get("counts_toward_early_hour_evidence")
            if clean_day_countability
            else fleet_summary.get("clean_active_day_counts_toward_early_hour_evidence")
        ),
        "early_hour_coverage_status": early_hour_summary.get("status") or fleet_summary.get("early_hour_coverage_status"),
        "early_hour_coverage_countable_markets": (
            early_hour_summary.get("countable_market_count")
            if early_hour_summary
            else fleet_summary.get("early_hour_coverage_countable_markets")
        ),
        "early_hour_coverage_total_snapshots": (
            early_hour_summary.get("total_snapshot_count")
            if early_hour_summary
            else fleet_summary.get("early_hour_coverage_total_snapshots")
        ),
        "clean_active_day_countability": clean_day_countability,
        "early_hour_coverage_proof": early_hour_coverage,
    }

    blockers = []
    if hourly_status in {"BLOCK", "MISSING"}:
        hourly_clear = (
            hourly_lineage["gate_status"] == "PASS"
            and hourly_lineage["variant_match"]
            and hourly_lineage["corpus_match"]
            and hourly_lineage["freshness"]["status"] == "PASS"
        )
        if not hourly_clear:
            _append_blocker(
                blockers,
                "candidate_hourly_mitigation",
                (
                    f"current hourly gate is {hourly_status}; candidate hourly gate must PASS "
                    "with matching variant, corpus hash, and fresh generated_at"
                ),
                evidence=hourly_lineage,
            )
    if ten_minute_status in {"BLOCK", "MISSING"}:
        ten_minute_clear = (
            ten_minute_lineage["gate_status"] == "PASS"
            and ten_minute_lineage["variant_match"]
            and ten_minute_lineage["corpus_match"]
            and ten_minute_lineage["freshness"]["status"] == "PASS"
        )
        if not ten_minute_clear:
            _append_blocker(
                blockers,
                "candidate_ten_minute_mitigation",
                (
                    f"current 10-minute weak-slot gate is {ten_minute_status}; "
                    "candidate 10-minute gate must PASS with matching variant, corpus hash, "
                    "and fresh generated_at"
                ),
                evidence=ten_minute_lineage,
            )
    if not broad_replay["active_registry_contract_present"]:
        _append_blocker(
            blockers,
            "active_replay_export_contract",
            "candidate replay evidence is surrogate-only unless backed by an active registry export contract",
            evidence=broad_replay,
        )
    if not broad_replay["within_market_tolerance"]:
        _append_blocker(
            blockers,
            "broad_replay_market_tolerance",
            (
                "candidate broad replay must be within market tolerance before "
                "early-hour mitigation can clear promotion"
            ),
            evidence=broad_replay,
        )
    if production_readiness["live_forward_slo_status"] not in {"PASS", "OK"}:
        _append_blocker(
            blockers,
            "live_forward_slo",
            (
                "live-forward SLO remains a production-readiness blocker, "
                f"status={production_readiness['live_forward_slo_status']}"
            ),
            evidence=production_readiness,
        )
    if production_readiness["current_code_soak_status"] not in {"PASS", "OK"}:
        _append_blocker(
            blockers,
            "current_code_soak",
            (
                "current-code soak remains a production-readiness blocker, "
                f"status={production_readiness['current_code_soak_status']}"
            ),
            evidence=production_readiness,
        )
    if (
        production_readiness["clean_active_day_countability_status"] not in {"PASS", "OK"}
        or production_readiness["counts_toward_early_hour_evidence"] is not True
    ):
        first_clean_blocker = (clean_day_countability.get("first_blocker") or {})
        _append_blocker(
            blockers,
            "clean_active_day_countability",
            (
                "clean active day is not countable for early-hour evidence, "
                f"status={production_readiness['clean_active_day_countability_status']}; "
                f"first_blocker={first_clean_blocker.get('name') or '-'}"
            ),
            evidence=production_readiness,
        )

    return {
        "schema_version": EARLY_HOUR_PROMOTION_BLOCKER_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCK",
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "current_gates": {
            "hourly_status": hourly_status,
            "hourly_first_blocker": _gate_first_detail(hourly_performance, "hourly_performance_gate"),
            "ten_minute_status": ten_minute_status,
            "ten_minute_first_blocker": _gate_first_detail(ten_minute_performance, "ten_minute_performance_gate"),
        },
        "candidate_gates": {
            "hourly": hourly_lineage,
            "ten_minute": ten_minute_lineage,
        },
        "broad_replay": broad_replay,
        "production_readiness": production_readiness,
    }


def promotion_readiness(
    candidate,
    serving,
    decisions,
    extra_location_transfer=None,
    hourly_performance=None,
    candidate_hourly_performance=None,
    ten_minute_performance=None,
    candidate_ten_minute_performance=None,
    source_family_inventory=None,
    physical_feature_family_ratchet=None,
    fleet_observability=None,
    runtime_identity_evidence=None,
    evidence_freshness=None,
    per_location_artifact_quarantine=None,
    early_hour_promotion_blocker=None,
    source_missingness_location_gate=None,
):
    blockers = []
    market_scope = _market_scope_phrase(decisions.get("family_unit"))
    aggregate = candidate.get("aggregate") or {}
    candidate_shadow = candidate.get("candidate_shadow_variants") or {}
    if candidate_shadow.get("uses_market_features"):
        blockers.append({
            "category": "market_informed_candidate",
            "severity": "block",
            "detail": (
                "candidate variant uses market features; market-informed evidence may support "
                "quote/risk gates but cannot satisfy weather-only core promotion readiness"
            ),
            "evidence": candidate_shadow,
        })
    delta_vs_market = aggregate.get("delta_vs_market")
    if delta_vs_market is not None and delta_vs_market > 0:
        blockers.append({
            "category": "candidate_market_skill",
            "severity": "open",
            "detail": (
                f"aggregate candidate trails market Brier by {delta_vs_market:+.4f}; "
                "broad readiness requires aggregate delta_vs_market <= 0 and daily-first clearance"
            ),
        })
    blocked_validation = candidate.get("blocked_validation") or {}
    if blocked_validation and not blocked_validation.get("passed"):
        blockers.append({
            "category": "blocked_validation",
            "severity": "block",
            "detail": (
                "daily-first blocked validation failed: "
                + ("; ".join(blocked_validation.get("reasons") or []) or "inspect blocked validation gate")
            ),
            "evidence": blocked_validation,
        })
    validation_evidence = candidate.get("validation_evidence") or blocked_validation.get("validation_evidence")
    if validation_evidence == "row_export_surrogate":
        blockers.append({
            "category": "repair_integration",
            "severity": "block",
            "detail": (
                "row-export surrogate evidence is preview-only; serving-changing repairs "
                "must be integrated and re-scored with validation_evidence=active_replay_contract"
            ),
            "evidence": {
                "validation_evidence": validation_evidence,
                "row_export_metric_passed": candidate.get("row_export_metric_passed"),
                "blocked_validation": blocked_validation,
            },
        })
    repair_integration = candidate.get("repair_integration") or {}
    if repair_integration and validation_evidence != "active_replay_contract":
        blockers.append({
            "category": "repair_integration_contract",
            "severity": "block",
            "detail": "integrated repair candidates require active replay/export contract evidence",
            "evidence": {
                "validation_evidence": validation_evidence,
                "repair_integration": repair_integration,
            },
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
    runtime_evidence = runtime_identity_evidence or {}
    if runtime_evidence.get("status") == "BLOCK":
        blockers.append({
            "category": "runtime_identity",
            "severity": "block",
            "detail": (
                "mixed runtime identities block unsegmented promotion evidence: "
                f"{runtime_evidence.get('runtime_identity_count')} identities, "
                f"{runtime_evidence.get('snapshot_row_count')} snapshot rows"
            ),
            "evidence": {
                "blocking_reason": runtime_evidence.get("blocking_reason"),
                "runtime_identity_count": runtime_evidence.get("runtime_identity_count"),
                "snapshot_row_count": runtime_evidence.get("snapshot_row_count"),
                "reconciliation_status": runtime_evidence.get("reconciliation_status"),
            },
        })
    freshness = evidence_freshness or {}
    if freshness and freshness.get("status") != "PASS":
        first = freshness.get("first_blocker") or next(iter(freshness.get("blockers") or []), {})
        blockers.append({
            "category": "location_evidence_freshness",
            "severity": "block",
            "detail": (
                "location promotion evidence is non-countable until freshness gates pass: "
                + (first.get("detail") or "inspect evidence_freshness")
            ),
            "evidence": freshness,
        })
    artifact_quarantine = per_location_artifact_quarantine or {}
    if artifact_quarantine and artifact_quarantine.get("status") != "PASS":
        summary = artifact_quarantine.get("summary") or {}
        violations = artifact_quarantine.get("active_candidate_violations") or []
        blockers.append({
            "category": "per_location_artifact_quarantine",
            "severity": "block",
            "detail": (
                "stale or unregistered per-location artifacts cannot appear as active "
                "promotion candidates; "
                f"active violations={summary.get('active_candidate_violation_count', len(violations))}"
            ),
            "evidence": {
                "status": artifact_quarantine.get("status"),
                "path": artifact_quarantine.get("path"),
                "summary": summary,
                "active_candidate_violations": violations[:12],
            },
        })
    early_hour_blocker = early_hour_promotion_blocker or {}
    if early_hour_blocker and early_hour_blocker.get("status") != "PASS":
        first = next(iter(early_hour_blocker.get("blockers") or []), {})
        blockers.append({
            "category": "early_hour_promotion_blocker",
            "severity": "block",
            "detail": (
                "early-hour promotion remains fail-closed: "
                + (first.get("detail") or "inspect early_hour_promotion_blocker")
            ),
            "evidence": early_hour_blocker,
        })
    source_missingness_gate = source_missingness_location_gate or {}
    if source_missingness_gate and source_missingness_gate.get("status") != "PASS":
        first = source_missingness_gate.get("first_blocker") or next(
            iter(source_missingness_gate.get("blockers") or []),
            {},
        )
        blockers.append({
            "category": "source_missingness_location_gate",
            "severity": "block",
            "detail": (
                "market/source/missingness location gate is BLOCK: "
                + (first.get("detail") or "inspect source_missingness_location_gate")
            ),
            "evidence": source_missingness_gate,
        })
    source_preflight = (source_family_inventory or {}).get("promotion_preflight") or {}
    source_contract = source_family_inventory_operational_contract(
        source_family_inventory
    )
    source_status = source_preflight.get("status")
    if (source_contract or {}).get("status") != "PASS":
        source_status = (
            "MISSING" if not source_family_inventory else "BLOCK"
        )
    if source_status != "PASS":
        blocked_families = source_preflight.get("blocked_families") or []
        blockers.append({
            "category": "source_family_preflight",
            "severity": "block",
            "detail": (
                f"source-family promotion preflight is {source_status or 'MISSING'}"
                + (f": {', '.join(blocked_families)}" if blocked_families else "")
            ),
            "evidence": {
                **source_preflight,
                "operational_contract": source_contract or {},
            },
        })
    physical_ratchet = physical_feature_family_ratchet or {}
    physical_contract = physical_feature_family_ratchet_operational_contract(
        physical_ratchet
    )
    physical_status = physical_ratchet.get("status")
    if (physical_contract or {}).get("status") != "PASS":
        physical_status = (
            "MISSING" if not physical_feature_family_ratchet else "BLOCK"
        )
    if physical_status != "PASS":
        summary = physical_ratchet.get("summary") or {}
        first = physical_ratchet.get("first_blocker") or {}
        blocked_families = ((physical_ratchet.get("rollup") or {}).get("evidence_blocked") or [])
        family_details = physical_ratchet.get("blocked_family_details") or []
        family_detail_text = "; ".join(
            f"{row.get('family_id')}: {row.get('detail')}"
            for row in family_details[:5]
            if row.get("family_id") or row.get("detail")
        )
        if not family_detail_text:
            family_detail_text = first.get("detail") or "inspect physical_feature_family_ratchet"
        blockers.append({
            "category": "physical_feature_family_ratchet",
            "severity": "block",
            "detail": (
                "physical feature-family ratchet is "
                f"{physical_status or 'MISSING'}; "
                f"blocked families={summary.get('blocking_family_count')}; "
                + family_detail_text
            ),
            "evidence": {
                "path": physical_ratchet.get("path"),
                "status": physical_status,
                "summary": summary,
                "blocked_families": blocked_families[:20],
                "blocked_family_details": family_details[:20],
                "first_blocker": first,
                "operational_contract": physical_contract or {},
            },
        })
    fleet_summary = (fleet_observability or {}).get("summary") or {}
    live_forward_status = fleet_summary.get("live_forward_slo_status")
    if fleet_observability is not None and live_forward_status not in {None, "OK", "PASS"}:
        blockers.append({
            "category": "live_forward_slo",
            "severity": "block" if live_forward_status in {"BLOCK", "CRITICAL", "MISSING"} else "open",
            "detail": f"live-forward collection SLO is {live_forward_status}; inspect fleet observability",
            "evidence": {
                "status": live_forward_status,
                "fleet_status": (fleet_observability or {}).get("status"),
                "path": (fleet_observability or {}).get("path"),
            },
        })
    hourly_gate = (hourly_performance or {}).get("hourly_performance_gate") or {}
    if ((hourly_performance or {}).get("scoring_liveness") or {}).get("status") == "BLOCK":
        hourly_gate = apply_liveness_to_gate(hourly_gate, (hourly_performance or {}).get("scoring_liveness") or {})
    hourly_status = hourly_gate.get("status")
    hourly_liveness_blocked = gate_has_liveness_blocker(hourly_gate)
    candidate_hourly_gate = (candidate_hourly_performance or {}).get("candidate_hourly_gate") or {}
    candidate_hourly_status = candidate_hourly_gate.get("status")
    candidate_variant_id = (candidate.get("candidate_shadow_variants") or {}).get("variant_id")
    candidate_hourly_variant_ids = {
        str(value)
        for value in (candidate_hourly_performance or {}).get("variant_ids") or []
        if value not in (None, "")
    }
    candidate_hourly_matches = bool(
        candidate_variant_id and str(candidate_variant_id) in candidate_hourly_variant_ids
    )
    hourly_mitigation = {
        "applied": bool(
            hourly_status in {"BLOCK", "MISSING"}
            and candidate_hourly_status == "PASS"
            and candidate_hourly_matches
            and not hourly_liveness_blocked
        ),
        "current_hourly_status": hourly_status,
        "current_scoring_liveness_blocked": hourly_liveness_blocked,
        "candidate_hourly_status": candidate_hourly_status,
        "candidate_variant_id": candidate_variant_id,
        "candidate_hourly_variant_ids": sorted(candidate_hourly_variant_ids),
        "candidate_hourly_matches": candidate_hourly_matches,
        "current_hourly_gate": hourly_gate,
        "candidate_hourly_gate": candidate_hourly_gate,
    }
    if hourly_status in {"BLOCK", "MISSING"} and not hourly_mitigation["applied"]:
        first = hourly_gate.get("first_blocker") or next(iter(hourly_gate.get("blockers") or []), {})
        blockers.append({
            "category": "hourly_performance_gate",
            "severity": "block" if hourly_status == "BLOCK" else "open",
            "detail": (
                f"hourly performance gate is {hourly_status}: "
                + (first.get("detail") or "inspect hourly model performance report")
            ),
            "evidence": hourly_gate,
        })
    ten_minute_gate = (ten_minute_performance or {}).get("ten_minute_performance_gate") or {}
    if ((ten_minute_performance or {}).get("scoring_liveness") or {}).get("status") == "BLOCK":
        ten_minute_gate = apply_liveness_to_gate(
            ten_minute_gate,
            (ten_minute_performance or {}).get("scoring_liveness") or {},
        )
    ten_minute_status = ten_minute_gate.get("status")
    ten_minute_liveness_blocked = gate_has_liveness_blocker(ten_minute_gate)
    candidate_ten_minute_gate = (candidate_ten_minute_performance or {}).get("candidate_ten_minute_gate") or {}
    candidate_ten_minute_status = candidate_ten_minute_gate.get("status")
    candidate_ten_minute_variant_ids = _candidate_ten_minute_variant_ids(candidate_ten_minute_performance)
    candidate_ten_minute_matches = bool(
        candidate_variant_id and str(candidate_variant_id) in candidate_ten_minute_variant_ids
    )
    ten_minute_mitigation = {
        "applied": bool(
            ten_minute_status in {"BLOCK", "MISSING"}
            and candidate_ten_minute_status == "PASS"
            and candidate_ten_minute_matches
            and not ten_minute_liveness_blocked
        ),
        "current_ten_minute_status": ten_minute_status,
        "current_scoring_liveness_blocked": ten_minute_liveness_blocked,
        "candidate_ten_minute_status": candidate_ten_minute_status,
        "candidate_variant_id": candidate_variant_id,
        "candidate_ten_minute_variant_ids": sorted(candidate_ten_minute_variant_ids),
        "candidate_ten_minute_matches": candidate_ten_minute_matches,
        "current_ten_minute_gate": ten_minute_gate,
        "candidate_ten_minute_gate": candidate_ten_minute_gate,
    }
    if ten_minute_status in {"BLOCK", "MISSING"} and not ten_minute_mitigation["applied"]:
        first = ten_minute_gate.get("first_blocker") or next(iter(ten_minute_gate.get("blockers") or []), {})
        blockers.append({
            "category": "ten_minute_performance_gate",
            "severity": "block" if ten_minute_status == "BLOCK" else "open",
            "detail": (
                f"10-minute performance gate is {ten_minute_status}: "
                + (first.get("detail") or "inspect 10-minute model performance report")
            ),
            "evidence": ten_minute_gate,
        })
    extra_gate = (extra_location_transfer or {}).get("promotion_gate") or {}
    extra_gate_status = extra_gate.get("status")
    if extra_gate_status in {"BLOCK", "BLOCKED", "MISSING"}:
        blockers.append({
            "category": "no_market_extra_location_shadow_lane",
            "severity": "block" if extra_gate_status != "MISSING" else "open",
            "detail": (
                "extra-location shadow lane gate is "
                f"{extra_gate_status}: "
                + ("; ".join(extra_gate.get("reasons") or []) or "inspect transfer report")
            ),
            "evidence": extra_gate,
        })
    elif extra_gate_status == "SHADOW_ONLY":
        blockers.append({
            "category": "no_market_extra_location_shadow_lane",
            "severity": "open",
            "detail": (
                "extra-location shadow lane is inconclusive and cannot affect serving: "
                + ("; ".join(extra_gate.get("reasons") or []) or "inspect transfer report")
            ),
            "evidence": extra_gate,
        })
    return {
        "status": "READY" if not blockers else "OPEN",
        "blockers": blockers,
        "shadow_market_details": shadow_details,
        "blocked_market_details": blocked_details,
        "hourly_performance_mitigation": hourly_mitigation,
        "ten_minute_performance_mitigation": ten_minute_mitigation,
        "evidence_freshness": freshness,
        "per_location_artifact_quarantine": artifact_quarantine,
        "early_hour_promotion_blocker": early_hour_blocker,
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
