"""Adapter for the canonical Windows host diagnostic."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import threading
import time

from weather.paths import REPO_ROOT


HOST_STATUS_SCRIPT = REPO_ROOT / "scripts" / "ops" / "status.ps1"


def host_status_snapshot(script_path: str | Path = HOST_STATUS_SCRIPT, *, repo_root=REPO_ROOT) -> dict:
    """Run the canonical host digest; its ATTENTION exit code remains valid."""

    script_path = Path(script_path)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-RepoRoot",
                str(repo_root),
                "-Json",
            ],
            cwd=repo_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=60,
            creationflags=creationflags,
        )
        if result.returncode not in {0, 2}:
            detail = result.stderr.strip() or result.stdout.strip() or "host status failed"
            raise RuntimeError(detail)
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("host status did not return an object")
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
    ) as exc:
        return {
            "available": False,
            "path": str(script_path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    # The script's legacy `ts` omits an offset. Timestamp this actual collection
    # in UTC; a file read must never refresh it from its filesystem mtime.
    collected_at = datetime.now(timezone.utc).isoformat()
    payload["checked_at_utc"] = collected_at
    return {"available": True, "path": str(script_path), "payload": payload,
            "collected_at_utc": collected_at}


class HostStatusCache:
    """One bounded diagnostic at a time, independent of browser refreshes."""

    def __init__(self, collector, *, interval_seconds=300, clock=time.monotonic):
        self._collector = collector
        self._interval = interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._next_collection = 0
        self._snapshot = {"available": False, "loading": True,
                          "error": "Collecting the canonical host diagnostic."}

    def _collect(self):
        try:
            snapshot = self._collector()
        except Exception as exc:  # noqa: BLE001 - surface a diagnostic failure
            snapshot = {"available": False, "error": f"Host diagnostic failed: {type(exc).__name__}"}
        with self._lock:
            self._snapshot = snapshot
            self._next_collection = self._clock() + self._interval
            self._running = False

    def get(self):
        with self._lock:
            if not self._running and self._clock() >= self._next_collection:
                self._running = True
                threading.Thread(target=self._collect, name="weather-host-observer", daemon=True).start()
            return {**self._snapshot, "loading": self._running}
