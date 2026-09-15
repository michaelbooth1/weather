"""Real Git progression through the checks called by the guarded primitive."""

import pytest

from test_qualification_merge_tree import merge_fixture
from weather.operations.qualification import merge_session, merge_tree, records


def checked_fixture(fixture):
    git, repo, baseline, candidate, graph, ref, expected, inventory, run = fixture
    run("update-ref", "refs/remotes/origin/master", baseline)
    source_ref = records.publish(graph.root, "source-inventory.json", inventory)
    return {"manifest": {"repo_root": str(repo), "worktree_root": str(repo), "expected_tip": candidate,
                         "baseline": {"master": baseline}, "branch_ref": "candidate"},
            "review": {"source": {"tree": run("rev-parse", candidate + "^{tree}")}, "source_inventory": source_ref},
            "host_plan": {"configuration": ref}, "graph": graph, "local": graph}


def boundary(fixture, checked, phase, prepared):
    return merge_session.tree_boundary(checked, fixture[0], phase=phase, prepared_baseline=prepared)


def prepare(fixture, checked):
    run, baseline = fixture[-1], fixture[2]
    for phase in ("prepare", "before-config"):
        boundary(fixture, checked, phase, baseline)
    run("add", "--", *merge_tree.GENERATED)
    run("commit", "-qm", "prepared Q fixture")
    prepared = run("rev-parse", "HEAD")
    for phase in ("prepared", "before-stage"):
        boundary(fixture, checked, phase, prepared)
    return prepared


def test_every_real_mutation_boundary_accepts_only_the_effective_tree(merge_fixture):
    fixture = merge_fixture
    checked, run = checked_fixture(fixture), fixture[-1]
    prepared = prepare(fixture, checked)
    run("merge", "--no-commit", "--no-ff", fixture[3])
    for phase in ("staged", "before-commit"):
        assert boundary(fixture, checked, phase, prepared)["effective_tree"] == fixture[6]["tree"]
    run("commit", "-qm", "guarded fixture")
    for phase in ("committed", "before-push"):
        assert boundary(fixture, checked, phase, prepared)["head"] == run("rev-parse", "HEAD")
    with pytest.raises(records.QualificationError, match="unacknowledged"):
        boundary(fixture, checked, "published", prepared)
    run("update-ref", "refs/remotes/origin/master", run("rev-parse", "HEAD"))
    assert boundary(fixture, checked, "published", prepared)["head"] == run("rev-parse", "HEAD")


@pytest.mark.parametrize("phase", ["prepare", "before-config", "prepared", "before-stage", "staged", "before-commit", "committed", "before-push", "published"])
def test_hidden_working_rewrite_refuses_at_every_boundary(merge_fixture, phase):
    fixture, run = merge_fixture, merge_fixture[-1]
    checked = checked_fixture(fixture)
    prepared = fixture[2]
    if phase not in {"prepare", "before-config"}:
        prepared = prepare(fixture, checked)
    if phase in {"staged", "before-commit", "committed", "before-push", "published"}:
        run("merge", "--no-commit", "--no-ff", fixture[3])
    if phase in {"committed", "before-push", "published"}:
        run("commit", "-qm", "guarded fixture")
    if phase == "published":
        run("update-ref", "refs/remotes/origin/master", run("rev-parse", "HEAD"))
    (fixture[1] / "module.py").write_bytes(b"unreviewed = True\n")
    with pytest.raises(records.QualificationError, match="working source/config"):
        boundary(fixture, checked, phase, prepared)


def test_resolution_staged_after_recovery_refuses_before_commit(merge_fixture):
    fixture, run = merge_fixture, merge_fixture[-1]
    checked = checked_fixture(fixture)
    prepared = prepare(fixture, checked)
    run("merge", "--no-commit", "--no-ff", fixture[3])
    boundary(fixture, checked, "staged", prepared)
    (fixture[1] / "module.py").write_bytes(b"unreviewed = True\n")
    run("add", "module.py")
    with pytest.raises(records.QualificationError, match="staged merge differs"):
        boundary(fixture, checked, "before-commit", prepared)


@pytest.mark.parametrize("ref", ["refs/remotes/origin/master", "refs/heads/candidate"])
def test_moved_source_or_published_ref_blocks_mutation(merge_fixture, ref):
    fixture = merge_fixture
    checked = checked_fixture(fixture)
    target = fixture[3] if ref.endswith("master") else fixture[2]
    fixture[-1]("update-ref", ref, target)
    with pytest.raises(records.QualificationError, match="moved"):
        boundary(fixture, checked, "before-config", fixture[2])
