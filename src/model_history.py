"""Compatibility wrapper for weather.reporting.model_history."""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

_SRC_ROOT = _Path(__file__).resolve().parent
if str(_SRC_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_SRC_ROOT))

_module = _importlib.import_module("weather.reporting.model_history")
_sys.modules[__name__] = _module
