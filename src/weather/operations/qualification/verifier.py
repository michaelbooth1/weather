"""Actual contained offline verification using the independently pinned gh.

Construction is an adopted-controller operation. No downloaded artifact can
choose the controller files, native runtime, executable roots or output folder.
The Windows default is off-host; capture-host execution belongs to its parent
under the separately admitted host plan.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import authentication, environment, process
from .contracts import fields, inventory
from .records import checked_root, decode, encode, open_record, require
from .runner import TRUSTED_WINDOWS, native_result


CHILD = "scripts/ops/qualification_verifier_child.py"


class ContainedVerifier:
    def __init__(self, *, trusted_root, scratch, files, tools, runtime, trust_graph):
        self.trusted = checked_root(trusted_root)
        self.scratch = Path(scratch)
        checked_root(self.scratch.parent)
        require(not self.scratch.exists(), "verifier namespace spent")
        self.files, self.tools, self.runtime, self.trust_graph = files, tools, runtime, trust_graph
        self.platform = "windows" if os.name == "nt" else "linux"
        require(set(files) == {CHILD, *(TRUSTED_WINDOWS if os.name == "nt" else ())},
                "exact verifier launch closure required")
        require(set(tools) == {"python", "gh", *(["powershell"] if os.name == "nt" else [])},
                "exact verifier native tools required")
        for value in tools.values():
            fields(value, {"root", "path", "sha256", "size"})
            checked_root(Path(value["root"]))
        fields(runtime, {"root", "files", "exclusions"})
        self.verify_dependencies()

    def tool(self, name):
        return Path(self.tools[name]["root"]) / self.tools[name]["path"]

    def verify_dependencies(self):
        for path, expected in self.files.items():
            actual = environment.file_identity(self.trusted, path)
            require({key: actual[key] for key in ("sha256", "size")} == expected, "verifier launch closure drift")
        for item in self.tools.values():
            actual = environment.file_identity(Path(item["root"]), item["path"], native_installation=True)
            require(actual["sha256"] == item["sha256"] and actual["size"] == item["size"], "verifier native tool drift")
        root = checked_root(Path(self.runtime["root"]))
        require(self.tool("python").is_relative_to(root), "verifier interpreter outside reviewed runtime")
        expected = inventory(self.trust_graph.get(self.runtime["files"]), "qualification_runtime_files_v2")
        paths = environment.enumerate_files(root, excluded_directories=self.runtime["exclusions"])
        require(paths == [item["path"] for item in expected["files"]] and
                environment.files_manifest(root, paths, native_installation=True) == expected,
                "verifier runtime drift")
        self.trust_graph.fresh()

    def verify(self, *, graph, policy_ref, review_ref, certificate_ref, bundle_ref):
        self.verify_dependencies()
        command = authentication.verifier_command(graph, policy_ref, review_ref, certificate_ref, bundle_ref, self.tool("gh"))
        require(not self.scratch.exists(), "verifier namespace spent")
        self.scratch.mkdir()
        request = {"command": command, "gh_sha256": self.tools["gh"]["sha256"],
                   "output": str(self.scratch / "stdout.json"), "stderr": str(self.scratch / "stderr.log"),
                   "result": str(self.scratch / "exit.json")}
        raw = encode(request)
        require(len(raw) <= 16384, "verifier launch metadata exceeds bound")
        request_path = self.scratch / "request.json"
        with request_path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        argv = [str(self.tool("python")), "-I", "-S", "-B", str(self.trusted / CHILD),
                str(request_path), hashlib.sha256(raw).hexdigest()]
        options = dict(cwd=self.trusted, env=process.clean_environment(scratch=self.scratch,
                       executable_paths=[self.tool(name) for name in self.tools]),
                       transcript=self.scratch / "controller-output.log", seconds=120, teardown_seconds=30,
                       memory_bytes=512 * 1024**2, output_bytes=2 * 1024**2, minimum_disk_bytes=2 * 1024**3)
        if os.name == "nt":
            actual = process.windows_run(argv, powershell=self.tool("powershell"),
                                         dispatcher=self.trusted / "scripts/ops/qualification_offhost_process.ps1",
                                         scratch=self.scratch, **options)
        else:
            actual = process.linux_run(argv, **options)
        native_result(actual, platform=self.platform)
        with open_record(self.scratch, "stdout.json") as handle:
            stdout = handle.read(2 * 1024**2 + 1)
        require(0 < len(stdout) <= 2 * 1024**2, "verifier stdout missing or exceeds bound")
        with open_record(self.scratch, "exit.json") as handle:
            result = decode(handle.read(1024))
        require(fields(result, {"exit_code"})["exit_code"] == 0 and type(result["exit_code"]) is int,
                "actual offline verifier failed")
        self.verify_dependencies()
        graph.fresh()
        return {"stdout": stdout, "exit_code": result["exit_code"], "teardown_proved": actual["teardown_proved"]}
