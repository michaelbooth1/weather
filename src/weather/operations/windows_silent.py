"""Windows defaults for background workers that must never open consoles."""

from __future__ import annotations

import os


def _safe_loky_cpu_cap() -> int:
    count = int(os.cpu_count() or 1)
    if count <= 1:
        return 1
    return max(1, count - 1)


def _cap_loky_cpu_count() -> None:
    count = int(os.cpu_count() or 1)
    desired = _safe_loky_cpu_cap()
    raw = os.environ.get("LOKY_MAX_CPU_COUNT")
    try:
        current = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        current = None
    if current is None or current >= count:
        os.environ["LOKY_MAX_CPU_COUNT"] = str(desired)


def _patch_platform_version_probe() -> None:
    try:
        import platform

        def _silent_syscmd_ver(system="", release="", version="", supported_platforms=None):
            return system, release, version

        platform._syscmd_ver = _silent_syscmd_ver
    except Exception:
        return


def _patch_subprocess_popen() -> None:
    try:
        import subprocess

        if getattr(subprocess.Popen, "_weather_silent_windows_children", False):
            return

        original_popen = subprocess.Popen

        class SilentWindowsPopen(original_popen):
            _weather_silent_windows_children = True

            def __init__(self, *popenargs, **kwargs):
                try:
                    flags = int(kwargs.get("creationflags") or 0)
                    kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
                except Exception:
                    pass
                super().__init__(*popenargs, **kwargs)

        subprocess.Popen = SilentWindowsPopen
    except Exception:
        return


def _patch_loky_physical_core_probe() -> None:
    try:
        from joblib.externals.loky.backend import context as loky_context
    except Exception:
        return

    safe_count = _safe_loky_cpu_cap()

    def _silent_count_physical_cores_win32():
        return safe_count

    try:
        loky_context._count_physical_cores_win32 = _silent_count_physical_cores_win32
        loky_context.physical_cores_cache = safe_count
    except Exception:
        return


def apply_windows_silent_subprocess_defaults() -> None:
    if os.name != "nt" or os.environ.get("WEATHER_ALLOW_CONSOLE_CHILDREN") == "1":
        return
    _cap_loky_cpu_count()
    _patch_platform_version_probe()
    _patch_subprocess_popen()
    _patch_loky_physical_core_probe()
