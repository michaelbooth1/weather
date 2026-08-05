"""Explicit-only, fail-closed all-market base-model retrain orchestration.

This module is intentionally absent from every scheduler.  It snapshots and
checks the evidence needed by the first fleet base retrain, then can call the
candidate-only per-market fitter only after every named check passes and the
operator supplies ``--execute-fit``.  It never reads the ambient stitched
``forecast_daily.csv`` archive and never writes a release or release pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from weather.market.market_registry import all_specs
from weather.paths import ARTIFACTS_ROOT, DATA_ROOT, REPO_ROOT
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("all_market_base_retrain")
EVIDENCE_MANIFEST_SCHEMA_VERSION = schema_version(
    "all_market_base_retrain_evidence_manifest"
)
PARITY_REPORT_SCHEMA_VERSION = schema_version("train_serve_feature_parity")
REPORT_HASH_FIELD = "payload_sha256"
REGIME_BOUNDARY = date(2026, 7, 31)
BASE_CUTOFF_HOURS = tuple(range(7, 21))
EXPECTED_MARKET_COUNT = 12
EXPECTED_C_MARKETS = 1
EXPECTED_F_MARKETS = 11
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Classes still absent after the late-July seasonal alignment measured by
# -08-25a.  They are requirements of the first-retrain support policy, not a
# claim that estimator.classes_ itself must contain every bucket.
WARM_TAIL_REQUIRED_CLASSES = {
    "dallas": (108,),
    "denver": (101, 102),
    "houston": (103, 104),
    "seattle": (95,),
}


class BaseRetrainContractError(RuntimeError):
    """The all-market base-retrain contract failed closed."""


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _self_hashed(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop(REPORT_HASH_FIELD, None)
    result[REPORT_HASH_FIELD] = _canonical_sha256(result)
    return result


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: str | Path, payload: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, destination)
    return destination


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaseRetrainContractError(f"{label} is unreadable: {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BaseRetrainContractError(f"{label} must be a JSON object: {source}")
    return payload


def _read_bound_json(record: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    path = Path(str(record.get("path") or ""))
    expected = str(record.get("sha256") or "")
    if not SHA256_RE.fullmatch(expected):
        raise BaseRetrainContractError(f"{label} has no valid SHA-256 binding")
    if path.is_symlink() or not path.is_file():
        raise BaseRetrainContractError(f"{label} is missing or is a symlink: {path}")
    actual = _sha256_file(path)
    if actual != expected:
        raise BaseRetrainContractError(
            f"{label} SHA-256 mismatch: expected={expected}, actual={actual}"
        )
    payload = _read_json(path, label=label)
    if _sha256_file(path) != expected:
        raise BaseRetrainContractError(f"{label} changed while it was read: {path}")
    return payload


def _parse_date(value: Any, *, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise BaseRetrainContractError(f"{field} must be an ISO date") from exc


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BaseRetrainContractError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise BaseRetrainContractError(f"{field} must be timezone-aware")
    return parsed


def _gate(name: str, blockers: Sequence[Mapping[str, Any]], **evidence: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": [dict(row) for row in blockers],
        **evidence,
    }


def _live_specs() -> tuple[Any, ...]:
    return tuple(all_specs())


def _artifact_suffix(market_id: str) -> str:
    return "" if market_id == "toronto" else f"_{market_id}"


def candidate_market_outputs(market_id: str) -> dict[str, str]:
    suffix = _artifact_suffix(market_id)
    root = f"markets/{market_id}"
    return {
        "feature_hgb": f"{root}/feature_model_hgb{suffix}.pkl",
        "feature_lr_coefficients": f"{root}/feature_model_coefs{suffix}.json",
        "probability_calibration": f"{root}/probability_calibration{suffix}.json",
        "fit_receipt": f"{root}/fit_receipt.json",
        "fit_report": f"{root}/fit_report.md",
    }


def build_plan(
    *,
    target_date: str,
    training_as_of: str,
    parent_artifact_id: str,
    feature_contract_id: str,
    evidence_manifest: str | Path,
    candidate_dir: str | Path,
    runtime_id: str,
) -> dict[str, Any]:
    specs = _live_specs()
    markets = [
        {
            "market_id": spec.id,
            "unit": spec.unit,
            "outputs": candidate_market_outputs(spec.id),
        }
        for spec in specs
    ]
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "document_type": "plan",
            "status": "DECLARED",
            "invocation": "explicit_only",
            "scheduled": False,
            "registered_task": False,
            "step_name": "all_market_base_retrain",
            "step_count": 1,
            "target_date": str(target_date),
            "training_as_of": str(training_as_of),
            "parent_artifact_id": str(parent_artifact_id),
            "feature_contract_id": str(feature_contract_id),
            "evidence_manifest": str(evidence_manifest),
            "candidate_dir": str(candidate_dir),
            "runtime_id": str(runtime_id),
            "market_count": len(markets),
            "markets": markets,
            "fleet_atomic": True,
            "fit_requires_execute_flag": True,
        }
    )


def _explicit_argument_check(plan: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    required = (
        "target_date",
        "training_as_of",
        "parent_artifact_id",
        "feature_contract_id",
        "evidence_manifest",
        "candidate_dir",
        "runtime_id",
    )
    missing = [name for name in required if not str(plan.get(name) or "").strip()]
    if missing:
        blockers.append(
            {
                "code": "EXPLICIT_ARGUMENT_MISSING",
                "fields": missing,
                "message": "the base retrain has no ambient identity or path defaults",
            }
        )
    for value, field, parser in (
        (plan.get("target_date"), "target_date", _parse_date),
        (plan.get("training_as_of"), "training_as_of", _parse_timestamp),
    ):
        try:
            parser(value, field=field)
        except BaseRetrainContractError as exc:
            blockers.append(
                {"code": f"{field.upper()}_INVALID", "message": str(exc)}
            )
    return _gate("explicit_arguments", blockers)


def _registry_check(plan: Mapping[str, Any]) -> dict[str, Any]:
    specs = _live_specs()
    expected_ids = [spec.id for spec in specs]
    plan_ids = [str(row.get("market_id") or "") for row in plan.get("markets") or []]
    units = [spec.unit for spec in specs]
    blockers: list[dict[str, Any]] = []
    if len(specs) != EXPECTED_MARKET_COUNT:
        blockers.append(
            {
                "code": "LIVE_REGISTRY_MARKET_COUNT",
                "expected": EXPECTED_MARKET_COUNT,
                "actual": len(specs),
                "message": "the live registry is not the required 12-market fleet",
            }
        )
    if len(set(expected_ids)) != len(expected_ids) or plan_ids != expected_ids:
        blockers.append(
            {
                "code": "LIVE_REGISTRY_PLAN_MISMATCH",
                "registry_market_ids": expected_ids,
                "plan_market_ids": plan_ids,
                "message": "the plan is not an exact ordered projection of the live registry",
            }
        )
    if units.count("C") != EXPECTED_C_MARKETS or units.count("F") != EXPECTED_F_MARKETS:
        blockers.append(
            {
                "code": "LIVE_REGISTRY_UNIT_MIX",
                "units": units,
                "message": "the live registry must contain 1 C and 11 F markets",
            }
        )
    if any(len((row.get("outputs") or {})) != 5 for row in plan.get("markets") or []):
        blockers.append(
            {
                "code": "CANDIDATE_OUTPUT_PLAN_INCOMPLETE",
                "message": "each market must declare five candidate-only outputs",
            }
        )
    return _gate(
        "live_registry_fleet",
        blockers,
        market_ids=expected_ids,
        c_market_count=units.count("C"),
        f_market_count=units.count("F"),
    )


def _candidate_output_check(plan: Mapping[str, Any]) -> dict[str, Any]:
    candidate = Path(str(plan.get("candidate_dir") or "")).resolve()
    protected = (
        (ARTIFACTS_ROOT / "releases").resolve(),
        (ARTIFACTS_ROOT / "models").resolve(),
        (ARTIFACTS_ROOT / "calibration").resolve(),
        DATA_ROOT.resolve(),
    )
    blockers: list[dict[str, Any]] = []
    if candidate.exists():
        blockers.append(
            {
                "code": "CANDIDATE_ROOT_EXISTS",
                "path": str(candidate),
                "message": "candidate output must be a new immutable directory",
            }
        )
    for root in protected:
        if candidate == root or candidate.is_relative_to(root):
            blockers.append(
                {
                    "code": "CANDIDATE_ROOT_PROTECTED",
                    "path": str(candidate),
                    "protected_root": str(root),
                    "message": "candidate output overlaps release, global artifact, or data state",
                }
            )
    output_paths = []
    for market in plan.get("markets") or []:
        for relative in (market.get("outputs") or {}).values():
            output = (candidate / str(relative)).resolve()
            output_paths.append(str(output))
            if not output.is_relative_to(candidate):
                blockers.append(
                    {
                        "code": "CANDIDATE_OUTPUT_ESCAPE",
                        "path": str(output),
                        "message": "a planned output escapes the candidate root",
                    }
                )
    if len(output_paths) != len(set(output_paths)):
        blockers.append(
            {
                "code": "CANDIDATE_OUTPUT_COLLISION",
                "message": "two fleet outputs resolve to the same path",
            }
        )
    return _gate(
        "candidate_output_isolation",
        blockers,
        candidate_dir=str(candidate),
        protected_roots=[str(root) for root in protected],
        planned_output_count=len(output_paths),
    )


def _manifest_identity_check(
    plan: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if manifest.get("schema_version") != EVIDENCE_MANIFEST_SCHEMA_VERSION:
        blockers.append(
            {
                "code": "EVIDENCE_MANIFEST_SCHEMA",
                "expected": EVIDENCE_MANIFEST_SCHEMA_VERSION,
                "actual": manifest.get("schema_version"),
                "message": "the evidence manifest schema is unsupported",
            }
        )
    for field in (
        "target_date",
        "training_as_of",
        "parent_artifact_id",
        "feature_contract_id",
        "runtime_id",
    ):
        if manifest.get(field) != plan.get(field):
            blockers.append(
                {
                    "code": "EVIDENCE_PLAN_BINDING_MISMATCH",
                    "field": field,
                    "plan": plan.get(field),
                    "manifest": manifest.get(field),
                    "message": "the evidence manifest and explicit plan differ",
                }
            )
    expected = [spec.id for spec in _live_specs()]
    actual = list((manifest.get("markets") or {}).keys())
    if set(actual) != set(expected) or len(actual) != len(expected):
        blockers.append(
            {
                "code": "EVIDENCE_FLEET_MISMATCH",
                "expected": expected,
                "actual": actual,
                "message": "the evidence manifest is not the exact live fleet",
            }
        )
    return _gate("evidence_manifest_identity", blockers)


def _date_in_season(value: date, season: Mapping[str, Any]) -> bool:
    try:
        start_month, start_day = map(int, season["start"])
        end_month, end_day = map(int, season["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BaseRetrainContractError("forecast manifest season_window is invalid") from exc
    token = (value.month, value.day)
    start = (start_month, start_day)
    end = (end_month, end_day)
    return start <= token <= end if start <= end else token >= start or token <= end


def _seasonal_dates(target: date, years: Sequence[int]) -> list[date]:
    selected: list[date] = []
    for year in sorted(set(int(value) for value in years if int(value) < target.year)):
        try:
            centre = target.replace(year=year)
        except ValueError:
            centre = date(year, target.month, 28)
        selected.extend(centre + timedelta(days=offset) for offset in range(-7, 8))
    return selected


def _cell_key(market_id: str, target_date: Any, cutoff_hour: Any) -> tuple[str, str, int]:
    return market_id, str(target_date), int(cutoff_hour)


def _load_coverage_cells(
    market_id: str,
    market: Mapping[str, Any],
    expected_keys: set[tuple[str, str, int]],
) -> tuple[dict[tuple[str, str, int], dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    record = (market.get("forecast_archive") or {}).get("coverage_manifest")
    if not isinstance(record, Mapping):
        return {}, [
            {
                "code": "FORECAST_MATRIX_MANIFEST_MISSING",
                "market_id": market_id,
                "message": "no hash-bound market/date/cutoff coverage manifest is present",
            }
        ]
    try:
        payload = _read_bound_json(record, label=f"{market_id} forecast coverage manifest")
    except BaseRetrainContractError as exc:
        return {}, [
            {
                "code": "FORECAST_MATRIX_MANIFEST_INVALID",
                "market_id": market_id,
                "message": str(exc),
            }
        ]
    cells: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in payload.get("cells") or []:
        try:
            key = _cell_key(market_id, row["target_date"], row["cutoff_hour"])
        except (KeyError, TypeError, ValueError) as exc:
            blockers.append(
                {
                    "code": "FORECAST_MATRIX_CELL_INVALID",
                    "market_id": market_id,
                    "message": str(exc),
                }
            )
            continue
        if key in cells:
            blockers.append(
                {
                    "code": "FORECAST_MATRIX_CELL_DUPLICATE",
                    "market_id": market_id,
                    "cell": list(key),
                    "message": "the exact coverage matrix contains a duplicate cell",
                }
            )
        cells[key] = dict(row)
    actual_keys = set(cells)
    if actual_keys != expected_keys:
        blockers.append(
            {
                "code": "FORECAST_MATRIX_INCOMPLETE",
                "market_id": market_id,
                "expected_cell_count": len(expected_keys),
                "actual_cell_count": len(actual_keys),
                "missing_cell_count": len(expected_keys - actual_keys),
                "unexpected_cell_count": len(actual_keys - expected_keys),
                "message": "coverage is not the exact expected market/date/cutoff matrix",
            }
        )
    return cells, blockers


def _load_feature_records(
    market_id: str,
    market: Mapping[str, Any],
) -> tuple[dict[tuple[str, str, int], dict[str, Any]], list[dict[str, Any]]]:
    record = market.get("feature_records")
    if not isinstance(record, Mapping):
        return {}, [
            {
                "code": "FEATURE_RECORD_MANIFEST_MISSING",
                "market_id": market_id,
                "message": "no hash-bound feature-record corpus is present",
            }
        ]
    path = Path(str(record.get("path") or ""))
    expected = str(record.get("sha256") or "")
    if (
        not SHA256_RE.fullmatch(expected)
        or path.is_symlink()
        or not path.is_file()
        or _sha256_file(path) != expected
    ):
        return {}, [
            {
                "code": "FEATURE_RECORD_CORPUS_INVALID",
                "market_id": market_id,
                "message": "the feature-record corpus is not an exact hash-bound file",
            }
        ]
    rows: dict[tuple[str, str, int], dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = _cell_key(market_id, row["target_date"], row["cutoff_hour"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                blockers.append(
                    {
                        "code": "FEATURE_RECORD_INVALID",
                        "market_id": market_id,
                        "line": line_number,
                        "message": str(exc),
                    }
                )
                continue
            if key in rows:
                blockers.append(
                    {
                        "code": "FEATURE_RECORD_DUPLICATE",
                        "market_id": market_id,
                        "cell": list(key),
                        "message": "the feature corpus contains a duplicate market/date/cutoff row",
                    }
                )
            rows[key] = row
    if _sha256_file(path) != expected:
        blockers.append(
            {
                "code": "FEATURE_RECORD_CORPUS_CHANGED",
                "market_id": market_id,
                "message": "the feature corpus changed while it was read",
            }
        )
    return rows, blockers


def _forecast_and_pit_checks(
    plan: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    target = _parse_date(plan["target_date"], field="target_date")
    forecast_blockers: list[dict[str, Any]] = []
    pit_blockers: list[dict[str, Any]] = []
    evidence_by_market: dict[str, dict[str, Any]] = {}
    for spec in _live_specs():
        market_id = spec.id
        market = (manifest.get("markets") or {}).get(market_id) or {}
        archive = market.get("forecast_archive") or {}
        source_record = archive.get("source_manifest")
        source_payload: dict[str, Any] = {}
        source_hash = ""
        years: list[int] = []
        seasonal: list[date] = []
        if not isinstance(source_record, Mapping):
            forecast_blockers.append(
                {
                    "code": "FORECAST_SOURCE_MANIFEST_MISSING",
                    "market_id": market_id,
                    "message": "the forecast archive has no hash-bound source manifest",
                }
            )
        else:
            try:
                source_payload = _read_bound_json(
                    source_record, label=f"{market_id} forecast source manifest"
                )
                source_hash = str(source_record.get("sha256") or "")
                years = [int(value) for value in source_payload.get("covered_years") or []]
                seasonal = _seasonal_dates(target, years)
                in_window = [
                    value
                    for value in seasonal
                    if _date_in_season(value, source_payload.get("season_window") or {})
                ]
                if len(in_window) != len(seasonal):
                    forecast_blockers.append(
                        {
                            "code": "FORECAST_SEASON_WINDOW_MISS",
                            "market_id": market_id,
                            "expected_date_count": len(seasonal),
                            "covered_date_count": len(in_window),
                            "season_window": source_payload.get("season_window"),
                            "manifest_sha256": source_hash,
                            "message": "the manifest-backed archive does not cover the target-aligned seasonal dates",
                        }
                    )
            except BaseRetrainContractError as exc:
                forecast_blockers.append(
                    {
                        "code": "FORECAST_SOURCE_MANIFEST_INVALID",
                        "market_id": market_id,
                        "message": str(exc),
                    }
                )
        expected_keys = {
            _cell_key(market_id, value.isoformat(), hour)
            for value in seasonal
            for hour in BASE_CUTOFF_HOURS
        }
        coverage_cells, coverage_errors = _load_coverage_cells(
            market_id, market, expected_keys
        )
        forecast_blockers.extend(coverage_errors)
        feature_rows, feature_errors = _load_feature_records(market_id, market)
        forecast_blockers.extend(feature_errors)
        if feature_rows and set(feature_rows) != expected_keys:
            forecast_blockers.append(
                {
                    "code": "FEATURE_RECORD_MATRIX_INCOMPLETE",
                    "market_id": market_id,
                    "expected_cell_count": len(expected_keys),
                    "actual_cell_count": len(feature_rows),
                    "message": "feature records are not the exact expected market/date/cutoff matrix",
                }
            )
        if coverage_cells and feature_rows:
            for key in sorted(expected_keys & set(coverage_cells) & set(feature_rows)):
                cell = coverage_cells[key]
                record = feature_rows[key]
                provenance = record.get("forecast_provenance") or {}
                if (
                    provenance.get("source_manifest_sha256") != source_hash
                    or provenance.get("matrix_cell_sha256")
                    != cell.get("matrix_cell_sha256")
                ):
                    forecast_blockers.append(
                        {
                            "code": "FEATURE_FORECAST_PROVENANCE_MISMATCH",
                            "market_id": market_id,
                            "cell": list(key),
                            "message": "feature-record provenance does not match the manifest-backed forecast cell",
                        }
                    )
        if not coverage_cells:
            pit_blockers.append(
                {
                    "code": "PIT_COVERAGE_EVIDENCE_MISSING",
                    "market_id": market_id,
                    "message": "point-in-time issue evidence is unavailable",
                }
            )
        for key, row in sorted(coverage_cells.items()):
            try:
                cutoff = _parse_timestamp(row.get("cutoff_at"), field="cutoff_at")
                issue = _parse_timestamp(row.get("issue_time"), field="issue_time")
                available = _parse_timestamp(row.get("available_at"), field="available_at")
                if issue > cutoff or available > cutoff:
                    raise BaseRetrainContractError("forecast evidence was not known by cutoff")
                if row.get("point_in_time") is not True:
                    raise BaseRetrainContractError("point_in_time is not exact true")
                if row.get("provenance_state") != "verified":
                    raise BaseRetrainContractError("forecast provenance is not verified")
                if str(row.get("issue_identity") or "").lower() in {"", "stitched"}:
                    raise BaseRetrainContractError("forecast issue identity is empty or stitched")
                if row.get("source_manifest_sha256") != source_hash:
                    raise BaseRetrainContractError("forecast cell is not bound to the source manifest")
            except BaseRetrainContractError as exc:
                pit_blockers.append(
                    {
                        "code": "PIT_FORECAST_CELL_INVALID",
                        "market_id": market_id,
                        "cell": list(key),
                        "message": str(exc),
                    }
                )
        if not feature_rows:
            pit_blockers.append(
                {
                    "code": "PIT_FEATURE_RECORD_BINDING_MISSING",
                    "market_id": market_id,
                    "message": "the trainer has no PIT-bound feature-record corpus",
                }
            )
        evidence_by_market[market_id] = {
            "source_manifest_sha256": source_hash,
            "expected_date_count": len(seasonal),
            "expected_cell_count": len(expected_keys),
            "coverage_cell_count": len(coverage_cells),
            "feature_record_count": len(feature_rows),
            "feature_rows": feature_rows,
        }
    return (
        _gate("forecast_archive_coverage", forecast_blockers),
        _gate("point_in_time_forecast_binding", pit_blockers),
        evidence_by_market,
    )


def _parity_check(manifest: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    record = manifest.get("train_serve_parity")
    payload: dict[str, Any] = {}
    if not isinstance(record, Mapping):
        blockers.append(
            {
                "code": "PARITY_REPORT_MISSING",
                "message": "the retrain has no hash-bound train/serve parity report",
            }
        )
    else:
        try:
            payload = _read_bound_json(record, label="train/serve parity report")
            if payload.get("schema_version") != PARITY_REPORT_SCHEMA_VERSION:
                raise BaseRetrainContractError("parity report schema is unsupported")
            if payload.get("status") != "PASS":
                summary = payload.get("summary") or {}
                blockers.append(
                    {
                        "code": "TRAIN_SERVE_PARITY_BLOCK",
                        "blocking_finding_count": summary.get("blocking_finding_count"),
                        "coverage_blocker_count": summary.get("coverage_blocker_count"),
                        "message": "the field-level train/serve parity gate is not exact PASS",
                    }
                )
            expected = [spec.id for spec in _live_specs()]
            coverage = payload.get("coverage") or {}
            expected_market_ids = list(coverage.get("expected_market_ids") or [])
            full_schema_market_ids = list(coverage.get("full_schema_market_ids") or [])
            if (
                set(expected_market_ids) != set(expected)
                or len(expected_market_ids) != len(expected)
                or set(full_schema_market_ids) != set(expected)
                or len(full_schema_market_ids) != len(expected)
            ):
                blockers.append(
                    {
                        "code": "TRAIN_SERVE_PARITY_FLEET_COVERAGE",
                        "message": "the parity report does not cover the full live fleet and schema",
                    }
                )
        except BaseRetrainContractError as exc:
            blockers.append(
                {"code": "PARITY_REPORT_INVALID", "message": str(exc)}
            )
    return _gate(
        "train_serve_feature_parity",
        blockers,
        report_status=payload.get("status"),
        report_summary=payload.get("summary") or {},
    )


def _class_support_check(
    manifest: Mapping[str, Any],
    evidence_by_market: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    evidence = []
    for spec in _live_specs():
        market = (manifest.get("markets") or {}).get(spec.id) or {}
        support = market.get("serving_support")
        required = list(WARM_TAIL_REQUIRED_CLASSES.get(spec.id, ()))
        row = {
            "market_id": spec.id,
            "unit": spec.unit,
            "required_warm_tail_classes": required,
            "declared_support": support,
        }
        evidence.append(row)
        if not isinstance(support, Mapping):
            blockers.append(
                {
                    "code": "SERVING_SUPPORT_UNDECLARED",
                    "market_id": spec.id,
                    "required_warm_tail_classes": required,
                    "message": "serving support is not declared separately from model.classes_",
                }
            )
            continue
        try:
            values = [int(value) for value in support.get("values") or []]
            if not values or values != list(range(min(values), max(values) + 1)):
                raise BaseRetrainContractError("serving support is not a contiguous native range")
            if support.get("unit") != spec.unit:
                raise BaseRetrainContractError("serving support unit is not the market native unit")
            if support.get("source") != "declared_separate_from_model_classes":
                raise BaseRetrainContractError("serving support is not explicitly separate from estimator classes")
            feature_rows = (evidence_by_market.get(spec.id) or {}).get("feature_rows") or {}
            label_values = [
                int(row["final_bucket"])
                for row in feature_rows.values()
                if row.get("final_bucket") is not None
            ]
            forecast_values = [
                float(row["forecast_high"])
                for row in feature_rows.values()
                if row.get("forecast_high") is not None
            ]
            if not label_values:
                raise BaseRetrainContractError("support has no bound training labels")
            margin = 2 if spec.unit == "C" else 4
            minimum_upper = max(
                max(label_values),
                math.ceil(max(forecast_values)) if forecast_values else max(label_values),
            ) + margin
            if min(values) != min(label_values) or max(values) < minimum_upper:
                raise BaseRetrainContractError(
                    "serving support does not cover the bound labels and cutoff-valid forecast plus native margin"
                )
            missing_required = sorted(set(required) - set(values))
            if missing_required:
                raise BaseRetrainContractError(
                    f"required warm-tail classes are absent: {missing_required}"
                )
            model_classes = {int(value) for value in support.get("model_classes") or []}
            if not model_classes.issubset(set(values)):
                raise BaseRetrainContractError("model classes escape the declared serving support")
        except (BaseRetrainContractError, TypeError, ValueError) as exc:
            blockers.append(
                {
                    "code": "SERVING_SUPPORT_INVALID",
                    "market_id": spec.id,
                    "required_warm_tail_classes": required,
                    "message": str(exc),
                }
            )
    return _gate("class_support", blockers, markets=evidence)


def _calibration_check(manifest: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    evidence = []
    for spec in _live_specs():
        market = (manifest.get("markets") or {}).get(spec.id) or {}
        calibration = market.get("candidate_calibration")
        incumbent = market.get("incumbent_calibration") or {}
        evidence.append(
            {
                "market_id": spec.id,
                "candidate_calibration": calibration,
                "incumbent_generated_at": incumbent.get("generated_at"),
                "incumbent_sha256": incumbent.get("sha256"),
                "incumbent_components": incumbent.get("components") or {},
            }
        )
        if not isinstance(calibration, Mapping):
            blockers.append(
                {
                    "code": "CANDIDATE_OOF_CALIBRATION_UNDECLARED",
                    "market_id": spec.id,
                    "incumbent_generated_at": incumbent.get("generated_at"),
                    "message": "candidate-specific blocked-OOF recalibration is not declared",
                }
            )
            continue
        if (
            calibration.get("mode") != "candidate_specific_blocked_oof"
            or calibration.get("inherit_incumbent") is not False
            or calibration.get("bind_to_candidate_fit_receipt") is not True
        ):
            blockers.append(
                {
                    "code": "STALE_CALIBRATOR_INHERITANCE",
                    "market_id": spec.id,
                    "incumbent_generated_at": incumbent.get("generated_at"),
                    "message": "a changed base would inherit or fail to bind candidate-specific calibration",
                }
            )
    return _gate("candidate_specific_calibration", blockers, markets=evidence)


def _regime_boundary_check(
    evidence_by_market: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    evidence = []
    fleet_regimes: set[str] = set()
    fleet_code_identities: set[str] = set()
    for spec in _live_specs():
        rows = (evidence_by_market.get(spec.id) or {}).get("feature_rows") or {}
        regimes: set[str] = set()
        code_identities: set[str] = set()
        artifact_hashes: set[str] = set()
        for row in rows.values():
            regime = str(row.get("artifact_regime_id") or "")
            code_identity = str(row.get("code_identity_sha256") or "")
            artifact_hash = str(row.get("source_artifact_sha256") or "")
            if regime:
                regimes.add(regime)
                fleet_regimes.add(regime)
            if code_identity:
                code_identities.add(code_identity)
                fleet_code_identities.add(code_identity)
            if artifact_hash:
                artifact_hashes.add(artifact_hash)
        evidence.append(
            {
                "market_id": spec.id,
                "record_count": len(rows),
                "artifact_regime_ids": sorted(regimes),
                "code_identity_sha256s": sorted(code_identities),
                "source_artifact_sha256_count": len(artifact_hashes),
            }
        )
        if not rows:
            blockers.append(
                {
                    "code": "ARTIFACT_REGIME_PROVENANCE_MISSING",
                    "market_id": spec.id,
                    "boundary": REGIME_BOUNDARY.isoformat(),
                    "message": "feature records carry no artifact provenance",
                }
            )
        elif len(regimes) != 1 or len(code_identities) != 1 or not artifact_hashes:
            blockers.append(
                {
                    "code": "ARTIFACT_REGIME_MIXED",
                    "market_id": spec.id,
                    "boundary": REGIME_BOUNDARY.isoformat(),
                    "artifact_regime_ids": sorted(regimes),
                    "code_identity_sha256s": sorted(code_identities),
                    "message": "training records mix or omit artifact provenance across the rows[-1] boundary",
                }
            )
    if len(fleet_regimes) > 1 or len(fleet_code_identities) > 1:
        blockers.append(
            {
                "code": "FLEET_ARTIFACT_REGIME_MIXED",
                "boundary": REGIME_BOUNDARY.isoformat(),
                "artifact_regime_ids": sorted(fleet_regimes),
                "code_identity_sha256s": sorted(fleet_code_identities),
                "message": "the fleet corpus is not one artifact-provenance regime",
            }
        )
    return _gate(
        "artifact_regime_boundary",
        blockers,
        boundary=REGIME_BOUNDARY.isoformat(),
        boundary_meaning="artifact_provenance_not_target_date_age",
        markets=evidence,
    )


def evaluate_preflight(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
) -> dict[str, Any]:
    """Evaluate all independent gates; never stop after the first blocker."""

    forecast, pit, evidence_by_market = _forecast_and_pit_checks(plan, manifest)
    checks = [
        _explicit_argument_check(plan),
        _registry_check(plan),
        _candidate_output_check(plan),
        _manifest_identity_check(plan, manifest),
        forecast,
        pit,
        _parity_check(manifest),
        _class_support_check(manifest, evidence_by_market),
        _calibration_check(manifest),
        _regime_boundary_check(evidence_by_market),
        _gate(
            "fleet_atomicity",
            [],
            required_market_count=EXPECTED_MARKET_COUNT,
            required_outputs_per_market=5,
            partial_fleet_releasable=False,
        ),
    ]
    blockers = [
        blocker
        for check in checks
        for blocker in check.get("blockers") or []
    ]
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "document_type": "preflight",
            "status": "PASS" if not blockers else "BLOCK",
            "fit_authorized": not blockers,
            "target_date": plan.get("target_date"),
            "training_as_of": plan.get("training_as_of"),
            "parent_artifact_id": plan.get("parent_artifact_id"),
            "feature_contract_id": plan.get("feature_contract_id"),
            "runtime_id": plan.get("runtime_id"),
            "candidate_dir": plan.get("candidate_dir"),
            "evidence_manifest_sha256": manifest_sha256,
            "checks": checks,
            "blocker_count": len(blockers),
            "blockers": blockers,
            "ambient_forecast_daily_reachable": False,
            "scheduled": False,
            "release_path_reachable": False,
        }
    )


def _find_generated_at(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("generated_at_utc", "generated_at", "trained_at"):
            if value.get(key):
                return str(value[key])
        for child in value.values():
            found = _find_generated_at(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_generated_at(child)
            if found:
                return found
    return None


def _file_identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256_file(path) if path.is_file() else None,
        "bytes": path.stat().st_size if path.is_file() else None,
        "exists": path.is_file(),
    }


def snapshot_current_evidence(
    *,
    target_date: str,
    training_as_of: str,
    data_root: str | Path,
    artifact_root: str | Path,
    parity_report: str | Path,
    runtime_id: str,
) -> dict[str, Any]:
    """Snapshot current production evidence without reading feature data or fitting."""

    _parse_date(target_date, field="target_date")
    _parse_timestamp(training_as_of, field="training_as_of")
    data = Path(data_root).resolve()
    artifacts = Path(artifact_root).resolve()
    parity = Path(parity_report).resolve()
    markets: dict[str, Any] = {}
    parent_rows = []
    for spec in _live_specs():
        suffix = spec.artifact_suffix
        hgb = artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl"
        lr = artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json"
        calibration = artifacts / "calibration" / f"probability_calibration{suffix}.json"
        weights = artifacts / "calibration" / f"calibrated_weights{suffix}.json"
        late_day = artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json"
        source_manifest = data / "forecast_history" / spec.icao.lower() / "manifest.json"
        incumbent_payload = (
            _read_json(calibration, label=f"{spec.id} incumbent calibration")
            if calibration.is_file()
            else {}
        )
        hgb_identity = _file_identity(hgb)
        lr_identity = _file_identity(lr)
        calibration_identity = _file_identity(calibration)
        incumbent_components = {}
        for component_name, component_path in (
            ("calibrated_weights", weights),
            ("feature_lr", lr),
            ("late_day", late_day),
            ("probability_calibration", calibration),
        ):
            payload = (
                _read_json(component_path, label=f"{spec.id} {component_name}")
                if component_path.is_file() and component_path.suffix == ".json"
                else {}
            )
            incumbent_components[component_name] = {
                **_file_identity(component_path),
                "generated_at": _find_generated_at(payload),
            }
        parent_rows.append(
            {
                "market_id": spec.id,
                "unit": spec.unit,
                "hgb_sha256": hgb_identity.get("sha256"),
                "lr_sha256": lr_identity.get("sha256"),
                "calibration_sha256": calibration_identity.get("sha256"),
            }
        )
        markets[spec.id] = {
            "unit": spec.unit,
            "parent_hgb": hgb_identity,
            "parent_lr": lr_identity,
            "forecast_archive": {
                "source_manifest": _file_identity(source_manifest),
                "coverage_manifest": None,
            },
            # Intentionally do not make ambient forecast_daily.csv reachable.
            "feature_records": None,
            "serving_support": None,
            "incumbent_calibration": {
                **calibration_identity,
                "generated_at": _find_generated_at(incumbent_payload),
                "components": incumbent_components,
            },
            "candidate_calibration": None,
            "artifact_regime": None,
        }
    parent_identity_sha256 = _canonical_sha256(parent_rows)
    parent_artifact_id = "tracked-base-" + parent_identity_sha256[:16]
    feature_contract_id = "tracked-parent-feature-contract-" + parent_identity_sha256[:16]
    return _self_hashed(
        {
            "schema_version": EVIDENCE_MANIFEST_SCHEMA_VERSION,
            "document_type": "evidence_manifest",
            "status": "EVIDENCE_SNAPSHOT_NOT_AUTHORIZATION",
            "target_date": target_date,
            "training_as_of": training_as_of,
            "parent_artifact_id": parent_artifact_id,
            "feature_contract_id": feature_contract_id,
            "runtime_id": runtime_id,
            "artifact_regime_boundary": REGIME_BOUNDARY.isoformat(),
            "markets": markets,
            "train_serve_parity": _file_identity(parity),
            "ambient_forecast_daily_included": False,
        }
    )


def _load_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    source = Path(path)
    expected = _sha256_file(source)
    payload = _read_json(source, label="base-retrain evidence manifest")
    embedded = str(payload.get(REPORT_HASH_FIELD) or "")
    unhashed = dict(payload)
    unhashed.pop(REPORT_HASH_FIELD, None)
    if embedded != _canonical_sha256(unhashed):
        raise BaseRetrainContractError("evidence manifest self-hash is invalid")
    if _sha256_file(source) != expected:
        raise BaseRetrainContractError("evidence manifest changed while it was read")
    return payload, expected


def _parent_payloads(market: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    hgb_record = market.get("parent_hgb") or {}
    lr_record = market.get("parent_lr") or {}
    hgb_path = Path(str(hgb_record.get("path") or ""))
    lr_path = Path(str(lr_record.get("path") or ""))
    if _sha256_file(hgb_path) != hgb_record.get("sha256"):
        raise BaseRetrainContractError(f"parent HGB identity changed: {hgb_path}")
    with hgb_path.open("rb") as handle:
        hgb = pickle.load(handle)  # noqa: S301 - exact hash-bound local artifact
    if _sha256_file(hgb_path) != hgb_record.get("sha256"):
        raise BaseRetrainContractError(f"parent HGB changed while read: {hgb_path}")
    lr = _read_bound_json(lr_record, label="parent LR artifact")
    return hgb, lr


def _execute_fleet(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    market_fitter: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    candidate = Path(str(plan["candidate_dir"])).resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{candidate.name}.staging-",
            dir=str(candidate.parent),
        )
    )
    results: list[dict[str, Any]] = []
    try:
        for spec in _live_specs():
            market = manifest["markets"][spec.id]
            records, errors = _load_feature_records(spec.id, market)
            if errors or not records:
                raise BaseRetrainContractError(
                    f"{spec.id} feature records failed after preflight: {errors}"
                )
            parent_hgb, parent_lr = _parent_payloads(market)
            outputs = candidate_market_outputs(spec.id)
            result = dict(
                market_fitter(
                    market_id=spec.id,
                    unit=spec.unit,
                    target_date=str(plan["target_date"]),
                    parent_release_id=str(plan["parent_artifact_id"]),
                    training_as_of=str(plan["training_as_of"]),
                    feature_contract_id=str(plan["feature_contract_id"]),
                    runtime_id=str(plan["runtime_id"]),
                    corpus_manifest_sha256=manifest_sha256,
                    records=[records[key] for key in sorted(records)],
                    parent_hgb=parent_hgb,
                    parent_lr=parent_lr,
                    hgb_path=staging / outputs["feature_hgb"],
                    lr_path=staging / outputs["feature_lr_coefficients"],
                    probability_calibration_path=staging / outputs["probability_calibration"],
                    receipt_path=staging / outputs["fit_receipt"],
                    report_path=staging / outputs["fit_report"],
                )
            )
            if result.get("status") != "PASS" or len(result.get("outputs") or {}) != 5:
                raise BaseRetrainContractError(
                    f"{spec.id} did not produce the complete five-output candidate contract"
                )
            calibration_path = staging / outputs["probability_calibration"]
            calibration = _read_json(
                calibration_path, label=f"{spec.id} candidate calibration"
            )
            if (
                ((calibration.get("exact_distribution") or {}).get("fit_scope"))
                != "candidate_blocked_oof"
            ):
                raise BaseRetrainContractError(
                    f"{spec.id} candidate calibration is not blocked-OOF bound"
                )
            if _sha256_file(calibration_path) == (
                market.get("incumbent_calibration") or {}
            ).get("sha256"):
                raise BaseRetrainContractError(
                    f"{spec.id} candidate calibration bytes did not change"
                )
            results.append(result)
        if [row.get("market_id") for row in results] != [spec.id for spec in _live_specs()]:
            raise BaseRetrainContractError("the fitted fleet is not the exact live registry")
        fleet_receipt = _self_hashed(
            {
                "schema_version": SCHEMA_VERSION,
                "document_type": "fleet_fit_receipt",
                "status": "PASS",
                "target_date": plan["target_date"],
                "training_as_of": plan["training_as_of"],
                "parent_artifact_id": plan["parent_artifact_id"],
                "runtime_id": plan["runtime_id"],
                "evidence_manifest_sha256": manifest_sha256,
                "market_count": len(results),
                "markets": results,
                "release_created": False,
                "release_pointer_modified": False,
                "scheduled": False,
            }
        )
        _write_json_atomic(staging / "fleet-fit-receipt.json", fleet_receipt)
        os.replace(staging, candidate)
        return fleet_receipt
    except Exception:
        # A partial staging tree is intentionally retained as non-releasable
        # evidence.  The declared final candidate path remains absent.
        raise


def run_base_retrain(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    execute_fit: bool,
    market_fitter: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    preflight = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    if preflight["status"] != "PASS":
        return {"status": "BLOCK", "preflight": preflight, "fit": None}
    if not execute_fit:
        return {
            "status": "BLOCK",
            "preflight": preflight,
            "fit": None,
            "reason": "EXPLICIT_EXECUTE_FIT_REQUIRED",
        }
    if market_fitter is None:
        from weather.calibration.base_model_candidate import fit_market_candidate

        market_fitter = fit_market_candidate
    fitted = _execute_fleet(
        plan=plan,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        market_fitter=market_fitter,
    )
    return {"status": "PASS", "preflight": preflight, "fit": fitted}


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--parent-artifact-id", required=True)
    parser.add_argument("--feature-contract-id", required=True)
    parser.add_argument("--evidence-manifest", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--output", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicit-only all-market base retrain with fail-closed preflight"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-current",
        help="Snapshot current evidence only; never read feature rows or fit",
    )
    inspect_parser.add_argument("--target-date", required=True)
    inspect_parser.add_argument("--training-as-of", required=True)
    inspect_parser.add_argument("--data-root", required=True)
    inspect_parser.add_argument("--artifact-root", required=True)
    inspect_parser.add_argument("--parity-report", required=True)
    inspect_parser.add_argument("--runtime-id", required=True)
    inspect_parser.add_argument("--output", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    _add_plan_arguments(preflight_parser)
    preflight_parser.add_argument("--fail-on-block", action="store_true")

    run_parser = subparsers.add_parser("run")
    _add_plan_arguments(run_parser)
    run_parser.add_argument("--execute-fit", action="store_true", required=True)
    return parser


def _plan_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return build_plan(
        target_date=args.target_date,
        training_as_of=args.training_as_of,
        parent_artifact_id=args.parent_artifact_id,
        feature_contract_id=args.feature_contract_id,
        evidence_manifest=args.evidence_manifest,
        candidate_dir=args.candidate_dir,
        runtime_id=args.runtime_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect-current":
        manifest = snapshot_current_evidence(
            target_date=args.target_date,
            training_as_of=args.training_as_of,
            data_root=args.data_root,
            artifact_root=args.artifact_root,
            parity_report=args.parity_report,
            runtime_id=args.runtime_id,
        )
        _write_json_atomic(Path(args.output), manifest)
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "parent_artifact_id": manifest["parent_artifact_id"],
                    "output": str(Path(args.output)),
                },
                sort_keys=True,
            )
        )
        return 0

    manifest, manifest_sha256 = _load_manifest(args.evidence_manifest)
    plan = _plan_from_args(args)
    if args.command == "preflight":
        result = evaluate_preflight(
            plan=plan,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
        )
        _write_json_atomic(Path(args.output), result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "fit_authorized": result["fit_authorized"],
                    "blocker_count": result["blocker_count"],
                    "output": str(Path(args.output)),
                },
                sort_keys=True,
            )
        )
        return 2 if args.fail_on_block and result["status"] != "PASS" else 0

    result = run_base_retrain(
        plan=plan,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        execute_fit=args.execute_fit,
    )
    _write_json_atomic(Path(args.output), result)
    print(json.dumps({"status": result["status"], "output": args.output}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_CUTOFF_HOURS",
    "BaseRetrainContractError",
    "EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "REGIME_BOUNDARY",
    "SCHEMA_VERSION",
    "WARM_TAIL_REQUIRED_CLASSES",
    "build_parser",
    "build_plan",
    "candidate_market_outputs",
    "evaluate_preflight",
    "main",
    "run_base_retrain",
    "snapshot_current_evidence",
]
