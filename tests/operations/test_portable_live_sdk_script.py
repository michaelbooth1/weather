from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ops/portable_live_sdk.ps1"


def test_portable_live_sdk_script_is_thin_offline_current_user_entrypoint():
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "weather.market.live_sdk_portability" in text
    assert "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13" in text
    assert "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_EXPORT" in text
    assert "AUTHORIZE_NON_SECRET_INTERNATIONAL_LIVE_SDK_IMPORT" in text
    assert "-i" in lowered
    assert "$arguments.add(\"-b\")" in lowered
    assert "sys.dont_write_bytecode = true" in lowered
    assert "import is current-user-only" in lowered
    assert "drivetype]::fixed" in lowered
    assert "drivetype]::removable" in lowered
    assert "get-command python" not in lowered
    assert "invoke-webrequest" not in lowered
    assert "invoke-restmethod" not in lowered
    assert "scheduledtasks" not in lowered
    assert "register-scheduledtask" not in lowered
    assert "credential" not in lowered
    assert "clob.polymarket.com" not in lowered


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell.exe") is None,
    reason="requires Windows PowerShell native Python argument transport",
)
def test_sdk_audit_bootstrap_reaches_isolated_module_with_exact_arguments(tmp_path):
    repo = tmp_path / "repository with spaces"
    scripts = repo / "scripts" / "ops"
    scripts.mkdir(parents=True)
    script = scripts / SCRIPT.name
    shutil.copyfile(SCRIPT, script)
    package = repo / "src" / "weather" / "market"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "live_sdk_portability.py").write_text(
        "import json, pathlib, sys\n"
        "assert sys.flags.isolated == 1\n"
        "assert sys.flags.no_site == 1\n"
        "assert sys.dont_write_bytecode\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--receipt-out') + 1])\n"
        "out.write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    receipt = tmp_path / "audit receipt.json"
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Command", "Audit", "-ReceiptOut", str(receipt),
            "-PythonPath", sys.executable,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(receipt.read_text(encoding="utf-8")) == [
        "audit", "--manifest",
        str(scripts / "international_live_templates" / "sdk_overlay_manifest.json"),
        "--expected-manifest-sha256",
        "2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13",
        "--receipt-out", str(receipt),
    ]
