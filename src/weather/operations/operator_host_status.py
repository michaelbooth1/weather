"""Read-only adapter for the canonical Windows host status digest."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from weather.paths import REPO_ROOT


HOST_STATUS_SCRIPT = REPO_ROOT / "scripts" / "ops" / "status.ps1"


def host_status_snapshot(script_path: str | Path = HOST_STATUS_SCRIPT) -> dict:
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
                "-Json",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=20,
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
    return {"available": True, "path": str(script_path), "payload": payload}
