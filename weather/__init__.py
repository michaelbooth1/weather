"""Repo-root import shim for the source-layout weather package."""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "weather"
if _SRC_PACKAGE.is_dir():
    _src_path = str(_SRC_PACKAGE)
    if _src_path not in __path__:
        __path__.insert(0, _src_path)

