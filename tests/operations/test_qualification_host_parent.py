"""Actual nine fixed Windows probes under the same native containment primitive."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from weather.operations.qualification import environment, host, host_acceptance, process, records, runner


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="actual Windows inherited-handle and Job probes")


def test_real_fixed_host_probes_complete_inside_native_job(tmp_path):
    tmp_path = tmp_path.resolve()
    authority, output, trusted = [tmp_path / name for name in ("authority", "output", "trusted")]
    for path in (authority, output, trusted):
        path.mkdir()
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
    payload = {"manifest": {"worktree_root": str(ROOT), "repo_root": str(tmp_path / "production"),
        "control": {"root": str(trusted), "closure": closure}, "qualification": {"root": str(authority)}},
        "review": {"source_inventory": source_ref}, "host_plan": {"configuration": qref},
        "selected": selected, "deadline": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")}
    request = records.publish(authority, "parent.json", payload)
    # This disposable driver imports the installed authority package. The fixed
    # candidate child still verifies its source witness and runs all real probes.
    driver = tmp_path / "driver.py"
    driver.write_text("\n".join([
        "import json, sys",
        "from pathlib import Path",
        "from weather.operations.qualification import host_session, records",
        "from weather.operations.qualification.contracts import Graph",
        "root = Path(" + repr(str(authority)) + ")",
        "value = records.read(root, " + repr(request) + ").value",
        "value['local'] = Graph(root)",
        "result, markets = host_session._probes(value, value['selected'], Path(" + repr(str(output)) + "), value['deadline'])",
        "records.publish(Path(" + repr(str(output)) + "), 'complete.json', {'results': result, 'markets': markets})",
    ]), encoding="utf-8")
    for name in runner.TRUSTED_WINDOWS:
        target = trusted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    log = tmp_path / "native.log"
    try:
        native = process.windows_run([str(python), "-I", "-B", str(driver)],
            powershell=Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe",
            dispatcher=trusted / runner.TRUSTED_WINDOWS[0], scratch=tmp_path,
            cwd=trusted, env=process.clean_environment(scratch=output, executable_paths=[python]),
            transcript=log, seconds=120, teardown_seconds=30, memory_bytes=1024**3,
            output_bytes=1024**2, minimum_disk_bytes=1)
    except Exception:
        for path in (log, output / "probe-streams.log"):
            if path.exists():
                print(path.read_text(errors="replace")[-16384:])
        raise
    assert native["completed"] and native["teardown_proved"], (native, log.read_text(errors="replace"))
    result = json.loads((output / "complete.json").read_text())
    assert set(result["results"]) == set(host_acceptance.PROBES)
    assert result["markets"]
    for name, ref in result["results"].items():
        assert records.read(output, ref).value["name"] == name
