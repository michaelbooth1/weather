"""Contained wrapper dispatch and bounded receipt reads for one night."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time

from weather.operations import storage_recovery_night_contract as contract
from weather.operations import storage_recovery_night_evidence as evidence
from weather.operations import storage_recovery_inventory as metadata
from weather.paths import repo_path

KINDS = {
    "inventory": ("storage_recovery_inventory_run.ps1", "storage_recovery_inventory", 180),
    "dry": ("cold_snapshot_compression_run.ps1", "cold_snapshot_compression", 150),
    "apply": ("cold_snapshot_compression_run.ps1", "cold_snapshot_compression", 360),
    "verify": ("cold_snapshot_compression_run.ps1", "cold_snapshot_compression", 150),
}


def source_clean(source, expected):
    for args, wanted in ((["rev-parse", "HEAD"], expected), (["status", "--porcelain"], "")):
        result = subprocess.run(["git", "-C", str(source), *args], capture_output=True,
                                text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or len(result.stdout) > 65536 or result.stdout.strip() != wanted:
            raise ValueError("reviewed source changed or cannot be proved clean")


def runtime_owner(source, expected_host):
    from weather.operations.windows_processes import snapshot_processes, describe_process
    from weather.execution_host import current_execution_host_id
    if os.name != "nt" or source != repo_path():
        raise ValueError("night controller requires its bound native source")
    if os.environ.get(contract.ENV + "SOURCE_ROOT") != str(source):
        raise ValueError("night controller imports escaped the wrapper source")
    owner = int(os.environ.get(contract.ENV + "OWNER_PID", "0"))
    token = os.environ.get(contract.ENV + "OWNER_TOKEN")
    observed = describe_process(owner)
    if not owner or not token or observed.get("creation_time_token") != token:
        raise ValueError("night controller wrapper owner is missing or changed")
    table, current = snapshot_processes(), os.getpid()
    if table is None:
        raise ValueError("native process ancestry unavailable")
    for _ in range(3):
        current = (table.get(current) or {}).get("parent_pid")
        if current == owner:
            break
    else:
        raise ValueError("night controller owner is not its live wrapper ancestor")
    if current_execution_host_id() != expected_host:
        raise ValueError("night controller host differs from its plan")


def invoke(plan, *, segment, index, kind, request, output_dir, plan_sha256, deadline):
    script_name, family, maximum_seconds = KINDS[kind]
    root, source = Path(plan["production_repo_root"]), Path(plan["source_root"])
    source_clean(source, plan["source_git_sha"])
    if (deadline - datetime.now(timezone.utc)).total_seconds() < maximum_seconds + 30:
        raise TimeoutError("not enough time to dispatch and contain the next wrapper")
    name = f"{plan['plan_id']}-{segment}-{index:04d}-{kind}"
    attempt = root / "scratch" / family / name
    if attempt.exists():
        raise ValueError("spent wrapper namespace")
    request_path = output_dir / "requests" / f"{index:04d}-{kind}.json"
    request_sha = contract.write_json(request_path, request, 128 * 1024)
    intent_path = output_dir / "steps" / f"{index:04d}-{kind}-intent.json"
    intent = {
        "kind": kind, "request_path": str(request_path), "request_sha256": request_sha,
        "output_root": str(attempt), "plan_sha256": plan_sha256,
        "source_git_sha": plan["source_git_sha"], "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    contract.write_json(intent_path, intent)
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    args = [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(source / "scripts/ops" / script_name), "-ProductionRepoRoot", str(root),
            "-RequestPath", str(request_path), "-RequestSha256", request_sha,
            "-OutputRoot", str(attempt), "-ExpectedSourceTip", plan["source_git_sha"]]
    if kind != "inventory":
        args += ["-MaxRuntimeSeconds", "300" if kind == "apply" else "90"]
    if kind == "apply":
        args.append("-Apply")
    if kind == "verify":
        args.append("-VerifyRetained")
    log_path = output_dir / "steps" / f"{index:04d}-{kind}.log"
    started = time.monotonic()
    with log_path.open("xb") as log:
        process = subprocess.Popen(args, cwd=source, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while process.poll() is None:
                if (time.monotonic() - started >= maximum_seconds or datetime.now(timezone.utc) >= deadline
                        or log_path.stat().st_size > contract.MIB):
                    raise RuntimeError("wrapper exceeded its dispatch time or output bound")
                time.sleep(0.25)
            code = process.wait(timeout=5)
        except BaseException:
            # The nested wrapper's kill-on-close Job owns its descendants; the
            # outer night Job independently drains the complete tree on failure.
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise
        log.flush()
        os.fsync(log.fileno())
    wrapper_path = attempt / "wrapper-result.json"
    if not wrapper_path.exists():
        raw = log_path.read_text(encoding="utf-8", errors="replace")
        if (code != 0 and not attempt.exists()
                and "REFUSED: shared workload lease is busy" in raw):
            terminal = {**intent, "status": "BUSY_BEFORE_DISPATCH", "returncode": code,
                        "source_files_changed": 0, "deleted_files": 0}
            contract.write_json(output_dir / "steps" / f"{index:04d}-{kind}-terminal.json", terminal)
            return {"busy": True, "intent": intent, "request": request, "request_sha": request_sha,
                    "output_bytes": log_path.stat().st_size + request_path.stat().st_size + 16384}
        raise ValueError("wrapper has no terminal teardown receipt; retain and stop")
    wrapper, wrapper_sha = contract.read_json(wrapper_path, 2 * contract.MIB)
    evidence.validate_wrapper(wrapper, request_sha=request_sha, plan=plan, kind=kind)
    result = result_sha = refusal = None
    if (attempt / "result.json").exists():
        result, result_sha = contract.read_json(
            attempt / "result.json", 2 * contract.MIB,
            wrapper.get("child_result_sha256") if wrapper["status"] == "PASS" else None)
        evidence.validate_result_header(result, request, request_sha, plan, kind)
    if (attempt / "refusal.json").exists():
        refusal, _ = contract.read_json(attempt / "refusal.json", 2 * contract.MIB)
        if (refusal.get("source_git_sha") != plan["source_git_sha"]
                or refusal.get("request_sha256") != request_sha
                or refusal.get("deleted_files") != 0 or refusal.get("cleanup_eligible") is not False):
            raise ValueError("refusal receipt binding mismatch")
    if (wrapper["status"] == "PASS") != (code == 0):
        raise ValueError("wrapper process exit differs from its receipt")
    journals, hashes, total_bytes = {}, {}, 0
    entries = list(attempt.iterdir())
    if len(entries) > 2 * 256 + 8:
        raise ValueError("attempt output cardinality exceeded")
    for path in entries:
        info = metadata.checked_stat(path, directory=False)
        total_bytes += info.st_size
        if path.name.endswith(("-before.json", "-after.json", "-verification.json")):
            value, sha = contract.read_json(path, 2 * contract.MIB)
            journals[path.name], hashes[path.name] = value, sha
    source_clean(source, plan["source_git_sha"])
    terminal = {**intent, "status": wrapper["status"], "returncode": code,
                "wrapper_sha256": wrapper_sha, "result_sha256": result_sha,
                "journal_sha256": hashes, "output_bytes": total_bytes}
    contract.write_json(output_dir / "steps" / f"{index:04d}-{kind}-terminal.json", terminal)
    return {"busy": False, "wrapper": wrapper, "wrapper_sha": wrapper_sha,
            "result": result, "result_sha": result_sha, "refusal": refusal,
            "journals": journals, "journal_hashes": hashes, "request": request,
            "request_sha": request_sha, "attempt": attempt,
            "output_bytes": total_bytes + log_path.stat().st_size + request_path.stat().st_size
                            + intent_path.stat().st_size
                            + (output_dir / "steps" / f"{index:04d}-{kind}-terminal.json").stat().st_size}


def failure_error(outcome):
    return (outcome.get("result") or outcome.get("refusal") or {}).get("error")


def append_rows(current, added):
    existing = {row["path"].casefold() for row in current}
    if any(row["path"].casefold() in existing for row in added):
        raise ValueError("a previously credited file cannot be counted again")
    combined = current + added
    contract.validate_ledger(combined)
    return combined
