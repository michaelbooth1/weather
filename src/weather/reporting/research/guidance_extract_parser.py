"""Isolated NBM NBP parser version 2, run from a pinned detached worktree (111h).

Parser v2 was first built on ``codex/nbm-target-fix-20260921`` @ ``2e17ce0eb``;
the extractor keeps that pin so every 111h extract reproduces byte for byte,
whatever parser the running tree carries. It starts a child interpreter with
``-P -B`` and ``PYTHONPATH=<pinned>/src`` and refuses to parse unless a probe
proves the parser module resolves under that exact tree, the worktree HEAD is
the pinned commit and its tracked files are unmodified.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PINNED_PARSER_COMMIT = "2e17ce0eb"
PARSER_MODULE = "weather.sources.nbm_probabilistic_tmax"
PARSER_V2_LABEL = "nbm-probabilistic-tmax-parser-v2"
RESULT_FIELDS = (
    "available", "reason", "parser_version", "issued_at", "valid_time_utc",
    "forecast_hour", "period_kind", "group_index", "token_index", "percentiles",
    "mean_native", "stddev_native", "value_rejection_reasons", "product_version",
)

# The child reads one JSON request per line and answers one JSON line each.
# It never touches the network or the data root; it only decodes the bytes
# the parent verified and calls the pinned parser with parser_version=2.
_CHILD = r"""
import hashlib, json, sys
import weather.sources.nbm_probabilistic_tmax as m
FIELDS = %s
if getattr(m, "NBM_NBP_PARSER_V2", None) != %r:
    raise SystemExit("pinned module lacks parser v2")
print(json.dumps({"module_file": m.__file__}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    data = open(request["blob"], "rb").read()
    if hashlib.sha256(data).hexdigest() != request["sha256"]:
        print(json.dumps({"error": "blob_sha256_mismatch"}), flush=True)
        continue
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        print(json.dumps({"error": "blob_not_utf8"}), flush=True)
        continue
    results = []
    for station, target in request["targets"]:
        try:
            payload = m.parse_nbp_station_tmax(text, station, target, parser_version=2)
        except ValueError as exc:
            payload = {"available": False, "reason": "parser_error:" + type(exc).__name__}
        results.append({k: payload.get(k) for k in FIELDS})
    print(json.dumps({"results": results}), flush=True)
"""


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def verify_pinned_worktree(root):
    """Return the pinned tree identity or raise; never trusts a dirty tree."""
    root = Path(root).resolve()
    head = _git(root, "rev-parse", "HEAD")
    if not head.startswith(PINNED_PARSER_COMMIT):
        raise ValueError(f"parser worktree HEAD {head} is not {PINNED_PARSER_COMMIT}")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("parser worktree has modified tracked files")
    module = root / "src" / "weather" / "sources" / "nbm_probabilistic_tmax.py"
    return {"root": str(root), "head": head,
            "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest()}


class PinnedParser:
    """Line-protocol client for the isolated parser child process."""

    def __init__(self, worktree, python=None):
        self.identity = verify_pinned_worktree(worktree)
        src = Path(self.identity["root"]) / "src"
        env = {k: v for k, v in os.environ.items() if k != "PYTHONHOME"}
        env["PYTHONPATH"] = str(src)
        env["PYTHONNOUSERSITE"] = "1"
        code = _CHILD % (repr(RESULT_FIELDS), PARSER_V2_LABEL)
        self.process = subprocess.Popen(
            [python or sys.executable, "-P", "-B", "-c", code], cwd=str(src), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        probe = json.loads(self.process.stdout.readline() or "{}")
        resolved = os.path.normcase(os.path.realpath(probe.get("module_file") or ""))
        prefix = os.path.normcase(os.path.realpath(src)) + os.sep
        if not resolved.startswith(prefix):
            self.close()
            raise ValueError(f"parser module does not resolve under {src}: {resolved or 'no probe'}")
        self.identity["module_file"] = probe["module_file"]

    def parse(self, blob, sha256, targets):
        """Parse one verified bulletin for [(station, target_date), ...]."""
        request = {"blob": str(blob), "sha256": sha256, "targets": [list(t) for t in targets]}
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("parser child exited")
        answer = json.loads(line)
        if "error" in answer:
            return answer["error"], []
        return None, answer["results"]

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
