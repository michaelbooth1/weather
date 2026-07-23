from pathlib import Path

import pytest

from weather.execution_identity import (
    EnvironmentSpec,
    InvocationSpec,
    capture_execution_identity,
)
from weather.reporting.research import ordinal_smoothing_execution_closure as closure


def _fixture_layout(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / "src" / "weather" / "owner.py").write_text("OWNER = True\n", encoding="utf-8")
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "model.json").write_text("{}\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "markets.yaml").write_text("markets: []\n", encoding="utf-8")
    data = tmp_path / "data"
    snapshots = data / "snapshots"
    folder = snapshots / "toronto-2026-06-03"
    folder.mkdir(parents=True)
    (folder / "replay_inputs.jsonl").write_text("{}\n", encoding="utf-8")
    (folder / "snapshots.jsonl").write_text("{}\n", encoding="utf-8")
    (folder / "snapshots_long.csv").write_text("snapshot_id\n", encoding="utf-8")
    wu = data / "wunderground" / "cyyz"
    (wu / "daily").mkdir(parents=True)
    (wu / "daily" / "daily_summary.csv").write_text("date,max_temp\n", encoding="utf-8")
    hourly = wu / "hourly" / "year=2026" / "month=06"
    hourly.mkdir(parents=True)
    (hourly / "observations.jsonl").write_text("{}\n", encoding="utf-8")
    corpus = tmp_path / "corpus.json"
    corpus.write_text("{}\n", encoding="utf-8")
    contract = tmp_path / "dates.txt"
    contract.write_text("2026-06-03\n", encoding="utf-8")
    entries = [
        {
            "market_id": "toronto",
            "target_date": "2026-06-03",
            "event_slug": "toronto-2026-06-03",
            "folder_relative_to_snapshots_root": "toronto-2026-06-03",
        }
    ]
    return repo, data, snapshots, corpus, contract, entries


def _invocation() -> InvocationSpec:
    return InvocationSpec.current(run_parameters={"partition": "tune", "case": "fixture"})


def test_closure_binds_source_graph_pointers_tapes_reconstruction_and_wu(tmp_path):
    repo, data, snapshots, corpus, contract, entries = _fixture_layout(tmp_path)
    spec = closure.build_replay_closure_spec(
        name="fixture",
        repo_root=repo,
        staged_data_root=data,
        snapshots_root=snapshots,
        corpus_path=corpus,
        entries=entries,
        invocation=_invocation(),
        required_contract_files=(("dates", contract),),
        environment=EnvironmentSpec(include_packages=False),
    )
    manifest = capture_execution_identity(spec)
    bindings = {row["label"]: row for row in manifest.identity["bindings"]}
    assert bindings["canonical_source"]["file_count"] == 1
    assert bindings["artifact_graph"]["file_count"] == 1
    assert bindings["configuration_graph"]["file_count"] == 1
    assert bindings["release_pointer_absent:1"]["state"] == "absent"
    assert bindings["release_pointer_absent:2"]["state"] == "absent"
    reconstructed = next(
        row for label, row in bindings.items() if label.startswith("reconstructed_replay:")
    )
    assert reconstructed["state"] == "absent"
    assert bindings["wu_hourly:toronto"]["file_count"] == 1
    lineage = closure.execution_lineage(manifest)
    assert lineage["model_graph"] == "RESEARCH_UNBOUND"
    assert lineage["active_or_current_production_claimed"] is False


def test_pointer_presence_blocks_research_unbound_closure(tmp_path):
    repo, data, snapshots, corpus, contract, entries = _fixture_layout(tmp_path)
    pointer = repo / "artifacts" / "releases" / "current_release.json"
    pointer.parent.mkdir()
    pointer.write_text("{}\n", encoding="utf-8")
    spec = closure.build_replay_closure_spec(
        name="fixture",
        repo_root=repo,
        staged_data_root=data,
        snapshots_root=snapshots,
        corpus_path=corpus,
        entries=entries,
        invocation=_invocation(),
        required_contract_files=(("dates", contract),),
        environment=EnvironmentSpec(include_packages=False),
    )
    from weather.execution_identity import ExecutionIdentityError

    with pytest.raises(ExecutionIdentityError, match="required absent"):
        capture_execution_identity(spec)


def test_research_smoothing_configs_are_explicit_and_unit_aware():
    w0 = closure.research_smoothing_config(None, "C")
    assert w0 == {
        "enabled": False,
        "sigma": 0.0,
        "blend_weight": 0.0,
        "source": "research_explicit_w0",
        "model_graph": "RESEARCH_UNBOUND",
    }
    physical = {"C": 0.75, "F": 1.25}
    assert closure.research_smoothing_config(physical, "C")["sigma"] == 0.75
    assert closure.research_smoothing_config(physical, "F")["sigma"] == 2.25
    assert closure.research_smoothing_config(physical, "F")["blend_weight"] == 1.0
    with pytest.raises(closure.ClosureConfigurationError):
        closure.research_smoothing_config({"C": 0.75}, "C")


def test_candidate_replay_version_is_distinct_stable_and_configuration_bound():
    base = "weather-hgb-v1"
    selected = {"C": 0.75, "F": 1.25}
    assert closure.research_replay_model_version(base, None) == base
    first = closure.research_replay_model_version(base, selected)
    assert first == closure.research_replay_model_version(base, dict(selected))
    assert first.startswith(base + "+research-h1-physical-")
    assert first != closure.research_replay_model_version(
        base, {"C": 1.25, "F": 1.25}
    )


def test_partition_arm_enforces_baseline_fidelity_and_candidate_identity(
    tmp_path, monkeypatch
):
    from weather.backtesting import replay_backtest

    fidelity = {
        "same_identity_n": 1,
        "same_identity_mean_l1": 0.25,
        "same_identity_max_l1": 0.25,
        "same_identity_faithful": False,
    }

    def fake_replay(*_args, **_kwargs):
        return {
            "snaps_in_corpus": 1,
            "snaps_scored": 1,
            "total_rows": 1,
            "replayed_versions": [],
            "fidelity": dict(fidelity),
            "band_semantics": {},
            "corpus_warnings": [],
            "all_rows": [],
            "distribution_rows": [],
        }

    monkeypatch.setattr(replay_backtest, "run_replay_backtest", fake_replay)
    common = {
        "partition": "fixture",
        "folders": [],
        "corpus_manifest": {},
        "staged_data_root": tmp_path,
        "scratch_output_root": tmp_path,
    }
    baseline = closure.run_partition_arm(
        arm_name="w0", physical_c_sigma_by_family=None, **common
    )
    assert "same-identity replay fidelity canary failed" in baseline["replay"]["blockers"]
    assert baseline["replay"]["fidelity_semantics"]["same_identity_required"] is True

    candidate = closure.run_partition_arm(
        arm_name="candidate",
        physical_c_sigma_by_family={"C": 0.75, "F": 1.25},
        **common,
    )
    assert (
        "intentional candidate transform retained captured replay identity"
        in candidate["replay"]["blockers"]
    )
    fidelity.update(
        same_identity_n=0,
        same_identity_mean_l1=None,
        same_identity_max_l1=None,
        same_identity_faithful=False,
    )
    distinct = closure.run_partition_arm(
        arm_name="candidate-distinct",
        physical_c_sigma_by_family={"C": 0.75, "F": 1.25},
        **common,
    )
    assert not any("identity" in item for item in distinct["replay"]["blockers"])
    assert distinct["replay"]["fidelity_semantics"]["same_identity_forbidden"] is True


def test_snapshot_folder_escape_is_rejected(tmp_path):
    repo, data, snapshots, corpus, contract, entries = _fixture_layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    entries[0]["folder_relative_to_snapshots_root"] = "../../outside"
    with pytest.raises(closure.ClosureConfigurationError, match="escapes"):
        closure.build_replay_closure_spec(
            name="fixture",
            repo_root=repo,
            staged_data_root=data,
            snapshots_root=snapshots,
            corpus_path=corpus,
            entries=entries,
            invocation=_invocation(),
            required_contract_files=(("dates", contract),),
            environment=EnvironmentSpec(include_packages=False),
        )


def test_closure_rejects_folder_alias_that_replay_would_not_read(tmp_path):
    repo, data, snapshots, corpus, contract, entries = _fixture_layout(tmp_path)
    entries[0]["folder_relative_to_snapshots_root"] = "toronto-2026-06-03"
    entries[0]["event_slug"] = "different-replay-folder"
    with pytest.raises(closure.ClosureConfigurationError, match="folder identity"):
        closure.build_replay_closure_spec(
            name="fixture",
            repo_root=repo,
            staged_data_root=data,
            snapshots_root=snapshots,
            corpus_path=corpus,
            entries=entries,
            invocation=_invocation(),
            required_contract_files=(("dates", contract),),
            environment=EnvironmentSpec(include_packages=False),
        )
