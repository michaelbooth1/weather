from __future__ import annotations

import hashlib
import json
import re
import ctypes
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather import execution_host


@pytest.mark.skipif(os.name != "nt", reason="Windows session API")
def test_execution_session_matches_windows_process_metadata():
    observed = execution_host.current_execution_session_id()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"(Get-Process -Id {os.getpid()}).SessionId"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    assert observed == int(result.stdout.strip())


@pytest.mark.parametrize("session_id", [0, 1, 7])
def test_execution_session_id_comes_from_windows_process_api(monkeypatch, session_id):
    calls = []

    def query(pid, output):
        calls.append(pid)
        output._obj.value = session_id
        return 1

    kernel = SimpleNamespace(ProcessIdToSessionId=query)
    monkeypatch.setattr(execution_host, "os", SimpleNamespace(name="nt", getpid=lambda: 321))
    monkeypatch.setattr(execution_host, "ctypes", SimpleNamespace(
        WinDLL=lambda name, **kwargs: kernel, c_uint32=ctypes.c_uint32,
        c_int=ctypes.c_int, POINTER=ctypes.POINTER, byref=ctypes.byref,
    ), raising=False)
    assert execution_host.current_execution_session_id() == session_id
    assert calls == [321]


def test_execution_session_query_failure_cannot_look_like_a_desktop(monkeypatch):
    def query(pid, output):
        output._obj.value = 1
        return 0

    monkeypatch.setattr(execution_host, "os", SimpleNamespace(name="nt", getpid=lambda: 321))
    monkeypatch.setattr(execution_host, "ctypes", SimpleNamespace(
        WinDLL=lambda name, **kwargs: SimpleNamespace(ProcessIdToSessionId=query),
        c_uint32=ctypes.c_uint32, c_int=ctypes.c_int,
        POINTER=ctypes.POINTER, byref=ctypes.byref,
    ), raising=False)
    with pytest.raises(RuntimeError, match="session is unavailable"):
        execution_host.current_execution_session_id()


def test_execution_session_has_no_non_windows_fallback(monkeypatch):
    monkeypatch.setattr(execution_host, "os", SimpleNamespace(name="posix"))
    with pytest.raises(RuntimeError, match="Windows desktop session"):
        execution_host.current_execution_session_id()


def test_execution_host_profiles_are_explicit_and_closed() -> None:
    assert execution_host.CAPTURE_COLOCATED_HOST_PROFILE == "capture_colocated_v1"
    assert execution_host.PORTABLE_EXECUTION_HOST_PROFILE == "portable_execution_v1"
    assert execution_host.EXECUTION_HOST_PROFILES == {
        "capture_colocated_v1",
        "portable_execution_v1",
    }


def test_execution_host_id_is_stable_versioned_machine_binding(monkeypatch) -> None:
    monkeypatch.setattr(execution_host, "_machine_identity", lambda: "machine-guid")

    observed = execution_host.current_execution_host_id()
    expected = hashlib.sha256(
        b"international_live_execution_host_v2\x00machine-guid"
    ).hexdigest()

    assert observed == expected
    assert re.fullmatch(r"[0-9a-f]{64}", observed)


def test_execution_host_identity_does_not_use_spoofable_name_environment() -> None:
    text = Path(execution_host.__file__).read_text(encoding="utf-8")

    assert "COMPUTERNAME" not in text
    assert "USERNAME" not in text
    assert "MachineGuid" in text


def test_capture_assignment_requires_dedicated_host_and_no_portable_lane(
    tmp_path,
) -> None:
    path = tmp_path / "assignment.json"
    payload = {
        "schema_version": "international_live_execution_host_assignment_v0.1",
        "assignment_status": "UNASSIGNED",
        "dedicated_capture_execution_host_id": "a" * 64,
        "active_portable_execution_host_id": None,
        "active_portable_execution_principal_id": None,
        "reassignment_requires_new_production_tip": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = execution_host.require_current_capture_execution_assignment(
        path,
        execution_host_id="a" * 64,
    )

    assert result["assignment_status"] == "UNASSIGNED"


def test_portable_assignment_requires_exact_host_and_principal(tmp_path) -> None:
    path = tmp_path / "assignment.json"
    payload = {
        "schema_version": "international_live_execution_host_assignment_v0.1",
        "assignment_status": "ASSIGNED",
        "dedicated_capture_execution_host_id": "a" * 64,
        "active_portable_execution_host_id": "b" * 64,
        "active_portable_execution_principal_id": "c" * 64,
        "reassignment_requires_new_production_tip": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = execution_host.require_current_portable_execution_assignment(
        path,
        execution_host_id="b" * 64,
        execution_principal_id="c" * 64,
    )

    assert result["assignment_status"] == "ASSIGNED"
    with pytest.raises(execution_host.ExecutionHostAssignmentError):
        execution_host.require_current_portable_execution_assignment(
            path,
            execution_host_id="b" * 64,
            execution_principal_id="d" * 64,
        )


def test_capture_assignment_is_disabled_while_portable_lane_is_assigned(
    tmp_path,
) -> None:
    path = tmp_path / "assignment.json"
    payload = {
        "schema_version": "international_live_execution_host_assignment_v0.1",
        "assignment_status": "ASSIGNED",
        "dedicated_capture_execution_host_id": "a" * 64,
        "active_portable_execution_host_id": "b" * 64,
        "active_portable_execution_principal_id": "c" * 64,
        "reassignment_requires_new_production_tip": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        execution_host.ExecutionHostAssignmentError,
        match="disabled while a portable executor is assigned",
    ):
        execution_host.require_current_capture_execution_assignment(
            path,
            execution_host_id="a" * 64,
        )
