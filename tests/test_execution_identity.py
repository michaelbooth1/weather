import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityDriftError,
    ExecutionIdentityError,
    ExecutionIdentityManifest,
    ExclusivePublicationError,
    InvocationSpec,
    PathBinding,
    TreeBinding,
    assert_manifest_digest,
    assert_serialized_completion_matches,
    atomic_write_json_exclusive,
    atomic_write_text_exclusive,
    capture_execution_identity,
    recapture_and_assert_unchanged,
    validate_execution_identity_dict,
)


def _invocation(case: str = "fixture") -> InvocationSpec:
    return InvocationSpec.current(run_parameters={"case": case})


def _spec(tmp_path: Path, *, case: str = "fixture") -> ClosureSpec:
    required = tmp_path / "required.json"
    required.write_text('{"ok": true}\n', encoding="utf-8")
    tree = tmp_path / "tree"
    tree.mkdir(exist_ok=True)
    (tree / "b.txt").write_text("b\n", encoding="utf-8")
    (tree / "a.txt").write_text("a\n", encoding="utf-8")
    return ClosureSpec(
        name="fixture-closure",
        base_root=tmp_path,
        invocation=_invocation(case),
        path_bindings=(
            PathBinding("absent_pointer", tmp_path / "current.json", "absent"),
            PathBinding("required", required),
        ),
        tree_bindings=(TreeBinding("tree", tree),),
        environment=EnvironmentSpec(
            import_names=("json",),
            env_names=("PYTHONPATH", "WEATHER_EXECUTION_IDENTITY_TEST"),
            env_prefixes=("WEATHER_",),
            include_packages=False,
        ),
    )


def test_capture_is_deterministic_serializable_and_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_EXECUTION_IDENTITY_TEST", "secret-value")
    spec = _spec(tmp_path)
    first = capture_execution_identity(spec)
    second = capture_execution_identity(spec)
    assert first.identity_digest == second.identity_digest
    raw = first.to_dict()
    assert json.loads(json.dumps(raw)) == raw
    assert validate_execution_identity_dict(raw) == first
    assert assert_manifest_digest(raw, first.identity_digest) == first

    variables = {row["name"]: row for row in first.identity["environment"]["variables"]}
    assert variables["WEATHER_EXECUTION_IDENTITY_TEST"]["present"] is True
    assert variables["WEATHER_EXECUTION_IDENTITY_TEST"]["value_sha256"]
    assert "secret-value" not in json.dumps(raw)
    assert [row["label"] for row in first.identity["bindings"]] == [
        "absent_pointer",
        "required",
        "tree",
    ]
    tree = first.identity["bindings"][2]
    assert [row["relative_path"] for row in tree["files"]] == ["a.txt", "b.txt"]
    assert first.identity["invocation"] == {
        "argv": list(sys.argv),
        "cwd": Path.cwd().resolve().as_posix(),
        "run_parameters": {"case": "fixture"},
    }
    assert first.identity["environment"]["runtime"]["sys_path"]
    assert [row["raw"] for row in first.identity["environment"]["runtime"]["sys_path"]] == list(sys.path)


def test_file_byte_change_and_environment_change_are_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_EXECUTION_IDENTITY_TEST", "one")
    spec = _spec(tmp_path)
    start = capture_execution_identity(spec)
    (tmp_path / "required.json").write_text('{"ok": false}\n', encoding="utf-8")
    with pytest.raises(ExecutionIdentityDriftError, match="binding:required"):
        recapture_and_assert_unchanged(start, spec, phase="after cache")

    (tmp_path / "required.json").write_text('{"ok": true}\n', encoding="utf-8")
    start = capture_execution_identity(spec)
    monkeypatch.setenv("WEATHER_EXECUTION_IDENTITY_TEST", "two")
    with pytest.raises(ExecutionIdentityDriftError, match="environment:variables"):
        recapture_and_assert_unchanged(start, spec, phase="before publication")


def test_tree_change_and_absent_path_appearance_fail_closed(tmp_path):
    spec = _spec(tmp_path)
    start = capture_execution_identity(spec)
    (tmp_path / "tree" / "c.txt").write_text("c\n", encoding="utf-8")
    with pytest.raises(ExecutionIdentityDriftError, match="binding:tree"):
        recapture_and_assert_unchanged(start, spec, phase="tree mutation")

    (tmp_path / "current.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ExecutionIdentityError, match="required absent"):
        capture_execution_identity(spec)


def test_optional_file_presence_and_absence_are_both_identity(tmp_path):
    anchor = tmp_path / "anchor.json"
    anchor.write_text("{}\n", encoding="utf-8")
    spec = ClosureSpec(
        name="optional",
        base_root=tmp_path,
        invocation=_invocation("optional"),
        path_bindings=(
            PathBinding("anchor", anchor),
            PathBinding("reconstructed", tmp_path / "r.json", "file_or_absent"),
        ),
        environment=EnvironmentSpec(include_packages=False),
    )
    absent = capture_execution_identity(spec)
    (tmp_path / "r.json").write_text("{}\n", encoding="utf-8")
    present = capture_execution_identity(spec)
    assert absent.identity_digest != present.identity_digest
    absent_bindings = {row["label"]: row for row in absent.identity["bindings"]}
    present_bindings = {row["label"]: row for row in present.identity["bindings"]}
    assert absent_bindings["reconstructed"]["state"] == "absent"
    assert present_bindings["reconstructed"]["state"] == "file"


def test_raw_manifest_tampering_and_completion_mismatch_are_rejected(tmp_path):
    spec = _spec(tmp_path)
    start = capture_execution_identity(spec)
    tampered = start.to_dict()
    tampered["identity"]["bindings"][1]["sha256"] = "0" * 64
    with pytest.raises(ExecutionIdentityError, match="does not match"):
        validate_execution_identity_dict(tampered)

    (tmp_path / "tree" / "a.txt").write_text("changed\n", encoding="utf-8")
    completion = capture_execution_identity(spec)
    with pytest.raises(ExecutionIdentityDriftError, match="binding:tree"):
        assert_serialized_completion_matches(start.to_dict(), completion.to_dict())


def test_noncanonical_raw_inventory_is_rejected_even_with_recomputed_digest(tmp_path):
    start = capture_execution_identity(_spec(tmp_path))
    raw = start.to_dict()
    raw["identity"]["bindings"].reverse()
    from weather import execution_identity

    raw["identity_digest"] = execution_identity._payload_digest(raw["identity"])
    with pytest.raises(ExecutionIdentityError, match="not sorted"):
        validate_execution_identity_dict(raw)


def test_atomic_publication_is_exclusive_and_leaves_no_temp(tmp_path):
    output = tmp_path / "out" / "result.json"
    atomic_write_json_exclusive(output, {"status": "COMPLETE"})
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "COMPLETE"}
    with pytest.raises(ExclusivePublicationError, match="overwrite"):
        atomic_write_json_exclusive(output, {"status": "REPLACED"})
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "COMPLETE"}
    assert not list(output.parent.glob(".*.tmp-*"))

    text_output = tmp_path / "out" / "report.md"
    atomic_write_text_exclusive(text_output, "# Complete\n")
    assert text_output.read_text(encoding="utf-8") == "# Complete\n"
    with pytest.raises(ExclusivePublicationError, match="overwrite"):
        atomic_write_text_exclusive(text_output, "replacement\n")


def test_file_or_absent_rejects_directory(tmp_path):
    directory = tmp_path / "value"
    directory.mkdir()
    anchor = tmp_path / "anchor.json"
    anchor.write_text("{}\n", encoding="utf-8")
    spec = ClosureSpec(
        name="bad-optional",
        base_root=tmp_path,
        invocation=_invocation("bad-optional"),
        path_bindings=(
            PathBinding("anchor", anchor),
            PathBinding("value", directory, "file_or_absent"),
        ),
        environment=EnvironmentSpec(include_packages=False),
    )
    with pytest.raises(ExecutionIdentityError, match="required file is a directory"):
        capture_execution_identity(spec)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation is not reliable on Windows CI")
def test_tree_symlink_target_change_changes_identity(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("one\n", encoding="utf-8")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "linked.txt").symlink_to(target)
    spec = ClosureSpec(
        name="symlink-tree",
        base_root=tmp_path,
        invocation=_invocation("symlink-tree"),
        tree_bindings=(TreeBinding("tree", tree),),
        environment=EnvironmentSpec(include_packages=False),
    )
    first = capture_execution_identity(spec)
    target.write_text("two\n", encoding="utf-8")
    second = capture_execution_identity(spec)
    assert first.identity_digest != second.identity_digest


def test_empty_or_absence_only_closure_and_empty_tree_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="at least one binding"):
        ClosureSpec(
            name="empty",
            base_root=tmp_path,
            invocation=_invocation("empty"),
            environment=EnvironmentSpec(include_packages=False),
        )
    with pytest.raises(ValueError, match="required content"):
        ClosureSpec(
            name="absence-only",
            base_root=tmp_path,
            invocation=_invocation("absence-only"),
            path_bindings=(PathBinding("pointer", tmp_path / "pointer", "absent"),),
            environment=EnvironmentSpec(include_packages=False),
        )
    empty_tree = tmp_path / "empty-tree"
    empty_tree.mkdir()
    spec = ClosureSpec(
        name="empty-tree",
        base_root=tmp_path,
        invocation=_invocation("empty-tree"),
        tree_bindings=(TreeBinding("tree", empty_tree),),
        environment=EnvironmentSpec(include_packages=False),
    )
    with pytest.raises(ExecutionIdentityError, match="matched no files"):
        capture_execution_identity(spec)


def test_invocation_mismatch_and_effective_parameters_are_bound(tmp_path, monkeypatch):
    first = capture_execution_identity(_spec(tmp_path, case="one"))
    second = capture_execution_identity(_spec(tmp_path, case="two"))
    assert first.identity_digest != second.identity_digest

    spec = _spec(tmp_path, case="one")
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--unexpected"])
    with pytest.raises(ExecutionIdentityError, match="argv differs"):
        capture_execution_identity(spec)


def test_invocation_cwd_mismatch_is_rejected(tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    other = tmp_path / "other-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    with pytest.raises(ExecutionIdentityError, match="cwd differs"):
        capture_execution_identity(spec)


def test_invocation_rejects_empty_and_nonfinite_run_contracts():
    with pytest.raises(ValueError, match="nonempty mapping"):
        InvocationSpec.current(run_parameters={})
    with pytest.raises(ValueError, match="finite JSON"):
        InvocationSpec.current(run_parameters={"sigma": math.nan})


def test_serialized_manifest_missing_invocation_fails_even_with_new_digest(tmp_path):
    raw = capture_execution_identity(_spec(tmp_path)).to_dict()
    del raw["identity"]["invocation"]
    from weather import execution_identity

    raw["identity_digest"] = execution_identity._payload_digest(raw["identity"])
    with pytest.raises(ExecutionIdentityError, match="identity fields"):
        validate_execution_identity_dict(raw)


def test_hardlink_topology_change_is_identity_drift(tmp_path):
    spec = _spec(tmp_path)
    required = tmp_path / "required.json"
    alias = tmp_path / "required-alias.json"
    try:
        os.link(required, alias)
    except OSError as exc:
        pytest.skip(f"hard links unsupported: {exc}")
    start = capture_execution_identity(spec)
    alias.unlink()
    with pytest.raises(ExecutionIdentityDriftError, match="binding:required"):
        recapture_and_assert_unchanged(start, spec, phase="hardlink alias removal")


def test_single_leaf_publication_race_has_exactly_one_winner(tmp_path):
    output = tmp_path / "race" / "result.json"

    def publish(value: int) -> str:
        try:
            atomic_write_json_exclusive(output, {"winner": value})
        except ExclusivePublicationError:
            return "rejected"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, (1, 2)))
    assert sorted(outcomes) == ["published", "rejected"]
    assert json.loads(output.read_text(encoding="utf-8"))["winner"] in {1, 2}
    # A loser that reached CREATE_NEW retains its private temporary instead
    # of risking pathname cleanup of a replacement.
    assert len(list(output.parent.glob(".*.tmp-*"))) <= 1


def test_single_leaf_publication_failure_retains_owned_temp(tmp_path, monkeypatch):
    from weather import execution_identity

    output = tmp_path / "failed" / "result.json"

    def fail_publish(*args, **kwargs):
        del args, kwargs
        raise OSError("simulated final publication failure")

    helper = (
        "_windows_rename_open_file_exclusive"
        if os.name == "nt"
        else "_posix_rename_open_file_exclusive"
    )
    monkeypatch.setattr(execution_identity, helper, fail_publish)
    with pytest.raises(ExclusivePublicationError, match="single-leaf"):
        atomic_write_json_exclusive(output, {"status": "COMPLETE"})
    assert not os.path.lexists(output)
    retained = list(output.parent.glob(".*.tmp-*"))
    assert len(retained) == 1
    assert json.loads(retained[0].read_text(encoding="utf-8")) == {
        "status": "COMPLETE"
    }


def test_single_leaf_expected_parent_must_preexist_and_match(tmp_path):
    missing_output = tmp_path / "missing-parent" / "result.json"
    with pytest.raises(ExclusivePublicationError, match="parent is absent"):
        atomic_write_json_exclusive(
            missing_output,
            {"status": "COMPLETE"},
            expected_parent_identity=(0, 0),
        )
    assert not missing_output.parent.exists()

    parent = tmp_path / "existing-parent"
    parent.mkdir()
    observed = parent.stat()
    wrong_identity = (int(observed.st_dev), int(observed.st_ino) + 1)
    output = parent / "result.json"
    with pytest.raises(ExclusivePublicationError, match="parent identity changed"):
        atomic_write_json_exclusive(
            output,
            {"status": "COMPLETE"},
            expected_parent_identity=wrong_identity,
        )
    assert not os.path.lexists(output)
    assert not list(parent.glob(".*.tmp-*"))


def test_single_leaf_preexisting_temp_sentinel_is_never_cleaned_by_path(
    tmp_path, monkeypatch
):
    from weather import execution_identity

    output = tmp_path / "substitution" / "result.json"
    output.parent.mkdir()
    token = "fixed-collision-token"
    temporary = output.with_name(
        f".{output.name}.tmp-{os.getpid()}-{token}"
    )
    sentinel = b"competitor-owned-sentinel\n"
    temporary.write_bytes(sentinel)
    monkeypatch.setattr(execution_identity.secrets, "token_hex", lambda size: token)

    with pytest.raises(ExclusivePublicationError, match="overwrite"):
        atomic_write_json_exclusive(output, {"status": "COMPLETE"})
    assert not output.exists()
    assert temporary.read_bytes() == sentinel


@pytest.mark.skipif(os.name != "nt", reason="Windows file-share semantics")
def test_windows_held_temp_blocks_substitution_until_final_rename(
    tmp_path, monkeypatch
):
    from weather import execution_identity

    output = tmp_path / "held-temp" / "result.json"
    real_rename = execution_identity._windows_rename_open_file_exclusive
    blocked: list[str] = []

    def attack_then_rename(descriptor, destination):
        [temporary] = list(destination.parent.glob(".*.tmp-*"))
        for name, operation in {
            "write": lambda: temporary.write_bytes(b'{"status":"COMPLETE"}\n'),
            "delete": temporary.unlink,
            "rename": lambda: temporary.rename(temporary.with_suffix(".swapped")),
        }.items():
            try:
                operation()
            except OSError:
                blocked.append(name)
            else:
                raise AssertionError(f"held temporary allowed {name}")
        return real_rename(descriptor, destination)

    monkeypatch.setattr(
        execution_identity,
        "_windows_rename_open_file_exclusive",
        attack_then_rename,
    )
    atomic_write_json_exclusive(output, {"status": "SEALED"})
    assert blocked == ["write", "delete", "rename"]
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "SEALED"}


@pytest.mark.skipif(os.name != "nt", reason="Windows extended path semantics")
def test_windows_exclusive_publication_supports_path_over_max_path(tmp_path):
    parent = tmp_path
    component = "segmentxxx"
    while len(str(parent / component / "result.json")) <= 245:
        parent = parent / component
    parent.mkdir(parents=True)
    output = parent / "result.json"
    assert len(str(output)) < 260
    assert len(
        str(
            output.with_name(
                f".{output.name}.tmp-{os.getpid()}-{'0' * 32}"
            )
        )
    ) > 260
    atomic_write_json_exclusive(output, {"status": "COMPLETE"})
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "status": "COMPLETE"
    }


def test_single_leaf_preexisting_hardlink_is_never_replaced(tmp_path):
    parent = tmp_path / "hardlink"
    parent.mkdir()
    protected = parent / "protected.json"
    protected.write_text('{"protected":true}\n', encoding="utf-8")
    output = parent / "result.json"
    try:
        os.link(protected, output)
    except OSError as exc:
        pytest.skip(f"hard links unsupported: {exc}")

    with pytest.raises(ExclusivePublicationError, match="overwrite"):
        atomic_write_json_exclusive(output, {"status": "COMPLETE"})
    assert protected.read_text(encoding="utf-8") == '{"protected":true}\n'
    assert output.samefile(protected)


def test_open_handle_fstat_drift_blocks_file_hash(tmp_path, monkeypatch):
    from weather import execution_identity

    path = tmp_path / "bound.txt"
    path.write_text("bound\n", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("a different file\n", encoding="utf-8")
    real_fstat = os.fstat
    calls = 0

    def drifting_fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            return other.stat()
        return real_fstat(descriptor)

    monkeypatch.setattr(os, "fstat", drifting_fstat)
    with pytest.raises(ExecutionIdentityError, match="changed while hashing"):
        execution_identity._stable_file_record(path)


def test_tree_candidate_inventory_is_enumerated_before_and_after_hashing(
    tmp_path, monkeypatch
):
    from weather import execution_identity

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "first.txt").write_text("first\n", encoding="utf-8")
    binding = TreeBinding("tree", tree)
    real_enumerate = execution_identity._enumerate_tree_candidates
    calls = 0

    def changing_inventory(bound, root):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tree / "late.txt").write_text("late\n", encoding="utf-8")
        return real_enumerate(bound, root)

    monkeypatch.setattr(
        execution_identity, "_enumerate_tree_candidates", changing_inventory
    )
    with pytest.raises(ExecutionIdentityError, match="inventory changed"):
        execution_identity._capture_tree(binding, tmp_path)


def test_manifest_instances_are_revalidated_before_assertion_or_recapture(tmp_path):
    forged = ExecutionIdentityManifest(
        identity={"closure_name": "forged"}, identity_digest="0" * 64
    )
    with pytest.raises(ExecutionIdentityError, match="identity fields"):
        assert_manifest_digest(forged, "0" * 64)
    with pytest.raises(ExecutionIdentityError, match="identity fields"):
        recapture_and_assert_unchanged(forged, _spec(tmp_path), phase="forged")


def test_json_publication_rejects_nan_and_leaves_no_leaf_or_temp(tmp_path):
    output = tmp_path / "nan" / "result.json"
    with pytest.raises(ExclusivePublicationError, match="publication failed"):
        atomic_write_json_exclusive(output, {"value": math.nan})
    assert not os.path.lexists(output)
    assert not list(output.parent.glob(".*.tmp-*"))


def test_absent_path_binds_nearest_existing_parent(tmp_path):
    anchor = tmp_path / "anchor.txt"
    anchor.write_text("anchor\n", encoding="utf-8")
    nested = tmp_path / "missing-parent" / "missing.json"
    spec = ClosureSpec(
        name="absence-parent",
        base_root=tmp_path,
        invocation=_invocation("absence-parent"),
        path_bindings=(
            PathBinding("anchor", anchor),
            PathBinding("nested", nested, "absent"),
        ),
        environment=EnvironmentSpec(include_packages=False),
    )
    start = capture_execution_identity(spec)
    binding = {row["label"]: row for row in start.identity["bindings"]}["nested"]
    assert binding["absence_anchor"]["missing_suffix"] == "missing-parent/missing.json"
    (tmp_path / "missing-parent").mkdir()
    with pytest.raises(ExecutionIdentityDriftError, match="binding:nested"):
        recapture_and_assert_unchanged(start, spec, phase="absent parent appeared")


def test_absent_path_records_directory_alias_or_windows_reparse_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory alias unavailable: {symlink_error}")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"directory alias unavailable: {symlink_error}")
    anchor = tmp_path / "anchor.txt"
    anchor.write_text("anchor\n", encoding="utf-8")
    spec = ClosureSpec(
        name="absence-alias",
        base_root=tmp_path,
        invocation=_invocation("absence-alias"),
        path_bindings=(
            PathBinding("anchor", anchor),
            PathBinding("missing", alias / "missing.json", "absent"),
        ),
        environment=EnvironmentSpec(include_packages=False),
    )
    manifest = capture_execution_identity(spec)
    binding = {row["label"]: row for row in manifest.identity["bindings"]}["missing"]
    absence = binding["absence_anchor"]
    assert absence["existing_parent_resolved_path"] == "target"
    assert absence["existing_parent_symlink"] or absence["existing_parent_reparse_point"]
