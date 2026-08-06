"""Fail closed when trained model inputs do not arrive at serving time.

The gate reads retained surfaces only: exact trained feature names in serving
HGB artifacts, flattened feature vectors already captured with live snapshots,
and the paired snapshot/release identities needed to bind each row to that
artifact.  It does not replay the model, fetch a provider, or add a capture
path.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import pickle
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.captured_input_hash import (
    CAPTURED_INPUT_HASH_ALGORITHM,
    captured_input_payload_sha256,
)
from weather.io import write_json_atomic
from weather.market.market_config import config_for_date, market_id_from_slug
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.model_identity import IDENTITY_SCHEMA_VERSION
from weather.paths import REPO_ROOT, artifacts_path, data_path
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
)
from weather.release_serving import (
    STATUS_BOUND,
    load_verified_active_serving_bundle,
    materialize_verified_base_model_market,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("model_input_surface_gate")
REPLAY_INPUT_SCHEMA_VERSION = schema_version("replay_inputs")

# These are policy, not evidence supplied by the model or capture being judged.
TRAINED_FEATURE_POPULATION_FLOOR = 0.25
WINDOW_TARGET_DATE_COUNT = 3
EXPECTED_CUTOFF_HOURS = tuple(range(7, 21))
LEGITIMATELY_SPARSE_TRAINED_FEATURES = frozenset({"wind_gust_kmh"})
# ``wind_speed_kmh`` is a legacy name: U.S. captured rows retain native mph
# while Toronto retains km/h.  Five in either native unit is conservative
# affirmative evidence of calm/light wind.  Gust absence is exempt only when
# every row in the judged slice carries wind evidence at or below this bound.
GUST_CALM_MAX_SUSTAINED_WIND_NATIVE = 5.0

# The fixed 19-field base surface is reported independently from the dynamic
# trained surface.  A future artifact may add trained fields; those fields are
# still judged because the trained coverage table is not capped by this list.
BASE_FEATURES = (
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
    "forecast_high",
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
)

ESTABLISHED_DEAD_BASE_FEATURES = frozenset(
    {
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
        "wind_gust_kmh",
        "wind_shift_3h_degrees",
    }
)
ESTABLISHED_DEAD_TRAINED_FEATURES = frozenset(
    {
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
    }
)
ESTABLISHED_SURVIVOR_MIN_FRACTION = 0.936

DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_AMBIENT_HGB_ROOT = artifacts_path("models", "hgb")
DEFAULT_OUTPUT_ROOT = data_path("backtest", "model_input_surface_gate")


class ModelInputSurfaceGateError(RuntimeError):
    """The retained artifact or captured-row contract is unreadable."""


def _utc_iso(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _is_populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() in {"nan", "null", "none"}:
            return False
        return True
    try:
        return not math.isnan(value)
    except (TypeError, ValueError):
        return True


def _finite_number(value: Any) -> float | None:
    if not _is_populated(value):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _load_pickle(path: Path) -> tuple[Mapping[str, Any], str]:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ModelInputSurfaceGateError(f"cannot read serving artifact {path}: {exc}") from exc
    try:
        payload = pickle.loads(content)  # noqa: S301 - repository serving artifact
    except Exception as exc:  # noqa: BLE001 - fail-closed artifact boundary
        raise ModelInputSurfaceGateError(
            f"cannot deserialize serving artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ModelInputSurfaceGateError(f"serving artifact is not a mapping: {path}")
    return payload, _sha256_bytes(content)


def _hour_bundle(payload: Mapping[str, Any], hour: int) -> Any:
    if str(hour) in payload:
        return payload[str(hour)]
    return payload.get(hour)


def _feature_specs_for_hour(
    bundle: Mapping[str, Any],
    *,
    market_id: str,
    cutoff_hour: int | None,
) -> list[dict[str, str]]:
    names = bundle.get("feature_names")
    if isinstance(names, (str, bytes)) or not isinstance(names, Sequence) or not names:
        raise ModelInputSurfaceGateError(
            f"{market_id} hour {cutoff_hour} has no trained feature_names"
        )
    feature_names = [str(value).strip() for value in names]
    if any(not value for value in feature_names):
        raise ModelInputSurfaceGateError(
            f"{market_id} hour {cutoff_hour} has an empty trained feature name"
        )
    if len(feature_names) != len(set(feature_names)):
        raise ModelInputSurfaceGateError(
            f"{market_id} hour {cutoff_hour} has duplicate trained feature names"
        )

    wind_groups = [str(value) for value in (bundle.get("all_wind_groups") or [])]
    cloud_groups = [str(value) for value in (bundle.get("all_cloud_groups") or [])]
    derived_wind = {f"wind_{group}" for group in wind_groups}
    derived_cloud = {f"cloud_{group}" for group in cloud_groups}
    specs = []
    for name in feature_names:
        if name in derived_wind:
            specs.append(
                {
                    "feature": name,
                    "source_kind": "derived_one_hot",
                    "source_field": "wind_group",
                    "category": name.removeprefix("wind_"),
                }
            )
        elif name in derived_cloud:
            specs.append(
                {
                    "feature": name,
                    "source_kind": "derived_one_hot",
                    "source_field": "cloud_group",
                    "category": name.removeprefix("cloud_"),
                }
            )
        else:
            specs.append(
                {
                    "feature": name,
                    "source_kind": "direct",
                    "source_field": name,
                    "category": "",
                }
            )
    return specs


def _extract_trained_surface(
    payload: Mapping[str, Any],
    *,
    market_id: str,
) -> dict[int, list[dict[str, str]]]:
    result: dict[int, list[dict[str, str]]] = {}
    for hour in EXPECTED_CUTOFF_HOURS:
        bundle = _hour_bundle(payload, hour)
        if not isinstance(bundle, Mapping):
            raise ModelInputSurfaceGateError(
                f"{market_id} serving artifact has no hour {hour} bundle"
            )
        result[hour] = _feature_specs_for_hour(
            bundle,
            market_id=market_id,
            cutoff_hour=hour,
        )
    return result


def _ambient_artifact_path(market_id: str, artifact_root: Path) -> Path:
    spec = spec_for_id(market_id)
    return artifact_root / f"feature_model_hgb{spec.artifact_suffix}.pkl"


def _load_trained_surfaces(
    *,
    market_ids: Sequence[str],
    artifact_paths: Mapping[str, str | Path] | None,
    artifact_root: str | Path,
    active_release_pointer: str | Path,
    releases_root: str | Path,
) -> tuple[
    dict[str, dict[int, list[dict[str, str]]]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    trained: dict[str, dict[int, list[dict[str, str]]]] = {}
    identities: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    pointer_path = Path(active_release_pointer)
    binding: dict[str, Any] = {
        "mode": "explicit_artifact_paths" if artifact_paths is not None else "ambient_global",
        "active_release_pointer": str(pointer_path.resolve()),
        "active_release_pointer_present": pointer_path.is_file(),
    }

    release_bundle = None
    if artifact_paths is None and pointer_path.is_file():
        try:
            release_bundle = load_verified_active_serving_bundle(
                pointer_path=pointer_path,
                releases_root=releases_root,
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed release boundary
            blockers.append(
                {
                    "code": "active_release_binding_invalid",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            binding.update(
                {
                    "mode": "verified_active_release",
                    "status": release_bundle.status,
                    "release_id": release_bundle.release_id,
                    "manifest_sha256": release_bundle.manifest_sha256,
                    "pointer_sha256": release_bundle.pointer_sha256,
                    "sequence": release_bundle.sequence,
                    "base_model_bound": release_bundle.base_model_bound,
                    "base_model_binding_reason": release_bundle.base_model_binding_reason,
                }
            )
            if release_bundle.status != STATUS_BOUND:
                blockers.append(
                    {
                        "code": "active_release_not_bound",
                        "detail": release_bundle.reason,
                    }
                )
            elif not release_bundle.base_model_bound:
                blockers.append(
                    {
                        "code": "active_release_base_model_not_bound",
                        "detail": release_bundle.base_model_binding_reason,
                    }
                )

    for market_id in market_ids:
        payload: Mapping[str, Any] | None = None
        path: Path | None = None
        sha256 = ""
        try:
            if release_bundle is not None and release_bundle.status == STATUS_BOUND:
                materialized = materialize_verified_base_model_market(
                    release_bundle,
                    market_id,
                )
                payload = materialized["feature_hgb"]
                descriptor = release_bundle.base_model_artifacts[market_id]["feature_hgb"]
                path = Path(str(descriptor["path"]))
                sha256 = str(descriptor["sha256"])
            else:
                if artifact_paths is not None:
                    raw_path = artifact_paths.get(market_id)
                    if raw_path is None:
                        raise ModelInputSurfaceGateError(
                            f"no serving artifact supplied for market {market_id}"
                        )
                    path = Path(raw_path)
                else:
                    path = _ambient_artifact_path(market_id, Path(artifact_root))
                payload, sha256 = _load_pickle(path)
            trained[market_id] = _extract_trained_surface(payload, market_id=market_id)
            identities.append(
                {
                    "market_id": market_id,
                    "path": str(path.resolve()),
                    "sha256": sha256,
                    "trained_feature_count_by_hour": {
                        str(hour): len(trained[market_id][hour])
                        for hour in EXPECTED_CUTOFF_HOURS
                    },
                    "trained_feature_names_by_hour": {
                        str(hour): [row["feature"] for row in trained[market_id][hour]]
                        for hour in EXPECTED_CUTOFF_HOURS
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 - one market must not hide another
            blockers.append(
                {
                    "code": "serving_artifact_unusable",
                    "market_id": market_id,
                    "path": str(path.resolve()) if path is not None else None,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        finally:
            payload = None
            gc.collect()

    return trained, identities, binding, blockers


def _window_dates(end_date: str | date) -> tuple[date, ...]:
    end = date.fromisoformat(str(end_date)) if not isinstance(end_date, date) else end_date
    start = end - timedelta(days=WINDOW_TARGET_DATE_COUNT - 1)
    return tuple(start + timedelta(days=offset) for offset in range(WINDOW_TARGET_DATE_COUNT))


def _feature_source_path(folder: Path) -> tuple[Path | None, str | None]:
    sidecar = folder / "features.jsonl"
    if sidecar.is_file():
        return sidecar, "features_jsonl"
    snapshots = folder / "snapshots.jsonl"
    if snapshots.is_file():
        return snapshots, "snapshots_jsonl_feature_vector"
    return None, None


def _read_feature_file(
    path: Path,
    *,
    source_kind: str,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    try:
        handle = path.open("rb")
    except OSError as exc:
        raise ModelInputSurfaceGateError(f"cannot read captured features {path}: {exc}") from exc
    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                issues.append(
                    {
                        "code": "captured_feature_row_invalid_json",
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "detail": str(exc),
                    }
                )
                continue
            if not isinstance(payload, Mapping):
                issues.append(
                    {
                        "code": "captured_feature_row_not_object",
                        "path": str(path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            if source_kind == "snapshots_jsonl_feature_vector":
                vector = payload.get("feature_vector")
                if not isinstance(vector, Mapping):
                    issues.append(
                        {
                            "code": "snapshot_feature_vector_missing",
                            "path": str(path.resolve()),
                            "line_number": line_number,
                            "snapshot_id": payload.get("snapshot_id"),
                        }
                    )
                    continue
                row = dict(vector)
                for key in ("snapshot_id", "event_slug"):
                    row.setdefault(key, payload.get(key))
                row.setdefault("captured_at_local", payload.get("captured_at_local"))
                row.setdefault("captured_at_utc", payload.get("captured_at_utc"))
            else:
                row = dict(payload)
            rows.append(row)
    return rows, digest.hexdigest(), issues


def _hgb_descriptor_from_model_identity(
    model_identity: Any,
    *,
    market_id: str,
    expected_artifact_path: Path,
) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(model_identity, Mapping):
        return None, "model_identity_missing"
    if model_identity.get("schema_version") != IDENTITY_SCHEMA_VERSION:
        return None, "model_identity_schema_invalid"
    identity_market = str(model_identity.get("market_id") or "").strip()
    if identity_market != market_id:
        return None, "model_identity_market_mismatch"
    active_kind = str(model_identity.get("active_model_kind") or "").strip().casefold()
    if active_kind != "hgb":
        return None, "active_model_kind_not_hgb"
    artifact_files = model_identity.get("artifact_files")
    if isinstance(artifact_files, (str, bytes)) or not isinstance(
        artifact_files,
        Sequence,
    ):
        return None, "artifact_files_missing"
    expected_normalized = str(expected_artifact_path.resolve()).casefold()

    def normalized_descriptor_path(row: Mapping[str, Any]) -> str:
        raw = Path(str(row.get("path") or ""))
        resolved = raw if raw.is_absolute() else REPO_ROOT / raw
        return str(resolved.resolve()).casefold()

    descriptors = [row for row in artifact_files if isinstance(row, Mapping)]
    exact = [
        row
        for row in descriptors
        if normalized_descriptor_path(row) == expected_normalized
    ]
    if len(exact) != 1:
        return None, "hgb_descriptor_missing" if not exact else "hgb_descriptor_ambiguous"
    descriptor = exact[0]
    if descriptor.get("exists") is not True:
        return None, "hgb_descriptor_not_present"
    sha256 = str(descriptor.get("sha256") or "").strip().casefold()
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        return None, "hgb_sha256_invalid"
    return {
        "path": str(descriptor.get("path") or ""),
        "sha256": sha256,
        "identity_hash": str(model_identity.get("identity_hash") or ""),
        "model_identity_payload_sha256": _canonical_mapping_sha256(model_identity),
    }, None


def _read_snapshot_bindings(
    path: Path,
    *,
    market_id: str,
    event_slug: str,
    expected_artifact_path: Path,
) -> tuple[dict[str, dict[str, str]], str | None, list[dict[str, Any]]]:
    bindings: dict[str, dict[str, str]] = {}
    duplicate_ids: set[str] = set()
    issues: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    try:
        handle = path.open("rb")
    except OSError as exc:
        issues.append(
            {
                "code": "captured_model_artifact_identity_unbound",
                "reason": "snapshot_identity_file_missing",
                "market_id": market_id,
                "path": str(path.resolve()),
                "detail": str(exc),
            }
        )
        return bindings, None, issues

    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "snapshot_identity_invalid_json",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "detail": str(exc),
                    }
                )
                continue
            if not isinstance(payload, Mapping):
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "snapshot_identity_not_object",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            snapshot_id = str(payload.get("snapshot_id") or "").strip()
            if not snapshot_id:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "snapshot_id_missing",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            if snapshot_id in bindings or snapshot_id in duplicate_ids:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "duplicate_snapshot_identity",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "snapshot_id": snapshot_id,
                    }
                )
                bindings.pop(snapshot_id, None)
                duplicate_ids.add(snapshot_id)
                continue
            if str(payload.get("event_slug") or "") != event_slug:
                bindings[snapshot_id] = {"error": "snapshot_identity_event_mismatch"}
                continue
            descriptor, reason = _hgb_descriptor_from_model_identity(
                payload.get("model_identity"),
                market_id=market_id,
                expected_artifact_path=expected_artifact_path,
            )
            if descriptor is None:
                bindings[snapshot_id] = {"error": str(reason)}
            else:
                bindings[snapshot_id] = descriptor
    return bindings, digest.hexdigest(), issues


def _read_release_lineage_bindings(
    path: Path,
    *,
    market_id: str,
    event_slug: str,
    target_date: str,
    serving_binding: Mapping[str, Any],
) -> tuple[dict[str, dict[str, str]], str | None, list[dict[str, Any]]]:
    bindings: dict[str, dict[str, str]] = {}
    duplicate_ids: set[str] = set()
    issues: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    try:
        handle = path.open("rb")
    except OSError as exc:
        issues.append(
            {
                "code": "captured_model_artifact_identity_unbound",
                "reason": "release_lineage_file_missing",
                "market_id": market_id,
                "path": str(path.resolve()),
                "detail": str(exc),
            }
        )
        return bindings, None, issues

    expected = {
        "release_id": str(serving_binding.get("release_id") or ""),
        "release_manifest_sha256": str(serving_binding.get("manifest_sha256") or ""),
        "release_pointer_sha256": str(serving_binding.get("pointer_sha256") or ""),
        "release_sequence": serving_binding.get("sequence"),
    }
    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "release_lineage_invalid_json",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "detail": str(exc),
                    }
                )
                continue
            if not isinstance(payload, Mapping):
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "release_lineage_not_object",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            snapshot_id = str(payload.get("snapshot_id") or "").strip()
            if not snapshot_id:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "release_lineage_snapshot_id_missing",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                    }
                )
                continue
            if snapshot_id in bindings or snapshot_id in duplicate_ids:
                issues.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "duplicate_release_lineage",
                        "market_id": market_id,
                        "path": str(path.resolve()),
                        "line_number": line_number,
                        "snapshot_id": snapshot_id,
                    }
                )
                bindings.pop(snapshot_id, None)
                duplicate_ids.add(snapshot_id)
                continue

            reason = ""
            replay_model_identity = payload.get("model_identity")
            replay_model_identity_sha256 = (
                _canonical_mapping_sha256(replay_model_identity)
                if isinstance(replay_model_identity, Mapping)
                else ""
            )
            try:
                expected_captured_input_hash = captured_input_payload_sha256(
                    payload,
                    persisted=True,
                )
            except Exception:  # noqa: BLE001 - corrupt retained replay row
                expected_captured_input_hash = ""
            observed = {
                "release_id": str(payload.get("release_id") or ""),
                "release_manifest_sha256": str(
                    payload.get("release_manifest_sha256") or ""
                ),
                "release_pointer_sha256": str(
                    payload.get("release_pointer_sha256") or ""
                ),
                "release_sequence": payload.get("release_sequence"),
            }
            if payload.get("schema_version") != REPLAY_INPUT_SCHEMA_VERSION:
                reason = "release_lineage_schema_invalid"
            elif (
                payload.get("captured_input_hash_algorithm")
                != CAPTURED_INPUT_HASH_ALGORITHM
                or not expected_captured_input_hash
                or str(payload.get("captured_input_hash") or "")
                != expected_captured_input_hash
            ):
                reason = "captured_input_self_hash_invalid"
            elif not replay_model_identity_sha256:
                reason = "release_model_identity_missing"
            elif str(payload.get("event_slug") or "") != event_slug:
                reason = "release_lineage_event_mismatch"
            elif str(payload.get("target_date") or "") != target_date:
                reason = "release_lineage_target_date_mismatch"
            elif market_id_from_slug(event_slug) != market_id:
                reason = "release_lineage_market_mismatch"
            elif payload.get("release_identity_status") != "verified_variant_serving_bundle":
                reason = "release_identity_not_verified"
            elif payload.get("base_model_release_bound") is not True:
                reason = "base_model_release_not_bound"
            elif not str(payload.get("base_model_binding_reason") or "").strip():
                reason = "base_model_binding_reason_missing"
            elif observed != expected:
                reason = "release_lineage_mismatch"
            bindings[snapshot_id] = (
                {"error": reason}
                if reason
                else {
                    "release_id": observed["release_id"],
                    "manifest_sha256": observed["release_manifest_sha256"],
                    "pointer_sha256": observed["release_pointer_sha256"],
                    "sequence": str(observed["release_sequence"]),
                    "model_identity_payload_sha256": replay_model_identity_sha256,
                }
            )
    return bindings, digest.hexdigest(), issues


def _coverage_row(
    *,
    market_id: str,
    target_date: str | None,
    cutoff_hour: int,
    feature: str,
    source_kind: str,
    source_field: str,
    category: str,
    total_count: int,
    populated_count: int,
    source_populated_count: int | None = None,
    affirmative_calm_count: int | None = None,
    require_any_arrival: bool = False,
) -> dict[str, Any]:
    null_count = total_count - populated_count
    fraction = populated_count / total_count if total_count else None
    if not total_count:
        decision = "BLOCK"
        reason = "no artifact-bound captured rows for expected slice"
    elif feature in LEGITIMATELY_SPARSE_TRAINED_FEATURES:
        if populated_count > 0:
            decision = "PASS"
            reason = "at least one gust value proves arrival; other calm-condition gaps are allowed"
        elif affirmative_calm_count == total_count:
            decision = "EXEMPT_ALLOWED_MISSING"
            reason = "every row has affirmative calm-wind evidence, so gust absence is allowed"
        else:
            decision = "BLOCK"
            reason = "gust is absent without affirmative calm-wind evidence for every row"
    elif require_any_arrival and populated_count > 0:
        decision = "PASS"
        reason = "trained feature arrived at least once on the target date"
    elif require_any_arrival:
        decision = "BLOCK"
        reason = "trained feature did not arrive on the target date"
    elif fraction is not None and fraction >= TRAINED_FEATURE_POPULATION_FLOOR:
        decision = "PASS"
        reason = "trained feature meets the code-owned population floor"
    else:
        decision = "BLOCK"
        reason = "trained feature is below the code-owned population floor"
    result = {
        "market_id": market_id,
        "target_date": target_date,
        "cutoff_hour": cutoff_hour,
        "feature": feature,
        "source_kind": source_kind,
        "source_field": source_field,
        "derived_category": category or None,
        "total_count": total_count,
        "populated_count": populated_count,
        "null_count": null_count,
        "populated_fraction": fraction,
        "minimum_fraction": (
            None
            if feature in LEGITIMATELY_SPARSE_TRAINED_FEATURES or require_any_arrival
            else TRAINED_FEATURE_POPULATION_FLOOR
        ),
        "minimum_population_rule": (
            "gust_arrival_or_all_rows_affirmatively_calm"
            if feature in LEGITIMATELY_SPARSE_TRAINED_FEATURES
            else "at_least_one_arrival_per_target_date"
            if require_any_arrival
            else "window_fraction_floor"
        ),
        "decision": decision,
        "reason": reason,
    }
    if source_populated_count is not None:
        result["source_field_populated_count"] = source_populated_count
        result["source_field_null_count"] = total_count - source_populated_count
    if feature in LEGITIMATELY_SPARSE_TRAINED_FEATURES:
        result["affirmative_calm_count"] = int(affirmative_calm_count or 0)
        result["unproven_calm_count"] = total_count - int(affirmative_calm_count or 0)
        result["calm_max_sustained_wind_native"] = GUST_CALM_MAX_SUSTAINED_WIND_NATIVE
    return result


def _base_coverage_rows(
    *,
    market_ids: Sequence[str],
    total_by_slice: Mapping[tuple[str, int], int],
    populated_by_field: Mapping[tuple[str, int, str], int],
) -> list[dict[str, Any]]:
    rows = []
    for market_id in market_ids:
        for hour in EXPECTED_CUTOFF_HOURS:
            total = total_by_slice.get((market_id, hour), 0)
            for feature in BASE_FEATURES:
                populated = populated_by_field.get((market_id, hour, feature), 0)
                rows.append(
                    {
                        "market_id": market_id,
                        "cutoff_hour": hour,
                        "feature": feature,
                        "total_count": total,
                        "populated_count": populated,
                        "null_count": total - populated,
                        "populated_fraction": populated / total if total else None,
                    }
                )
    return rows


def _base_feature_summary(base_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    populated: dict[str, int] = defaultdict(int)
    for row in base_rows:
        feature = str(row["feature"])
        totals[feature] += int(row["total_count"])
        populated[feature] += int(row["populated_count"])
    return [
        {
            "feature": feature,
            "total_count": totals[feature],
            "populated_count": populated[feature],
            "null_count": totals[feature] - populated[feature],
            "populated_fraction": (
                populated[feature] / totals[feature] if totals[feature] else None
            ),
        }
        for feature in BASE_FEATURES
    ]


def _positive_control(
    *,
    market_ids: Sequence[str],
    base_rows: Sequence[Mapping[str, Any]],
    trained_rows: Sequence[Mapping[str, Any]],
    artifact_identities: Sequence[Mapping[str, Any]],
    requested: bool,
) -> dict[str, Any]:
    # Section 4 reports Toronto separately from an 11-market fleet result, so a
    # non-Toronto comparison is useful.  It does *not* enumerate the historical
    # 11 market IDs, however; this comparison must never be represented as an
    # identity-bound reproduction of the retained production scope.
    control_market_ids = tuple(
        market_id for market_id in market_ids if market_id != "toronto"
    )
    scoped_base_rows = [
        row for row in base_rows if row["market_id"] in control_market_ids
    ]
    scoped_base_summary = _base_feature_summary(scoped_base_rows)
    by_feature_cells: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in scoped_base_rows:
        by_feature_cells[str(row["feature"])].append(row)
    expected_cell_count = len(control_market_ids) * len(EXPECTED_CUTOFF_HOURS)
    uniform_zero = sorted(
        feature
        for feature, cells in by_feature_cells.items()
        if len(cells) == expected_cell_count
        and all(
            int(row["total_count"]) > 0 and float(row["populated_fraction"]) == 0.0
            for row in cells
        )
    )
    base_by_name = {str(row["feature"]): row for row in scoped_base_summary}
    survivors = [
        base_by_name[feature]
        for feature in BASE_FEATURES
        if feature not in ESTABLISHED_DEAD_BASE_FEATURES
    ]
    survivor_fractions = [
        float(row["populated_fraction"])
        for row in survivors
        if row.get("populated_fraction") is not None
    ]
    survivor_min = min(survivor_fractions) if survivor_fractions else None
    survivor_max = max(survivor_fractions) if survivor_fractions else None

    toronto_rows = [row for row in trained_rows if row["market_id"] == "toronto"]
    dead_by_hour: dict[int, set[str]] = defaultdict(set)
    for row in toronto_rows:
        if (
            row["source_kind"] == "direct"
            and row.get("populated_fraction") == 0.0
        ):
            dead_by_hour[int(row["cutoff_hour"])].add(str(row["feature"]))
    toronto_identity = next(
        (row for row in artifact_identities if row.get("market_id") == "toronto"),
        {},
    )
    count_by_hour = toronto_identity.get("trained_feature_count_by_hour") or {}
    trained_control = (
        set(dead_by_hour) == set(EXPECTED_CUTOFF_HOURS)
        and all(
            dead_by_hour[hour] == set(ESTABLISHED_DEAD_TRAINED_FEATURES)
            for hour in EXPECTED_CUTOFF_HOURS
        )
        and all(int(count_by_hour.get(str(hour), -1)) == 29 for hour in EXPECTED_CUTOFF_HOURS)
    )
    base_control = set(uniform_zero) == set(ESTABLISHED_DEAD_BASE_FEATURES)
    survivor_control = (
        len(survivor_fractions) == 9
        and survivor_min is not None
        and survivor_min >= ESTABLISHED_SURVIVOR_MIN_FRACTION
        and survivor_max is not None
        and survivor_max <= 1.0
    )
    return {
        "requested": requested,
        "reference": "docs/operations/ESTABLISHED_FINDINGS.md#4",
        "scope_note": (
            "Section 4 reports an 11-market Aug 3--5 fleet result and a separate "
            "Toronto result but does not enumerate the fleet market IDs. The non-Toronto "
            "rows below are a provisional comparison, not an identity-bound reproduction."
        ),
        "reference_market_count": 11,
        "reference_scope_market_ids_enumerated": False,
        "authoritative_scope": False,
        "required_control": "full_retained_range",
        "market_ids": list(control_market_ids),
        "market_count": len(control_market_ids),
        "target_date_count": WINDOW_TARGET_DATE_COUNT,
        "row_count": (
            int(scoped_base_summary[0]["total_count"])
            if scoped_base_summary
            else 0
        ),
        "expected_dead_base_features": sorted(ESTABLISHED_DEAD_BASE_FEATURES),
        "observed_uniform_zero_base_features": uniform_zero,
        "base_feature_control_reproduced": base_control,
        "surviving_base_feature_count": len(survivor_fractions),
        "surviving_base_feature_fraction_min": survivor_min,
        "surviving_base_feature_fraction_max": survivor_max,
        "evaluated_scope_survivor_range_matches_reference": survivor_control,
        "expected_dead_trained_features": sorted(ESTABLISHED_DEAD_TRAINED_FEATURES),
        "toronto_dead_trained_features_by_hour": {
            str(hour): sorted(dead_by_hour.get(hour, set()))
            for hour in EXPECTED_CUTOFF_HOURS
        },
        "toronto_trained_8_of_29_all_hours_reproduced": trained_control,
        "core_dead_input_control_reproduced": base_control and trained_control,
        "full_retained_range_reproduced_on_this_host": False,
        "full_retained_range_unverified_reason": "historical_market_ids_not_enumerated",
        "authoritative_production_range_verification_required": True,
        "reproduced": False,
    }


def evaluate_gate(
    *,
    snapshot_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    end_date: str | date,
    artifact_paths: Mapping[str, str | Path] | None = None,
    market_ids: Sequence[str] | None = None,
    generated_at: datetime | None = None,
    require_positive_control: bool = False,
    artifact_root: str | Path = DEFAULT_AMBIENT_HGB_ROOT,
    active_release_pointer: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
) -> dict[str, Any]:
    """Build the fleet-wide trained-input coverage artifact and verdict."""

    markets = tuple(market_ids or sorted(spec.id for spec in all_specs()))
    if not markets or len(markets) != len(set(markets)):
        raise ModelInputSurfaceGateError("expected market set must be non-empty and unique")
    dates = _window_dates(end_date)
    snapshot_root = Path(snapshot_root)
    trained, artifact_identities, serving_binding, evidence_blockers = _load_trained_surfaces(
        market_ids=markets,
        artifact_paths=artifact_paths,
        artifact_root=artifact_root,
        active_release_pointer=active_release_pointer,
        releases_root=releases_root,
    )

    artifact_identity_by_market = {
        str(row["market_id"]): row for row in artifact_identities
    }
    total_by_slice: dict[tuple[str, int], int] = defaultdict(int)
    total_by_date_slice: dict[tuple[str, str, int], int] = defaultdict(int)
    rows_by_date_hour: dict[tuple[str, str, int], int] = defaultdict(int)
    populated_by_field: dict[tuple[str, int, str], int] = defaultdict(int)
    populated_by_date_field: dict[tuple[str, str, int, str], int] = defaultdict(int)
    affirmative_calm_by_slice: dict[tuple[str, int], int] = defaultdict(int)
    affirmative_calm_by_date_slice: dict[tuple[str, str, int], int] = defaultdict(int)
    capture_files: list[dict[str, Any]] = []
    seen_snapshot_ids: set[tuple[str, str, str]] = set()
    ignored_out_of_scope_rows = 0
    release_bound_mode = serving_binding.get("mode") == "verified_active_release"

    for market_id in markets:
        expected_artifact = artifact_identity_by_market.get(market_id)
        expected_artifact_path = (
            Path(str(expected_artifact["path"])) if expected_artifact is not None else None
        )
        expected_artifact_sha256 = (
            str(expected_artifact["sha256"]).casefold()
            if expected_artifact is not None
            else ""
        )
        captured_identity_artifact_path = (
            _ambient_artifact_path(market_id, Path(artifact_root))
            if release_bound_mode
            else expected_artifact_path
        )
        direct_by_hour = {
            hour: {
                spec["source_field"]
                for spec in trained.get(market_id, {}).get(hour, [])
                if spec["source_kind"] == "direct"
            }
            for hour in EXPECTED_CUTOFF_HOURS
        }
        for target in dates:
            target_text = target.isoformat()
            try:
                slug = config_for_date(target, market_id).event_slug
            except Exception as exc:  # noqa: BLE001 - registry/config evidence boundary
                evidence_blockers.append(
                    {
                        "code": "expected_event_slug_unavailable",
                        "market_id": market_id,
                        "target_date": target_text,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            folder = snapshot_root / slug
            source_path, source_kind = _feature_source_path(folder)
            if source_path is None or source_kind is None:
                evidence_blockers.append(
                    {
                        "code": "captured_feature_file_missing",
                        "market_id": market_id,
                        "target_date": target_text,
                        "folder": str(folder.resolve()),
                    }
                )
                continue
            try:
                file_rows, file_sha256, file_issues = _read_feature_file(
                    source_path,
                    source_kind=source_kind,
                )
            except ModelInputSurfaceGateError as exc:
                evidence_blockers.append(
                    {
                        "code": "captured_feature_file_unreadable",
                        "market_id": market_id,
                        "target_date": target_text,
                        "path": str(source_path.resolve()),
                        "detail": str(exc),
                    }
                )
                continue
            evidence_blockers.extend(file_issues)

            snapshot_identity_path = folder / "snapshots.jsonl"
            bindings: dict[str, dict[str, str]] = {}
            identity_sha256: str | None = None
            if captured_identity_artifact_path is not None:
                bindings, identity_sha256, identity_issues = _read_snapshot_bindings(
                    snapshot_identity_path,
                    market_id=market_id,
                    event_slug=slug,
                    expected_artifact_path=captured_identity_artifact_path,
                )
                evidence_blockers.extend(
                    {**issue, "target_date": target_text} for issue in identity_issues
                )
            release_lineage_path = folder / "replay_inputs.jsonl"
            release_bindings: dict[str, dict[str, str]] = {}
            release_lineage_sha256: str | None = None
            if release_bound_mode:
                (
                    release_bindings,
                    release_lineage_sha256,
                    release_issues,
                ) = _read_release_lineage_bindings(
                    release_lineage_path,
                    market_id=market_id,
                    event_slug=slug,
                    target_date=target_text,
                    serving_binding=serving_binding,
                )
                evidence_blockers.extend(
                    {**issue, "target_date": target_text} for issue in release_issues
                )
            used_rows = 0
            unbound_reason_counts: dict[str, int] = defaultdict(int)
            unbound_examples: dict[str, list[str]] = defaultdict(list)
            observed_hgb_sha256s: set[str] = set()
            observed_release_ids: set[str] = set()
            feature_id_counts: dict[str, int] = defaultdict(int)
            for candidate in file_rows:
                candidate_id = str(candidate.get("snapshot_id") or "").strip()
                if candidate_id:
                    feature_id_counts[candidate_id] += 1
            duplicate_feature_ids = {
                snapshot_id
                for snapshot_id, count in feature_id_counts.items()
                if count > 1
            }
            if duplicate_feature_ids:
                evidence_blockers.append(
                    {
                        "code": "captured_feature_row_duplicate",
                        "market_id": market_id,
                        "target_date": target_text,
                        "path": str(source_path.resolve()),
                        "duplicate_snapshot_id_count": len(duplicate_feature_ids),
                        "example_snapshot_ids": sorted(duplicate_feature_ids)[:5],
                    }
                )
            snapshot_ids_without_feature_rows = set(bindings) - set(feature_id_counts)
            if snapshot_ids_without_feature_rows:
                evidence_blockers.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": "feature_sidecar_row_missing",
                        "market_id": market_id,
                        "target_date": target_text,
                        "feature_path": str(source_path.resolve()),
                        "identity_path": str(snapshot_identity_path.resolve()),
                        "affected_row_count": len(snapshot_ids_without_feature_rows),
                        "example_snapshot_ids": sorted(
                            snapshot_ids_without_feature_rows
                        )[:5],
                    }
                )
            if release_bound_mode:
                release_ids_without_snapshots = set(release_bindings) - set(bindings)
                if release_ids_without_snapshots:
                    evidence_blockers.append(
                        {
                            "code": "captured_model_artifact_identity_unbound",
                            "reason": "release_lineage_row_unjoined",
                            "market_id": market_id,
                            "target_date": target_text,
                            "identity_path": str(snapshot_identity_path.resolve()),
                            "release_lineage_path": str(
                                release_lineage_path.resolve()
                            ),
                            "affected_row_count": len(release_ids_without_snapshots),
                            "example_snapshot_ids": sorted(
                                release_ids_without_snapshots
                            )[:5],
                        }
                    )
            for row in file_rows:
                row_target = str(row.get("target_date") or "")[:10]
                row_slug = str(row.get("event_slug") or "")
                if row_target != target_text or row_slug != slug:
                    evidence_blockers.append(
                        {
                            "code": "captured_feature_row_identity_mismatch",
                            "market_id": market_id,
                            "target_date": target_text,
                            "snapshot_id": row.get("snapshot_id"),
                            "observed_target_date": row_target or None,
                            "observed_event_slug": row_slug or None,
                            "expected_event_slug": slug,
                            "path": str(source_path.resolve()),
                        }
                    )
                    continue
                if market_id_from_slug(row_slug) != market_id:
                    evidence_blockers.append(
                        {
                            "code": "captured_feature_row_market_mismatch",
                            "market_id": market_id,
                            "target_date": target_text,
                            "snapshot_id": row.get("snapshot_id"),
                            "event_slug": row_slug,
                        }
                    )
                    continue
                try:
                    hour = int(row.get("cutoff_hour"))
                except (TypeError, ValueError):
                    evidence_blockers.append(
                        {
                            "code": "captured_feature_row_cutoff_invalid",
                            "market_id": market_id,
                            "target_date": target_text,
                            "snapshot_id": row.get("snapshot_id"),
                            "cutoff_hour": row.get("cutoff_hour"),
                        }
                    )
                    continue
                if hour not in EXPECTED_CUTOFF_HOURS:
                    ignored_out_of_scope_rows += 1
                    continue
                snapshot_id = str(row.get("snapshot_id") or "").strip()
                if not snapshot_id:
                    evidence_blockers.append(
                        {
                            "code": "captured_feature_row_snapshot_id_missing",
                            "market_id": market_id,
                            "target_date": target_text,
                            "cutoff_hour": hour,
                        }
                    )
                    continue
                if snapshot_id in duplicate_feature_ids:
                    continue
                identity = (market_id, target_text, snapshot_id)
                if identity in seen_snapshot_ids:
                    evidence_blockers.append(
                        {
                            "code": "captured_feature_row_duplicate",
                            "market_id": market_id,
                            "target_date": target_text,
                            "snapshot_id": snapshot_id,
                        }
                    )
                    continue
                seen_snapshot_ids.add(identity)

                if expected_artifact is None:
                    # The serving artifact failure is already an evidence blocker;
                    # no row can be safely interpreted without its trained surface.
                    continue
                binding = bindings.get(snapshot_id)
                if binding is None:
                    binding_reason = "model_identity_missing"
                elif binding.get("error"):
                    binding_reason = str(binding["error"])
                else:
                    observed_sha256 = str(binding.get("sha256") or "").casefold()
                    observed_hgb_sha256s.add(observed_sha256)
                    binding_reason = (
                        "hgb_sha256_mismatch"
                        if not release_bound_mode
                        and observed_sha256 != expected_artifact_sha256
                        else ""
                    )
                if not binding_reason and release_bound_mode:
                    release_binding = release_bindings.get(snapshot_id)
                    if release_binding is None:
                        binding_reason = "release_lineage_missing"
                    elif release_binding.get("error"):
                        binding_reason = str(release_binding["error"])
                    elif release_binding.get("model_identity_payload_sha256") != binding.get(
                        "model_identity_payload_sha256"
                    ):
                        binding_reason = "release_snapshot_model_identity_mismatch"
                    else:
                        observed_release_ids.add(
                            str(release_binding.get("release_id") or "")
                        )
                if binding_reason:
                    unbound_reason_counts[binding_reason] += 1
                    if len(unbound_examples[binding_reason]) < 5:
                        unbound_examples[binding_reason].append(snapshot_id)
                    continue

                used_rows += 1
                total_by_slice[(market_id, hour)] += 1
                total_by_date_slice[(market_id, target_text, hour)] += 1
                rows_by_date_hour[(market_id, target_text, hour)] += 1
                tracked = set(BASE_FEATURES)
                tracked.update(direct_by_hour.get(hour, set()))
                tracked.update({"wind_group", "cloud_group"})
                for feature in tracked:
                    if _is_populated(row.get(feature)):
                        populated_by_field[(market_id, hour, feature)] += 1
                        populated_by_date_field[
                            (market_id, target_text, hour, feature)
                        ] += 1
                sustained_wind = _finite_number(row.get("wind_speed_kmh"))
                if (
                    sustained_wind is not None
                    and 0.0 <= sustained_wind <= GUST_CALM_MAX_SUSTAINED_WIND_NATIVE
                ):
                    affirmative_calm_by_slice[(market_id, hour)] += 1
                    affirmative_calm_by_date_slice[
                        (market_id, target_text, hour)
                    ] += 1

            unbound_row_count = sum(unbound_reason_counts.values())
            if not release_bound_mode and len(observed_hgb_sha256s) > 1:
                unbound_reason_counts["mixed_hgb_sha256"] += len(observed_hgb_sha256s)
            for reason, count in sorted(unbound_reason_counts.items()):
                evidence_blockers.append(
                    {
                        "code": "captured_model_artifact_identity_unbound",
                        "reason": reason,
                        "market_id": market_id,
                        "target_date": target_text,
                        "feature_path": str(source_path.resolve()),
                        "identity_path": str(snapshot_identity_path.resolve()),
                        "expected_hgb_sha256": expected_artifact_sha256,
                        "observed_hgb_sha256s": sorted(observed_hgb_sha256s),
                        "affected_row_count": count,
                        "example_snapshot_ids": unbound_examples.get(reason, []),
                    }
                )
            capture_files.append(
                {
                    "market_id": market_id,
                    "target_date": target_text,
                    "path": str(source_path.resolve()),
                    "source_kind": source_kind,
                    "sha256": file_sha256,
                    "model_identity_path": str(snapshot_identity_path.resolve()),
                    "model_identity_sha256": identity_sha256,
                    "release_lineage_path": (
                        str(release_lineage_path.resolve()) if release_bound_mode else None
                    ),
                    "release_lineage_sha256": release_lineage_sha256,
                    "expected_hgb_sha256": expected_artifact_sha256 or None,
                    "observed_hgb_sha256s": sorted(observed_hgb_sha256s),
                    "observed_release_ids": sorted(observed_release_ids),
                    "parsed_row_count": len(file_rows),
                    "used_row_count": used_rows,
                    "unbound_row_count": unbound_row_count,
                }
            )

    for market_id in markets:
        for target in dates:
            for hour in EXPECTED_CUTOFF_HOURS:
                count = rows_by_date_hour.get((market_id, target.isoformat(), hour), 0)
                if count == 0:
                    evidence_blockers.append(
                        {
                            "code": "captured_market_date_hour_missing",
                            "market_id": market_id,
                            "target_date": target.isoformat(),
                            "cutoff_hour": hour,
                        }
                    )

    trained_coverage = []
    for market_id in markets:
        for hour in EXPECTED_CUTOFF_HOURS:
            total = total_by_slice.get((market_id, hour), 0)
            for spec in trained.get(market_id, {}).get(hour, []):
                source_populated = populated_by_field.get(
                    (market_id, hour, spec["source_field"]),
                    0,
                )
                trained_coverage.append(
                    _coverage_row(
                        market_id=market_id,
                        target_date=None,
                        cutoff_hour=hour,
                        feature=spec["feature"],
                        source_kind=spec["source_kind"],
                        source_field=spec["source_field"],
                        category=spec["category"],
                        total_count=total,
                        populated_count=source_populated,
                        source_populated_count=(
                            source_populated
                            if spec["source_kind"] == "derived_one_hot"
                            else None
                        ),
                        affirmative_calm_count=affirmative_calm_by_slice.get(
                            (market_id, hour),
                            0,
                        ),
                    )
                )

    trained_daily_coverage = []
    for market_id in markets:
        for target in dates:
            target_text = target.isoformat()
            for hour in EXPECTED_CUTOFF_HOURS:
                total = total_by_date_slice.get((market_id, target_text, hour), 0)
                for spec in trained.get(market_id, {}).get(hour, []):
                    source_populated = populated_by_date_field.get(
                        (market_id, target_text, hour, spec["source_field"]),
                        0,
                    )
                    daily_row = _coverage_row(
                        market_id=market_id,
                        target_date=target_text,
                        cutoff_hour=hour,
                        feature=spec["feature"],
                        source_kind=spec["source_kind"],
                        source_field=spec["source_field"],
                        category=spec["category"],
                        total_count=total,
                        populated_count=source_populated,
                        source_populated_count=(
                            source_populated
                            if spec["source_kind"] == "derived_one_hot"
                            else None
                        ),
                        affirmative_calm_count=affirmative_calm_by_date_slice.get(
                            (market_id, target_text, hour),
                            0,
                        ),
                        require_any_arrival=True,
                    )
                    daily_row["affects_current_verdict"] = False
                    daily_row["verdict_scope"] = "diagnostic_only"
                    trained_daily_coverage.append(daily_row)

    day_groups: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in trained_daily_coverage:
        key = (
            str(row["market_id"]),
            str(row["target_date"]),
            str(row["feature"]),
            str(row["source_kind"]),
            str(row["source_field"]),
            str(row.get("derived_category") or ""),
        )
        group = day_groups.setdefault(
            key,
            {
                "total_count": 0,
                "populated_count": 0,
                "affirmative_calm_count": 0,
                "cutoff_hours": [],
            },
        )
        group["total_count"] += int(row["total_count"])
        group["populated_count"] += int(row["populated_count"])
        group["affirmative_calm_count"] += int(row.get("affirmative_calm_count") or 0)
        group["cutoff_hours"].append(int(row["cutoff_hour"]))

    trained_feature_day_arrival = []
    for key, group in sorted(day_groups.items()):
        market_id, target_text, feature, source_kind, source_field, category = key
        day_row = _coverage_row(
            market_id=market_id,
            target_date=target_text,
            cutoff_hour=None,
            feature=feature,
            source_kind=source_kind,
            source_field=source_field,
            category=category,
            total_count=int(group["total_count"]),
            populated_count=int(group["populated_count"]),
            source_populated_count=(
                int(group["populated_count"])
                if source_kind == "derived_one_hot"
                else None
            ),
            affirmative_calm_count=int(group["affirmative_calm_count"]),
            require_any_arrival=True,
        )
        day_row["cutoff_hours"] = sorted(set(group["cutoff_hours"]))
        day_row["affects_current_verdict"] = target_text == dates[-1].isoformat()
        trained_feature_day_arrival.append(day_row)

    base_coverage = _base_coverage_rows(
        market_ids=markets,
        total_by_slice=total_by_slice,
        populated_by_field=populated_by_field,
    )
    base_summary = _base_feature_summary(base_coverage)
    positive_control = _positive_control(
        market_ids=markets,
        base_rows=base_coverage,
        trained_rows=trained_coverage,
        artifact_identities=artifact_identities,
        requested=require_positive_control,
    )
    if require_positive_control and not positive_control["reproduced"]:
        evidence_blockers.append(
            {
                "code": "established_positive_control_not_reproduced",
                "reference": positive_control["reference"],
            }
        )

    blocking_coverage = [row for row in trained_coverage if row["decision"] == "BLOCK"]
    exempt_coverage = [
        row for row in trained_coverage if row["decision"] == "EXEMPT_ALLOWED_MISSING"
    ]
    diagnostic_blocking_daily_coverage = [
        row for row in trained_daily_coverage if row["decision"] == "BLOCK"
    ]
    all_blocking_day_arrival = [
        row
        for row in trained_feature_day_arrival
        if row["decision"] == "BLOCK"
    ]
    blocking_current_day_arrival = [
        row
        for row in all_blocking_day_arrival
        if row["target_date"] == dates[-1].isoformat()
    ]
    all_exempt_day_arrival = [
        row
        for row in trained_feature_day_arrival
        if row["decision"] == "EXEMPT_ALLOWED_MISSING"
    ]
    exempt_current_day_arrival = [
        row
        for row in all_exempt_day_arrival
        if row["target_date"] == dates[-1].isoformat()
    ]
    status = (
        "BLOCK"
        if evidence_blockers or blocking_coverage or blocking_current_day_arrival
        else "PASS"
    )
    generated = _utc_iso(generated_at)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "model_input_surface_gate",
        "generated_at_utc": generated,
        "artifact_date": dates[-1].isoformat(),
        "status": status,
        "verdict": (
            "BLOCK: at least one trained input missed the window/day arrival "
            "policy or evidence is incomplete"
            if status == "BLOCK"
            else "PASS: every trained input meets both window and daily arrival policy"
        ),
        "mode": "standalone_read_only_no_network_no_model_replay_no_chain_registration",
        "policy": {
            "trained_feature_population_floor": TRAINED_FEATURE_POPULATION_FLOOR,
            "population_floor_owner": (
                "weather.reporting.source_gates.model_input_surface_gate."
                "TRAINED_FEATURE_POPULATION_FLOOR"
            ),
            "window_target_date_count": WINDOW_TARGET_DATE_COUNT,
            "daily_population_rule": (
                "at_least_one artifact-bound arrival per market/date/feature "
                "across its trained cutoff hours; only artifact_date groups affect verdict"
            ),
            "cutoff_hours": list(EXPECTED_CUTOFF_HOURS),
            "market_population": "all registered markets",
            "threshold_cli_override_supported": False,
            "market_cli_override_supported": False,
            "window_size_cli_override_supported": False,
            "legitimately_sparse_trained_features": {
                "wind_gust_kmh": {
                    "rule": "at_least_one_arrival_or_every_row_affirmatively_calm",
                    "calm_max_sustained_wind_native": GUST_CALM_MAX_SUSTAINED_WIND_NATIVE,
                    "native_unit_note": (
                        "legacy wind_speed_kmh is mph in U.S. captured rows and "
                        "km/h in Toronto"
                    ),
                }
            },
            "captured_row_artifact_binding_required": True,
            "base_features": list(BASE_FEATURES),
        },
        "window": {
            "start_date": dates[0].isoformat(),
            "end_date": dates[-1].isoformat(),
            "target_dates": [value.isoformat() for value in dates],
        },
        "serving_binding": serving_binding,
        "serving_artifacts": artifact_identities,
        "capture_inputs": {
            "snapshot_root": str(snapshot_root.resolve()),
            "files": capture_files,
            "used_row_count": sum(total_by_slice.values()),
            "ignored_out_of_scope_row_count": ignored_out_of_scope_rows,
        },
        "summary": {
            "expected_market_count": len(markets),
            "loaded_artifact_market_count": len(trained),
            "expected_market_date_hour_count": (
                len(markets) * len(dates) * len(EXPECTED_CUTOFF_HOURS)
            ),
            "covered_market_date_hour_count": sum(
                1
                for market_id in markets
                for target in dates
                for hour in EXPECTED_CUTOFF_HOURS
                if rows_by_date_hour.get((market_id, target.isoformat(), hour), 0) > 0
            ),
            "trained_feature_cell_count": len(trained_coverage),
            "blocking_trained_feature_cell_count": len(blocking_coverage),
            "exempt_trained_feature_cell_count": len(exempt_coverage),
            "daily_trained_feature_cell_count": len(trained_daily_coverage),
            "diagnostic_blocking_daily_hour_cell_count": len(
                diagnostic_blocking_daily_coverage
            ),
            "trained_feature_day_arrival_cell_count": len(
                trained_feature_day_arrival
            ),
            "blocking_current_day_trained_feature_count": len(
                blocking_current_day_arrival
            ),
            "exempt_current_day_trained_feature_count": len(
                exempt_current_day_arrival
            ),
            "historical_blocking_day_arrival_count": (
                len(all_blocking_day_arrival) - len(blocking_current_day_arrival)
            ),
            "historical_exempt_day_arrival_count": (
                len(all_exempt_day_arrival) - len(exempt_current_day_arrival)
            ),
            "evidence_blocker_count": len(evidence_blockers),
            "base_feature_count": len(BASE_FEATURES),
        },
        "market_ids": list(markets),
        "trained_feature_coverage": trained_coverage,
        "trained_feature_daily_coverage": trained_daily_coverage,
        "trained_feature_day_arrival": trained_feature_day_arrival,
        "base_feature_coverage": base_coverage,
        "base_feature_summary": base_summary,
        "positive_control": positive_control,
        "evidence_blockers": evidence_blockers,
    }
    return payload


def default_output_path(end_date: str | date) -> Path:
    end = date.fromisoformat(str(end_date)) if not isinstance(end_date, date) else end_date
    return DEFAULT_OUTPUT_ROOT / f"model-input-surface-gate-{end.isoformat()}.json"


def write_output(payload: Mapping[str, Any], output_path: str | Path) -> Path:
    return write_json_atomic(output_path, dict(payload), trailing_newline=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--end-date",
        required=True,
        help="Final target date in the fixed three-date coverage window (YYYY-MM-DD)",
    )
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact-root", default=str(DEFAULT_AMBIENT_HGB_ROOT))
    parser.add_argument(
        "--active-release-pointer",
        default=str(DEFAULT_ACTIVE_RELEASE_POINTER),
    )
    parser.add_argument("--releases-root", default=str(DEFAULT_RELEASES_ROOT))
    parser.add_argument(
        "--output",
        default="",
        help="Dated JSON output path; defaults under data/backtest/model_input_surface_gate",
    )
    parser.add_argument(
        "--require-established-positive-control",
        action="store_true",
        help=(
            "Initial proof only: require the exact retained 11-market 93.6--100% "
            "range plus 10-dead-base / Toronto 8-of-29 control. This fails closed "
            "until the retained 11 market IDs are enumerated in a reviewed source."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = evaluate_gate(
        snapshot_root=args.snapshot_root,
        end_date=args.end_date,
        require_positive_control=args.require_established_positive_control,
        artifact_root=args.artifact_root,
        active_release_pointer=args.active_release_pointer,
        releases_root=args.releases_root,
    )
    output_path = Path(args.output) if args.output else default_output_path(args.end_date)
    written = write_output(payload, output_path)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "verdict": payload["verdict"],
                "summary": payload["summary"],
                "core_dead_input_control_reproduced": payload["positive_control"][
                    "core_dead_input_control_reproduced"
                ],
                "full_retained_range_reproduced": payload["positive_control"][
                    "full_retained_range_reproduced_on_this_host"
                ],
                "output": str(written),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_FEATURES",
    "EXPECTED_CUTOFF_HOURS",
    "GUST_CALM_MAX_SUSTAINED_WIND_NATIVE",
    "LEGITIMATELY_SPARSE_TRAINED_FEATURES",
    "ModelInputSurfaceGateError",
    "SCHEMA_VERSION",
    "TRAINED_FEATURE_POPULATION_FLOOR",
    "WINDOW_TARGET_DATE_COUNT",
    "build_parser",
    "default_output_path",
    "evaluate_gate",
    "main",
    "write_output",
]
