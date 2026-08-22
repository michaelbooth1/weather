from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from weather.operations import international_live_session_launcher_sealer as launcher_sealer
from weather.operations import international_live_session_runner as runner
from weather.operations.live_path_security import canonical_windows_powershell


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path):
    repo = tmp_path / "production"
    python = repo / "venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"not invoked in preparation tests")
    source = repo / "src/weather/operations/international_live_session_runner.py"
    source.parent.mkdir(parents=True)
    source.write_text("# reviewed runner source\n", encoding="utf-8")
    template = repo / "scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl"
    template.parent.mkdir(parents=True)
    shutil.copyfile(launcher_sealer.TEMPLATE_PATH, template)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    manifest = attempt / "inputs/stage0-session-manifest.json"
    manifest.parent.mkdir(parents=True)
    payload = {
        "schema_version": runner.SESSION_SCHEMA_VERSION,
        "stage": "stage0",
        "production": {"root": str(repo.resolve()), "python": str(python.resolve())},
        "scope": {"attempt_root": str(attempt.resolve())},
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = manifest.with_suffix(manifest.suffix + ".sha256")
    sidecar.write_text(f"{sha(manifest)}  {manifest.name}\n", encoding="ascii")
    return repo, template, attempt, manifest


def prepare(repo, template, manifest):
    return launcher_sealer.prepare_fixed_session_launcher(
        manifest,
        sha(manifest),
        repo_root=repo,
        template_path=template,
        powershell_parser=lambda _source: None,
        attempt_root_validator=lambda path: {"status": "PASS", "path": str(path)},
    )


def test_preparer_writes_no_argument_hash_bound_launcher_and_review_receipt(tmp_path):
    repo, template, attempt, manifest = fixture(tmp_path)

    receipt = prepare(repo, template, manifest)

    launcher = Path(receipt["launcher"]["path"])
    text = launcher.read_text(encoding="utf-8-sig")
    assert receipt["status"] == "PASS"
    assert receipt["no_argument_surface"] is True
    assert "param()" in text
    assert "$MyInvocation.UnboundArguments.Count -ne 0" in text
    assert sha(manifest) in text
    assert "--expected-session-manifest-sha256" in text
    assert "[IO.FileShare]::Read" in text
    assert "source_sha256.psobject.Properties" in text
    assert "Get-ChildItem -LiteralPath $attemptRoot -File -Recurse" in text
    assert "& $python -I -c" in text
    assert "PYTHONPATH" not in text
    assert receipt["production_python"]["sha256"] == sha(
        repo / "venv/Scripts/python.exe"
    )
    assert (attempt / "session/stage0-launcher-review.json.sha256").is_file()


def test_no_argument_launcher_rejects_manifest_and_sidecar_rewrite(tmp_path):
    repo, template, attempt, manifest = fixture(tmp_path)
    receipt = prepare(repo, template, manifest)
    candidate = attempt / "incoming/fresh-stage0-candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    payload = json.loads(manifest.read_text())
    payload["scope"]["attempt_root"] = str((tmp_path / "other").resolve())
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.with_suffix(manifest.suffix + ".sha256").write_text(
        f"{sha(manifest)}  {manifest.name}\n", encoding="ascii"
    )

    result = subprocess.run(
        [
            str(canonical_windows_powershell()),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            receipt["launcher"]["path"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "fixed session locked-file hash changed" in (
        result.stdout + result.stderr
    )
