"""Fail-closed evidence reduction for the operator control room."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.paths import data_path


INTERNATIONAL_PLATFORM = "polymarket_global"
RUNS_ROOT = data_path("mm_runs")
BACKTEST_ROOT = data_path("backtest")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def run_folders(runs_root=RUNS_ROOT):
    runs_root = Path(runs_root)
    if not runs_root.exists():
        return []
    folders = [summary.parent for summary in runs_root.glob("*/*/run_summary.json")]
    return sorted(folders, key=lambda folder: folder.stat().st_mtime, reverse=True)


def latest_run(runs_root=RUNS_ROOT):
    folders = run_folders(runs_root)
    if not folders:
        return None, {}
    folder = folders[0]
    payload = read_json(folder / "run_summary.json", {}) or {}
    return folder, payload if isinstance(payload, dict) else {}


def latest_readiness(backtest_root=BACKTEST_ROOT, target_date=None):
    """Return only exact-market-day readiness when a target date is supplied."""

    root = Path(backtest_root)
    if not root.exists():
        return None, {}
    candidates = [
        path for path in root.glob("mm_live_readiness*.json") if path.is_file()
    ]
    if target_date is not None:
        matching = []
        for path in candidates:
            payload = read_json(path, {}) or {}
            if (
                isinstance(payload, dict)
                and str(payload.get("target_date") or "") == str(target_date)
            ):
                matching.append((path, payload))
        return (
            max(matching, key=lambda item: item[0].stat().st_mtime)
            if matching
            else (None, {})
        )
    if not candidates:
        return None, {}
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = read_json(path, {}) or {}
    return path, payload if isinstance(payload, dict) else {}


def _text(value, fallback="-"):
    return fallback if value in (None, "") else str(value)


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def artifact_payload(artifact):
    if not isinstance(artifact, Mapping) or artifact.get("available") is not True:
        return {}
    value = artifact.get("payload")
    return value if isinstance(value, Mapping) else {}


def _state(status, detail, *, evidence=None):
    return {
        "status": status,
        "detail": detail,
        "evidence": evidence or "-",
    }


def _artifact(path):
    path = Path(path)
    payload = read_json(path, None)
    if not isinstance(payload, dict):
        return {
            "available": False,
            "path": str(path),
            "error": "file missing or payload is not a JSON object",
        }
    try:
        recorded_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        recorded_at = None
    return {
        "available": True,
        "path": str(path),
        "recorded_at": payload.get("generated_at_utc") or recorded_at,
        "payload": payload,
    }


def collect_control_room_snapshot(runs_root=RUNS_ROOT, backtest_root=BACKTEST_ROOT):
    """Collect bounded, read-only evidence for the operator control room."""

    backtest_root = Path(backtest_root)
    run_folder, run_summary = latest_run(runs_root)
    if not isinstance(run_summary, dict):
        run_summary = {}
    target_date = str((run_summary or {}).get("target_date") or "") or None
    readiness_path, readiness = (
        latest_readiness(backtest_root, target_date=target_date)
        if target_date
        else (None, {})
    )
    if not isinstance(readiness, dict):
        readiness = {}
    run_artifact = {
        "available": bool(run_folder and isinstance(run_summary, dict)),
        "path": str(run_folder / "run_summary.json") if run_folder else str(Path(runs_root)),
        "payload": run_summary if isinstance(run_summary, dict) else {},
    }
    if run_folder:
        try:
            run_artifact["recorded_at"] = datetime.fromtimestamp(
                (run_folder / "run_summary.json").stat().st_mtime,
                timezone.utc,
            ).isoformat()
        except OSError:
            run_artifact["recorded_at"] = None
    readiness_artifact = {
        "available": bool(readiness_path and isinstance(readiness, dict)),
        "path": str(readiness_path) if readiness_path else str(backtest_root),
        "payload": readiness if isinstance(readiness, dict) else {},
    }
    if readiness_path:
        readiness_artifact["recorded_at"] = (
            readiness.get("generated_at_utc")
            or datetime.fromtimestamp(readiness_path.stat().st_mtime, timezone.utc).isoformat()
        )
    elif target_date:
        readiness_artifact["error"] = f"no readiness receipt for target date {target_date}"
    else:
        readiness_artifact["error"] = "no current run target date is available"

    return {
        "target_date": target_date,
        "run": run_artifact,
        "readiness": readiness_artifact,
        "platform_verification": _artifact(backtest_root / "mm_platform_verification.json"),
        "economics_snapshot": _artifact(backtest_root / "exchange_economics_snapshot.json"),
        "economics_drift": _artifact(backtest_root / "exchange_economics_drift.json"),
        "economics_accepted": _artifact(
            backtest_root / "exchange_economics_accepted_snapshot.json"
        ),
    }


def evaluate_control_room(control, operations):
    """Reduce persisted artifacts to one conservative operator verdict."""

    target_date = control.get("target_date")
    host_artifact = operations.get("host_status") or {}
    host = artifact_payload(host_artifact)
    flags = list(host.get("flags") or [])
    host_ok = bool(host_artifact.get("available")) and host.get("verdict") == "OK" and not flags
    host_state = _state(
        "PASS" if host_ok else "BLOCK",
        (
            "Canonical host digest is OK with no active flags."
            if host_ok
            else (
                "Host digest unavailable."
                if not host_artifact.get("available")
                else f"Host verdict {_text(host.get('verdict'), 'UNKNOWN')} with {len(flags)} flag(s)."
            )
        ),
        evidence=host_artifact.get("path"),
    )

    streak = host.get("streak") or {}
    today = _text(streak.get("today"), "UNKNOWN")
    capture_ok = today.upper().startswith("ON_TRACK")
    capture_state = _state(
        "PASS" if capture_ok else "BLOCK",
        today,
        evidence=host_artifact.get("path"),
    )

    tape = host.get("execution_tape") or {}
    tape_ok = (
        tape.get("process_healthy") is True
        and tape.get("capture_state") == "CONNECTED"
        and tape.get("evidence_integrity") == "PASS"
        and tape.get("price_path_usable") is True
    )
    tape_state = _state(
        "PASS" if tape_ok else "BLOCK",
        (
            f"{_text(tape.get('capture_state'), 'UNKNOWN')} / integrity "
            f"{_text(tape.get('evidence_integrity'), 'UNKNOWN')} / price path "
            f"{'usable' if tape.get('price_path_usable') is True else 'not usable'}"
        ),
        evidence=host_artifact.get("path"),
    )

    readiness_artifact = control.get("readiness") or {}
    readiness = artifact_payload(readiness_artifact)
    readiness_current = (
        bool(target_date)
        and readiness_artifact.get("available") is True
        and str(readiness.get("target_date") or "") == str(target_date)
    )
    readiness_ok = (
        readiness_current
        and readiness.get("status") == "PASS"
        and readiness.get("live_capital_permission") is True
        and readiness.get("requires_explicit_operator_approval") is True
    )
    readiness_state = _state(
        "PASS" if readiness_ok else "BLOCK",
        (
            "Current receipt passes and grants software live-capital permission."
            if readiness_ok
            else (
                readiness_artifact.get("error")
                or (
                    "Current readiness is "
                    f"{_text(readiness.get('status'), 'unavailable')}; "
                    "live permission is not granted."
                )
            )
        ),
        evidence=readiness_artifact.get("path"),
    )

    platform_artifact = control.get("platform_verification") or {}
    platform = artifact_payload(platform_artifact)
    verified_date = platform.get("verified_for_target_date")
    platform_name = platform.get("platform")
    platform_ok = (
        bool(target_date)
        and platform_artifact.get("available") is True
        and platform_name == INTERNATIONAL_PLATFORM
        and str(verified_date or "") == str(target_date or "")
        and platform.get("status") == "PASS"
    )
    if platform_name == "polymarket_us":
        platform_detail = (
            "Polymarket US evidence is ineligible. "
            "This project uses International Polymarket only."
        )
    elif platform_ok:
        platform_detail = "International Polymarket identity is verified for the current target date."
    else:
        platform_detail = (
            f"International identity not proven for {target_date or 'the current run'} "
            f"(platform={_text(platform_name, 'missing')}, "
            f"status={_text(platform.get('status'), 'missing')})."
        )
    platform_state = _state(
        "PASS" if platform_ok else "BLOCK",
        platform_detail,
        evidence=platform_artifact.get("path"),
    )

    current_economics_artifact = control.get("economics_snapshot") or {}
    drift_artifact = control.get("economics_drift") or {}
    accepted_artifact = control.get("economics_accepted") or {}
    current_economics = artifact_payload(current_economics_artifact)
    drift = artifact_payload(drift_artifact)
    accepted = artifact_payload(accepted_artifact)
    economics_ok = (
        bool(target_date)
        and current_economics_artifact.get("available") is True
        and drift_artifact.get("available") is True
        and accepted_artifact.get("available") is True
        and current_economics.get("platform") == INTERNATIONAL_PLATFORM
        and accepted.get("platform") == INTERNATIONAL_PLATFORM
        and str(current_economics.get("target_date") or "") == str(target_date or "")
        and str(drift.get("target_date") or "") == str(target_date or "")
        and drift.get("status") == "PASS"
    )
    economics_state = _state(
        "PASS" if economics_ok else "BLOCK",
        (
            "Current International economics match the explicitly accepted baseline."
            if economics_ok
            else (
                f"Drift {_text(drift.get('status'), 'unavailable')}; current platform "
                f"{_text(current_economics.get('platform'), 'missing')}; accepted platform "
                f"{_text(accepted.get('platform'), 'missing')}."
            )
        ),
        evidence=drift_artifact.get("path"),
    )

    run = artifact_payload(control.get("run") or {})
    markets = run.get("markets")
    market_count = len(markets) if isinstance(markets, list) else None
    selected_markets = _number(
        run.get("selected_market_count")
        or (run.get("artifact_checks") or {}).get("selected_market_count")
        or market_count
    )
    run_budget = _number(run.get("budget_usdc") or run.get("run_budget_usdc"))
    envelope_ok = (
        bool(target_date)
        and run.get("mode") == "live-pilot"
        and selected_markets == 1
        and run_budget is not None
        and 0 < run_budget <= MAX_OPERATOR_PILOT_BUDGET_USDC
    )
    envelope_state = _state(
        "PASS" if envelope_ok else "BLOCK",
        (
            f"mode={_text(run.get('mode'), 'missing')}; markets="
            f"{_text(int(selected_markets) if selected_markets is not None else None, 'not evidenced')}; "
            f"budget={'$' + format(run_budget, ',.2f') if run_budget is not None else 'not evidenced'}."
        ),
        evidence=(control.get("run") or {}).get("path"),
    )

    states = {
        "Host": host_state,
        "Capture": capture_state,
        "International": platform_state,
        "Readiness": readiness_state,
        "Execution tape": tape_state,
        "Economics": economics_state,
        "Pilot envelope": envelope_state,
    }
    software_ready = all(item["status"] == "PASS" for item in states.values())
    verdict = "READY FOR EXPLICIT APPROVAL" if software_ready else "HOLD"
    return {
        "verdict": verdict,
        "software_ready": software_ready,
        "states": states,
        "target_date": target_date,
        "host": host,
        "readiness": readiness,
        "run": run,
        "pilot_contract": {
            "max_budget_usdc": MAX_OPERATOR_PILOT_BUDGET_USDC,
            "market_count": 1,
        },
        "economics": {
            "current": current_economics,
            "drift": drift,
            "accepted": accepted,
        },
    }


def attention_rows(evaluation, limit=8):
    """Return a bounded, decision-ordered list instead of the raw warning stream."""

    rows = []
    for name, state in evaluation["states"].items():
        if state["status"] != "PASS":
            rows.append({
                "Priority": len(rows) + 1,
                "Area": name,
                "What blocks progress": state["detail"],
            })
    readiness = evaluation.get("readiness") or {}
    for action in readiness.get("next_actions") or []:
        if len(rows) >= limit:
            break
        if not isinstance(action, Mapping):
            continue
        rows.append({
            "Priority": len(rows) + 1,
            "Area": _text(action.get("gate_id") or action.get("category"), "Readiness"),
            "What blocks progress": _text(
                action.get("safe_next_step")
                or action.get("remediation")
                or action.get("detail"),
                "Review the named readiness gate.",
            ),
        })
    return rows[:limit]
