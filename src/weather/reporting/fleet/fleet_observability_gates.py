"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

from weather.reporting.fleet.fleet_observability_loops import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def _gate_from_alerts(name, alerts):
    if any(row.get("severity") == "critical" for row in alerts):
        severity = "critical"
    elif alerts:
        severity = "warning"
    else:
        severity = "ok"
    return {
        "name": name,
        "ok": not alerts,
        "severity": severity,
        "messages": [row.get("message") for row in alerts],
    }


def _broad_slo_rule(gate_name):
    rule = BROAD_SLO_RULES.get(gate_name) or REMEDIATION_RULES.get(gate_name) or {}
    return {
        "root_cause": rule.get("root_cause") or gate_name or "unknown_broad_slo_failure",
        "owner": rule.get("owner") or "unknown",
        "suggested_command": rule.get("suggested_command") or BROAD_SLO_VERIFY_COMMAND,
        "recoverable_same_day": bool(rule.get("recoverable_same_day", False)),
    }


def _recovery_row(component, gate, market, detail, before, rule_override=None):
    rule = _broad_slo_rule(gate)
    if rule_override:
        rule.update({key: value for key, value in rule_override.items() if value is not None})
    return {
        "component": component,
        "gate": gate,
        "status": "BLOCK",
        "market_id": market.get("market_id") or "fleet",
        "event_slug": market.get("event_slug"),
        "target_date": market.get("target_date"),
        "owner": rule["owner"],
        "root_cause": rule["root_cause"],
        "repair_command": rule["suggested_command"],
        "suggested_command": rule["suggested_command"],
        "recoverable_same_day": rule["recoverable_same_day"],
        "before": before,
        "after": "rerun broad live-forward SLO and require PASS before broad countability",
        "verification_command": BROAD_SLO_VERIFY_COMMAND,
        "detail": detail,
    }


def _unique_gates(gates):
    seen = set()
    ordered = []
    for gate in gates:
        if gate in seen:
            continue
        seen.add(gate)
        ordered.append(gate)
    return ordered


def _collection_recovery_gates(row):
    reason = str(row.get("reason") or "").lower()
    gates = []
    if not row.get("snapshots") or "no snapshot" in reason or "no captures" in reason:
        gates.append("snapshot_collection")
    if "gap" in reason:
        gates.append("snapshot_coverage_gap")
    if "afternoon window" in reason or "window close" in reason or "window start" in reason:
        gates.append("afternoon_window_coverage")
    if "latest capture" in reason:
        gates.append("latest_model_row_freshness")
    if not gates:
        gates.append("snapshot_collection")
    return _unique_gates(gates)


def _source_status_recovery(source_status):
    if not source_status:
        return None
    repair_command = source_status.get("repair_command") or SOURCE_PROVIDER_STATUS_COMMAND
    if source_status.get("available") is False:
        return {
            "detail": source_status.get("reason") or "source_status_long.csv unavailable",
            "rule_override": {
                "root_cause": "missing_source_status_tape",
                "owner": "snapshot source-status writer",
                "suggested_command": repair_command,
                "recoverable_same_day": True,
            },
        }
    if source_status.get("trading_evidence_allowed") is False:
        families = source_status.get("families") or {}
        affected = [(name, row) for name, row in sorted(families.items()) if row.get("status") != "healthy"]
        if affected:
            names = [name for name, _ in affected]
            counts = [
                (
                    f"{name} "
                    f"failed={row.get('failed_source_count', 0)} "
                    f"fallback={row.get('fallback_source_count', 0)} "
                    f"rate_limited={row.get('rate_limited_source_count', 0)} "
                    f"settlement_auth={row.get('settlement_auth_failure_source_count', 0)}"
                )
                for name, row in affected
            ]
            settlement_auth_sources = {
                name: [source for source in row.get("settlement_auth_failure_sources") or [] if source]
                for name, row in affected
                if row.get("settlement_auth_failure_source_count")
            }
            fallback_sources = {
                name: [source for source in row.get("fallback_sources") or [] if source]
                for name, row in affected
                if row.get("fallback_source_count")
            }
            rate_limited_sources = {
                name: [source for source in row.get("rate_limited_sources") or [] if source]
                for name, row in affected
                if row.get("rate_limited_source_count")
            }
            detail = (
                "source-status degraded families: "
                + ", ".join(names)
                + " ("
                + "; ".join(counts)
                + ")"
            )
            if fallback_sources:
                source_bits = [
                    f"{name} fallback_sources={','.join(sources)}"
                    for name, sources in sorted(fallback_sources.items())
                ]
                detail += "; " + "; ".join(source_bits)
            if rate_limited_sources:
                source_bits = [
                    f"{name} rate_limited_sources={','.join(sources)}"
                    for name, sources in sorted(rate_limited_sources.items())
                ]
                detail += "; " + "; ".join(source_bits)
            if settlement_auth_sources:
                source_bits = [
                    f"{name} settlement_auth_sources={','.join(sources)}"
                    for name, sources in sorted(settlement_auth_sources.items())
                ]
                detail += "; " + "; ".join(source_bits)
                return {
                    "detail": detail,
                    "rule_override": {
                        "root_cause": "settlement_source_auth_failure",
                        "owner": "snapshot source-status writer / optional provider source",
                        "suggested_command": repair_command,
                        "recoverable_same_day": False,
                    },
                }
            if any(name == "open_meteo" and row.get("fallback_source_count") for name, row in affected):
                return {
                    "detail": detail,
                    "rule_override": {
                        "root_cause": "open_meteo_provider_fallback",
                        "owner": "Open-Meteo quota / forecast source collector",
                        "suggested_command": repair_command,
                        "recoverable_same_day": False,
                    },
                }
            if any(name == "open_meteo" and row.get("rate_limited_source_count") for name, row in affected):
                return {
                    "detail": detail,
                    "rule_override": {
                        "root_cause": "open_meteo_provider_rate_limited",
                        "owner": "Open-Meteo quota / forecast source collector",
                        "suggested_command": repair_command,
                        "recoverable_same_day": False,
                    },
                }
            return {
                "detail": detail,
                "rule_override": {
                    "root_cause": "degraded_source_status",
                    "owner": "snapshot source-status writer",
                    "suggested_command": repair_command,
                    "recoverable_same_day": False,
                },
            }
        return {
            "detail": "source-status degradation blocks trading-grade broad evidence",
            "rule_override": {
                "root_cause": "degraded_source_status",
                "owner": "snapshot source-status writer",
                "suggested_command": repair_command,
                "recoverable_same_day": False,
            },
        }
    return None


def _variant_prediction_recovery_detail(variant_tape):
    if not variant_tape:
        return None
    if variant_tape.get("action_required"):
        return variant_tape.get("reason") or "variant_predictions_long.csv is missing or stale"
    return None


def _collection_recovery_rows(collection):
    rows = []
    for row in (collection or {}).get("markets") or []:
        if row.get("snapshot_action_required", row.get("action_required")):
            cadence_proof = row.get("snapshot_cadence_proof") or {}
            cadence_override = {
                "root_cause": cadence_proof.get("root_cause"),
                "suggested_command": cadence_proof.get("repair_command") or SNAPSHOT_RESTART_COMMAND,
                "recoverable_same_day": cadence_proof.get("recoverable_same_day"),
            } if cadence_proof else None
            before = (
                f"state={row.get('state')}; snapshots={row.get('snapshots')}; "
                f"latest_age_minutes={row.get('latest_age_minutes')}; reason={row.get('reason')}"
            )
            for gate in _collection_recovery_gates(row):
                rows.append(_recovery_row(
                    "snapshot_collection",
                    gate,
                    row,
                    row.get("reason") or "snapshot collection needs attention",
                    before,
                    cadence_override,
                ))
        source_recovery = _source_status_recovery(row.get("source_family_degradation") or {})
        if source_recovery:
            before = (
                f"snapshot_id={(row.get('source_family_degradation') or {}).get('snapshot_id')}; "
                f"affected_family_count={(row.get('source_family_degradation') or {}).get('affected_family_count')}; "
                f"failed_source_count={(row.get('source_family_degradation') or {}).get('failed_source_count')}; "
                f"fallback_source_count={(row.get('source_family_degradation') or {}).get('fallback_source_count')}"
            )
            rows.append(_recovery_row(
                "source_status",
                "source_status_freshness",
                row,
                source_recovery["detail"],
                before,
                source_recovery.get("rule_override"),
            ))
        variant_detail = _variant_prediction_recovery_detail(row.get("variant_prediction_tape") or {})
        if variant_detail:
            variant_tape = row.get("variant_prediction_tape") or {}
            before = (
                f"snapshot_id={variant_tape.get('snapshot_id')}; "
                f"active_variant_count={variant_tape.get('active_variant_count')}; "
                f"latest_rows={variant_tape.get('latest_rows')}; "
                f"expected_latest_rows={variant_tape.get('expected_latest_rows')}"
            )
            rows.append(_recovery_row(
                "variant_prediction_tape",
                "variant_prediction_freshness",
                row,
                variant_detail,
                before,
            ))
    return rows


def _clob_recovery_rows(clob):
    rows = []
    clob = clob or {}
    loop = clob.get("loop") or {}
    state = loop.get("state")
    if state in ("DEAD", "UNKNOWN", "ERRORING", "PAUSED", "DEGRADED"):
        rows.append(_recovery_row(
            "clob_book_capture",
            "clob_book_freshness",
            {"market_id": "fleet"},
            f"CLOB book loop is {state}",
            (
                f"state={state}; heartbeat_age_seconds={loop.get('heartbeat_age_seconds')}; "
                f"last_books_age_seconds={loop.get('last_books_age_seconds')}; last_error={loop.get('last_error')}"
            ),
        ))
    discovery = loop.get("discovery_sanity") or {}
    if discovery and not discovery.get("ok", True):
        rows.append(_recovery_row(
            "clob_book_capture",
            "clob_discovery",
            {"market_id": "fleet"},
            discovery.get("reason") or "CLOB discovery sanity gate failed",
            (
                f"status={discovery.get('status')}; root_cause={discovery.get('root_cause')}; "
                f"market_count={discovery.get('market_count')}"
            ),
        ))
    for row in (clob.get("books") or {}).get("markets") or []:
        if row.get("ok"):
            continue
        rows.append(_recovery_row(
            "clob_book_capture",
            "clob_book_freshness",
            row,
            row.get("reason") or "CLOB book tape needs attention",
            (
                f"captures={row.get('captures')}; trailing_age_seconds={row.get('trailing_age_seconds')}; "
                f"gaps_over_threshold={row.get('gaps_over_threshold')}; max_gap_seconds={row.get('max_gap_seconds')}"
            ),
        ))
    return rows


def optional_market_event_stream_gate(clob):
    clob = clob or {}
    loop = clob.get("loop") or {}
    enrichment = clob.get("enrichment") or {}
    separate_enrichment = enrichment.get("state") not in {None, "NOT_CONFIGURED"}
    source = enrichment if separate_enrichment else loop
    include_history = bool(source.get("include_price_history"))
    include_ws = bool(source.get("include_ws_events"))
    results = source.get("last_market_results") or {}
    issues = []
    if include_history or include_ws:
        for market_id, result in sorted(results.items()):
            if not isinstance(result, dict):
                continue
            books = int(result.get("books") or 0)
            stream_expected = (
                books > 0
                or int(result.get("captured_tokens") or 0) > 0
                or separate_enrichment
            )
            if include_history and stream_expected and int(result.get("price_history_rows") or 0) <= 0:
                issues.append({
                    "market_id": market_id,
                    "stream": "price_history",
                    "severity": "warning",
                    "detail": "price history is enabled but latest loop result wrote zero rows",
                    "books": books,
                    "price_history_rows": int(result.get("price_history_rows") or 0),
                })
            if include_ws:
                ws_error = result.get("ws_error")
                ws_rows = int(result.get("ws_event_rows") or 0)
                ws_messages = int(result.get("ws_messages") or 0)
                if ws_error:
                    issues.append({
                        "market_id": market_id,
                        "stream": "websocket_events",
                        "severity": "warning",
                        "detail": f"WebSocket event capture failed: {ws_error}",
                        "books": books,
                        "ws_messages": ws_messages,
                        "ws_event_rows": ws_rows,
                    })
                elif stream_expected and ws_messages <= 0 and ws_rows <= 0:
                    issues.append({
                        "market_id": market_id,
                        "stream": "websocket_events",
                        "severity": "warning",
                        "detail": "WebSocket events are enabled but latest loop result captured no messages",
                        "books": books,
                        "ws_messages": ws_messages,
                        "ws_event_rows": ws_rows,
                    })
        if not results:
            issues.append({
                "market_id": "fleet",
                "stream": "market_event_streams",
                "severity": "warning",
                "detail": "optional market event streams are enabled but no loop result has been recorded yet",
            })
    status = "DISABLED" if not include_history and not include_ws else ("WARN" if issues else "PASS")
    return {
        "schema_version": "optional_market_event_streams_v0.1",
        "status": status,
        "ok": not issues,
        "include_price_history": include_history,
        "include_ws_events": include_ws,
        "capture_mode": "separate_enrichment" if separate_enrichment else "legacy_loop_or_disabled",
        "enrichment_state": enrichment.get("state") or "NOT_CONFIGURED",
        "market_count": len(results),
        "issue_count": len(issues),
        "issues": issues,
        "blocks_core_model_review": False,
        "counts_toward_live_forward_gate": False,
        "reason": (
            "optional price-history/WebSocket streams are disabled"
            if status == "DISABLED"
            else (
                "optional price-history/WebSocket streams need attention"
                if issues else
                "optional price-history/WebSocket streams are being captured"
            )
        ),
    }


def _observation_recovery_rows(observation):
    alerts = observation_alerts(observation)
    if not alerts:
        return []
    observation = observation or {}
    return [
        _recovery_row(
            "observation_trigger",
            "observation_trigger_health",
            {"market_id": "fleet"},
            alerts[0].get("message") or "observation trigger watcher needs attention",
            (
                f"state={observation.get('state')}; heartbeat_age_seconds={observation.get('heartbeat_age_seconds')}; "
                f"consecutive_errors={observation.get('consecutive_errors')}; last_error={observation.get('last_error')}"
            ),
        )
    ]


def event_metadata_alerts(event_metadata):
    if event_metadata is None:
        return []
    event_metadata = event_metadata or {}
    if not event_metadata or not event_metadata.get("exists", True):
        return [{
            "severity": "critical",
            "market_id": "fleet",
            "category": "event_metadata_validation",
            "message": "event metadata validation artifact is missing",
            "detail": event_metadata,
        }]
    if event_metadata.get("status") != "PASS":
        summary = event_metadata.get("summary") or {}
        first = summary.get("first_blocker") or {}
        return [{
            "severity": "critical",
            "market_id": first.get("market_id") or "fleet",
            "category": "event_metadata_validation",
            "message": (
                f"event metadata validation {event_metadata.get('status')} "
                f"for {event_metadata.get('target_date') or 'active target date'}"
            ),
            "detail": {
                "validation_hash": event_metadata.get("validation_hash"),
                "summary": summary,
                "first_blocker": first,
            },
        }]
    return []


def _event_metadata_recovery_rows(event_metadata):
    alerts = event_metadata_alerts(event_metadata)
    if not alerts:
        return []
    event_metadata = event_metadata or {}
    summary = event_metadata.get("summary") or {}
    first = summary.get("first_blocker") or {}
    first_issue = first.get("first_issue") or {}
    detail = (
        first.get("reason")
        or first_issue.get("detail")
        or alerts[0].get("message")
        or "event metadata validation blocks active-day evidence"
    )
    return [_recovery_row(
        "event_metadata_validation",
        "event_metadata_validation",
        {
            "market_id": first.get("market_id") or "fleet",
            "event_slug": first.get("event_slug"),
            "target_date": first.get("target_date") or event_metadata.get("target_date"),
        },
        detail,
        (
            f"status={event_metadata.get('status')}; "
            f"validation_hash={event_metadata.get('validation_hash')}; "
            f"issue_count={summary.get('issue_count')}; "
            f"first_issue={first_issue.get('code')}"
        ),
        {
            "suggested_command": (
                first.get("remediation_command")
                or event_metadata.get("validation_command")
                or event_metadata.get("refresh_command")
            ),
            "recoverable_same_day": first.get("recoverable_same_day"),
        },
    )]


def broad_live_forward_recovery_rows(collection, clob, observation, event_metadata=None):
    return (
        _event_metadata_recovery_rows(event_metadata)
        + _collection_recovery_rows(collection)
        + _clob_recovery_rows(clob)
        + _observation_recovery_rows(observation)
    )


def _concrete_broad_slo_gates(recovery_rows):
    counts = Counter(row.get("gate") for row in recovery_rows if row.get("gate"))
    gate_names = list(BROAD_SLO_REQUIRED_GATES)
    gate_names.extend(sorted(name for name in counts if name not in BROAD_SLO_REQUIRED_GATES))
    rows_by_gate = {}
    for row in recovery_rows:
        rows_by_gate.setdefault(row.get("gate"), []).append(row)
    gates = []
    for gate_name in gate_names:
        rows = rows_by_gate.get(gate_name) or []
        gates.append({
            "name": gate_name,
            "ok": not rows,
            "severity": "critical" if rows else "ok",
            "messages": [row.get("detail") for row in rows],
            "blocked_market_count": len({row.get("market_id") for row in rows}),
            "owner": (rows[0].get("owner") if rows else _broad_slo_rule(gate_name)["owner"]),
            "repair_command": (rows[0].get("repair_command") if rows else None),
        })
    return gates


def _broad_slo_summary(recovery_rows):
    first = recovery_rows[0] if recovery_rows else {}
    return {
        "recovery_row_count": len(recovery_rows),
        "first_blocking_market": first.get("market_id"),
        "first_blocking_component": first.get("component"),
        "first_blocking_gate": first.get("gate"),
        "first_blocking_owner": first.get("owner"),
        "first_repair_command": first.get("repair_command"),
        "blocking_gate_counts": dict(sorted(Counter(row.get("gate") for row in recovery_rows).items())),
        "blocking_component_counts": dict(sorted(Counter(row.get("component") for row in recovery_rows).items())),
    }


def _fallback_snapshot_root_cause(row):
    reason = str(row.get("reason") or "").lower()
    if "stale code" in reason or "source tree" in reason:
        return "stale_code_restart"
    if "duplicate writer" in reason or "writer lock" in reason:
        return "duplicate_writer_prevention"
    if "disk" in reason or "headroom" in reason or "backpressure" in reason:
        return "disk_backpressure"
    if "provider" in reason or "source delay" in reason or "rate limit" in reason:
        return "provider_source_delay"
    if not row.get("snapshots") or "no snapshot" in reason or "no captures" in reason:
        return "process_down"
    if "latest capture" in reason:
        return "long_iteration_or_stalled_loop"
    if "gap" in reason:
        return "unknown_snapshot_gap"
    if not row.get("snapshot_action_required", row.get("action_required")):
        return "within_cadence"
    return "unknown"


def _snapshot_gap_windows_from_row(row):
    windows = []
    for item in (row.get("snapshot_cadence_proof") or {}).get("gap_windows") or []:
        windows.append({
            "after": item.get("after"),
            "before": item.get("before"),
            "gap_minutes": item.get("gap_minutes"),
        })
    return windows


def _snapshot_cadence_market_proof(row):
    proof = dict(row.get("snapshot_cadence_proof") or {})
    action_required = bool(row.get("snapshot_action_required", row.get("action_required")))
    proof.setdefault("status", "BLOCK" if action_required else "PASS")
    proof.setdefault("counts_so_far", not action_required)
    proof.setdefault("root_cause", _fallback_snapshot_root_cause(row))
    proof.setdefault("root_cause_class", proof.get("root_cause"))
    proof.setdefault("state", row.get("state"))
    proof.setdefault("reason", row.get("reason"))
    proof.setdefault("snapshot_count", row.get("snapshots", 0))
    proof.setdefault("latest_snapshot_id", row.get("latest_snapshot_id"))
    proof.setdefault("latest_age_minutes", row.get("latest_age_minutes"))
    proof.setdefault("freshness_sla_minutes", row.get("freshness_sla_minutes"))
    proof.setdefault("gap_count", len(_snapshot_gap_windows_from_row(row)))
    proof.setdefault("max_gap_minutes", row.get("max_gap_minutes"))
    proof.setdefault("gap_windows", _snapshot_gap_windows_from_row(row))
    proof.setdefault("status_command", SNAPSHOT_STATUS_COMMAND)
    proof.setdefault("repair_command", SNAPSHOT_RESTART_COMMAND)
    proof.setdefault("verification_command", BROAD_SLO_VERIFY_COMMAND)
    proof.setdefault("recoverable_same_day", bool(action_required and not proof.get("gap_windows")))
    proof.setdefault("active_day_countable", proof.get("status") == "PASS")
    proof["market_id"] = row.get("market_id")
    proof["event_slug"] = row.get("event_slug")
    proof["target_date"] = row.get("target_date")
    return proof


def _snapshot_next_unblock_action(blocked, recoverable_same_day, nonrecoverable_active_day_blocked):
    if not blocked:
        return "none"
    if nonrecoverable_active_day_blocked:
        return "collect next active day with zero snapshot_coverage_gap blocked markets"
    if recoverable_same_day:
        return SNAPSHOT_RESTART_COMMAND
    return SNAPSHOT_RESTART_COMMAND


def _snapshot_cadence_proof(collection, recovery_rows):
    provided = (collection or {}).get("snapshot_cadence_proof") or {}
    markets = [_snapshot_cadence_market_proof(row) for row in (collection or {}).get("markets") or []]
    recovery_gates_by_market = {}
    for row in recovery_rows:
        if row.get("component") != "snapshot_collection":
            continue
        market_id = row.get("market_id")
        recovery_gates_by_market.setdefault(market_id, []).append(row.get("gate"))
    for row in markets:
        gates = recovery_gates_by_market.get(row.get("market_id"))
        if gates:
            row["blocking_gates"] = _unique_gates(gates)
            row["status"] = "BLOCK"
        else:
            row.setdefault("blocking_gates", [])
    blocked = [row for row in markets if row.get("status") != "PASS"]
    recoverable_same_day = [
        row for row in blocked if row.get("recoverable_same_day")
    ]
    nonrecoverable_active_day_blocked = [
        row for row in blocked if not row.get("active_day_countable", row.get("status") == "PASS")
    ]
    gap_markets = {
        row.get("market_id")
        for row in markets
        if int(row.get("gap_count") or 0) > 0
    }
    gap_markets.update(
        row.get("market_id")
        for row in recovery_rows
        if row.get("component") == "snapshot_collection" and row.get("gate") == "snapshot_coverage_gap"
    )
    max_gaps = [
        float(row.get("max_gap_minutes"))
        for row in markets
        if row.get("max_gap_minutes") is not None
    ]
    summary = {
        "status": "PASS" if not blocked else "BLOCK",
        "market_count": len(markets),
        "blocked_market_count": len(blocked),
        "snapshot_coverage_gap_market_count": len(gap_markets),
        "snapshot_coverage_gap_blocked_market_count": len(gap_markets),
        "total_gap_count": sum(int(row.get("gap_count") or 0) for row in markets),
        "max_gap_minutes": max(max_gaps) if max_gaps else None,
        "root_cause_counts": dict(sorted(Counter(row.get("root_cause") or "unknown" for row in markets).items())),
        "active_day_countable_market_count": sum(
            1 for row in markets if row.get("active_day_countable", row.get("status") == "PASS")
        ),
        "recoverable_same_day_market_count": len(recoverable_same_day),
        "nonrecoverable_active_day_blocked_market_count": len(nonrecoverable_active_day_blocked),
        "clean_active_day_required": bool(nonrecoverable_active_day_blocked),
        "next_unblock_action": _snapshot_next_unblock_action(
            blocked,
            recoverable_same_day,
            nonrecoverable_active_day_blocked,
        ),
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": BROAD_SLO_VERIFY_COMMAND,
    }
    summary.update({key: value for key, value in (provided.get("summary") or {}).items() if value is not None})
    summary["snapshot_coverage_gap_blocked_market_count"] = len(gap_markets)
    summary["blocked_market_count"] = len(blocked)
    summary["status"] = "PASS" if not blocked else "BLOCK"
    summary["recoverable_same_day_market_count"] = len(recoverable_same_day)
    summary["nonrecoverable_active_day_blocked_market_count"] = len(nonrecoverable_active_day_blocked)
    summary["clean_active_day_required"] = bool(nonrecoverable_active_day_blocked)
    summary["next_unblock_action"] = _snapshot_next_unblock_action(
        blocked,
        recoverable_same_day,
        nonrecoverable_active_day_blocked,
    )
    return {
        "schema_version": "snapshot_cadence_proof_v0.1",
        "summary": summary,
        "markets": sorted(markets, key=lambda row: row.get("market_id") or ""),
        "status_command": SNAPSHOT_STATUS_COMMAND,
        "repair_command": SNAPSHOT_RESTART_COMMAND,
        "verification_command": BROAD_SLO_VERIFY_COMMAND,
    }


def live_forward_slo_gate(collection, clob, observation, event_metadata=None):
    """Single fail-closed gate for live-forward MM evidence.

    A paper/live day can count only when the slow weather snapshot tape, fast
    CLOB book tape, and observation-trigger watcher are all fresh and gap-free.
    """
    gates = [
        _gate_from_alerts("event_metadata_validation", event_metadata_alerts(event_metadata)),
        _gate_from_alerts("snapshot_collection", collection_alerts(collection)),
        _gate_from_alerts("clob_book_capture", clob_alerts(clob)),
        _gate_from_alerts("observation_trigger", observation_alerts(observation)),
    ]
    recovery_rows = broad_live_forward_recovery_rows(collection, clob, observation, event_metadata)
    snapshot_cadence = _snapshot_cadence_proof(collection, recovery_rows)
    concrete_gates = _concrete_broad_slo_gates(recovery_rows)
    optional_streams = optional_market_event_stream_gate(clob)
    blockers = [
        message
        for gate in gates
        if not gate["ok"]
        for message in gate.get("messages") or []
    ]
    source_status_blockers = [
        row.get("detail")
        for row in recovery_rows
        if row.get("component") == "source_status"
    ]
    blockers.extend([detail for detail in source_status_blockers if detail not in blockers])
    ok = not blockers and not recovery_rows
    first_blocker = recovery_rows[0] if recovery_rows else {}
    reason = (
        "all broad live-forward gates are countable"
        if ok
        else (
            f"{first_blocker.get('gate')} blocks broad live-forward SLO for "
            f"{first_blocker.get('market_id')}: {first_blocker.get('detail')}"
            if first_blocker
            else "; ".join(blockers[:3])
        )
    )
    return {
        "schema_version": "live_forward_slo_v0.1",
        "status": "PASS" if ok else "BLOCK",
        "ok": ok,
        "counts_toward_live_forward_gate": ok,
        "reason": reason,
        "gates": gates,
        "concrete_gates": concrete_gates,
        "blockers": blockers,
        "first_blocker": first_blocker,
        "recovery_checklist": recovery_rows,
        "optional_market_event_streams": optional_streams,
        "snapshot_cadence_proof": snapshot_cadence,
        "rerun_command": BROAD_SLO_VERIFY_COMMAND,
        "summary": _broad_slo_summary(recovery_rows),
    }


def _target_date_from_collection(collection):
    dates = [
        str(row.get("target_date"))
        for row in (collection or {}).get("markets") or []
        if row.get("target_date")
    ]
    if not dates:
        return None
    counts = Counter(dates)
    return sorted(counts.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)[0][0]


def _clean_day_gate(name, status, ok, detail, *, evidence=None):
    status = status or "MISSING"
    return {
        "name": name,
        "status": status,
        "ok": bool(ok),
        "detail": detail,
        "evidence": evidence or {},
    }


def clean_active_day_countability(collection, clob, live_forward_slo, current_code_soak):
    """Fail-closed active-day operational countability for early-hour evidence."""
    collection = collection or {}
    clob = clob or {}
    live_forward_slo = live_forward_slo or {}
    current_code_soak = current_code_soak or {}
    cadence = (
        live_forward_slo.get("snapshot_cadence_proof")
        or collection.get("snapshot_cadence_proof")
        or {}
    )
    cadence_summary = cadence.get("summary") or {}
    early_hour = collection.get("early_hour_coverage_proof") or {}
    early_summary = early_hour.get("summary") or {}
    source_status = collection.get("source_status_proof") or {}
    source_summary = (
        source_status.get("summary")
        or ((collection.get("summary") or {}).get("source_status_proof") or {})
        or ((collection.get("summary") or {}).get("source_family_degradation") or {})
    )
    clob_books = clob.get("books") or {}
    clob_rows = clob_books.get("markets") or []
    snapshot_gap_blocked = int(cadence_summary.get("snapshot_coverage_gap_blocked_market_count") or 0)
    early_hour_status = early_summary.get("status")
    early_hour_counts = early_summary.get("counts_toward_early_hour_evidence")
    if early_hour_counts is None:
        early_hour_counts = early_hour_status == "PASS" if early_summary else False
    source_blocked = int(source_summary.get("promotion_readiness_blocked_market_count") or 0)
    source_known = bool(source_summary)
    source_allowed = source_summary.get("promotion_readiness_allowed")
    if source_allowed is None:
        source_allowed = source_known and source_blocked == 0
    clob_ok = clob_books.get("ok")
    if clob_ok is None and clob_rows:
        clob_ok = all(row.get("ok") for row in clob_rows)
    clob_blocked_markets = [
        row.get("market_id")
        for row in clob_rows
        if not row.get("ok")
    ]

    gates = [
        _clean_day_gate(
            "live_forward_slo",
            live_forward_slo.get("status"),
            live_forward_slo.get("counts_toward_live_forward_gate") is True
            or live_forward_slo.get("ok") is True,
            live_forward_slo.get("reason") or "live-forward SLO must pass",
            evidence={
                "first_blocker": live_forward_slo.get("first_blocker") or {},
                "summary": live_forward_slo.get("summary") or {},
            },
        ),
        _clean_day_gate(
            "snapshot_coverage_gap",
            "PASS" if snapshot_gap_blocked == 0 and cadence_summary.get("status") == "PASS" else "BLOCK",
            snapshot_gap_blocked == 0 and cadence_summary.get("status") == "PASS",
            f"snapshot_coverage_gap blocked markets={snapshot_gap_blocked}",
            evidence=cadence_summary,
        ),
        _clean_day_gate(
            "clob_book_freshness",
            "PASS" if clob_ok else "BLOCK",
            clob_ok is True,
            (
                "CLOB books are fresh for every active market"
                if clob_ok
                else f"CLOB blocked markets={', '.join(m for m in clob_blocked_markets if m) or '-'}"
            ),
            evidence={
                "blocked_markets": clob_blocked_markets,
                "market_count": len(clob_rows),
                "max_gap_seconds_threshold": clob_books.get("max_gap_seconds_threshold"),
            },
        ),
        _clean_day_gate(
            "source_status_proof",
            "PASS" if source_allowed else "BLOCK",
            source_allowed is True and source_blocked == 0,
            (
                "source status allows promotion-readiness evidence for every active market"
                if source_allowed and source_blocked == 0
                else f"promotion-readiness source-status blocked markets={source_blocked}"
            ),
            evidence=source_summary,
        ),
        _clean_day_gate(
            "current_code_soak",
            current_code_soak.get("status"),
            current_code_soak.get("counts_toward_active_day") is True
            and current_code_soak.get("status") in {"PASS", "OK"},
            (
                current_code_soak.get("cadence_slo_reason")
                or ((current_code_soak.get("summary") or {}).get("first_blocking_reason"))
                or "current-code soak must pass"
            ),
            evidence={
                "summary": current_code_soak.get("summary") or {},
                "verification_command": current_code_soak.get("verification_command"),
            },
        ),
        _clean_day_gate(
            "early_hour_coverage",
            early_hour_status,
            early_hour_counts is True,
            (
                early_summary.get("reason")
                or "00:00-08:00 snapshot coverage must be countable"
            ),
            evidence=early_summary,
        ),
    ]
    blockers = [gate for gate in gates if not gate.get("ok")]
    return {
        "schema_version": "clean_active_day_countability_v0.1",
        "target_date": _target_date_from_collection(collection),
        "status": "PASS" if not blockers else "BLOCK",
        "counts_toward_clean_active_day": not blockers,
        "counts_toward_early_hour_evidence": not blockers,
        "model_skill_blockers_separate": True,
        "operational_blocker_count": len(blockers),
        "gates": gates,
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "snapshot_cadence_proof": cadence,
        "early_hour_coverage_proof": early_hour,
        "policy": {
            "requires": [
                "live-forward SLO PASS",
                "snapshot_coverage_gap blocked markets 0",
                "fresh CLOB books",
                "source-status promotion-readiness allowed",
                "current-code soak PASS",
                "countable 00:00-08:00 snapshot coverage",
            ],
            "model_skill_blockers_are_not_masked": True,
        },
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
