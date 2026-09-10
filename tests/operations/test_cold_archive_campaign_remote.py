"""Native metadata-only RPC checks; no archive payloads or network clients."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from weather.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native PowerShell parser and metadata RPC")


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW)


@pytest.mark.parametrize("name", ["cold_archive_campaign_remote.ps1", "cold_archive_campaign_run.ps1"])
def test_native_powershell_parses_without_errors(name):
    ps = str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    path = str(REPO_ROOT / "scripts/ops" / name).replace("'", "''")
    code = ("$tokens=$null;$errors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile('" + path +
            "',[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){$errors|ConvertTo-Json -Depth 5;exit 1}")
    result = run(ps, "-NoProfile", "-NonInteractive", "-Command", code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_rpc_roundtrip_is_bounded_and_refuses_changed_existing_metadata(tmp_path):
    root = tmp_path / "repo"
    folder = root / "scripts/ops"; folder.mkdir(parents=True)
    source = REPO_ROOT / "scripts/ops/cold_archive_campaign_remote.ps1"
    script = folder / source.name; shutil.copyfile(source, script)
    (root / ".gitignore").write_text("scratch/\n")
    assert run("git", "init", "-q", str(root)).returncode == 0
    assert run("git", "-C", str(root), "add", ".").returncode == 0
    committed = run("git", "-C", str(root), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    assert committed.returncode == 0, committed.stderr
    tip = run("git", "-C", str(root), "rev-parse", "HEAD").stdout.strip()
    ps = str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    def rpc(mode, request):
        result = run(ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-File", str(script), "-RepoRoot", str(root), "-ExpectedSourceTip", tip,
                     "-Mode", mode, "-RequestBase64",
                     base64.b64encode(json.dumps(request).encode()).decode())
        return result
    result = rpc("setup", {"campaign_id": "fixture"})
    assert result.returncode == 0, result.stdout + result.stderr
    relative = "scratch/ac-control/fixture/proof.json"
    raw = b'{"metadata":"synthetic"}'
    request = {"path": relative, "base64": base64.b64encode(raw).decode(),
               "sha256": hashlib.sha256(raw).hexdigest()}
    result = rpc("write", request)
    assert result.returncode == 0, result.stdout + result.stderr
    assert rpc("write", request).returncode == 0
    assert (root / relative).read_bytes() == raw
    result = rpc("read", {"paths": [relative]})
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout.split("WEATHER_ARCHIVE_RPC ")[1])
    assert base64.b64decode(value["files"][0]["base64"]) == raw
    changed = b"changed"
    assert rpc("write", {**request, "base64": base64.b64encode(changed).decode(),
                         "sha256": hashlib.sha256(changed).hexdigest()}).returncode != 0
    assert (root / relative).read_bytes() == raw
    assert rpc("read", {"paths": ["data/private.json"]}).returncode != 0
