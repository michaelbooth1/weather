"""Build one immutable research-only all-shadow release without a pointer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.io import write_json_atomic
from weather.market.market_registry import REGISTRY
from weather.operations.release_candidate_contract import (
    SEMANTIC_PATHS,
    freeze_candidate_semantic_contract,
)
from weather.operations.release_manifest import (
    capture_code_identity,
    create_release,
    verify_release,
)
from weather.paths import REPO_ROOT, data_path
from weather.release_artifacts import (
    canonical_payload_sha256,
    sha256_file,
    strict_json_loads,
)
from weather.release_contract import (
    BASE_MODEL_MARKET_COMPONENT_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("all_shadow_release_bootstrap_receipt")
ARTIFACT_TYPE = "all_shadow_release_bootstrap_receipt"
EXPECTED_RUNTIME_MARKET_COUNT = 12
EXPECTED_FAHRENHEIT_MARKET_COUNT = 11
DEFAULT_EXPECTED_RUNTIMES = (
    "snapshot_loop",
    "observation_trigger",
    "market_making",
    "taker_bot",
)
SOURCE_ARTIFACTS = {
    "pooled_band_model": (
        "artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl",
        "model/feature_model_hgb_f_pooled_v0_3.pkl",
    ),
    "family_secondary_calibration": (
        "artifacts/manifests/f_family_secondary_artifacts.json",
        "calibration/f_family_secondary_artifacts.json",
    ),
    "artifact_registry": (
        "artifacts/manifests/model_artifact_registry.json",
        "config/model_artifact_registry.json",
    ),
}


class AllShadowBootstrapError(ValueError):
    """The bounded all-shadow bootstrap cannot be built safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_run_root(run_root: str | Path, *, repo_root: Path) -> Path:
    value = Path(run_root)
    if value.exists() and value.is_symlink():
        raise AllShadowBootstrapError(f"run root must not be a symlink: {value}")
    root = value.resolve()
    forbidden = (
        data_path().resolve(),
        (repo_root / "artifacts" / "releases").resolve(),
        (repo_root / "artifacts" / "candidates").resolve(),
    )
    if root == repo_root or any(
        root == path or _contains(path, root) for path in forbidden
    ):
        raise AllShadowBootstrapError(
            "run root must be a dedicated directory outside data and repository-owned "
            "candidate/release roots"
        )
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise AllShadowBootstrapError(f"run root is not a regular directory: {root}")
    return root


def _runtime_market_inventory() -> dict[str, Any]:
    rows = [
        {"market_id": market_id, "unit": spec.display_unit}
        for market_id, spec in sorted(REGISTRY.items())
    ]
    market_ids = [row["market_id"] for row in rows]
    fahrenheit = [row["market_id"] for row in rows if row["unit"] == "F"]
    celsius = [row["market_id"] for row in rows if row["unit"] == "C"]
    if (
        len(rows) != EXPECTED_RUNTIME_MARKET_COUNT
        or celsius != ["toronto"]
        or len(fahrenheit) != EXPECTED_FAHRENHEIT_MARKET_COUNT
    ):
        raise AllShadowBootstrapError(
            "runtime registry must be exactly Toronto in C plus eleven F markets; "
            f"observed={rows}"
        )
    return {
        "market_count": len(rows),
        "market_ids": market_ids,
        "toronto_unit": "C",
        "fahrenheit_market_count": len(fahrenheit),
        "markets": rows,
    }


def all_shadow_promotion() -> dict[str, Any]:
    inventory = _runtime_market_inventory()
    return {
        "verdict": "shadow",
        "promote_markets": [],
        "shadow_markets": inventory["market_ids"],
        "blocked_markets": [],
    }


def _copy_exclusive(
    source: Path,
    destination: Path,
    *,
    role: str,
    repo_root: Path,
) -> dict[str, Any]:
    try:
        source_info = source.lstat()
    except OSError as exc:
        raise AllShadowBootstrapError(f"{role} source is unreadable: {source}") from exc
    if stat.S_ISLNK(source_info.st_mode) or not stat.S_ISREG(source_info.st_mode):
        raise AllShadowBootstrapError(f"{role} source must be a regular non-symlink file: {source}")
    source_hash = sha256_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as input_handle, destination.open("xb") as output_handle:
            while chunk := input_handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
    except FileExistsError as exc:
        raise AllShadowBootstrapError(f"candidate destination already exists: {destination}") from exc
    except OSError as exc:
        raise AllShadowBootstrapError(f"{role} cannot be copied to {destination}") from exc
    if (
        destination.is_symlink()
        or size != source_info.st_size
        or digest.hexdigest() != source_hash
        or sha256_file(source) != source_hash
    ):
        raise AllShadowBootstrapError(f"{role} changed or failed hash verification while copied")
    result = {
        "role": role,
        "source_path": str(source),
        "candidate_relative_path": destination.as_posix(),
        "bytes": size,
        "sha256": source_hash,
    }
    try:
        result["source_repo_relative_path"] = source.relative_to(repo_root).as_posix()
    except ValueError:
        result["source_repo_relative_path"] = None
    return result


def _verified_release_role_source(
    source_release_dir: str | Path,
    *,
    role: str,
) -> tuple[Path, dict[str, Any]]:
    release_dir = Path(source_release_dir).resolve()
    verified = verify_release(release_dir, check_runtime=False)
    manifest = verified.get("manifest")
    inventory = (
        ((manifest or {}).get("artifacts") or {}).get("inventory")
        if isinstance(manifest, Mapping)
        else None
    )
    matches = [
        row
        for row in inventory or ()
        if isinstance(row, Mapping) and row.get("role") == role
    ]
    if verified.get("status") != "PASS" or len(matches) != 1:
        raise AllShadowBootstrapError(
            f"source release does not verify with exactly one {role!r} role: {release_dir}"
        )
    row = matches[0]
    source = release_dir / str(row.get("path") or "")
    if (
        source.is_symlink()
        or not source.is_file()
        or sha256_file(source) != row.get("sha256")
    ):
        raise AllShadowBootstrapError(
            f"source release role {role!r} failed its immutable hash: {source}"
        )
    return source, {
        "release_id": manifest.get("release_id"),
        "release_manifest_sha256": verified.get("manifest_sha256"),
        "role": role,
        "role_sha256": row.get("sha256"),
        "runtime_reverification_requested": False,
        "integrity_verification_status": verified.get("status"),
    }


def _verified_release_research_lineage(
    source_release_dir: str | Path,
    *,
    expected_bundle_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    release_dir = Path(source_release_dir).resolve()
    verified = verify_release(release_dir, check_runtime=False)
    manifest = verified.get("manifest")
    inventory = (
        ((manifest or {}).get("artifacts") or {}).get("inventory")
        if isinstance(manifest, Mapping)
        else None
    )
    matches = [
        row
        for row in inventory or ()
        if isinstance(row, Mapping) and row.get("role") == "training_evaluation_corpus"
    ]
    if verified.get("status") != "PASS" or len(matches) != 1:
        raise AllShadowBootstrapError(
            "source release does not verify with exactly one "
            f"training_evaluation_corpus role: {release_dir}"
        )
    row = matches[0]
    path = release_dir / str(row.get("path") or "")
    payload = _read_contract_json(path, label="source release training/evaluation corpus")
    if (
        sha256_file(path) != row.get("sha256")
        or payload.get("bundle_sha256") != expected_bundle_sha256
        or not isinstance(payload.get("corpus_lineage"), Mapping)
    ):
        raise AllShadowBootstrapError(
            "source release training/evaluation corpus is not bound to the selected model"
        )
    return dict(payload["corpus_lineage"]), {
        "role": "training_evaluation_corpus",
        "role_sha256": row.get("sha256"),
        "payload_sha256": payload.get("payload_sha256"),
        "bundle_sha256": payload.get("bundle_sha256"),
        "lineage_source_release_id": manifest.get("release_id"),
        "lineage_source_manifest_sha256": verified.get("manifest_sha256"),
    }


def _read_contract_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"), label=label)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AllShadowBootstrapError(f"{label} is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AllShadowBootstrapError(f"{label} must be a JSON object: {path}")
    return payload


def _verify_all_shadow_contract(
    *,
    candidate_dir: Path,
    semantic: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    market_ids = list(inventory["market_ids"])
    route = semantic.get("route")
    routes = route.get("markets") if isinstance(route, Mapping) else None
    if not isinstance(routes, Mapping) or sorted(routes) != market_ids:
        raise AllShadowBootstrapError("candidate route does not cover the exact runtime market set")
    invalid_routes = [
        market_id
        for market_id, row in routes.items()
        if (
            not isinstance(row, Mapping)
            or row.get("decision") != "shadow"
            or row.get("counts_toward_promotion") is not False
            or row.get("serving_release") is not None
        )
    ]
    if invalid_routes:
        raise AllShadowBootstrapError(f"candidate route is not uniformly inactive shadow: {invalid_routes}")
    graph = _read_contract_json(
        candidate_dir / SEMANTIC_PATHS["base_model_serving_graph"],
        label="base model serving graph",
    )
    markets = graph.get("markets")
    if not isinstance(markets, Mapping) or sorted(markets) != market_ids:
        raise AllShadowBootstrapError("base model graph does not cover the exact runtime market set")
    expected_components = sorted(BASE_MODEL_MARKET_COMPONENT_KINDS)
    invalid_graph = [
        market_id
        for market_id, row in markets.items()
        if not isinstance(row, Mapping)
        or sorted((row.get("components") or {}).keys()) != expected_components
    ]
    if invalid_graph:
        raise AllShadowBootstrapError(
            f"base model graph markets do not have the exact seven components: {invalid_graph}"
        )
    if (
        semantic.get("candidate_mode") != RESEARCH_ONLY_CANDIDATE_MODE
        or semantic.get("production_capable") is not False
    ):
        raise AllShadowBootstrapError("candidate semantic contract is not research_only")
    return {
        "market_count": len(markets),
        "shadow_market_count": len(routes),
        "promote_market_count": 0,
        "blocked_market_count": 0,
        "toronto_base_component_count": len(markets["toronto"]["components"]),
        "base_component_names": expected_components,
        "base_graph_sha256": sha256_file(
            candidate_dir / SEMANTIC_PATHS["base_model_serving_graph"]
        ),
        "route_sha256": route.get("payload_sha256"),
    }


def build_all_shadow_release(
    *,
    candidate_id: str,
    run_root: str | Path,
    repo_root: str | Path = REPO_ROOT,
    receipt_path: str | Path | None = None,
    expected_live_runtimes: Sequence[str] = DEFAULT_EXPECTED_RUNTIMES,
    model_source_release: str | Path | None = None,
) -> dict[str, Any]:
    """Freeze and verify one inactive release; never create an active pointer."""

    repo_root = Path(repo_root).resolve()
    root = _validate_run_root(run_root, repo_root=repo_root)
    inventory = _runtime_market_inventory()
    candidates_root = root / "release-bootstrap" / "candidates"
    releases_root = root / "release-bootstrap" / "releases"
    candidate_dir = candidates_root / candidate_id
    pointer_path = releases_root / "current_release.json"
    if pointer_path.exists() or pointer_path.is_symlink():
        raise AllShadowBootstrapError(f"active pointer must be absent before bootstrap: {pointer_path}")
    if candidate_dir.exists() or (releases_root / candidate_id).exists():
        raise AllShadowBootstrapError(f"candidate/release identity already exists: {candidate_id}")
    code = capture_code_identity(repo_root)
    if code.get("git_dirty") is not False:
        raise AllShadowBootstrapError("all-shadow release bootstrap requires a clean source tree")
    source_rows = []
    research_corpus_lineage: dict[str, Any] | None = None
    source_provenance: dict[str, Any] = {
        "pooled_band_model": {
            "kind": "tracked_repository_artifact",
            "path": SOURCE_ARTIFACTS["pooled_band_model"][0],
        }
    }
    candidate_dir.mkdir(parents=True)
    candidate_paths: dict[str, Path] = {}
    for role, (source_relative, candidate_relative) in SOURCE_ARTIFACTS.items():
        if role == "pooled_band_model" and model_source_release is not None:
            source, release_proof = _verified_release_role_source(
                model_source_release,
                role=role,
            )
            source_provenance[role] = {
                "kind": "verified_immutable_release_role",
                **release_proof,
            }
        else:
            source = repo_root / source_relative
            source_provenance.setdefault(
                role,
                {
                    "kind": "tracked_repository_artifact",
                    "path": source_relative,
                },
            )
        destination = candidate_dir / candidate_relative
        row = _copy_exclusive(
            source,
            destination,
            role=role,
            repo_root=repo_root,
        )
        row["candidate_relative_path"] = candidate_relative
        source_rows.append(row)
        candidate_paths[role] = destination
    if model_source_release is not None:
        research_corpus_lineage, lineage_proof = (
            _verified_release_research_lineage(
                model_source_release,
                expected_bundle_sha256=next(
                    row["sha256"]
                    for row in source_rows
                    if row["role"] == "pooled_band_model"
                ),
            )
        )
        source_provenance["training_evaluation_corpus"] = {
            "kind": "verified_immutable_release_role",
            **lineage_proof,
        }
    promotion = all_shadow_promotion()
    semantic = freeze_candidate_semantic_contract(
        candidate_dir=candidate_dir,
        model_bundle_path=candidate_paths["pooled_band_model"],
        family_secondary_path=candidate_paths["family_secondary_calibration"],
        artifact_registry_path=candidate_paths["artifact_registry"],
        repo_root=repo_root,
        candidate_id=candidate_id,
        parent_release=None,
        promotion=promotion,
        family_unit="F",
        candidate_mode=RESEARCH_ONLY_CANDIDATE_MODE,
        research_corpus_lineage=research_corpus_lineage,
    )
    contract_summary = _verify_all_shadow_contract(
        candidate_dir=candidate_dir,
        semantic=semantic,
        inventory=inventory,
    )
    release = create_release(
        release_id=candidate_id,
        candidate_dir=candidate_dir,
        declarations=semantic["declarations"],
        route=semantic["route"],
        expected_live_runtimes=expected_live_runtimes,
        releases_root=releases_root,
        repo_root=repo_root,
        parent_release=None,
        rollback_target=None,
        lineage={
            "build_kind": "reviewed_all_shadow_research_bootstrap",
            "candidate_mode": RESEARCH_ONLY_CANDIDATE_MODE,
            "production_capable": False,
            "promotion": promotion,
            "source_artifacts": source_rows,
            "source_provenance": source_provenance,
        },
        code_identity=code,
    )
    verified = verify_release(
        releases_root / candidate_id,
        repo_root=repo_root,
        expected_manifest_sha256=release["manifest_sha256"],
        check_runtime=True,
    )
    verified_semantic = verified.get("semantic_contract")
    if (
        verified.get("status") != "PASS"
        or not isinstance(verified_semantic, Mapping)
        or verified_semantic.get("candidate_mode") != RESEARCH_ONLY_CANDIDATE_MODE
        or verified_semantic.get("production_capable") is not False
    ):
        raise AllShadowBootstrapError("immutable release did not reverify as research_only")
    if pointer_path.exists() or pointer_path.is_symlink():
        raise AllShadowBootstrapError("bootstrap unexpectedly created an active pointer")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "generated_at_utc": _now(),
        "status": "PASS",
        "candidate_id": candidate_id,
        "candidate_mode": RESEARCH_ONLY_CANDIDATE_MODE,
        "production_capable": False,
        "activation": "NONE",
        "run_root": str(root),
        "candidate_dir": str(candidate_dir),
        "release_dir": release["release_dir"],
        "release_manifest_sha256": release["manifest_sha256"],
        "release_file_count": release["file_count"],
        "code_identity": code,
        "runtime_markets": inventory,
        "promotion": promotion,
        "contract": contract_summary,
        "source_artifacts": source_rows,
        "source_provenance": source_provenance,
        "verification": {
            "status": verified["status"],
            "semantic_candidate_mode": verified_semantic["candidate_mode"],
            "semantic_production_capable": verified_semantic["production_capable"],
            "runtime_checked": True,
        },
        "active_pointer": {
            "path": str(pointer_path),
            "exists": False,
            "created_or_changed": False,
        },
    }
    receipt["receipt_sha256"] = canonical_payload_sha256(
        receipt,
        omit=("receipt_sha256",),
    )
    output = Path(receipt_path) if receipt_path is not None else root / "release-bootstrap" / "receipt.json"
    write_json_atomic(output, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--receipt-out")
    parser.add_argument(
        "--model-source-release",
        help=(
            "optional previously verified immutable release whose pooled_band_model "
            "role supplies the bundle when the tracked research bundle lacks lineage"
        ),
    )
    parser.add_argument(
        "--expected-live-runtimes",
        default=",".join(DEFAULT_EXPECTED_RUNTIMES),
        help="comma-separated exact runtime identities",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_all_shadow_release(
        candidate_id=args.candidate_id,
        run_root=args.run_root,
        repo_root=args.repo_root,
        receipt_path=args.receipt_out,
        expected_live_runtimes=[
            value.strip()
            for value in args.expected_live_runtimes.split(",")
            if value.strip()
        ],
        model_source_release=args.model_source_release,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
