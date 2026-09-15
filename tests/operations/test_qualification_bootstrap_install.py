"""First landing consumes external approval, never a candidate certificate."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations.qualification import bootstrap_install, records
from test_qualification_bootstrap import envelope
from test_qualification_evidence import NOW, bundle
from test_qualification_merge_tree import merge_fixture
from test_qualification_merge_session import checked_fixture, prepare

ROOT = Path(__file__).resolve().parents[2]
PS = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.fixture
def installation(envelope, tmp_path):
    probe_root, probe = envelope
    root, adapter, adopted = [tmp_path / name for name in ("install-evidence", "install-adapter", "adopted")]
    for directory in (root, adapter, adopted):
        directory.mkdir()
    placeholder = records.publish(root, "placeholder.json", {"fixture_only": True})
    observations = probe_root / "probe-work/observations"
    observations.mkdir(parents=True)
    (observations / "candidate").mkdir()
    results = {}
    for name in ("isolated_imports", "configuration_overlay", "offline_environment", "duplicate_path", "stdin_eof",
                 "create_once_flush_rename", "captured_streams", "timeout_cleanup", "inherited_handles"):
        prefix = "" if name in {"captured_streams", "timeout_cleanup", "inherited_handles"} else "candidate/"
        results[name] = records.publish(observations, prefix + name + ".json",
            {"schema": "qualification_host_probe_v2", "name": name, "status": "PASS", "detail": {"fixture_only": True}})
    probe_ref = records.publish(probe_root, "envelope.json", probe)
    observation = records.publish(observations, "observation.json", {
        "schema": "qualification_bootstrap_probe_observation_v1", "envelope_sha256": probe_ref["sha256"],
        "started_at": (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"), "completed_at": (NOW + timedelta(seconds=100)).isoformat().replace("+00:00", "Z"),
        "source": probe["source"], "configuration": {"fixture_only": True}, "results": results, "markets": [],
        "native_parent_completion_required": True, "integration_eligible": False, "full_suite_replacement": False})
    observation = {**observation, "path": "probe-work/observations/" + observation["path"]}
    result = records.publish(probe_root, "probe-result.json", {
        "schema": "qualification_bootstrap_probe_result_v1", "status": "PROBES_RECORDED",
        "envelope_sha256": probe_ref["sha256"], "adapter_sha256": "d" * 64,
        "outer_teardown_proved": True, "child_exit_code": 0, "preflight_read_bytes": 1,
        "observation": observation, "native_read_bytes": 1, "scratch_bytes": 1,
        "integration_eligible": False, "full_suite_replacement": False, "review_required": True})
    records.publish(probe_root, "probe-work/invocation.json", {"task_xml": "<fixture-only/>"})
    probe_review = records.publish(root, "probe-review.json", {
        "schema": "qualification_bootstrap_probe_review_v1", "envelope_sha256": probe_ref["sha256"],
        "result_sha256": result["sha256"], "source": probe["source"], "reviewer": "fixture reviewer",
        "reviewed_at": (NOW + timedelta(seconds=490)).isoformat().replace("+00:00", "Z"), "decision": "ACCEPT_FIXED_PROBES_FOR_K"})
    closure = records.publish(root, "closure.json", {"schema": "qualification_runtime_files_v2",
        "files": [{"path": path, "sha256": "d" * 64, "size": 1, "mode": "100644"}
                  for path in sorted(bootstrap_install.REQUIRED_ADAPTER)]})
    reviewed = records.publish(root, "review.json", {"schema": "qualification_bootstrap_install_review_v1",
        "source": probe["source"], "policy_sha256": probe["qualification"]["policy"]["sha256"],
        "adapter_closure_sha256": closure["sha256"], "baseline_closure_sha256": placeholder["sha256"],
        "workflow_revision": "d" * 40,
        "windows": {"status": "PASS", "run_id": "1", "attempt": "1",
                    "coverage": placeholder, "logs": placeholder, "artifacts": placeholder},
        "linux": {"status": "PASS", "run_id": "1", "attempt": "1",
                  "coverage": placeholder, "logs": placeholder, "artifacts": placeholder},
        "diff_review": placeholder, "rollback_review": placeholder})
    value = {"schema": bootstrap_install.SCHEMA, "bootstrap_id": "fixture", "operation": "install_control_plane_K_once",
        "repo_root": probe["repo_root"], "candidate": probe["candidate"], "baseline": probe["baseline"],
        "source": deepcopy(probe["source"]), "branch_ref": "refs/remotes/origin/codex/fixture",
        "qualification": deepcopy(probe["qualification"]), "control": {"root": str(adapter), "closure": closure, "git_policy": placeholder},
        "baseline_control": {"root": str(adopted), "closure": placeholder}, "environment": placeholder,
        "configuration": placeholder, "effective_tree": "e" * 40, "host": deepcopy(probe["host"]),
        "task": {"name": "WeatherQualificationBootstrapInstall_fixture"},
        "not_before": (NOW + timedelta(seconds=600)).isoformat().replace("+00:00", "Z"), "deadline": (NOW + timedelta(seconds=1800)).isoformat().replace("+00:00", "Z"),
        "limits": {"commit_bytes": 512 * 1024**2, "working_set_bytes": 512 * 1024**2, "scratch_bytes": 64 * 1024**2,
                   "read_bytes": 8 * 1024**3, "metadata_seconds": 120, "metadata_read_bytes": 2 * 1024**3, "teardown_seconds": 30},
        "adopted_helpers": deepcopy(probe["adopted_helpers"]), "review_evidence": reviewed,
        "approval": {"owner": "fixture owner", "approved_at": (NOW + timedelta(seconds=500)).isoformat().replace("+00:00", "Z"),
                     "replaces_full_host_suite_for_K_only": True},
        "probe": {"root": str(probe_root), "envelope": probe_ref, "result": result, "review": probe_review,
                  "task_xml_sha256": hashlib.sha256(b"<fixture-only/>").hexdigest()},
        "rollback": {"baseline": probe["baseline"], "generated_configuration": placeholder,
                     "mode": "guarded_abort_restore_and_prove_capture", "after_commit": "preserve_and_reconcile"},
        "evidence_root": str(root)}
    return root, value


def test_explicit_owner_envelope_is_separate_from_both_probe_and_v2_authority(installation):
    root, value = installation
    checked = bootstrap_install.context(value, root, now=NOW + timedelta(seconds=600))
    assert checked["review"]["scope"] == "control_plane"
    assert "certificate" not in checked["manifest"]["qualification"]
    assert checked["envelope"]["approval"]["replaces_full_host_suite_for_K_only"] is True


@pytest.mark.parametrize("fault", [
    "v2", "command", "operation", "source", "baseline", "scope", "branch", "ref-traversal", "task", "id",
    "approval", "string-approval", "owner", "future-approval", "too-early", "expired", "long-window",
    "memory", "working-set", "scratch", "read", "metadata", "boolean-limit",
    "probe-root", "probe-task", "probe-review", "probe-result", "probe-source",
    "adapter-root", "baseline-root", "helper", "rollback", "certificate", "review"])
def test_changed_unapproved_or_overbroad_installations_are_refused(installation, fault):
    root, original = installation
    value, now = deepcopy(original), NOW + timedelta(seconds=600)
    if fault == "v2": value["schema"] = "weather_integration_attempt_manifest_v2"
    elif fault == "command": value["command"] = ["arbitrary.exe"]
    elif fault == "operation": value["operation"] = "merge_reliability_candidate"
    elif fault == "source": value["source"]["commit"] = "f" * 40
    elif fault == "baseline": value["baseline"] = "f" * 40
    elif fault == "scope": value["scope"] = "reliability_current_inputs"
    elif fault == "branch": value["branch_ref"] = "HEAD"
    elif fault == "ref-traversal": value["branch_ref"] = "refs/remotes/origin/codex/a/../b"
    elif fault == "task": value["task"]["name"] += "other"
    elif fault == "id": value["bootstrap_id"] = "../outside"
    elif fault == "approval": value["approval"]["replaces_full_host_suite_for_K_only"] = False
    elif fault == "string-approval": value["approval"]["replaces_full_host_suite_for_K_only"] = "true"
    elif fault == "owner": value["approval"]["owner"] = ""
    elif fault == "future-approval": value["approval"]["approved_at"] = (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    elif fault == "too-early": now -= timedelta(seconds=1)
    elif fault == "expired": now = NOW + timedelta(seconds=1800)
    elif fault == "long-window": value["deadline"] = (now + timedelta(seconds=2701)).isoformat().replace("+00:00", "Z")
    elif fault == "memory": value["limits"]["commit_bytes"] = 2 * 1024**3 + 1
    elif fault == "working-set": value["limits"]["working_set_bytes"] += 1
    elif fault == "scratch": value["limits"]["scratch_bytes"] = 128 * 1024**2 + 1
    elif fault == "read": value["limits"]["read_bytes"] = 64 * 1024**3 + 1
    elif fault == "metadata": value["limits"]["metadata_seconds"] = 121
    elif fault == "boolean-limit": value["limits"]["metadata_seconds"] = True
    elif fault == "probe-root": value["probe"]["root"] = str(root)
    elif fault == "probe-task": value["probe"]["task_xml_sha256"] = "f" * 64
    elif fault == "probe-review": value["probe"]["review"] = value["environment"]
    elif fault == "probe-result": value["probe"]["result"]["sha256"] = "f" * 64
    elif fault == "probe-source": value["probe"]["envelope"]["sha256"] = "f" * 64
    elif fault == "adapter-root": value["control"]["root"] = value["candidate"]
    elif fault == "baseline-root": value["baseline_control"]["root"] = value["repo_root"]
    elif fault == "helper": value["adopted_helpers"]["files"][0]["path"] = "another.ps1"
    elif fault == "rollback": value["rollback"]["after_commit"] = "reset_and_retry"
    elif fault == "certificate": value["qualification"]["certificate"] = value["environment"]
    elif fault == "review": value["review_evidence"] = value["environment"]
    with pytest.raises(ValueError):
        bootstrap_install.context(value, root, now=now)


@pytest.mark.parametrize("fault", ["no-teardown", "string-teardown", "string-exit", "excess-reads", "false-PASS", "wrong-adapter"])
def test_reviewed_probe_parent_must_be_native_complete(installation, fault):
    root, value = installation
    probe_root = Path(value["probe"]["root"])
    result = records.read(probe_root, value["probe"]["result"]).value
    if fault == "no-teardown": result["outer_teardown_proved"] = False
    elif fault == "string-teardown": result["outer_teardown_proved"] = "true"
    elif fault == "string-exit": result["child_exit_code"] = "0"
    elif fault == "excess-reads": result["native_read_bytes"] = 2 * 1024**3 + 1
    elif fault == "false-PASS": result["status"] = "PASS"
    elif fault == "wrong-adapter": result["adapter_sha256"] = "f" * 64
    value["probe"]["result"] = records.publish(probe_root, "changed-result.json", result)
    with pytest.raises(ValueError):
        bootstrap_install.context(value, root, now=NOW + timedelta(seconds=600))


def test_request_pin_and_single_use_boundary_refuse_before_validation(installation, monkeypatch):
    root, value = installation
    work = root / "install-work/merge-work/prepare"
    work.mkdir(parents=True)
    envelope = records.publish(root, "envelope.json", value)
    request = records.publish(work, "request.json", {
        "envelope_path": str(root / envelope["path"]), "envelope_sha256": envelope["sha256"], "phase": "prepare",
        "prepared_baseline": value["baseline"], "deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")})
    called = []
    monkeypatch.setattr(bootstrap_install, "context", lambda *_: called.append(True))
    with pytest.raises(ValueError, match="request changed"):
        bootstrap_install.run_boundary(work / request["path"], "f" * 64)
    assert called == []


@pytest.mark.parametrize("changed", [False, True])
def test_bootstrap_boundary_calls_actual_effective_tree_gate(merge_fixture, monkeypatch, changed):
    fixture = merge_fixture
    git, repo, baseline, candidate, graph, config_ref, effective, _, run = fixture
    checked = checked_fixture(fixture)
    prepared = prepare(fixture, checked)
    run("merge", "--no-commit", "--no-ff", candidate)
    if changed:
        (repo / "module.py").write_bytes(b"unreviewed = True\n")
    root = graph.root
    output = root / "install-work/merge-work/before-commit"
    output.mkdir(parents=True)
    envelope = records.publish(root, "envelope.json", {"fixture_only": True})
    request = records.publish(output, "request.json", {
        "envelope_path": str(root / envelope["path"]), "envelope_sha256": envelope["sha256"],
        "phase": "before-commit", "prepared_baseline": prepared,
        "deadline": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")})
    monkeypatch.setattr(bootstrap_install, "context", lambda *_: checked)
    monkeypatch.setattr(bootstrap_install, "verify_inputs", lambda *_: ({}, git, {"fixture_only": True}))
    checked["manifest"]["control"] = {"git_policy": config_ref}
    monkeypatch.setattr(bootstrap_install.git_policy, "options", lambda *_: ["--no-replace-objects"])
    if changed:
        with pytest.raises(ValueError, match="working source/config"):
            bootstrap_install.run_boundary(output / request["path"], request["sha256"])
        assert not (output / "boundary.json").exists()
    else:
        result = bootstrap_install.run_boundary(output / request["path"], request["sha256"])
        value = records.read(output, result).value
        assert value["schema"] == "qualification_bootstrap_install_boundary_v1"
        assert value["effective_tree"] == effective["tree"]
        assert value["integration_eligible"] is False
        with pytest.raises((ValueError, FileExistsError), match="exists|spent|immutable"):
            bootstrap_install.run_boundary(output / request["path"], request["sha256"])


@pytest.mark.skipif(os.name != "nt", reason="native parser and entrypoint refusals")
def test_native_first_landing_scripts_parse_and_bad_pins_have_no_side_effects(tmp_path):
    names = ("bootstrap_qualification_install.ps1", "qualification_bootstrap_install_contract.ps1",
             "qualification_bootstrap_install_child.ps1", "close_bootstrap_qualification_install.ps1",
             "qualification_process.ps1", "quiet_window_merge.ps1")
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    paths = ",".join(quote(ROOT / "scripts/ops" / name) for name in names)
    script = tmp_path / "parse.ps1"
    script.write_text("$ErrorActionPreference='Stop'\nforeach($path in @(" + paths + ")) {\n"
        "$tokens=$null;$errors=$null\n[void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n}\n", encoding="utf-8")
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(script)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    request = tmp_path / "envelope.json"
    request.write_text('{"schema":"weather_integration_attempt_manifest_v2"}', encoding="utf-8")
    adapter = ROOT / "scripts/ops/bootstrap_qualification_install.ps1"
    for wrong in ("self", "envelope", "v2"):
        adapter_sha = "f" * 64 if wrong == "self" else hashlib.sha256(adapter.read_bytes()).hexdigest()
        request_sha = "f" * 64 if wrong == "envelope" else hashlib.sha256(request.read_bytes()).hexdigest()
        result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(adapter),
            "-EnvelopePath", str(request), "-ExpectedEnvelopeSha256", request_sha,
            "-ExpectedAdapterSha256", adapter_sha], capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
        assert ("pinned bytes differ" if wrong != "v2" else "K-only installation") in result.stdout + result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["envelope.json", "parse.ps1"]


@pytest.mark.skipif(os.name != "nt", reason="actual native guarded entry rejects ordinary v2 arguments")
def test_temporary_guarded_entry_cannot_mix_first_landing_with_v2_or_overrides(tmp_path):
    script = ROOT / "scripts/ops/quiet_window_merge.ps1"
    for extra in (["-QualificationManifestPath", "ordinary.json"], ["-Force"], ["-DryRun"]):
        result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(script),
            "-RepoRoot", str(ROOT), "-Branch", "refs/remotes/origin/codex/fixture",
            "-ExpectedTip", "a" * 40, "-ExpectedBaseline", "b" * 40,
            "-ExpectedSelfSha256", hashlib.sha256(script.read_bytes()).hexdigest(),
            "-BootstrapEnvelopePath", str(tmp_path / "absent.json"), "-BootstrapEnvelopeSha256", "c" * 64,
            "-AttemptReportPath", str(tmp_path / "report.json"), *extra],
            capture_output=True, text=True, timeout=20)
        assert result.returncode != 0
        assert "requires" in (result.stdout + result.stderr).lower() or "forbidden" in (result.stdout + result.stderr).lower()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("fault", ["none", "generated-change", "no-control-change", "dirty-candidate"])
def test_installer_checks_real_reviewed_candidate_before_loading_adapter(merge_fixture, tmp_path, monkeypatch, fault):
    git, repo, baseline, candidate, graph, _, _, _, run = merge_fixture
    monkeypatch.setattr(bootstrap_install.source, "_HOST_GIT_OPTIONS", ())
    isolated = tmp_path / "isolated"
    run("worktree", "add", "--detach", str(isolated), baseline if fault == "no-control-change" else candidate)

    def candidate_git(*args):
        return bootstrap_install.source.git_output(git, isolated, *args).decode().strip()

    if fault == "generated-change":
        (isolated / bootstrap_install.merge_tree.GENERATED[0]).write_bytes(b'{"candidate":"must not own Q"}\n')
        candidate_git("add", ".")
        candidate_git("commit", "-qm", "reviewed fixture config change")
    elif fault == "no-control-change":
        candidate_git("commit", "--allow-empty", "-qm", "reviewed fixture with no control change")
    candidate = candidate_git("rev-parse", "HEAD")
    identity = bootstrap_install.source.identity(git, isolated, source=candidate, baseline=baseline)
    source_ref = records.publish(graph.root, "installation-source.json",
        bootstrap_install.source.inventory(git, isolated, candidate, verify_working=True))
    placeholder = records.publish(graph.root, "installation-placeholder.json", {"files": []})
    authority = tmp_path / "adapter"
    authority.mkdir()
    checked = {"manifest": {"repo_root": str(repo), "worktree_root": str(isolated), "expected_tip": candidate,
                            "control": {"root": str(authority), "closure": placeholder, "git_policy": placeholder}},
        "envelope": {"baseline": baseline, "source": identity, "environment": placeholder},
        "graph": graph, "local": graph, "review": {"source_inventory": source_ref}}
    selected = {"environment": placeholder, "bindings": {}}
    monkeypatch.setattr(bootstrap_install.host_runtime, "profile", lambda *_args, **_kwargs: selected)
    monkeypatch.setattr(bootstrap_install.host_runtime, "verify_environment", lambda *_: None)
    monkeypatch.setattr(bootstrap_install.host_runtime, "tool", lambda *_: git)
    monkeypatch.setattr(bootstrap_install.git_policy, "validate", lambda *_args, **_kwargs: ["--no-replace-objects"])

    def reached_adapter(_root):
        raise RuntimeError("candidate verified before adapter")
    monkeypatch.setattr(bootstrap_install.environment, "enumerate_files", reached_adapter)
    if fault == "dirty-candidate":
        (isolated / "module.py").write_bytes(b"unreviewed = True\n")
    if fault == "none":
        with pytest.raises(RuntimeError, match="candidate verified before adapter"):
            bootstrap_install.verify_inputs(checked)
    else:
        with pytest.raises(ValueError, match="generated configuration|no control-plane change|clean|modified|dirty"):
            bootstrap_install.verify_inputs(checked)


@pytest.mark.skipif(os.name != "nt", reason="actual temporary native primitive refuses general invocation")
@pytest.mark.parametrize("ordinary_v2", [False, True])
def test_frozen_first_landing_copy_rejects_general_invocations_before_dependency_loading(tmp_path, ordinary_v2):
    authority = tmp_path / "authority"
    scripts = authority / "scripts/ops"
    scripts.mkdir(parents=True)
    script = scripts / "quiet_window_merge.ps1"
    script.write_bytes((ROOT / "scripts/ops/quiet_window_merge.ps1").read_bytes())
    (authority / "bootstrap-install-only.json").write_bytes(bootstrap_install.BOOTSTRAP_ONLY_MARKER)
    extra = ["-QualificationManifestPath", str(tmp_path / "ordinary.json"),
             "-QualificationManifestSha256", "d" * 64] if ordinary_v2 else []
    result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-File", str(script),
        "-RepoRoot", str(ROOT), "-Branch", "refs/remotes/origin/codex/fixture", "-ExpectedTip", "a" * 40,
        "-ExpectedBaseline", "b" * 40, "-ExpectedSelfSha256", hashlib.sha256(script.read_bytes()).hexdigest(),
        "-AttemptReportPath", str(tmp_path / "report.json"), *extra],
        capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "bootstrap-only" in result.stdout + result.stderr
    assert not (tmp_path / "report.json").exists()
