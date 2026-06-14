"""Compatibility wrapper for weather.sources.reanalysis_history."""

from __future__ import annotations

import importlib as _importlib
import runpy as _runpy
import sys as _sys
from pathlib import Path as _Path

_SRC_ROOT = _Path(__file__).resolve().parent
if str(_SRC_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_SRC_ROOT))

_TARGET = "weather.sources.reanalysis_history"

if __name__ == "__main__":
    _runpy.run_module(_TARGET, run_name="__main__")
else:
    _module = _importlib.import_module(_TARGET)
    _sys.modules[__name__] = _module
