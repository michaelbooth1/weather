"""Artifact path policy with compatibility for the pre-package layout."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import ARTIFACTS_ROOT, SRC_ROOT, relative_to_repo
from weather.schema_registry import schema_version


ARTIFACT_REGISTRY_SCHEMA_VERSION = schema_version("model_artifact_registry")
DEFAULT_ARTIFACT_REGISTRY_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_registry.json"


def _artifact_dir(filename: str) -> Path:
    name = Path(filename).name
    if name.startswith("feature_model_hgb") and name.endswith(".pkl"):
        return ARTIFACTS_ROOT / "models" / "hgb"
    if (
        name.startswith("feature_model_coefs")
        or name.startswith("late_day_model_coefs")
    ) and name.endswith(".json"):
        return ARTIFACTS_ROOT / "models" / "coefs"
    if name == "f_family_secondary_artifacts.json":
        return ARTIFACTS_ROOT / "manifests"
    if (
        name.startswith("calibrated_weights")
        or name.startswith("probability_calibration")
        or name.startswith("forecast_error_model")
        or name.startswith("settlement_lag_model")
    ) and name.endswith(".json"):
        return ARTIFACTS_ROOT / "calibration"
    return ARTIFACTS_ROOT / "misc"


def artifact_path(filename: str | Path) -> Path:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return path
    return _artifact_dir(path.name) / path.name


def legacy_artifact_path(filename: str | Path) -> Path:
    return SRC_ROOT / Path(filename).name


def artifact_candidates(filename: str | Path) -> tuple[Path, ...]:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return (path,)
    return artifact_path(path.name), legacy_artifact_path(path.name)


def resolve_artifact_path(filename: str | Path, *, for_write: bool = False) -> Path:
    path = Path(filename)
    if path.is_absolute() or path.parent != Path("."):
        return path
    new_path = artifact_path(path.name)
    if for_write:
        return new_path
    if new_path.exists():
        return new_path
    old_path = legacy_artifact_path(path.name)
    if old_path.exists():
        return old_path
    return new_path


def writable_artifact_path(filename: str | Path) -> Path:
    path = resolve_artifact_path(filename, for_write=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def artifact_metadata_path(filename: str | Path) -> dict:
    path = resolve_artifact_path(filename)
    return {
        "path": relative_to_repo(path),
        "legacy_path": relative_to_repo(legacy_artifact_path(filename)),
        "exists": path.exists(),
        "is_legacy": path == legacy_artifact_path(filename),
    }


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def artifact_kind(path: str | Path) -> str:
    path = Path(path)
    name = path.name
    parts = {part.lower() for part in path.parts}
    if "hgb" in parts or (name.startswith("feature_model_hgb") and name.endswith(".pkl")):
        return "hgb_model"
    if "coefs" in parts or name.startswith(("feature_model_coefs", "late_day_model_coefs")):
        return "coefs_model"
    if "calibration" in parts:
        return "calibration"
    if "manifests" in parts:
        return "manifest"
    return "misc"


def json_artifact_versions(path: str | Path) -> dict:
    path = Path(path)
    if path.suffix.lower() != ".json":
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    versions = {}
    for key in ("schema_version", "feature_schema_version", "model_schema_version"):
        if payload.get(key):
            versions[key] = payload.get(key)
    if not versions and isinstance(payload, dict):
        first = next(iter(payload.values()), None)
        if isinstance(first, dict):
            for key in ("schema_version", "feature_schema_version", "model_schema_version"):
                if first.get(key):
                    versions[key] = first.get(key)
    return versions


def discover_artifact_files(root: str | Path = ARTIFACTS_ROOT):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and path.name != DEFAULT_ARTIFACT_REGISTRY_PATH.name
        and path.suffix.lower() in {".json", ".pkl", ".parquet"}
    )


def artifact_record(path: str | Path, root: str | Path = ARTIFACTS_ROOT) -> dict:
    path = Path(path)
    root = Path(root)
    stat = path.stat()
    try:
        artifact_id = path.relative_to(root).as_posix()
    except ValueError:
        artifact_id = relative_to_repo(path)
    versions = json_artifact_versions(path)
    return {
        "artifact_id": artifact_id,
        "path": relative_to_repo(path),
        "kind": artifact_kind(path),
        "suffix": path.suffix.lower(),
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "schema_version": versions.get("schema_version"),
        "feature_schema_version": versions.get("feature_schema_version"),
        "model_schema_version": versions.get("model_schema_version"),
    }


def build_artifact_registry(root: str | Path = ARTIFACTS_ROOT, generated_at=None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    rows = [artifact_record(path, root=root) for path in discover_artifact_files(root)]
    counts = Counter(row["kind"] for row in rows)
    return {
        "schema_version": ARTIFACT_REGISTRY_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "artifact_root": relative_to_repo(root),
        "artifact_count": len(rows),
        "kind_counts": dict(sorted(counts.items())),
        "artifacts": rows,
    }


def write_artifact_registry(path: str | Path = DEFAULT_ARTIFACT_REGISTRY_PATH, root: str | Path = ARTIFACTS_ROOT) -> Path:
    payload = build_artifact_registry(root=root)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def cmd_registry(args):
    out = write_artifact_registry(args.out, root=args.root)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact registry to {out}")
    print(f"artifacts={payload.get('artifact_count')} kinds={payload.get('kind_counts')}")


def build_parser():
    parser = argparse.ArgumentParser(description="Artifact path and registry utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    registry = sub.add_parser("registry")
    registry.add_argument("--root", default=str(ARTIFACTS_ROOT))
    registry.add_argument("--out", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    registry.set_defaults(func=cmd_registry)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
