"""Native probe wiring and lifetime resource refusal on disposable inputs.

These are hosted Windows fixtures, not production S4U acceptance. The wiring
fixture isolates probe execution from the separately tested input validators.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from weather.operations.qualification import environment, host, host_acceptance, process, records, runner
from test_qualification_native_job import run as run_native


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows Job and handle probes")


def test_exited_nested_reader_remains_in_parent_job_io_accounting(tmp_path):
    (tmp_path / "input.bin").write_bytes(b"x" * (16 * 1024**2))
    (tmp_path / "reader.py").write_text("from pathlib import Path\nassert len(Path('input.bin').read_bytes()) == 16*1024**2\n", encoding="utf-8")
    run_native(tmp_path, r'''
$outer=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(536870912,16)
$job=[Weather.Operations.KillOnCloseJob]::CreateBounded(134217728,8)
$child=$null
try {
    $arguments=ConvertTo-WeatherWindowsArgumentString -Tokens @('-I','-S','-B',(Join-Path $root 'reader.py'))
    $child=$job.StartAssignedCaptured($python,$arguments,$root,(Join-Path $root 'reader.log'),4096)
    if(-not $child.Process.WaitForExit(10000) -or $child.Process.ExitCode -ne 0) {throw 'reader failed'}
    $job.TerminateAndWait(5000)
    if(-not $child.WaitForCapture(5000)) {throw 'reader EOF missing'}
    if($job.Snapshot().ProcessIds.Count -ne 0 -or $outer.Snapshot().ProcessIds.Count -ne 1) {throw 'reader remains'}
    if($job.Snapshot().ReadBytes -lt 16777216 -or $outer.Snapshot().ReadBytes -lt 16777216) {
        throw 'terminated nested reader disappeared from lifetime I/O accounting'
    }
} finally {
    $job.TerminateAndWait(5000)
    if($child){[void]$child.WaitForCapture(5000);$child.Dispose()}
    $job.Dispose();$outer.Dispose()
}
''')


def test_native_read_budget_refuses_and_proves_cleanup(tmp_path):
    (tmp_path / "input.bin").write_bytes(b"x" * (16 * 1024**2))
    (tmp_path / "reader.py").write_text("from pathlib import Path\nwhile True: Path('input.bin').read_bytes()\n", encoding="utf-8")
    helper = str(ROOT / "scripts/ops/qualification_process.ps1").replace("'", "''")
    run_native(tmp_path, ". '" + helper + "'\n" + r'''
$outer=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(536870912,16)
try {
    $result=Invoke-WeatherQualificationProcess -Envelope $outer -Executable $python `
        -Tokens @('-I','-S','-B',(Join-Path $root 'reader.py')) -WorkingDirectory $root `
        -Transcript (Join-Path $root 'reader.log') -DeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds(25)) `
        -MaximumSeconds 15 -TeardownSeconds 5 -CommitBytes 536870912 -WorkingSetBytes 536870912 `
        -MaximumOutputBytes 4096 -VolumePaths @($root) -MinimumDiskBytes 1 -MaximumReadBytes 4194304
    if($result.completed -or -not $result.teardown_proved -or $result.failure -notlike '*read budget*') {
        throw ('read-budget refusal/cleanup missing: '+($result | ConvertTo-Json -Compress))
    }
    if($outer.Snapshot().ReadBytes -le 4194304 -or $outer.Snapshot().ProcessIds.Count -ne 1) {throw 'native read/zero-child proof missing'}
} finally {$outer.Dispose()}
''')


def test_fixed_bootstrap_pipeline_records_all_nine_native_probes_without_acceptance(tmp_path):
    tmp_path = tmp_path.resolve()
    authority, trusted = [tmp_path / name for name in ("authority", "trusted")]
    output = authority / "probe-work" / "observations"
    for path in (authority, trusted, output):
        path.mkdir(parents=True, exist_ok=True)
    paths = sorted(path.relative_to(ROOT).as_posix() for directory in (ROOT / "src/weather", ROOT / "weather")
                   for path in directory.rglob("*.py"))
    source_ref = records.publish(authority, "source.json", {"schema": "qualification_source_inventory_v2",
        "files": environment.files_manifest(ROOT, paths)["files"]})
    generated = []
    for name in ("locations.json", "location_market_events.json"):
        raw = (ROOT / "config" / name).read_bytes()
        (authority / name).write_bytes(raw)
        generated.append({"path": "config/" + name, "payload": {
            "path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}})
    qref = records.publish(authority, "configuration.json", {"generated": generated})
    fixed = ["scripts/ops/qualification_host_child.py", "scripts/ops/qualification_host_probe.py",
             *("src/weather/operations/qualification/" + name + ".py" for name in host.AUDIT_MODULES)]
    for name in fixed:
        target = trusted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    closure = records.publish(authority, "closure.json", environment.files_manifest(trusted, fixed))
    python = Path(sys.executable).resolve()
    python_id = environment.file_identity(python.parent, python.name, native_installation=True)
    selected = {"tools": {"python": {"root": str(python.parent), **python_id}},
                "bindings": {"site_roots": [str(Path(pytest.__file__).resolve().parents[1])]}}
    deadline = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    payload = {"manifest": {"worktree_root": str(ROOT), "repo_root": str(tmp_path / "production"),
        "control": {"root": str(trusted), "closure": closure}, "qualification": {"root": str(authority)}},
        "review": {"source_inventory": source_ref}, "host_plan": {"configuration": qref},
        "envelope": {"deadline": deadline, "source": {"commit": "a" * 40, "tree": "b" * 40, "baseline": "c" * 40}},
        "selected": selected}
    request = records.publish(authority, "fixture-envelope.json", payload)
    driver = tmp_path / "driver.py"
    driver.write_text("\n".join([
        "from pathlib import Path",
        "from weather.operations.qualification import bootstrap_probe, records",
        "from weather.operations.qualification.contracts import Graph",
        "root = Path(" + repr(str(authority)) + ")",
        "value = records.read(root, " + repr(request) + ").value",
        "value['local'] = Graph(root)",
        "value['graph'] = Graph(root)",
        "bootstrap_probe.context = lambda *_: value",
        "bootstrap_probe.verify_inputs = lambda *_: (value['selected'], {'fixture': 'validated separately'})",
        "bootstrap_probe.run(root / " + repr(request["path"]) + ", " + repr(request["sha256"]) + ")",
    ]), encoding="utf-8")
    for name in runner.TRUSTED_WINDOWS:
        target = trusted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    log = tmp_path / "native.log"
    native = process.windows_run([str(python), "-I", "-B", str(driver)],
        powershell=Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe",
        dispatcher=trusted / runner.TRUSTED_WINDOWS[0], scratch=tmp_path, cwd=trusted,
        env=process.clean_environment(scratch=output, executable_paths=[python]),
        transcript=log, seconds=120, teardown_seconds=30, memory_bytes=1024**3,
        output_bytes=1024**2, minimum_disk_bytes=1)
    assert native["completed"] and native["teardown_proved"], (native, log.read_text(errors="replace"))
    result = json.loads((output / "observation.json").read_text())
    assert result["schema"] == "qualification_bootstrap_probe_observation_v1"
    assert set(result["results"]) == set(host_acceptance.PROBES)
    assert result["integration_eligible"] is result["full_suite_replacement"] is False
    assert result["native_parent_completion_required"] is True
    assert result["envelope_sha256"] == request["sha256"]
