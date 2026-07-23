from __future__ import annotations

import json

import pytest

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityDriftError,
    InvocationSpec,
    PathBinding,
    capture_execution_identity,
)
from weather.reporting.research.source_ablation_hardened import (
    HardenedSourceAblationError,
    _canonicalize_variant_outputs,
    build_parser,
    build_source_closure,
    publish_complete_generation,
)
from weather.reporting.research.research_generation import ResearchGeneration
from weather.reporting.research.source_ablation_synthesis_hardened import (
    _validate_day_effect_support,
)
from weather.backtesting.source_ablation_contract import ALL_VARIANTS
from weather.backtesting.replay_ablation import paired_inference_sensitivities


def _payload(tmp_path):
    bound = tmp_path / "bound.json"
    bound.write_text('{"sealed": true}\n', encoding="utf-8")
    spec = ClosureSpec(
        name="source-publication-fixture",
        base_root=tmp_path,
        invocation=InvocationSpec.current(run_parameters={"case": "publication"}),
        path_bindings=(PathBinding("bound", bound),),
        environment=EnvironmentSpec(
            import_names=("json",),
            env_names=("PYTHONPATH",),
            env_prefixes=("WEATHER_",),
            include_packages=False,
        ),
    )
    start = capture_execution_identity(spec)
    completion = capture_execution_identity(spec)
    return {
        "schema_version": "source_family_ablation_v0.2",
        "summary": {"variant_count": 22, "market_days_scored": 309},
        "sealed_contracts": {"support": {"sha256": "a" * 64}},
        "execution_identity": {
            "start": start.to_dict(),
            "completion": completion.to_dict(),
            "full_manifest_equality": True,
        },
    }, spec


def test_source_generation_uses_complete_marker_as_final_commit(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    output_parent = tmp_path / "scratch"
    output_parent.mkdir()
    generation = output_parent / "generation-001"

    payload, closure = _payload(tmp_path)
    commit = publish_complete_generation(
        generation,
        data_root=data_root,
        payload=payload,
        report="# source result\n",
        closure=closure,
    )

    assert commit["status"] == "COMPLETE"
    assert commit["execution_identity"]["identical_full_manifest"] is True
    assert [row["name"] for row in commit["outputs"]] == [
        "source_family_ablation.json",
        "source_family_ablation.md",
    ]
    assert json.loads((generation / "COMPLETE.json").read_text(encoding="utf-8")) == commit
    assert (generation / "source_family_ablation.json").is_file()
    assert (generation / "source_family_ablation.md").is_file()


def test_source_generation_rejects_read_only_or_existing_destination(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    inside_parent = data_root / "analysis"
    inside_parent.mkdir()
    payload, closure = _payload(tmp_path)
    with pytest.raises(HardenedSourceAblationError, match="read-only data"):
        publish_complete_generation(
            inside_parent / "generation",
            data_root=data_root,
            payload=payload,
            report="forbidden",
            closure=closure,
        )

    outside_parent = tmp_path / "scratch"
    outside_parent.mkdir()
    existing = outside_parent / "generation"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(HardenedSourceAblationError, match="already exists"):
        publish_complete_generation(
            existing,
            data_root=data_root,
            payload=payload,
            report="must not replace",
            closure=closure,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_source_generation_rechecks_closure_after_writing_leaves(
    tmp_path, monkeypatch
):
    data_root = tmp_path / "data"
    data_root.mkdir()
    output_parent = tmp_path / "scratch"
    output_parent.mkdir()
    generation = output_parent / "generation-drift"
    payload, closure = _payload(tmp_path)
    bound = tmp_path / "bound.json"
    original_publish_text = ResearchGeneration.publish_text

    def publish_then_drift(self, relative_name, text):
        receipt = original_publish_text(self, relative_name, text)
        bound.write_text('{"sealed": false}\n', encoding="utf-8")
        return receipt

    monkeypatch.setattr(ResearchGeneration, "publish_text", publish_then_drift)
    with pytest.raises(ExecutionIdentityDriftError, match="final output inventory"):
        publish_complete_generation(
            generation,
            data_root=data_root,
            payload=payload,
            report="drift",
            closure=closure,
        )
    assert generation.is_dir()
    assert not (generation / "COMPLETE.json").exists()


def test_hardened_result_canonicalizes_all_variants_and_rejects_omission():
    summaries = [{"variant": variant} for variant in reversed(ALL_VARIANTS)]
    day_effects = {variant: [{"variant": variant}] for variant in reversed(ALL_VARIANTS)}
    ordered_summaries, ordered_effects = _canonicalize_variant_outputs(
        summaries, day_effects
    )
    assert [row["variant"] for row in ordered_summaries] == list(ALL_VARIANTS)
    assert tuple(ordered_effects) == ALL_VARIANTS

    with pytest.raises(HardenedSourceAblationError, match="exactly one"):
        _canonicalize_variant_outputs(summaries[:-1], day_effects)


def test_producer_parser_requires_runtime_support_correction():
    required = [
        "--repo-root", "repo",
        "--data-root", "data",
        "--snapshots-root", "snapshots",
        "--corpus", "corpus.json",
        "--preregistration", "prereg.json",
        "--support-seal", "support.json",
        "--feasibility-seal", "feasibility.json",
        "--tune-dates-file", "tune.txt",
        "--holdout-dates-file", "holdout.txt",
        "--generation-dir", "sealed-source-ablation-v0.1-generation-002",
    ]
    with pytest.raises(SystemExit):
        build_parser().parse_args(required)
    parsed = build_parser().parse_args(
        required
        + ["--runtime-support-correction-seal", "correction.json"]
    )
    assert parsed.runtime_support_correction_seal == "correction.json"


def test_producer_closure_binds_correction_helper_and_failed_leaf(tmp_path):
    repo = tmp_path / "repo"
    data = tmp_path / "data"
    snapshots = data / "snapshots"
    for path in (repo, data, snapshots):
        path.mkdir(parents=True, exist_ok=True)
    correction_path = tmp_path / "correction.json"
    helper_path = repo / "src/weather/backtesting/source_ablation_contract.py"
    helper_path.parent.mkdir(parents=True)
    correction_path.write_text("{}\n", encoding="utf-8")
    helper_path.write_text("# helper\n", encoding="utf-8")
    generation = tmp_path / "sealed-source-ablation-v0.1-generation-002"
    contracts = {
        "corpus": {"entries": [], "corpus_hash": "c" * 64},
        "corpus_path": tmp_path / "corpus.json",
        "preregistration_path": tmp_path / "prereg.json",
        "support_path": tmp_path / "support.json",
        "feasibility_path": tmp_path / "feasibility.json",
        "correction_path": correction_path,
        "helper_path": helper_path,
        "tune_path": tmp_path / "tune.txt",
        "holdout_path": tmp_path / "holdout.txt",
        "corpus_file_sha256": "1" * 64,
        "preregistration_sha256": "2" * 64,
        "support_sha256": "3" * 64,
        "feasibility_sha256": "4" * 64,
        "correction_sha256": "5" * 64,
        "helper_sha256": "6" * 64,
        "tune_dates": ("2026-06-01",),
        "holdout_dates": ("2026-06-02",),
        "correction_validation": {
            "pairs_sha256": "7" * 64,
            "failed_generation_path": generation.with_name(
                "sealed-source-ablation-v0.1-generation-001"
            ),
        },
    }
    closure = build_source_closure(
        repo_root=repo,
        data_root=data,
        snapshots_root=snapshots,
        contracts=contracts,
        generation_dir=generation,
    )
    labels = {binding.label for binding in closure.path_bindings}
    assert {
        "runtime_support_correction",
        "runtime_support_helper",
        "failed_generation_001",
    } <= labels
    parameters = closure.invocation.run_parameters
    assert parameters["runtime_support_correction_sha256"] == "5" * 64
    assert parameters["runtime_support_helper_sha256"] == "6" * 64
    assert parameters["retry_generation_leaf"] == generation.name


def test_synthesis_accepts_exact_day_effect_family_after_sorted_json_round_trip():
    serialized = json.dumps(
        {variant: [] for variant in ALL_VARIANTS}, sort_keys=True
    )
    round_tripped = json.loads(serialized)
    assert tuple(round_tripped) != ALL_VARIANTS
    support_rows = {
        variant: {
            "splits": {
                "tune": {"supported_market_days": []},
                "holdout": {"supported_market_days": []},
            }
        }
        for variant in ALL_VARIANTS
    }
    _validate_day_effect_support(round_tripped, support_rows)
    canonical = {variant: round_tripped[variant] for variant in ALL_VARIANTS}
    inference_args = {
        "split_dates": {"tune": [], "holdout": []},
        "required_market_ids": (),
    }
    expected = paired_inference_sensitivities(
        {variant: [] for variant in ALL_VARIANTS}, [], **inference_args
    )
    assert paired_inference_sensitivities(
        round_tripped, [], **inference_args
    ) != expected
    assert paired_inference_sensitivities(canonical, [], **inference_args) == expected

    del round_tripped[ALL_VARIANTS[0]]
    with pytest.raises(ValueError, match="exact variant family"):
        _validate_day_effect_support(round_tripped, support_rows)
