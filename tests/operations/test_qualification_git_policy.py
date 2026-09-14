"""Real Git configuration and working attributes cannot change interpretation."""

from pathlib import Path

import pytest

from weather.operations.qualification import environment, git_policy, records
from weather.operations.qualification.contracts import Graph
from test_qualification_merge_tree import merge_fixture


def policy(fixture):
    git, repo, baseline, candidate, *_ = fixture
    hooks = repo.parent / "empty-hooks"
    hooks.mkdir()
    args = dict(git=git, production=repo, candidate=repo, baseline=baseline, commit=candidate,
                graph=None, environment_ref=None, bindings=None)
    value = git_policy.capture(**args, hooks=hooks)
    return args, value


def test_actual_git_policy_is_stable_without_touching_the_index(merge_fixture):
    args, value = policy(merge_fixture)
    index = (args["production"] / ".git/index").read_bytes()
    options = git_policy.validate(value, **args)
    assert "core.hooksPath=" + value["hooks"] in options
    assert "credential.helper=" in options
    assert (args["production"] / ".git/index").read_bytes() == index


@pytest.mark.parametrize("key,value", [
    ("merge.unknown.driver", "must-never-run %O %A %B"),
    ("diff.external", "must-never-run"),
    ("filter.unknown.clean", "must-never-run"),
    ("include.path", "/missing-include-must-be-rejected"),
    ("url.https://wrong.invalid/.insteadOf", "https://github.com/"),
])
def test_executable_or_redirecting_config_is_rejected_before_use(merge_fixture, key, value):
    args, frozen = policy(merge_fixture)
    merge_fixture[-1]("config", key, value)
    with pytest.raises(ValueError):
        git_policy.validate(frozen, **args)


def test_benign_config_changes_still_invalidate_the_frozen_identity(merge_fixture):
    args, value = policy(merge_fixture)
    merge_fixture[-1]("config", "user.name", "different actor")
    with pytest.raises(ValueError, match="policy changed"):
        git_policy.validate(value, **args)


def test_new_hook_file_cannot_execute(merge_fixture):
    args, value = policy(merge_fixture)
    (Path(value["hooks"]) / "pre-commit").write_text("must never run", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        git_policy.validate(value, **args)


def test_local_attribute_override_appearance_is_rejected(merge_fixture):
    args, value = policy(merge_fixture)
    (args["production"] / ".git/info/attributes").write_text("* merge=unknown\n", encoding="utf-8")
    with pytest.raises(ValueError, match="attribute override"):
        git_policy.validate(value, **args)


def test_lfs_tool_must_be_an_exact_qualified_native_file(tmp_path):
    root = tmp_path.resolve()
    native = root / "native"
    native.mkdir()
    executable = native / "git-lfs.exe"
    executable.write_bytes(b"opaque reviewed fixture; never launched")
    files = records.publish(root, "native.json", environment.files_manifest(native, [executable.name]))
    profile = records.publish(root, "environment.json", {"native_files": files})
    result = git_policy.native_lfs(Graph(root), profile, {"native": str(native)}, required=True)
    assert result["sha256"] == environment.file_identity(native, executable.name)["sha256"]
    executable.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        git_policy.native_lfs(Graph(root), profile, {"native": str(native)}, required=True)
