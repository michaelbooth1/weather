"""Actual Git trees and each pre-publication mutation-boundary refusal."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from weather.operations.qualification import inputs, merge_tree, records, source
from weather.operations.qualification.contracts import Graph


@pytest.fixture
def merge_fixture(tmp_path):
    git = Path(shutil.which("git")).resolve()
    repo, config = tmp_path / "repo", tmp_path / "configuration"
    repo.mkdir()
    config.mkdir()

    def run(*args):
        result = subprocess.run(source.git_argv(git, repo, *args), env=source.git_environment(),
                                capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout.decode().strip()

    run("init", "-b", "master")
    run("config", "user.name", "Qualification fixture")
    run("config", "user.email", "fixture@example.invalid")
    run("config", "commit.gpgSign", "false")
    run("config", "core.autocrlf", "false")
    (repo / "config").mkdir()
    for name in merge_tree.GENERATED:
        (repo / name).write_bytes(b'{"generation":"old"}\n')
    (repo / "module.py").write_bytes(b"value = 1\n")
    (repo / "folder").mkdir()
    (repo / "folder.file").write_bytes(b"ordering fixture\n")
    (repo / "folder/file.txt").write_bytes(b"directory ordering fixture\n")
    run("add", ".")
    run("commit", "-qm", "baseline")
    baseline = run("rev-parse", "HEAD")
    run("checkout", "-qb", "candidate")
    (repo / "module.py").write_bytes(b"value = 2\n")
    run("add", ".")
    run("commit", "-qm", "candidate")
    candidate, tree = run("rev-parse", "HEAD"), run("rev-parse", "HEAD^{tree}")
    inventory = source.inventory(git, repo, candidate)
    run("checkout", "master")
    for name in merge_tree.GENERATED:
        (repo / name).write_bytes(b'{"generation":"frozen Q"}\n')
    roots = inputs.SourceRoots({"production": repo}, {"production": ["config"]}, relative_root="production")
    budget = inputs.ReadBudget(1024 * 1024, time.monotonic() + 60)
    stager = inputs.Stager(roots, config, budget)
    generated = []
    for name in merge_tree.GENERATED:
        entry = stager.stage(name, kind="config", mandatory=True)
        raw = (repo / name).read_bytes()
        generated.append({"path": name, "payload": entry["staged"], "generation": entry["generation"],
                          "git_blob": merge_tree.object_id("blob", raw)})
    dependencies = stager.seal()
    config_ref = records.publish(config, "configuration.json", {"schema": "qualification_configuration_v2",
                                "source": candidate, "baseline": baseline, "generated": generated, "dependencies": dependencies})
    graph = Graph(config)
    arguments = dict(source_commit=candidate, source_tree=tree, baseline=baseline,
                     config_graph=graph, configuration_ref=config_ref)
    before = (repo / ".git/index").read_bytes()
    expected = merge_tree.preview(git, repo, **arguments)
    assert (repo / ".git/index").read_bytes() == before
    return git, repo, baseline, candidate, graph, config_ref, expected, inventory, run


def stage(fixture):
    _, _, _, candidate, _, _, _, _, run = fixture
    run("add", "--", *merge_tree.GENERATED)
    run("commit", "-qm", "prepared generated configuration")
    prepared = run("rev-parse", "HEAD")
    run("merge", "--no-commit", "--no-ff", candidate)
    return prepared


def check_working(fixture):
    git, repo, _, candidate, graph, ref, _, inventory, _ = fixture
    return merge_tree.working_bytes(git, repo, source_root=repo, source_commit=candidate,
                                    source_inventory=inventory, config_graph=graph, configuration_ref=ref)


def test_predicted_tree_matches_actual_staged_and_two_parent_committed_tree(merge_fixture):
    git, repo, _, candidate, _, _, expected, _, run = merge_fixture
    prepared = stage(merge_fixture)
    merge_tree.staged_tree(git, repo, expected["tree"])
    check_working(merge_fixture)
    run("commit", "-qm", "exact guarded merge fixture")
    result = merge_tree.committed_tree(git, repo, expected_tree=expected["tree"], first_parent=prepared, source_commit=candidate)
    assert result == run("rev-parse", "HEAD")


def test_unstaged_source_change_cannot_hide_behind_correct_index(merge_fixture):
    git, repo, _, _, _, _, expected, _, _ = merge_fixture
    stage(merge_fixture)
    (repo / "module.py").write_bytes(b"value = 9\n")
    merge_tree.staged_tree(git, repo, expected["tree"])
    with pytest.raises(records.QualificationError, match="working source/config"):
        check_working(merge_fixture)


def test_staged_unreviewed_resolution_is_rejected(merge_fixture):
    git, repo, _, _, _, _, expected, _, run = merge_fixture
    stage(merge_fixture)
    (repo / "module.py").write_bytes(b"value = 9\n")
    run("add", "module.py")
    with pytest.raises(records.QualificationError, match="staged merge differs"):
        merge_tree.staged_tree(git, repo, expected["tree"])


def test_generated_config_rewrite_invalidates_generation_even_same_bytes(merge_fixture):
    _, repo, _, _, graph, ref, _, _, _ = merge_fixture
    path = repo / merge_tree.GENERATED[0]
    raw = path.read_bytes()
    path.write_bytes(raw)
    # Force a distinct observed generation even on coarse timestamp filesystems.
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 2_000_000))
    with pytest.raises(records.QualificationError, match="generation changed"):
        merge_tree.revalidate_generated(repo, graph, ref)


def test_wrong_merge_parent_never_satisfies_committed_boundary(merge_fixture):
    git, repo, baseline, candidate, _, _, expected, _, run = merge_fixture
    stage(merge_fixture)
    run("commit", "-qm", "fixture merge")
    with pytest.raises(records.QualificationError, match="two-parent"):
        merge_tree.committed_tree(git, repo, expected_tree=expected["tree"], first_parent=baseline, source_commit=candidate)
