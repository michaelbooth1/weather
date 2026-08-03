"""Fail-closed all-market base-model candidate orchestration.

The command is deliberately explicit and candidate-only.  It cannot infer a
target date, parent, cutoff, corpus, candidate directory, feature contract, or
runtime identity.  All training inputs are manifest/hash bound, and the legacy
global-writing base trainer is not reachable from this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from weather.calibration.base_model_candidate import (
    BaseModelCandidateFitError,
    contiguous_serving_support,
    fit_market_candidate,
    read_hash_bound_records,
)
from weather.calibration.forecast_training_contract import (
    pit_selection_binding_sha256,
    preflight_pit_forecast_training_corpus,
)
from weather.market.market_registry import BUILTIN_SPECS
from weather.operations.release_candidate_contract import (
    SEMANTIC_PATHS,
    _finalize_payload,
    verify_candidate_semantic_contract,
)
from weather.operations.release_manifest import capture_code_identity, create_release
from weather.paths import REPO_ROOT
from weather.release_artifacts import (
    load_active_release_pointer,
    sha256_file,
    validate_release_id,
    verify_release,
)
from weather.release_contract import (
    BASE_MODEL_MARKET_COMPONENT_KINDS,
    RESEARCH_ONLY_CANDIDATE_MODE,
    SEMANTIC_CONTRACT_SCHEMA_VERSION,
)
from weather.schema_registry import schema_version
from weather.sources.forecast_training_corpus import (
    CorpusVerificationError,
    MaterializationBlocked,
)


SCHEMA_VERSION = schema_version("all_market_base_retrain")
CORPUS_MANIFEST_SCHEMA_VERSION = schema_version(
    "all_market_base_retrain_corpus_manifest"
)
EXPECTED_MARKETS = tuple(spec.id for spec in BUILTIN_SPECS)
MARKET_UNITS = {spec.id: spec.unit for spec in BUILTIN_SPECS}
REPLACED_COMPONENTS = frozenset(
    {"feature_hgb", "feature_lr_coefficients", "probability_calibration"}
)
REGENERATED_ROLES = frozenset(
    {
        "base_model_serving_graph",
        "candidate_input_leakage_audit",
        "semantic_serving_contract",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class BaseRetrainContractError(RuntimeError):
    """The all-market base-retrain contract failed closed."""


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
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
    result["payload_sha256"] = _canonical_sha256(result)
    return result


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise BaseRetrainContractError(
            f"immutable candidate file already exists: {path}"
        ) from exc


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaseRetrainContractError(f"{label} is unreadable: {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BaseRetrainContractError(f"{label} must be a JSON object: {source}")
    return payload


def _parse_date(value: Any, *, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise BaseRetrainContractError(f"{field} must be an ISO date") from exc


def _parse_aware_datetime(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BaseRetrainContractError(
            f"{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise BaseRetrainContractError(f"{field} must include a timezone")
    return parsed


def _artifact_suffix(market_id: str) -> str:
    return "" if market_id == "toronto" else f"_{market_id}"


def candidate_market_outputs(candidate_dir: str | Path, market_id: str) -> dict[str, str]:
    root = Path(candidate_dir)
    suffix = _artifact_suffix(market_id)
    return {
        "feature_hgb": f"base_model/{market_id}/feature_model_hgb{suffix}.pkl",
        "feature_lr_coefficients": (
            f"base_model/{market_id}/feature_model_coefs{suffix}.json"
        ),
        "probability_calibration": (
            f"base_model/{market_id}/probability_calibration{suffix}.json"
        ),
        "fit_receipt": f"base_retrain/markets/{market_id}/fit_receipt.json",
        "fit_report": f"base_retrain/markets/{market_id}/fit_report.md",
        "candidate_root": str(root),
    }


def build_plan(
    *,
    target_date: str,
    parent_release_id: str,
    training_as_of: str,
    feature_contract_id: str,
    corpus_manifest: str | Path,
    pit_forecast_corpus_manifest: str | Path,
    candidate_dir: str | Path,
    runtime_id: str,
) -> dict[str, Any]:
    """Return the single scheduler-visible all-market step receipt."""

    candidate_value = str(candidate_dir)
    corpus_value = str(corpus_manifest)
    pit_corpus_value = str(pit_forecast_corpus_manifest)
    markets = []
    for market_id in EXPECTED_MARKETS:
        outputs = candidate_market_outputs(candidate_dir, market_id)
        markets.append(
            {
                "market_id": market_id,
                "unit": MARKET_UNITS[market_id],
                "outputs": {
                    role: relative
                    for role, relative in outputs.items()
                    if role != "candidate_root"
                },
            }
        )
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "document_type": "plan",
            "status": "DECLARED",
            "step_count": 1,
            "step_name": "all_market_base_retrain",
            "target_date": str(target_date),
            "parent_release_id": str(parent_release_id),
            "training_as_of": str(training_as_of),
            "feature_contract_id": str(feature_contract_id),
            "corpus_manifest": corpus_value,
            "pit_forecast_corpus_manifest": pit_corpus_value,
            "candidate_dir": candidate_value,
            "candidate_release_id": (
                Path(candidate_value).name if candidate_value.strip() else ""
            ),
            "runtime_id": str(runtime_id),
            "market_count": len(markets),
            "markets": markets,
            "fleet_atomic": True,
        }
    )


def explicit_argument_gate(plan: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "target_date",
        "parent_release_id",
        "training_as_of",
        "feature_contract_id",
        "corpus_manifest",
        "pit_forecast_corpus_manifest",
        "candidate_dir",
        "runtime_id",
    )
    missing = [field for field in required if not str(plan.get(field) or "").strip()]
    blockers = []
    if missing:
        blockers.append(
            {
                "code": "EXPLICIT_ARGUMENT_MISSING",
                "fields": missing,
                "message": "base retrain has no ambient defaults",
            }
        )
    try:
        _parse_date(plan.get("target_date"), field="target_date")
    except BaseRetrainContractError as exc:
        blockers.append({"code": "TARGET_DATE_INVALID", "message": str(exc)})
    try:
        _parse_aware_datetime(plan.get("training_as_of"), field="training_as_of")
    except BaseRetrainContractError as exc:
        blockers.append({"code": "TRAINING_AS_OF_INVALID", "message": str(exc)})
    try:
        validate_release_id(str(plan.get("parent_release_id") or ""))
        validate_release_id(str(plan.get("candidate_release_id") or ""))
    except Exception as exc:  # release validator supplies the exact reason
        blockers.append({"code": "RELEASE_ID_INVALID", "message": str(exc)})
    return {
        "name": "target_cutoff_and_explicit_arguments",
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
    }


def _protected_roots(repo_root: Path) -> tuple[Path, ...]:
    return (
        repo_root / "artifacts" / "models",
        repo_root / "artifacts" / "calibration",
        repo_root / "artifacts" / "misc",
        repo_root / "data",
    )


def _inventory_path(path: Path, *, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        return [{"label": label, "path": str(path), "exists": False}]
    if path.is_symlink():
        raise BaseRetrainContractError(f"protected path is a symlink: {path}")
    paths = [path] if path.is_file() else sorted(path.rglob("*"))
    rows = []
    for child in paths:
        if child.is_symlink():
            raise BaseRetrainContractError(f"protected inventory contains a symlink: {child}")
        if not child.is_file():
            continue
        rows.append(
            {
                "label": label,
                "path": str(child.resolve()),
                "exists": True,
                "bytes": child.stat().st_size,
                "sha256": sha256_file(child),
            }
        )
    return rows


def protected_state_inventory(
    *,
    repo_root: str | Path,
    active_pointer: str | Path,
    parent_release_dir: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    rows: list[dict[str, Any]] = []
    for protected in _protected_roots(root):
        rows.extend(_inventory_path(protected, label="repository_global"))
    rows.extend(_inventory_path(Path(active_pointer), label="active_pointer"))
    rows.extend(_inventory_path(Path(parent_release_dir), label="parent_release"))
    payload = {"rows": rows, "row_count": len(rows)}
    payload["inventory_sha256"] = _canonical_sha256(payload)
    return payload


def prove_output_isolation(
    *,
    candidate_dir: str | Path,
    repo_root: str | Path,
    active_pointer: str | Path,
    parent_release_dir: str | Path,
    probe: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Write only below the candidate root and prove all protected hashes held."""

    candidate = Path(candidate_dir).resolve()
    before = protected_state_inventory(
        repo_root=repo_root,
        active_pointer=active_pointer,
        parent_release_dir=parent_release_dir,
    )
    if probe is None:
        _write_json_exclusive(
            candidate / "base_retrain" / "output_path_probe.json",
            _self_hashed(
                {
                    "schema_version": SCHEMA_VERSION,
                    "document_type": "output_path_probe",
                    "status": "PASS",
                    "candidate_root": str(candidate),
                }
            ),
        )
    else:
        probe(candidate)
    after = protected_state_inventory(
        repo_root=repo_root,
        active_pointer=active_pointer,
        parent_release_dir=parent_release_dir,
    )
    changed = before["inventory_sha256"] != after["inventory_sha256"]
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "document_type": "output_isolation",
            "status": "BLOCK" if changed else "PASS",
            "candidate_root": str(candidate),
            "before_inventory_sha256": before["inventory_sha256"],
            "after_inventory_sha256": after["inventory_sha256"],
            "protected_row_count": before["row_count"],
            "outside_write_detected": changed,
        }
    )


def _feature_contract_id(markets: Mapping[str, Any]) -> str:
    payload = {
        market_id: {
            hour: list(row["feature_names"])
            for hour, row in sorted(market["hours"].items())
        }
        for market_id, market in sorted(markets.items())
    }
    return "sha256:" + _canonical_sha256(payload)


def load_parent_contract(
    *,
    parent_release_id: str,
    releases_root: str | Path,
    active_pointer: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Verify the active parent and extract its exact 84-role base contract."""

    pointer = load_active_release_pointer(active_pointer)
    if pointer["active_release_id"] != parent_release_id:
        raise BaseRetrainContractError(
            "explicit parent release does not match the active pointer"
        )
    parent_dir = Path(releases_root).resolve() / parent_release_id
    verified = verify_release(
        parent_dir,
        repo_root=repo_root,
        expected_manifest_sha256=pointer["active_manifest_sha256"],
        check_runtime=False,
    )
    manifest = verified["manifest"]
    inventory = manifest["artifacts"]["inventory"]
    role_rows = {
        str(row["role"]): dict(row)
        for row in inventory
        if row.get("declared") and row.get("role")
    }
    graph_row = role_rows.get("base_model_serving_graph")
    semantic_row = role_rows.get("semantic_serving_contract")
    if not graph_row or not semantic_row:
        raise BaseRetrainContractError("parent release has no bound base graph")
    graph = _read_json(parent_dir / graph_row["path"], label="parent base graph")
    semantic = _read_json(
        parent_dir / semantic_row["path"], label="parent semantic contract"
    )
    if semantic.get("candidate_mode") != RESEARCH_ONLY_CANDIDATE_MODE:
        raise BaseRetrainContractError(
            "base-only child release requires a research-only parent; production "
            "qualification cannot be reused after changing 36 base components"
        )
    graph_markets = graph.get("markets")
    if not isinstance(graph_markets, Mapping) or tuple(sorted(graph_markets)) != tuple(
        sorted(EXPECTED_MARKETS)
    ):
        raise BaseRetrainContractError(
            "parent base graph does not contain the exact 12-market fleet"
        )
    base_roles = {
        str(component["role"])
        for market in graph_markets.values()
        for component in (market.get("components") or {}).values()
        if isinstance(component, Mapping)
    }
    if len(base_roles) != len(EXPECTED_MARKETS) * len(BASE_MODEL_MARKET_COMPONENT_KINDS):
        raise BaseRetrainContractError(
            f"parent base graph must bind 84 market components, found {len(base_roles)}"
        )
    markets: dict[str, Any] = {}
    for market_id in EXPECTED_MARKETS:
        component_rows = graph_markets[market_id]["components"]
        hgb_role = component_rows["feature_hgb"]["role"]
        lr_role = component_rows["feature_lr_coefficients"]["role"]
        with (parent_dir / role_rows[hgb_role]["path"]).open("rb") as handle:
            hgb = pickle.load(handle)  # noqa: S301 - release hash verified above
        lr = _read_json(
            parent_dir / role_rows[lr_role]["path"],
            label=f"parent LR {market_id}",
        )
        hours = {}
        for hour, hgb_row in hgb.items():
            if not str(hour).isdigit():
                continue
            lr_row = lr.get(str(hour))
            if not isinstance(hgb_row, Mapping) or not isinstance(lr_row, Mapping):
                raise BaseRetrainContractError(
                    f"parent HGB/LR hour contract is incomplete: {market_id}.{hour}"
                )
            hgb_names = [str(value) for value in hgb_row.get("feature_names") or []]
            lr_names = [str(value) for value in lr_row.get("feature_names") or []]
            if not hgb_names or hgb_names != lr_names:
                raise BaseRetrainContractError(
                    f"parent HGB/LR feature order differs: {market_id}.{hour}"
                )
            hours[str(hour)] = {"feature_names": hgb_names}
        markets[market_id] = {
            "unit": MARKET_UNITS[market_id],
            "hours": hours,
            "hgb": hgb,
            "lr": lr,
            "components": component_rows,
        }
    return {
        "status": "PASS",
        "parent_release_id": parent_release_id,
        "parent_release_dir": str(parent_dir),
        "parent_manifest_sha256": manifest["manifest_sha256"],
        "manifest": manifest,
        "inventory": inventory,
        "role_rows": role_rows,
        "graph": graph,
        "semantic": semantic,
        "markets": markets,
        "feature_contract_id": _feature_contract_id(markets),
        "base_market_component_role_count": len(base_roles),
    }


def _season_distance(local_date: date, target_date: date) -> int:
    reference_year = 2000
    local_reference = local_date.replace(year=reference_year)
    target_reference = target_date.replace(year=reference_year)
    return abs((local_reference - target_reference).days)


def _gate(name: str, blockers: Sequence[Mapping[str, Any]], **evidence: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": [dict(row) for row in blockers],
        **evidence,
    }


def _required_pit_selection_keys(
    manifest: Mapping[str, Any],
    parent: Mapping[str, Any],
) -> tuple[tuple[str, str, int], ...]:
    markets = manifest.get("markets")
    if not isinstance(markets, Mapping):
        return ()
    keys = set()
    for market_id in EXPECTED_MARKETS:
        market = markets.get(market_id)
        if not isinstance(market, Mapping):
            continue
        dates = {
            str(row.get("local_date") or "")
            for row in market.get("selected_dates") or []
            if str(row.get("local_date") or "")
        }
        hours = {
            int(hour)
            for hour in ((parent.get("markets") or {}).get(market_id) or {}).get(
                "hours", {}
            )
            if str(hour).isdigit()
        }
        keys.update(
            (market_id, target_date, cutoff_hour)
            for target_date in dates
            for cutoff_hour in hours
        )
    return tuple(sorted(keys))


def _feature_record_pit_binding(
    manifest: Mapping[str, Any],
    parent: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_keys = set(_required_pit_selection_keys(manifest, parent))
    bindings: dict[tuple[str, str, int], dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    markets = manifest.get("markets")
    if not isinstance(markets, Mapping):
        markets = {}
    for market_id in EXPECTED_MARKETS:
        market = markets.get(market_id)
        if not isinstance(market, Mapping):
            continue
        try:
            records = read_hash_bound_records(
                market.get("records_path") or "",
                expected_sha256=str(market.get("records_sha256") or ""),
            )
        except (BaseModelCandidateFitError, OSError, TypeError, ValueError) as exc:
            blockers.append(
                {
                    "code": "PIT_FEATURE_RECORD_UNVERIFIED",
                    "market_id": market_id,
                    "message": str(exc),
                }
            )
            continue
        for record in records:
            try:
                key = (
                    market_id,
                    str(record["target_date"]),
                    int(record["cutoff_hour"]),
                )
            except (KeyError, TypeError, ValueError):
                blockers.append(
                    {
                        "code": "PIT_FEATURE_RECORD_KEY_INVALID",
                        "market_id": market_id,
                        "message": "feature record lacks a valid target date or cutoff hour",
                    }
                )
                continue
            if key not in required_keys:
                blockers.append(
                    {
                        "code": "PIT_FEATURE_RECORD_OUTSIDE_PLAN",
                        "market_id": market_id,
                        "target_date": key[1],
                        "cutoff_hour_local": key[2],
                        "message": "fitted feature record is outside the planned PIT matrix",
                    }
                )
                continue
            if key in bindings:
                blockers.append(
                    {
                        "code": "PIT_FEATURE_RECORD_DUPLICATE",
                        "market_id": market_id,
                        "target_date": key[1],
                        "cutoff_hour_local": key[2],
                        "message": "more than one feature record claims the planned PIT key",
                    }
                )
                continue
            binding = {
                "market_id": market_id,
                "target_date": key[1],
                "cutoff_hour_local": key[2],
                "forecast_high_native": record.get("forecast_high"),
                "temperature_unit": record.get("forecast_pit_temperature_unit"),
                "corpus_id": record.get("forecast_pit_corpus_id"),
                "request_hash": record.get("forecast_pit_request_hash"),
                "raw_response_sha256": record.get(
                    "forecast_pit_raw_response_sha256"
                ),
                "issue_time_utc": record.get("forecast_pit_issue_time_utc"),
                "available_at_utc": record.get("forecast_pit_available_at_utc"),
                "feature_as_of_utc": record.get(
                    "forecast_pit_feature_as_of_utc"
                ),
            }
            missing = [
                field
                for field, value in binding.items()
                if value is None or (isinstance(value, str) and not value.strip())
            ]
            if missing:
                blockers.append(
                    {
                        "code": "PIT_FEATURE_RECORD_PROVENANCE_MISSING",
                        "market_id": market_id,
                        "target_date": key[1],
                        "cutoff_hour_local": key[2],
                        "fields": missing,
                        "message": "feature record lacks explicit PIT corpus provenance",
                    }
                )
                continue
            if binding["temperature_unit"] != MARKET_UNITS[market_id]:
                blockers.append(
                    {
                        "code": "PIT_FEATURE_RECORD_UNIT_MISMATCH",
                        "market_id": market_id,
                        "target_date": key[1],
                        "cutoff_hour_local": key[2],
                        "message": "PIT forecast value is not in the market's native unit",
                    }
                )
                continue
            bindings[key] = binding
    missing_keys = sorted(required_keys - set(bindings))
    if missing_keys:
        blockers.append(
            {
                "code": "PIT_FEATURE_RECORD_MATRIX_INCOMPLETE",
                "missing_count": len(missing_keys),
                "missing": [list(key) for key in missing_keys[:5]],
                "message": "feature records do not cover the planned market/date/cutoff matrix",
            }
        )
    rows = [bindings[key] for key in sorted(bindings)]
    evidence = {
        "required_selection_row_count": len(required_keys),
        "feature_record_selection_row_count": len(rows),
        "feature_record_selection_binding_sha256": (
            pit_selection_binding_sha256(rows) if rows else ""
        ),
    }
    return blockers, evidence


def evaluate_preflight(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    pit_forecast_manifest_sha256: str,
    pit_forecast_preflight: Mapping[str, Any],
    parent: Mapping[str, Any],
    output_isolation: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate every base-retrain table row without trusting summary booleans."""

    checks: list[dict[str, Any]] = [explicit_argument_gate(plan)]
    scheduler_blockers = []
    if plan.get("step_count") != 1 or plan.get("step_name") != "all_market_base_retrain":
        scheduler_blockers.append(
            {"code": "SCHEDULER_STEP_COUNT", "message": "exactly one all-market step is required"}
        )
    if [row.get("market_id") for row in plan.get("markets") or []] != list(EXPECTED_MARKETS):
        scheduler_blockers.append(
            {"code": "SCHEDULER_FLEET", "message": "plan does not name the exact 12-market fleet"}
        )
    if any(len((row.get("outputs") or {})) != 5 for row in plan.get("markets") or []):
        scheduler_blockers.append(
            {"code": "SCHEDULER_OUTPUTS", "message": "plan omits candidate outputs"}
        )
    checks.append(_gate("scheduler_plan", scheduler_blockers, declared_market_count=12))

    parent_blockers = []
    if parent.get("status") != "PASS":
        parent_blockers.append({"code": "PARENT_NOT_VERIFIED", "message": "parent is not exact PASS"})
    if parent.get("base_market_component_role_count") != 84:
        parent_blockers.append(
            {"code": "PARENT_ROLE_COUNT", "message": "parent does not bind all 84 market components"}
        )
    if parent.get("feature_contract_id") != plan.get("feature_contract_id"):
        parent_blockers.append(
            {"code": "FEATURE_CONTRACT_ID_MISMATCH", "message": "explicit feature contract is not the parent contract"}
        )
    checks.append(
        _gate(
            "parent_release",
            parent_blockers,
            verified_component_role_count=parent.get("base_market_component_role_count"),
        )
    )

    target_blockers = []
    for field in ("target_date", "training_as_of", "feature_contract_id", "runtime_id"):
        if manifest.get(field) != plan.get(field):
            target_blockers.append(
                {"code": "MANIFEST_BINDING_MISMATCH", "field": field, "message": "manifest and CLI differ"}
            )
    if manifest.get("schema_version") != CORPUS_MANIFEST_SCHEMA_VERSION:
        target_blockers.append(
            {"code": "CORPUS_SCHEMA", "message": "corpus manifest schema is unsupported"}
        )
    checks.append(_gate("target_cutoff", target_blockers))

    manifest_markets = manifest.get("markets")
    if not isinstance(manifest_markets, Mapping):
        manifest_markets = {}
    target = _parse_date(plan["target_date"], field="target_date")
    training_as_of = _parse_aware_datetime(
        plan["training_as_of"], field="training_as_of"
    )
    wu_blockers = []
    feature_blockers = []
    parity_blockers = []
    sidecar_blockers = []
    support_blockers = []
    for market_id in EXPECTED_MARKETS:
        market = manifest_markets.get(market_id)
        parent_market = (parent.get("markets") or {}).get(market_id) or {}
        if not isinstance(market, Mapping):
            wu_blockers.append(
                {"code": "WU_MARKET_MISSING", "market_id": market_id, "message": "market manifest is absent"}
            )
            continue
        if market.get("unit") != MARKET_UNITS[market_id]:
            wu_blockers.append(
                {"code": "NATIVE_UNIT_MISMATCH", "market_id": market_id, "message": "market unit is not native"}
            )
        selected = market.get("selected_dates") or []
        declared_count = int(market.get("expected_selected_day_count") or -1)
        minimum_count = int(market.get("minimum_selected_day_count") or 1)
        if declared_count != len(selected) or len(selected) < minimum_count:
            wu_blockers.append(
                {"code": "WU_COUNT_MISMATCH", "market_id": market_id, "message": "selected-day counts fail declaration/minimum"}
            )
        records_path = Path(str(market.get("records_path") or ""))
        records_sha = str(market.get("records_sha256") or "")
        if (
            not SHA256_RE.fullmatch(records_sha)
            or records_path.is_symlink()
            or not records_path.is_file()
            or sha256_file(records_path) != records_sha
        ):
            wu_blockers.append(
                {
                    "code": "FEATURE_RECORD_CORPUS_IDENTITY",
                    "market_id": market_id,
                    "message": "feature-record corpus is not an exact hash-bound file",
                }
            )
        selected_dates = []
        for row in selected:
            try:
                local = _parse_date(row.get("local_date"), field="selected local_date")
                selected_dates.append(local.isoformat())
                if local.year >= target.year or _season_distance(local, target) > 7:
                    raise BaseRetrainContractError("selected date is not prior-year target +/-7")
                if not SHA256_RE.fullmatch(str(row.get("daily_sha256") or "")) or not SHA256_RE.fullmatch(
                    str(row.get("hourly_sha256") or "")
                ):
                    raise BaseRetrainContractError("selected source hash is missing")
                if int(row.get("hourly_row_count") or 0) < int(
                    market.get("minimum_hourly_rows_per_day") or 1
                ):
                    raise BaseRetrainContractError("hourly row count is below minimum")
                int(row["label_bucket"])
                cutoff_at = _parse_aware_datetime(row.get("cutoff_at"), field="cutoff_at")
                predictor_at = _parse_aware_datetime(
                    row.get("max_predictor_known_at"), field="max_predictor_known_at"
                )
                if predictor_at > cutoff_at:
                    raise BaseRetrainContractError("post-cutoff predictor is present")
                if cutoff_at > training_as_of:
                    raise BaseRetrainContractError(
                        "selected cutoff is after the explicit training as-of"
                    )
            except (BaseRetrainContractError, KeyError, TypeError, ValueError) as exc:
                wu_blockers.append(
                    {"code": "WU_ROW_INVALID", "market_id": market_id, "message": str(exc)}
                )

        parent_hours = parent_market.get("hours") or {}
        manifest_hours = market.get("feature_names_by_hour") or {}
        for hour, parent_hour in sorted(parent_hours.items()):
            expected_names = list(parent_hour.get("feature_names") or [])
            candidate_names = list(manifest_hours.get(hour) or [])
            if candidate_names != expected_names:
                feature_blockers.append(
                    {"code": "FEATURE_ORDER_DRIFT", "market_id": market_id, "hour": hour, "message": "candidate names are not the frozen parent order"}
                )
        if set(manifest_hours) != set(parent_hours):
            feature_blockers.append(
                {"code": "FEATURE_HOUR_DRIFT", "market_id": market_id, "message": "candidate cutoff hours differ from parent"}
            )
        parent_feature_names = {
            name
            for row in parent_hours.values()
            for name in row.get("feature_names") or []
        }
        all_missing = sorted(set(market.get("all_missing_features") or []) & parent_feature_names)
        live_only = sorted(set(market.get("live_only_features") or []) & parent_feature_names)
        if all_missing:
            feature_blockers.append(
                {"code": "ALL_MISSING_FEATURE", "market_id": market_id, "features": all_missing, "message": "selected parent field is all missing in training"}
            )
        if live_only:
            feature_blockers.append(
                {"code": "LIVE_ONLY_FEATURE", "market_id": market_id, "features": live_only, "message": "selected parent field is live-only"}
            )

        parity_by_field: dict[str, list[Mapping[str, Any]]] = {}
        for sample in market.get("parity_samples") or []:
            parity_by_field.setdefault(str(sample.get("field") or ""), []).append(sample)
        for field in sorted(parent_feature_names):
            samples = parity_by_field.get(field) or []
            if not samples:
                parity_blockers.append(
                    {"code": "PARITY_FIELD_UNPROVEN", "market_id": market_id, "field": field, "message": "no row-level historical/live comparison"}
                )
                continue
            for sample in samples:
                historical = sample.get("historical")
                live = sample.get("live")
                if not isinstance(historical, Mapping) or not isinstance(live, Mapping):
                    parity_blockers.append(
                        {"code": "PARITY_SAMPLE_INVALID", "market_id": market_id, "field": field, "message": "parity sample lacks both builder outputs"}
                    )
                    continue
                compared = ("value", "unit", "category", "missing", "cutoff_behavior")
                mismatches = [key for key in compared if historical.get(key) != live.get(key)]
                if mismatches:
                    parity_blockers.append(
                        {"code": "TRAIN_SERVE_PARITY_MISMATCH", "market_id": market_id, "field": field, "mismatches": mismatches, "historical": {key: historical.get(key) for key in compared}, "live": {key: live.get(key) for key in compared}, "message": "historical/live feature values differ"}
                    )

        for sidecar in market.get("sidecars") or []:
            fields = set(sidecar.get("feature_names") or [])
            missing_metadata = [
                field
                for field in ("schema_version", "generated_at", "logical_horizon", "sha256")
                if not sidecar.get(field)
            ]
            if (
                missing_metadata
                or not SHA256_RE.fullmatch(str(sidecar.get("sha256") or ""))
                or not fields
                or not fields.issubset(parent_feature_names)
                or int(sidecar.get("selected_row_coverage") or 0) != len(selected_dates)
            ):
                sidecar_blockers.append(
                    {"code": "SIDECAR_CONTRACT_INVALID", "market_id": market_id, "sidecar": sidecar.get("name"), "message": "allowed sidecar is not hash/coverage bound"}
                )

        support = market.get("support") or {}
        support_rows = list(support.get("folds") or []) + [support.get("final") or {}]
        if not support_rows or not support.get("folds"):
            support_blockers.append(
                {"code": "FOLD_LOCAL_SUPPORT_MISSING", "market_id": market_id, "message": "fold-local support declarations are required"}
            )
        for support_row in support_rows:
            try:
                expected_support = contiguous_serving_support(
                    support_row.get("label_buckets") or [],
                    support_row.get("cutoff_valid_forecast_highs") or [],
                    unit=MARKET_UNITS[market_id],
                )
                declared_support = [int(value) for value in support_row.get("serving_support") or []]
                if declared_support != expected_support:
                    raise BaseRetrainContractError("support is not contiguous and margin-complete")
                classes = {int(value) for value in support_row.get("model_classes") or []}
                if not classes.issubset(set(declared_support)):
                    raise BaseRetrainContractError("model classes escape declared serving support")
                prior = support_row.get("alpha_smoothed_prior") or {}
                if set(map(int, prior)) != set(declared_support) or any(float(value) <= 0 for value in prior.values()):
                    raise BaseRetrainContractError("alpha-smoothed prior does not represent every class")
            except (BaseRetrainContractError, TypeError, ValueError) as exc:
                support_blockers.append(
                    {"code": "CLASS_SUPPORT_INVALID", "market_id": market_id, "message": str(exc)}
                )

    if set(manifest_markets) != set(EXPECTED_MARKETS):
        wu_blockers.append(
            {"code": "WU_FLEET_MISMATCH", "message": "corpus manifest is not exactly the 12 built-in markets"}
        )
    pit_blockers = []
    if pit_forecast_preflight.get("status") != "PASS":
        pit_blockers.append(
            {
                "code": "PIT_FORECAST_CORPUS_UNVERIFIED",
                "message": str(
                    pit_forecast_preflight.get("error")
                    or "PIT forecast corpus preflight is not exact PASS"
                ),
            }
        )
    expected_preflight_hash = _canonical_sha256(
        {
            key: value
            for key, value in pit_forecast_preflight.items()
            if key != "preflight_sha256"
        }
    )
    if pit_forecast_preflight.get("preflight_sha256") != expected_preflight_hash:
        pit_blockers.append(
            {
                "code": "PIT_FORECAST_PREFLIGHT_IDENTITY",
                "message": "PIT forecast corpus preflight self-hash does not verify",
            }
        )
    try:
        receipt_path = Path(str(pit_forecast_preflight.get("manifest_path") or "")).resolve()
        planned_path = Path(str(plan.get("pit_forecast_corpus_manifest") or "")).resolve()
        path_matches = receipt_path == planned_path
    except (OSError, RuntimeError, ValueError):
        path_matches = False
    if (
        not path_matches
        or pit_forecast_preflight.get("manifest_file_sha256")
        != pit_forecast_manifest_sha256
    ):
        pit_blockers.append(
            {
                "code": "PIT_FORECAST_MANIFEST_IDENTITY",
                "message": "PIT preflight is not bound to the explicit manifest file",
            }
        )
    record_blockers, record_evidence = _feature_record_pit_binding(manifest, parent)
    pit_blockers.extend(record_blockers)
    if record_evidence["required_selection_row_count"] <= 0:
        pit_blockers.append(
            {
                "code": "PIT_FORECAST_SELECTION_EMPTY",
                "message": "planned market/date/cutoff selection is empty",
            }
        )
    if (
        int(pit_forecast_preflight.get("selection_row_count") or -1)
        != record_evidence["required_selection_row_count"]
        or pit_forecast_preflight.get("selection_binding_sha256")
        != record_evidence["feature_record_selection_binding_sha256"]
    ):
        pit_blockers.append(
            {
                "code": "PIT_FORECAST_SELECTION_BINDING_MISMATCH",
                "message": "feature records are not the exact preflighted PIT selection",
            }
        )
    checks.extend(
        [
            _gate("wu_corpus", wu_blockers),
            _gate(
                "pit_forecast_corpus",
                pit_blockers,
                manifest_file_sha256=pit_forecast_manifest_sha256,
                corpus_id=pit_forecast_preflight.get("corpus_id"),
                selection_binding_sha256=pit_forecast_preflight.get(
                    "selection_binding_sha256"
                ),
                **record_evidence,
            ),
            _gate("feature_allowlist", feature_blockers),
            _gate("train_serve_parity", parity_blockers),
            _gate("sidecars", sidecar_blockers),
            _gate("class_support", support_blockers),
            _gate(
                "output_isolation",
                [] if output_isolation.get("status") == "PASS" else [
                    {"code": "OUTPUT_ISOLATION_FAILED", "message": "protected state changed during the dry path probe"}
                ],
                proof=dict(output_isolation),
            ),
            _gate(
                "fleet_atomicity",
                [],
                required_markets=list(EXPECTED_MARKETS),
                required_outputs_per_market=list(REPLACED_COMPONENTS),
                release_before_complete=False,
            ),
        ]
    )
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
            "target_date": plan["target_date"],
            "training_as_of": plan["training_as_of"],
            "parent_release_id": plan["parent_release_id"],
            "feature_contract_id": plan["feature_contract_id"],
            "runtime_id": plan["runtime_id"],
            "corpus_manifest_sha256": manifest_sha256,
            "pit_forecast_corpus_manifest_sha256": pit_forecast_manifest_sha256,
            "pit_forecast_preflight_sha256": pit_forecast_preflight.get(
                "preflight_sha256"
            ),
            "checks": checks,
            "blocker_count": len(blockers),
            "blockers": blockers,
            "fit_authorized": not blockers,
        }
    )


def _validate_candidate_root(
    *, candidate_dir: str | Path, repo_root: str | Path, releases_root: str | Path
) -> Path:
    candidate = Path(candidate_dir).resolve()
    repo = Path(repo_root).resolve()
    releases = Path(releases_root).resolve()
    if candidate.exists():
        raise BaseRetrainContractError(f"candidate directory must be new: {candidate}")
    if candidate == repo or candidate.is_relative_to(repo):
        raise BaseRetrainContractError(
            "candidate directory must be outside the repository/mirror"
        )
    if candidate == releases or candidate.is_relative_to(releases):
        raise BaseRetrainContractError(
            "candidate directory cannot be inside the immutable release store"
        )
    release_dir = releases / candidate.name
    if release_dir.exists():
        raise BaseRetrainContractError(
            f"inactive candidate release already exists: {release_dir}"
        )
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _copy_parent_unchanged(parent: Mapping[str, Any], candidate_dir: Path) -> None:
    parent_dir = Path(parent["parent_release_dir"])
    skipped_roles = set(REGENERATED_ROLES)
    for market_id in EXPECTED_MARKETS:
        components = parent["markets"][market_id]["components"]
        skipped_roles.update(
            components[component]["role"] for component in REPLACED_COMPONENTS
        )
    for row in parent["inventory"]:
        role = str(row.get("role") or "") if row.get("declared") else ""
        if role in skipped_roles:
            continue
        source = parent_dir / row["path"]
        destination = candidate_dir / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise BaseRetrainContractError(
                f"parent copy would overwrite candidate output: {destination}"
            )
        shutil.copy2(source, destination, follow_symlinks=False)
        if sha256_file(destination) != row["sha256"]:
            raise BaseRetrainContractError(
                f"unchanged parent component hash drifted: {role or row['path']}"
            )


def _finalize_candidate_contract(
    *, parent: Mapping[str, Any], candidate_dir: Path, candidate_id: str
) -> dict[str, Any]:
    role_rows = parent["role_rows"]
    graph = json.loads(json.dumps(parent["graph"]))
    for market_id in EXPECTED_MARKETS:
        for component_name in REPLACED_COMPONENTS:
            component = graph["markets"][market_id]["components"][component_name]
            path = candidate_dir / component["path"]
            if not path.is_file() or path.is_symlink():
                raise BaseRetrainContractError(
                    f"fleet output is missing: {market_id}.{component_name}"
                )
            component["sha256"] = sha256_file(path)
    graph.pop("payload_sha256", None)
    graph = _finalize_payload(graph)
    graph_path = candidate_dir / role_rows["base_model_serving_graph"]["path"]
    _write_json_exclusive(graph_path, graph)

    required_role_kinds = dict(parent["semantic"]["required_role_kinds"])
    artifact_rows = {}
    for role, kind in sorted(required_role_kinds.items()):
        if role in {"semantic_serving_contract", "candidate_input_leakage_audit"}:
            continue
        relative = (
            role_rows[role]["path"]
            if role != "base_model_serving_graph"
            else role_rows["base_model_serving_graph"]["path"]
        )
        path = candidate_dir / relative
        if not path.is_file() or path.is_symlink():
            raise BaseRetrainContractError(f"candidate role is missing: {role}")
        artifact_rows[role] = {
            "path": relative,
            "kind": kind,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    parent_audit_row = role_rows["candidate_input_leakage_audit"]
    parent_audit = _read_json(
        Path(parent["parent_release_dir"]) / parent_audit_row["path"],
        label="parent candidate-input audit",
    )
    audit = {
        key: value
        for key, value in parent_audit.items()
        if key not in {"payload_sha256", "input_hashes"}
    }
    audit["input_hashes"] = [
        {"role": role, **artifact_rows[role]}
        for role in sorted(artifact_rows)
        if role != "candidate_input_leakage_audit"
    ]
    audit = _finalize_payload(audit)
    audit_path = candidate_dir / parent_audit_row["path"]
    _write_json_exclusive(audit_path, audit)
    artifact_rows["candidate_input_leakage_audit"] = {
        "path": parent_audit_row["path"],
        "kind": required_role_kinds["candidate_input_leakage_audit"],
        "sha256": sha256_file(audit_path),
        "bytes": audit_path.stat().st_size,
    }

    pooled_sha = artifact_rows["pooled_band_model"]["sha256"]
    contract = _finalize_payload(
        {
            "schema_version": SEMANTIC_CONTRACT_SCHEMA_VERSION,
            "status": "PASS",
            "candidate_id": candidate_id,
            "candidate_mode": RESEARCH_ONLY_CANDIDATE_MODE,
            "production_capable": False,
            "bundle_sha256": pooled_sha,
            "leakage_audit_status": audit["status"],
            "required_role_kinds": required_role_kinds,
            "artifacts": artifact_rows,
            "generated_in_seconds": 0.0,
        }
    )
    contract_path = candidate_dir / role_rows["semantic_serving_contract"]["path"]
    _write_json_exclusive(contract_path, contract)
    return verify_candidate_semantic_contract(candidate_dir)


def _render_preflight(preflight: Mapping[str, Any]) -> str:
    lines = [
        "# All-market base-retrain preflight",
        "",
        f"- Status: **{preflight['status']}**",
        f"- Target date: `{preflight['target_date']}`",
        f"- Parent release: `{preflight['parent_release_id']}`",
        f"- Feature contract: `{preflight['feature_contract_id']}`",
        f"- Blockers: {preflight['blocker_count']}",
        "",
        "| Gate | Status | First blocker |",
        "| --- | --- | --- |",
    ]
    for check in preflight["checks"]:
        first = (check.get("blockers") or [{}])[0]
        message = str(first.get("message") or "-").replace("|", "\\|")
        if first.get("coverage"):
            message += f" ({first['coverage']})"
        lines.append(f"| {check['name']} | {check['status']} | {message} |")
    return "\n".join(lines) + "\n"


def run_base_retrain(
    args: argparse.Namespace,
    *,
    parent_loader: Callable[..., dict[str, Any]] = load_parent_contract,
    pit_preflight_loader: Callable[..., dict[str, Any]] = (
        preflight_pit_forecast_training_corpus
    ),
    market_fitter: Callable[..., dict[str, Any]] = fit_market_candidate,
    release_builder: Callable[..., dict[str, Any]] = create_release,
    isolation_probe: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Run preflight, then fit/assemble only if every gate is exact PASS."""

    plan = build_plan(
        target_date=args.target_date,
        parent_release_id=args.parent_release_id,
        training_as_of=args.training_as_of,
        feature_contract_id=args.feature_contract_id,
        corpus_manifest=args.corpus_manifest,
        pit_forecast_corpus_manifest=args.pit_forecast_corpus_manifest,
        candidate_dir=args.candidate_dir,
        runtime_id=args.runtime_id,
    )
    argument_gate = explicit_argument_gate(plan)
    if argument_gate["status"] != "PASS":
        raise BaseRetrainContractError(
            "; ".join(row["message"] for row in argument_gate["blockers"])
        )
    candidate = _validate_candidate_root(
        candidate_dir=args.candidate_dir,
        repo_root=args.repo_root,
        releases_root=args.releases_root,
    )
    plan_path = candidate / "base_retrain" / "plan.json"
    _write_json_exclusive(plan_path, plan)
    parent = parent_loader(
        parent_release_id=args.parent_release_id,
        releases_root=args.releases_root,
        active_pointer=args.active_pointer,
        repo_root=args.repo_root,
    )
    manifest_path = Path(args.corpus_manifest)
    manifest_sha = sha256_file(manifest_path)
    manifest = _read_json(manifest_path, label="base-retrain corpus manifest")
    pit_manifest_path = Path(args.pit_forecast_corpus_manifest)
    pit_manifest_sha = ""
    required_pit_selection = _required_pit_selection_keys(manifest, parent)
    try:
        pit_manifest_sha = sha256_file(pit_manifest_path)
        pit_preflight = pit_preflight_loader(
            pit_manifest_path,
            target_year=_parse_date(args.target_date, field="target_date").year,
            required_market_ids=list(EXPECTED_MARKETS),
            required_market_date_cutoffs=required_pit_selection,
        )
    except (
        CorpusVerificationError,
        MaterializationBlocked,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        pit_preflight = {
            "status": "BLOCK",
            "manifest_path": str(pit_manifest_path.resolve()),
            "manifest_file_sha256": pit_manifest_sha,
            "error": str(exc),
        }
    isolation = prove_output_isolation(
        candidate_dir=candidate,
        repo_root=args.repo_root,
        active_pointer=args.active_pointer,
        parent_release_dir=parent["parent_release_dir"],
        probe=isolation_probe,
    )
    preflight = evaluate_preflight(
        plan=plan,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        pit_forecast_manifest_sha256=pit_manifest_sha,
        pit_forecast_preflight=pit_preflight,
        parent=parent,
        output_isolation=isolation,
    )
    _write_json_exclusive(candidate / "base_retrain" / "preflight.json", preflight)
    report_path = candidate / "base_retrain" / "preflight.md"
    try:
        with report_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(_render_preflight(preflight))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise BaseRetrainContractError(
            f"immutable candidate file already exists: {report_path}"
        ) from exc
    if preflight["status"] != "PASS":
        return {
            "status": "BLOCK",
            "candidate_dir": str(candidate),
            "preflight": preflight,
            "release": None,
        }

    protected_before = protected_state_inventory(
        repo_root=args.repo_root,
        active_pointer=args.active_pointer,
        parent_release_dir=parent["parent_release_dir"],
    )
    market_results = []
    for market_id in EXPECTED_MARKETS:
        market_manifest = manifest["markets"][market_id]
        records = read_hash_bound_records(
            market_manifest["records_path"],
            expected_sha256=market_manifest["records_sha256"],
        )
        components = parent["markets"][market_id]["components"]
        paths = {
            component: candidate / components[component]["path"]
            for component in REPLACED_COMPONENTS
        }
        outputs = candidate_market_outputs(candidate, market_id)
        result = market_fitter(
            market_id=market_id,
            unit=MARKET_UNITS[market_id],
            target_date=args.target_date,
            parent_release_id=args.parent_release_id,
            training_as_of=args.training_as_of,
            feature_contract_id=args.feature_contract_id,
            runtime_id=args.runtime_id,
            corpus_manifest_sha256=manifest_sha,
            pit_forecast_corpus_manifest_sha256=pit_manifest_sha,
            pit_forecast_preflight_sha256=pit_preflight["preflight_sha256"],
            records=records,
            parent_hgb=parent["markets"][market_id]["hgb"],
            parent_lr=parent["markets"][market_id]["lr"],
            hgb_path=paths["feature_hgb"],
            lr_path=paths["feature_lr_coefficients"],
            probability_calibration_path=paths["probability_calibration"],
            receipt_path=candidate / outputs["fit_receipt"],
            report_path=candidate / outputs["fit_report"],
        )
        market_results.append(result)
        protected_after_market = protected_state_inventory(
            repo_root=args.repo_root,
            active_pointer=args.active_pointer,
            parent_release_dir=parent["parent_release_dir"],
        )
        if protected_after_market["inventory_sha256"] != protected_before["inventory_sha256"]:
            raise BaseRetrainContractError(
                f"outside-candidate write detected after market fit: {market_id}"
            )

    completed = {
        row.get("market_id")
        for row in market_results
        if row.get("status") == "PASS"
        and set((row.get("outputs") or {}))
        >= {"feature_hgb", "feature_lr_coefficients", "probability_calibration"}
    }
    if completed != set(EXPECTED_MARKETS):
        raise BaseRetrainContractError(
            "fleet atomicity failed: all 12 HGB/LR/calibration triples are required"
        )
    _copy_parent_unchanged(parent, candidate)
    semantic = _finalize_candidate_contract(
        parent=parent,
        candidate_dir=candidate,
        candidate_id=plan["candidate_release_id"],
    )
    fleet_receipt = _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "document_type": "fleet_receipt",
            "status": "PASS",
            "market_count": len(market_results),
            "markets": market_results,
            "semantic_contract_sha256": semantic["contract_sha256"],
            "parent_release_id": args.parent_release_id,
            "parent_manifest_sha256": parent["parent_manifest_sha256"],
            "pit_forecast_corpus_manifest_sha256": pit_manifest_sha,
            "pit_forecast_preflight_sha256": pit_preflight["preflight_sha256"],
            "active_pointer_unchanged_before_release_build": True,
        }
    )
    fleet_path = candidate / "base_retrain" / "fleet_receipt.json"
    _write_json_exclusive(fleet_path, fleet_receipt)
    code_identity = capture_code_identity(args.repo_root)
    if code_identity.get("git_dirty") is not False:
        raise BaseRetrainContractError(
            "inactive release construction requires a clean source tree"
        )
    release = release_builder(
        release_id=plan["candidate_release_id"],
        candidate_dir=candidate,
        declarations=semantic["declarations"],
        route=semantic["route"],
        expected_live_runtimes=parent["manifest"]["expected_live_runtimes"],
        releases_root=args.releases_root,
        repo_root=args.repo_root,
        parent_release=args.parent_release_id,
        rollback_target=args.parent_release_id,
        lineage={
            "all_market_base_retrain": {
                "plan_sha256": plan["payload_sha256"],
                "preflight_sha256": preflight["payload_sha256"],
                "fleet_receipt_sha256": fleet_receipt["payload_sha256"],
                "corpus_manifest_sha256": manifest_sha,
                "pit_forecast_corpus_manifest_sha256": pit_manifest_sha,
                "pit_forecast_preflight_sha256": pit_preflight[
                    "preflight_sha256"
                ],
                "runtime_id": args.runtime_id,
            }
        },
        code_identity=code_identity,
    )
    protected_after = protected_state_inventory(
        repo_root=args.repo_root,
        active_pointer=args.active_pointer,
        parent_release_dir=parent["parent_release_dir"],
    )
    if protected_after["inventory_sha256"] != protected_before["inventory_sha256"]:
        raise BaseRetrainContractError(
            "protected globals, active pointer, or parent release changed"
        )
    return {
        "status": "PASS",
        "candidate_dir": str(candidate),
        "preflight": preflight,
        "fleet_receipt": fleet_receipt,
        "release": {**release, "activation": "NONE"},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one explicit, candidate-only, all-market base-model release."
    )
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--parent-release-id", required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--feature-contract-id", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--pit-forecast-corpus-manifest", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--releases-root", required=True)
    parser.add_argument("--active-pointer", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_base_retrain(args)
    except BaseRetrainContractError as exc:
        print(f"All-market base retrain: ERROR: {exc}")
        return 1
    print(f"All-market base retrain: {result['status']}")
    print(f"Candidate root: {result['candidate_dir']}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
