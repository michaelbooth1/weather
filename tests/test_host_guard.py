"""tests.host_guard skips only a research guard's capture-host refusal, and only on the capture host.

Guards: host bounded-suite collection (incident 2026-10-26, STACK 4a4db1273 exit 2); the helper must
never hide an ordinary ImportError or an unprovable-host refusal.
"""

from __future__ import annotations

import sys

import pytest

from tests import host_guard
from weather import execution_host

CAPTURE_ID = execution_host.load_execution_host_assignment()["dedicated_capture_execution_host_id"]
REFUSAL = "demo is workstation research and refuses to import on the dedicated capture host"


@pytest.fixture
def refusing_module(monkeypatch, tmp_path):
    def install(message):
        (tmp_path / "hostguard_demo_mod.py").write_text(f"raise ImportError({message!r})\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.delitem(sys.modules, "hostguard_demo_mod", raising=False)
        return "hostguard_demo_mod"
    return install


def test_refusal_on_the_capture_host_skips(monkeypatch, refusing_module):
    monkeypatch.setattr(execution_host, "current_execution_host_id", lambda: CAPTURE_ID)
    with pytest.raises(pytest.skip.Exception, match="refuses the capture host by design"):
        host_guard.import_or_skip_on_capture_host(refusing_module(REFUSAL))


def test_refusal_off_the_capture_host_is_reraised(monkeypatch, refusing_module):
    monkeypatch.setattr(execution_host, "current_execution_host_id", lambda: "0" * 64)
    with pytest.raises(ImportError, match="dedicated capture host"):
        host_guard.import_or_skip_on_capture_host(refusing_module(REFUSAL))


def test_other_import_errors_on_the_capture_host_are_reraised(monkeypatch, refusing_module):
    monkeypatch.setattr(execution_host, "current_execution_host_id", lambda: CAPTURE_ID)
    with pytest.raises(ImportError, match="host identity not provable"):
        host_guard.import_or_skip_on_capture_host(
            refusing_module("demo refuses to import: host identity not provable (x)"))
    with pytest.raises(ModuleNotFoundError):
        host_guard.import_or_skip_on_capture_host("hostguard_no_such_module_xyz")


def test_unprovable_host_identity_is_not_the_capture_host(monkeypatch, refusing_module):
    def boom():
        raise RuntimeError("Windows machine identity is unavailable")
    monkeypatch.setattr(execution_host, "current_execution_host_id", boom)
    assert host_guard.on_capture_host() is False
    with pytest.raises(ImportError, match="dedicated capture host"):
        host_guard.import_or_skip_on_capture_host(refusing_module(REFUSAL))


def test_a_successful_import_returns_the_module():
    assert host_guard.import_or_skip_on_capture_host("json") is sys.modules["json"]
