"""Literal native process and metadata transport for the archive controller."""
from __future__ import annotations
import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from weather.operations import production_cold_archive_stage as archive
from weather.operations import cold_archive_campaign_state as state
from weather.operations import bulk_cold_archive_crypt as bridge

MAX_OUTPUT = 3 * 1024**2


def write_bytes(path, raw):
    path = Path(path)
    archive._safe_path(path.parent, directory=True)
    if len(raw) > 2 * archive.MIB:
        raise ValueError("controller metadata bound")
    if path.exists():
        if archive._safe_path(path).read_bytes() != raw:
            raise ValueError("existing controller metadata differs")
    else:
        with path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def spec(path):
    path = archive._safe_path(Path(path))
    with path.open("rb") as source:
        raw = source.read(2 * archive.MIB + 1)
    if len(raw) > 2 * archive.MIB:
        raise ValueError("controller metadata exceeds bound")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def load_spec(value):
    return archive._load(value["path"], value["sha256"])[0]


class Transport:
    def __init__(self, config, source_root):
        self.config, self.source = config, Path(source_root)
        self.root = Path(config["production_root"])
        self.ws = config["workstation_root"].rstrip("/")
        self.ssh = str(Path(os.environ["WINDIR"]) / "System32" / "OpenSSH" / "ssh.exe")
        self.scp = str(Path(os.environ["WINDIR"]) / "System32" / "OpenSSH" / "scp.exe")
        self.ps = str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        self.options = [
            "-F", "none", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "PermitLocalCommand=no", "-o", "ProxyCommand=none", "-o", "ProxyJump=none",
            "-o", "ClearAllForwardings=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=10",
            "-i", config["private_key"], "-o", "UserKnownHostsFile=" + config["known_hosts"]]
        if spec(config["known_hosts"])["sha256"] != config["known_hosts_sha256"]:
            raise ValueError("pinned SSH trust changed")

    def run(self, arguments, seconds):
        process = subprocess.Popen(
            arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.source, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        output, errors, overflow = bytearray(), bytearray(), threading.Event()
        def drain(stream, target):
            while True:
                block = stream.read(4096)
                if not block:
                    return
                if len(target) + len(block) > MAX_OUTPUT:
                    overflow.set()
                    return
                target.extend(block)
        readers = [threading.Thread(target=drain, args=pair, daemon=True) for pair in (
            (process.stdout, output), (process.stderr, errors))]
        for reader in readers:
            reader.start()
        end = time.monotonic() + seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= end or overflow.is_set():
                    raise state.CampaignPaused("phase transport ended; retained claim needs reconciliation")
                try:
                    process.wait(timeout=.25)
                except subprocess.TimeoutExpired:
                    pass
            for reader in readers:
                reader.join(timeout=2)
            if overflow.is_set() or any(reader.is_alive() for reader in readers):
                raise state.CampaignPaused("phase output was not bounded")
            return process.returncode, output.decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def ssh_run(self, arguments, seconds):
        with ExitStack() as stack:
            for name in ("private_key", "known_hosts"):
                path = archive._safe_path(Path(self.config[name]))
                stack.enter_context(bridge._file_pin(path))
            if spec(self.config["known_hosts"])["sha256"] != self.config["known_hosts_sha256"]:
                raise ValueError("pinned SSH trust changed")
            return self.run(arguments, seconds)

    def rpc(self, mode, request, *, seconds=45):
        raw = archive._canonical(request)
        encoded = base64.b64encode(raw).decode("ascii")
        if len(encoded) > 24000:
            raise ValueError("RPC command exceeds Windows argument bound")
        command = [self.ssh, *self.options, "-T", "-n", "-o",
                   "HostName=" + self.config["remote_host"], "-l", self.config["remote_user"],
                   self.config["remote_host"], "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                   "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                   self.ws + "/scripts/ops/cold_archive_campaign_remote.ps1",
                   "-RepoRoot", self.ws, "-ExpectedSourceTip", self.config["workstation_source_tip"],
                   "-Mode", mode, "-RequestBase64", encoded]
        code, output = self.ssh_run(command, seconds)
        lines = [line[len("WEATHER_ARCHIVE_RPC "):] for line in output.splitlines()
                 if line.startswith("WEATHER_ARCHIVE_RPC ")]
        if len(lines) != 1:
            raise state.CampaignPaused("remote terminal receipt unavailable")
        result = json.loads(lines[0], object_pairs_hook=archive._pairs)
        if code or result["status"] != "PASS":
            raise state.CampaignPaused("remote phase failed; inspect retained receipts")
        return result

    def read_remote(self, relative, local, *, missing_ok=False):
        result = self.rpc("read", {"paths": [relative]})
        rows = result["files"]
        if len(rows) != 1 or rows[0]["path"] != relative:
            raise ValueError("remote metadata binding differs")
        row = rows[0]
        if not row["exists"]:
            if missing_ok:
                return None
            raise state.CampaignPaused("remote metadata is not yet terminal")
        raw = base64.b64decode(row["base64"], validate=True)
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("remote metadata hash differs")
        return {**write_bytes(local, raw), "remote_path": relative}

    def push_metadata(self, local, relative):
        local_spec = spec(local)
        # Use bounded file transport, avoiding credential-bearing shell text or
        # an overlong Windows command line for a large catalog entry.
        checked = self.rpc("read", {"paths": [relative]})["files"][0]
        if checked["exists"]:
            if checked["sha256"] != local_spec["sha256"]:
                raise ValueError("remote metadata namespace differs")
            return local_spec
        if not relative.startswith("scratch/ac-") or ".." in relative or not relative.endswith((".json", ".md")):
            raise ValueError("metadata copy escaped archive scratch")
        destination = self.config["remote_user"] + "@" + self.config["remote_host"] + ":" + self.ws + "/" + relative
        code, _ = self.ssh_run([self.scp, *self.options, "-l", "8192", str(local), destination], 45)
        if code:
            raise state.CampaignPaused("metadata copy needs reconciliation")
        after = self.rpc("read", {"paths": [relative]})["files"][0]
        if not after["exists"] or after["sha256"] != local_spec["sha256"]:
            raise ValueError("metadata copy readback differs")
        return local_spec
