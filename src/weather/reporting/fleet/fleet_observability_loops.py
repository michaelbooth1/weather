"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

from weather.operations.supervisor import jsonl_integrity, read_writer_lock
from weather.reporting.fleet.fleet_observability_inventory import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def loop_artifact_integrity():
    rows = []

    def _repair_command(*paths):
        usable = [str(path) for path in paths if path]
        return "python -m weather.operations.loop_jsonl_repair repair " + " ".join(usable)

    for spec in SUPERVISED_LOOP_SPECS:
        status = {}
        status_path = Path(spec.status_path)
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            status = {}
        writer = read_writer_lock(spec.status_path)
        status_writer = status.get("status_writer") or {}
        active_pid = str(writer.get("pid")) if writer.get("exists") and writer.get("pid") is not None else None
        status_pid = str(status_writer.get("pid")) if status_writer.get("pid") is not None else None
        duplicate_writer = bool(active_pid and status_pid and active_pid != status_pid)
        diagnostics = jsonl_integrity(spec.diagnostics_path)
        if spec.name in BOT_DAILY_ROLL_SUPERVISOR_NAMES:
            console_path = Path(spec.console_log_path)
            console = {
                "path": str(console_path),
                "exists": console_path.exists(),
                "line_count": None,
                "valid_json_lines": None,
                "malformed_lines": 0,
                "examples": [],
                "malformed_line_numbers": [],
                "classification_counts": {},
                "ok": True,
                "skipped_reason": "plain_text_daily_roll_console",
            }
        else:
            console = jsonl_integrity(spec.console_log_path)
        malformed_lines = int(diagnostics.get("malformed_lines") or 0) + int(console.get("malformed_lines") or 0)
        malformed_samples = []
        for source, payload in (("diagnostics", diagnostics), ("console", console)):
            for sample in payload.get("examples") or []:
                malformed_samples.append({
                    "source": source,
                    "path": payload.get("path"),
                    **sample,
                })
        repair_paths = [
            payload.get("path")
            for payload in (diagnostics, console)
            if int(payload.get("malformed_lines") or 0)
        ]
        rows.append({
            "name": spec.name,
            "status_path": str(spec.status_path),
            "diagnostics_path": str(spec.diagnostics_path),
            "console_log_path": str(spec.console_log_path),
            "writer_lock": writer,
            "status_writer": status_writer,
            "duplicate_writer": duplicate_writer,
            "diagnostics_integrity": diagnostics,
            "console_integrity": console,
            "malformed_lines": malformed_lines,
            "malformed_samples": malformed_samples,
            "repair_command": _repair_command(*repair_paths) if repair_paths else None,
            "ok": malformed_lines == 0 and not duplicate_writer,
        })
    return {
        "schema_version": "loop_artifact_integrity_v0.1",
        "generated_at_utc": utc_now(),
        "rows": rows,
        "summary": {
            "loop_count": len(rows),
            "malformed_lines": sum(row["malformed_lines"] for row in rows),
            "duplicate_writer_count": sum(1 for row in rows if row.get("duplicate_writer")),
            "ok": all(row.get("ok") for row in rows),
        },
    }


def loop_integrity_alerts(integrity):
    alerts = []
    for row in (integrity or {}).get("rows") or []:
        if row.get("duplicate_writer"):
            add_alert(
                alerts,
                "critical",
                "fleet",
                "loop_integrity",
                f"{row.get('name')} status writer lock does not match status owner",
                {
                    "status_writer": row.get("status_writer"),
                    "writer_lock": row.get("writer_lock"),
                },
            )
        malformed = int(row.get("malformed_lines") or 0)
        if malformed:
            add_alert(
                alerts,
                "warning",
                "fleet",
                "loop_integrity",
                f"{row.get('name')} has {malformed} malformed JSONL/log lines",
                {
                    "diagnostics": row.get("diagnostics_integrity"),
                    "console": row.get("console_integrity"),
                    "samples": row.get("malformed_samples"),
                    "repair_command": row.get("repair_command"),
                },
            )
    return alerts


def _parse_event_time(value):
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_diagnostic_events(path, *, since=None):
    events = []
    path = Path(path)
    if not path.exists():
        return events
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return events
    with handle:
        for line_number, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event_time = _parse_event_time(event.get("time"))
            if since and event_time and event_time < since:
                continue
            events.append({"line": line_number, "event_time": event_time, "event": event})
    return events


def _event_text(event):
    try:
        return json.dumps(event, sort_keys=True, default=str).lower()
    except TypeError:
        return str(event).lower()


def classify_loop_diagnostic_event(event):
    text = _event_text(event)
    status = str(event.get("status") or "").lower()
    action = str(event.get("action") or "").lower()
    state = str(event.get("state") or "").lower()
    supervisor = event.get("supervisor")
    if status == "duplicate_writer_blocked":
        existing = event.get("existing_writer") or {}
        if existing.get("exists"):
            return "duplicate_writer_incident"
        return "duplicate_writer_blocked_benign"
    if "duplicate writer" in text or "matched_process_count" in text or "running_process_count" in text:
        return "duplicate_writer_prevention"
    if status == "stale_code" or state == "stale_code" or "code identity differs" in text or "runtime_identity_matches_current\": false" in text:
        return "stale_code"
    if "no space left" in text or "disk full" in text or "insufficient" in text and "disk" in text:
        return "disk_backpressure"
    if "permissionerror" in text or "access is denied" in text or "access denied" in text:
        return "permission_write_error"
    if action in {"start", "restart"} and state in {"dead", "unknown"}:
        return "process_dead_or_hung"
    if action == "restart" and state in {"degraded", "erroring"}:
        return "hung_or_erroring_heartbeat"
    if supervisor in {"start", "stop"} or action in {"start", "restart"}:
        return "manual_or_supervisor_restart"
    if status in {"error", "exception"} or "traceback" in text:
        return "loop_error"
    return "operational_event"


def _is_restart_event(event, restart_class):
    action = str(event.get("action") or "").lower()
    supervisor = event.get("supervisor")
    if action in {"start", "restart"}:
        return True
    if supervisor == "start":
        return True
    return restart_class in {
        "stale_code",
        "process_dead_or_hung",
        "hung_or_erroring_heartbeat",
        "manual_or_supervisor_restart",
    }


def _expiry_after_window(event_times, *, allowed_count, window_hours):
    times = sorted(
        event_time
        for event_time in event_times
        if event_time is not None
    )
    allowed_count = max(0, int(allowed_count))
    if len(times) <= allowed_count:
        return None
    expiring_index = len(times) - allowed_count - 1
    return times[expiring_index] + timedelta(hours=window_hours, seconds=1)


def _display_command(command):
    if not command:
        return None
    if isinstance(command, str):
        return command
    return " ".join(str(part) for part in command)


def _loop_owner(spec):
    if spec.name == SNAPSHOT_SUPERVISOR.name:
        return "weather snapshot/model loop"
    if spec.name == CLOB_SUPERVISOR.name:
        return "CLOB book supervisor"
    if spec.name == OBSERVATION_SUPERVISOR.name:
        return "observation-trigger supervisor"
    if spec.name == TAKER_DAILY_ROLL_SUPERVISOR.name:
        return "taker-bot daily-roll supervisor"
    if spec.name == MARKET_MAKING_DAILY_ROLL_SUPERVISOR.name:
        return "market-making daily-roll supervisor"
    return "unknown"


def _loop_status_payload(spec):
    path = Path(spec.status_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _loop_health_for_spec(spec, status, now, current_identity):
    if spec.name == SNAPSHOT_SUPERVISOR.name:
        from weather.collection.snapshot_tracker import loop_health
        from weather.collection.snapshot_tracker import TORONTO_TZ

        local_now = now.astimezone(TORONTO_TZ)
        return loop_health(status, local_now, current_identity=current_identity)
    if spec.name == CLOB_SUPERVISOR.name:
        return clob_loop_health(status, now=now)
    if spec.name == OBSERVATION_SUPERVISOR.name:
        return watcher_health(status, now=now)
    if spec.name in BOT_DAILY_ROLL_SUPERVISOR_NAMES:
        from weather.operations.bot_daily_roll_supervisor import daily_roll_health
        from weather.operations.market_making_daily_roll import pid_matches_market_making_run
        from weather.operations.taker_bot_daily_roll import pid_matches_taker_bot

        pid_alive = (
            pid_matches_taker_bot
            if spec.name == TAKER_DAILY_ROLL_SUPERVISOR.name
            else pid_matches_market_making_run
        )

        return daily_roll_health(
            status,
            target_date=(status or {}).get("target_date"),
            current_identity=current_identity,
            now=now,
            pid_alive=pid_alive,
        )
    return {}


def _loop_restart_command(spec):
    if spec.name == SNAPSHOT_SUPERVISOR.name:
        return spec.command("--restart")
    if spec.name in BOT_DAILY_ROLL_SUPERVISOR_NAMES:
        return spec.command("start", "--force")
    return spec.command("restart")


def _loop_ensure_command(spec):
    if spec.name == SNAPSHOT_SUPERVISOR.name:
        return spec.command("--ensure")
    return spec.command("ensure")


def _runtime_code_state(status, current_identity):
    runtime_identity = (status or {}).get("runtime_identity") or {}
    if not runtime_identity:
        return "unknown"
    return "current" if identities_match(runtime_identity, current_identity) else "stale_code"


def _status_writer_matches(row):
    writer = row.get("writer_lock") or {}
    status_writer = row.get("status_writer") or {}
    if not writer.get("exists"):
        return True
    writer_pid = str(writer.get("pid")) if writer.get("pid") is not None else None
    status_pid = str(status_writer.get("pid")) if status_writer.get("pid") is not None else None
    return bool(writer_pid and status_pid and writer_pid == status_pid)


def _current_code_soak_row(spec, integrity_by_name, *, current_identity, now, window_start, budget_start):
    status = _loop_status_payload(spec)
    health = _loop_health_for_spec(spec, status, now, current_identity)
    integrity = integrity_by_name.get(spec.name) or {}
    events = _read_diagnostic_events(spec.diagnostics_path, since=window_start)
    classes = Counter()
    active_day_classes = Counter()
    restart_classes = Counter()
    diagnostic_restart_classes = Counter()
    diagnostic_restart_count = 0
    restart_count = 0
    latest_restart_at = None
    restart_event_times = []
    duplicate_writer_incident_times = []
    latest_duplicate_writer_incident_at = None
    for item in events:
        event = item["event"]
        restart_class = classify_loop_diagnostic_event(event)
        classes[restart_class] += 1
        in_budget_window = bool(item.get("event_time") and item["event_time"] >= budget_start)
        if in_budget_window:
            active_day_classes[restart_class] += 1
            if restart_class == "duplicate_writer_incident":
                duplicate_writer_incident_times.append(item["event_time"])
                if (
                    latest_duplicate_writer_incident_at is None
                    or item["event_time"] > latest_duplicate_writer_incident_at
                ):
                    latest_duplicate_writer_incident_at = item["event_time"]
        if _is_restart_event(event, restart_class):
            diagnostic_restart_count += 1
            diagnostic_restart_classes[restart_class] += 1
            if in_budget_window:
                restart_count += 1
                restart_event_times.append(item["event_time"])
                restart_classes[restart_class] += 1
            if item.get("event_time") and (latest_restart_at is None or item["event_time"] > latest_restart_at):
                latest_restart_at = item["event_time"]
    runtime_state = _runtime_code_state(status, current_identity)
    state = health.get("state") or "UNKNOWN"
    restart_budget = int(LOOP_RESTART_BUDGETS.get(spec.name, 12))
    duplicate_writer_incidents = int(active_day_classes.get("duplicate_writer_incident") or 0)
    diagnostic_duplicate_writer_incidents = int(classes.get("duplicate_writer_incident") or 0)
    benign_duplicate_blocks = int(classes.get("duplicate_writer_blocked_benign") or 0)
    blocking_reasons = []
    immediate_repair_commands = []
    aging_blockers = []
    restart_command = _loop_restart_command(spec)
    ensure_command = _loop_ensure_command(spec)
    restart_budget_clears_at = _expiry_after_window(
        restart_event_times,
        allowed_count=restart_budget,
        window_hours=LOOP_RESTART_BUDGET_WINDOW_HOURS,
    )
    duplicate_writer_clears_at = _expiry_after_window(
        duplicate_writer_incident_times,
        allowed_count=0,
        window_hours=LOOP_RESTART_BUDGET_WINDOW_HOURS,
    )
    if state not in COUNTABLE_SOAK_STATES:
        blocking_reasons.append(f"state={state}")
        immediate_repair_commands.append(_display_command(ensure_command))
    if runtime_state != "current":
        blocking_reasons.append(f"runtime_code_state={runtime_state}")
        immediate_repair_commands.append(_display_command(restart_command))
    if int(health.get("consecutive_errors") or 0) != 0:
        blocking_reasons.append(f"consecutive_errors={health.get('consecutive_errors')}")
        immediate_repair_commands.append(_display_command(restart_command))
    if restart_count > restart_budget:
        blocking_reasons.append(f"restart_budget_exceeded={restart_count}>{restart_budget}")
        aging_blockers.append({
            "type": "restart_budget",
            "current": restart_count,
            "allowed": restart_budget,
            "clears_at_utc": restart_budget_clears_at.isoformat() if restart_budget_clears_at else None,
        })
    if duplicate_writer_incidents:
        blocking_reasons.append(f"duplicate_writer_incidents={duplicate_writer_incidents}")
        aging_blockers.append({
            "type": "duplicate_writer_incident_window",
            "current": duplicate_writer_incidents,
            "allowed": 0,
            "clears_at_utc": duplicate_writer_clears_at.isoformat() if duplicate_writer_clears_at else None,
        })
    if integrity.get("duplicate_writer") or not _status_writer_matches(integrity):
        blocking_reasons.append("active_writer_lock_mismatch")
        immediate_repair_commands.append(_display_command(restart_command))
    if int(integrity.get("malformed_lines") or 0):
        blocking_reasons.append(f"malformed_loop_lines={integrity.get('malformed_lines')}")
        immediate_repair_commands.append(integrity.get("repair_command"))
    immediate_repair_commands = [
        command
        for index, command in enumerate(immediate_repair_commands)
        if command and command not in immediate_repair_commands[:index]
    ]
    return {
        "name": spec.name,
        "status": "PASS" if not blocking_reasons else "BLOCK",
        "counts_toward_active_day": not blocking_reasons,
        "state": state,
        "pid": health.get("pid") or status.get("pid"),
        "runtime_code_state": runtime_state,
        "running_code": format_runtime_identity(status.get("runtime_identity") or {}),
        "current_code": format_runtime_identity(current_identity),
        "consecutive_errors": health.get("consecutive_errors"),
        "heartbeat_age_seconds": health.get("heartbeat_age_seconds"),
        "heartbeat_age_minutes": health.get("heartbeat_age_min"),
        "last_capture_age_seconds": health.get("last_books_age_seconds"),
        "last_raw_books_age_seconds": health.get("last_raw_books_age_seconds"),
        "raw_book_market_ages_seconds": health.get("raw_book_market_ages_seconds"),
        "raw_book_useful_iterations": health.get("raw_book_useful_iterations"),
        "last_derived_features_age_seconds": health.get("last_derived_features_age_seconds"),
        "derived_feature_market_ages_seconds": health.get("derived_feature_market_ages_seconds"),
        "derived_feature_error_markets": health.get("derived_feature_error_markets"),
        "last_capture_age_minutes": health.get("last_snapshot_age_min"),
        "last_iteration_elapsed_seconds": health.get("last_iteration_elapsed_seconds"),
        "max_recent_iteration_elapsed_seconds": health.get("max_recent_iteration_elapsed_seconds"),
        "last_iteration_elapsed_minutes": health.get("last_iteration_elapsed_minutes"),
        "max_recent_iteration_elapsed_minutes": health.get("max_recent_iteration_elapsed_minutes"),
        "restart_count": restart_count,
        "diagnostic_restart_count": diagnostic_restart_count,
        "restart_budget": restart_budget,
        "restart_budget_window_hours": LOOP_RESTART_BUDGET_WINDOW_HOURS,
        "restart_budget_clears_at_utc": restart_budget_clears_at.isoformat() if restart_budget_clears_at else None,
        "latest_restart_at_utc": latest_restart_at.isoformat() if latest_restart_at else None,
        "restart_class_counts": dict(sorted(restart_classes.items())),
        "diagnostic_restart_class_counts": dict(sorted(diagnostic_restart_classes.items())),
        "diagnostic_class_counts": dict(sorted(classes.items())),
        "duplicate_writer_incidents": duplicate_writer_incidents,
        "diagnostic_duplicate_writer_incidents": diagnostic_duplicate_writer_incidents,
        "duplicate_writer_incident_window_hours": LOOP_RESTART_BUDGET_WINDOW_HOURS,
        "duplicate_writer_incidents_clear_at_utc": (
            duplicate_writer_clears_at.isoformat() if duplicate_writer_clears_at else None
        ),
        "latest_duplicate_writer_incident_at_utc": (
            latest_duplicate_writer_incident_at.isoformat() if latest_duplicate_writer_incident_at else None
        ),
        "benign_duplicate_writer_blocks": benign_duplicate_blocks,
        "single_writer": not bool(integrity.get("duplicate_writer")) and _status_writer_matches(integrity),
        "malformed_lines": int(integrity.get("malformed_lines") or 0),
        "blocking_reasons": blocking_reasons,
        "blocking_owner": _loop_owner(spec),
        "immediate_repair_required": bool(immediate_repair_commands),
        "immediate_repair_commands": immediate_repair_commands,
        "aging_blockers": aging_blockers,
        "status_path": str(spec.status_path),
        "diagnostics_path": str(spec.diagnostics_path),
        "restart_command": restart_command,
        "ensure_command": ensure_command,
    }


def current_code_soak_summary(loop_integrity, live_forward_slo, now=None, current_identity=None, specs=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current_identity = current_identity or get_runtime_identity()
    window_start = now - timedelta(days=LOOP_DIAGNOSTIC_WINDOW_DAYS)
    budget_start = now - timedelta(hours=LOOP_RESTART_BUDGET_WINDOW_HOURS)
    integrity_by_name = {
        row.get("name"): row
        for row in (loop_integrity or {}).get("rows") or []
    }
    specs = tuple(specs or SUPERVISED_LOOP_SPECS)
    loop_rows = [
        _current_code_soak_row(
            spec,
            integrity_by_name,
            current_identity=current_identity,
            now=now,
            window_start=window_start,
            budget_start=budget_start,
        )
        for spec in specs
    ]
    cadence_status = (live_forward_slo or {}).get("status")
    cadence_counts = bool((live_forward_slo or {}).get("counts_toward_live_forward_gate"))
    cadence_reason = (live_forward_slo or {}).get("reason")
    blocking_loop_count = sum(1 for row in loop_rows if row.get("status") != "PASS")
    counts_toward_active_day = blocking_loop_count == 0 and cadence_counts
    status = "PASS" if counts_toward_active_day else "BLOCK"
    class_counts = Counter()
    restart_class_counts = Counter()
    for row in loop_rows:
        class_counts.update(row.get("diagnostic_class_counts") or {})
        restart_class_counts.update(row.get("restart_class_counts") or {})
    immediate_repair_rows = [row for row in loop_rows if row.get("immediate_repair_required")]
    aging_rows = [row for row in loop_rows if row.get("aging_blockers")]
    aging_clears_at = [
        blocker.get("clears_at_utc")
        for row in aging_rows
        for blocker in row.get("aging_blockers") or []
        if blocker.get("clears_at_utc")
    ]
    first_immediate_command = next(
        (
            (row.get("immediate_repair_commands") or [None])[0]
            for row in immediate_repair_rows
            if row.get("immediate_repair_commands")
        ),
        None,
    )
    latest_aging_clear = max(aging_clears_at) if aging_clears_at else None
    return {
        "schema_version": CURRENT_CODE_SOAK_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "window_start_utc": window_start.isoformat(),
        "restart_budget_window_start_utc": budget_start.isoformat(),
        "window_days": LOOP_DIAGNOSTIC_WINDOW_DAYS,
        "status": status,
        "counts_toward_active_day": counts_toward_active_day,
        "current_identity": current_identity,
        "cadence_slo_status": cadence_status,
        "cadence_slo_counts": cadence_counts,
        "cadence_slo_reason": cadence_reason,
        "restart_budgets": LOOP_RESTART_BUDGETS,
        "restart_budget_window_hours": LOOP_RESTART_BUDGET_WINDOW_HOURS,
        "loops": loop_rows,
        "summary": {
            "loop_count": len(loop_rows),
            "blocking_loop_count": blocking_loop_count,
            "restart_count": sum(int(row.get("restart_count") or 0) for row in loop_rows),
            "diagnostic_restart_count": sum(int(row.get("diagnostic_restart_count") or 0) for row in loop_rows),
            "restart_class_counts": dict(sorted(restart_class_counts.items())),
            "diagnostic_class_counts": dict(sorted(class_counts.items())),
            "duplicate_writer_incident_count": sum(int(row.get("duplicate_writer_incidents") or 0) for row in loop_rows),
            "diagnostic_duplicate_writer_incident_count": sum(
                int(row.get("diagnostic_duplicate_writer_incidents") or 0) for row in loop_rows
            ),
            "benign_duplicate_writer_block_count": sum(int(row.get("benign_duplicate_writer_blocks") or 0) for row in loop_rows),
            "malformed_lines": sum(int(row.get("malformed_lines") or 0) for row in loop_rows),
            "current_code_loop_count": sum(1 for row in loop_rows if row.get("runtime_code_state") == "current"),
            "single_writer_loop_count": sum(1 for row in loop_rows if row.get("single_writer")),
            "cadence_slo_status": cadence_status,
            "immediate_repair_loop_count": len(immediate_repair_rows),
            "aging_blocker_loop_count": len(aging_rows),
            "first_immediate_repair_command": first_immediate_command,
            "latest_aging_blocker_clears_at_utc": latest_aging_clear,
            "first_blocking_loop": next((row.get("name") for row in loop_rows if row.get("status") != "PASS"), None),
            "first_blocking_reason": next(
                ("; ".join(row.get("blocking_reasons") or []) for row in loop_rows if row.get("status") != "PASS"),
                None,
            ) or (cadence_reason if not cadence_counts else None),
        },
        "verification_command": BROAD_SLO_VERIFY_COMMAND,
    }


def current_code_soak_alerts(soak):
    if not soak or soak.get("status") == "PASS":
        return []
    summary = soak.get("summary") or {}
    return [{
        "severity": "critical",
        "market_id": "fleet",
        "category": "current_code_soak",
        "message": (
            "current-code loop soak is BLOCK: "
            f"{summary.get('first_blocking_loop') or 'cadence_slo'} "
            f"{summary.get('first_blocking_reason') or soak.get('cadence_slo_reason') or ''}"
        ).strip(),
        "detail": {
            "status": soak.get("status"),
            "counts_toward_active_day": soak.get("counts_toward_active_day"),
            "summary": summary,
            "verification_command": soak.get("verification_command"),
        },
    }]

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
