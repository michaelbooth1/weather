"""Complete real Git/Q closure, including absent and newly appearing releases."""

import hashlib
import json
import time

import pytest

from weather.operations.qualification import host_configuration, inputs, merge_tree, records
from weather.operations.qualification.contracts import Graph
from test_qualification_merge_tree import merge_fixture


def seal(fixture, *, omit=None, optional=None):
    _, repo, baseline, candidate, _, _, _, _, _ = fixture
    root = repo.parent / "host-configuration"
    root.mkdir()
    roots = inputs.SourceRoots({"production": repo}, {"production": ["config", "artifacts"]},
                              relative_root="production")
    stager = inputs.Stager(roots, root, inputs.ReadBudget(1024**2, time.monotonic() + 60))
    generated = []
    for name in [*merge_tree.GENERATED, host_configuration.POINTER]:
        if name == omit:
            continue
        entry = stager.stage(name, kind="config", mandatory=name != host_configuration.POINTER and name != optional)
        if name in merge_tree.GENERATED:
            generated.append({"path": name, "payload": entry["staged"], "generation": entry["generation"],
                              "git_blob": merge_tree.object_id("blob", (repo / name).read_bytes())})
    ref = records.publish(root, "q.json", {"schema": "qualification_configuration_v2", "source": candidate,
        "baseline": baseline, "generated": generated, "dependencies": stager.seal()})
    return Graph(root), ref


def validate(fixture, graph, ref):
    git, repo, baseline, candidate, *_ = fixture
    return host_configuration.validate(git, repo, candidate=repo, source_commit=candidate, baseline=baseline,
        graph=graph, configuration_ref=ref, budget=inputs.ReadBudget(4 * 1024**2, time.monotonic() + 60))


def test_full_generated_pair_and_absent_pointer_are_bound(merge_fixture):
    graph, ref = seal(merge_fixture)
    result = validate(merge_fixture, graph, ref)
    assert result["file_count"] == 3
    assert result["current_pointer_present"] is False
    assert result["read_bytes"] > 0


def test_absent_pointer_cannot_be_omitted_from_q(merge_fixture):
    graph, ref = seal(merge_fixture, omit=host_configuration.POINTER)
    with pytest.raises(ValueError, match="closure is incomplete"):
        validate(merge_fixture, graph, ref)


def test_required_generated_input_cannot_be_downgraded(merge_fixture):
    graph, ref = seal(merge_fixture, optional=merge_tree.GENERATED[0])
    with pytest.raises(ValueError, match="downgraded"):
        validate(merge_fixture, graph, ref)


def test_new_pointer_after_seal_invalidates_absence_proof(merge_fixture):
    graph, ref = seal(merge_fixture)
    repo = merge_fixture[1]
    pointer = repo / host_configuration.POINTER
    pointer.parent.mkdir(parents=True)
    pointer.write_text('{"active_release_id":"new-release"}', encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        validate(merge_fixture, graph, ref)


def test_active_release_requires_the_complete_actual_file_inventory(merge_fixture):
    git, repo, baseline, candidate, *_ = merge_fixture
    release = repo / "artifacts/releases/fixture-release"
    release.mkdir(parents=True)
    (release.parent / "current_release.json").write_text('{"active_release_id":"fixture-release"}', encoding="utf-8")
    (release / "model.bin").write_bytes(b"opaque model, never deserialize")
    manifest = {"release_id": "fixture-release", "artifacts": {"inventory": [{"path": "model.bin"}]}}
    (release / "release_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    arguments = dict(source_commit=candidate, baseline=baseline,
                     budget=inputs.ReadBudget(1024**2, time.monotonic() + 60))
    required, optional = host_configuration.required_paths(git, repo, repo, **arguments)
    assert optional == []
    assert set(required) == {*merge_tree.GENERATED, host_configuration.POINTER,
        "artifacts/releases/fixture-release/release_manifest.json", "artifacts/releases/fixture-release/model.bin"}
    (release / "unlisted.bin").write_bytes(b"must block")
    with pytest.raises(ValueError, match="unlisted"):
        host_configuration.required_paths(git, repo, repo, **arguments)
