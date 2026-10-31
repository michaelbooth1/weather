"""Import a workstation-only research module, or skip the test module on the capture host.

Some research modules refuse to import on the dedicated capture host (they call a
``refuse_production_import`` guard at import time and raise ``ImportError``). A test
module that imports one, directly or through another research module, would turn
that designed refusal into a collection error and fail the host's bounded suite.

``import_or_skip_on_capture_host`` converts exactly that refusal into a module-level
skip. It skips only when both hold:

* the ``ImportError`` text names the dedicated capture host (``CAPTURE_HOST_REFUSAL``),
  which every host guard's capture-host refusal says; and
* this process really is the capture host: ``weather.execution_host``'s current host
  id equals the tracked ``dedicated_capture_execution_host_id`` (read at call time,
  so ``tests/capture_host_emulation.py`` can emulate it on a workstation).

Every other ``ImportError`` is re-raised, including a guard's "host identity not
provable" refusal, so a broken module or an unprovable host still fails loudly.
The guards themselves are unchanged.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest

CAPTURE_HOST_REFUSAL = "dedicated capture host"


def on_capture_host() -> bool:
    """True when the current execution host id is the tracked capture-host id."""

    from weather import execution_host

    try:
        capture_id = execution_host.load_execution_host_assignment()["dedicated_capture_execution_host_id"]
        here = execution_host.current_execution_host_id()
    except Exception:  # noqa: BLE001 - unprovable is not "the capture host"
        return False
    return bool(capture_id) and here == capture_id


def is_capture_host_refusal(exc: BaseException) -> bool:
    """The import failed because a research guard refused this capture host."""

    return isinstance(exc, ImportError) and CAPTURE_HOST_REFUSAL in str(exc) and on_capture_host()


def import_or_skip_on_capture_host(name: str) -> ModuleType:
    """Import ``name``; on the capture host, turn its designed refusal into a module skip."""

    try:
        return importlib.import_module(name)
    except ImportError as exc:
        if is_capture_host_refusal(exc):
            pytest.skip(f"{name} is workstation research and refuses the capture host by design",
                        allow_module_level=True)
        raise
