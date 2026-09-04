import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "ops" / "invoke_workstation_codex_mission.ps1"
POWERSHELL = Path(os.environ["WINDIR"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CSC = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
CANONICAL_ORIGIN = "https://github.com/michaelbooth1/weather.git"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_for(path: Path, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {path}")


def _is_running(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    return result.returncode == 0 and f'"{pid}"' in result.stdout


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


@pytest.fixture(scope="session")
def fake_codex_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("fake-codex")
    source = root / "fake_codex.cs"
    binary = root / "codex.exe"
    source.write_text(
        r'''
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

public static class FakeCodex {
    private static void WriteLastMessage(string[] args) {
        for (int index = 0; index + 1 < args.Length; index++) {
            if (args[index] == "--output-last-message") {
                File.WriteAllText(args[index + 1], "synthetic codex completed\n");
                return;
            }
        }
    }

    public static int Main(string[] args) {
        string mode = Environment.GetEnvironmentVariable("FAKE_CODEX_MODE") ?? "exit0";
        if (mode == "exit17") return 17;
        if (mode == "capture_lfs_env") {
            string value = Environment.GetEnvironmentVariable("GIT_LFS_SKIP_SMUDGE");
            File.WriteAllText(
                Environment.GetEnvironmentVariable("FAKE_ENV_CAPTURE_PATH"),
                value ?? "<unset>"
            );
            WriteLastMessage(args);
            return 0;
        }
        if (mode == "identity_drift") {
            File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "identity-drift.txt"), "drift\n");
            WriteLastMessage(args);
            return 0;
        }
        if (mode == "sleep" || mode == "sleep_descendant") {
            if (mode == "sleep_descendant") {
                ProcessStartInfo info = new ProcessStartInfo();
                info.FileName = Environment.ExpandEnvironmentVariables(@"%WINDIR%\System32\PING.EXE");
                info.Arguments = "-n 60 127.0.0.1";
                info.UseShellExecute = true;
                info.WindowStyle = ProcessWindowStyle.Hidden;
                Process child = Process.Start(info);
                File.WriteAllText(Environment.GetEnvironmentVariable("FAKE_DESCENDANT_PID_PATH"), child.Id.ToString());
            }
            Thread.Sleep(30000);
            return 0;
        }
        if (mode == "handback") {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = Environment.ExpandEnvironmentVariables(@"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe");
            info.Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"" +
                Environment.GetEnvironmentVariable("FAKE_HANDBACK_HELPER") + "\"";
            info.WorkingDirectory = Environment.CurrentDirectory;
            info.UseShellExecute = false;
            Process helper = Process.Start(info);
            helper.WaitForExit();
            if (helper.ExitCode != 0) return helper.ExitCode;
            WriteLastMessage(args);
            return 0;
        }
        WriteLastMessage(args);
        return 0;
    }
}
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [str(CSC), "/nologo", "/target:exe", f"/out:{binary}", str(source)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    return binary


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if cwd is not None:
        command.extend(["-C", str(cwd)])
    command.extend(args)
    return subprocess.run(command, text=True, capture_output=True, timeout=30, check=check)


def _make_repo(path: Path) -> dict[str, str]:
    path.mkdir()
    _git("init", "-q", str(path))
    _git("config", "user.name", "Synthetic Runner Test", cwd=path)
    _git("config", "user.email", "runner@example.invalid", cwd=path)
    _git("remote", "add", "origin", CANONICAL_ORIGIN, cwd=path)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git("add", "--", "base.txt", cwd=path)
    _git("commit", "-q", "-m", "synthetic base", cwd=path)
    base = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
    base_tree = _git("rev-parse", "HEAD^{tree}", cwd=path).stdout.strip()
    (path / "source.txt").write_text("source\n", encoding="utf-8")
    _git("add", "--", "source.txt", cwd=path)
    _git("commit", "-q", "-m", "synthetic source", cwd=path)
    source = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
    source_tree = _git("rev-parse", "HEAD^{tree}", cwd=path).stdout.strip()
    return {
        "base": base,
        "base_tree": base_tree,
        "source": source,
        "source_tree": source_tree,
    }


@pytest.fixture
def local_lfs_endpoint():
    state: dict[str, object] = {"requests": [], "oid": "", "payload": b""}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            return

        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            state["requests"].append(("POST", self.path, request))
            response = {
                "transfer": "basic",
                "objects": [
                    {
                        "oid": state["oid"],
                        "size": len(state["payload"]),
                        "actions": {
                            "download": {
                                "href": (
                                    f"http://127.0.0.1:{self.server.server_port}"
                                    f"/objects/{state['oid']}"
                                )
                            }
                        },
                    }
                ],
            }
            self._reply(200, json.dumps(response).encode("utf-8"), "application/json")

        def do_GET(self):
            state["requests"].append(("GET", self.path, None))
            self._reply(200, state["payload"], "application/octet-stream")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/lfs"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _make_lfs_repo(path: Path, endpoint: str, state: dict[str, object]) -> dict[str, str]:
    path.mkdir()
    _git("init", "-q", str(path))
    _git("config", "user.name", "Synthetic Runner Test", cwd=path)
    _git("config", "user.email", "runner@example.invalid", cwd=path)
    _git("remote", "add", "origin", CANONICAL_ORIGIN, cwd=path)
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git("add", "--", "base.txt", cwd=path)
    _git("commit", "-q", "-m", "synthetic base", cwd=path)
    base = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
    base_tree = _git("rev-parse", "HEAD^{tree}", cwd=path).stdout.strip()

    payload = b"local synthetic LFS payload\n"
    oid = hashlib.sha256(payload).hexdigest()
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{oid}\n"
        f"size {len(payload)}\n"
    ).encode("ascii")
    state["oid"] = oid
    state["payload"] = payload
    (path / ".gitattributes").write_text(
        "*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8"
    )
    (path / "payload.bin").write_bytes(pointer)
    _git("add", "--", ".gitattributes", "payload.bin", cwd=path)
    _git("commit", "-q", "-m", "synthetic LFS pointer", cwd=path)
    source = _git("rev-parse", "HEAD", cwd=path).stdout.strip()
    source_tree = _git("rev-parse", "HEAD^{tree}", cwd=path).stdout.strip()
    _git("config", "lfs.url", endpoint, cwd=path)
    return {
        "base": base,
        "base_tree": base_tree,
        "source": source,
        "source_tree": source_tree,
        "pointer": pointer,
        "payload": payload,
    }


@pytest.fixture
def attempt_fixture(tmp_path: Path, fake_codex_binary: Path):
    repo = tmp_path / "repo"
    identities = _make_repo(repo)
    mission = tmp_path / "mission.md"
    mission.write_text("sealed synthetic mission\n", encoding="utf-8")
    run_parent = tmp_path / "evidence"
    run_parent.mkdir()
    branch = f"codex/synthetic-{uuid.uuid4().hex}"
    fixture = {
        **identities,
        "repo": repo,
        "mission": mission,
        "mission_sha": _sha(mission),
        "attempt_root": run_parent / "attempt-1",
        "controller": tmp_path / "controller",
        "result_worktree": tmp_path / "result",
        "result_ref": f"refs/heads/{branch}",
        "result_branch": branch,
        "report": "docs/roadmap/synthetic-report.md",
        "receipt": "docs/roadmap/synthetic-handback.json",
        "bundle": run_parent / "final.bundle",
        "codex": tmp_path / "codex.exe",
        "helper": tmp_path / "handback.ps1",
    }
    shutil.copy2(fake_codex_binary, fixture["codex"])
    yield fixture
    for key in ("attempt_root", "controller", "result_worktree"):
        path = fixture[key]
        if Path(path).exists():
            status = _git("status", "--porcelain=v1", cwd=Path(path), check=False)
            if status.returncode == 0 and status.stdout:
                continue


def _deadline(seconds: float = 15.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _run_command(fixture, *, deadline_seconds: float = 15.0, heartbeat: int = 1) -> list[str]:
    return [
        str(POWERSHELL),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-Mode",
        "Run",
        "-MissionId",
        "synthetic-mission",
        "-MissionPath",
        str(fixture["mission"]),
        "-ExpectedMissionSha256",
        fixture["mission_sha"],
        "-AttemptRoot",
        str(fixture["attempt_root"]),
        "-Attempt",
        "1",
        "-RepositoryRoot",
        str(fixture["repo"]),
        "-ControllerWorktree",
        str(fixture["controller"]),
        "-ExpectedSourceTip",
        fixture["source"],
        "-ExpectedSourceTree",
        fixture["source_tree"],
        "-ExpectedSourceParent",
        fixture["base"],
        "-ExpectedBaseTip",
        fixture["base"],
        "-ResultRef",
        fixture["result_ref"],
        "-ResultWorktree",
        str(fixture["result_worktree"]),
        "-RequiredReportPath",
        fixture["report"],
        "-RequiredReceiptPath",
        fixture["receipt"],
        "-BundlePath",
        str(fixture["bundle"]),
        "-CodexPath",
        str(fixture["codex"]),
        "-ExpectedCodexSha256",
        _sha(fixture["codex"]),
        "-DeadlineUtc",
        _deadline(deadline_seconds),
        "-HeartbeatSeconds",
        str(heartbeat),
        "-Prompt",
        "synthetic runner test only",
    ]


def _run(fixture, mode: str, *, deadline_seconds: float = 15.0, timeout: float = 30.0, extra_env=None):
    env = os.environ.copy()
    env["FAKE_CODEX_MODE"] = mode
    env.update(extra_env or {})
    return subprocess.run(
        _run_command(fixture, deadline_seconds=deadline_seconds),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _start(fixture, mode: str, *, deadline_seconds: float = 20.0, extra_env=None):
    env = os.environ.copy()
    env["FAKE_CODEX_MODE"] = mode
    env.update(extra_env or {})
    return subprocess.Popen(
        _run_command(fixture, deadline_seconds=deadline_seconds),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _terminal(fixture) -> dict:
    return json.loads((fixture["attempt_root"] / "terminal-receipt.json").read_text(encoding="utf-8"))


def _status_command(fixture, claim_sha: str, stale_after: int = 30) -> list[str]:
    return [
        str(POWERSHELL),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RUNNER),
        "-Mode",
        "Status",
        "-MissionId",
        "synthetic-mission",
        "-AttemptRoot",
        str(fixture["attempt_root"]),
        "-Attempt",
        "1",
        "-ExpectedClaimSha256",
        claim_sha,
        "-StaleAfterSeconds",
        str(stale_after),
    ]


def _write_handback_helper(fixture) -> None:
    values = {
        "repo": str(fixture["repo"]),
        "result": str(fixture["result_worktree"]),
        "branch": fixture["result_branch"],
        "source": fixture["source"],
        "source_tree": fixture["source_tree"],
        "base": fixture["base"],
        "base_tree": fixture["base_tree"],
        "result_ref": fixture["result_ref"],
        "report": fixture["report"],
        "receipt": fixture["receipt"],
        "bundle": str(fixture["bundle"]),
        "mission_sha": fixture["mission_sha"],
    }
    encoded = json.dumps(values, separators=(",", ":"))
    fixture["helper"].write_text(
        f"$v = '{encoded}' | ConvertFrom-Json\n"
        "$utf8=[Text.UTF8Encoding]::new($false)\n"
        "git -C $v.repo worktree add -b $v.branch $v.result $v.source\n"
        "if($LASTEXITCODE -ne 0){exit 61}\n"
        "[IO.File]::WriteAllText((Join-Path $v.result 'implementation.txt'),'implemented`n',$utf8)\n"
        "git -C $v.result add -- implementation.txt\n"
        "git -C $v.result commit -q -m 'synthetic implementation'\n"
        "if($LASTEXITCODE -ne 0){exit 62}\n"
        "$implementationTip=(git -C $v.result rev-parse HEAD).Trim()\n"
        "$implementationTree=(git -C $v.result rev-parse 'HEAD^{tree}').Trim()\n"
        "$reportFull=Join-Path $v.result ($v.report -replace '/','\\')\n"
        "$receiptFull=Join-Path $v.result ($v.receipt -replace '/','\\')\n"
        "[void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($reportFull)) -Force)\n"
        "[IO.File]::WriteAllText($reportFull,'# Synthetic validated handback`n',$utf8)\n"
        "$payload=[ordered]@{\n"
        " schema_version='workstation_unattended_mission_handback_v0.1'; mission_id='synthetic-mission'; mission_sha256=$v.mission_sha;\n"
        " source_tip=$v.source; source_tree=$v.source_tree; base_tip=$v.base; base_tree=$v.base_tree; result_ref=$v.result_ref;\n"
        " implementation_tip=$implementationTip; implementation_tree=$implementationTree; report_path=$v.report; receipt_path=$v.receipt; bundle_path=$v.bundle;\n"
        " changed_paths=@('docs/roadmap/synthetic-handback.json','docs/roadmap/synthetic-report.md','implementation.txt');\n"
        " tests=@([ordered]@{name='synthetic';status='PASS'}); script_sha256=[ordered]@{};\n"
        " terminal_state_semantics=[ordered]@{complete='COMPLETE_VALIDATED'}; measured_evidence=[ordered]@{synthetic=$true};\n"
        " remaining_reboot_boundary='No process supervisor survives host power loss.'; prohibited_actions=@('push','merge','scheduler','production');\n"
        " external_binding=[ordered]@{rule='terminal_receipt_binds_final_result_tip_tree_and_bundle_sha256';final_tip=$null;final_tree=$null;bundle_sha256=$null}\n"
        "}\n"
        "[IO.File]::WriteAllText($receiptFull,($payload|ConvertTo-Json -Depth 12)+\"`n\",$utf8)\n"
        "git -C $v.result add -- $v.report $v.receipt\n"
        "git -C $v.result commit -q -m 'synthetic handback'\n"
        "if($LASTEXITCODE -ne 0){exit 63}\n"
        "git -C $v.repo bundle create $v.bundle $v.result_ref\n"
        "if($LASTEXITCODE -ne 0){exit 64}\n"
        "exit 0\n",
        encoding="utf-8",
    )


def test_heartbeat_is_atomic_fresh_and_status_is_read_only(attempt_fixture):
    proc = _start(attempt_fixture, "sleep")
    claim_path = attempt_fixture["attempt_root"] / "claim.json"
    heartbeat_path = attempt_fixture["attempt_root"] / "heartbeat.json"
    _wait_for(claim_path)
    _wait_for(heartbeat_path)
    claim_sha = _sha(claim_path)
    first = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    second = first
    while second["sequence"] <= first["sequence"] and time.monotonic() < deadline:
        time.sleep(0.15)
        second = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert second["sequence"] > first["sequence"]
    assert second["monotonic_elapsed_ms"] > first["monotonic_elapsed_ms"]
    status = subprocess.run(
        _status_command(attempt_fixture, claim_sha),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert status.returncode == 0, status.stdout + status.stderr
    assert json.loads(status.stdout)["state"] == "RUNNING"
    interrupt = {
        "schema_version": "workstation_codex_mission_interrupt_v0.1",
        "mission_id": "synthetic-mission",
        "attempt": 1,
        "claim_sha256": claim_sha,
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "synthetic test completion",
    }
    (attempt_fixture["attempt_root"] / "interrupt-request.json").write_text(
        json.dumps(interrupt), encoding="utf-8"
    )
    proc.wait(timeout=15)
    assert proc.returncode == 22
    assert _terminal(attempt_fixture)["state"] == "INTERRUPTED"


def test_success_requires_validated_handback_and_complete_bundle(attempt_fixture):
    _write_handback_helper(attempt_fixture)
    completed = _run(
        attempt_fixture,
        "handback",
        extra_env={"FAKE_HANDBACK_HELPER": str(attempt_fixture["helper"])},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    terminal = _terminal(attempt_fixture)
    assert terminal["state"] == "COMPLETE_VALIDATED"
    assert terminal["child_tree_teardown_confirmed"] is True
    assert terminal["validation"]["bundle_verify"] == "PASS"
    assert terminal["validation"]["strict_fsck"] == "PASS"
    assert terminal["validation"]["result_tip"] == _git(
        "rev-parse", attempt_fixture["result_ref"], cwd=attempt_fixture["repo"]
    ).stdout.strip()
    assert _git("status", "--porcelain=v1", cwd=attempt_fixture["result_worktree"]).stdout == ""


def test_zero_exit_without_handback_is_invalid(attempt_fixture):
    completed = _run(attempt_fixture, "exit0")
    assert completed.returncode == 23
    terminal = _terminal(attempt_fixture)
    assert terminal["state"] == "INVALID_HANDBACK"
    assert terminal["child_tree_teardown_confirmed"] is True


def test_deadline_terminates_complete_descendant_tree(attempt_fixture):
    descendant_path = attempt_fixture["attempt_root"].parent / "descendant.pid"
    completed = _run(
        attempt_fixture,
        "sleep_descendant",
        deadline_seconds=4,
        timeout=15,
        extra_env={"FAKE_DESCENDANT_PID_PATH": str(descendant_path)},
    )
    assert completed.returncode == 21, completed.stdout + completed.stderr
    _wait_for(descendant_path)
    descendant_pid = int(descendant_path.read_text(encoding="ascii").strip())
    terminal = _terminal(attempt_fixture)
    assert terminal["state"] == "DEADLINE"
    assert terminal["child_tree_teardown_confirmed"] is True
    assert not _is_running(terminal["child_root_pid"])
    assert not _is_running(terminal["codex_pid"])
    assert not _is_running(descendant_pid)


def test_attempt_outputs_are_create_only_and_never_retried(attempt_fixture):
    first = _run(attempt_fixture, "exit17")
    assert first.returncode == 20
    terminal_path = attempt_fixture["attempt_root"] / "terminal-receipt.json"
    before = terminal_path.read_bytes()
    second = _run(attempt_fixture, "exit0")
    assert second.returncode != 0
    assert terminal_path.read_bytes() == before
    assert _terminal(attempt_fixture)["state"] == "CHILD_FAILURE"


def test_controller_identity_drift_fails_closed(attempt_fixture):
    completed = _run(attempt_fixture, "identity_drift")
    assert completed.returncode == 24, completed.stdout + completed.stderr
    terminal = _terminal(attempt_fixture)
    assert terminal["state"] == "IDENTITY_DRIFT"
    assert "controller worktree identity drift" in terminal["detail"]


def test_controller_checkout_skips_lfs_download_and_restores_scope(
    tmp_path: Path, fake_codex_binary: Path, local_lfs_endpoint
):
    state, endpoint = local_lfs_endpoint
    repo = tmp_path / "repo"
    identities = _make_lfs_repo(repo, endpoint, state)
    mission = tmp_path / "mission.md"
    mission.write_text("sealed synthetic LFS mission\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    env_capture = tmp_path / "captured-lfs-env.txt"
    branch = f"codex/synthetic-lfs-{uuid.uuid4().hex}"
    fixture = {
        **identities,
        "repo": repo,
        "mission": mission,
        "mission_sha": _sha(mission),
        "attempt_root": evidence / "attempt-1",
        "controller": tmp_path / "controller",
        "result_worktree": tmp_path / "result",
        "result_ref": f"refs/heads/{branch}",
        "result_branch": branch,
        "report": "docs/roadmap/synthetic-report.md",
        "receipt": "docs/roadmap/synthetic-handback.json",
        "bundle": evidence / "final.bundle",
        "codex": tmp_path / "codex.exe",
    }
    shutil.copy2(fake_codex_binary, fixture["codex"])

    repo_config_before = (repo / ".git" / "config").read_bytes()
    global_before = _git("config", "--global", "--null", "--show-origin", "--list", check=False)
    system_before = _git("config", "--system", "--null", "--show-origin", "--list", check=False)
    parent_env_before = os.environ.get("GIT_LFS_SKIP_SMUDGE")
    completed = _run(
        fixture,
        "capture_lfs_env",
        extra_env={
            "GIT_LFS_SKIP_SMUDGE": "0",
            "FAKE_ENV_CAPTURE_PATH": str(env_capture),
        },
    )
    assert completed.returncode == 23, completed.stdout + completed.stderr
    assert (fixture["controller"] / "payload.bin").read_bytes() == identities["pointer"]
    assert state["requests"] == []
    assert _git("status", "--porcelain=v1", cwd=fixture["controller"]).stdout == ""
    assert _git("rev-parse", "HEAD", cwd=fixture["controller"]).stdout.strip() == identities["source"]
    assert _git("rev-parse", "HEAD^{tree}", cwd=fixture["controller"]).stdout.strip() == identities["source_tree"]
    assert env_capture.read_text(encoding="utf-8") == "0"
    assert os.environ.get("GIT_LFS_SKIP_SMUDGE") == parent_env_before
    assert (repo / ".git" / "config").read_bytes() == repo_config_before
    global_after = _git("config", "--global", "--null", "--show-origin", "--list", check=False)
    system_after = _git("config", "--system", "--null", "--show-origin", "--list", check=False)
    assert (global_after.returncode, global_after.stdout, global_after.stderr) == (
        global_before.returncode,
        global_before.stdout,
        global_before.stderr,
    )
    assert (system_after.returncode, system_after.stdout, system_after.stderr) == (
        system_before.returncode,
        system_before.stdout,
        system_before.stderr,
    )


@pytest.mark.parametrize(
    ("identity", "drift"),
    (("Git", "path"), ("Git", "sha"), ("Windows PowerShell", "path"), ("Windows PowerShell", "sha")),
)
def test_final_executable_identity_drift_fails_before_handback(
    tmp_path: Path, identity: str, drift: str
):
    paths = {}
    for name in ("mission", "codex", "runner", "job", "powershell", "git"):
        path = tmp_path / f"{name}.bin"
        path.write_bytes(f"synthetic {name}\n".encode("ascii"))
        paths[name] = path
    claim = {
        "mission_path": str(paths["mission"]),
        "mission_sha256": _sha(paths["mission"]),
        "codex_path": str(paths["codex"]),
        "codex_sha256": _sha(paths["codex"]),
        "runner_path": str(paths["runner"]),
        "runner_sha256": _sha(paths["runner"]),
        "job_helper_path": str(paths["job"]),
        "job_helper_sha256": _sha(paths["job"]),
        "powershell_path": str(paths["powershell"]),
        "powershell_sha256": _sha(paths["powershell"]),
        "git_path": str(paths["git"]),
        "git_sha256": _sha(paths["git"]),
    }
    target_key = "git" if identity == "Git" else "powershell"
    actual_path = paths[target_key]
    if drift == "sha":
        actual_path.write_bytes(actual_path.read_bytes() + b"drift\n")
    else:
        replacement = tmp_path / f"{target_key}-replacement.bin"
        shutil.copy2(actual_path, replacement)
        actual_path = replacement

    runner_text = RUNNER.read_text(encoding="utf-8")
    definitions = tmp_path / "runner-definitions.ps1"
    definitions.write_text(runner_text[: runner_text.rfind("switch ($Mode)")], encoding="utf-8")
    contract = tmp_path / "identity-contract.json"
    contract.write_text(
        json.dumps(
            {
                "definitions": str(definitions),
                "paths": {**{key: str(value) for key, value in paths.items()}, target_key: str(actual_path)},
                "claim": claim,
            }
        ),
        encoding="utf-8",
    )
    harness = tmp_path / "identity-harness.ps1"
    harness.write_text(
        "$c=Get-Content -LiteralPath $args[0] -Raw|ConvertFrom-Json\n"
        ". $c.definitions\n"
        "try {\n"
        "  Assert-FinalExecutableIdentity -MissionPath $c.paths.mission -CodexPath $c.paths.codex `\n"
        "    -RunnerPath $c.paths.runner -JobHelperPath $c.paths.job `\n"
        "    -PowerShellPath $c.paths.powershell -GitPath $c.paths.git -Claim $c.claim\n"
        "  exit 0\n"
        "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 41 }\n",
        encoding="utf-8",
    )
    checked = subprocess.run(
        [
            str(POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            str(contract),
        ],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert checked.returncode == 41
    assert f"{identity} executable identity drift" in checked.stderr

    final_boundary = runner_text.index("if ($teardownConfirmed -and $terminalState -eq \"PENDING_VALIDATION\")")
    identity_call = runner_text.index("Assert-FinalExecutableIdentity", final_boundary)
    identity_terminal = runner_text.index('$terminalState = "IDENTITY_DRIFT"', identity_call)
    handback_call = runner_text.index("Assert-Handback", final_boundary)
    assert identity_call < identity_terminal < handback_call


def test_dirty_root_does_not_block_clean_controller_handback(attempt_fixture):
    dirty = attempt_fixture["repo"] / "unrelated-user-scratch.txt"
    dirty.write_text("preserve me\n", encoding="utf-8")
    _write_handback_helper(attempt_fixture)
    completed = _run(
        attempt_fixture,
        "handback",
        extra_env={"FAKE_HANDBACK_HELPER": str(attempt_fixture["helper"])},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _terminal(attempt_fixture)["state"] == "COMPLETE_VALIDATED"
    assert dirty.read_text(encoding="utf-8") == "preserve me\n"
    assert "?? unrelated-user-scratch.txt" in _git(
        "status", "--short", cwd=attempt_fixture["repo"]
    ).stdout


def test_interrupt_request_terminalizes_and_tears_down(attempt_fixture):
    proc = _start(attempt_fixture, "sleep")
    claim_path = attempt_fixture["attempt_root"] / "claim.json"
    child_start_path = attempt_fixture["attempt_root"] / "child-start.json"
    _wait_for(claim_path)
    _wait_for(child_start_path)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    child_start = json.loads(child_start_path.read_text(encoding="utf-8"))
    interrupt = {
        "schema_version": "workstation_codex_mission_interrupt_v0.1",
        "mission_id": "synthetic-mission",
        "attempt": 1,
        "claim_sha256": _sha(claim_path),
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "synthetic interruption",
    }
    path = attempt_fixture["attempt_root"] / "interrupt-request.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(interrupt, handle)
    proc.wait(timeout=15)
    terminal = _terminal(attempt_fixture)
    assert proc.returncode == 22
    assert terminal["state"] == "INTERRUPTED"
    assert terminal["child_tree_teardown_confirmed"] is True
    assert not _is_running(claim["child_root_pid"])
    assert not _is_running(child_start["codex_pid"])


def test_status_reader_rejects_cross_attempt_malformed_and_classifies_stale(attempt_fixture):
    proc = _start(attempt_fixture, "sleep", deadline_seconds=25)
    claim_path = attempt_fixture["attempt_root"] / "claim.json"
    status_path = attempt_fixture["attempt_root"] / "status.json"
    _wait_for(claim_path)
    _wait_for(status_path)
    claim_sha = _sha(claim_path)
    wrong = subprocess.run(
        _status_command(attempt_fixture, "0" * 64),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert wrong.returncode != 0
    _kill_tree(proc.pid)
    proc.wait(timeout=10)
    time.sleep(1.2)
    stale = subprocess.run(
        _status_command(attempt_fixture, claim_sha, stale_after=1),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert stale.returncode == 0, stale.stdout + stale.stderr
    assert json.loads(stale.stdout)["state"] == "ABRUPT_WRAPPER_EXIT_OR_CLIENT_DISCONNECT"
    status_path.write_bytes(b'{"schema_version":')
    malformed = subprocess.run(
        _status_command(attempt_fixture, claim_sha, stale_after=1),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert malformed.returncode != 0


def test_runner_binds_explicit_executable_and_has_no_retry_or_network_git_surface():
    text = RUNNER.read_text(encoding="utf-8")
    assert "ExpectedCodexSha256" in text
    assert "codex_sha256" in text
    assert "worktree\", \"add\", \"--detach" in text
    assert "COMPLETE_VALIDATED" in text
    assert "git push" not in text.lower()
    assert "start-scheduledtask" not in text.lower()
    assert "register-scheduledtask" not in text.lower()
    assert "retry" not in text.lower()
