"""One long-lived evidence family child: ``python -m weather.evidence.child --family <id>``.

The PL-6 supervisor starts each child inside a Windows Job object with a hard commit cap. The
child owns its family's journal writer lock, runs the family's channels on their intervals, and
exits cleanly when ``<root>/control/host.stop`` or ``<root>/control/<family>.restart`` appears.

Pause rules (plan PL-6 / §4c), checked before every poll and journalled as ``pause``/``resume``
rows on each transition:

- a channel's own ``quiet_local`` windows (FC-1 stays out of 12:00-18:00);
- optional channels pause inside the host's ``optional_pause_local`` windows (09:30-11:55, the
  Stage-A chain) and whenever available physical memory is below ``min_available_mib`` plus the
  declared caps of every enabled child and the parent;
- disk band (the 88a ``disk_band``): ``red`` pauses optional channels, ``critical`` pauses all.
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from weather.evidence.code_identity import capture_identity, disk_drift
from weather.evidence.config import (
    DEFAULT_CONFIG_PATH, DEFAULT_LOCATIONS_PATH, MIB, declared_caps_bytes, evidence_root, load_config,
    load_locations,
)
from weather.evidence.embargo import EmbargoRefused, embargo_guard
from weather.evidence.fetch import Fetcher, FetchError, RequestBudgetExceeded, urllib_transport
from weather.evidence.journal import EvidenceJournal
from weather.evidence.telemetry import FamilyTelemetry

FAMILY_PACKAGE = "weather.evidence.families."
IDENTITY_CHECK_SECONDS = 300.0


@dataclass
class Channel:
    name: str
    interval_seconds: float
    poll: Callable
    optional: bool = True
    quiet_local: tuple = ()
    run_local: tuple = ()


def _minutes(text) -> int:
    hour, minute = str(text).split(":")
    return int(hour) * 60 + int(minute)


def in_window(local_time, start, end) -> bool:
    now = local_time.hour * 60 + local_time.minute
    lo, hi = _minutes(start), _minutes(end)
    return lo <= now < hi if lo <= hi else (now >= lo or now < hi)


def pause_reason(channel, *, now_local, optional_windows, available_bytes, required_available_bytes,
                 disk_band_name) -> str | None:
    for start, end in channel.quiet_local:
        if in_window(now_local, start, end):
            return "channel_quiet_window"
    if disk_band_name == "critical":
        return "disk_critical"
    if not channel.optional:
        return None
    for start, end in optional_windows:
        if in_window(now_local, start, end):
            return "optional_pause_window"
    if available_bytes is not None and available_bytes < required_available_bytes:
        return "low_available_memory"
    if disk_band_name == "red":
        return "disk_red"
    return None


@dataclass
class PollContext:
    family: str
    cfg: dict
    host: dict
    journal: EvidenceJournal
    fetcher: Fetcher
    telemetry: FamilyTelemetry
    locations: list
    clock: Callable
    sleep: Callable
    channel: str = ""
    continuous: bool = False
    state: dict = field(default_factory=dict)

    def now(self) -> datetime:
        return self.clock()

    def fetch(self, url, **kwargs):
        return self.fetcher.get(url, **kwargs)

    def record(self, items, *, channel=None, meta=None):
        return self.journal.record_poll(channel or self.channel, items, meta=meta)

    def gap(self, reason, **detail):
        return self.journal.event("gap", {"reason": reason, **detail}, channel=self.channel)

    def warn(self, reason, **detail):
        return self.journal.event("warn", {"reason": reason, **detail}, channel=self.channel)

    def guard(self, event_date, *, mode):
        """The fetch-side embargo guard; a refusal is journalled and re-raised."""
        try:
            return embargo_guard(self.family, event_date, mode=mode, today=self.clock().date())
        except EmbargoRefused as exc:
            self.journal.event("guard", {"decision": "refused", "reason": exc.reason, **{
                k: v for k, v in exc.detail.items() if k in ("event_date", "mode", "scopes")}},
                channel=self.channel)
            raise


def load_family_channels(family_cfg, locations) -> list[Channel]:
    module_name = str(family_cfg["module"])
    if not module_name.startswith(FAMILY_PACKAGE):
        raise ValueError(f"family module must live under {FAMILY_PACKAGE}")
    module = importlib.import_module(module_name)
    return list(module.build(family_cfg, locations))


class ChildRunner:
    def __init__(self, family, *, config, config_sha256, root, repo_root, locations, config_path=None,
                 transport=urllib_transport, clock=None, local_clock=None, sleep=time.sleep,
                 available_memory=None, disk_free=None, monotonic=time.monotonic):
        self.family = family
        self.config, self.config_sha256 = config, config_sha256
        self.family_cfg = config["families"][family]
        self.host = config.get("host") or {}
        self.root, self.repo_root = Path(root), Path(repo_root)
        self.locations = locations
        self.config_path = config_path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.local_clock = local_clock or (lambda: datetime.now().astimezone())
        self.sleep, self.monotonic = sleep, monotonic
        if available_memory is None:
            from weather.operations.capture_resource_gate import available_memory_bytes as available_memory
        self.available_memory = available_memory
        self.disk_free = disk_free or (lambda: shutil.disk_usage(self.root).free)
        self.transport = transport
        self.paused: dict[str, str | None] = {}
        self.last_success: dict[str, float] = {}
        self.next_due: dict[str, float] = {}
        self.ran_on: dict[str, str] = {}
        self.states: dict[str, dict] = {}

    def control_stop(self) -> str | None:
        control = self.root / "control"
        if (control / "host.stop").exists():
            return "host_stop"
        if (control / f"{self.family}.restart").exists():
            return "restart_requested"
        return None

    def _disk_band(self):
        from weather.market.maker_evidence_store import disk_band
        try:
            return disk_band(self.disk_free())
        except OSError:
            return None

    def _run_channel(self, channel, ctx, now_mono):
        local = self.local_clock()
        required = int(self.host.get("min_available_mib", 0)) * MIB + declared_caps_bytes(self.config)
        reason = pause_reason(channel, now_local=local, optional_windows=self.host.get("optional_pause_local", []),
                              available_bytes=self.available_memory(), required_available_bytes=required,
                              disk_band_name=self._disk_band())
        if reason:
            if self.paused.get(channel.name) != reason:
                self.journal.event("pause", {"reason": reason}, channel=channel.name)
                self.paused[channel.name] = reason
                self.telemetry.channel(channel.name, paused=reason)
            return
        if self.paused.get(channel.name):
            self.journal.event("resume", {"after": self.paused[channel.name]}, channel=channel.name)
            self.paused[channel.name] = None
            self.telemetry.channel(channel.name, paused=None)
        if channel.run_local:
            today = local.date().isoformat()
            if self.ran_on.get(channel.name) == today or not any(
                    in_window(local, start, end) for start, end in channel.run_local):
                return
            self.ran_on[channel.name] = today
        previous = self.last_success.get(channel.name)
        ctx.channel = channel.name
        ctx.continuous = previous is not None and now_mono - previous <= 3 * channel.interval_seconds
        ctx.state = self.states.setdefault(channel.name, {})
        try:
            channel.poll(ctx)
            self.last_success[channel.name] = now_mono
            self.telemetry.channel(channel.name, last_success_utc=self.clock().isoformat())
        except RequestBudgetExceeded as exc:
            self.journal.event("cap", {"reason": "request_budget_per_hour", "detail": str(exc)}, channel=channel.name)
        except EmbargoRefused:
            pass  # journalled by ctx.guard
        except FetchError as exc:
            self.journal.event("gap", {"reason": "fetch_error", "detail": str(exc)[:300]}, channel=channel.name)
        except Exception as exc:  # noqa: BLE001 - a family bug must leave a gap row, not kill capture
            self.journal.event("gap", {"reason": "poll_exception",
                                       "detail": f"{type(exc).__name__}: {exc}"[:300]}, channel=channel.name)

    def _identity_status(self, manifest):
        drift = disk_drift(self.repo_root, manifest)
        self.telemetry.extra["code_identity"] = {
            "running_code_manifest_sha": self.journal.code_manifest_sha, "disk_matches_running": not drift,
            "drift_paths": drift[:20], "checked_at_utc": self.clock().isoformat(),
            "adoption": "explicit_restart"}

    def run(self, *, max_iterations=None) -> int:
        cfg = self.family_cfg
        self.telemetry = FamilyTelemetry(self.root, self.family, clock=self.clock,
                                         min_interval_seconds=float(self.host.get("status_interval_seconds", 30)),
                                         monotonic=self.monotonic)
        channels = load_family_channels(cfg, self.locations)
        config_paths = [p for p in (self.config_path, DEFAULT_LOCATIONS_PATH) if p]
        code_sha, manifest = capture_identity(self.root, self.repo_root, config_paths)
        self.journal = EvidenceJournal(self.root, self.family, clock=self.clock,
                                       hour_byte_budget=int(float(cfg["hour_byte_budget_mib"]) * MIB),
                                       config_sha256=self.config_sha256, code_manifest_sha=code_sha)
        self.journal.on_day_seal = lambda day, seal: self.telemetry.ledger(self.journal, day, seal)
        fetcher = Fetcher(user_agent=self.config["user_agent"], request_budget_per_hour=cfg["request_budget_per_hour"],
                          telemetry=self.telemetry, transport=self.transport)
        ctx = PollContext(self.family, cfg, self.host, self.journal, fetcher, self.telemetry, self.locations,
                          self.clock, self.sleep)
        stop_reason = "max_iterations"
        with self.journal:
            self.journal.event("start", {"pid": os.getpid(), "code_manifest_sha": code_sha,
                                         "config_sha256": self.config_sha256,
                                         "channels": [c.name for c in channels]})
            self._identity_status(manifest)
            last_identity = self.monotonic()
            iterations = 0
            try:
                while max_iterations is None or iterations < max_iterations:
                    iterations += 1
                    stop = self.control_stop()
                    if stop:
                        stop_reason = stop
                        break
                    self.journal.tick()
                    now_mono = self.monotonic()
                    for channel in channels:
                        if now_mono >= self.next_due.get(channel.name, 0.0):
                            self.next_due[channel.name] = now_mono + channel.interval_seconds
                            self._run_channel(channel, ctx, now_mono)
                    if now_mono - last_identity >= IDENTITY_CHECK_SECONDS:
                        self._identity_status(manifest)
                        last_identity = now_mono
                    self.telemetry.write_status(self.journal)
                    if max_iterations is None or iterations < max_iterations:
                        wait = min(self.next_due.values(), default=now_mono + 1.0) - self.monotonic()
                        self.sleep(max(0.2, min(1.0, wait)))
            finally:
                self.journal.event("stop", {"reason": stop_reason})
                self.telemetry.extra["stopped"] = stop_reason
                self.telemetry.write_status(self.journal, force=True)
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one evidence family child (normally started by the host).")
    parser.add_argument("--family", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--locations", default=str(DEFAULT_LOCATIONS_PATH))
    parser.add_argument("--max-iterations", type=int, default=None)
    args = parser.parse_args(argv)
    config, config_sha = load_config(args.config)
    if args.family not in config["families"]:
        parser.error(f"unknown family {args.family}")
    from weather.paths import REPO_ROOT
    runner = ChildRunner(args.family, config=config, config_sha256=config_sha, root=evidence_root(config),
                         repo_root=REPO_ROOT, locations=load_locations(args.locations), config_path=args.config)
    return runner.run(max_iterations=args.max_iterations)


if __name__ == "__main__":
    sys.exit(main())
