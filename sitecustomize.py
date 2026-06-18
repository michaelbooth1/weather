"""Local Windows safety defaults for background Python jobs.

The weather workers run from Task Scheduler under pythonw.exe. Some libraries
probe platform or CPU details by spawning console programs such as cmd.exe or
powershell.exe; with Windows Terminal as the default console host those probes
can steal focus. This file is imported automatically by Python when the repo
root is on sys.path, which is true for the scheduled workers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent
_SRC_ROOT = _REPO_ROOT / "src"
if (_SRC_ROOT / "weather").is_dir():
    _src_text = str(_SRC_ROOT)
    if _src_text not in sys.path:
        sys.path.insert(0, _src_text)

if os.name == "nt" and os.environ.get("WEATHER_ALLOW_CONSOLE_CHILDREN") != "1":
    _cpu_count = int(os.cpu_count() or 1)
    _safe_loky_count = max(1, _cpu_count - 1) if _cpu_count > 1 else 1
    try:
        _current_loky_count = int(os.environ.get("LOKY_MAX_CPU_COUNT", "0") or "0")
    except ValueError:
        _current_loky_count = 0
    if _current_loky_count <= 0 or _current_loky_count >= _cpu_count:
        os.environ["LOKY_MAX_CPU_COUNT"] = str(_safe_loky_count)

    try:
        import platform

        def _silent_syscmd_ver(system="", release="", version="", supported_platforms=None):
            return system, release, version

        platform._syscmd_ver = _silent_syscmd_ver
    except Exception:
        pass

    try:
        import subprocess

        if not getattr(subprocess.Popen, "_weather_silent_windows_children", False):
            _original_popen = subprocess.Popen

            class _SilentWindowsPopen(_original_popen):
                _weather_silent_windows_children = True

                def __init__(self, *popenargs, **kwargs):
                    try:
                        flags = int(kwargs.get("creationflags") or 0)
                        kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
                    except Exception:
                        pass
                    super().__init__(*popenargs, **kwargs)

            subprocess.Popen = _SilentWindowsPopen
    except Exception:
        pass
