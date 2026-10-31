"""Pytest plugin: emulate the dedicated capture host on a workstation.

Load it with ``-p tests.capture_host_emulation``. Before any test module is
collected it replaces ``weather.execution_host.current_execution_host_id`` with a
function returning the tracked ``dedicated_capture_execution_host_id`` from
``config/international_live_execution_host.json``. Research modules whose import
guards compare the two then refuse exactly as they do on the capture host, so

    python -m pytest -p tests.capture_host_emulation --collect-only -q tests

reproduces the host's collection on a workstation (the WS pregate emulation in
docs/development.md). Guards that also require ``os.name == "nt"`` refuse only
when this runs on Windows; on Linux CI only the guards keyed on the host id alone
fire. The plugin is fail-closed: if the tracked id cannot be read, configuration
fails instead of silently collecting as a workstation.

Nothing outside the pytest process changes; never load it in production code.
"""

from __future__ import annotations

import pytest

EMULATION_BANNER = "capture-host emulation: active"


def _capture_host_id() -> str:
    from weather import execution_host

    capture_id = str(execution_host.load_execution_host_assignment()["dedicated_capture_execution_host_id"])
    if not capture_id:
        raise pytest.UsageError("capture-host emulation: tracked capture host id is empty")
    return capture_id


def pytest_configure(config: pytest.Config) -> None:
    from weather import execution_host

    capture_id = _capture_host_id()
    execution_host.current_execution_host_id = lambda: capture_id


def pytest_report_collectionfinish(config: pytest.Config, start_path, items) -> str:
    from weather import execution_host

    capture_id = _capture_host_id()
    if execution_host.current_execution_host_id() != capture_id:
        raise pytest.UsageError("capture-host emulation: host id patch was not in effect")
    return EMULATION_BANNER
