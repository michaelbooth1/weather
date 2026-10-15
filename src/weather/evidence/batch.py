"""S5 light batch lane: one-shot evidence tasks (LB-1 labels, VR-5 trades) under the evidence host.

``config/evidence_host.json`` ``light_lane`` lists the tasks. Each task is a module under
``weather.evidence.tasks`` exposing ``run(ctx, days=None) -> dict``. It journals through the same
PL-1 writer, fetcher, telemetry and fetch-side embargo guard as a family child, under its own
journal family id (the task id).

- ``python -m weather.evidence.batch task --task <id> [--day YYYY-MM-DD ...]`` runs one task in this
  process (the command the lane starts; ``--day`` is a manual missing-range backfill, each day
  still guarded).
- The evidence host's light-lane thread (:class:`weather.evidence.host.LightLaneSupervisor`)
  starts every enabled task once per local day inside ``light_lane.run_local`` (00:30-01:00), one
  at a time, each in a kill-on-close Job with a hard commit cap (``ram_cap_mib`` <= 256) and a wall
  bound (``wall_seconds`` <= 600). The lane takes no workload lease (plan §5 schedule).
- ``python -m weather.evidence.batch run [--task <id>]`` runs the lane once now through the same
  containment (workstation and manual use; on the capture host the host thread is the trigger).

A task stops itself ``DEADLINE_MARGIN_SECONDS`` before its wall bound and journals a ``cap`` row.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.evidence.child import PollContext
from weather.evidence.code_identity import capture_identity
from weather.evidence.config import (
    DEFAULT_CONFIG_PATH, DEFAULT_LOCATIONS_PATH, MIB, evidence_root, load_config, load_locations,
)
from weather.evidence.embargo import EmbargoRefused
from weather.evidence.fetch import Fetcher, FetchError, RequestBudgetExceeded, urllib_transport
from weather.evidence.journal import NAME_RE, EvidenceJournal
from weather.evidence.telemetry import FamilyTelemetry

TASK_PACKAGE = "weather.evidence.tasks."
MAX_TASK_RAM_CAP_MIB = 256
MAX_TASK_WALL_SECONDS = 600
DEADLINE_MARGIN_SECONDS = 30.0
TASK_KEYS = ("plan_family", "module", "enabled", "ram_cap_mib", "wall_seconds", "hour_byte_budget_mib",
             "request_budget_per_hour")


class LightLaneConfigError(ValueError):
    pass


class TaskDeadline(RuntimeError):
    pass


def light_lane(config) -> dict:
    return config.get("light_lane") or {}


def task_configs(config) -> dict:
    """Validated ``light_lane.tasks`` in config order (cap and wall bound enforced here)."""
    tasks = light_lane(config).get("tasks") or {}
    for task_id, cfg in tasks.items():
        if not NAME_RE.match(task_id) or task_id in (config.get("families") or {}):
            raise LightLaneConfigError(f"{task_id}: invalid or clashes with a family id")
        for key in TASK_KEYS:
            if key not in cfg:
                raise LightLaneConfigError(f"{task_id}: missing {key}")
        if not str(cfg["module"]).startswith(TASK_PACKAGE):
            raise LightLaneConfigError(f"{task_id}: module must live under {TASK_PACKAGE}")
        if not 0 < int(cfg["ram_cap_mib"]) <= MAX_TASK_RAM_CAP_MIB:
            raise LightLaneConfigError(f"{task_id}: ram_cap_mib must be 1..{MAX_TASK_RAM_CAP_MIB}")
        if not 0 < int(cfg["wall_seconds"]) <= MAX_TASK_WALL_SECONDS:
            raise LightLaneConfigError(f"{task_id}: wall_seconds must be 1..{MAX_TASK_WALL_SECONDS}")
        if float(cfg["hour_byte_budget_mib"]) <= 0 or int(cfg["request_budget_per_hour"]) <= 0:
            raise LightLaneConfigError(f"{task_id}: budgets must be positive")
    return dict(tasks)


def max_task_cap_bytes(config) -> int:
    """Tasks run one at a time, so the lane adds at most its largest enabled cap."""
    caps = [int(c["ram_cap_mib"]) * MIB for c in task_configs(config).values() if c.get("enabled")]
    return max(caps, default=0)


@dataclass
class TaskContext(PollContext):
    deadline: float = 0.0
    monotonic: object = time.monotonic

    def check_deadline(self):
        if self.deadline and self.monotonic() >= self.deadline:
            raise TaskDeadline("wall bound reached")

    def fetch(self, url, **kwargs):
        self.check_deadline()
        return super().fetch(url, **kwargs)

    def guard_days(self, days, *, mode) -> bool:
        """Guard every UTC day a request touches; False (journalled) when any is refused."""
        for day in sorted({str(d) for d in days}):
            try:
                self.guard(day, mode=mode)
            except EmbargoRefused:
                return False
        return True


def utc_days(start: datetime, end: datetime) -> list[str]:
    day, last, out = start.astimezone(timezone.utc).date(), end.astimezone(timezone.utc).date(), []
    while day <= last:
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def load_task(cfg):
    module_name = str(cfg["module"])
    if not module_name.startswith(TASK_PACKAGE):
        raise ValueError(f"task module must live under {TASK_PACKAGE}")
    return importlib.import_module(module_name)


def run_task(task_id, *, config, config_sha256, root, repo_root, locations, config_path=None, days=None,
             transport=urllib_transport, clock=None, sleep=time.sleep, monotonic=time.monotonic) -> dict:
    tasks = task_configs(config)
    if task_id not in tasks:
        raise LightLaneConfigError(f"unknown light-lane task {task_id}")
    cfg = tasks[task_id]
    clock = clock or (lambda: datetime.now(timezone.utc))
    root = Path(root)
    host = config.get("host") or {}
    telemetry = FamilyTelemetry(root, task_id, clock=clock, monotonic=monotonic,
                                min_interval_seconds=float(host.get("status_interval_seconds", 30)))
    module = load_task(cfg)  # imported first so the code identity covers the task's own module
    config_paths = [p for p in (config_path, DEFAULT_LOCATIONS_PATH) if p]
    code_sha, _ = capture_identity(root, repo_root, config_paths)
    journal = EvidenceJournal(root, task_id, clock=clock, hour_byte_budget=int(float(cfg["hour_byte_budget_mib"]) * MIB),
                              config_sha256=config_sha256, code_manifest_sha=code_sha)
    journal.on_day_seal = lambda day, seal: telemetry.ledger(journal, day, seal)
    fetcher = Fetcher(user_agent=config["user_agent"], request_budget_per_hour=cfg["request_budget_per_hour"],
                      telemetry=telemetry, transport=transport)
    ctx = TaskContext(task_id, cfg, host, journal, fetcher, telemetry, locations, clock, sleep, channel=task_id,
                      deadline=monotonic() + max(1.0, float(cfg["wall_seconds"]) - DEADLINE_MARGIN_SECONDS),
                      monotonic=monotonic)
    summary, outcome = {}, "ok"
    with journal:
        journal.event("start", {"pid": os.getpid(), "code_manifest_sha": code_sha, "config_sha256": config_sha256,
                                "task": task_id, "days": list(days or [])}, channel=task_id)
        try:
            summary = module.run(ctx, days=[date.fromisoformat(str(d)) for d in days] if days else None) or {}
        except TaskDeadline:
            outcome = "wall_bound"
            journal.event("cap", {"reason": "wall_seconds", "limit_seconds": cfg["wall_seconds"]}, channel=ctx.channel)
        except RequestBudgetExceeded as exc:
            outcome = "request_budget"
            journal.event("cap", {"reason": "request_budget_per_hour", "detail": str(exc)}, channel=ctx.channel)
        except FetchError as exc:
            outcome = "fetch_error"
            journal.event("gap", {"reason": "fetch_error", "detail": str(exc)[:300]}, channel=ctx.channel)
        finally:
            journal.event("stop", {"reason": outcome, "summary": summary}, channel=task_id)
            telemetry.extra["stopped"] = outcome
            telemetry.write_status(journal, force=True)
    return {"task": task_id, "outcome": outcome, **summary}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DLv2 S5 light batch lane (LB-1, VR-5).")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--locations", default=str(DEFAULT_LOCATIONS_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("task", help="run one task in this process")
    one.add_argument("--task", required=True)
    one.add_argument("--day", action="append", default=None, help="target local day (repeatable); each is guarded")
    lane = sub.add_parser("run", help="run the lane once now, each task under its Job cap and wall bound")
    lane.add_argument("--task", action="append", default=None)
    args = parser.parse_args(argv)
    config, config_sha = load_config(args.config)
    root = evidence_root(config)
    from weather.paths import REPO_ROOT
    if args.command == "task":
        if args.task not in task_configs(config):
            parser.error(f"unknown task {args.task}")
        result = run_task(args.task, config=config, config_sha256=config_sha, root=root, repo_root=REPO_ROOT,
                          locations=load_locations(args.locations), config_path=args.config, days=args.day)
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    from weather.evidence.host import LightLaneSupervisor
    from weather.operations.long_job_guard import run_isolated_subprocess
    lane_runner = LightLaneSupervisor(config=config, config_path=args.config, root=root,
                                      runner=run_isolated_subprocess, cwd=str(REPO_ROOT))
    results = lane_runner.run_once(only=args.task)
    print(json.dumps(results, indent=1, sort_keys=True, default=str))
    return 0 if all(r.get("outcome") == "exit" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
