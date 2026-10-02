from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from weather.operations import thin_ensure as thin


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def prepared(monkeypatch, tmp_path, loop):
    identity = {"source_scope_files": ["src/weather/paths.py"], "source_fingerprint": "fixture"}
    status = {"pid": 12345, "last_heartbeat": NOW.isoformat(), "runtime_identity": identity,
              "interval_minutes": 10, "interval_seconds": 60,
              "last_market_results": {"fixture": {"books": 1, "captured_tokens": 2}}}
    monkeypatch.setattr(thin.supervision, "read_json_file", lambda path: status)
    monkeypatch.setattr(thin.supervision, "pid_is_python", lambda pid: True)
    monkeypatch.setattr(thin.supervision, "loop_writer_lock_health", lambda *a, **k: {"healthy": True})
    monkeypatch.setattr(thin, "current_identity_for", lambda value: identity)
    monkeypatch.setattr(thin, "process_rows", lambda: [
        {"pid": 12345, "command_line": "python -m weather.market.market_microstructure loop"}])
    monkeypatch.setattr(thin.supervision, "supervisor_recovery_guard", lambda *a, **k: {"allowed": True})
    monkeypatch.setattr(thin.supervision, "persist_supervisor_status", lambda spec, result, **k: result)
    return status


@pytest.mark.parametrize("loop", ["snapshot", "clob"])
def test_healthy_noop_never_imports_loop_and_releases_lock(monkeypatch, tmp_path, loop):
    prepared(monkeypatch, tmp_path, loop)
    monkeypatch.setattr(thin.importlib, "import_module", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    result = thin.ensure(loop, now=NOW, root=tmp_path)
    assert result["action"] == "noop"
    assert result["state"] == "RUNNING"
    assert not thin.supervisor_spec(loop, tmp_path).lock_path.exists()


@pytest.mark.parametrize("failure", ["stale", "dead", "lock", "unknown_identity", "changed_code", "paused", "errors", "orphan", "target", "discovery"])
def test_uncertain_probe_delegates_to_owner_with_lock_released(monkeypatch, tmp_path, failure):
    status = prepared(monkeypatch, tmp_path, "clob")
    if failure == "stale": status["last_heartbeat"] = (NOW - timedelta(hours=1)).isoformat()
    if failure == "dead": monkeypatch.setattr(thin.supervision, "pid_is_python", lambda pid: False)
    if failure == "lock": monkeypatch.setattr(thin.supervision, "loop_writer_lock_health", lambda *a, **k: {"healthy": False})
    if failure == "unknown_identity": status["runtime_identity"] = None
    if failure == "changed_code": monkeypatch.setattr(thin, "current_identity_for", lambda _: {"source_fingerprint": "changed"})
    if failure == "paused": status["paused"] = True
    if failure == "errors": status["consecutive_errors"] = 1
    if failure == "orphan": monkeypatch.setattr(thin, "process_rows", lambda: [
        {"pid": pid, "command_line": "python -m weather.market.market_microstructure loop"}
        for pid in (12345, 12346, 12347)])
    if failure == "target": status["target_date"] = "2026-08-01"
    if failure == "discovery": status["last_market_results"] = {"fixture": {"books": 0, "captured_tokens": 0}}
    calls = []
    def canonical(**kwargs):
        assert not thin.supervisor_spec("clob", tmp_path).lock_path.exists()
        calls.append(kwargs)
        return {"action": "restart_blocked"}
    monkeypatch.setattr(thin.importlib, "import_module", lambda name: SimpleNamespace(ensure_clob_loop=canonical))
    assert thin.ensure("clob", now=NOW, root=tmp_path)["action"] == "restart_blocked"
    assert calls == [dict(market_id="all", interval_seconds=60, fast_interval_seconds=15, now=NOW)]


def test_snapshot_fallback_and_cli_exit_code(monkeypatch, tmp_path):
    prepared(monkeypatch, tmp_path, "snapshot")["runtime_identity"] = None
    calls = []
    monkeypatch.setattr(thin.importlib, "import_module", lambda name: SimpleNamespace(
        ensure_loop=lambda **kwargs: (calls.append(kwargs), {"action": "noop"})[1]))
    thin.ensure("snapshot", now=NOW, root=tmp_path, interval_minutes=12)
    assert calls == [dict(interval_minutes=12, now=NOW)]
    monkeypatch.setattr(thin, "ensure", lambda *a, **k: {"action": "restart_blocked"})
    assert thin.main(["--ensure", "--loop", "snapshot"]) != 0


def test_wiring_matches_canonical_owner_and_import_stays_light():
    from weather.collection.snapshot_tracker import SNAPSHOT_SUPERVISOR
    from weather.market.market_microstructure import CLOB_SUPERVISOR
    for loop, canonical in [("snapshot", SNAPSHOT_SUPERVISOR), ("clob", CLOB_SUPERVISOR)]:
        spec = thin.supervisor_spec(loop)
        for field in ("name", "module", "status_path", "diagnostics_path", "console_log_path",
                      "cwd", "pause_flag_path", "lock_path", "restart_budget"):
            assert getattr(spec, field) == getattr(canonical, field)
    result = subprocess.run([sys.executable, "-c",
        "import sys; import weather.operations.thin_ensure; "
        "assert not any(x in sys.modules for x in "
        "['numpy','pandas','sklearn','weather.collection.snapshot_tracker','weather.market.market_microstructure'])"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_registrar_actions_are_thin_and_principal_preserved():
    root = Path(__file__).resolve().parents[2]
    for loop in ("snapshot", "clob"):
        text = (root / "scripts" / "ops" / f"register_{loop}_supervisor.ps1").read_text()
        assert f"weather.operations.thin_ensure --ensure --loop {loop}" in text
        assert "-LogonType S4U" in text
        assert "-RunLevel Limited" in text
