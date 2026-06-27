"""Conservative live-readiness summary for market-making evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.collection.collection_health import weather_provider_credential_environment
from weather.market.market_making_evidence import EVIDENCE_MODE_ACTIVE_DAY
from weather.market.market_making_preflight import load_platform_verification_gate
from weather.market.market_making_run_constants import DEFAULT_PLATFORM_VERIFICATION, DEFAULT_RUNS_ROOT
from weather.market.market_making_run_support import load_live_readiness
from weather.market.mm_policy import bool_value, maybe_float, parse_time
from weather.paths import data_path, relative_to_repo


SCHEMA_VERSION = "mm_live_readiness_v0.2"
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_STATUS_PATH = DEFAULT_RUNS_ROOT / "daily_roll_status.json"
DEFAULT_LIVE_READINESS = DEFAULT_BACKTEST_ROOT / "live_readiness.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "mm_live_readiness.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "mm_live_readiness.md"
MIN_LIVE_FORWARD_DAYS = 14
EVENT_METADATA_GATES = ("event_metadata_validation",)
CLOB_GATES = (
    "clob_discovery",
    "clob_tokens",
    "clob_books",
    "clob_features",
    "clob_freshness",
    "reward_metadata",
)
SNAPSHOT_SOURCE_GATES = (
    "snapshot_model_rows",
    "model_freshness",
    "source_status_rows",
    "source_status_fresh",
    "source_status_degradation",
)
OBSERVATION_GATES = ("observation_trigger",)
SOURCE_STATUS_REPAIR_COMMAND = (
    "python -m weather.collection.snapshot_tracker "
    "--backfill-source-status --overwrite-source-status"
)
ACTION_METADATA = {
    "readiness_inputs_target_date_aligned": {
        "priority": 8,
        "category": "input_integrity",
        "safe_next_step": "score the same target date as the selected status/run evidence, then rebuild readiness",
    },
    "daily_roll_target_date_current": {
        "priority": 9,
        "category": "runtime",
        "safe_next_step": "stop the prior-target paper loop and start the current target date during the active evidence window",
    },
    "latest_preflight_passes": {
        "priority": 10,
        "category": "data_preflight",
        "safe_next_step": "fix stale or blocked preflight inputs, then rerun a keyless shadow or paper-live-forward check",
    },
    "event_metadata_target_date_validated": {
        "priority": 11,
        "category": "data_preflight",
        "safe_next_step": "refresh target-date event metadata validation before interpreting quote output",
    },
    "clob_capture_and_reward_metadata_fresh": {
        "priority": 12,
        "category": "market_data",
        "safe_next_step": "restore CLOB capture, token discovery, book freshness, features, and reward metadata",
    },
    "snapshot_model_source_fresh": {
        "priority": 13,
        "category": "model_data",
        "safe_next_step": "refresh snapshot/model/source-status rows and wait for source freshness to pass",
    },
    "observation_trigger_fresh": {
        "priority": 14,
        "category": "observation_data",
        "safe_next_step": "restore observation trigger heartbeat before collecting promotion evidence",
    },
    "daily_roll_runtime_identity_current": {
        "priority": 15,
        "category": "runtime",
        "safe_next_step": "wait for guarded recovery or restart the paper loop after checking supervisor diagnostics",
    },
    "active_day_live_forward_evidence": {
        "priority": 20,
        "category": "paper_evidence",
        "safe_next_step": "collect active-window paper-live-forward evidence; post-settlement and shadow runs do not count",
    },
    "live_forward_gate_passes": {
        "priority": 21,
        "category": "paper_evidence",
        "safe_next_step": "resolve live-forward gate blockers before treating any paper day as countable",
    },
    "exchange_economics_current": {
        "priority": 22,
        "category": "exchange_rules",
        "safe_next_step": "publish and accept a target-date exchange-economics snapshot from current official assumptions",
    },
    "quote_permission_present_in_countable_paper": {
        "priority": 30,
        "category": "quote_policy",
        "safe_next_step": "after countable evidence exists, diagnose quote starvation by known-edge, book, cadence, and event gates",
    },
    "paper_modes_do_not_emit_live_trade_permission": {
        "priority": 5,
        "category": "safety_invariant",
        "safe_next_step": "stop promotion and inspect mode/live-gate handling if any paper run emits live permission",
    },
    "fill_evidence_complete": {
        "priority": 40,
        "category": "fills_pnl",
        "safe_next_step": "collect trade-size, queue-book, markout, settlement, and resting-quote resolution evidence",
    },
    "locked_policy_across_paper_days": {
        "priority": 50,
        "category": "anti_overfit",
        "safe_next_step": "freeze policy parameters and policy hash before counting additional promotion days",
    },
    "fourteen_consecutive_countable_live_forward_days": {
        "priority": 60,
        "category": "anti_overfit",
        "safe_next_step": "collect the required consecutive countable active-day paper-live-forward days",
    },
    "positive_conservative_pnl_after_costs": {
        "priority": 70,
        "category": "fills_pnl",
        "safe_next_step": "continue paper scoring until conservative P&L is positive after costs and markouts",
    },
    "no_unresolved_resting_quotes": {
        "priority": 41,
        "category": "fills_pnl",
        "safe_next_step": "resolve all resting quotes against decisive observation or settlement before promotion",
    },
    "actual_reward_payout_evidence": {
        "priority": 80,
        "category": "reward_reconciliation",
        "safe_next_step": "reconcile predicted rewards/rebates with actual payout artifacts before scaling",
    },
    "operator_live_readiness_file_passes": {
        "priority": 90,
        "category": "operator_controls",
        "safe_next_step": "create live_readiness.json only after wallet, allowance, heartbeat, user stream, and cancel-all proofs exist",
    },
    "platform_verification_v0_2_passes": {
        "priority": 91,
        "category": "platform_verification",
        "safe_next_step": "refresh platform verification v0.2 with maker-only, private-stream, cancel-all, latency-stopgap, and secret-redaction proofs",
    },
}


def read_json(path, default=None):
    if path in (None, ""):
        return default
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def find_latest_paper_score(backtest_root=DEFAULT_BACKTEST_ROOT, target_date=None):
    root = Path(backtest_root)
    candidates = [
        path for path in root.glob("mm_paper*.json")
        if path.is_file()
    ]
    if not candidates:
        return None
    if target_date:
        target_dates = set(_target_date_values(target_date))
        matching = []
        for path in candidates:
            payload = read_json(path, {}) or {}
            if target_dates.intersection(_paper_target_dates(payload)):
                matching.append(path)
        if matching:
            return max(matching, key=lambda path: path.stat().st_mtime)
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _status(ok):
    return "PASS" if bool(ok) else "BLOCK"


def _gate(gate_id, ok, detail, *, evidence=None, remediation=None):
    return {
        "id": gate_id,
        "status": _status(ok),
        "ok": bool(ok),
        "detail": detail,
        "evidence": evidence or {},
        "remediation": remediation,
    }


def _gate_with_details(gate_id, ok, pass_detail, block_detail, *, evidence=None, remediation=None):
    return _gate(
        gate_id,
        ok,
        pass_detail if bool(ok) else block_detail,
        evidence=evidence,
        remediation=remediation,
    )


def _next_actions(blockers):
    actions = []
    for gate in blockers:
        gate_id = gate.get("id")
        metadata = ACTION_METADATA.get(gate_id, {})
        priority = metadata.get("priority", 999)
        actions.append({
            "gate_id": gate_id,
            "priority": priority,
            "category": metadata.get("category", "other"),
            "safe_next_step": gate.get("remediation") or metadata.get("safe_next_step") or "inspect gate evidence",
            "remediation": gate.get("remediation"),
            "detail": gate.get("detail"),
            "evidence": gate.get("evidence") or {},
        })
    return sorted(actions, key=lambda action: (action["priority"], str(action["gate_id"])))


def _operator_report(status_payload):
    return (status_payload or {}).get("operator_report") or {}


def _is_run_summary_status(status_payload):
    status_payload = status_payload or {}
    if status_payload.get("runner") == "market_making_daily_roll":
        return False
    if status_payload.get("daily_roll_supervisor"):
        return False
    return bool(
        status_payload.get("run_id")
        or status_payload.get("run_folder")
        or status_payload.get("run_config_path")
        or status_payload.get("quote_intents_path")
        or status_payload.get("preflight_path")
    )


def _latest_run_folder(status_payload):
    report = _operator_report(status_payload)
    value = (
        report.get("latest_run_folder")
        or (status_payload or {}).get("latest_run_folder")
        or (status_payload or {}).get("run_folder")
        or (status_payload or {}).get("path")
    )
    return Path(value) if value else None


def _runtime_identity_matches(status_payload):
    if _is_run_summary_status(status_payload) and not _runtime_liveness_blocked(status_payload):
        return True
    if _runtime_liveness_blocked(status_payload):
        return False
    report = _operator_report(status_payload)
    if "supervisor_runtime_identity_matches_current" in report:
        return bool_value(report.get("supervisor_runtime_identity_matches_current"), False)
    supervisor = (status_payload or {}).get("daily_roll_supervisor") or {}
    if "runtime_identity_matches_current" in supervisor:
        return bool_value(supervisor.get("runtime_identity_matches_current"), False)
    return False


def _runtime_liveness_blocked(status_payload):
    status_payload = status_payload or {}
    report = _operator_report(status_payload)
    artifact_liveness = status_payload.get("artifact_liveness") or {}
    if bool_value(report.get("restart_recommended"), False):
        return True
    if str(status_payload.get("action") or "") == "blocked_restart_required":
        return True
    if "ok" in artifact_liveness and not bool_value(artifact_liveness.get("ok"), False):
        return True
    status = str(artifact_liveness.get("status") or "").upper()
    return status.startswith("STALE_") or status in {"BLOCK", "BLOCKED"}


def _runtime_identity_evidence(status_payload):
    status_payload = status_payload or {}
    report = _operator_report(status_payload)
    supervisor = status_payload.get("daily_roll_supervisor") or {}
    recovery_guard = supervisor.get("recovery_guard") or {}
    artifact_liveness = status_payload.get("artifact_liveness") or {}
    return {
        "status_input_kind": "run_summary" if _is_run_summary_status(status_payload) else "daily_roll",
        "daily_roll_action": status_payload.get("action"),
        "daily_roll_root_cause_class": None if _is_run_summary_status(status_payload) else status_payload.get("root_cause_class"),
        "run_summary_root_cause_class": status_payload.get("root_cause_class") if _is_run_summary_status(status_payload) else None,
        "artifact_liveness_status": artifact_liveness.get("status"),
        "artifact_liveness_root_cause": artifact_liveness.get("root_cause_class"),
        "artifact_liveness_detail": artifact_liveness.get("detail"),
        "operator_restart_recommended": report.get("restart_recommended"),
        "operator_restart_reason": report.get("restart_reason"),
        "supervisor_state": report.get("supervisor_state") or supervisor.get("state"),
        "supervisor_action": report.get("supervisor_action") or supervisor.get("action"),
        "supervisor_reason": report.get("supervisor_reason") or supervisor.get("reason"),
        "supervisor_restart_cause": report.get("supervisor_restart_cause") or supervisor.get("restart_cause"),
        "start_time_gate": supervisor.get("start_time_gate"),
        "runtime_identity_matches_current": (
            report.get("supervisor_runtime_identity_matches_current")
            if "supervisor_runtime_identity_matches_current" in report
            else supervisor.get("runtime_identity_matches_current")
        ),
        "retry_after_seconds": (
            report.get("supervisor_retry_after_seconds")
            if "supervisor_retry_after_seconds" in report
            else recovery_guard.get("retry_after_seconds")
        ),
        "retry_at_utc": report.get("supervisor_retry_at_utc") or recovery_guard.get("retry_at_utc"),
        "detail": supervisor.get("detail"),
    }


def _runtime_identity_detail(status_payload):
    evidence = _runtime_identity_evidence(status_payload)
    if _is_run_summary_status(status_payload) and not _runtime_liveness_blocked(status_payload):
        root_cause = evidence.get("run_summary_root_cause_class")
        suffix = f"; run_summary_root_cause_class={root_cause}" if root_cause else ""
        return "daily-roll runtime identity is not applicable for this one-shot run-summary status" + suffix
    if bool_value(evidence.get("runtime_identity_matches_current"), False) and not _runtime_liveness_blocked(status_payload):
        return "running daily-roll code identity matches the current source tree"
    has_supervisor_evidence = any(
        evidence.get(key) not in (None, "")
        for key in (
            "daily_roll_action",
            "daily_roll_root_cause_class",
            "artifact_liveness_status",
            "artifact_liveness_root_cause",
            "operator_restart_reason",
            "supervisor_state",
            "supervisor_action",
            "supervisor_reason",
            "supervisor_restart_cause",
            "retry_at_utc",
            "detail",
            "start_time_gate",
        )
    ) or evidence.get("runtime_identity_matches_current") is not None
    one_shot_status = _is_run_summary_status(status_payload) and not _operator_report(status_payload)
    one_shot_operator_report = bool(
        (status_payload or {}).get("run_folder")
        or (status_payload or {}).get("run_id")
    ) and not (status_payload or {}).get("daily_roll_supervisor") and (
        str(evidence.get("supervisor_state") or "").upper() == "NOT_APPLICABLE"
        or str(evidence.get("supervisor_action") or "") == "one_shot_shadow"
    )
    if (one_shot_status and not has_supervisor_evidence) or one_shot_operator_report:
        return "daily-roll runtime identity evidence is absent for this one-shot or non-daily-roll status"
    parts = ["running daily-roll code identity is stale or unknown"]
    for key in (
        "daily_roll_action",
        "daily_roll_root_cause_class",
        "artifact_liveness_status",
        "artifact_liveness_root_cause",
        "operator_restart_reason",
        "operator_restart_recommended",
        "supervisor_state",
        "supervisor_action",
        "supervisor_reason",
        "supervisor_restart_cause",
        "retry_at_utc",
    ):
        value = evidence.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    detail = evidence.get("detail")
    if detail:
        parts.append(str(detail))
    artifact_detail = evidence.get("artifact_liveness_detail")
    if artifact_detail:
        parts.append(str(artifact_detail))
    start_gate = evidence.get("start_time_gate") or {}
    if start_gate:
        parts.append(
            "start_time_gate="
            f"allowed={start_gate.get('allowed')}, "
            f"start_after_local_time={start_gate.get('start_after_local_time')}, "
            f"reason={start_gate.get('reason')}"
        )
    return "; ".join(parts)


def _live_forward_gate_status(status_payload, live_forward_gate):
    report = _operator_report(status_payload)
    return (
        report.get("live_forward_gate_status")
        or (status_payload or {}).get("live_forward_gate_status")
        or (live_forward_gate or {}).get("status")
    )


def _current_counts_toward_live_forward(status_payload, live_forward_gate):
    report = _operator_report(status_payload)
    for payload in (status_payload or {}, report, live_forward_gate or {}):
        if "current_counts_toward_live_forward_gate" in payload:
            return bool_value(payload.get("current_counts_toward_live_forward_gate"), False)
        if "counts_toward_live_forward_gate" in payload:
            return bool_value(payload.get("counts_toward_live_forward_gate"), False)
    return False


def _paper_summary(paper_payload):
    return (paper_payload or {}).get("summary") or {}


def _target_date_values(*values):
    dates = []
    for value in values:
        if value in (None, ""):
            continue
        try:
            dates.append(date.fromisoformat(str(value)).isoformat())
        except ValueError:
            dates.append(str(value))
    return dates


def _paper_target_dates(paper_payload):
    payload = paper_payload or {}
    summary = _paper_summary(payload)
    dates = _target_date_values(
        payload.get("target_date"),
        payload.get("run_target_date"),
        summary.get("target_date"),
        (payload.get("run_folder_selection") or {}).get("target_date"),
    )
    run_configs = payload.get("run_configs")
    if isinstance(run_configs, dict):
        configs = run_configs.values()
    elif isinstance(run_configs, list):
        configs = run_configs
    else:
        configs = []
    for config in configs:
        if not isinstance(config, dict):
            continue
        dates.extend(_target_date_values(
            config.get("target_date"),
            (config.get("evidence_classification") or {}).get("target_date"),
            (config.get("event_metadata_validation") or {}).get("target_date"),
        ))
    return sorted(set(dates))


def _target_date_alignment(status_payload, latest_run_summary, paper_payload):
    status_target = (status_payload or {}).get("target_date")
    latest_run_target = (latest_run_summary or {}).get("target_date")
    paper_dates = _paper_target_dates(paper_payload)
    known_dates = sorted(set(_target_date_values(status_target, latest_run_target, *paper_dates)))
    return {
        "ok": len(known_dates) <= 1,
        "status_target_date": status_target,
        "latest_run_target_date": latest_run_target,
        "paper_score_target_dates": paper_dates,
        "known_target_dates": known_dates,
    }


def _daily_roll_target_date_evidence(status_payload):
    status_payload = status_payload or {}
    supervisor = status_payload.get("daily_roll_supervisor") or {}
    report = _operator_report(status_payload)
    expected = (
        supervisor.get("expected_target_date")
        or report.get("supervisor_expected_target_date")
    )
    status_target = status_payload.get("target_date")
    supervisor_target = supervisor.get("target_date")
    ok = not expected or not status_target or str(expected) == str(status_target)
    return {
        "ok": ok,
        "status_input_kind": "run_summary" if _is_run_summary_status(status_payload) else "daily_roll",
        "status_target_date": status_target,
        "supervisor_target_date": supervisor_target,
        "expected_target_date": expected,
        "daily_roll_status": status_payload.get("status"),
        "evidence_mode": status_payload.get("evidence_mode"),
        "supervisor_state": report.get("supervisor_state") or supervisor.get("state"),
        "supervisor_action": report.get("supervisor_action") or supervisor.get("action"),
        "start_time_gate": supervisor.get("start_time_gate"),
    }


def _summary_number(summary, key, nested=None):
    if nested:
        value = (summary.get(nested) or {}).get(key)
    else:
        value = summary.get(key)
    return maybe_float(value)


def _summary_bool(summary, key, nested=None):
    payload = summary.get(nested) if nested else summary
    if not isinstance(payload, dict):
        return False
    return bool_value(payload.get(key), False)


def _live_forward_days(summary):
    anti = summary.get("anti_overfit") or {}
    days = anti.get("live_forward_days")
    if isinstance(days, list):
        return [str(day) for day in days if str(day).strip()]
    return []


def _dates_are_consecutive(days, min_days):
    if len(days) < min_days:
        return False
    try:
        parsed = sorted({date.fromisoformat(day) for day in days})
    except ValueError:
        return False
    if len(parsed) < min_days:
        return False
    latest = parsed[-min_days:]
    return all((right - left) == timedelta(days=1) for left, right in zip(latest, latest[1:]))


def _path_text(path):
    if not path:
        return None
    return relative_to_repo(Path(path))


def _preflight_markets(preflight_payload):
    return (preflight_payload or {}).get("markets") or []


def _gate_by_name(market):
    return {gate.get("name"): gate for gate in (market or {}).get("gates") or []}


def _preflight_gate_group(preflight_payload, gate_names):
    markets = _preflight_markets(preflight_payload)
    failing = []
    missing = []
    failing_gate_counts = {}
    failing_market_sets = {}
    missing_gate_counts = {}
    missing_market_sets = {}
    for market in markets:
        gates = _gate_by_name(market)
        market_id = market.get("market_id")
        for name in gate_names:
            gate = gates.get(name)
            if gate is None:
                missing.append({"market_id": market_id, "gate": name})
                missing_gate_counts[name] = missing_gate_counts.get(name, 0) + 1
                missing_market_sets.setdefault(name, set()).add(market_id)
            elif not bool(gate.get("ok")):
                failing.append({
                    "market_id": market_id,
                    "gate": name,
                    "severity": gate.get("severity"),
                    "detail": gate.get("detail"),
                })
                failing_gate_counts[name] = failing_gate_counts.get(name, 0) + 1
                failing_market_sets.setdefault(name, set()).add(market_id)
    return {
        "market_count": len(markets),
        "gate_names": list(gate_names),
        "ok": bool(markets) and not failing and not missing,
        "failing_count": len(failing),
        "missing_count": len(missing),
        "failing_gate_counts": dict(sorted(failing_gate_counts.items())),
        "failing_market_counts": {
            gate: len(markets)
            for gate, markets in sorted(failing_market_sets.items())
        },
        "failing_markets": {
            gate: sorted(market for market in markets if market)
            for gate, markets in sorted(failing_market_sets.items())
        },
        "missing_gate_counts": dict(sorted(missing_gate_counts.items())),
        "missing_markets": {
            gate: sorted(market for market in markets if market)
            for gate, markets in sorted(missing_market_sets.items())
        },
        "failing": failing[:12],
        "missing": missing[:12],
    }


def _preflight_pass_evidence(preflight_payload, latest_run_summary):
    preflight_payload = preflight_payload or {}
    diagnostics = latest_run_summary.get("preflight_diagnostics") or {}
    markets = _preflight_markets(preflight_payload)
    stale_count = int(diagnostics.get("stale_market_count") or 0)
    blocked_count = int(diagnostics.get("blocked_market_count") or 0)
    if markets:
        status_counts = {}
        for market in markets:
            status = str(market.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        ok = all(market.get("status") == "PASS" for market in markets)
    else:
        status_counts = diagnostics.get("status_counts") or {}
        ok = latest_run_summary.get("preflight_status") == "PASS" and not stale_count and not blocked_count
    return {
        "ok": bool(ok),
        "status": preflight_payload.get("status") or latest_run_summary.get("preflight_status"),
        "market_count": len(markets),
        "status_counts": status_counts,
        "stale_market_count": stale_count,
        "blocked_market_count": blocked_count,
        "top_failing_gates": diagnostics.get("top_failing_gates") or [],
    }


def _int_after_marker(text, marker):
    text = str(text or "")
    if marker not in text:
        return None
    suffix = text.split(marker, 1)[1]
    digits = []
    for char in suffix:
        if char.isdigit():
            digits.append(char)
            continue
        break
    return int("".join(digits)) if digits else None


def _aggregate_detail_marker(rows, marker, blocked_market_count):
    values = []
    for row in rows or []:
        value = _int_after_marker(row.get("detail"), marker)
        if value is not None:
            values.append((row, value))
    if not values:
        return None, None, 0

    per_market_value = values[0][1]
    top_rows = [
        (row, value)
        for row, value in values
        if int(row.get("market_count") or 0) > 0
    ]
    if top_rows:
        totals = [
            value * int(row.get("market_count") or 0)
            for row, value in top_rows
        ]
        market_count = max(int(row.get("market_count") or 0) for row, _value in top_rows)
        return max(totals), per_market_value, market_count

    per_market = {}
    for row, value in values:
        market_id = row.get("market_id")
        if market_id and market_id not in per_market:
            per_market[market_id] = value
    if per_market:
        return sum(per_market.values()), per_market_value, len(per_market)

    if blocked_market_count:
        return per_market_value * int(blocked_market_count), per_market_value, int(blocked_market_count)
    return sum(value for _row, value in values), per_market_value, len(values)


def _source_status_blocker_evidence(preflight_evidence, snapshot_source_evidence):
    failing = [
        row for row in (snapshot_source_evidence or {}).get("failing") or []
        if row.get("gate") == "source_status_degradation"
    ]
    top_failing = [
        row for row in (preflight_evidence or {}).get("top_failing_gates") or []
        if row.get("gate") == "source_status_degradation"
    ]
    if not failing and not top_failing:
        return {
            "status": "PASS",
            "ok": True,
            "blocked_market_count": 0,
            "blocked_markets": [],
        }

    details = [
        str(row.get("detail") or "")
        for row in [*top_failing, *failing]
        if row.get("detail")
    ]
    detail = details[0] if details else "source-status degradation blocks trading evidence"
    blocked_markets = sorted({
        market
        for row in [*top_failing, *failing]
        for market in (
            row.get("markets") if isinstance(row.get("markets"), list) else [row.get("market_id")]
        )
        if market
    })
    blocked_market_count = (
        max(int(row.get("market_count") or 0) for row in top_failing)
        if top_failing
        else len(blocked_markets)
    )
    rows = [*top_failing, *failing]
    settlement_auth_failures, settlement_auth_failures_per_market, settlement_auth_failure_market_count = (
        _aggregate_detail_marker(rows, "settlement_auth_failures=", blocked_market_count)
    )
    root_cause_class = (
        "settlement_source_auth_failure"
        if settlement_auth_failures
        else "source_status_degradation"
    )
    provider_credential_environment = (
        weather_provider_credential_environment()
        if root_cause_class == "settlement_source_auth_failure"
        else None
    )
    if (
        root_cause_class == "settlement_source_auth_failure"
        and provider_credential_environment
        and not provider_credential_environment.get("any_present")
    ):
        safe_next_step = (
            "configure WEATHER_COM_API_KEY or WEATHER_COM_KEY outside the repo, rerun snapshot "
            "collection/source-status backfill, then rerun keyless shadow and readiness"
        )
    elif root_cause_class == "settlement_source_auth_failure":
        safe_next_step = (
            "verify external Weather.com credential validity/provider auth, then run "
            f"`{SOURCE_STATUS_REPAIR_COMMAND}`, then rerun keyless shadow and readiness"
        )
    else:
        safe_next_step = (
            "fix external weather-provider/source-health failures blocking preflight, then run "
            f"`{SOURCE_STATUS_REPAIR_COMMAND}`, then rerun keyless shadow and readiness"
        )
    return {
        "status": "BLOCK",
        "ok": False,
        "gate": "source_status_degradation",
        "detail": detail,
        "root_cause_class": root_cause_class,
        "blocking_families": _int_after_marker(detail, "blocking_families="),
        "settlement_auth_failures": settlement_auth_failures,
        "settlement_auth_failures_per_market": settlement_auth_failures_per_market,
        "settlement_auth_failure_market_count": settlement_auth_failure_market_count,
        "provider_credential_environment": provider_credential_environment,
        "blocked_market_count": blocked_market_count,
        "blocked_markets": blocked_markets,
        "repair_command": SOURCE_STATUS_REPAIR_COMMAND,
        "safe_next_step": safe_next_step,
    }


def _observation_evidence(preflight_payload):
    group = _preflight_gate_group(preflight_payload, OBSERVATION_GATES)
    observation = (preflight_payload or {}).get("observation_status") or {}
    fresh = bool_value(observation.get("fresh"), False)
    heartbeat_ok = bool_value(observation.get("heartbeat_ok"), False)
    return {
        **group,
        "observation_fresh": fresh,
        "observation_heartbeat_ok": heartbeat_ok,
        "last_heartbeat": observation.get("last_heartbeat"),
        "ok": group["ok"] and fresh and heartbeat_ok,
    }


def build_readiness_snapshot(
    *,
    status_payload=None,
    status_path=DEFAULT_STATUS_PATH,
    paper_payload=None,
    paper_score_path=None,
    latest_run_summary=None,
    preflight_payload=None,
    live_forward_gate=None,
    live_readiness_path=DEFAULT_LIVE_READINESS,
    platform_verification_path=DEFAULT_PLATFORM_VERIFICATION,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    now=None,
    min_live_forward_days=MIN_LIVE_FORWARD_DAYS,
):
    now_dt = parse_time(now) or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    status_path = Path(status_path) if status_path else None
    status_payload = status_payload if status_payload is not None else read_json(status_path, {}) or {}

    latest_folder = _latest_run_folder(status_payload)
    if latest_run_summary is None and latest_folder and latest_folder.name != "daily_roll_status.json":
        latest_run_summary = read_json(latest_folder / "run_summary.json", {}) or {}
    latest_run_summary = latest_run_summary or {}
    if preflight_payload is None and latest_folder and latest_folder.name != "daily_roll_status.json":
        preflight_payload = read_json(latest_folder / "preflight.json", {}) or {}
    preflight_payload = preflight_payload or {}
    if live_forward_gate is None and latest_folder and latest_folder.name != "daily_roll_status.json":
        live_forward_gate = read_json(latest_folder / "live_forward_gate.json", {}) or {}
    live_forward_gate = live_forward_gate or {}

    requested_target_date = (
        (status_payload or {}).get("target_date")
        or latest_run_summary.get("target_date")
    )
    if paper_payload is None:
        selected_paper_path = (
            Path(paper_score_path)
            if paper_score_path
            else find_latest_paper_score(backtest_root, target_date=requested_target_date)
        )
        paper_payload = read_json(selected_paper_path, {}) if selected_paper_path else {}
    else:
        selected_paper_path = Path(paper_score_path) if paper_score_path else None

    summary = _paper_summary(paper_payload)
    paper_quote_blockers = summary.get("quote_blocker_diagnostics") or (paper_payload or {}).get("quote_blocker_diagnostics") or {}
    paper_quote_uptime = summary.get("quote_uptime") or {}
    target_date = (
        (status_payload or {}).get("target_date")
        or latest_run_summary.get("target_date")
        or summary.get("target_date")
        or (paper_payload or {}).get("target_date")
    )
    target_date = str(target_date) if target_date else None

    live_readiness = load_live_readiness(live_readiness_path)
    platform_gate = load_platform_verification_gate(
        platform_verification_path,
        target_date or now_dt.date().isoformat(),
        "live-pilot",
        now=now_dt,
    )
    preflight_evidence = _preflight_pass_evidence(preflight_payload, latest_run_summary)
    known_edge_map_evidence = (
        latest_run_summary.get("known_edge_map")
        or (preflight_payload or {}).get("known_edge_map")
        or {}
    )
    event_metadata_evidence = _preflight_gate_group(preflight_payload, EVENT_METADATA_GATES)
    clob_evidence = _preflight_gate_group(preflight_payload, CLOB_GATES)
    snapshot_source_evidence = _preflight_gate_group(preflight_payload, SNAPSHOT_SOURCE_GATES)
    source_status_blocker = _source_status_blocker_evidence(preflight_evidence, snapshot_source_evidence)
    snapshot_source_failing_markets = snapshot_source_evidence.get("failing_markets") or {}
    model_freshness_failed_markets = snapshot_source_failing_markets.get("model_freshness", [])
    source_status_degradation_failed_markets = (
        source_status_blocker.get("blocked_markets")
        or snapshot_source_failing_markets.get("source_status_degradation", [])
    )
    source_provider_credential_environment = (
        source_status_blocker.get("provider_credential_environment") or {}
    )
    preflight_remediation = latest_run_summary.get("preflight_remediation") or {}
    preflight_remediation_root_cause_counts = preflight_remediation.get("root_cause_counts") or {}
    observation_trigger_runtime_root_cause_counts = {
        key: value
        for key, value in sorted(preflight_remediation_root_cause_counts.items())
        if str(key).startswith("observation_trigger_")
    }
    observation_evidence = _observation_evidence(preflight_payload)
    runtime_identity_ok = _runtime_identity_matches(status_payload)
    runtime_identity_evidence = _runtime_identity_evidence(status_payload)

    evidence_mode = (
        (status_payload or {}).get("evidence_mode")
        or latest_run_summary.get("evidence_mode")
        or live_forward_gate.get("evidence_mode")
    )
    current_counts = _current_counts_toward_live_forward(status_payload, live_forward_gate)
    live_gate_status = _live_forward_gate_status(status_payload, live_forward_gate)
    paper_score_quote_permission_rows = int(_summary_number(summary, "quote_permission_rows") or 0)
    paper_score_live_trade_permission_rows = int(_summary_number(summary, "live_trade_permission_rows") or 0)
    report = _operator_report(status_payload)
    latest_tick_quote_outcome = latest_run_summary.get("quote_outcome") or {}
    latest_tick_quote_rows = int(
        maybe_float(
            report.get("latest_quote_rows")
            or latest_run_summary.get("quote_rows")
            or latest_run_summary.get("quote_intent_rows")
            or latest_tick_quote_outcome.get("row_count")
        )
        or 0
    )
    latest_tick_quote_permission_rows = int(
        maybe_float(
            report.get("latest_quote_permission_rows")
            or latest_run_summary.get("quote_permission_rows")
            or latest_tick_quote_outcome.get("quote_permission_rows")
        )
        or 0
    )
    latest_tick_no_quote_rows = int(
        maybe_float(
            latest_run_summary.get("no_quote_rows")
            or latest_tick_quote_outcome.get("no_quote_rows")
        )
        or max(0, latest_tick_quote_rows - latest_tick_quote_permission_rows)
    )
    latest_tick_live_trade_permission_rows = int(
        maybe_float(
            report.get("latest_live_trade_permission_rows")
            or latest_run_summary.get("live_trade_permission_rows")
        )
        or 0
    )
    latest_tick_reason_counts = latest_run_summary.get("reason_counts") or {}
    fill_status = summary.get("fill_evidence_completeness_status")
    fill_promotion_grade = _summary_bool(summary, "fill_evidence_promotion_grade")
    fill_completeness = (
        summary.get("fill_evidence_completeness")
        or (paper_payload or {}).get("fill_evidence_completeness")
        or {}
    )
    fill_blockers = summary.get("fill_evidence_blockers") or []
    fill_quote_legs = int(
        maybe_float(summary.get("quote_legs") or fill_completeness.get("quote_legs"))
        or 0
    )
    fill_evidence_vacuous = (
        bool_value(summary.get("fill_evidence_vacuous"), False)
        or bool_value(fill_completeness.get("vacuous"), False)
        or (
            fill_status == "PASS"
            and fill_promotion_grade
            and paper_score_quote_permission_rows == 0
            and fill_quote_legs == 0
        )
    )
    fill_effective_promotion_grade = (
        fill_status == "PASS"
        and fill_promotion_grade
        and not fill_evidence_vacuous
    )
    paper_score_freshness_status = summary.get("paper_score_freshness_status")
    live_forward_days = _live_forward_days(summary)
    locked_policy_params = _summary_bool(summary.get("anti_overfit") or {}, "locked_policy_params")
    conservative_fills = int(_summary_number(summary, "conservative_fills") or 0)
    queue_estimated_fill_legs = int(_summary_number(summary, "queue_estimated_fill_legs") or 0)
    missing_size_trade_rows = int(_summary_number(summary, "missing_size_trade_rows") or 0)
    missing_book_queue_legs = int(_summary_number(summary, "missing_book_queue_legs") or 0)
    total_reward_score = _summary_number(summary, "total_reward_score")
    counterfactual_reward_usdc = _summary_number(summary, "counterfactual_reward_usdc")
    net_pnl = _summary_number(summary, "net_pnl_after_fees_incentives_usdc", nested="pnl")
    unresolved_resting_quotes = int(_summary_number(summary, "unresolved_resting_quote_count") or 0)
    actual_payout_evidence = _summary_bool(summary, "actual_payout_evidence")
    exchange_economics_status = (
        summary.get("exchange_economics_gate_status")
        or summary.get("exchange_economics_status")
    )
    target_date_alignment = _target_date_alignment(status_payload, latest_run_summary, paper_payload)
    daily_roll_target_date_evidence = _daily_roll_target_date_evidence(status_payload)

    gates = [
        _gate_with_details(
            "readiness_inputs_target_date_aligned",
            target_date_alignment["ok"],
            "status, selected run, and paper-score target dates are aligned",
            "status, selected run, and paper-score target dates are not aligned",
            evidence=target_date_alignment,
            remediation="rebuild readiness from status and paper-score artifacts that cover the same target date",
        ),
        _gate_with_details(
            "daily_roll_target_date_current",
            daily_roll_target_date_evidence["ok"],
            "daily-roll status target date matches the supervisor expected target date",
            "daily-roll status target date does not match the supervisor expected target date",
            evidence=daily_roll_target_date_evidence,
            remediation="stop the prior-target paper loop and start the current target date during the active evidence window",
        ),
        _gate_with_details(
            "latest_preflight_passes",
            preflight_evidence["ok"],
            "latest selected run preflight is PASS for all markets",
            "latest selected run preflight is stale or blocked",
            evidence=preflight_evidence,
            remediation=(
                source_status_blocker.get("safe_next_step")
                if not source_status_blocker.get("ok")
                else "resolve stale or blocked preflight gates before interpreting paper evidence"
            ),
        ),
        _gate_with_details(
            "event_metadata_target_date_validated",
            event_metadata_evidence["ok"],
            "event metadata target-date validation passes for all selected markets",
            "event metadata target-date validation is missing or failing for selected markets",
            evidence=event_metadata_evidence,
            remediation="refresh event metadata validation for the target date",
        ),
        _gate_with_details(
            "clob_capture_and_reward_metadata_fresh",
            clob_evidence["ok"],
            "CLOB discovery, token, book, feature, freshness, and reward metadata gates pass",
            "CLOB discovery, token, book, feature, freshness, or reward metadata gates are missing or failing",
            evidence=clob_evidence,
            remediation="refresh CLOB capture/recon and reward metadata before quoting",
        ),
        _gate_with_details(
            "snapshot_model_source_fresh",
            snapshot_source_evidence["ok"],
            "snapshot/model rows, model freshness, and source-status gates pass",
            "snapshot/model rows, model freshness, or source-status gates are stale or failing",
            evidence=snapshot_source_evidence,
            remediation=(
                source_status_blocker.get("safe_next_step")
                if not source_status_blocker.get("ok")
                else "refresh snapshots, model outputs, and source-status rows before quoting"
            ),
        ),
        _gate_with_details(
            "observation_trigger_fresh",
            observation_evidence["ok"],
            "observation trigger heartbeat is fresh and all observation gates pass",
            "observation trigger heartbeat or observation gates are stale or failing",
            evidence=observation_evidence,
            remediation="restore observation trigger heartbeat before quoting",
        ),
        _gate(
            "daily_roll_runtime_identity_current",
            runtime_identity_ok,
            _runtime_identity_detail(status_payload),
            evidence=runtime_identity_evidence,
            remediation=(
                _operator_report(status_payload).get("supervisor_remediation")
                or "wait for the guarded restart window or restart the paper loop after inspecting diagnostics"
            ),
        ),
        _gate_with_details(
            "active_day_live_forward_evidence",
            evidence_mode == EVIDENCE_MODE_ACTIVE_DAY and current_counts,
            "latest run is active-day paper-live-forward evidence that counts toward live-forward gates",
            "latest run is not countable active-day paper-live-forward evidence",
            evidence={
                "evidence_mode": evidence_mode,
                "current_counts_toward_live_forward_gate": current_counts,
                "target_date": target_date,
            },
            remediation="collect active-window paper-live-forward evidence for the current target date",
        ),
        _gate_with_details(
            "live_forward_gate_passes",
            live_gate_status == "PASS" and current_counts,
            "latest live-forward gate passes for the selected paper run",
            "latest live-forward gate is blocked or the run does not count",
            evidence={
                "live_forward_gate_status": live_gate_status,
                "current_counts_toward_live_forward_gate": current_counts,
            },
            remediation="resolve live-forward gate blockers before interpreting paper evidence",
        ),
        _gate_with_details(
            "exchange_economics_current",
            exchange_economics_status == "PASS",
            "paper score used a passing exchange-economics snapshot",
            "paper score does not have a passing exchange-economics snapshot",
            evidence={
                "exchange_economics_status": exchange_economics_status,
                "exchange_economics_snapshot_id": summary.get("exchange_economics_snapshot_id"),
                "exchange_economics_verified_at_utc": summary.get("exchange_economics_verified_at_utc"),
            },
            remediation="publish and accept a current target-date exchange-economics snapshot",
        ),
        _gate_with_details(
            "quote_permission_present_in_countable_paper",
            paper_score_quote_permission_rows > 0 and current_counts,
            "countable paper evidence has nonzero quote permissions",
            "countable paper evidence does not have nonzero quote permissions",
            evidence={
                "paper_score_quote_permission_rows": paper_score_quote_permission_rows,
                "latest_tick_quote_permission_rows": latest_tick_quote_permission_rows,
                "paper_score_path": _path_text(selected_paper_path),
                "current_counts_toward_live_forward_gate": current_counts,
            },
            remediation="first obtain active-day countable paper evidence, then diagnose quote starvation",
        ),
        _gate_with_details(
            "paper_modes_do_not_emit_live_trade_permission",
            paper_score_live_trade_permission_rows == 0 and latest_tick_live_trade_permission_rows == 0,
            "paper/shadow evidence did not emit live-trade permissions",
            "paper/shadow evidence emitted live-trade permissions",
            evidence={
                "paper_score_live_trade_permission_rows": paper_score_live_trade_permission_rows,
                "latest_tick_live_trade_permission_rows": latest_tick_live_trade_permission_rows,
            },
            remediation="block promotion and inspect run mode/live gate handling if paper emits live permission",
        ),
        _gate_with_details(
            "fill_evidence_complete",
            fill_effective_promotion_grade,
            "fill evidence is complete and promotion grade",
            "fill evidence is incomplete or not promotion grade",
            evidence={
                "fill_evidence_completeness_status": fill_status,
                "fill_evidence_promotion_grade": fill_promotion_grade,
                "fill_evidence_effective_promotion_grade": fill_effective_promotion_grade,
                "fill_evidence_vacuous": fill_evidence_vacuous,
                "fill_evidence_blockers": summary.get("fill_evidence_blockers") or [],
                "quote_legs": fill_quote_legs,
            },
            remediation="collect trade sizes, queue-book evidence, markouts, settlement, and resting-quote resolution",
        ),
        _gate_with_details(
            "locked_policy_across_paper_days",
            locked_policy_params,
            "policy parameters are locked across the scored evidence window",
            "policy parameters are not locked across the scored evidence window",
            evidence={
                "locked_policy_params": locked_policy_params,
                "policy_hashes": (summary.get("anti_overfit") or {}).get("policy_hashes") or [],
            },
            remediation="freeze policy parameters before using paper days as promotion evidence",
        ),
        _gate_with_details(
            "fourteen_consecutive_countable_live_forward_days",
            _dates_are_consecutive(live_forward_days, min_live_forward_days),
            f"at least {min_live_forward_days} consecutive countable live-forward paper days are present",
            f"fewer than {min_live_forward_days} consecutive countable live-forward paper days are present",
            evidence={
                "live_forward_days": live_forward_days,
                "min_live_forward_days": min_live_forward_days,
            },
            remediation="collect consecutive active-day paper-live-forward runs before risking capital",
        ),
        _gate_with_details(
            "positive_conservative_pnl_after_costs",
            net_pnl is not None and net_pnl > 0,
            "conservative paper P&L is positive after fees, incentives, rebates, and flattening",
            "conservative paper P&L is not positive after fees, incentives, rebates, and flattening",
            evidence={"net_pnl_after_fees_incentives_usdc": net_pnl},
            remediation="do not trade live until conservative markout/P&L evidence is positive",
        ),
        _gate_with_details(
            "no_unresolved_resting_quotes",
            unresolved_resting_quotes == 0,
            "no resting quotes remain unresolved through decisive observation or settlement",
            "resting quotes remain unresolved through decisive observation or settlement",
            evidence={"unresolved_resting_quote_count": unresolved_resting_quotes},
            remediation="resolve resting quotes against settlement/decisive observation before promotion",
        ),
        _gate_with_details(
            "actual_reward_payout_evidence",
            actual_payout_evidence,
            "actual reward/rebate payout evidence exists; counterfactual rewards are not treated as realized P&L",
            "actual reward/rebate payout evidence is missing; counterfactual rewards are not realized P&L",
            evidence={
                "actual_payout_evidence": actual_payout_evidence,
                "counterfactual_reward_usdc": summary.get("counterfactual_reward_usdc"),
                "counterfactual_reward_status": summary.get("counterfactual_reward_status"),
            },
            remediation="reconcile predicted rewards/rebates against actual payout artifacts before scaling",
        ),
        _gate_with_details(
            "operator_live_readiness_file_passes",
            live_readiness.get("ok"),
            "operator live-readiness booleans all pass",
            "operator live-readiness booleans are missing or failing",
            evidence={
                "path": _path_text(live_readiness.get("path")),
                "missing": live_readiness.get("missing") or [],
                "reason": live_readiness.get("reason"),
            },
            remediation="create a live-readiness JSON only after wallet, allowance, heartbeat, user-stream, and cancel-all readiness are proven",
        ),
        _gate_with_details(
            "platform_verification_v0_2_passes",
            platform_gate.get("ok"),
            "platform/account/API verification passes for the target date",
            "platform/account/API verification is missing, stale, or failing for the target date",
            evidence={
                "path": _path_text(platform_gate.get("path")),
                "schema_version": platform_gate.get("schema_version"),
                "missing": platform_gate.get("missing") or [],
                "reason": platform_gate.get("reason"),
            },
            remediation="refresh mm_platform_verification_v0.2 with maker-only, private-stream, cancel-all, latency-stopgap, and secret-redaction proofs",
        ),
    ]

    blockers = [gate for gate in gates if not gate["ok"]]
    next_actions = _next_actions(blockers)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now_dt.astimezone(timezone.utc).isoformat(),
        "status": "PASS" if not blockers else "BLOCK",
        "live_capital_permission": False,
        "requires_explicit_operator_approval": True,
        "blocker_count": len(blockers),
        "target_date": target_date,
        "inputs": {
            "status_path": _path_text(status_path),
            "latest_run_folder": _path_text(latest_folder),
            "paper_score_path": _path_text(selected_paper_path),
            "live_readiness_path": _path_text(live_readiness.get("path")),
            "platform_verification_path": _path_text(platform_gate.get("path")),
        },
        "summary": {
            "daily_roll_status": (status_payload or {}).get("status"),
            "daily_roll_action": (status_payload or {}).get("action"),
            "runtime_root_cause_class": ((status_payload or {}).get("artifact_liveness") or {}).get("root_cause_class")
            or (None if _is_run_summary_status(status_payload) else (status_payload or {}).get("root_cause_class")),
            "artifact_liveness_status": ((status_payload or {}).get("artifact_liveness") or {}).get("status"),
            "operator_restart_recommended": report.get("restart_recommended"),
            "operator_restart_reason": report.get("restart_reason"),
            "supervisor_state": report.get("supervisor_state"),
            "supervisor_action": report.get("supervisor_action"),
            "supervisor_expected_target_date": daily_roll_target_date_evidence.get("expected_target_date"),
            "preflight_status": preflight_evidence.get("status"),
            "preflight_stale_market_count": preflight_evidence.get("stale_market_count"),
            "preflight_blocked_market_count": preflight_evidence.get("blocked_market_count"),
            "preflight_remediation_status": preflight_remediation.get("status"),
            "preflight_remediation_root_cause_counts": preflight_remediation_root_cause_counts,
            "preflight_remediation_owner_counts": preflight_remediation.get("owner_counts") or {},
            "observation_trigger_runtime_root_cause_counts": observation_trigger_runtime_root_cause_counts,
            "snapshot_model_source_failing_count": snapshot_source_evidence.get("failing_count"),
            "snapshot_model_source_failing_gate_counts": snapshot_source_evidence.get("failing_gate_counts") or {},
            "snapshot_model_source_failing_market_counts": snapshot_source_evidence.get("failing_market_counts") or {},
            "snapshot_model_source_failing_markets": snapshot_source_failing_markets,
            "snapshot_model_source_missing_markets": snapshot_source_evidence.get("missing_markets") or {},
            "model_freshness_failed_market_count": (
                snapshot_source_evidence.get("failing_market_counts") or {}
            ).get("model_freshness", 0),
            "model_freshness_failed_markets": model_freshness_failed_markets,
            "source_status_degradation_failed_market_count": (
                snapshot_source_evidence.get("failing_market_counts") or {}
            ).get("source_status_degradation", 0),
            "source_status_degradation_failed_markets": source_status_degradation_failed_markets,
            "source_status_blocker_status": source_status_blocker.get("status"),
            "source_status_blocker_root_cause_class": source_status_blocker.get("root_cause_class"),
            "source_status_blocked_market_count": source_status_blocker.get("blocked_market_count"),
            "source_status_blocking_families": source_status_blocker.get("blocking_families"),
            "source_status_settlement_auth_failures": source_status_blocker.get("settlement_auth_failures"),
            "source_status_settlement_auth_failures_per_market": source_status_blocker.get(
                "settlement_auth_failures_per_market"
            ),
            "source_status_settlement_auth_failure_market_count": source_status_blocker.get(
                "settlement_auth_failure_market_count"
            ),
            "source_status_weather_com_credential_present": (
                source_provider_credential_environment.get("any_present")
            ),
            "source_status_weather_com_credential_present_by_var": (
                source_provider_credential_environment.get("present_by_var") or {}
            ),
            "source_status_weather_com_credential_values_redacted": (
                source_provider_credential_environment.get("values_redacted")
            ),
            "source_status_repair_command": source_status_blocker.get("repair_command"),
            "evidence_mode": evidence_mode,
            "current_counts_toward_live_forward_gate": current_counts,
            "live_forward_gate_status": live_gate_status,
            "paper_score_gate_status": summary.get("gate_status"),
            "paper_score_gate_scope": summary.get("gate_status_scope"),
            "paper_score_live_capital_gate_status": summary.get("live_capital_gate_status"),
            "paper_score_live_capital_gate_reason": summary.get("live_capital_gate_reason"),
            "paper_score_quote_permission_rows": paper_score_quote_permission_rows,
            "paper_score_live_trade_permission_rows": paper_score_live_trade_permission_rows,
            "paper_quote_permission_market_counts": paper_quote_uptime.get("quote_permission_market_counts") or {},
            "paper_top_quote_permission_cells": (paper_quote_uptime.get("top_quote_permission_cells") or [])[:12],
            "paper_quote_blocked_rows": paper_quote_blockers.get("blocked_rows"),
            "paper_quote_blocked_fraction": paper_quote_blockers.get("blocked_fraction"),
            "paper_quote_blocker_reason_counts": paper_quote_blockers.get("reason_counts") or {},
            "paper_quote_blocker_event_gate_suppressed_rows": paper_quote_blockers.get("event_gate_suppressed_rows"),
            "paper_quote_blocker_contextual_event_gate_suppressed_rows": paper_quote_blockers.get(
                "contextual_event_gate_suppressed_rows"
            ),
            "paper_quote_blocker_stale_input_rows": paper_quote_blockers.get("stale_input_rows"),
            "latest_tick_quote_rows": latest_tick_quote_rows,
            "latest_tick_no_quote_rows": latest_tick_no_quote_rows,
            "latest_tick_quote_permission_rows": latest_tick_quote_permission_rows,
            "latest_tick_live_trade_permission_rows": latest_tick_live_trade_permission_rows,
            "latest_tick_first_failing_gate": latest_run_summary.get("first_failing_gate"),
            "latest_tick_root_cause_class": latest_run_summary.get("root_cause_class"),
            "latest_tick_quote_outcome_status": latest_tick_quote_outcome.get("status"),
            "latest_tick_quote_outcome_reason": latest_tick_quote_outcome.get("reason"),
            "latest_tick_reason_counts": latest_tick_reason_counts,
            "known_edge_map_path": _path_text(known_edge_map_evidence.get("path")),
            "known_edge_map_schema_version": known_edge_map_evidence.get("schema_version"),
            "known_edge_map_record_count": known_edge_map_evidence.get("record_count"),
            "known_edge_map_diagnostic_only": known_edge_map_evidence.get("diagnostic_only"),
            "quote_permission_rows": paper_score_quote_permission_rows,
            "live_trade_permission_rows": paper_score_live_trade_permission_rows,
            "paper_score_freshness_status": paper_score_freshness_status,
            "live_forward_day_count": len(live_forward_days),
            "locked_policy_params": locked_policy_params,
            "fill_evidence_completeness_status": fill_status,
            "fill_evidence_promotion_grade": fill_promotion_grade,
            "fill_evidence_effective_promotion_grade": fill_effective_promotion_grade,
            "fill_evidence_vacuous": fill_evidence_vacuous,
            "fill_evidence_blockers": fill_blockers,
            "fill_evidence_quote_legs": fill_quote_legs,
            "conservative_fills": conservative_fills,
            "queue_estimated_fill_legs": queue_estimated_fill_legs,
            "missing_size_trade_rows": missing_size_trade_rows,
            "missing_book_queue_legs": missing_book_queue_legs,
            "unresolved_resting_quote_count": unresolved_resting_quotes,
            "total_reward_score": total_reward_score,
            "counterfactual_reward_usdc": counterfactual_reward_usdc,
            "counterfactual_reward_status": summary.get("counterfactual_reward_status"),
            "score_at_or_above_target_size": summary.get("score_at_or_above_target_size"),
            "net_pnl_after_fees_incentives_usdc": net_pnl,
            "actual_payout_evidence": actual_payout_evidence,
        },
        "gates": gates,
        "blockers": blockers,
        "next_actions": next_actions,
    }


def render_readiness_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Market-Making Live Readiness",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Live capital permission: `{payload.get('live_capital_permission')}`",
        f"- Requires explicit operator approval: `{payload.get('requires_explicit_operator_approval')}`",
        f"- Blocker count: `{payload.get('blocker_count')}`",
        f"- Target date: `{payload.get('target_date')}`",
        f"- Generated: `{payload.get('generated_at_utc')}`",
        "",
        "## Inputs",
        "",
    ]
    for key, value in (payload.get("inputs") or {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "|---|---:|",
    ])
    summary_fields = (
        "daily_roll_status",
        "daily_roll_action",
        "runtime_root_cause_class",
        "artifact_liveness_status",
        "operator_restart_recommended",
        "operator_restart_reason",
        "supervisor_state",
        "supervisor_action",
        "supervisor_expected_target_date",
        "preflight_status",
        "preflight_stale_market_count",
        "preflight_blocked_market_count",
        "preflight_remediation_status",
        "preflight_remediation_root_cause_counts",
        "preflight_remediation_owner_counts",
        "observation_trigger_runtime_root_cause_counts",
        "snapshot_model_source_failing_count",
        "snapshot_model_source_failing_gate_counts",
        "snapshot_model_source_failing_market_counts",
        "snapshot_model_source_failing_markets",
        "snapshot_model_source_missing_markets",
        "model_freshness_failed_market_count",
        "model_freshness_failed_markets",
        "source_status_degradation_failed_market_count",
        "source_status_degradation_failed_markets",
        "source_status_blocker_status",
        "source_status_blocker_root_cause_class",
        "source_status_blocked_market_count",
        "source_status_blocking_families",
        "source_status_settlement_auth_failures",
        "source_status_settlement_auth_failures_per_market",
        "source_status_settlement_auth_failure_market_count",
        "source_status_weather_com_credential_present",
        "source_status_weather_com_credential_present_by_var",
        "source_status_weather_com_credential_values_redacted",
        "source_status_repair_command",
        "evidence_mode",
        "current_counts_toward_live_forward_gate",
        "live_forward_gate_status",
        "paper_score_gate_status",
        "paper_score_gate_scope",
        "paper_score_live_capital_gate_status",
        "paper_score_live_capital_gate_reason",
        "paper_score_quote_permission_rows",
        "paper_quote_permission_market_counts",
        "paper_top_quote_permission_cells",
        "paper_quote_blocked_rows",
        "paper_quote_blocked_fraction",
        "paper_quote_blocker_reason_counts",
        "paper_quote_blocker_event_gate_suppressed_rows",
        "paper_quote_blocker_contextual_event_gate_suppressed_rows",
        "paper_quote_blocker_stale_input_rows",
        "latest_tick_quote_rows",
        "latest_tick_no_quote_rows",
        "latest_tick_quote_permission_rows",
        "latest_tick_first_failing_gate",
        "latest_tick_root_cause_class",
        "latest_tick_quote_outcome_status",
        "latest_tick_quote_outcome_reason",
        "latest_tick_reason_counts",
        "known_edge_map_path",
        "known_edge_map_schema_version",
        "known_edge_map_record_count",
        "known_edge_map_diagnostic_only",
        "paper_score_live_trade_permission_rows",
        "latest_tick_live_trade_permission_rows",
        "paper_score_freshness_status",
        "live_forward_day_count",
        "locked_policy_params",
        "fill_evidence_completeness_status",
        "fill_evidence_promotion_grade",
        "fill_evidence_effective_promotion_grade",
        "fill_evidence_vacuous",
        "fill_evidence_blockers",
        "fill_evidence_quote_legs",
        "conservative_fills",
        "queue_estimated_fill_legs",
        "missing_size_trade_rows",
        "missing_book_queue_legs",
        "unresolved_resting_quote_count",
        "total_reward_score",
        "counterfactual_reward_usdc",
        "counterfactual_reward_status",
        "score_at_or_above_target_size",
        "net_pnl_after_fees_incentives_usdc",
        "actual_payout_evidence",
    )
    for key in summary_fields:
        if key in summary:
            value = str(summary.get(key)).replace("|", "\\|")
            lines.append(f"| `{key}` | `{value}` |")
    lines.extend([
        "",
        "## Gates",
        "",
        "| Gate | Status | Detail |",
        "|---|---:|---|",
    ])
    for gate in payload.get("gates") or []:
        detail = str(gate.get("detail") or "").replace("|", "\\|")
        lines.append(f"| `{gate.get('id')}` | `{gate.get('status')}` | {detail} |")
    blockers = payload.get("blockers") or []
    next_actions = payload.get("next_actions") or []
    lines.extend([
        "",
        "## Next Actions",
        "",
    ])
    if not next_actions:
        lines.append("- None.")
    else:
        lines.extend([
            "| Priority | Category | Gate | Safe Next Step |",
            "|---:|---|---|---|",
        ])
        for action in next_actions:
            step = str(action.get("safe_next_step") or "").replace("|", "\\|")
            lines.append(
                f"| `{action.get('priority')}` | `{action.get('category')}` | "
                f"`{action.get('gate_id')}` | {step} |"
            )
    lines.extend(["", "## Blockers", ""])
    if not blockers:
        lines.append("- None.")
    else:
        for gate in blockers:
            remediation = gate.get("remediation") or "inspect gate evidence"
            lines.append(f"- `{gate.get('id')}`: {remediation}")
    lines.append("")
    return "\n".join(lines)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Build a conservative market-making live-readiness summary.")
    parser.add_argument("--status", default=str(DEFAULT_STATUS_PATH), help="Daily-roll status or run-summary JSON path.")
    parser.add_argument("--paper-score", default=None, help="Paper score JSON path; defaults to newest mm_paper*.json.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--live-readiness", default=str(DEFAULT_LIVE_READINESS))
    parser.add_argument("--platform-verification", default=str(DEFAULT_PLATFORM_VERIFICATION))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--now", default=None)
    parser.add_argument("--min-live-forward-days", type=int, default=MIN_LIVE_FORWARD_DAYS)
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    payload = build_readiness_snapshot(
        status_path=Path(args.status),
        paper_score_path=Path(args.paper_score) if args.paper_score else None,
        backtest_root=Path(args.backtest_root),
        live_readiness_path=Path(args.live_readiness) if args.live_readiness else None,
        platform_verification_path=Path(args.platform_verification) if args.platform_verification else None,
        now=args.now,
        min_live_forward_days=args.min_live_forward_days,
    )
    json_path = write_json(args.json_out, payload)
    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_readiness_report(payload), encoding="utf-8")
    print(
        "MM live readiness: "
        f"{payload['status']} with {payload['blocker_count']} blockers -> {json_path}"
    )
    return payload


if __name__ == "__main__":
    main()
