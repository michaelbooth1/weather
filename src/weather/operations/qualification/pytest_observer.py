"""Trusted pytest observer, loaded by absolute reviewed path in an off-host child.

Every event is flushed before the test process proceeds. The outer runner owns
exit status, source/environment checks and final publication. This transcript
cannot authorize production and is never replaced with a JUnit-only verdict.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest


MAX_EVENTS = 200_000
MAX_BYTES = 128 * 1024**2
_handle = None
_sequence = 0
_bytes = 0


def _emit(event, **values):
    global _sequence, _bytes
    if _handle is None:
        raise RuntimeError("qualification journal was not opened")
    _sequence += 1
    raw = (json.dumps({"ordinal": _sequence, "event": event, "monotonic_ns": time.monotonic_ns(), **values},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    _bytes += len(raw)
    if _sequence > MAX_EVENTS or _bytes > MAX_BYTES:
        raise RuntimeError("qualification journal limit exceeded")
    _handle.write(raw)
    _handle.flush()


def pytest_configure(config):
    global _handle, _sequence, _bytes
    if _handle is not None:
        raise RuntimeError("observer cannot be reused in one process")
    path = Path(os.environ["WEATHER_QUALIFICATION_JOURNAL"])
    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError("absolute existing journal parent required")
    _handle = path.open("xb")
    _sequence, _bytes = 0, 0
    _emit("session_start", root=str(config.rootpath), invocation=[str(arg) for arg in config.invocation_params.args])


def pytest_collectreport(report):
    if not report.passed:
        reason = str(report.longrepr)
        if report.skipped and isinstance(report.longrepr, tuple):
            reason = str(report.longrepr[2])
        _emit("collection_problem", nodeid=report.nodeid, outcome=report.outcome, reason=reason[:8192])


def pytest_deselected(items):
    _emit("deselected", nodes=[item.nodeid for item in items])


@pytest.hookimpl(trylast=True)
def pytest_collection_finish(session):
    for item in session.items:
        _emit("collected_node", nodeid=item.nodeid)
    _emit("collection_finish", count=len(session.items))


def pytest_runtest_logstart(nodeid, location):
    _emit("test_start", nodeid=nodeid)


def pytest_runtest_logreport(report):
    reason = None
    wasxfail = hasattr(report, "wasxfail")
    if wasxfail:
        reason = str(report.wasxfail)
    elif report.skipped:
        reason = str(report.longrepr[2] if isinstance(report.longrepr, tuple) else report.longrepr)
        reason = reason.removeprefix("Skipped: ")
    elif report.failed:
        reason = str(report.longrepr)
    _emit("test_phase", nodeid=report.nodeid, when=report.when, outcome=report.outcome,
          wasxfail=wasxfail, reason=reason[:8192] if reason else None)


def pytest_runtest_logfinish(nodeid, location):
    _emit("test_finish", nodeid=nodeid)


def pytest_sessionfinish(session, exitstatus):
    _emit("session_finish", exit_code=int(exitstatus), tests_collected=int(session.testscollected),
          tests_failed=int(session.testsfailed))
    os.fsync(_handle.fileno())


def pytest_unconfigure(config):
    global _handle
    if _handle is not None:
        _handle.close()
        _handle = None
