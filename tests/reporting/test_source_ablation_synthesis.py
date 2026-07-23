from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from weather.backtesting.source_ablation_contract import ALL_VARIANTS
from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityDriftError,
    ExecutionIdentityError,
    InvocationSpec,
    PathBinding,
    capture_execution_identity,
)
from weather.reporting.research import source_ablation_synthesis_hardened as hardened
from weather.reporting.research.source_ablation_hardened import TERMINAL_MARKET_IDS
from weather.reporting.research.source_ablation_synthesis import (
    SourceAblationSynthesisError,
    add_market_holm_adjustments,
    holm_adjust,
    synthesize,
    write_outputs,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(p_value: float) -> dict[str, object]:
    return {
        "mean": -0.1,
        "date_bootstrap_95ci": {
            "low": -0.2,
            "high": -0.05,
            "replicates": 10_000,
            "seed": 1,
        },
        "sign_test": {
            "improvements": 1,
            "regressions": 9,
            "ties": 0,
            "non_ties": 10,
            "two_sided_p": p_value,
        },
    }


def _identity(tmp_path: Path):
    seed = tmp_path / "identity-seed.txt"
    seed.write_text("fixed", encoding="utf-8")
    closure = ClosureSpec(
        name="test-source-generation",
        base_root=tmp_path,
        invocation=InvocationSpec.current(run_parameters={"test": True}),
        path_bindings=(PathBinding("seed", seed, "required_file"),),
        environment=EnvironmentSpec(include_packages=False),
    )
    return capture_execution_identity(closure)


def _sealed_receipts() -> dict[str, dict[str, object]]:
    hashes = {
        "corpus": "c" * 64,
        "preregistration": hardened.TERMINAL_PREREGISTRATION_SHA256,
        "support": hardened.TERMINAL_SUPPORT_SHA256,
        "feasibility": hardened.TERMINAL_FEASIBILITY_SHA256,
        "runtime_support_correction": (
            hardened.TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256
        ),
        "runtime_support_helper": "f" * 64,
        "tune_dates": "d" * 64,
        "holdout_dates": "e" * 64,
    }
    return {
        name: {
            "path": f"C:/repo/sealed/{name}",
            "sha256": digest,
            "size_bytes": 10,
            "mtime_ns": 1,
        }
        for name, digest in hashes.items()
    }


def _source_generation(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    generation = tmp_path / hardened.RETRY_GENERATION_LEAF
    generation.mkdir()
    identity = _identity(tmp_path)
    artifact = {
        "schema_version": "source_family_ablation_v0.2",
        "sealed_contracts": _sealed_receipts(),
        "execution_identity": {
            "start": identity.to_dict(),
            "completion": identity.to_dict(),
            "full_manifest_equality": True,
        },
    }
    artifact_path = generation / hardened.SOURCE_ARTIFACT_NAME
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    report_path = generation / hardened.SOURCE_REPORT_NAME
    report_path.write_text("# Source replay\n", encoding="utf-8")
    commit = {
        "schema_version": hardened.SOURCE_COMMIT_SCHEMA_VERSION,
        "status": "COMPLETE",
        "generated_at_utc": "2026-07-22T12:00:00+00:00",
        "research_only": True,
        "serving_or_release_authorization": False,
        "multi_leaf_atomic_transaction_claimed": False,
        "commit_marker_semantics": "COMPLETE.json is the sole final commit marker",
        "execution_identity": {
            "start_digest": identity.identity_digest,
            "completion_digest": identity.identity_digest,
            "identical_full_manifest": True,
        },
        "terminal_seals": copy.deepcopy(artifact["sealed_contracts"]),
        "outputs": [
            {
                "name": artifact_path.name,
                "sha256": _sha(artifact_path),
                "size_bytes": artifact_path.stat().st_size,
            },
            {
                "name": report_path.name,
                "sha256": _sha(report_path),
                "size_bytes": report_path.stat().st_size,
            },
        ],
        "metadata": {
            "profile": "workstation_source_ablation_hardened_v0.1",
            "artifact_schema_version": "source_family_ablation_v0.2",
            "variant_count": 22,
            "market_days_scored": 309,
        },
    }
    (generation / hardened.SOURCE_COMPLETE_NAME).write_text(
        json.dumps(commit), encoding="utf-8"
    )
    return artifact_path, artifact


def _publication_closure(tmp_path: Path):
    bound = tmp_path / "bound.txt"
    bound.write_text("unchanged", encoding="utf-8")
    closure = ClosureSpec(
        name="synthesis-publication-test",
        base_root=tmp_path,
        invocation=InvocationSpec.current(run_parameters={"profile": "test"}),
        path_bindings=(PathBinding("bound", bound, "required_file"),),
        environment=EnvironmentSpec(include_packages=False),
    )
    return bound, closure, capture_execution_identity(closure)


def _synthesis_publication_payload(
    identity,
    *,
    summary: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "source_ablation_synthesis_v0.2",
        "summary": dict(summary or {}),
        "synthesis_execution_identity": {
            "start": identity.to_dict(),
            "completion": identity.to_dict(),
            "full_manifest_equality": True,
        },
    }


def _file_binding(label: str) -> dict[str, object]:
    return {
        "label": label,
        "kind": "path",
        "expectation": "required_file",
        "state": "file",
        "sha256": "a" * 64,
        "size_bytes": 1,
        "resolved_path": "C:/bound/file",
    }


def _source_profile() -> SimpleNamespace:
    bindings: dict[str, dict[str, object]] = {
        label: _file_binding(label)
        for label in (
            "python_executable",
            "sitecustomize_shim",
            "weather_package_shim",
            "corpus",
            "preregistration",
            "support_seal",
            "feasibility_seal",
            "runtime_support_correction",
            "runtime_support_helper",
            "tune_dates",
            "holdout_dates",
            *(f"wu_{market_id}_daily" for market_id in TERMINAL_MARKET_IDS),
        )
    }
    bindings["python_executable"]["resolved_path"] = "C:/python.exe"
    sealed = _sealed_receipts()
    for label in ("runtime_support_correction", "runtime_support_helper"):
        bindings[label].update(
            resolved_path=f"sealed/{label}",
            sha256=sealed[label]["sha256"],
            size_bytes=sealed[label]["size_bytes"],
            mtime_ns=sealed[label]["mtime_ns"],
        )
    bindings["active_release_pointer"] = {
        "label": "active_release_pointer",
        "kind": "path",
        "expectation": "absent",
        "state": "absent",
        "absence_anchor": {"existing_parent": "artifacts/releases"},
    }
    bindings["failed_generation_001"] = {
        "label": "failed_generation_001",
        "kind": "path",
        "expectation": "absent",
        "state": "absent",
        "absence_anchor": {"existing_parent": "source"},
    }
    tree_names = {
        "weather_source_tree",
        "artifact_tree",
        "config_tree",
        *(f"wu_{market_id}_hourly" for market_id in TERMINAL_MARKET_IDS),
    }
    for label in tree_names:
        bindings[label] = {
            "label": label,
            "kind": "tree",
            "state": "directory",
            "files": [
                {
                    "relative_path": "one.json",
                    "sha256": "b" * 64,
                    "size_bytes": 1,
                }
            ],
        }
    for index in range(309):
        bindings[f"corpus_{index:03d}_tape"] = _file_binding(
            f"corpus_{index:03d}_tape"
        )
        bindings[f"corpus_{index:03d}_replay"] = _file_binding(
            f"corpus_{index:03d}_replay"
        )
        label = f"corpus_{index:03d}_reconstructed"
        bindings[label] = {
            "label": label,
            "kind": "path",
            "expectation": "file_or_absent",
            "state": "absent",
            "absence_anchor": {"existing_parent": "snapshots"},
        }
    required_imports = {
        "joblib",
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        "weather",
        "weather.backtesting.replay_ablation",
        "weather.model.feature_store",
        "weather.model.toronto_model",
        "weather.reporting.research.source_ablation_hardened",
    }
    imports = [
        {
            "name": name,
            "resolved_file": (
                "C:/bound/file"
                if name == "weather"
                else (
                    f"src/weather/{name.removeprefix('weather.').replace('.', '/')}.py"
                    if name.startswith("weather.")
                    else f"C:/modules/{name.replace('.', '/')}.py"
                )
            ),
            "sha256": ("a" if name == "weather" else "c") * 64,
            "size_bytes": 1,
        }
        for name in sorted(required_imports)
    ]
    identity = {
        "base_root": "C:/repo",
        "bindings": list(bindings.values()),
        "environment": {
            "selection": {"import_names": sorted(required_imports)},
            "imports": imports,
            "packages": [
                {"name": name, "version": "1"}
                for name in ("joblib", "numpy", "pandas", "scipy", "scikit-learn")
            ],
            "runtime": {
                "implementation": "cpython",
                "python_version": "3.11",
                "executable": "C:/python.exe",
                "sys_path": [
                    {"raw": "", "resolved": "."},
                    {"raw": "C:/repo/src", "resolved": "src"},
                ],
            },
        },
        "invocation": {
            "cwd": "C:/repo",
            "argv": ["python", "-m", "source"],
            "run_parameters": {
                "profile": "workstation_source_ablation_hardened_v0.1",
                "model_binding": "RESEARCH_UNBOUND",
                "variants": list(ALL_VARIANTS),
                "market_ids": list(TERMINAL_MARKET_IDS),
                "support_sha256": hardened.TERMINAL_SUPPORT_SHA256,
                "preregistration_sha256": hardened.TERMINAL_PREREGISTRATION_SHA256,
                "feasibility_sha256": hardened.TERMINAL_FEASIBILITY_SHA256,
                "runtime_support_correction_sha256": (
                    hardened.TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256
                ),
                "runtime_support_helper_sha256": sealed[
                    "runtime_support_helper"
                ]["sha256"],
                "runtime_support_pairs_sha256": "1" * 64,
                "retry_generation_leaf": hardened.RETRY_GENERATION_LEAF,
                "corpus_hash": hardened.TERMINAL_CORPUS_HASH,
            },
        },
    }
    return SimpleNamespace(identity=identity, identity_digest="f" * 64)


def test_holm_adjust_is_step_down_monotone_and_market_family_is_global():
    assert holm_adjust([0.03, 0.01, 0.04, 1.0]) == pytest.approx(
        [0.09, 0.04, 0.09, 1.0]
    )
    rows = [
        {
            "variant": f"v{index}",
            "split": "holdout",
            "market_id": "x",
            "brier_delta": _metric(p_value),
            "logloss_delta": _metric(p_value),
        }
        for index, p_value in enumerate((0.001, 0.02, 0.5))
    ]
    corrected = add_market_holm_adjustments(rows)
    assert [
        row["brier_delta"]["multiplicity"]["adjusted_p"] for row in corrected
    ] == pytest.approx([0.003, 0.04, 0.5])


def test_ordered_split_dates_restores_producer_order_after_sorted_json():
    sorted_json_order = {
        "holdout": ["2026-06-22"],
        "tune": ["2026-06-03"],
    }
    ordered = hardened._ordered_split_dates(sorted_json_order)
    assert list(ordered) == ["tune", "holdout"]
    assert ordered == {
        "tune": ["2026-06-03"],
        "holdout": ["2026-06-22"],
    }
    with pytest.raises(ValueError, match="split mapping"):
        hardened._ordered_split_dates({"holdout": []})


def test_public_synthesize_requires_terminal_paths_and_exactly_one_artifact(
    monkeypatch,
):
    with pytest.raises(TypeError):
        synthesize([])  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="exactly one"):
        hardened.synthesize_hardened(
            ("one", "two"),
            repo_root="repo",
            preregistration_path="prereg",
            support_path="support",
            feasibility_path="feasibility",
            runtime_support_correction_path="correction",
            helpers={},
        )
    observed: dict[str, object] = {}

    def fake(paths, **kwargs):
        observed.update(paths=paths, **kwargs)
        return {"ok": True}

    monkeypatch.setattr(hardened, "synthesize_hardened", fake)
    assert synthesize(
        ("only.json",),
        repo_root="repo",
        preregistration_path="prereg.json",
        support_path="support.json",
        feasibility_path="feasibility.json",
        runtime_support_correction_path="correction.json",
    ) == {"ok": True}
    assert observed["paths"] == ("only.json",)
    assert observed["repo_root"] == "repo"
    assert observed["runtime_support_correction_path"] == "correction.json"


def test_runtime_correction_load_pins_live_helper_and_source_receipts(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    helper = repo / "src" / "weather" / "backtesting" / "source_ablation_contract.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("X = 1\n", encoding="utf-8")
    correction_path = tmp_path / "correction.json"
    correction_path.write_text(
        json.dumps(
            {
                "schema_version": hardened.CORRECTION_SCHEMA_VERSION,
                "all_44_parity": {"pairs_sha256": "1" * 64},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hardened,
        "TERMINAL_RUNTIME_SUPPORT_CORRECTION_SHA256",
        _sha(correction_path),
    )
    helper_receipt = hardened.stable_file_receipt(helper)
    observed: dict[str, object] = {}

    def validate(payload, **kwargs):
        observed.update(payload=payload, **kwargs)
        return {
            "helper_path": helper,
            "helper_receipt": helper_receipt,
            "pairs": [],
            "pairs_sha256": "1" * 64,
            "failed_generation_path": (
                Path(kwargs["generation_dir"]).with_name(
                    "sealed-source-ablation-v0.1-generation-001"
                )
            ),
        }

    monkeypatch.setattr(hardened, "validate_runtime_support_correction", validate)
    correction_receipt = hardened.stable_file_receipt(correction_path)
    artifact = {
        "corpus": {"corpus_hash": "corpus-hash"},
        "sealed_contracts": {
            "corpus": {"sha256": "c" * 64},
            "tune_dates": {"sha256": "d" * 64},
            "holdout_dates": {"sha256": "e" * 64},
            "runtime_support_correction": correction_receipt,
            "runtime_support_helper": helper_receipt,
        },
    }
    support = {
        "admitted_replay_rows": 44_178,
        "provenance": {
            "replay_input_manifest_sha256": "a" * 64,
            "replay_input_file_count": 309,
        },
    }
    source_generation = tmp_path / hardened.RETRY_GENERATION_LEAF
    evidence = hardened._load_validate_runtime_support_correction(
        correction_path=correction_path,
        repo_root=repo,
        source_generation_dir=source_generation,
        artifact=artifact,
        support=support,
        preregistration_sha256="p" * 64,
        support_sha256="s" * 64,
        feasibility_sha256="f" * 64,
    )
    assert evidence["receipt"] == correction_receipt
    assert evidence["helper_receipt"] == helper_receipt
    assert observed["generation_dir"] == source_generation
    assert observed["predecessor_hashes"]["pinned_record_count"] == 44_178

    artifact["sealed_contracts"]["runtime_support_helper"] = {
        **helper_receipt,
        "sha256": "0" * 64,
    }
    with pytest.raises(ValueError, match="helper receipt differs"):
        hardened._load_validate_runtime_support_correction(
            correction_path=correction_path,
            repo_root=repo,
            source_generation_dir=source_generation,
            artifact=artifact,
            support=support,
            preregistration_sha256="p" * 64,
            support_sha256="s" * 64,
            feasibility_sha256="f" * 64,
        )


def test_direct_loose_leaf_publication_is_disabled(tmp_path):
    with pytest.raises(SourceAblationSynthesisError, match="generation-dir"):
        write_outputs(
            {},
            output_json=tmp_path / "out.json",
            output_report=tmp_path / "out.md",
        )
    assert not list(tmp_path.iterdir())


def test_source_generation_commit_accepts_exact_complete_generation(tmp_path):
    artifact_path, artifact = _source_generation(tmp_path)
    receipt = hardened._validate_source_generation_commit(artifact_path, artifact)
    assert receipt["outputs"][hardened.SOURCE_ARTIFACT_NAME]["sha256"] == _sha(
        artifact_path
    )
    assert receipt["metadata"]["variant_count"] == 22


@pytest.mark.parametrize("mutation", ("missing_complete", "artifact", "report"))
def test_source_generation_commit_rejects_missing_or_mutated_outputs(
    tmp_path, mutation
):
    artifact_path, artifact = _source_generation(tmp_path)
    generation = artifact_path.parent
    if mutation == "missing_complete":
        (generation / hardened.SOURCE_COMPLETE_NAME).unlink()
        match = "exactly the two outputs"
    elif mutation == "artifact":
        artifact_path.write_text(json.dumps({**artifact, "mutated": True}), encoding="utf-8")
        match = "differs from COMPLETE"
    else:
        (generation / hardened.SOURCE_REPORT_NAME).write_text("changed", encoding="utf-8")
        match = "differs from COMPLETE"
    with pytest.raises(ValueError, match=match):
        hardened._validate_source_generation_commit(artifact_path, artifact)


def test_source_generation_commit_rejects_alias_mutation_surface(tmp_path):
    artifact_path, artifact = _source_generation(tmp_path)
    report = artifact_path.parent / hardened.SOURCE_REPORT_NAME
    alias = tmp_path / "report-alias.md"
    try:
        os.link(report, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with pytest.raises(ValueError, match="one hard link"):
        hardened._validate_source_generation_commit(artifact_path, artifact)


@pytest.mark.parametrize("field", ("terminal_seals", "execution_identity", "metadata"))
def test_source_generation_commit_rejects_wrong_seal_execution_or_profile(
    tmp_path, field
):
    artifact_path, artifact = _source_generation(tmp_path)
    complete_path = artifact_path.parent / hardened.SOURCE_COMPLETE_NAME
    commit = json.loads(complete_path.read_text(encoding="utf-8"))
    if field == "terminal_seals":
        commit[field]["support"]["sha256"] = "0" * 64
        match = "terminal-seal"
    elif field == "execution_identity":
        commit[field]["start_digest"] = "0" * 64
        match = "execution digest"
    else:
        commit[field]["profile"] = "weaker-profile"
        match = "metadata"
    complete_path.write_text(json.dumps(commit), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        hardened._validate_source_generation_commit(artifact_path, artifact)


def test_source_execution_profile_requires_shims_imports_runtime_and_profile(
    monkeypatch,
):
    start = _source_profile()
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (start, start),
    )
    artifact = {
        "sealed_contracts": _sealed_receipts(),
        "execution_identity": {
            "start": {},
            "completion": {},
            "full_manifest_equality": True,
        }
    }
    correction = {"all_44_parity": {"pairs_sha256": "1" * 64}}
    assert hardened._validate_execution_profile(artifact, correction) == "f" * 64

    wrong_receipt_path = copy.deepcopy(start)
    next(
        row
        for row in wrong_receipt_path.identity["bindings"]
        if row["label"] == "runtime_support_correction"
    )["resolved_path"] = "sealed/different-correction.json"
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (wrong_receipt_path, wrong_receipt_path),
    )
    with pytest.raises(ValueError, match="binding differs"):
        hardened._validate_execution_profile(artifact, correction)

    wrong_receipt_mtime = copy.deepcopy(start)
    next(
        row
        for row in wrong_receipt_mtime.identity["bindings"]
        if row["label"] == "runtime_support_helper"
    )["mtime_ns"] = 2
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (wrong_receipt_mtime, wrong_receipt_mtime),
    )
    with pytest.raises(ValueError, match="binding differs"):
        hardened._validate_execution_profile(artifact, correction)

    escaping_receipt_path = copy.deepcopy(start)
    next(
        row
        for row in escaping_receipt_path.identity["bindings"]
        if row["label"] == "runtime_support_correction"
    )["resolved_path"] = "../sealed/runtime_support_correction"
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (escaping_receipt_path, escaping_receipt_path),
    )
    with pytest.raises(ValueError, match="escaping relative path"):
        hardened._validate_execution_profile(artifact, correction)

    without_shim = copy.deepcopy(start)
    without_shim.identity["bindings"] = [
        row
        for row in without_shim.identity["bindings"]
        if row["label"] != "sitecustomize_shim"
    ]
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (without_shim, without_shim),
    )
    with pytest.raises(ValueError, match="missing bindings"):
        hardened._validate_execution_profile(artifact, correction)

    wrong_profile = copy.deepcopy(start)
    wrong_profile.identity["invocation"]["run_parameters"]["profile"] = "old"
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (wrong_profile, wrong_profile),
    )
    with pytest.raises(ValueError, match="profile ID"):
        hardened._validate_execution_profile(artifact, correction)

    missing_sys_path = copy.deepcopy(start)
    missing_sys_path.identity["environment"]["runtime"]["sys_path"] = []
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (missing_sys_path, missing_sys_path),
    )
    with pytest.raises(ValueError, match="runtime inventory"):
        hardened._validate_execution_profile(artifact, correction)

    bypassed_weather = copy.deepcopy(start)
    weather_row = next(
        row
        for row in bypassed_weather.identity["environment"]["imports"]
        if row["name"] == "weather"
    )
    weather_row["resolved_file"] = "C:/unbound/weather/__init__.py"
    monkeypatch.setattr(
        hardened,
        "assert_serialized_completion_matches",
        lambda _start, _completion: (bypassed_weather, bypassed_weather),
    )
    with pytest.raises(ValueError, match="bypasses the bound shim"):
        hardened._validate_execution_profile(artifact, correction)


def test_synthesis_closure_binds_source_commit_shims_trees_runtime_and_argv(tmp_path):
    repo = tmp_path / "repo"
    (repo / "weather").mkdir(parents=True)
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / "artifacts" / "releases").mkdir(parents=True)
    (repo / "config").mkdir()
    (repo / "sitecustomize.py").write_text("# shim\n", encoding="utf-8")
    (repo / "weather" / "__init__.py").write_text("# shim\n", encoding="utf-8")
    (repo / "src" / "weather" / "one.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "artifacts" / "one.json").write_text("{}", encoding="utf-8")
    (repo / "config" / "one.json").write_text("{}", encoding="utf-8")
    data_root = tmp_path / "data"
    data_root.mkdir()
    artifact_path, artifact = _source_generation(tmp_path)
    source_generation = hardened._validate_source_generation_commit(
        artifact_path, artifact
    )
    seals = []
    for name in ("prereg", "support", "feasibility"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        seals.append(path)
    correction_path = tmp_path / "correction.json"
    helper_path = repo / "src" / "weather" / "helper.py"
    correction_path.write_text("{}", encoding="utf-8")
    helper_path.write_text("X = 2\n", encoding="utf-8")
    correction_evidence = {
        "path": correction_path,
        "receipt": {
            "path": str(correction_path.resolve()),
            "sha256": _sha(correction_path),
            "size_bytes": correction_path.stat().st_size,
            "mtime_ns": correction_path.stat().st_mtime_ns,
        },
        "helper_path": helper_path,
        "helper_receipt": {
            "path": str(helper_path.resolve()),
            "sha256": _sha(helper_path),
            "size_bytes": helper_path.stat().st_size,
            "mtime_ns": helper_path.stat().st_mtime_ns,
        },
        "validation": {
            "pairs_sha256": "1" * 64,
            "failed_generation_path": artifact_path.parent.with_name(
                "sealed-source-ablation-v0.1-generation-001"
            ),
        },
    }
    output = tmp_path / "output" / "generation"
    output.parent.mkdir()
    closure = hardened.build_synthesis_closure(
        repo_root=repo,
        data_root=data_root,
        artifact_path=artifact_path,
        source_generation=source_generation,
        preregistration_path=seals[0],
        support_path=seals[1],
        feasibility_path=seals[2],
        runtime_support_correction=correction_evidence,
        generation_dir=output,
    )
    path_labels = {binding.label for binding in closure.path_bindings}
    tree_labels = {binding.label for binding in closure.tree_bindings}
    assert {
        "python_executable",
        "sitecustomize_shim",
        "weather_package_shim",
        "source_artifact",
        "source_generation_complete",
        "preregistration",
        "support_seal",
        "feasibility_seal",
        "runtime_support_correction",
        "runtime_support_helper",
        "failed_generation_001",
        "active_release_pointer",
    } <= path_labels
    assert {
        "source_generation_tree",
        "weather_source_tree",
        "artifact_tree",
        "config_tree",
    } == tree_labels
    assert "weather" in closure.environment.import_names
    assert closure.invocation.argv
    assert closure.invocation.run_parameters["source_complete_sha256"] == source_generation[
        "complete"
    ]["sha256"]
    assert (
        closure.invocation.run_parameters["runtime_support_helper_sha256"]
        == correction_evidence["helper_receipt"]["sha256"]
    )


def test_synthesis_generation_commits_both_outputs_last(tmp_path):
    _, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for path in (data_root, source_root, output_parent):
        path.mkdir()
    generation_dir = output_parent / "generation"
    commit = hardened.publish_synthesis_generation(
        generation_dir=generation_dir,
        data_root=data_root,
        source_generation_dir=source_root,
        payload=_synthesis_publication_payload(
            start, summary={"variant_count": 22}
        ),
        report="# synthesis\n",
        start=start,
        closure=closure,
        terminal_seals={"support": {"sha256": "a" * 64}},
    )
    assert commit["status"] == "COMPLETE"
    assert commit["execution_identity"]["identical_full_manifest"] is True
    assert {row["name"] for row in commit["outputs"]} == {
        hardened.SYNTHESIS_ARTIFACT_NAME,
        hardened.SYNTHESIS_REPORT_NAME,
    }
    assert (generation_dir / "COMPLETE.json").is_file()


def test_synthesis_generation_retains_failed_partial_without_complete(
    tmp_path, monkeypatch
):
    _, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for path in (data_root, source_root, output_parent):
        path.mkdir()
    generation_dir = output_parent / "generation"

    def fail_report(self, relative_name, text):
        del self, relative_name, text
        raise RuntimeError("injected report failure")

    monkeypatch.setattr(hardened.ResearchGeneration, "publish_text", fail_report)
    with pytest.raises(RuntimeError, match="injected"):
        hardened.publish_synthesis_generation(
            generation_dir=generation_dir,
            data_root=data_root,
            source_generation_dir=source_root,
            payload=_synthesis_publication_payload(start),
            report="# report\n",
            start=start,
            closure=closure,
            terminal_seals={"support": {"sha256": "a" * 64}},
        )
    assert generation_dir.is_dir()
    assert not (generation_dir / "COMPLETE.json").exists()


def test_synthesis_generation_recaptures_closure_after_writing_outputs(
    tmp_path, monkeypatch
):
    bound, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for path in (data_root, source_root, output_parent):
        path.mkdir()
    generation_dir = output_parent / "generation"
    original = hardened.ResearchGeneration.publish_text

    def publish_then_drift(self, relative_name, text):
        receipt = original(self, relative_name, text)
        bound.write_text("changed after output publication", encoding="utf-8")
        return receipt

    monkeypatch.setattr(
        hardened.ResearchGeneration, "publish_text", publish_then_drift
    )
    with pytest.raises(ExecutionIdentityDriftError, match="execution identity changed"):
        hardened.publish_synthesis_generation(
            generation_dir=generation_dir,
            data_root=data_root,
            source_generation_dir=source_root,
            payload=_synthesis_publication_payload(start),
            report="# report\n",
            start=start,
            closure=closure,
            terminal_seals={"support": {"sha256": "a" * 64}},
        )
    assert generation_dir.is_dir()
    assert not (generation_dir / "COMPLETE.json").exists()


def test_synthesis_generation_race_never_removes_competitor(tmp_path):
    _, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for path in (data_root, source_root, output_parent):
        path.mkdir()
    generation_dir = output_parent / "generation"
    generation_dir.mkdir()
    sentinel = generation_dir / "competitor.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        hardened.publish_synthesis_generation(
            generation_dir=generation_dir,
            data_root=data_root,
            source_generation_dir=source_root,
            payload=_synthesis_publication_payload(start),
            report="# report\n",
            start=start,
            closure=closure,
            terminal_seals={"support": {"sha256": "a" * 64}},
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "embedded_identity",
    (
        None,
        {},
        {"start": {}},
        {"start": {}, "completion": {}},
        {"start": "not-a-manifest", "completion": "not-a-manifest"},
    ),
)
def test_synthesis_generation_requires_embedded_completion_before_creation(
    tmp_path, embedded_identity
):
    _, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    output_parent = tmp_path / "output"
    for path in (data_root, source_root, output_parent):
        path.mkdir()
    generation_dir = output_parent / "generation"
    payload: dict[str, object] = {
        "schema_version": "source_ablation_synthesis_v0.2",
        "summary": {},
    }
    if embedded_identity is not None:
        payload["synthesis_execution_identity"] = embedded_identity

    with pytest.raises(
        (ValueError, ExecutionIdentityError),
        match=(
            "(?i)synthesis.*execution.*identity|"
            "execution-identity (?:manifest|schema)"
        ),
    ):
        hardened.publish_synthesis_generation(
            generation_dir=generation_dir,
            data_root=data_root,
            source_generation_dir=source_root,
            payload=payload,
            report="# report\n",
            start=start,
            closure=closure,
            terminal_seals={"support": {"sha256": "a" * 64}},
        )

    assert not os.path.lexists(generation_dir)


def test_synthesis_generation_rejects_read_only_data_and_source_roots(tmp_path):
    _, closure, start = _publication_closure(tmp_path)
    data_root = tmp_path / "data"
    source_root = tmp_path / "source"
    data_root.mkdir()
    source_root.mkdir()
    common = {
        "payload": _synthesis_publication_payload(start),
        "report": "# report\n",
        "start": start,
        "closure": closure,
        "terminal_seals": {"support": {"sha256": "a" * 64}},
        "data_root": data_root,
        "source_generation_dir": source_root,
    }
    with pytest.raises(ValueError, match="read-only root"):
        hardened.publish_synthesis_generation(
            generation_dir=data_root / "forbidden",
            **common,
        )
    with pytest.raises(ValueError, match="read-only root"):
        hardened.publish_synthesis_generation(
            generation_dir=source_root / "forbidden",
            **common,
        )
    assert not list(data_root.iterdir())
    assert not list(source_root.iterdir())


def test_parser_has_only_generation_publication_mode():
    parser = hardened.build_parser()
    args = parser.parse_args(
        [
            "source_family_ablation.json",
            "--repo-root",
            "repo",
            "--data-root",
            "data",
            "--preregistration",
            "prereg.json",
            "--support-seal",
            "support.json",
            "--feasibility-seal",
            "feas.json",
            "--runtime-support-correction-seal",
            "correction.json",
            "--generation-dir",
            "generation",
        ]
    )
    assert args.generation_dir == "generation"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "source_family_ablation.json",
                "--repo-root",
                "repo",
                "--data-root",
                "data",
                "--preregistration",
                "prereg.json",
                "--support-seal",
                "support.json",
                "--feasibility-seal",
                "feas.json",
                "--runtime-support-correction-seal",
                "correction.json",
                "--generation-dir",
                "generation",
                "--out",
                "loose.json",
            ]
        )
