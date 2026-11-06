"""The workstation wrapper's research_script kind admits only a named, sha-pinned script.

Guards: HOST_LOAD_POLICY workstation scope (master 2026-11-03, item b) - a research script runs only
as ``python -I <script>`` from an exact (path, sha256) allowlist entry under C:\\t\\<lane>\\; any sha
mismatch, missing entry, path outside one lane segment, "..", or reparse point/junction is refused
before a lease; the script is held deny-write from the hash until the child exits; a disk floor
refuses the start; the exit code and the Job's whole-tree peak committed memory are reported; and
the kind adds no mutex, slot or state name. The shipped allowlist holds exactly the reviewed entries in
SHIPPED_ENTRIES (each an exact path and sha256).

Every wrapper run here uses the slot tests' fixture-local mutex and state path, never the host's real
lease, and an overridden allowlist root under tmp_path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from tests.operations.test_workstation_heavy_slots import (
    POWERSHELL,
    _env,
    _events,
    _install,
    _write_assignment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or shutil.which("powershell") is None,
        reason="Windows PowerShell wrapper",
    ),
]

SCRIPT_BODY = """import json, os, sys
from pathlib import Path
record = Path(sys.argv[1])
ballast = bytearray(256 * 1024 * 1024)
try:
    with open(__file__, "a", encoding="utf-8"):
        writable = True
except PermissionError:
    writable = False
record.write_text(json.dumps({"isolated": sys.flags.isolated, "argv": sys.argv[1:], "self_writable": writable}))
sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _overrides(root: Path, entries: list[tuple[str, str]]) -> str:
    rows = "\n".join(f"        @{{ path = '{path}'; sha256 = '{sha}' }}" for path, sha in entries)
    return (
        "\n# TEST-ONLY RESEARCH-SCRIPT ROOT AND ALLOWLIST\n"
        f"function Get-WeatherWorkstationResearchScriptRoot {{ '{root}' }}\n"
        "function Get-WeatherWorkstationResearchScriptAllowlist {\n"
        f"    @(\n{rows}\n    )\n}}\n"
    )


def _lane_script(root: Path, lane: str = "L1") -> Path:
    script = root / lane / "scripts" / "run_probe.py"
    script.parent.mkdir(parents=True)
    script.write_text(SCRIPT_BODY, encoding="utf-8")
    return script


def _refusals(root: Path, entries: list[tuple[str, str]], cases: dict[str, tuple[str, str]]) -> dict:
    lines = "\n".join(
        f"$verdicts['{name}'] = Get-WeatherWorkstationResearchScriptRefusal -ScriptPath '{path}' -ActualSha256 '{sha}'"
        for name, (path, sha) in cases.items()
    )
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        f". '{OPS / 'workload_admission.ps1'}'\n"
        + _overrides(root, entries)
        + "$verdicts = [ordered]@{}\n"
        + lines
        + "\nConvertTo-Json -InputObject $verdicts -Compress\n"
    )
    result = subprocess.run([*POWERSHELL, "-Command", script], capture_output=True, text=True, check=False, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


SHIPPED_ENTRIES = [
    {"path": "C:\\t\\L59\\b0712\\scripts\\row28_run_v13.py",
     "sha256": "d23980b5123761ef0cfe46afa60274063aee66c84eb58169a55cb283a847f61d"},
    {"path": "C:\\t\\ws3\\projection\\scripts\\ws3_projection.py",
     "sha256": "9edf93c173d4978cf4a00420d038ff69fecb63034fec9fa2feec3051b5946740"},
    {"path": "C:\\t\\ws3\\scan\\book_nul_scan.py",
     "sha256": "481a71cd044d37af3cda41b1f630bd7aa0a6aac1150ea9d5e4ebf0b9c02ca757"},
    {"path": "C:\\t\\ws3\\projection\\scripts\\ws3_projection_v2.py",
     "sha256": "2bc440dabd40716bb28561a94da56fd9d2634ba1072e4ce51b2689712db9bfba"},
    {"path": "C:\\t\\ws3\\emit\\ws3_asof_emit.py",
     "sha256": "d3cd2dbffdc191713c6bcd58f822906aeb2d92008b9356b19e71fb3d50db0018"},
    {"path": "C:\\t\\ws3\\read\\scripts\\ws3_read_inputs.py",
     "sha256": "15a061698143ffed2feebf65210bd688913b55d89665065be4e4a063aab10c04"},
]


def test_shipped_allowlist_is_exactly_the_reviewed_entries_and_rooted_at_c_t() -> None:
    script = (
        f". '{OPS / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -Compress -InputObject @{ entries = @(Get-WeatherWorkstationResearchScriptAllowlist); "
        "root = Get-WeatherWorkstationResearchScriptRoot }\n"
    )
    result = subprocess.run([*POWERSHELL, "-Command", script], capture_output=True, text=True, check=False, timeout=120)
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    assert got["root"] == "C:\\t"
    entries = got["entries"] if isinstance(got["entries"], list) else [got["entries"]]
    assert [{"path": e["path"], "sha256": e["sha256"]} for e in entries] == SHIPPED_ENTRIES
    for entry in entries:
        assert set(entry) == {"path", "sha256"}
        assert "*" not in entry["path"] and "?" not in entry["path"] and entry["path"].endswith(".py")


def test_refusal_admits_only_the_exact_pinned_path_and_sha(tmp_path: Path) -> None:
    root = tmp_path / "t"
    script = _lane_script(root)
    sha = _sha(script)
    other = root / "L1" / "scripts" / "other.py"
    other.write_text("print(1)\n", encoding="utf-8")
    unpinned = root / "L1" / "scripts" / "unpinned.py"
    unpinned.write_text("print(2)\n", encoding="utf-8")
    (root / "L1" / "notes.txt").write_text("x", encoding="utf-8")
    (root / "top.py").write_text("x", encoding="utf-8")
    outside = tmp_path / "elsewhere" / "L1" / "run_probe.py"
    outside.parent.mkdir(parents=True)
    outside.write_text(SCRIPT_BODY, encoding="utf-8")
    junction = root / "L2"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(root / "L1")], capture_output=True, text=True, check=False
    )
    assert made.returncode == 0, made.stderr
    via_junction = junction / "scripts" / "run_probe.py"
    entries = [
        (str(script), sha),
        (str(other), "A" * 64),
        (str(via_junction), sha),
        (str(outside), _sha(outside)),
        (str(root / "top.py"), _sha(root / "top.py")),
    ]
    cases = {
        "admitted": (str(script), sha),
        "admitted_case_insensitive_path": (str(script).replace("run_probe", "RUN_probe"), sha),
        "sha_mismatch": (str(script), "0" * 64),
        "sha_uppercase": (str(script), sha.upper()),
        "sha_empty": (str(script), ""),
        "missing_file": (str(root / "L1" / "scripts" / "absent.py"), sha),
        "missing_entry": (str(unpinned), _sha(unpinned)),
        "unlisted_file": (str(root / "L1" / "notes.txt"), sha),
        "malformed_entry": (str(other), _sha(other)),
        "junction": (str(via_junction), sha),
        "outside_root": (str(outside), _sha(outside)),
        "no_lane_segment": (str(root / "top.py"), _sha(root / "top.py")),
        "dotdot": (str(root / "L1" / "scripts" / ".." / "scripts" / "run_probe.py"), sha),
        "wildcard": (str(root / "L1" / "scripts" / "run_*.py"), sha),
        "forward_slash": (str(script).replace("\\scripts\\", "/scripts/"), sha),
        "stream": (str(script) + ":evil.py", sha),
        "short_name": (str(root / "L1" / "SCRIPT~1" / "run_probe.py"), sha),
        "lane_directory": (str(root / "L1"), sha),
    }
    verdicts = _refusals(root, entries, cases)
    assert verdicts.pop("admitted") is None
    # The allowlist compare is ordinal-ignore-case, but every component must still exist.
    assert verdicts.pop("admitted_case_insensitive_path") is None
    assert "does not match the pinned" in verdicts.pop("sha_mismatch")
    assert "does not match the pinned" in verdicts.pop("sha_uppercase")
    assert "does not match the pinned" in verdicts.pop("sha_empty")
    assert "absent" in verdicts.pop("missing_file")
    assert "no single allowlist entry" in verdicts.pop("missing_entry")
    assert "named .py file" in verdicts.pop("unlisted_file")
    assert "malformed" in verdicts.pop("malformed_entry")
    assert "reparse point or junction" in verdicts.pop("junction")
    for name, refusal in verdicts.items():
        assert refusal and "named .py file" in refusal, (name, refusal)


def test_duplicate_entries_for_one_path_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "t"
    script = _lane_script(root)
    sha = _sha(script)
    verdicts = _refusals(root, [(str(script), sha), (str(script), sha)], {"dup": (str(script), sha)})
    assert "no single allowlist entry" in verdicts["dup"]


@pytest.fixture
def lane(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _install(repo)
    _write_assignment(repo, capture_identity=False)
    root = tmp_path / "t"
    script = _lane_script(root)
    return repo, root, script


def _pin(repo: Path, root: Path, entries: list[tuple[str, str]]) -> None:
    admission = repo / "scripts" / "ops" / "workload_admission.ps1"
    admission.write_text(admission.read_text(encoding="utf-8") + _overrides(root, entries), encoding="utf-8")


def _run(repo: Path, arguments: list[str], *extra: str) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(json.dumps(arguments).encode("utf-8")).decode("ascii")
    return subprocess.run(
        [
            *POWERSHELL, "-File", str(repo / "scripts/ops/workstation_heavy.ps1"), "-Kind", "research_script",
            "-PythonPath", sys.executable, "-ArgumentsBase64", encoded, "-RepoRoot", str(repo),
            "-Queue", "-QueuePollMilliseconds", "100", *extra,
        ],
        capture_output=True, text=True, check=False, timeout=240, env=_env(),
    )


def test_a_pinned_script_runs_isolated_locked_and_reports_rc_and_tree_peak(lane) -> None:
    repo, root, script = lane
    sha = _sha(script)
    _pin(repo, root, [(str(script), sha)])
    record = repo / "record.json"
    result = _run(repo, ["-I", str(script), str(record), "3"])
    assert result.returncode == 3, result.stderr
    ran = json.loads(record.read_text(encoding="utf-8"))
    assert ran == {"isolated": 1, "argv": [str(record), "3"], "self_writable": False}
    match = re.search(
        r"workstation-heavy: research_script exit_code=3 peak_job_memory_bytes=(\d+) script_sha256=([0-9a-f]{64})",
        result.stdout,
    )
    assert match, result.stdout
    # The 256 MiB ballast lives in the real interpreter behind the venv redirector stub.
    assert int(match.group(1)) >= 256 * 1024 * 1024
    assert match.group(2) == sha
    finish = next(event for event in _events(repo) if event["event"] == "finish")
    assert finish["exit_code"] == 3
    assert finish["script_path"] == str(script)
    assert finish["script_sha256"] == sha
    assert finish["peak_job_memory_bytes"] == int(match.group(1))
    assert finish["workload"].startswith("WorkstationOffline-research_script-")
    assert script.read_text(encoding="utf-8") == SCRIPT_BODY


@pytest.mark.parametrize(
    "case",
    ("sha_mismatch", "unpinned", "no_isolation_flag", "module_form", "live_switch", "disk_floor"),
)
def test_the_wrapper_refuses_before_starting_anything(lane, case: str) -> None:
    repo, root, script = lane
    record = repo / "record.json"
    arguments = ["-I", str(script), str(record)]
    extra: tuple[str, ...] = ()
    entries = [(str(script), _sha(script))]
    expected = "does not match the pinned"
    if case == "sha_mismatch":
        script.write_text(SCRIPT_BODY + "# edited after pinning\n", encoding="utf-8")
    elif case == "unpinned":
        entries = []
        expected = "no single allowlist entry"
    elif case == "no_isolation_flag":
        arguments = [str(script), str(record)]
        expected = "requires exact '-I <script>' arguments"
    elif case == "module_form":
        arguments = ["-m", "weather.calibration.b_scorer", str(record)]
        expected = "requires exact '-I <script>' arguments"
    elif case == "live_switch":
        arguments = ["-I", str(script), str(record), "--live"]
        expected = "no live switch"
    elif case == "disk_floor":
        extra = ("-MinFreeDiskGB", "4096")
        expected = "below the"
    _pin(repo, root, entries)
    result = _run(repo, arguments, *extra)
    assert result.returncode != 0
    assert expected in result.stderr, result.stderr
    assert not record.exists()
    assert not any(event["event"] == "finish" for event in _events(repo))
    if case != "disk_floor":
        # Refused before admission: no queue ticket was ever taken.
        assert _events(repo) == []


def test_the_kind_adds_no_mutex_slot_or_state_name() -> None:
    wrapper = (OPS / "workstation_heavy.ps1").read_text(encoding="utf-8-sig")
    admission = (OPS / "workload_admission.ps1").read_text(encoding="utf-8-sig")
    job = (OPS / "windows_kill_on_close_job.ps1").read_text(encoding="utf-8-sig")
    assert set(re.findall(r"(?:Global|Local)\\[A-Za-z0-9_.{}-]+", admission)) == {"Global\\WeatherProjectHeavyWorkloadV1"}
    for text in (wrapper, job):
        assert not re.search(r"(?:Global|Local)\\|Mutex|\.poison", text)
    assert '"workstation_offline_v1"' in wrapper
    assert 'workloadName = "WorkstationOffline-{0}-{1}" -f $Kind, $PID' in wrapper
