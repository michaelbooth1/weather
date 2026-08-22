from __future__ import annotations

import json
import subprocess

import pytest

from weather.operations import live_path_security as security


def test_canonical_powershell_ignores_path_shadow(monkeypatch, tmp_path):
    shadow = tmp_path / "powershell.exe"
    shadow.write_text("shadow", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))

    result = security.canonical_windows_powershell()

    assert result != shadow
    assert "System32" in str(result)


def test_private_acl_validator_accepts_only_current_user_owned_root(monkeypatch, tmp_path):
    monkeypatch.setattr(security, "is_reparse", lambda _path: False)
    monkeypatch.setattr(
        security.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, json.dumps({"current_user_write": True, "broad_write_count": 0}), ""
        ),
    )

    result = security.validate_private_attempt_root(
        tmp_path, powershell_path=security.canonical_windows_powershell()
    )

    assert result["status"] == "PASS"


def test_private_acl_validator_rejects_broad_write_or_reparse(monkeypatch, tmp_path):
    monkeypatch.setattr(security, "is_reparse", lambda _path: False)
    monkeypatch.setattr(
        security.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, json.dumps({"current_user_write": True, "broad_write_count": 1}), ""
        ),
    )
    with pytest.raises(security.LivePathSecurityError, match="broadly writable"):
        security.validate_private_attempt_root(
            tmp_path, powershell_path=security.canonical_windows_powershell()
        )

    monkeypatch.setattr(security, "is_reparse", lambda _path: True)
    with pytest.raises(security.LivePathSecurityError, match="redirected"):
        security.validate_private_attempt_root(
            tmp_path, powershell_path=security.canonical_windows_powershell()
        )


def test_contained_file_rejects_redirect_before_resolve(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    artifact = target / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    redirected = tmp_path / "redirected"
    try:
        redirected.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(security.LivePathSecurityError, match="redirected"):
        security.validate_contained_regular_file(
            tmp_path, redirected / artifact.name
        )
