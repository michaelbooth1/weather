import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import pytest

from weather.execution_identity import (
    ClosureSpec,
    EnvironmentSpec,
    ExecutionIdentityDriftError,
    ExclusivePublicationError,
    InvocationSpec,
    PathBinding,
    capture_execution_identity,
)
from weather.reporting.research.research_generation import (
    COMPLETE_NAME,
    ResearchGeneration,
    ResearchGenerationError,
)


def _identity(tmp_path: Path):
    anchor = tmp_path / "anchor.txt"
    anchor.write_text("anchor\n", encoding="utf-8")
    spec = ClosureSpec(
        name="generation-fixture",
        base_root=tmp_path,
        invocation=InvocationSpec.current(run_parameters={"case": "generation"}),
        path_bindings=(PathBinding("anchor", anchor),),
        environment=EnvironmentSpec(include_packages=False),
    )
    return capture_execution_identity(spec), spec


def _builder(tmp_path: Path, name: str = "generation") -> ResearchGeneration:
    read_only = tmp_path / "data"
    read_only.mkdir(exist_ok=True)
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    return ResearchGeneration(
        generation_dir=output / name,
        read_only_roots=(read_only,),
        commit_schema_version="fixture_generation_commit_v0.1",
    )


def test_complete_marker_is_last_commit_and_binds_all_fixed_leaves(tmp_path):
    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path)
    with generation as active:
        active.publish_json("cache/arm.json", {"arm": 1}, compact=True)
        active.publish_text("report.md", "# Complete\n")
        completion = capture_execution_identity(spec)
        commit = active.commit(
            start=start,
            expected_completion=completion,
            terminal_recapture=lambda: capture_execution_identity(spec),
            terminal_seals={"design": {"sha256": "a" * 64}},
            extra={"graph": "RESEARCH_UNBOUND"},
        )

    complete_path = generation.generation_dir / COMPLETE_NAME
    assert complete_path.is_file()
    written = json.loads(complete_path.read_text(encoding="utf-8"))
    assert written == commit
    assert written["execution_identity"]["identical_full_manifest"] is True
    assert written["metadata"] == {"graph": "RESEARCH_UNBOUND"}
    assert [row["name"] for row in written["outputs"]] == [
        "cache/arm.json",
        "report.md",
    ]
    for row in written["outputs"]:
        raw = (generation.generation_dir / row["name"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    assert complete_path.stat().st_nlink == 1


def test_uncommitted_generation_is_retained_without_complete_on_error(tmp_path):
    generation = _builder(tmp_path)
    with pytest.raises(RuntimeError, match="stop"):
        with generation as active:
            active.publish_text("partial.txt", "partial\n")
            raise RuntimeError("stop")
    assert generation.generation_dir.is_dir()
    assert (generation.generation_dir / "partial.txt").is_file()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_normal_exit_without_commit_is_retained_without_complete(tmp_path):
    generation = _builder(tmp_path)
    with generation as active:
        active.publish_text("partial.txt", "partial\n")
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_nan_leaf_fails_and_generation_is_retained_without_complete(tmp_path):
    generation = _builder(tmp_path)
    with pytest.raises(ExclusivePublicationError, match="publication failed"):
        with generation as active:
            active.publish_json("bad.json", {"value": math.nan})
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_nonfinite_commit_metadata_fails_before_terminal_recapture(tmp_path):
    start, _ = _identity(tmp_path)
    generation = _builder(tmp_path, "bad-commit-metadata")
    recaptured = False

    def terminal_recapture():
        nonlocal recaptured
        recaptured = True
        return start

    with pytest.raises(ResearchGenerationError, match="finite JSON"):
        with generation as active:
            active.publish_text("result.txt", "result\n")
            active.commit(
                start=start,
                terminal_recapture=terminal_recapture,
                terminal_seals={"design": {"value": math.nan}},
            )
    assert recaptured is False
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_unregistered_leaf_blocks_commit_and_retains_generation(tmp_path):
    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path)
    with pytest.raises(ResearchGenerationError, match="unregistered"):
        with generation as active:
            active.publish_text("registered.txt", "registered\n")
            (generation.generation_dir / "stray.txt").write_text(
                "stray\n", encoding="utf-8"
            )
            active.commit(
                start=start,
                terminal_recapture=lambda: capture_execution_identity(spec),
                terminal_seals={"design": {"sha256": "a" * 64}},
            )
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_generation_rejects_existing_read_only_and_escape_paths(tmp_path):
    read_only = tmp_path / "data"
    read_only.mkdir()
    with pytest.raises(ValueError, match="read-only"):
        ResearchGeneration(
            generation_dir=read_only / "generation",
            read_only_roots=(read_only,),
            commit_schema_version="fixture_v0.1",
        )

    generation = _builder(tmp_path)
    with generation as active:
        with pytest.raises(ResearchGenerationError, match="invalid generation leaf"):
            active.path("../escape.json")
        if os.name == "nt":
            with pytest.raises(
                ResearchGenerationError, match="invalid generation leaf"
            ):
                active.publish_json("COMPLETE.json.", {"status": "forged"})
            assert not (generation.generation_dir / COMPLETE_NAME).exists()
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()

    existing = tmp_path / "output" / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        _builder(tmp_path, "existing")


def test_terminal_recapture_runs_after_final_leaf_hash(tmp_path, monkeypatch):
    from weather.reporting.research import research_generation as module

    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "late-drift")
    original_receipt = module.ResearchGeneration._held_receipt
    anchor = tmp_path / "anchor.txt"
    injected = False

    def hash_then_drift(self, name):
        nonlocal injected
        receipt = original_receipt(self, name)
        if name == "result.txt" and not injected:
            injected = True
            anchor.write_text("changed after output rehash\n", encoding="utf-8")
        return receipt

    with pytest.raises(ExecutionIdentityDriftError, match="binding:anchor"):
        with generation as active:
            active.publish_text("result.txt", "result\n")
            monkeypatch.setattr(
                module.ResearchGeneration, "_held_receipt", hash_then_drift
            )
            active.commit(
                start=start,
                expected_completion=start,
                terminal_recapture=lambda: capture_execution_identity(spec),
                terminal_seals={"design": {"sha256": "a" * 64}},
            )

    assert injected is True
    assert generation.generation_dir.is_dir()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_unregistered_directory_blocks_commit_and_is_never_recursively_deleted(
    tmp_path,
):
    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "directory-race")
    with pytest.raises(ResearchGenerationError, match="topology"):
        with generation as active:
            active.publish_text("registered.txt", "registered\n")
            replacement = generation.generation_dir / "replacement"
            replacement.mkdir()
            (replacement / "sentinel.txt").write_text("preserve\n", encoding="utf-8")
            active.commit(
                start=start,
                terminal_recapture=lambda: capture_execution_identity(spec),
                terminal_seals={"design": {"sha256": "a" * 64}},
            )

    assert (generation.generation_dir / "replacement" / "sentinel.txt").read_text(
        encoding="utf-8"
    ) == "preserve\n"
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_reparse_leaf_parent_is_rejected_without_touching_target(tmp_path):
    generation = _builder(tmp_path, "reparse")
    target = tmp_path / "protected-target"
    target.mkdir()
    alias = generation.generation_dir / "cache"

    with generation as active:
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
                pytest.skip(f"directory junction unavailable: {result.stderr}")
        with pytest.raises(ResearchGenerationError, match="unregistered"):
            active.publish_json("cache/arm.json", {"arm": 1})

    assert not (target / "arm.json").exists()
    assert not (generation.generation_dir / COMPLETE_NAME).exists()


def test_reparse_generation_parent_is_rejected_without_touching_target(tmp_path):
    read_only = tmp_path / "data"
    read_only.mkdir()
    target = tmp_path / "protected-output"
    target.mkdir()
    alias = tmp_path / "output-alias"
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
            pytest.skip(f"directory junction unavailable: {result.stderr}")

    with pytest.raises(ValueError, match="alias"):
        ResearchGeneration(
            generation_dir=alias / "generation",
            read_only_roots=(read_only,),
            commit_schema_version="fixture_generation_commit_v0.1",
        )
    assert not (target / "generation").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-share semantics")
def test_windows_directory_guards_allow_child_atomic_rename(
    tmp_path, monkeypatch
):
    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "windows-guard")

    def hardlink_must_not_be_used(*args, **kwargs):
        del args, kwargs
        raise AssertionError("Windows publication must use exclusive rename")

    monkeypatch.setattr(os, "link", hardlink_must_not_be_used)
    with generation as active:
        active.publish_json("cache/result.json", {"result": "sealed"})
        active.commit(
            start=start,
            expected_completion=start,
            terminal_recapture=lambda: capture_execution_identity(spec),
            terminal_seals={"design": {"sha256": "a" * 64}},
        )

    assert (generation.generation_dir / COMPLETE_NAME).is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows file-share semantics")
def test_windows_terminal_recapture_runs_while_registered_leaf_is_pinned(
    tmp_path,
):
    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "windows-leaf-guard")
    blocked: list[str] = []

    with generation as active:
        active.publish_text("result.txt", "sealed\n")
        leaf = generation.generation_dir / "result.txt"

        def recapture_while_attacking():
            operations = {
                "write": lambda: leaf.write_text("attacker\n", encoding="utf-8"),
                "delete": leaf.unlink,
                "rename": lambda: leaf.rename(leaf.with_name("renamed.txt")),
            }
            for name, operation in operations.items():
                try:
                    operation()
                except OSError:
                    blocked.append(name)
                else:
                    raise AssertionError(
                        f"registered leaf was not pinned against {name}"
                    )
            return capture_execution_identity(spec)

        active.commit(
            start=start,
            expected_completion=start,
            terminal_recapture=recapture_while_attacking,
            terminal_seals={"design": {"sha256": "a" * 64}},
        )

    assert blocked == ["write", "delete", "rename"]
    assert (generation.generation_dir / "result.txt").read_text(
        encoding="utf-8"
    ) == "sealed\n"
    assert (generation.generation_dir / COMPLETE_NAME).is_file()


def test_complete_marker_uses_carried_prepublication_evidence(
    tmp_path, monkeypatch
):
    from weather.reporting.research import research_generation as module

    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "carried-marker-evidence")
    original_receipt = module._stable_receipt
    original_topology = module._plain_file_topology

    def reject_postpublication_receipt(path, *, relative_to):
        if Path(path).name == COMPLETE_NAME:
            raise AssertionError(
                "COMPLETE receipt must be carried across its publication point"
            )
        return original_receipt(path, relative_to=relative_to)

    def reject_postpublication_topology(path):
        if Path(path).name == COMPLETE_NAME:
            raise AssertionError(
                "COMPLETE topology must be carried across its publication point"
            )
        return original_topology(path)

    monkeypatch.setattr(module, "_stable_receipt", reject_postpublication_receipt)
    monkeypatch.setattr(module, "_plain_file_topology", reject_postpublication_topology)
    with generation as active:
        active.publish_text("result.txt", "sealed\n")
        active.commit(
            start=start,
            expected_completion=start,
            terminal_recapture=lambda: capture_execution_identity(spec),
            terminal_seals={"design": {"sha256": "a" * 64}},
        )

    assert (generation.generation_dir / COMPLETE_NAME).is_file()


def test_post_commit_directory_guard_close_error_is_not_publication_failure(
    tmp_path, monkeypatch
):
    from weather.reporting.research import research_generation as module

    start, spec = _identity(tmp_path)
    generation = _builder(tmp_path, "post-commit-close")
    original_close = module._DirectoryGuard.close

    def close_then_report_error(self):
        original_close(self)
        raise OSError("injected close failure after publication")

    monkeypatch.setattr(module._DirectoryGuard, "close", close_then_report_error)
    with generation as active:
        active.publish_text("result.txt", "sealed\n")
        commit = active.commit(
            start=start,
            expected_completion=start,
            terminal_recapture=lambda: capture_execution_identity(spec),
            terminal_seals={"design": {"sha256": "a" * 64}},
        )

    assert commit["status"] == "COMPLETE"
    assert (generation.generation_dir / COMPLETE_NAME).is_file()
