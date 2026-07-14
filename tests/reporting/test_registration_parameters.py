from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.operations.release_manifest import create_release
from weather.release_artifacts import pointer_content_sha256
from weather.reporting.serving_gates.registration_parameters import (
    RegistrationParameterError,
    build_registration_parameters,
    render_ready_powershell,
)
from weather.schema_registry import schema_version


NOW = datetime(2026, 7, 14, 1, 30, tzinfo=timezone.utc)
COMMIT = "1" * 40


def _runtime_versions() -> dict:
    return {
        "python": "3.11.9",
        "implementation": "CPython",
        "platform": "test-platform",
        "direct_dependencies": {
            "scikit-learn": {
                "version": "1.8.0",
                "declared": "scikit-learn==1.8.0",
            }
        },
    }


def _runtime_identity() -> dict:
    return {
        "schema_version": "runtime_identity_v0.1",
        "source_fingerprint": "synthetic-source-fingerprint",
        "git_commit": COMMIT[:12],
    }


def _code_identity() -> dict:
    return {
        "git_commit": COMMIT,
        "git_branch": "synthetic-release",
        "git_dirty": False,
        "dirty_fingerprint": None,
    }


def _write_active_pointer(path: Path, *, release_id: str, manifest_sha256: str) -> Path:
    payload = {
        "schema_version": schema_version("active_release_pointer"),
        "sequence": 1,
        "action": "PROMOTE",
        "changed_at_utc": NOW.isoformat(),
        "active_release_id": release_id,
        "active_manifest_sha256": manifest_sha256,
        "previous_release_id": None,
        "previous_manifest_sha256": None,
    }
    payload["pointer_sha256"] = pointer_content_sha256(payload)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _synthetic_release(
    tmp_path: Path,
    *,
    include_route_role: bool = True,
    market_ids: tuple[str, ...] = ("toronto",),
    blocked_market_ids: tuple[str, ...] = (),
) -> dict:
    candidate = tmp_path / "candidate"
    (candidate / "models").mkdir(parents=True)
    (candidate / "config").mkdir()
    (candidate / "contract").mkdir()
    route = {
        "schema_version": "synthetic_route_v1",
        "default_variant": "pooled-v1",
        "markets": {
            **{
                market_id: {
                    "decision": "promote",
                    "artifact_role": "pooled_band_model",
                    "candidate_variant_id": "pooled-v1",
                    "variant_id": "pooled-v1",
                }
                for market_id in market_ids
            },
            **{
                market_id: {
                    "decision": "blocked",
                    "artifact_role": None,
                    "candidate_variant_id": None,
                    "variant_id": None,
                }
                for market_id in blocked_market_ids
            },
        },
    }
    (candidate / "models" / "pooled.bin").write_bytes(b"synthetic model")
    (candidate / "config" / "markets.json").write_text(
        json.dumps({"markets": [*market_ids, *blocked_market_ids]}) + "\n",
        encoding="utf-8",
    )
    (candidate / "contract" / "market_route_table.json").write_text(
        json.dumps(route, sort_keys=True),
        encoding="utf-8",
    )
    route_role = "market_route_table" if include_route_role else "not_the_served_route"
    result = create_release(
        release_id="synthetic-r1",
        candidate_dir=candidate,
        declarations=[
            {
                "path": "models/pooled.bin",
                "kind": "model",
                "role": "pooled_band_model",
            },
            {
                "path": "config/markets.json",
                "kind": "config",
                "role": "markets_config",
            },
            {
                "path": "contract/market_route_table.json",
                "kind": "route",
                "role": route_role,
            },
        ],
        route=route,
        expected_live_runtimes=["test-worker"],
        releases_root=tmp_path / "releases",
        repo_root=tmp_path,
        code_identity=_code_identity(),
        runtime_versions=_runtime_versions(),
        runtime_identity=_runtime_identity(),
        created_at_utc=NOW.isoformat(),
    )
    pointer = _write_active_pointer(
        tmp_path / "releases" / "current_release.json",
        release_id=result["release_id"],
        manifest_sha256=result["manifest_sha256"],
    )
    scripts = tmp_path / "scripts" / "ops"
    scripts.mkdir(parents=True)
    (scripts / "register_daily_refresh.ps1").write_text("param()\n", encoding="utf-8")
    (scripts / "register_nightly_retrain.ps1").write_text("param()\n", encoding="utf-8")
    parity_root = tmp_path / "data" / "backtest" / "captured_input_parity"
    served_paths = []
    replay_paths = []
    for market_id in market_ids:
        market_root = parity_root / market_id
        market_root.mkdir(parents=True)
        served = market_root / "served_rows.json"
        replay = market_root / "replay_rows.json"
        served.write_text('{"rows":[]}\n', encoding="utf-8")
        replay.write_text('{"rows":[]}\n', encoding="utf-8")
        served_paths.append(served)
        replay_paths.append(replay)
    return {
        "pointer": pointer,
        "releases_root": tmp_path / "releases",
        "release_dir": Path(result["release_dir"]),
        "manifest_sha256": result["manifest_sha256"],
        "served": served_paths[0],
        "replay": replay_paths[0],
        "served_paths": served_paths,
        "replay_paths": replay_paths,
    }


def _build(tmp_path: Path, fixture: dict) -> dict:
    return build_registration_parameters(
        pointer_path=fixture["pointer"],
        releases_root=fixture["releases_root"],
        repo_root=tmp_path,
        current_runtime_versions=_runtime_versions(),
        current_runtime_identity=_runtime_identity(),
    )


def test_verified_release_emits_exact_bindings_paths_and_powershell(tmp_path: Path):
    fixture = _synthetic_release(tmp_path)

    payload = _build(tmp_path, fixture)

    assert payload["status"] == "PASS"
    assert payload["active_release"]["release_id"] == "synthetic-r1"
    assert payload["active_release"]["manifest_sha256"] == fixture["manifest_sha256"]
    assert payload["active_release"]["routed_market_ids"] == ["toronto"]
    assert payload["active_release"]["served_artifact_roles"] == [
        "market_route_table",
        "markets_config",
        "pooled_band_model",
    ]
    daily = payload["registrations"]["daily_refresh"]
    nightly = payload["registrations"]["nightly_retrain"]
    assert daily["parameters"] == nightly["parameters"]
    assert daily["parameters"]["CapturedInputParityServed"] == [
        str(fixture["served"].resolve())
    ]
    assert daily["parameters"]["CapturedInputParityReplay"] == [
        str(fixture["replay"].resolve())
    ]
    assert daily["parameters"]["ProductionReadinessServedArtifact"] == [
        f"market_route_table={fixture['release_dir'] / 'contract' / 'market_route_table.json'}",
        f"markets_config={fixture['release_dir'] / 'config' / 'markets.json'}",
        f"pooled_band_model={fixture['release_dir'] / 'models' / 'pooled.bin'}",
    ]
    assert daily["parameters"]["ProductionReadinessServedRoute"] == str(
        fixture["release_dir"] / "contract" / "market_route_table.json"
    )
    expected_daily = "\n".join(
        [
            f"& '{tmp_path / 'scripts' / 'ops' / 'register_daily_refresh.ps1'}' `",
            f"    -CapturedInputParityServed @('{fixture['served'].resolve()}') `",
            f"    -CapturedInputParityReplay @('{fixture['replay'].resolve()}') `",
            "    -ProductionReadinessServedArtifact @(",
            f"        'market_route_table={fixture['release_dir'] / 'contract' / 'market_route_table.json'}',",
            f"        'markets_config={fixture['release_dir'] / 'config' / 'markets.json'}',",
            f"        'pooled_band_model={fixture['release_dir'] / 'models' / 'pooled.bin'}'",
            "    ) `",
            f"    -ProductionReadinessServedRoute '{fixture['release_dir'] / 'contract' / 'market_route_table.json'}'",
        ]
    )
    assert daily["powershell_invocation"] == expected_daily
    expected_nightly = expected_daily.replace(
        "register_daily_refresh.ps1",
        "register_nightly_retrain.ps1",
    )
    assert nightly["powershell_invocation"] == expected_nightly
    powershell = render_ready_powershell(payload)
    assert powershell == "\n\n".join(
        [
            "# Daily refresh registration",
            expected_daily,
            "# Nightly retrain registration",
            expected_nightly,
        ]
    )


def test_missing_or_corrupt_active_release_fails_closed(tmp_path: Path):
    missing_pointer = tmp_path / "releases" / "current_release.json"
    with pytest.raises(RegistrationParameterError, match="active release pointer is missing"):
        build_registration_parameters(
            pointer_path=missing_pointer,
            releases_root=tmp_path / "releases",
            repo_root=tmp_path,
            captured_input_parity_served=tmp_path / "served.json",
            captured_input_parity_replay=tmp_path / "replay.json",
            current_runtime_versions=_runtime_versions(),
            current_runtime_identity=_runtime_identity(),
        )

    fixture = _synthetic_release(tmp_path / "corrupt")
    (fixture["release_dir"] / "models" / "pooled.bin").write_bytes(b"tampered")
    with pytest.raises(RegistrationParameterError, match="artifact .*mismatch"):
        _build(tmp_path / "corrupt", fixture)


def test_default_parity_paths_cover_every_routed_market(tmp_path: Path):
    fixture = _synthetic_release(
        tmp_path,
        market_ids=("toronto", "nyc"),
        blocked_market_ids=("chicago",),
    )

    payload = _build(tmp_path, fixture)
    parameters = payload["registrations"]["daily_refresh"]["parameters"]

    assert payload["active_release"]["routed_market_ids"] == ["nyc", "toronto"]
    assert parameters["CapturedInputParityServed"] == [
        str(path.resolve())
        for path in (fixture["served_paths"][1], fixture["served_paths"][0])
    ]
    assert parameters["CapturedInputParityReplay"] == [
        str(path.resolve())
        for path in (fixture["replay_paths"][1], fixture["replay_paths"][0])
    ]
    assert not (tmp_path / "data" / "backtest" / "captured_input_parity" / "chicago").exists()


def test_verified_release_without_served_route_role_fails_closed(tmp_path: Path):
    fixture = _synthetic_release(tmp_path, include_route_role=False)

    with pytest.raises(RegistrationParameterError, match="market_route_table serving role"):
        _build(tmp_path, fixture)
