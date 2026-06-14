"""Compatibility wrapper for weather.market.market_microstructure_features."""

import importlib
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_TARGET = "weather.market.market_microstructure_features"
_module = importlib.import_module(_TARGET)

if __name__ == "__main__" and hasattr(_module, "main"):
    _module.main()
else:
    sys.modules[__name__] = _module
