"""Actual configuration preparation and adopted literal controller selection."""

import hashlib
from pathlib import Path

import pytest

from test_qualification_merge_tree import merge_fixture
from weather.operations.qualification import merge_tree, planning, records
from weather.operations.qualification.contracts import Graph


ROOT = Path(__file__).resolve().parents[2]


def test_actual_planner_seals_complete_q_without_changing_git(merge_fixture):
    git, repo, baseline, commit, *_, run = merge_fixture
    output = repo.parent / "planning"
    output.mkdir()
    before = (repo / ".git/index").read_bytes()
    head = run("rev-parse", "HEAD")
    result = planning.configuration(git, repo, repo, baseline=baseline, commit=commit, output=output,
        maximum={"read_bytes": 1024**2, "staged_bytes": 1024**2, "files": 100, "seconds": 60})
    graph = Graph(output)
    assert result["integration_eligible"] is False
    assert result["validation"]["current_pointer_present"] is False
    q = merge_tree.configuration(graph.get(result["configuration"]))
    assert [row["path"] for row in q["generated"]] == list(merge_tree.GENERATED)
    assert graph.get(q["dependencies"])["file_count"] == 3
    assert run("rev-parse", "HEAD") == head and (repo / ".git/index").read_bytes() == before
    with pytest.raises((records.QualificationError, FileExistsError)):
        planning.configuration(git, repo, repo, baseline=baseline, commit=commit, output=output,
            maximum={"read_bytes": 1024**2, "staged_bytes": 1024**2, "files": 100, "seconds": 60})


def test_actual_adopted_orchestration_map_has_no_second_generated_inventory():
    files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in (ROOT / "scripts/ops").glob("*.ps1")]
    mapped = planning.orchestration(ROOT, {"files": files})
    assert {"attempt_host", "attempt_merge", "attempt_planner", "attempt_reconciler", "qualification_creation"} <= set(mapped)
    assert all(Path(row["path"]).parent == ROOT / "scripts/ops" for row in mapped.values())
    assert mapped["contract"]["sha256"] == hashlib.sha256((ROOT / "scripts/ops/integration_attempt_contract.ps1").read_bytes()).hexdigest()


def test_planner_refuses_executable_expression_in_controller_map(tmp_path):
    path = tmp_path / "scripts/ops/qualification_attempt_contract.ps1"
    path.parent.mkdir(parents=True)
    path.write_text("function Get-WeatherQualificationOrchestrationNames { return [ordered]@{ contract = $(Get-Command git) } }", encoding="utf-8")
    with pytest.raises(records.QualificationError, match="expression"):
        planning.orchestration(tmp_path, {"files": []})


def test_configuration_planning_rejects_evidence_inside_production(merge_fixture):
    git, repo, baseline, commit, *_ = merge_fixture
    output = repo / "unapproved-output"
    output.mkdir()
    with pytest.raises(records.QualificationError, match="outside both"):
        planning.configuration(git, repo, repo, baseline=baseline, commit=commit, output=output,
            maximum={"read_bytes": 1024**2, "staged_bytes": 1024**2, "files": 100, "seconds": 60})
