"""Server-wide monitoring caches; browser reruns never call exchange APIs."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from weather.paths import REPO_ROOT


def evidence_repository():
    value = os.environ.get("WEATHER_MONITOR_DATA_REPO")
    root = Path(value) if value else REPO_ROOT
    if not root.is_absolute():
        raise ValueError("The monitoring evidence repository must be an absolute path.")
    return root


@st.cache_data(ttl=300, show_spinner=False)
def _capture_host_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment
    try:
        assignment = load_execution_host_assignment()
        if current_execution_host_id() != assignment["dedicated_capture_execution_host_id"]:
            return {"available": False, "error": "Capture-host evidence is not connected on this computer."}
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        return {"available": False, "error": f"Capture-host identity unavailable: {exc}"}
    return None


@st.cache_resource(show_spinner=False)
def _host_collector(repo_root):
    from weather.operations.operator_host_status import HostStatusCache, host_status_snapshot

    return HostStatusCache(lambda: host_status_snapshot(repo_root=repo_root))


@st.cache_data(ttl=60, show_spinner=False)
def _host_receipt(path):
    from weather.reporting.market.operator_evidence import read_artifact

    return read_artifact(path)


def cached_host_status(repo_root, receipt_path=None):
    if receipt_path:
        return _host_receipt(receipt_path)
    identity_error = _capture_host_identity()
    return identity_error or _host_collector(repo_root).get()


@st.cache_data(ttl=60, show_spinner=False)
def cached_control_snapshot(repo_root):
    from weather.reporting.market.operator_control_room import collect_control_room_snapshot

    root = Path(repo_root) / "data"
    return collect_control_room_snapshot(root / "mm_runs", root / "backtest")


@st.cache_data(ttl=60, show_spinner=False)
def cached_project():
    from weather.reporting.roadmap.project_overview import collect_project_overview

    return collect_project_overview()


def load_control_snapshot():
    root = evidence_repository()
    return cached_control_snapshot(str(root)), {
        "host_status": cached_host_status(str(root), os.environ.get("WEATHER_MONITOR_CAPTURE_STATUS")),
    }


def load_monitor_extras(control):
    from weather.reporting.market.operator_session import collect_portable_session, portable_host_observation
    from weather.reporting.market.operator_trading import collect_trading_snapshot

    collectors = {
        "project": cached_project,
        "session": lambda: collect_portable_session(os.environ.get("WEATHER_MONITOR_ATTEMPT_ROOT")),
        "portable": lambda: portable_host_observation(os.environ.get("WEATHER_MONITOR_PORTABLE_STATUS")),
        "trading": lambda: collect_trading_snapshot(control.get("run") or {}),
    }
    result = {"errors": []}
    for name, collect in collectors.items():
        try:
            result[name] = collect()
        except Exception as exc:  # noqa: BLE001 - isolate independent read-only evidence families
            detail = f"{name.capitalize()} evidence unavailable: {type(exc).__name__}: {exc}"
            result[name] = {"available": False, "detail": detail, "status": "UNAVAILABLE"}
            result["errors"].append(detail)
    return result
