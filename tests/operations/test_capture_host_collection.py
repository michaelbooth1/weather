"""Every test module collects cleanly on the dedicated capture host.

Guards: host bounded-suite collection under research import guards (incident 2026-10-26: the
capture host's bounded suite on STACK 4a4db1273 exited 2 with collection errors because test
modules imported workstation-only research modules whose import guards refuse the capture host;
docs/development.md "Capture-host collection emulation").

The whole ``tests/`` tree is collected in a child pytest with ``tests.capture_host_emulation``
loaded, which makes ``weather.execution_host.current_execution_host_id`` return the tracked
capture-host id. A test module that imports a refusing module must skip through
``tests.host_guard.import_or_skip_on_capture_host``; any collection error fails this ratchet.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.capture_host_emulation import EMULATION_BANNER

pytestmark = pytest.mark.ratchet

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.spawns
def test_every_test_module_collects_under_capture_host_emulation(tmp_path):
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests.capture_host_emulation", "-p", "no:cacheprovider",
         "--collect-only", "-q", "--basetemp", str(tmp_path / "bt"), "tests"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1200,
    )
    output = proc.stdout + proc.stderr
    errors = [line for line in output.splitlines() if line.startswith("ERROR ")]
    assert proc.returncode == 0 and not errors, (
        f"collection under capture-host emulation failed (exit {proc.returncode}); "
        "import research modules through tests.host_guard.import_or_skip_on_capture_host:\n"
        + "\n".join(errors or output.splitlines()[-40:])
    )
    assert EMULATION_BANNER in proc.stdout
