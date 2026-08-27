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


def test_no_ambient_proxy_configuration_accepts_exact_direct_state():
    result = security.assert_no_ambient_proxy_configuration(
        environment={"PATH": "ignored"},
        user_proxy_reader=lambda: {
            "proxy_enabled": False,
            "automatic_configuration": False,
            "automatic_detection": False,
        },
        winhttp_direct_reader=lambda: True,
    )

    assert result == {
        "status": "PASS",
        "market_registry_override": False,
        "environment_proxy_variables": [],
        "current_user_proxy": "DIRECT",
        "winhttp_proxy": "DIRECT",
    }


@pytest.mark.parametrize(
    "environment_key",
    [
        "HTTP_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "NO_PROXY",
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ],
)
def test_no_ambient_proxy_configuration_rejects_process_redirects(environment_key):
    with pytest.raises(security.LivePathSecurityError, match="ambient proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={environment_key: "configured"},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: True,
        )


def test_no_ambient_market_registry_override_is_case_insensitive():
    with pytest.raises(security.LivePathSecurityError, match="market-registry"):
        security.assert_no_ambient_market_registry_override(
            environment={"weather_market_registry": "C:/untracked/markets.json"}
        )


def test_proxy_gate_also_rejects_market_registry_override():
    with pytest.raises(security.LivePathSecurityError, match="market-registry"):
        security.assert_no_ambient_proxy_configuration(
            environment={"WEATHER_MARKET_REGISTRY": "C:/untracked/markets.json"},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: True,
        )


@pytest.mark.parametrize(
    "user_state",
    [
        {
            "proxy_enabled": True,
            "automatic_configuration": False,
            "automatic_detection": False,
        },
        {
            "proxy_enabled": False,
            "automatic_configuration": True,
            "automatic_detection": False,
        },
        {
            "proxy_enabled": False,
            "automatic_configuration": False,
            "automatic_detection": True,
        },
    ],
)
def test_no_ambient_proxy_configuration_rejects_windows_user_proxy(user_state):
    with pytest.raises(security.LivePathSecurityError, match="Windows proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={},
            user_proxy_reader=lambda: user_state,
            winhttp_direct_reader=lambda: True,
        )


def test_no_ambient_proxy_configuration_rejects_winhttp_proxy():
    with pytest.raises(security.LivePathSecurityError, match="WinHTTP proxy"):
        security.assert_no_ambient_proxy_configuration(
            environment={},
            user_proxy_reader=lambda: {
                "proxy_enabled": False,
                "automatic_configuration": False,
                "automatic_detection": False,
            },
            winhttp_direct_reader=lambda: False,
        )
