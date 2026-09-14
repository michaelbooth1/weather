"""Trusted serial off-host runner: native commands become retained evidence.

The caller supplies reviewed roots, executable hashes and dependency closure.
No source file or receipt chooses another executable, plugin, shell command or
network endpoint. This module has no host/Scheduler/merge entry point.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

from . import coverage, environment, journal, junit, process
from .contracts import Graph, fields, record
from .records import checked_root, digest, encode, integer, publish, read, require


TRUSTED_PYTHON = {
    "child": "scripts/ops/qualification_child.py",
    "guard": "src/weather/operations/qualification/offline_guard.py",
    "observer": "src/weather/operations/qualification/pytest_observer.py",
}
TRUSTED_WINDOWS = (
    "scripts/ops/qualification_offhost_process.ps1", "scripts/ops/qualification_process.ps1",
    "scripts/ops/windows_kill_on_close_job.ps1", "scripts/ops/workload_admission.ps1",
    "config/international_live_execution_host.json",
)


def native_result(value, *, platform, exit_code=0):
    common = {"completed", "failure", "exit_code", "teardown_proved", "elapsed_ms", "peak_working_set_bytes",
              "maximum_sample_gap_ms", "resource_samples", "minimum_disk_bytes", "started_at", "completed_at"}
    fields(value, common | ({"peak_private_bytes", "native_peak_commit_bytes", "system_commit_basis_points"}
                            if platform == "windows" else set()))
    require(value["completed"] is True and value["failure"] is None and value["teardown_proved"] is True and
            type(value["exit_code"]) is int and value["exit_code"] == exit_code, "native execution/cleanup did not pass")
    integer(value["maximum_sample_gap_ms"], maximum=1000)
    integer(value["resource_samples"], minimum=1)
    for key in common - {"completed", "failure", "exit_code", "teardown_proved", "started_at", "completed_at"}:
        integer(value[key])
    return value


def validate_process(graph, ref, *, platform, transcript, exit_code=0):
    value = record(graph.get(ref), "qualification_process_v2", {"platform", "argv_sha256", "limits", "native", "transcript"})
    require(value["platform"] == platform and value["transcript"] == transcript, "native transcript/platform differs")
    digest(value["argv_sha256"])
    limits = fields(value["limits"], {"seconds", "teardown_seconds", "memory_bytes", "output_bytes", "minimum_disk_bytes"})
    integer(limits["seconds"], minimum=1, maximum=1200)
    integer(limits["teardown_seconds"], minimum=1, maximum=120)
    integer(limits["memory_bytes"], minimum=16 * 1024**2, maximum=16 * 1024**3)
    integer(limits["output_bytes"], minimum=1, maximum=128 * 1024**2)
    integer(limits["minimum_disk_bytes"])
    actual = native_result(value["native"], platform=platform, exit_code=exit_code)
    require(actual["elapsed_ms"] <= (limits["seconds"] + limits["teardown_seconds"]) * 1000,
            "native process exceeded total envelope")
    require(actual["peak_working_set_bytes"] <= limits["memory_bytes"] and
            actual["minimum_disk_bytes"] >= limits["minimum_disk_bytes"], "native resource bound crossed")
    if platform == "windows":
        require(integer(actual["peak_private_bytes"]) <= limits["memory_bytes"] and
                integer(actual["native_peak_commit_bytes"]) <= limits["memory_bytes"], "native allocation limit refusal")
        integer(actual["system_commit_basis_points"], maximum=10000)
    graph.blob(transcript, maximum=limits["output_bytes"])
    return value


class Runner:
    def __init__(self, *, trusted_root, candidate_root, output_root, scratch_root, trusted_files,
                 executables, site_roots, forbidden_roots=(), seconds=1200, memory_bytes=4 * 1024**3):
        self.trusted, self.candidate, self.output, self.scratch = map(
            checked_root, (trusted_root, candidate_root, output_root, scratch_root))
        require(self.trusted != self.candidate and not self.candidate.is_relative_to(self.trusted) and
                not self.trusted.is_relative_to(self.candidate), "trusted and candidate source must be separate checkouts")
        require(not self.output.is_relative_to(self.candidate) and not self.scratch.is_relative_to(self.candidate),
                "output/scratch must be outside candidate")
        self.platform = "windows" if os.name == "nt" else "linux"
        require(set(executables) == ({"python", "git", "powershell"} if os.name == "nt" else {"python", "git"}),
                "exact native tool set required")
        self.executables = executables
        for value in executables.values():
            fields(value, {"root", "path", "sha256", "size"})
            tool_root = checked_root(Path(value["root"]))
            require(not tool_root.is_relative_to(self.candidate) and
                    not (tool_root / value["path"]).is_relative_to(self.candidate),
                    "native executable must be outside candidate source")
        self.trusted_files = trusted_files
        paths = set(TRUSTED_PYTHON.values()) | (set(TRUSTED_WINDOWS) if os.name == "nt" else set())
        require(set(trusted_files) == paths, "incomplete/extra trusted launch closure")
        self.sites = [checked_root(Path(p)) for p in site_roots]
        require(0 < len(self.sites) <= 4 and all(not p.is_relative_to(self.candidate) for p in self.sites),
                "explicit external dependency sites required")
        self.forbidden = [str(checked_root(Path(p))) for p in forbidden_roots]
        self.limits = {"seconds": seconds, "teardown_seconds": 30, "memory_bytes": memory_bytes,
                       "output_bytes": 128 * 1024**2, "minimum_disk_bytes": 2 * 1024**3}
        self.ordinal = 0
        self.verify_launch()

    def tool(self, name):
        item = self.executables[name]
        return Path(item["root"]) / item["path"]

    def verify_launch(self):
        for path, pin in self.trusted_files.items():
            actual = environment.file_identity(self.trusted, path)
            require({key: actual[key] for key in ("sha256", "size")} == pin, "trusted launch dependency drift")
        for item in self.executables.values():
            actual = environment.file_identity(Path(item["root"]), item["path"], native_installation=True)
            require(actual["sha256"] == item["sha256"] and actual["size"] == item["size"], "native executable drift")

    def blob(self, path):
        relative = Path(path).relative_to(self.output).as_posix()
        item = environment.file_identity(self.output, relative, maximum=128 * 1024**2)
        require(item["size"] > 0, "required native output is empty")
        return {key: item[key] for key in ("path", "sha256", "size")}

    def execute(self, mode, *, nodes=()):
        require(mode in {"collect", "tests", "imports", "compile", "agent_docs_audit", "roadmap_lint"}, "unsupported fixed mode")
        require((mode == "tests") == bool(nodes), "only execution accepts explicit node IDs")
        for node in nodes:
            coverage.node_id(node)
        self.verify_launch()
        self.ordinal += 1
        name = f"{self.platform}-{self.ordinal:04d}-{mode}"
        work = self.scratch / name
        work.mkdir()
        output = self.output / name
        output.mkdir()
        transcript = output / "transcript.txt"
        command = {"candidate": str(self.candidate), "mode": mode, "nodes": list(nodes),
                   "site_roots": [str(p) for p in self.sites],
                   "writable_roots": [str(work), str(output)], "forbidden_roots": self.forbidden,
                   "executable_paths": [str(self.tool(n)) for n in self.executables],
                   "cache": str(work / "cache"), "basetemp": str(work / "pytest"),
                   "junit": str(output / "junit.xml"), "imports": str(output / "imports.json")}
        for key, path in TRUSTED_PYTHON.items():
            command[key] = {"path": str(self.trusted / path), "sha256": self.trusted_files[path]["sha256"]}
        request = publish(work, "command.json", command)
        argv = [str(self.tool("python")), "-I", "-S", command["child"]["path"],
                str(work / request["path"]), request["sha256"]]
        env = process.clean_environment(scratch=work, executable_paths=command["executable_paths"],
                                        extra={"WEATHER_QUALIFICATION_JOURNAL": str(output / "journal.jsonl")})
        options = dict(cwd=self.candidate, env=env, transcript=transcript, **self.limits)
        started_at = process.utc()
        if self.platform == "windows":
            native = process.windows_run(argv, powershell=self.tool("powershell"),
                                         dispatcher=self.trusted / TRUSTED_WINDOWS[0], scratch=work, **options)
        else:
            native = process.linux_run(argv, **options)
        # A failure retains its raw native result and all partial output. It
        # never publishes a successful chunk or retries this spent directory.
        publish(output, "native.json", native)
        native_result(native, platform=self.platform)
        self.verify_launch()
        if transcript.stat().st_size == 0:
            # Successful quiet checks still need an actual retained transcript;
            # this parent marker is explicit and does not impersonate child text.
            with transcript.open("ab") as handle:
                handle.write(b"[trusted parent: native child produced no stdout/stderr]\n")
                handle.flush()
                os.fsync(handle.fileno())
        transcript_ref = self.blob(transcript)
        receipt = {"schema": "qualification_process_v2", "platform": self.platform,
                   "argv_sha256": hashlib.sha256(encode({"argv": argv})).hexdigest(), "limits": self.limits,
                   "native": native, "transcript": transcript_ref}
        ref = publish(self.output, name + "/process.json", receipt)
        validate_process(Graph(self.output), ref, platform=self.platform, transcript=transcript_ref)
        return {"started_at": started_at, "completed_at": process.utc(), "process": ref,
                "transcript": transcript_ref, "directory": output, "exit_code": native["exit_code"]}

    def collect(self):
        result = self.execute("collect")
        ref = self.blob(result["directory"] / "journal.jsonl")
        summary = journal.consume(self.output, ref, candidate_root=self.candidate,
                                  native_exit_code=result["exit_code"], collect_only=True)
        require(summary["status"] == "PASS", "native collection failed/deselected")
        return {**result, "journal": ref, "summary": summary}

    def chunk(self, expected, *, run, job_id):
        result = self.execute("tests", nodes=[node["nodeid"] for node in expected["nodes"]])
        journal_ref = self.blob(result["directory"] / "journal.jsonl")
        junit_ref = self.blob(result["directory"] / "junit.xml")
        summary = journal.consume(self.output, journal_ref, candidate_root=self.candidate, native_exit_code=result["exit_code"])
        junit.verify(self.output, junit_ref, summary["results"])
        chunk = {"schema": "qualification_chunk_v2", "id": expected["id"], "platform": self.platform,
                 "run": run, "job_id": job_id, "started_at": result["started_at"], "completed_at": result["completed_at"],
                 **summary, "journal": journal_ref, "junit": junit_ref, "transcript": result["transcript"],
                 "process": result["process"]}
        coverage.validate_chunk(chunk, expected, platform=self.platform, run=run, job_id=job_id,
                                now=process.datetime.now(process.timezone.utc), skew=0)
        return publish(self.output, result["directory"].name + "/chunk.json", chunk)
