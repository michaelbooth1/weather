from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from weather.model.model_bom import (
    MODEL_BOM_COMPLETE,
    MODEL_BOM_INCOMPLETE,
    ModelBomError,
    build_model_bill_of_materials,
    canonical_payload_sha256,
    coefficient_model_mapping,
    required_training_roles,
    verify_loaded_environment_binding,
    verify_loaded_model_node,
    verify_loaded_model_structure,
    verify_model_bill_of_materials,
)
from weather.model.model_bom_contracts import (
    RUNTIME_LANE_CONTRACTS,
    SERVING_GRAPH_EDGES,
    SERVING_STAGE_CONTRACTS,
)
from weather.model.model_contracts import (
    BASE_DISTRIBUTION_STAGE_ORDER,
    FORECAST_CONTEXT_SOURCE_ROLES,
    POOLED_BAND_STAGE_ORDER,
)


class FittedEstimator:
    n_features_in_ = 2
    feature_names_in_ = ["forecast_high", "high_so_far"]
    classes_ = [0, 1]
    n_iter_ = 7
    learning_rate = 0.05
    coef_ = [[1.0, 0.0]]


class _MalformedPredictor:
    nodes = []


class MalformedHgbEstimator(FittedEstimator):
    _predictors = [[_MalformedPredictor()]]


_RELEASE_RUNTIME_VERSIONS = {
    "python": "3.11.9",
    "dependencies": {"numpy": "fixture", "scikit-learn": "fixture"},
}
_RELEASE_RUNTIME_IDENTITY = {
    "schema_version": "weather_runtime_identity_v0.3",
    "source_fingerprint": "a" * 64,
    "source_file_count": 2,
    "identity_source": "git_filesystem",
    "python_version": "3.11.9",
    "source_scope": "model_serving",
    "source_scope_files": ["src/weather/model/model_distribution.py"],
    # Deliberately path-unstable metadata that the BOM projection must omit.
    "repository_root": "C:/one/absolute/worktree",
}
_MODEL_RUNTIME_DEPENDENCY_IDENTITY = {
    "schema_version": "weather_model_runtime_dependencies_v0.1",
    "python": "3.11.9",
    "packages": {"numpy": "fixture", "scikit-learn": "fixture"},
    "runtime_dependency_hash": "b" * 64,
}


def _artifact_rows() -> dict[str, dict]:
    roles = {
        "base_model_serving_graph": "route",
        "market_route_table": "route",
        "model_variant_registry": "registry",
        "location_market_events_config": "config",
        "locations_config": "config",
        "markets_config": "config",
        "pooled_band_model": "model",
        "pooled_feature_schema": "feature_schema",
        "pooled_imputer_metadata": "imputer",
        "pooled_calibrator_metadata": "calibration",
        "pooled_postprocessor_metadata": "postprocessor",
        "training_evaluation_corpus": "corpus",
        "base_model.nyc.feature_hgb": "model",
        "base_model.nyc.feature_lr_coefficients": "model",
        "base_model.nyc.calibrated_weights": "calibration",
        "base_model.nyc.forecast_error_model": "calibration",
        "base_model.nyc.late_day_lr_coefficients": "model",
        "base_model.nyc.probability_calibration": "calibration",
        "base_model.nyc.settlement_lag_model": "calibration",
        "base_model.shared.afternoon_residual_centering": "calibration",
        "settlement_rules": "settlement_rules",
        "family_secondary_calibration": "calibration",
    }
    return {
        role: {
            "path": f"contract/{role.replace('.', '_')}.bin",
            "kind": kind,
            "sha256": canonical_payload_sha256({"role": role}),
            "bytes": 123,
        }
        for role, kind in roles.items()
    }


def _evidence(binding: dict) -> dict:
    return {
        "status": MODEL_BOM_COMPLETE,
        "identity_sha256": canonical_payload_sha256(binding),
        "binding": binding,
    }


def _required_owner_modules() -> list[str]:
    return sorted(
        {str(row["owner_module"]) for row in SERVING_STAGE_CONTRACTS}
        | {str(row["runtime_owner"]) for row in RUNTIME_LANE_CONTRACTS}
    )


def _loaded_module_rows() -> list[dict]:
    return [
        {
            "module": module,
            "status": MODEL_BOM_COMPLETE,
            "sha256": canonical_payload_sha256(
                {"module": module, "surface": "loaded"}
            ),
        }
        for module in _required_owner_modules()
    ]


def _source_file_rows() -> list[dict]:
    return [
        {
            "module": module,
            "status": MODEL_BOM_COMPLETE,
            "sha256": canonical_payload_sha256(
                {"module": module, "surface": "source"}
            ),
            "bytes": 100,
        }
        for module in _required_owner_modules()
    ]


def _code_evidence() -> dict:
    source_files = _source_file_rows()
    loaded_modules = _loaded_module_rows()
    return _evidence(
        {
            "identity_schema_version": "weather_model_replay_identity_v0.3",
            "source_files": source_files,
            "source_file_count": len(source_files),
            "source_fingerprint": canonical_payload_sha256(
                {"source_files": source_files}
            ),
            "loaded_modules": loaded_modules,
            "loaded_code_hash": canonical_payload_sha256(
                {"loaded_modules": loaded_modules}
            ),
            "behavior_constants_sha256": canonical_payload_sha256(
                {"constants": "fixture"}
            ),
        }
    )


def _runtime_evidence() -> dict:
    return _evidence(
        {
            "release_runtime_versions": _RELEASE_RUNTIME_VERSIONS,
            "release_runtime_identity": {
                key: value
                for key, value in _RELEASE_RUNTIME_IDENTITY.items()
                if key != "repository_root"
            },
            "model_runtime_dependency_identity": (
                _MODEL_RUNTIME_DEPENDENCY_IDENTITY
            ),
        }
    )


def _context_evidence(name: str) -> dict:
    return _evidence(
        {
            "implementation": name,
            "runtime_contract_owner": "weather.model.model_contracts",
            "runtime_contract_symbol": "FORECAST_CONTEXT_SOURCE_ROLES",
            "source_roles": list(FORECAST_CONTEXT_SOURCE_ROLES[name]),
            "input_semantic_contract": f"{name}:inputs",
            "output_semantic_contract": f"{name}:outputs",
            "native_unit_obligation": "market native settlement unit",
            "cutoff_obligation": "effective cutoff only",
        }
    )


def _model_nodes() -> dict[str, dict]:
    return {
        role: {
            "12": {
                "feature_names": ["forecast_high", "high_so_far"],
                "model": FittedEstimator(),
            }
        }
        for role in (
            "pooled_band_model",
            "base_model.nyc.feature_hgb",
            "base_model.nyc.feature_lr_coefficients",
            "base_model.nyc.late_day_lr_coefficients",
        )
    }


def _finalize_lineage(row: dict) -> dict:
    result = deepcopy(row)
    result["identity_sha256"] = canonical_payload_sha256(result)
    return result


def _direct_fit_lineage(role: str, artifacts: dict[str, dict]) -> dict:
    partition_sha256 = canonical_payload_sha256(
        {"partition": "fixture", "artifact_role": role}
    )
    return _finalize_lineage(
        {
            "status": MODEL_BOM_COMPLETE,
            "disposition": "direct_fit_output",
            "artifact_role": role,
            "artifact_sha256": artifacts[role]["sha256"],
            "corpus_binding": {
                "artifact_role": "training_evaluation_corpus",
                "artifact_sha256": artifacts["training_evaluation_corpus"][
                    "sha256"
                ],
                "partition": "final_refit",
                "partition_sha256": partition_sha256,
                "row_count": 101,
            },
            "fit_binding": {
                "receipt_schema_version": "fixture_fit_receipt_v0.1",
                "receipt_sha256": canonical_payload_sha256(
                    {"fit": role, "partition": partition_sha256}
                ),
                "output_binding_kind": "artifact_content_sha256",
                "output_content_sha256": artifacts[role]["sha256"],
                "partition_sha256": partition_sha256,
                "row_count": 101,
            },
        }
    )


def _derivative_lineage(
    role: str,
    *,
    parent_role: str,
    artifacts: dict[str, dict],
    parent: dict,
) -> dict:
    return _finalize_lineage(
        {
            "status": MODEL_BOM_COMPLETE,
            "disposition": "deterministic_derivative",
            "artifact_role": role,
            "artifact_sha256": artifacts[role]["sha256"],
            "parent_binding": {
                "artifact_role": parent_role,
                "artifact_sha256": artifacts[parent_role]["sha256"],
                "lineage_identity_sha256": parent["identity_sha256"],
            },
            "derivation_sha256": canonical_payload_sha256(
                {
                    "derivation": "deterministic candidate sidecar",
                    "parent_role": parent_role,
                    "child_role": role,
                }
            ),
        }
    )


def _inherited_lineage(role: str, artifacts: dict[str, dict]) -> dict:
    return _finalize_lineage(
        {
            "status": MODEL_BOM_COMPLETE,
            "disposition": "verified_parent_inheritance",
            "artifact_role": role,
            "artifact_sha256": artifacts[role]["sha256"],
            "parent_binding": {
                "artifact_role": role,
                "artifact_sha256": artifacts[role]["sha256"],
                "parent_bom_identity_sha256": canonical_payload_sha256(
                    {"parent_bom": role}
                ),
                "parent_manifest_sha256": canonical_payload_sha256(
                    {"parent_manifest": role}
                ),
            },
        }
    )


def _training_lineage(artifacts: dict[str, dict]) -> dict[str, dict]:
    required = required_training_roles(artifacts)
    pooled = _direct_fit_lineage("pooled_band_model", artifacts)
    records = {
        role: _inherited_lineage(role, artifacts)
        for role in sorted(required)
        if not role.startswith("pooled_")
    }
    records["pooled_band_model"] = pooled
    for role in sorted(required & {
        "pooled_feature_schema",
        "pooled_imputer_metadata",
        "pooled_calibrator_metadata",
        "pooled_postprocessor_metadata",
    }):
        records[role] = _derivative_lineage(
            role,
            parent_role="pooled_band_model",
            artifacts=artifacts,
            parent=pooled,
        )
    assert set(records) == required
    return records


def _complete_bom(
    *,
    artifacts: dict[str, dict] | None = None,
    model_nodes: dict[str, dict] | None = None,
    training_lineage: dict[str, dict] | None = None,
    forecast_contexts: dict[str, dict] | None = None,
    code_constants: dict | None = None,
    runtime_dependencies: dict | None = None,
) -> dict:
    artifacts = artifacts or _artifact_rows()
    return build_model_bill_of_materials(
        artifacts=artifacts,
        model_nodes=model_nodes or _model_nodes(),
        code_constants=code_constants or _code_evidence(),
        runtime_dependencies=runtime_dependencies or _runtime_evidence(),
        training_lineage=(
            training_lineage
            if training_lineage is not None
            else _training_lineage(artifacts)
        ),
        forecast_contexts=(
            forecast_contexts
            if forecast_contexts is not None
            else {
                name: _context_evidence(name)
                for name in FORECAST_CONTEXT_SOURCE_ROLES
            }
        ),
    )


def _rehash(payload: dict) -> None:
    diagnostic_material = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "authoritative_identity_sha256",
            "diagnostic_sha256",
            "payload_sha256",
        }
    }
    payload["diagnostic_sha256"] = canonical_payload_sha256(diagnostic_material)
    payload["authoritative_identity_sha256"] = (
        payload["diagnostic_sha256"]
        if payload["status"] == MODEL_BOM_COMPLETE
        else None
    )
    payload["payload_sha256"] = canonical_payload_sha256(
        payload, omit=("payload_sha256",)
    )


def _rehash_graph(payload: dict) -> None:
    graph = payload["serving_graph"]
    graph["graph_identity_sha256"] = canonical_payload_sha256(
        graph, omit=("graph_identity_sha256",)
    )
    _rehash(payload)


def test_complete_bom_has_two_runtime_bound_lanes_and_no_global_order():
    first = _complete_bom()
    second = _complete_bom()

    assert first == second
    assert first["status"] == MODEL_BOM_COMPLETE
    assert first["missing_entries"] == []
    assert first["authoritative_identity_sha256"] == first["diagnostic_sha256"]

    graph = first["serving_graph"]
    assert [row["stage_id"] for row in graph["nodes"]] == [
        str(row["stage_id"]) for row in SERVING_STAGE_CONTRACTS
    ]
    assert graph["edges"] == [
        {"from": left, "to": right, "condition": condition}
        for left, right, condition in SERVING_GRAPH_EDGES
    ]
    assert graph["lanes"] == [
        {
            "lane_id": "toronto_base_distribution",
            "runtime_owner": "weather.model.model_distribution",
            "runtime_contract_symbol": "BASE_DISTRIBUTION_STAGE_ORDER",
            "stage_order": list(BASE_DISTRIBUTION_STAGE_ORDER),
            "runtime_contract_sha256": canonical_payload_sha256(
                {"stage_order": list(BASE_DISTRIBUTION_STAGE_ORDER)}
            ),
        },
        {
            "lane_id": "pooled_band_live_variant",
            "runtime_owner": "weather.collection.live_variant_predictions",
            "runtime_contract_symbol": "POOLED_BAND_STAGE_ORDER",
            "stage_order": list(POOLED_BAND_STAGE_ORDER),
            "runtime_contract_sha256": canonical_payload_sha256(
                {"stage_order": list(POOLED_BAND_STAGE_ORDER)}
            ),
        },
    ]
    assert set(BASE_DISTRIBUTION_STAGE_ORDER).isdisjoint(POOLED_BAND_STAGE_ORDER)
    assert all("execution_index" not in node for node in graph["nodes"])
    assert "execution_order" not in graph
    assert "serving_stages" not in first

    structure = first["model_nodes"]["base_model.nyc.feature_hgb"][
        "models"
    ]["12"]
    assert structure["feature_names"] == ["forecast_high", "high_so_far"]
    assert structure["n_features_in"] == 2
    assert structure["structural_attributes"]["n_iter_"] == 7
    assert structure["structural_feature_use"]["status"] == "COMPLETE"
    assert structure["structural_feature_use"]["used_feature_names"] == [
        "forecast_high"
    ]

    verify_model_bill_of_materials(
        first,
        expected_artifacts=_artifact_rows(),
        production_required=True,
        expected_runtime_versions=_RELEASE_RUNTIME_VERSIONS,
        expected_runtime_identity=_RELEASE_RUNTIME_IDENTITY,
    )


def test_mapping_order_does_not_move_bom_identity():
    first = _complete_bom()
    artifacts = dict(reversed(list(_artifact_rows().items())))
    lineage = dict(reversed(list(_training_lineage(artifacts).items())))
    contexts = dict(
        reversed(
            [
                (name, _context_evidence(name))
                for name in FORECAST_CONTEXT_SOURCE_ROLES
            ]
        )
    )
    code = _code_evidence()
    code["binding"] = dict(reversed(list(code["binding"].items())))
    code["identity_sha256"] = canonical_payload_sha256(code["binding"])
    runtime = _runtime_evidence()
    runtime["binding"] = dict(reversed(list(runtime["binding"].items())))
    runtime["identity_sha256"] = canonical_payload_sha256(runtime["binding"])

    second = _complete_bom(
        artifacts=artifacts,
        model_nodes=dict(reversed(list(_model_nodes().items()))),
        training_lineage=lineage,
        forecast_contexts=contexts,
        code_constants=code,
        runtime_dependencies=runtime,
    )
    assert second == first
    assert "C:/one/absolute/worktree" not in str(second)


def test_bom_identity_matches_across_distinct_absolute_roots_and_moves_on_source_drift(
    tmp_path: Path,
):
    source_model_dir = Path(__file__).parents[2] / "src" / "weather" / "model"
    probe = """
import hashlib
import json
from pathlib import Path

from weather.model import model_bom

source = Path(model_bom.__file__).resolve()
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
source_rows = [{
    "module": "weather.model.model_bom",
    "status": "COMPLETE",
    "sha256": source_sha,
    "bytes": source.stat().st_size,
}]
loaded_rows = [{
    "module": "weather.model.model_bom",
    "status": "COMPLETE",
    "sha256": source_sha,
}]
binding = {
    "identity_schema_version": "probe_v1",
    "source_files": source_rows,
    "source_file_count": 1,
    "source_fingerprint": model_bom.canonical_payload_sha256(
        {"source_files": source_rows}
    ),
    "loaded_modules": loaded_rows,
    "loaded_code_hash": model_bom.canonical_payload_sha256(
        {"loaded_modules": loaded_rows}
    ),
    "behavior_constants_sha256": "a" * 64,
}
code = {
    "status": "COMPLETE",
    "identity_sha256": model_bom.canonical_payload_sha256(binding),
    "binding": binding,
}
payload = model_bom.build_model_bill_of_materials(
    artifacts={},
    model_nodes={},
    code_constants=code,
    runtime_dependencies={},
    training_lineage={},
    forecast_contexts={},
)
print(json.dumps({
    "imported_file": str(source),
    "diagnostic_sha256": payload["diagnostic_sha256"],
    "payload_sha256": payload["payload_sha256"],
}, sort_keys=True))
"""

    def prepare(root: Path) -> Path:
        model_dir = root / "weather" / "model"
        model_dir.mkdir(parents=True)
        (root / "weather" / "__init__.py").write_text("", encoding="utf-8")
        (model_dir / "__init__.py").write_text("", encoding="utf-8")
        for name in ("model_bom.py", "model_bom_contracts.py", "model_contracts.py"):
            shutil.copy2(source_model_dir / name, model_dir / name)
        probe_path = root / "probe.py"
        probe_path.write_text(probe, encoding="utf-8")
        return probe_path

    def run(root: Path, probe_path: Path) -> dict:
        completed = subprocess.run(
            [sys.executable, str(probe_path)],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    left = tmp_path / "left_absolute_worktree"
    right = tmp_path / "right_absolute_worktree"
    left_probe = prepare(left)
    right_probe = prepare(right)
    left_result = run(left, left_probe)
    right_result = run(right, right_probe)

    assert left_result["imported_file"] != right_result["imported_file"]
    assert Path(left_result["imported_file"]).is_relative_to(left)
    assert Path(right_result["imported_file"]).is_relative_to(right)
    assert left_result["diagnostic_sha256"] == right_result["diagnostic_sha256"]
    assert left_result["payload_sha256"] == right_result["payload_sha256"]

    right_model_bom = right / "weather" / "model" / "model_bom.py"
    right_model_bom.write_text(
        right_model_bom.read_text(encoding="utf-8") + "\n# source-byte drift\n",
        encoding="utf-8",
    )
    drifted = run(right, right_probe)
    assert drifted["diagnostic_sha256"] != left_result["diagnostic_sha256"]
    assert drifted["payload_sha256"] != left_result["payload_sha256"]


def test_training_lineage_is_artifact_specific_and_role_correct():
    bom = _complete_bom()
    lineage = bom["training_lineage"]

    assert set(lineage) == required_training_roles(_artifact_rows())
    assert lineage["pooled_band_model"]["disposition"] == "direct_fit_output"
    assert (
        lineage["pooled_band_model"]["fit_binding"]["output_content_sha256"]
        == _artifact_rows()["pooled_band_model"]["sha256"]
    )
    for role in (
        "pooled_feature_schema",
        "pooled_imputer_metadata",
        "pooled_calibrator_metadata",
        "pooled_postprocessor_metadata",
    ):
        assert lineage[role]["disposition"] == "deterministic_derivative"
        assert lineage[role]["parent_binding"]["artifact_role"] == (
            "pooled_band_model"
        )
        assert lineage[role]["parent_binding"]["lineage_identity_sha256"] == (
            lineage["pooled_band_model"]["identity_sha256"]
        )
    inherited = set(lineage) - {
        "pooled_band_model",
        "pooled_feature_schema",
        "pooled_imputer_metadata",
        "pooled_calibrator_metadata",
        "pooled_postprocessor_metadata",
    }
    assert inherited
    assert all(
        lineage[role]["disposition"] == "verified_parent_inheritance"
        for role in inherited
    )


def test_sibling_lineage_cannot_be_reused_for_another_artifact_role():
    artifacts = _artifact_rows()
    lineage = _training_lineage(artifacts)
    lineage["pooled_imputer_metadata"] = deepcopy(
        lineage["pooled_feature_schema"]
    )

    bom = _complete_bom(artifacts=artifacts, training_lineage=lineage)

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert any(
        entry.startswith(
            "training_lineage.pooled_imputer_metadata.artifact_binding"
        )
        for entry in bom["missing_entries"]
    )


def test_derivative_parent_lineage_identity_is_cross_bound():
    artifacts = _artifact_rows()
    lineage = _training_lineage(artifacts)
    child = lineage["pooled_feature_schema"]
    child["parent_binding"]["lineage_identity_sha256"] = "f" * 64
    lineage["pooled_feature_schema"] = _finalize_lineage(
        {key: value for key, value in child.items() if key != "identity_sha256"}
    )

    bom = _complete_bom(artifacts=artifacts, training_lineage=lineage)

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert (
        "training_lineage.pooled_feature_schema.parent_binding."
        "lineage_identity_sha256"
        in bom["missing_entries"]
    )


def test_self_rehashed_lane_swap_is_rejected():
    bom = _complete_bom()
    first, second = bom["serving_graph"]["lanes"]
    first["stage_order"], second["stage_order"] = (
        second["stage_order"],
        first["stage_order"],
    )
    for lane in (first, second):
        lane["runtime_contract_sha256"] = canonical_payload_sha256(
            {"stage_order": lane["stage_order"]}
        )
    _rehash_graph(bom)

    with pytest.raises(ModelBomError, match="serving_graph is not canonical"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
        )


def test_self_rehashed_cross_lane_edge_is_rejected():
    bom = _complete_bom()
    edge = next(
        row
        for row in bom["serving_graph"]["edges"]
        if row["from"] == BASE_DISTRIBUTION_STAGE_ORDER[0]
    )
    edge["to"] = POOLED_BAND_STAGE_ORDER[0]
    edge["condition"] = "required"
    _rehash_graph(bom)

    with pytest.raises(ModelBomError, match="serving_graph is not canonical"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
        )


@pytest.mark.parametrize(
    ("context_name", "mutation", "missing_suffix"),
    [
        (
            "feature_extraction_forecast_ensemble",
            lambda binding: binding["source_roles"].remove(
                "open_meteo_global_models"
            ),
            ".source_roles",
        ),
        (
            "distribution_stage_forecast_context",
            lambda binding: binding.__setitem__(
                "runtime_contract_owner", "weather.model.model_bom"
            ),
            ".runtime_contract_owner",
        ),
        (
            "distribution_stage_forecast_context",
            lambda binding: binding.__setitem__(
                "runtime_contract_symbol", "LOCAL_FORECAST_SOURCES"
            ),
            ".runtime_contract_symbol",
        ),
    ],
)
def test_forecast_context_must_match_exact_runtime_contract(
    context_name, mutation, missing_suffix
):
    contexts = {
        name: _context_evidence(name) for name in FORECAST_CONTEXT_SOURCE_ROLES
    }
    mutation(contexts[context_name]["binding"])
    contexts[context_name]["identity_sha256"] = canonical_payload_sha256(
        contexts[context_name]["binding"]
    )

    bom = _complete_bom(forecast_contexts=contexts)

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert (
        f"forecast_contexts.{context_name}{missing_suffix}"
        in bom["missing_entries"]
    )


def test_malformed_hgb_structure_is_incomplete_and_never_authoritative():
    nodes = _model_nodes()
    nodes["base_model.nyc.feature_hgb"] = {
        "12": {
            "feature_names": ["forecast_high", "high_so_far"],
            "model": MalformedHgbEstimator(),
        }
    }

    bom = _complete_bom(model_nodes=nodes)

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert bom["authoritative_identity_sha256"] is None
    structure = bom["model_nodes"]["base_model.nyc.feature_hgb"]["models"][
        "12"
    ]
    assert structure["structural_feature_use"]["status"] == "UNREADABLE"
    assert (
        "model_nodes.base_model.nyc.feature_hgb."
        "12:structural_feature_use:unreadable"
        in bom["missing_entries"]
    )
    verify_model_bill_of_materials(
        bom,
        expected_artifacts=_artifact_rows(),
        production_required=False,
    )
    with pytest.raises(ModelBomError, match="production model BOM is incomplete"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
        )


def test_loaded_environment_binding_checks_exact_code_and_dependencies():
    bom = _complete_bom()
    verify_loaded_environment_binding(
        bom,
        loaded_modules=_loaded_module_rows(),
        runtime_dependency_identity=_MODEL_RUNTIME_DEPENDENCY_IDENTITY,
    )

    changed_modules = _loaded_module_rows()
    changed_modules[0]["sha256"] = "e" * 64
    with pytest.raises(ModelBomError, match="loaded module fingerprints"):
        verify_loaded_environment_binding(
            bom,
            loaded_modules=changed_modules,
            runtime_dependency_identity=_MODEL_RUNTIME_DEPENDENCY_IDENTITY,
        )

    changed_runtime = deepcopy(_MODEL_RUNTIME_DEPENDENCY_IDENTITY)
    changed_runtime["runtime_dependency_hash"] = "e" * 64
    with pytest.raises(ModelBomError, match="runtime dependency identity"):
        verify_loaded_environment_binding(
            bom,
            loaded_modules=_loaded_module_rows(),
            runtime_dependency_identity=changed_runtime,
        )


def test_release_runtime_cross_binding_is_not_self_certifying():
    bom = _complete_bom()
    changed_versions = deepcopy(_RELEASE_RUNTIME_VERSIONS)
    changed_versions["python"] = "3.11.10"
    with pytest.raises(ModelBomError, match="runtime versions disagree"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
            expected_runtime_versions=changed_versions,
        )

    changed_identity = deepcopy(_RELEASE_RUNTIME_IDENTITY)
    changed_identity["source_fingerprint"] = "e" * 64
    with pytest.raises(ModelBomError, match="runtime identity disagrees"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
            expected_runtime_identity=changed_identity,
        )


def test_absolute_artifact_path_is_explicitly_incomplete():
    artifacts = _artifact_rows()
    artifacts["pooled_band_model"]["path"] = "C:/ambient/model.pkl"
    bom = _complete_bom(artifacts=artifacts)

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert (
        "artifacts.pooled_band_model.path:not_candidate_relative"
        in bom["missing_entries"]
    )


def test_normalized_mapping_key_collision_is_rejected():
    rows = _artifact_rows()
    collision = {1: rows["pooled_band_model"], "1": rows["pooled_band_model"]}
    with pytest.raises(ModelBomError, match="role collision"):
        build_model_bill_of_materials(
            artifacts=collision,
            model_nodes={},
            code_constants=_code_evidence(),
            runtime_dependencies=_runtime_evidence(),
            training_lineage={},
            forecast_contexts={
                name: _context_evidence(name)
                for name in FORECAST_CONTEXT_SOURCE_ROLES
            },
        )


def test_pre_deserialization_verifier_rejects_artifact_substitution():
    expected = _artifact_rows()
    substituted = deepcopy(expected)
    substituted["base_model.nyc.feature_hgb"]["sha256"] = "b" * 64

    with pytest.raises(ModelBomError, match="artifact inventory disagrees"):
        verify_model_bill_of_materials(
            _complete_bom(),
            expected_artifacts=substituted,
            production_required=True,
        )


def test_pre_deserialization_verifier_rejects_rehashed_incomplete_authority():
    nodes = _model_nodes()
    nodes["base_model.nyc.feature_hgb"] = {
        "12": {"feature_names": ["forecast_high"], "model": None}
    }
    bom = _complete_bom(model_nodes=nodes)
    bom["authoritative_identity_sha256"] = "f" * 64
    bom["payload_sha256"] = canonical_payload_sha256(
        bom, omit=("payload_sha256",)
    )

    with pytest.raises(ModelBomError, match="incomplete model BOM must not expose"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=False,
        )


def test_post_load_verifier_rejects_feature_order_change():
    loaded = _model_nodes()
    loaded["base_model.nyc.feature_hgb"] = {
        "12": {
            "feature_names": ["high_so_far", "forecast_high"],
            "model": FittedEstimator(),
        }
    }
    with pytest.raises(ModelBomError, match="feature order disagrees"):
        verify_loaded_model_structure(
            _complete_bom(),
            loaded_model_nodes=loaded,
        )


def test_post_load_coefficient_model_preserves_declared_order_and_use():
    payload = {
        "12": {
            "feature_names": ["forecast_high", "high_so_far"],
            "coef": [1.0, 0.0],
            "classes": [0, 1],
        }
    }
    nodes = _model_nodes()
    nodes["base_model.nyc.feature_lr_coefficients"] = coefficient_model_mapping(
        payload
    )
    bom = _complete_bom(model_nodes=nodes)

    verify_loaded_model_node(
        bom,
        node="base_model.nyc.feature_lr_coefficients",
        loaded_models=coefficient_model_mapping(payload),
    )
    payload["12"]["feature_names"].reverse()
    with pytest.raises(ModelBomError, match="feature order disagrees"):
        verify_loaded_model_node(
            bom,
            node="base_model.nyc.feature_lr_coefficients",
            loaded_models=coefficient_model_mapping(payload),
        )


def test_forecast_context_nodes_cannot_be_collapsed_or_renamed():
    bom = _complete_bom(
        forecast_contexts={"forecast_context": _evidence({"collapsed": True})}
    )

    assert bom["status"] == MODEL_BOM_INCOMPLETE
    assert any(
        entry.startswith(
            "forecast_contexts.feature_extraction_forecast_ensemble.status"
        )
        for entry in bom["missing_entries"]
    )
    assert "forecast_contexts.unexpected:forecast_context" in bom["missing_entries"]


def test_self_rehashed_graph_node_omission_is_rejected():
    bom = _complete_bom()
    bom["serving_graph"]["nodes"].pop()
    _rehash_graph(bom)
    with pytest.raises(ModelBomError, match="serving_graph is not canonical"):
        verify_model_bill_of_materials(
            bom,
            expected_artifacts=_artifact_rows(),
            production_required=True,
        )
