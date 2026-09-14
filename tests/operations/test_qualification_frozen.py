"""Actual Git B copies survive S while substitutions and omitted imports fail."""

from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from weather.operations.qualification import frozen, source
from weather.operations.qualification.contracts import Graph


@pytest.fixture
def closure(tmp_path):
    repository, evidence, destination = (tmp_path.resolve() / name for name in ("repository", "evidence", "trusted"))
    repository.mkdir()
    evidence.mkdir()
    git = Path(shutil.which("git")).resolve()

    def command(*args):
        result = subprocess.run(source.git_argv(git, repository, *args), env=source.git_environment(),
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    command("init")
    command("config", "user.name", "Qualification fixture")
    command("config", "user.email", "fixture@example.invalid")
    for path, raw in {"src/weather/policy.py": b"AUTHORITY = 'B'\n",
                      "scripts/ops/merge.ps1": b"# adopted fixed entry\n",
                      "scripts/ops/deferred.py": b"# deferred import\n",
                      "config/policy.json": b'{}\n', "tests/test_not_control.py": b"# not executable authority\n",
                      "data/not_selected.json": b'{}\n', "docs/example.md": b"fixture\n"}.items():
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    command("add", "--", "src", "scripts", "config", "tests", "data", "docs")
    command("commit", "-m", "B fixture")
    baseline = command("rev-parse", "HEAD")
    ref = frozen.freeze(git, repository, baseline, destination=destination, evidence_root=evidence)
    return git, repository, baseline, destination, evidence, ref, command


def test_frozen_B_survives_mutable_working_tree_and_new_source_commit(closure):
    git, repository, baseline, destination, evidence, ref, command = closure
    (repository / "src/weather/policy.py").write_text("AUTHORITY = 'S'\n")
    command("add", "--", "src/weather/policy.py")
    command("commit", "-m", "S fixture")
    value = Graph(evidence).get(ref)
    frozen.validate(git, repository, baseline, destination=destination, value=value)
    assert (destination / "src/weather/policy.py").read_text() == "AUTHORITY = 'B'\n"
    assert [item["path"] for item in value["files"]] == ["config/policy.json", "scripts/ops/deferred.py", "scripts/ops/merge.ps1", "src/weather/policy.py"]
    with pytest.raises(ValueError, match="spent"):
        frozen.freeze(git, repository, baseline, destination=destination, evidence_root=evidence)


@pytest.mark.parametrize("mutation", ["omitted", "extra_bytecode", "rewritten", "resigned_sha256", "wrong_baseline"])
def test_deferred_closure_cannot_be_replaced_or_shrunk(closure, mutation):
    git, repository, baseline, destination, evidence, ref, command = closure
    value = deepcopy(Graph(evidence).get(ref))
    target = destination / "src/weather/policy.py"
    if mutation == "omitted":
        value["files"].pop()
    elif mutation == "extra_bytecode":
        (destination / "injected.pyc").write_bytes(b"stale code")
    elif mutation in {"rewritten", "resigned_sha256"}:
        target.chmod(0o600)
        raw = b"AUTHORITY = 'X'\n"
        target.write_bytes(raw)
        if mutation == "resigned_sha256":
            value["files"][-1]["sha256"] = hashlib.sha256(raw).hexdigest()
    else:
        value["baseline"] = "a" * 40
    with pytest.raises(ValueError):
        frozen.validate(git, repository, baseline, destination=destination, value=value)
