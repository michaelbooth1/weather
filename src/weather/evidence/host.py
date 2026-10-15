"""PL-6 evidence host: ``python -m weather.evidence.host run`` (the ``WeatherEvidenceHost`` task).

The parent only supervises. Each enabled family runs as one long-lived
``python -m weather.evidence.child --family <id>`` inside the Stage-A/snapshot containment
(:func:`weather.operations.long_job_guard.run_isolated_subprocess`): the child is created
suspended, assigned to a kill-on-close Job object with a **hard per-process commit limit**
(``ram_cap_mib``) and only then resumed, so allocation past the cap fails inside the child and the
Job dies with the parent. ``OPENBLAS_NUM_THREADS=1`` is set for every child.

Supervision rules:

- a child that ends with its cap exceeded leaves a **kill receipt** under ``kill_receipts/``; after
  ``max_cap_kills_per_day`` the family stays down until the next UTC day;
- a crash restarts with exponential backoff (5 s doubling to 300 s); a clean exit restarts at once;
- ``control/<family>.restart`` (``restart --family``) makes the child exit; the supervisor removes
  the file and relaunches it — new code is adopted **only** by such an explicit restart (owner Q11),
  and each child's status shows running-vs-disk code identity;
- ``control/host.stop`` (``stop``) stops every child within about a second and makes each respawn
  of the task exit at once (code 0, ``stop_reason`` in the status) until ``start`` removes it;
- the parent watches its own private bytes against ``parent_ram_cap_mib`` and stops everything if
  it ever exceeds it (the receipt is ``host_status.json``).

The S5 light lane (:class:`LightLaneSupervisor`) runs beside the families: once per host-local day
inside ``light_lane.run_local`` it starts each enabled task (``python -m weather.evidence.batch task``)
one at a time, each in the same containment with its own cap and ``wall_seconds`` timeout. A cap
kill writes a kill receipt for the task; ``host.stop`` stops the lane before its next task.

``kill-receipt`` runs the deliberate over-cap proof child the plan requires before S4 lands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from weather.evidence.batch import task_configs
from weather.evidence.config import (
    DEFAULT_CONFIG_PATH, MIB, declared_caps_bytes, evidence_root, load_config,
)
from weather.evidence.envelope import canonical, utc_text
from weather.evidence.journal import JournalBusy, WriterLock, atomic_bytes
from weather.schema_families import schema_version

HOST_STATUS_SCHEMA = schema_version("evidence_host_status")
KILL_RECEIPT_SCHEMA = schema_version("evidence_kill_receipt")
PARENT_RAM_CAP_BYTES = 64 * MIB
DEFAULT_CHILD_RAM_CAP_BYTES = 128 * MIB
DEFAULT_MAX_CAP_KILLS_PER_DAY = 3
BACKOFF_START_SECONDS, BACKOFF_MAX_SECONDS = 5.0, 300.0
CHILD_SAMPLE_INTERVAL_SECONDS = 5.0
PROOF_CAP_BYTES = 96 * MIB
PROOF_ALLOCATION = ("blocks = []\n"
                    "for _ in range(256):\n"
                    "    blocks.append(bytearray(8 * 1024 * 1024))\n"
                    "print('allocated', len(blocks))\n")


def _now():
    return datetime.now(timezone.utc)


def child_env(base=None) -> dict:
    env = dict(os.environ if base is None else base)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def family_cap_bytes(family_cfg) -> int:
    value = family_cfg.get("ram_cap_mib")
    return int(float(value) * MIB) if value else DEFAULT_CHILD_RAM_CAP_BYTES


def cap_exceeded(result) -> bool:
    return bool(result.get("resource_limit_exceeded")) or "MemoryError" in str(result.get("stderr") or "")


def write_kill_receipt(root, family, result, *, cap_bytes, deliberate=False, clock=_now) -> Path:
    stamp = clock()
    payload = {"schema_version": KILL_RECEIPT_SCHEMA, "family": family, "deliberate": bool(deliberate),
               "written_at_utc": utc_text(stamp), "cap_bytes": int(cap_bytes),
               "pid": result.get("pid"), "returncode": result.get("returncode"),
               "duration_seconds": result.get("duration_seconds"),
               "resource_limit_exceeded": result.get("resource_limit_exceeded"),
               "memory_error_in_stderr": "MemoryError" in str(result.get("stderr") or ""),
               "resource_peaks": result.get("resource_peaks"), "containment": result.get("containment"),
               "termination": result.get("termination"), "runner_error": result.get("runner_error"),
               "stderr_tail": str(result.get("stderr") or "")[-2000:]}
    path = Path(root) / "kill_receipts" / f"{stamp:%Y%m%dT%H%M%SZ}-{family}-{os.urandom(3).hex()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(path, json.dumps(payload, indent=1, sort_keys=True, default=str).encode("utf-8") + b"\n")
    return path


class FamilySupervisor:
    """Launch-and-handle loop for one family; :meth:`step` is one child lifetime."""

    def __init__(self, family, *, config, config_path, root, runner, python=sys.executable, clock=_now,
                 sleep=time.sleep, cwd=None):
        self.family, self.config, self.config_path = family, config, str(config_path)
        self.family_cfg = config["families"][family]
        self.host = config.get("host") or {}
        self.root, self.runner, self.python = Path(root), runner, python
        self.clock, self.sleep, self.cwd = clock, sleep, cwd
        self.cap_bytes = family_cap_bytes(self.family_cfg)
        self.max_kills = int(self.host.get("max_cap_kills_per_day", DEFAULT_MAX_CAP_KILLS_PER_DAY))
        self.state = {"family": self.family, "state": "idle", "starts": 0, "crashes": 0, "cap_kills_today": 0,
                      "cap_kill_day": None, "disabled_day": None, "backoff_seconds": 0.0, "pid": None,
                      "last_exit": None, "last_receipt": None, "cap_bytes": self.cap_bytes}

    def command(self) -> list[str]:
        return [self.python, "-m", "weather.evidence.child", "--family", self.family, "--config", self.config_path]

    def host_stopped(self) -> bool:
        return (self.root / "control" / "host.stop").exists()

    def _on_started(self, info):
        self.state.update(pid=(info or {}).get("pid"), state="running",
                          containment=(info or {}).get("containment"))

    def step(self) -> str:
        """Run the child once; return ``stopped``, ``disabled``, ``restart``, ``exit``, ``crash`` or ``cap_kill``."""
        day = self.clock().date().isoformat()
        if self.state["cap_kill_day"] != day:
            self.state.update(cap_kill_day=day, cap_kills_today=0)
        if self.host_stopped():
            self.state["state"] = "stopped"
            return "stopped"
        if self.state["disabled_day"] == day:
            self.state["state"] = "disabled_for_day"
            return "disabled"
        self.state["starts"] += 1
        self.state["state"] = "starting"
        result = self.runner(self.command(), timeout_seconds=None, private_memory_max_bytes=self.cap_bytes,
                             cwd=self.cwd, env=child_env(), on_started=self._on_started,
                             resource_sample_interval_seconds=CHILD_SAMPLE_INTERVAL_SECONDS)
        self.state.update(pid=None, last_exit={"returncode": result.get("returncode"),
                                               "duration_seconds": result.get("duration_seconds"),
                                               "at_utc": utc_text(self.clock())})
        restart_file = self.root / "control" / f"{self.family}.restart"
        if cap_exceeded(result):
            receipt = write_kill_receipt(self.root, self.family, result, cap_bytes=self.cap_bytes, clock=self.clock)
            self.state["last_receipt"] = str(receipt)
            self.state["cap_kills_today"] += 1
            if self.state["cap_kills_today"] >= self.max_kills:
                self.state["disabled_day"] = day
            self.state["state"] = "cap_killed"
            self._backoff()
            return "cap_kill"
        if restart_file.exists():
            restart_file.unlink(missing_ok=True)
            self.state.update(state="restarting", backoff_seconds=0.0)
            return "restart"
        if result.get("returncode") == 0:
            self.state.update(state="exited", backoff_seconds=0.0)
            return "exit"
        self.state["crashes"] += 1
        self.state["state"] = "crashed"
        self._backoff()
        return "crash"

    def _backoff(self):
        current = float(self.state["backoff_seconds"] or 0.0)
        self.state["backoff_seconds"] = min(BACKOFF_MAX_SECONDS, current * 2 if current else BACKOFF_START_SECONDS)

    def wait_backoff(self, stop_event):
        deadline = time.monotonic() + float(self.state["backoff_seconds"] or 0.0)
        while time.monotonic() < deadline and not stop_event.is_set() and not self.host_stopped():
            self.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    def loop(self, stop_event):
        while not stop_event.is_set():
            outcome = self.step()
            if outcome == "stopped":
                return
            if outcome == "disabled":
                stop_event.wait(60.0)
                continue
            self.wait_backoff(stop_event)


class LightLaneSupervisor:
    """Once per host-local day inside ``light_lane.run_local``: each enabled task, serially, contained."""

    def __init__(self, *, config, config_path, root, runner, python=sys.executable, clock=_now,
                 local_clock=None, sleep=time.sleep, cwd=None):
        from weather.evidence.child import in_window
        self.in_window = in_window
        self.config, self.config_path = config, str(config_path)
        self.tasks = {k: v for k, v in task_configs(config).items() if v.get("enabled")}
        self.windows = [tuple(w) for w in (config.get("light_lane") or {}).get("run_local", [])]
        self.root, self.runner, self.python = Path(root), runner, python
        self.clock, self.sleep, self.cwd = clock, sleep, cwd
        self.local_clock = local_clock or (lambda: datetime.now().astimezone())
        self.state = {"state": "idle", "ran_on": None, "runs": 0, "last": {}}

    def command(self, task) -> list[str]:
        return [self.python, "-m", "weather.evidence.batch", "--config", self.config_path, "task", "--task", task]

    def host_stopped(self) -> bool:
        return (self.root / "control" / "host.stop").exists()

    def due(self) -> bool:
        local = self.local_clock()
        return (bool(self.tasks) and self.state["ran_on"] != local.date().isoformat()
                and any(self.in_window(local, start, end) for start, end in self.windows))

    def run_once(self, only=None) -> list[dict]:
        results = []
        self.state["runs"] += 1
        for task, cfg in self.tasks.items():
            if only and task not in only:
                continue
            if self.host_stopped():
                results.append({"task": task, "outcome": "stopped"})
                break
            cap = int(cfg["ram_cap_mib"]) * MIB
            self.state.update(state="running", task=task)
            result = self.runner(self.command(task), timeout_seconds=float(cfg["wall_seconds"]),
                                 private_memory_max_bytes=cap, cwd=self.cwd, env=child_env(),
                                 resource_sample_interval_seconds=CHILD_SAMPLE_INTERVAL_SECONDS)
            row = {"task": task, "returncode": result.get("returncode"), "at_utc": utc_text(self.clock()),
                   "duration_seconds": result.get("duration_seconds"), "cap_bytes": cap,
                   "timed_out": bool(result.get("timed_out"))}
            if cap_exceeded(result):
                row["outcome"] = "cap_kill"
                row["receipt"] = str(write_kill_receipt(self.root, task, result, cap_bytes=cap, clock=self.clock))
            elif result.get("timed_out"):
                row["outcome"] = "wall_bound_kill"
            else:
                row["outcome"] = "exit" if result.get("returncode") == 0 else "crash"
            self.state["last"][task] = row
            results.append(row)
        self.state.update(state="idle", task=None)
        return results

    def loop(self, stop_event):
        while not stop_event.is_set() and not self.host_stopped():
            if self.due():
                self.state["ran_on"] = self.local_clock().date().isoformat()
                self.run_once()
            stop_event.wait(30.0)


class EvidenceHost:
    def __init__(self, *, config, config_sha256, config_path, root, runner=None, python=sys.executable,
                 clock=_now, sleep=time.sleep, memory_probe=None, cwd=None, local_clock=None):
        if runner is None:
            from weather.operations.long_job_guard import run_isolated_subprocess as runner
        self.config, self.config_sha256 = config, config_sha256
        self.root = Path(root)
        self.host = config.get("host") or {}
        self.clock, self.sleep = clock, sleep
        if memory_probe is None:
            from weather.evidence.telemetry import process_memory as memory_probe
        self.memory_probe = memory_probe
        self.parent_cap = int(float(self.host.get("parent_ram_cap_mib", 64)) * MIB)
        self.supervisors = [FamilySupervisor(name, config=config, config_path=config_path, root=root, runner=runner,
                                             python=python, clock=clock, sleep=sleep, cwd=cwd)
                            for name, cfg in sorted(config["families"].items()) if cfg.get("enabled")]
        self.light_lane = LightLaneSupervisor(config=config, config_path=config_path, root=root, runner=runner,
                                              python=python, clock=clock, local_clock=local_clock, sleep=sleep,
                                              cwd=cwd)
        self.stop_event = threading.Event()
        self.stop_reason = None

    def status_payload(self) -> dict:
        memory = self.memory_probe() or {}
        return {"schema_version": HOST_STATUS_SCHEMA, "written_at_utc": utc_text(self.clock()), "pid": os.getpid(),
                "config_sha256": self.config_sha256, "parent_memory": memory, "parent_cap_bytes": self.parent_cap,
                "declared_caps_bytes": declared_caps_bytes(self.config), "stop_reason": self.stop_reason,
                "host_stop_file": (self.root / "control" / "host.stop").exists(), "adoption": "explicit_restart",
                "families": {s.family: dict(s.state) for s in self.supervisors},
                "light_lane": dict(self.light_lane.state)}

    def write_status(self) -> dict:
        payload = self.status_payload()
        atomic_bytes(self.root / "host_status.json", canonical(payload) + b"\n")
        return payload

    def check_parent_cap(self, payload) -> bool:
        private = int((payload.get("parent_memory") or {}).get("private_bytes") or 0)
        if private > self.parent_cap:
            self.stop_reason = "parent_ram_cap_exceeded"
            control = self.root / "control"
            control.mkdir(parents=True, exist_ok=True)
            (control / "host.stop").write_text("parent_ram_cap_exceeded\n", encoding="utf-8")
            return True
        return False

    def run(self, *, max_seconds=None) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        lock = WriterLock(self.root / ".host.lock")
        try:
            lock.acquire()
        except JournalBusy:
            return 0  # another host owns the root (IgnoreNew double start)
        try:
            if (self.root / "control" / "host.stop").exists():
                self.stop_reason = "host_stop_file"
                self.write_status()
                return 0  # a deliberate stop is not a task failure
            threads = [threading.Thread(target=s.loop, args=(self.stop_event,), name=f"evidence-{s.family}",
                                        daemon=True) for s in self.supervisors]
            if self.light_lane.tasks:
                threads.append(threading.Thread(target=self.light_lane.loop, args=(self.stop_event,),
                                                name="evidence-light-lane", daemon=True))
            for thread in threads:
                thread.start()
            started = time.monotonic()
            interval = float(self.host.get("status_interval_seconds", 30))
            while any(t.is_alive() for t in threads):
                payload = self.write_status()
                if self.check_parent_cap(payload):
                    break
                if max_seconds is not None and time.monotonic() - started >= max_seconds:
                    self.stop_reason = "max_seconds"
                    break
                for _ in range(int(max(1, interval))):
                    if not any(t.is_alive() for t in threads):
                        break
                    self.sleep(1.0)
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=30)
            self.stop_reason = self.stop_reason or "children_stopped"
            self.write_status()
            return 0
        finally:
            lock.release()


def run_kill_receipt_proof(root, *, runner=None, python=sys.executable, cap_bytes=PROOF_CAP_BYTES) -> dict:
    """Start a child that allocates far past ``cap_bytes`` inside the containment; record the kill."""
    if runner is None:
        from weather.operations.long_job_guard import run_isolated_subprocess as runner
    result = runner([python, "-c", PROOF_ALLOCATION], timeout_seconds=120, private_memory_max_bytes=int(cap_bytes),
                    env=child_env(), resource_sample_interval_seconds=0.2)
    killed = cap_exceeded(result) and result.get("returncode") != 0 and "allocated" not in str(result.get("stdout"))
    receipt = write_kill_receipt(root, "proof_over_cap", result, cap_bytes=cap_bytes, deliberate=True)
    return {"killed": killed, "receipt": str(receipt), "returncode": result.get("returncode"),
            "containment": result.get("containment"), "resource_limit_exceeded": result.get("resource_limit_exceeded")}


def _control(root) -> Path:
    path = Path(root) / "control"
    path.mkdir(parents=True, exist_ok=True)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence host supervisor (DLv2 PL-6).")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="supervise every enabled family (the scheduled task action)")
    run.add_argument("--max-seconds", type=float, default=None)
    sub.add_parser("stop", help="write control/host.stop: children exit, respawns refuse")
    sub.add_parser("start", help="remove control/host.stop")
    restart = sub.add_parser("restart", help="explicit restart of one family (adopts new code)")
    restart.add_argument("--family", required=True)
    sub.add_parser("status", help="print host and family status (read-only)")
    proof = sub.add_parser("kill-receipt", help="deliberate over-cap child; writes a kill receipt")
    proof.add_argument("--cap-mib", type=float, default=PROOF_CAP_BYTES / MIB)
    args = parser.parse_args(argv)
    config, config_sha = load_config(args.config)
    root = evidence_root(config)
    if args.command == "run":
        from weather.paths import REPO_ROOT
        host = EvidenceHost(config=config, config_sha256=config_sha, config_path=args.config, root=root,
                            cwd=str(REPO_ROOT))
        return host.run(max_seconds=args.max_seconds)
    if args.command == "stop":
        (_control(root) / "host.stop").write_text("stop requested\n", encoding="utf-8")
        print(json.dumps({"stop_file": str(_control(root) / "host.stop")}))
        return 0
    if args.command == "start":
        (_control(root) / "host.stop").unlink(missing_ok=True)
        print(json.dumps({"stop_file_removed": True}))
        return 0
    if args.command == "restart":
        if args.family not in config["families"]:
            parser.error(f"unknown family {args.family}")
        (_control(root) / f"{args.family}.restart").write_text("restart requested\n", encoding="utf-8")
        print(json.dumps({"restart_requested": args.family}))
        return 0
    if args.command == "status":
        out = {"host": None, "families": {}}
        if (root / "host_status.json").exists():
            out["host"] = json.loads((root / "host_status.json").read_text(encoding="utf-8"))
        for family in sorted(config["families"]):
            path = root / family / "status.json"
            if path.exists():
                out["families"][family] = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(out, indent=1, sort_keys=True))
        return 0
    result = run_kill_receipt_proof(root, cap_bytes=int(args.cap_mib * MIB))
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0 if result["killed"] else 1


if __name__ == "__main__":
    sys.exit(main())
