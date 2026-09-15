"""Fixed child work for the native S4U host entrypoint.

No mode registers, merges, pushes or claims host PASS. The native parent owns
the common lease, phase limits, actual task identity and final receipt.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

from . import attempt, host, host_acceptance, host_runtime, process
from .contracts import Graph
from .records import checked_root, decode, open_record, publish, read, require, timestamp, utc_now


def _raw_reference(root, name):
    with open_record(root, name) as handle:
        raw = handle.read(2 * 1024**2 + 1)
    require(0 < len(raw) <= 2 * 1024**2, "host phase output exceeds metadata bound")
    return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def _fixed_child(checked, name):
    path = "scripts/ops/" + name
    m = checked["manifest"]
    closure = checked["local"].get(m["control"]["closure"])
    pin = next(row for row in closure["files"] if row["path"] == path)
    from . import environment
    actual = environment.file_identity(Path(m["control"]["root"]), path)
    require(actual["sha256"] == pin["sha256"] and actual["size"] == pin["size"], "fixed adopted host child drift")
    return Path(m["control"]["root"]) / path, pin["sha256"]


def _probes(checked, selected, output, deadline):
    from datetime import datetime, timezone

    m = checked["manifest"]
    probe_output = output / "candidate"
    probe_output.mkdir()
    closure = checked["local"].get(m["control"]["closure"])
    lookup = {row["path"]: row["sha256"] for row in closure["files"]}
    _, bootstrap = _fixed_child(checked, "qualification_host_child.py")
    child, _ = _fixed_child(checked, "qualification_host_probe.py")
    request = {"candidate": m["worktree_root"], "trusted_root": m["control"]["root"], "bootstrap_sha256": bootstrap,
        "trusted_modules": {name: lookup["src/weather/operations/qualification/" + name + ".py"] for name in host.AUDIT_MODULES},
        "authority_root": m["qualification"]["root"], "source_inventory": checked["review"]["source_inventory"],
        "sites": selected["bindings"]["site_roots"], "output": str(probe_output),
        "configuration_root": str(checked["local"].root), "configuration": checked["host_plan"]["configuration"],
        "forbidden_roots": [str(Path(m["repo_root"]) / "data")]}
    request_ref = publish(output, "probe-request.json", request)
    python = host_runtime.tool(selected, "python")
    env = process.clean_environment(scratch=probe_output, executable_paths=[host_runtime.tool(selected, key)
                                                                         for key in selected["tools"]])
    remaining = (timestamp(deadline) - datetime.now(timezone.utc)).total_seconds()
    require(remaining > 2, "no host probe budget remains")
    with (output / "probe-streams.log").open("xb") as transcript:
        native = subprocess.run([str(python), "-I", "-S", "-B", str(child),
                                 str(output / request_ref["path"]), request_ref["sha256"]],
            executable=str(python), cwd=m["worktree_root"], env=env, stdin=subprocess.DEVNULL,
            stdout=transcript, stderr=subprocess.STDOUT, timeout=remaining - 1, check=False)
        transcript.flush()
        os.fsync(transcript.fileno())
    require(native.returncode == 0, "fixed native candidate probe failed")
    with open_record(output, "probe-streams.log") as transcript:
        stream = transcript.read(16385)
    require(len(stream) <= 16384 and b"qualification host stdout fixture" in stream and
            b"qualification host stderr fixture" in stream, "native probe streams incomplete")
    summary = read(probe_output, _raw_reference(probe_output, "probe-results.json")).value
    results = {name: {**ref, "path": "candidate/" + ref["path"]} for name, ref in summary["results"].items()}
    # Fixed disposable direct-child timeout: no production process is selected.
    timed = subprocess.Popen([str(python), "-I", "-S", "-B", "-c", "import time; time.sleep(60)"],
        executable=str(python), cwd=output, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    try:
        try:
            timed.wait(timeout=.1)
        except subprocess.TimeoutExpired:
            timed.kill()
            timed.wait(timeout=1)
        else:
            raise ValueError("timeout fixture exited before the timeout boundary")
        require(timed.poll() is not None, "timeout fixture teardown unproved")
    finally:
        if timed.poll() is None:
            timed.kill()
            timed.wait(timeout=1)
    require(os.name == "nt", "real host handle probe requires Windows")
    import msvcrt
    with (output / "private-inheritable-fixture.txt").open("xb") as private:
        handle = msvcrt.get_osfhandle(private.fileno())
        os.set_handle_inheritable(handle, True)
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        name = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, name, len(name), 0)
        require(0 < length < len(name), "private fixture handle identity unavailable")
        # Handle values are process-local and can be reused for unrelated
        # objects. Compare the actual open file, with a positive inheritance
        # control proving the child can detect that exact file handle.
        command = ("import ctypes; from ctypes import wintypes; "
                   "k=ctypes.WinDLL('kernel32',use_last_error=True); "
                   "k.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]; "
                   "k.GetFinalPathNameByHandleW.restype=wintypes.DWORD; "
                   "name=ctypes.create_unicode_buffer(32768); "
                   "size=k.GetFinalPathNameByHandleW(" + str(handle) + ",name,len(name),0); "
                   "raise SystemExit(9 if 0<size<len(name) and name.value.casefold()==" + repr(name.value.casefold()) + " else 0)")
        inherited = subprocess.STARTUPINFO()
        inherited.lpAttributeList = {"handle_list": [handle]}
        control = subprocess.run([str(python), "-I", "-S", "-B", "-c", command], executable=str(python),
            cwd=output, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, close_fds=True, startupinfo=inherited, check=False)
        require(control.returncode == 9, "private handle positive inheritance control failed")
        isolated = subprocess.run([str(python), "-I", "-S", "-B", "-c", command], executable=str(python),
            cwd=output, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, close_fds=True, check=False)
        require(isolated.returncode == 0, "unapproved private handle inherited by host child")
    for name, detail in {
        "captured_streams": "Both native child streams completed and were durably read back",
        "timeout_cleanup": "Exact disposable timeout child was killed and waited to native exit",
        "inherited_handles": "Inheritable private file handle was absent from fixed isolated child",
    }.items():
        results[name] = publish(output, name + ".json", {"schema": "qualification_host_probe_v2",
                               "name": name, "status": "PASS", "detail": detail})
    require(set(results) == set(host_acceptance.PROBES), "native probe inventory incomplete")
    return results, summary["markets"]


def run_phase(manifest_path, manifest_sha256, phase):
    require(os.name == "nt" and phase in host_acceptance.PHASES, "fixed native host phase required")
    manifest_path = Path(manifest_path)
    root = checked_root(manifest_path.parent)
    ref = _raw_reference(root, manifest_path.name)
    require(ref["sha256"] == manifest_sha256, "host manifest bytes changed")
    checked = attempt.manifest(read(root, ref).value, actual_root=root)
    plan, m = checked["host_plan"], checked["manifest"]
    selected = host_runtime.profile(checked["local"].get(plan["environment"]), checked=checked)
    measured = host_acceptance.measurements(checked["local"], plan["measurements"], policy=checked["policy"], host_plan=plan)
    maximum = measured["phases"][phase]["maximum"]
    output = root / "host-work" / phase
    checked_root(output)
    require(not (output / "phase.json").exists(), "native host phase namespace spent")
    started = utc_now()
    host_runtime.verify_source(checked, selected)
    results = {"probes": None, "audit": None, "code": None, "configuration": None, "markets": None}
    if phase in {"probes", "metadata"}:
        host_runtime.verify_environment(checked, selected)
        results["configuration"] = host_runtime.verify_configuration(checked, selected, maximum)
        signature = output / "signature"
        signature.mkdir()
        results["code"] = host_runtime.verify_code_in_parent(checked, selected, scratch=signature,
            deadline=plan["deadline"], boundary="launch")
    if phase == "probes":
        results["probes"], results["markets"] = _probes(checked, selected, output, plan["deadline"])
    elif phase == "audit" and plan["scope"] == "reliability_current_inputs":
        audit_plan = checked["local"].get(plan["audit"])
        observed_markets = read(root / "host-work/probes", _raw_reference(root / "host-work/probes", "phase.json")).value["markets"]
        require(audit_plan["markets"] == observed_markets, "current audit differs from the complete actual candidate registry")
        results["audit"] = host.run_audit(audit_plan, scratch=output)
    require(timestamp(started) <= timestamp(utc_now()) <= timestamp(plan["deadline"]), "native host phase exceeded absolute deadline")
    return publish(output, "phase.json", {"schema": "qualification_host_phase_v2", "phase": phase,
        "manifest_sha256": manifest_sha256, "host_plan_sha256": m["host"]["sha256"], "started_at": started,
        "completed_at": utc_now(), "native_parent_completion_required": True, "integration_eligible": False, **results})
