"""Emit fail-closed parameters for production task registration scripts."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from weather.artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_IMMUTABLE_RELEASE_ROOT,
    ReleaseArtifactVerificationError,
    resolve_verified_active_release,
)
from weather.paths import REPO_ROOT
from weather.release_artifacts import strict_json_loads
from weather.release_contract import SERVING_ARTIFACT_KINDS


DAILY_REGISTER_SCRIPT = Path("scripts") / "ops" / "register_daily_refresh.ps1"
NIGHTLY_REGISTER_SCRIPT = Path("scripts") / "ops" / "register_nightly_retrain.ps1"
ROUTE_ROLE = "market_route_table"


class RegistrationParameterError(RuntimeError):
    """A complete, verified registration parameter set cannot be emitted."""


def _default_parity_paths(
    market_ids: Sequence[str],
    *,
    repo_root: Path,
) -> tuple[list[Path], list[Path]]:
    # Task 1 owns these paths. Keep the import lazy so this read-only command
    # does not load replay/serving code until the release route is verified.
    from weather.reporting.scorecards.captured_input_parity_evidence import (
        default_output_paths,
    )

    output_root = repo_root / "data" / "backtest" / "captured_input_parity"
    pairs = [
        default_output_paths(market_id, output_root=output_root)
        for market_id in market_ids
    ]
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def _path_values(value: str | Path | Sequence[str | Path] | None) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    return [Path(item) for item in value]


def _routed_market_ids(route: Mapping[str, Any]) -> list[str]:
    markets = route.get("markets")
    if not isinstance(markets, Mapping) or not markets:
        raise RegistrationParameterError(
            "verified served route declares no markets; repair the active release"
        )
    market_ids: list[str] = []
    for raw_market_id, row in markets.items():
        market_id = str(raw_market_id).strip()
        if not market_id or not isinstance(row, Mapping):
            raise RegistrationParameterError(
                "verified served route contains an invalid market entry"
            )
        decision = str(row.get("decision") or "").strip()
        if decision not in {"promote", "shadow", "blocked"}:
            raise RegistrationParameterError(
                f"verified served route for {market_id!r} has invalid decision "
                f"{decision!r}; expected promote, shadow, or blocked"
            )
        # Blocked markets are deliberately not served through this release and
        # therefore cannot have captured-input serving/replay evidence for it.
        if decision in {"promote", "shadow"}:
            market_ids.append(market_id)
    market_ids.sort()
    if not market_ids:
        raise RegistrationParameterError(
            "verified served route has no promote or shadow markets for "
            "captured-input parity registration"
        )
    return market_ids


def _required_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.exists() or not candidate.is_file():
        raise RegistrationParameterError(
            f"{label} is missing or is not a regular file: {candidate}"
        )
    return candidate.resolve()


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RegistrationParameterError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistrationParameterError(f"{label} must be a JSON object: {path}")
    return payload


def _serving_bindings(
    manifest: Mapping[str, Any],
    *,
    release_dir: Path,
) -> tuple[dict[str, Path], Path, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    inventory = artifacts.get("inventory") if isinstance(artifacts, Mapping) else None
    if not isinstance(inventory, list):
        raise RegistrationParameterError(
            "verified release manifest has no artifact inventory; repair the release"
        )

    bindings: dict[str, Path] = {}
    for row in inventory:
        if not isinstance(row, Mapping):
            continue
        if not row.get("declared") or row.get("kind") not in SERVING_ARTIFACT_KINDS:
            continue
        role = str(row.get("role") or "").strip()
        relative_path = str(row.get("path") or "").strip()
        if not role or not relative_path:
            raise RegistrationParameterError(
                "verified release has an incomplete declared serving artifact row"
            )
        raw_path = release_dir / relative_path
        path = _required_file(raw_path, label=f"served artifact {role!r}")
        try:
            path.relative_to(release_dir)
        except ValueError as exc:
            raise RegistrationParameterError(
                f"served artifact {role!r} escapes the verified release: {path}"
            ) from exc
        bindings[role] = path

    if not bindings:
        raise RegistrationParameterError(
            "verified release declares no serving artifact roles; rebuild a serving-capable release"
        )
    route_path = bindings.get(ROUTE_ROLE)
    if route_path is None:
        raise RegistrationParameterError(
            "verified release does not declare the market_route_table serving role; "
            "rebuild a semantic serving release before registration"
        )
    route_payload = _read_json_object(route_path, label="served market route")
    return bindings, route_path, route_payload


def _identity_tuple(identity: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        identity.get(field)
        for field in ("release_id", "manifest_sha256", "pointer_sha256", "sequence")
    )


def _powershell_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell_array(values: Sequence[str | Path]) -> str:
    return "@(" + ", ".join(_powershell_literal(value) for value in values) + ")"


def render_powershell_invocation(
    script_path: str | Path,
    parameters: Mapping[str, Any],
) -> str:
    """Render one reviewed parameter payload as a PowerShell 5.1 command."""

    bindings = list(parameters["ProductionReadinessServedArtifact"])
    lines = [
        f"& {_powershell_literal(script_path)} `",
        "    -CapturedInputParityServed "
        f"{_powershell_array(parameters['CapturedInputParityServed'])} `",
        "    -CapturedInputParityReplay "
        f"{_powershell_array(parameters['CapturedInputParityReplay'])} `",
        "    -ProductionReadinessServedArtifact @(",
    ]
    for index, binding in enumerate(bindings):
        comma = "," if index < len(bindings) - 1 else ""
        lines.append(f"        {_powershell_literal(binding)}{comma}")
    lines.extend(
        [
            "    ) `",
            "    -ProductionReadinessServedRoute "
            f"{_powershell_literal(parameters['ProductionReadinessServedRoute'])}",
        ]
    )
    return "\n".join(lines)


def build_registration_parameters(
    *,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_IMMUTABLE_RELEASE_ROOT,
    repo_root: str | Path = REPO_ROOT,
    captured_input_parity_served: str | Path | Sequence[str | Path] | None = None,
    captured_input_parity_replay: str | Path | Sequence[str | Path] | None = None,
    current_runtime_versions: Mapping[str, Any] | None = None,
    current_runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build exact registration parameters after release and binding verification."""

    repo_root = Path(repo_root).resolve()
    releases_root = Path(releases_root).resolve()
    pointer_path = Path(pointer_path)
    try:
        inspected = resolve_verified_active_release(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=True,
            current_runtime_versions=current_runtime_versions,
            current_runtime_identity=current_runtime_identity,
            require_served_bindings=False,
        )
    except (ReleaseArtifactVerificationError, OSError, ValueError) as exc:
        raise RegistrationParameterError(
            "active release verification failed: "
            f"{exc}. Repair or publish the reviewed active release pointer, then rerun."
        ) from exc
    if inspected.get("status") != "PASS" or not inspected.get("runtime_checked"):
        raise RegistrationParameterError(
            "active release resolver did not return a runtime-verified PASS"
        )

    manifest_path = _required_file(
        str(inspected.get("manifest_path") or ""),
        label="verified release manifest",
    )
    manifest = _read_json_object(manifest_path, label="verified release manifest")
    release_dir = Path(str(inspected.get("release_dir") or "")).resolve()
    bindings, route_path, route_payload = _serving_bindings(
        manifest,
        release_dir=release_dir,
    )
    routed_market_ids = _routed_market_ids(route_payload)

    try:
        verified = resolve_verified_active_release(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=True,
            current_runtime_versions=current_runtime_versions,
            current_runtime_identity=current_runtime_identity,
            served_artifact_paths=bindings,
            served_route=route_payload,
            require_served_bindings=True,
        )
    except (ReleaseArtifactVerificationError, OSError, ValueError) as exc:
        raise RegistrationParameterError(
            "derived serving bundle verification failed: "
            f"{exc}. Repair the active release artifacts or pointer, then rerun."
        ) from exc
    if _identity_tuple(verified) != _identity_tuple(inspected):
        raise RegistrationParameterError(
            "active release pointer changed while parameters were being derived; rerun"
        )
    expected_roles = sorted(bindings)
    if (
        verified.get("status") != "PASS"
        or not verified.get("runtime_checked")
        or not verified.get("served_bindings_verified")
        or verified.get("served_artifact_roles") != expected_roles
    ):
        raise RegistrationParameterError(
            "derived serving bundle did not return an exact verified role set"
        )

    if (captured_input_parity_served is None) != (
        captured_input_parity_replay is None
    ):
        raise RegistrationParameterError(
            "served and replay parity overrides must be supplied together"
        )
    if captured_input_parity_served is None:
        served_values, replay_values = _default_parity_paths(
            routed_market_ids,
            repo_root=repo_root,
        )
    else:
        served_values = _path_values(captured_input_parity_served)
        replay_values = _path_values(captured_input_parity_replay)
    if len(served_values) != len(replay_values) or len(served_values) != len(
        routed_market_ids
    ):
        raise RegistrationParameterError(
            "captured-input parity paths must contain exactly one served/replay pair "
            f"for every routed market ({', '.join(routed_market_ids)})"
        )
    parity_served = [
        _required_file(
            path,
            label=(
                f"captured-input served parity evidence for {market_id!r}; run "
                "python -m weather.reporting.scorecards.captured_input_parity_evidence first"
            ),
        )
        for market_id, path in zip(routed_market_ids, served_values)
    ]
    parity_replay = [
        _required_file(
            path,
            label=(
                f"captured-input replay parity evidence for {market_id!r}; run "
                "python -m weather.reporting.scorecards.captured_input_parity_evidence first"
            ),
        )
        for market_id, path in zip(routed_market_ids, replay_values)
    ]

    parameters = {
        "CapturedInputParityServed": [str(path) for path in parity_served],
        "CapturedInputParityReplay": [str(path) for path in parity_replay],
        "ProductionReadinessServedArtifact": [
            f"{role}={bindings[role]}" for role in expected_roles
        ],
        "ProductionReadinessServedRoute": str(route_path),
    }
    registrations: dict[str, dict[str, Any]] = {}
    for name, relative_script in (
        ("daily_refresh", DAILY_REGISTER_SCRIPT),
        ("nightly_retrain", NIGHTLY_REGISTER_SCRIPT),
    ):
        script_path = _required_file(
            repo_root / relative_script,
            label=f"{name.replace('_', ' ')} registration script",
        )
        script_parameters = {
            key: list(value) if isinstance(value, list) else value
            for key, value in parameters.items()
        }
        registrations[name] = {
            "script": str(script_path),
            "parameters": script_parameters,
            "powershell_invocation": render_powershell_invocation(
                script_path,
                script_parameters,
            ),
        }

    return {
        "status": "PASS",
        "active_release": {
            "release_id": verified["release_id"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": verified["manifest_sha256"],
            "pointer_path": str(pointer_path.resolve()),
            "pointer_sha256": verified["pointer_sha256"],
            "sequence": verified["sequence"],
            "served_binding_sha256": verified["served_binding_sha256"],
            "served_artifact_roles": expected_roles,
            "routed_market_ids": routed_market_ids,
        },
        "registrations": registrations,
    }


def render_ready_powershell(payload: Mapping[str, Any]) -> str:
    registrations = payload.get("registrations") or {}
    return "\n\n".join(
        [
            "# Daily refresh registration",
            str((registrations.get("daily_refresh") or {}).get("powershell_invocation") or ""),
            "# Nightly retrain registration",
            str((registrations.get("nightly_retrain") or {}).get("powershell_invocation") or ""),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-release-pointer", default=str(DEFAULT_ACTIVE_RELEASE_POINTER))
    parser.add_argument("--releases-root", default=str(DEFAULT_IMMUTABLE_RELEASE_ROOT))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--captured-input-parity-served", action="append")
    parser.add_argument("--captured-input-parity-replay", action="append")
    args = parser.parse_args(argv)
    try:
        payload = build_registration_parameters(
            pointer_path=args.active_release_pointer,
            releases_root=args.releases_root,
            repo_root=args.repo_root,
            captured_input_parity_served=args.captured_input_parity_served,
            captured_input_parity_replay=args.captured_input_parity_replay,
        )
    except RegistrationParameterError as exc:
        print(f"registration parameters BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("\n# Ready-to-run PowerShell\n")
    print(render_ready_powershell(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
