"""Operations page view for the Streamlit app."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from app.table_utils import arrow_safe_records
from weather.paths import REPO_ROOT, data_path


CAPTURE_STREAK_SCRIPT = REPO_ROOT / "scripts" / "ops" / "streak_status.py"
HOST_STATUS_SCRIPT = REPO_ROOT / "scripts" / "ops" / "status.ps1"
RELEASE_CLOCK_PATH = data_path("backtest", "release_admissibility", "clock.json")
DAILY_REFRESH_STATUS_PATH = data_path("backtest", "daily_refresh_status.json")
MORNING_BRIEFING_PATH = data_path("alerts", "MORNING_BRIEFING.md")
MAX_STATUS_BYTES = 5 * 1024 * 1024
MAX_BRIEFING_BYTES = 1024 * 1024


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_text(timestamp, *, now=None):
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return "unknown age"
    now = now or datetime.now(timezone.utc)
    seconds = max(0.0, (now - parsed).total_seconds())
    if seconds < 120:
        return f"{int(seconds)} seconds ago"
    if seconds < 7200:
        return f"{seconds / 60:.0f} minutes ago"
    return f"{seconds / 3600:.1f} hours ago"


def _json_artifact(path):
    path = Path(path)
    if not path.exists():
        return {"available": False, "path": str(path), "error": "file missing"}
    try:
        metadata = path.stat()
        if metadata.st_size > MAX_STATUS_BYTES:
            raise ValueError(f"status file exceeds {MAX_STATUS_BYTES} bytes")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status payload is not an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "available": False,
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    generated_at = (
        payload.get("generated_at_utc")
        or payload.get("generated_at")
        or payload.get("as_of_utc")
    )
    if generated_at is None:
        generated_at = datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat()
    return {
        "available": True,
        "path": str(path),
        "payload": payload,
        "recorded_at": generated_at,
        "age": _age_text(generated_at),
    }


def _text_artifact(path):
    path = Path(path)
    if not path.exists():
        return {"available": False, "path": str(path), "error": "file missing"}
    try:
        if path.stat().st_size > MAX_BRIEFING_BYTES:
            raise ValueError(f"briefing exceeds {MAX_BRIEFING_BYTES} bytes")
        text = path.read_text(encoding="utf-8")
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "available": False,
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "available": True,
        "path": str(path),
        "text": text,
        "recorded_at": modified_at,
        "age": _age_text(modified_at),
    }


def capture_streak_snapshot(script_path=CAPTURE_STREAK_SCRIPT):
    """Run the canonical read-only streak checker and return its JSON result."""

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [sys.executable, str(script_path), "--json"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=10,
            creationflags=creationflags,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "streak checker failed")
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("streak checker did not return an object")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return {
            "available": False,
            "path": str(script_path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"available": True, "path": str(script_path), "payload": payload}


def host_status_snapshot(script_path=HOST_STATUS_SCRIPT):
    """Run the canonical read-only host digest; ATTENTION exit code 2 is valid."""

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Json",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=20,
            creationflags=creationflags,
        )
        if result.returncode not in {0, 2}:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "host status failed")
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("host status did not return an object")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return {
            "available": False,
            "path": str(script_path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"available": True, "path": str(script_path), "payload": payload}


def _capture_streak_from_host_status(host_status):
    if not host_status.get("available"):
        return None
    streak = (host_status.get("payload") or {}).get("streak")
    if not isinstance(streak, dict) or streak.get("days") is None:
        return None
    return {
        "available": True,
        "path": host_status.get("path"),
        "payload": {
            "streak_days": streak.get("days"),
            "target": streak.get("target"),
            "streak_start": streak.get("start"),
            "most_recent_settled": streak.get("settled"),
            "projected_lock_date_if_all_clean": streak.get("lock"),
            "today_summary": streak.get("today"),
        },
    }


def collect_operations_snapshot():
    from weather.operations.ops_monitor import (
        loop_status_rows,
        nightly_retrain_status_rows,
        scheduled_task_rows,
    )
    from weather.runtime_identity import get_runtime_identity

    current_identity = get_runtime_identity()
    host_status = host_status_snapshot()
    return {
        "current_identity": current_identity,
        "loops": loop_status_rows(current_identity),
        "nightly": nightly_retrain_status_rows(),
        "tasks": scheduled_task_rows(),
        "host_status": host_status,
        "capture_streak": _capture_streak_from_host_status(host_status) or capture_streak_snapshot(),
        "release_clock": _json_artifact(RELEASE_CLOCK_PATH),
        "daily_refresh": _json_artifact(DAILY_REFRESH_STATUS_PATH),
        "morning_briefing": _text_artifact(MORNING_BRIEFING_PATH),
    }


def _daily_refresh_summary(artifact):
    if not artifact.get("available"):
        return {
            "status": "Unavailable",
            "run_state": "Unknown",
            "step": "-",
            "reason": artifact.get("error") or "status unavailable",
        }
    payload = artifact.get("payload") or {}
    current_step = payload.get("current_step") or {}
    if str(current_step.get("status") or "").lower().startswith("running"):
        return {
            "status": payload.get("status") or "running",
            "run_state": "RUNNING NOW",
            "step": current_step.get("name") or "unknown step",
            "reason": current_step.get("status") or "running",
        }
    failed = next(
        (
            row
            for row in payload.get("steps") or []
            if row.get("status") not in {None, "ok", "skipped"}
        ),
        None,
    )
    reason = None
    if failed:
        result = failed.get("result") or {}
        reason = (
            result.get("reason")
            or failed.get("error")
            or result.get("status")
            or failed.get("status")
        )
    return {
        "status": payload.get("status") or "unknown",
        "run_state": "terminal" if payload.get("terminal") else "stored state; activity unknown",
        "step": (failed or {}).get("name") or "none recorded",
        "reason": reason or "-",
    }


def render_host_truth(snapshot):
    """Render the small, read-only host evidence that operators act on first."""

    capture = snapshot.get("capture_streak") or {}
    host = snapshot.get("host_status") or {}
    release = snapshot.get("release_clock") or {}
    daily = snapshot.get("daily_refresh") or {}
    briefing = snapshot.get("morning_briefing") or {}
    capture_payload = capture.get("payload") or {}
    release_payload = release.get("payload") or {}
    daily_summary = _daily_refresh_summary(daily)
    today = capture_payload.get("today_health")

    st.subheader("Host Status")
    if host.get("available"):
        host_payload = host.get("payload") or {}
        flags = host_payload.get("flags") or []
        warnings = host_payload.get("warns") or []
        disk = host_payload.get("disk") or {}
        watchdog = host_payload.get("watchdog") or {}
        host_cols = st.columns(5)
        host_cols[0].metric("Host verdict", host_payload.get("verdict") or "UNKNOWN")
        host_cols[1].metric("Flags", len(flags))
        host_cols[2].metric(
            "RAM free",
            f"{host_payload.get('ram_free_gb')} GB"
            if host_payload.get("ram_free_gb") is not None
            else "Unknown",
        )
        host_cols[3].metric(
            "Disk headroom",
            f"{disk.get('days_left')} days"
            if disk.get("days_left") is not None
            else (
                f"{disk.get('free_gb')} GB free"
                if disk.get("free_gb") is not None
                else "Unknown"
            ),
        )
        host_cols[4].metric(
            "Watchdog",
            watchdog.get("verdict") or "UNKNOWN",
            delta=(
                f"{watchdog.get('age_min')} min old"
                if watchdog.get("age_min") is not None
                else None
            ),
            delta_color="off",
        )
        st.caption(
            f"Canonical host digest `{host.get('path')}` recorded "
            f"{host_payload.get('ts') or 'at an unknown time'}."
        )
        if flags:
            st.error("Host flags: " + " | ".join(str(item) for item in flags))
        elif warnings:
            st.warning("Host warnings: " + " | ".join(str(item) for item in warnings))
        else:
            st.success("The canonical host digest reports no flags or warnings.")
    else:
        st.warning(f"Host status unavailable: {host.get('error') or 'unknown error'}")

    st.subheader("Capture and Release Clocks")
    st.caption(
        "Operational capture continuity and release admissibility are separate clocks. "
        "A full capture streak is necessary, never sufficient, for release."
    )
    clock_cols = st.columns(4)
    clock_cols[0].metric(
        "Capture streak",
        (
            f"{capture_payload.get('streak_days')} / {capture_payload.get('target')}"
            if capture.get("available")
            else "Unavailable"
        ),
    )
    clock_cols[1].metric(
        "Release-admissible days",
        (
            str(release_payload.get("contiguous_pass_days"))
            if release.get("available")
            else "Unavailable"
        ),
    )
    clock_cols[2].metric(
        "Today's capture",
        (
            str(
                capture_payload.get("today_summary")
                or (today or {}).get("verdict")
                or "already settled"
            ).upper()
            if capture.get("available")
            else "Unknown"
        ),
    )
    clock_cols[3].metric("Daily refresh", str(daily_summary["status"]).upper())

    clock_rows = [
        {
            "Clock": "Operational capture",
            "State": (
                f"{capture_payload.get('streak_days')} / {capture_payload.get('target')}"
                if capture.get("available")
                else "Unavailable"
            ),
            "Start": capture_payload.get("streak_start") or "-",
            "Latest": capture_payload.get("most_recent_settled") or "-",
            "Next boundary": capture_payload.get("projected_lock_date_if_all_clean") or "-",
            "Evidence": capture.get("path"),
        },
        {
            "Clock": "Release admissibility",
            "State": release_payload.get("latest_status") or "Unavailable",
            "Start": release_payload.get("streak_start_date") or "-",
            "Latest": release_payload.get("evaluation_end_date") or "-",
            "Next boundary": release_payload.get("latest_reason_code") or "-",
            "Evidence": release.get("path"),
        },
    ]
    st.dataframe(arrow_safe_records(clock_rows), width="stretch", hide_index=True)

    for label, artifact in (
        ("Capture streak", capture),
        ("Release clock", release),
    ):
        if not artifact.get("available"):
            st.warning(f"{label} unavailable: {artifact.get('error') or 'unknown error'}")
    if release.get("available"):
        st.caption(
            f"Release clock recorded {release.get('recorded_at') or '-'} "
            f"({release.get('age') or 'unknown age'}). This is a stored receipt collapse, not a live grade."
        )
    if capture_payload.get("recent_tape"):
        with st.expander("Recent capture-grade tape"):
            st.dataframe(
                arrow_safe_records(capture_payload["recent_tape"]),
                width="stretch",
                hide_index=True,
            )

    st.subheader("Daily Refresh")
    daily_cols = st.columns(4)
    daily_cols[0].metric("Recorded status", str(daily_summary["status"]).upper())
    daily_cols[1].metric("Run state", daily_summary["run_state"])
    daily_cols[2].metric("First non-OK step", daily_summary["step"])
    daily_cols[3].metric("Receipt age", daily.get("age") or "unknown")
    st.caption(
        f"Reason: {daily_summary['reason']} | Evidence: {daily.get('path') or '-'} | "
        "The last stored terminal receipt is not proof that a run is active now."
    )
    if not daily.get("available"):
        st.warning(f"Daily refresh status unavailable: {daily.get('error') or 'unknown error'}")

    st.subheader("Morning Briefing")
    if briefing.get("available"):
        st.caption(
            f"Recorded {briefing.get('recorded_at') or '-'} "
            f"({briefing.get('age') or 'unknown age'}); `{briefing.get('path')}`"
        )
        with st.expander("Open morning briefing", expanded=True):
            st.markdown(briefing.get("text") or "_Briefing is empty._")
    else:
        st.info(
            f"Morning briefing unavailable: {briefing.get('error') or 'unknown error'} "
            f"(`{briefing.get('path') or MORNING_BRIEFING_PATH}`)"
        )


def render_operations_page():
    from weather.operations.ops_monitor import (
        ensure_clob_book_loop,
        ensure_weather_loop,
        restart_clob_loop,
        restart_weather_loop,
        set_clob_paused,
        set_weather_paused,
        start_all_loops,
        stop_all_loops,
        stop_clob_book_loop,
        stop_weather_loop,
    )
    from weather.runtime_identity import format_runtime_identity

    @st.cache_data(ttl=15, show_spinner=False)
    def cached_ops_snapshot():
        return collect_operations_snapshot()

    def run_ops_action(label, action):
        try:
            st.session_state["ops_last_action"] = {
                "action": label,
                "result": action(),
            }
        except Exception as exc:  # noqa: BLE001 - operator actions should surface in-page
            st.session_state["ops_last_action"] = {
                "action": label,
                "error": f"{type(exc).__name__}: {exc}",
            }
        cached_ops_snapshot.clear()
        st.rerun()

    snapshot = cached_ops_snapshot()
    current_identity = snapshot["current_identity"]
    loop_rows = snapshot["loops"]
    nightly_row = snapshot["nightly"]
    task_rows = snapshot["tasks"]
    weather_row = next(
        (row for row in loop_rows if row["Loop"] == "Weather snapshots"),
        {"Loop": "Weather snapshots", "State": "MISSING", "Paused": False},
    )
    clob_row = next(
        (row for row in loop_rows if row["Loop"] == "CLOB books"),
        {"Loop": "CLOB books", "State": "MISSING", "Paused": False},
    )

    st.title("Operations")
    st.caption("Current checkout")
    st.code(format_runtime_identity(current_identity), language=None)

    render_host_truth(snapshot)

    if "ops_last_action" in st.session_state:
        with st.expander("Last Action", expanded=True):
            st.json(st.session_state["ops_last_action"])

    status_cols = st.columns(5)
    status_cols[0].metric("Weather", weather_row["State"] or "UNKNOWN")
    status_cols[1].metric("CLOB", clob_row["State"] or "UNKNOWN")
    stale_count = sum(1 for row in loop_rows if row["Code State"] == "different")
    status_cols[2].metric("Code Drift", stale_count)
    status_cols[3].metric("Nightly", nightly_row["State"] or "UNKNOWN")
    missing_tasks = sum(1 for row in task_rows if row.get("Registered") is False)
    unknown_tasks = sum(1 for row in task_rows if row.get("Registered") is None)
    status_cols[4].metric(
        "Task Issues",
        missing_tasks + unknown_tasks,
        help=f"{missing_tasks} missing; {unknown_tasks} could not be queried.",
    )

    action_cols = st.columns(3)
    if action_cols[0].button("Start / Repair All", type="primary", width="stretch"):
        run_ops_action("start_all", start_all_loops)
    if action_cols[1].button("Stop All", width="stretch"):
        run_ops_action("stop_all", stop_all_loops)
    if action_cols[2].button("Refresh", width="stretch"):
        cached_ops_snapshot.clear()
        st.rerun()

    st.subheader("Loop Status")
    visible_loop_cols = [
        "Loop",
        "State",
        "PID",
        "Heartbeat",
        "Last Capture",
        "Errors",
        "Paused",
        "Mode",
        "Code State",
        "Running Code",
        "Started At",
        "Last Error",
    ]
    st.dataframe(
        arrow_safe_records([{key: row.get(key) for key in visible_loop_cols} for row in loop_rows]),
        width="stretch",
        hide_index=True,
    )

    weather_controls, clob_controls = st.columns(2)
    with weather_controls:
        st.markdown("#### Weather Snapshots")
        if st.button("Ensure Weather", width="stretch"):
            run_ops_action("ensure_weather", ensure_weather_loop)
        if st.button("Restart Weather", width="stretch"):
            run_ops_action("restart_weather", restart_weather_loop)
        if st.button("Stop Weather", width="stretch"):
            run_ops_action("stop_weather", stop_weather_loop)
        if weather_row["Paused"]:
            if st.button("Resume Weather", width="stretch"):
                run_ops_action("resume_weather", lambda: set_weather_paused(False))
        else:
            if st.button("Pause Weather", width="stretch"):
                run_ops_action("pause_weather", lambda: set_weather_paused(True))

    with clob_controls:
        st.markdown("#### CLOB Books")
        if st.button("Ensure CLOB", width="stretch"):
            run_ops_action("ensure_clob", ensure_clob_book_loop)
        if st.button("Restart CLOB", width="stretch"):
            run_ops_action("restart_clob", restart_clob_loop)
        if st.button("Stop CLOB", width="stretch"):
            run_ops_action("stop_clob", stop_clob_book_loop)
        if clob_row["Paused"]:
            if st.button("Resume CLOB", width="stretch"):
                run_ops_action("resume_clob", lambda: set_clob_paused(False))
        else:
            if st.button("Pause CLOB", width="stretch"):
                run_ops_action("pause_clob", lambda: set_clob_paused(True))

    st.subheader("Nightly Self-Improvement")
    st.dataframe(arrow_safe_records([nightly_row]), width="stretch", hide_index=True)

    st.subheader("Supervisor Tasks")
    st.dataframe(arrow_safe_records(task_rows), width="stretch", hide_index=True)

    st.subheader("Files")
    st.dataframe(
        arrow_safe_records([
            {
                "Loop": row["Loop"],
                "Status File": row["Status File"],
                "Diagnostics": row["Diagnostics"],
                "Console Log": row["Console Log"],
            }
            for row in loop_rows
        ]),
        width="stretch",
        hide_index=True,
    )
    st.stop()
