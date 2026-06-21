"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

from weather.reporting.promotion_refresh_readers import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

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
    fleet_observability=None,
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
    source_preflight = (source_family_inventory or {}).get("promotion_preflight") or {}
    source_status = source_preflight.get("status")
    if source_family_inventory is not None and source_status != "PASS":
        blocked_families = source_preflight.get("blocked_families") or []
        blockers.append({
            "category": "source_family_preflight",
            "severity": "block",
            "detail": (
                f"source-family promotion preflight is {source_status or 'MISSING'}"
                + (f": {', '.join(blocked_families)}" if blocked_families else "")
            ),
            "evidence": source_preflight,
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
    tape = (fleet_observability or {}).get("tape_backup") or {}
    tape_status = tape.get("status") or fleet_summary.get("tape_backup_status")
    if fleet_observability is not None and tape_status not in {None, "OK", "PASS"}:
        capacity = tape.get("capacity_preflight") or {}
        insufficient = capacity.get("insufficient_bytes")
        detail = f"tape backup status is {tape_status}; promotion readiness requires current backup/restore evidence"
        if insufficient is not None:
            detail += f" ({insufficient} bytes short)"
        blockers.append({
            "category": "tape_backup_sla",
            "severity": "block" if tape_status not in {"WARN"} else "open",
            "detail": detail,
            "evidence": tape,
        })
    hourly_gate = (hourly_performance or {}).get("hourly_performance_gate") or {}
    hourly_status = hourly_gate.get("status")
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
        ),
        "current_hourly_status": hourly_status,
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
    ten_minute_status = ten_minute_gate.get("status")
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
        ),
        "current_ten_minute_status": ten_minute_status,
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
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
