"""Artifact path policy with compatibility for the pre-package layout."""

from __future__ import annotations

from pathlib import Path

from weather.paths import ARTIFACTS_ROOT, SRC_ROOT, relative_to_repo


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
