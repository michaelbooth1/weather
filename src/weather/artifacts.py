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
ARTIFACT_SIZE_AUDIT_SCHEMA_VERSION = schema_version("model_artifact_size_audit")
DEFAULT_ARTIFACT_REGISTRY_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_registry.json"
DEFAULT_ARTIFACT_SIZE_AUDIT_PATH = ARTIFACTS_ROOT / "manifests" / "model_artifact_size_audit.json"

MIB = 1024 * 1024
DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES = 90 * MIB
DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES = 100 * MIB
DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES = 350 * MIB
DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES = 500 * MIB


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
        and path.name != DEFAULT_ARTIFACT_SIZE_AUDIT_PATH.name
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


def _size_status(rows):
    if any(row["status"] == "FAIL" for row in rows):
        return "FAIL"
    if any(row["status"] == "WARN" for row in rows):
        return "WARN"
    return "PASS"


def _threshold_row(kind, status, bytes_value, threshold_bytes, artifact=None):
    row = {
        "kind": kind,
        "status": status,
        "bytes": int(bytes_value),
        "threshold_bytes": int(threshold_bytes),
    }
    if artifact is not None:
        row["artifact_id"] = artifact.get("artifact_id")
        row["path"] = artifact.get("path")
        row["suffix"] = artifact.get("suffix")
        row["artifact_kind"] = artifact.get("kind")
    return row


def build_artifact_size_audit(
    root: str | Path = ARTIFACTS_ROOT,
    *,
    generated_at=None,
    individual_warning_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES,
    individual_failure_bytes=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES,
    total_warning_bytes=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES,
    total_failure_bytes=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES,
    largest_limit=10,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    registry = build_artifact_registry(root=root, generated_at=generated_at)
    artifacts = registry["artifacts"]
    total_bytes = sum(row["bytes"] for row in artifacts)
    checks = []
    for row in artifacts:
        if row["bytes"] >= individual_failure_bytes:
            checks.append(_threshold_row("individual_artifact", "FAIL", row["bytes"], individual_failure_bytes, row))
        elif row["bytes"] >= individual_warning_bytes:
            checks.append(_threshold_row("individual_artifact", "WARN", row["bytes"], individual_warning_bytes, row))
    if total_bytes >= total_failure_bytes:
        checks.append(_threshold_row("total_artifacts", "FAIL", total_bytes, total_failure_bytes))
    elif total_bytes >= total_warning_bytes:
        checks.append(_threshold_row("total_artifacts", "WARN", total_bytes, total_warning_bytes))

    largest = sorted(artifacts, key=lambda row: row["bytes"], reverse=True)[:largest_limit]
    thresholds = {
        "individual_warning_bytes": int(individual_warning_bytes),
        "individual_failure_bytes": int(individual_failure_bytes),
        "total_warning_bytes": int(total_warning_bytes),
        "total_failure_bytes": int(total_failure_bytes),
        "policy": (
            "Track small JSON calibration artifacts and manifests in Git. "
            "Move binary model artifacts that reach the warning threshold to Git LFS "
            "or an external artifact store before promotion, and block artifacts at "
            "the failure threshold."
        ),
    }
    return {
        "schema_version": ARTIFACT_SIZE_AUDIT_SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "artifact_root": registry["artifact_root"],
        "status": _size_status(checks),
        "artifact_count": registry["artifact_count"],
        "total_bytes": total_bytes,
        "kind_counts": registry["kind_counts"],
        "thresholds": thresholds,
        "largest_artifacts": largest,
        "checks": checks,
    }


def write_artifact_size_audit(
    path: str | Path = DEFAULT_ARTIFACT_SIZE_AUDIT_PATH,
    root: str | Path = ARTIFACTS_ROOT,
    **kwargs,
) -> Path:
    payload = build_artifact_size_audit(root=root, **kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def cmd_registry(args):
    out = write_artifact_registry(args.out, root=args.root)
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact registry to {out}")
    print(f"artifacts={payload.get('artifact_count')} kinds={payload.get('kind_counts')}")


def cmd_size_audit(args):
    out = write_artifact_size_audit(
        args.out,
        root=args.root,
        individual_warning_bytes=args.individual_warning_bytes,
        individual_failure_bytes=args.individual_failure_bytes,
        total_warning_bytes=args.total_warning_bytes,
        total_failure_bytes=args.total_failure_bytes,
    )
    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    print(f"Wrote artifact size audit to {out}")
    print(
        "status={status} artifacts={count} total_mib={total:.2f}".format(
            status=payload.get("status"),
            count=payload.get("artifact_count"),
            total=(payload.get("total_bytes") or 0) / MIB,
        )
    )
    for row in payload.get("checks") or []:
        artifact = row.get("artifact_id") or row.get("kind")
        print(
            "{status}: {artifact} {size:.2f} MiB threshold={threshold:.2f} MiB".format(
                status=row.get("status"),
                artifact=artifact,
                size=(row.get("bytes") or 0) / MIB,
                threshold=(row.get("threshold_bytes") or 0) / MIB,
            )
        )
    if payload.get("status") == "FAIL" or (args.fail_on_warn and payload.get("status") == "WARN"):
        raise SystemExit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Artifact path and registry utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    registry = sub.add_parser("registry")
    registry.add_argument("--root", default=str(ARTIFACTS_ROOT))
    registry.add_argument("--out", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    registry.set_defaults(func=cmd_registry)
    size_audit = sub.add_parser("size-audit")
    size_audit.add_argument("--root", default=str(ARTIFACTS_ROOT))
    size_audit.add_argument("--out", default=str(DEFAULT_ARTIFACT_SIZE_AUDIT_PATH))
    size_audit.add_argument("--individual-warning-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_WARNING_BYTES)
    size_audit.add_argument("--individual-failure-bytes", type=int, default=DEFAULT_INDIVIDUAL_ARTIFACT_FAILURE_BYTES)
    size_audit.add_argument("--total-warning-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_WARNING_BYTES)
    size_audit.add_argument("--total-failure-bytes", type=int, default=DEFAULT_TOTAL_ARTIFACT_FAILURE_BYTES)
    size_audit.add_argument("--fail-on-warn", action="store_true")
    size_audit.set_defaults(func=cmd_size_audit)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
