"""Fail-closed evidence reduction for the operator control room."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
import math
from itertools import islice
from pathlib import Path

from weather.market.market_making_run_constants import MAX_OPERATOR_PILOT_BUDGET_USDC
from weather.market.exchange_economics import check_snapshot_payload, economics_drift_receipt_checks
from weather.paths import data_path
from weather.reporting.market.operator_evidence import checked_local_path, evidence_timestamp, freshness, parse_timestamp, read_artifact
from weather.schema_registry import schema_version


INTERNATIONAL_PLATFORM = "polymarket_global"
RUNS_ROOT = data_path("mm_runs")
BACKTEST_ROOT = data_path("backtest")


class EvidenceDiscoveryError(ValueError):
    """Bounded discovery could not establish the selected evidence."""


def _object(value):
    return value if isinstance(value, Mapping) else {}


def _indexed_run(runs_root):
    """Use the producer's current-run pointer before inspecting history."""
    root = Path(runs_root).absolute()
    artifact = read_artifact(root / "daily_roll_status.json", root=root)
    if (root / "daily_roll_status.json").exists() and artifact.get("available") is not True:
        raise EvidenceDiscoveryError("Current-run status is unreadable: " + str(artifact.get("error")))
    status = artifact_payload(artifact)
    value = (_object(status.get("operator_report")).get("latest_run_folder")
             or status.get("latest_run_folder") or status.get("run_folder"))
    if not value:
        return None, {}
    try:
        folder = Path(value)
        if ".." in folder.parts:
            raise ValueError("parent traversal")
        if not folder.is_absolute():
            parts = folder.parts
            if parts[:2] == ("data", "mm_runs"):
                parts = parts[2:]
            folder = root.joinpath(*parts)
        relative = folder.relative_to(root)
        if len(relative.parts) != 2:
            raise ValueError("expected a market-date/run folder")
        summary_path = checked_local_path(folder / "run_summary.json", root=root)
        summary = artifact_payload(read_artifact(summary_path, root=root))
        if (summary.get("run_id") != folder.name
                or summary.get("target_date") != folder.parent.name
                or (status.get("target_date") and status["target_date"] != summary.get("target_date"))):
            raise ValueError("pointer and run identities disagree")
        return folder, dict(summary)
    except (OSError, TypeError, ValueError) as exc:
        raise EvidenceDiscoveryError(f"Current-run pointer is invalid: {exc}") from exc


def read_json(path, default=None):
    return read_artifact(path).get("payload", default)


def run_folders(runs_root=RUNS_ROOT):
    runs_root = Path(runs_root)
    if not runs_root.exists():
        return []
    summaries = list(islice(runs_root.glob("*/*/run_summary.json"), 1025))
    if len(summaries) > 1024:
        raise EvidenceDiscoveryError("Run history exceeds the 1,024-summary discovery limit; a valid daily-roll current-run pointer is required.")
    return [path.parent for path in sorted(summaries, key=lambda path: path.stat().st_mtime, reverse=True)]


def latest_run(runs_root=RUNS_ROOT):
    indexed = _indexed_run(runs_root)
    if indexed[0] is not None:
        return indexed
    folders = run_folders(runs_root)
    if not folders:
        return None, {}
    # Parse only the newest bounded candidates; unrelated folder writes must
    # not select a historical run over a more recent producer observation.
    candidates = [(folder, read_json(folder / "run_summary.json", {}) or {}) for folder in folders[:24]]
    candidates = [(folder, payload) for folder, payload in candidates if isinstance(payload, dict)]
    return max(candidates, key=lambda item: parse_timestamp(evidence_timestamp(item[1]))
               or datetime.min.replace(tzinfo=timezone.utc), default=(None, {}))


def latest_readiness(backtest_root=BACKTEST_ROOT, target_date=None):
    """Return only exact-market-day readiness when a target date is supplied."""

    root = Path(backtest_root)
    if not root.exists():
        return None, {}
    current_path = root / "mm_live_readiness.json"
    current = read_json(current_path, {}) or {}
    if isinstance(current, dict) and current and (target_date is None or current.get("target_date") == str(target_date)):
        return current_path, current
    candidates = list(islice((path for path in root.glob("mm_live_readiness*.json") if path.is_file()), 257))
    if len(candidates) > 256:
        raise EvidenceDiscoveryError("Readiness history exceeds the 256-receipt discovery limit; publish the current target's canonical mm_live_readiness.json.")
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
    if isinstance(value, bool):
        return None
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
    return read_artifact(path)


def collect_control_room_snapshot(runs_root=RUNS_ROOT, backtest_root=BACKTEST_ROOT):
    """Collect bounded, read-only evidence for the operator control room."""

    backtest_root = Path(backtest_root)
    discovery_error = None
    try:
        run_folder, run_summary = latest_run(runs_root)
    except (EvidenceDiscoveryError, OSError) as exc:
        run_folder, run_summary = None, {}
        discovery_error = str(exc)
    if not isinstance(run_summary, dict):
        run_summary = {}
    target_date = str((run_summary or {}).get("target_date") or "") or None
    readiness_error = None
    try:
        readiness_path, readiness = (latest_readiness(backtest_root, target_date=target_date)
                                     if target_date else (None, {}))
    except (EvidenceDiscoveryError, OSError) as exc:
        readiness_path, readiness = None, {}
        readiness_error = str(exc)
    if not isinstance(readiness, dict):
        readiness = {}
    run_artifact = {
        "available": bool(run_folder and isinstance(run_summary, dict)),
        "path": str(run_folder / "run_summary.json") if run_folder else str(Path(runs_root)),
        "payload": run_summary if isinstance(run_summary, dict) else {},
    }
    if discovery_error:
        run_artifact["error"] = discovery_error
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
        readiness_artifact["error"] = readiness_error or f"no readiness receipt for target date {target_date}"
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


def evaluate_control_room(control, operations, *, now=None):
    """Reduce persisted artifacts to one conservative operator verdict."""

    now = now or datetime.now(timezone.utc)
    control = dict(_object(control))
    for key in ("run", "readiness", "platform_verification", "economics_snapshot", "economics_drift", "economics_accepted"):
        control[key] = _object(control.get(key))
    operations = _object(operations)
    target_date = control.get("target_date")
    host_artifact = _object(operations.get("host_status"))
    host = dict(artifact_payload(host_artifact))
    malformed = []
    for key in ("streak", "execution_tape", "chain", "git", "capture_runtime"):
        if host.get(key) is not None and not isinstance(host[key], Mapping):
            malformed.append(key)
            host[key] = {}
    if host.get("flags") is not None and not isinstance(host["flags"], list):
        malformed.append("flags")
        host["flags"] = []
    flags = list(host.get("flags") or [])
    host_ok = bool(host_artifact.get("available")) and host.get("verdict") == "OK" and not flags and not malformed
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
    if malformed:
        host_state = _state("BLOCK", "Malformed host evidence: " + ", ".join(malformed), evidence=host_artifact.get("path"))

    streak = host.get("streak") or {}
    today = _text(streak.get("today"), "UNKNOWN")
    capture_ok = today.upper().split(" (", 1)[0].strip() in {"ON_TRACK", "CLEAN"}
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
    run = artifact_payload(control.get("run") or {})
    run_id = run.get("run_id")
    readiness_run_id = readiness.get("run_id")
    run_pointer = _object(readiness.get("inputs")).get("latest_run_folder")
    pointer_matches = (isinstance(run_pointer, str) and run_pointer.replace("\\", "/").rstrip("/").split("/")[-2:]
                       == [str(target_date), str(run_id)])
    run_binding = bool(run_id) and (
        readiness_run_id == run_id if readiness_run_id is not None else pointer_matches
    ) and (not run_pointer or pointer_matches)
    gates = readiness.get("gates")
    readiness_current = (
        bool(target_date)
        and readiness_artifact.get("available") is True
        and str(readiness.get("target_date") or "") == str(target_date)
    )
    readiness_ok = (
        readiness_current
        and readiness.get("schema_version") == schema_version("mm_live_readiness")
        and run_binding
        and readiness.get("status") == "PASS"
        and readiness.get("live_capital_permission") is False
        and readiness.get("requires_explicit_operator_approval") is True
        and type(readiness.get("blocker_count")) is int and readiness["blocker_count"] == 0
        and isinstance(gates, list) and bool(gates)
        and all(isinstance(gate, Mapping) and gate.get("ok") is True for gate in gates)
        and readiness.get("next_actions") == []
    )
    readiness_state = _state(
        "PASS" if readiness_ok else "BLOCK",
        (
            "Recorded readiness checks pass for this run; launch checks have not been re-run."
            if readiness_ok
            else (
                readiness_artifact.get("error")
                or (
                    "Current readiness is "
                    f"{_text(readiness.get('status'), 'unavailable')}; "
                    "schema, blockers and run binding must agree. Live permission is not granted."
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
        and platform.get("schema_version") == schema_version("mm_platform_verification")
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
    current_gate = check_snapshot_payload(dict(current_economics), target_date=target_date,
                                          platform=INTERNATIONAL_PLATFORM, now=now, max_age_hours=2)
    accepted_gate = check_snapshot_payload(dict(accepted), target_date=target_date,
                                           platform=INTERNATIONAL_PLATFORM, now=now, max_age_hours=2)
    bindings = economics_drift_receipt_checks(dict(current_economics), dict(accepted), dict(drift))
    acceptance = _object(accepted.get("accepted_gate"))
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
        and drift.get("schema_version") == schema_version("exchange_economics_drift")
        and drift.get("platform") == INTERNATIONAL_PLATFORM
        and current_gate.get("ok") is True and accepted_gate.get("ok") is True
        and all(bindings.values())
        and acceptance.get("status") == "PASS"
        and acceptance.get("snapshot_hash") == accepted_gate.get("snapshot_hash")
        and acceptance.get("snapshot_id") == accepted_gate.get("snapshot_id")
    )
    economics_state = _state(
        "PASS" if economics_ok else "BLOCK",
        (
            "Current/accepted economics and recorded drift identities validate; action-time checks remain required."
            if economics_ok
            else (
                f"Drift {_text(drift.get('status'), 'unavailable')}; current platform "
                f"{_text(current_economics.get('platform'), 'missing')}; accepted platform "
                f"{_text(accepted.get('platform'), 'missing')}. Content, acceptance and drift bindings are not verified."
            )
        ),
        evidence=drift_artifact.get("path"),
    )

    run = artifact_payload(control.get("run") or {})
    markets = run.get("markets")
    market_count = len(markets) if isinstance(markets, list) else None
    selected_markets = _number(
        run.get("selected_market_count")
        or _object(run.get("artifact_checks")).get("selected_market_count")
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
    # This display policy is separate from the executor's action-time gates.
    # A copied file or matching old market date cannot renew an observation.
    observations = {
        "Host": [host_artifact],
        "Capture": [host_artifact],
        "Execution tape": [host_artifact],
        "International": [platform_artifact],
        "Readiness": [readiness_artifact],
        "Economics": [current_economics_artifact, drift_artifact],
        "Pilot envelope": [control.get("run") or {}],
    }
    ages = {}
    for name, artifacts in observations.items():
        checks = [freshness(item, now=now, max_age_seconds=600) for item in artifacts]
        ages[name] = checks
        invalid = next((item for item in checks if item["status"] != "CURRENT"), None)
        if invalid:
            states[name] = _state(invalid["status"], invalid["detail"],
                                  evidence=states[name]["evidence"])
    readiness_run_id = readiness.get("run_id")
    if readiness_run_id and readiness_run_id != run.get("run_id"):
        states["Readiness"] = _state("BLOCK", "Readiness belongs to a different run.",
                                      evidence=readiness_artifact.get("path"))
    try:
        historical_target = date.fromisoformat(str(target_date)) < (now - timedelta(days=1)).date()
    except ValueError:
        historical_target = False
    if historical_target:
        states["Pilot envelope"] = _state("HISTORICAL", "The selected market date is historical.",
                                          evidence=(control.get("run") or {}).get("path"))
    recorded_checks_passed = all(item["status"] == "PASS" for item in states.values())
    verdict = "RECORDED CHECKS PASS — SESSION VALIDATION REQUIRED" if recorded_checks_passed else "HOLD"
    return {
        "verdict": verdict,
        "software_ready": False,
        "recorded_checks_passed": recorded_checks_passed,
        "states": states,
        "freshness": ages,
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
