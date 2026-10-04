"""The ``quarantine`` marker: the first, reversible stage of cutting a test.

``@pytest.mark.quarantine(reason="...", sunset="YYYY-MM-DD", replaced_by="...")``

* A quarantined test is still collected and still runs.
* If it fails (in setup or in the call), the failure is reported but is not fatal: the
  report becomes a non-strict xfail carrying the quarantine reason, a
  ``QuarantinedFailureWarning`` is emitted, the terminal report gains a
  "quarantined tests" section, and the JUnit test case carries a
  ``quarantine_failure`` property next to the ``quarantine`` property every
  quarantined test gets. A teardown error stays fatal.
* ``reason`` is required, ``sunset`` is a required ISO date (``YYYY-MM-DD``) no more
  than ``MAX_SUNSET_DAYS`` ahead, and ``replaced_by`` is optional. Once the sunset has
  passed, collection fails loudly (usage error) until the test is deleted with owner
  approval, restored, or given a newly reviewed sunset, so a quarantine can never
  become permanent silently.

`tests/conftest.py` registers these hooks; ``docs/development.md`` owns the staged-cut
procedure.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import pytest

MARKER = "quarantine"
MARKER_HELP = (
    "quarantine(reason, sunset, replaced_by=None): staged cut; the test still runs but a "
    "failure is reported as a non-fatal xfail; collection fails once the ISO-date sunset "
    "has passed (see docs/development.md)"
)
MAX_SUNSET_DAYS = 90
ALLOWED_KWARGS = frozenset({"reason", "sunset", "replaced_by"})
_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


class QuarantinedFailureWarning(pytest.PytestWarning):
    """A quarantined test failed; reported, but not fatal to the run."""


@dataclass(frozen=True)
class Quarantine:
    reason: str
    sunset: dt.date
    replaced_by: str | None

    def describe(self) -> str:
        text = f"reason={self.reason}; sunset={self.sunset.isoformat()}"
        if self.replaced_by:
            text += f"; replaced_by={self.replaced_by}"
        return text


_QUARANTINE_KEY = pytest.StashKey[Quarantine]()
_COLLECTED_KEY = pytest.StashKey[list]()
_FAILURES_KEY = pytest.StashKey[list]()


def today() -> dt.date:
    return dt.date.today()


def parse_marker(marker: pytest.Mark, *, on: dt.date) -> Quarantine:
    """Validate one quarantine marker; raise ``ValueError`` naming the defect."""
    if marker.args:
        raise ValueError("quarantine takes keyword arguments only (reason=, sunset=, replaced_by=)")
    unknown = sorted(set(marker.kwargs) - ALLOWED_KWARGS)
    if unknown:
        raise ValueError(f"unknown quarantine argument(s): {', '.join(unknown)}")
    reason = marker.kwargs.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("quarantine requires a non-empty reason=")
    sunset_text = marker.kwargs.get("sunset")
    if not isinstance(sunset_text, str) or not _ISO_DATE.match(sunset_text):
        raise ValueError(f"quarantine sunset= must be an ISO date string YYYY-MM-DD, got {sunset_text!r}")
    try:
        sunset = dt.date.fromisoformat(sunset_text)
    except ValueError:
        raise ValueError(f"quarantine sunset= is not a calendar date: {sunset_text!r}") from None
    if sunset > on + dt.timedelta(days=MAX_SUNSET_DAYS):
        raise ValueError(
            f"quarantine sunset {sunset_text} is more than {MAX_SUNSET_DAYS} days after {on.isoformat()}"
        )
    replaced_by = marker.kwargs.get("replaced_by")
    if replaced_by is not None and (not isinstance(replaced_by, str) or not replaced_by.strip()):
        raise ValueError("quarantine replaced_by= must be a non-empty string when given")
    return Quarantine(reason.strip(), sunset, replaced_by.strip() if replaced_by else None)


def pytest_configure(config: pytest.Config) -> None:
    registered = any(line.split(":", 1)[0].split("(", 1)[0].strip() == MARKER
                     for line in config.getini("markers"))
    if not registered:
        config.addinivalue_line("markers", MARKER_HELP)
    config.stash[_COLLECTED_KEY] = []
    config.stash[_FAILURES_KEY] = []


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list) -> None:
    # tryfirst: validate every collected item before -k/-m deselection, so an expired
    # quarantine cannot hide behind a narrower selection.
    on = today()
    problems = []
    for item in items:
        markers = list(item.iter_markers(MARKER))
        if not markers:
            continue
        if len(markers) > 1:
            problems.append(f"{item.nodeid}: more than one quarantine marker applies")
            continue
        try:
            quarantine = parse_marker(markers[0], on=on)
        except ValueError as exc:
            problems.append(f"{item.nodeid}: {exc}")
            continue
        if quarantine.sunset < on:
            problems.append(
                f"{item.nodeid}: quarantine sunset {quarantine.sunset.isoformat()} has passed "
                f"(today {on.isoformat()}); delete the test with owner approval, restore it, "
                "or set a newly reviewed sunset"
            )
            continue
        item.stash[_QUARANTINE_KEY] = quarantine
        item.user_properties.append(("quarantine", quarantine.describe()))
        config.stash[_COLLECTED_KEY].append(item.nodeid)
    if problems:
        raise pytest.UsageError(
            "invalid or expired quarantine marker(s):\n  " + "\n  ".join(problems)
        )


def _short_failure(report: pytest.TestReport) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    message = getattr(crash, "message", "") or ""
    if message.strip():
        return message.strip().splitlines()[0]
    text = report.longreprtext.strip().splitlines()
    for line in reversed(text):
        if line.startswith("E "):
            return line[1:].strip()
    return text[-1].strip() if text else "failed"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    quarantine = item.stash.get(_QUARANTINE_KEY, None)
    if quarantine is None or not report.failed or report.when not in ("setup", "call"):
        return report
    short = _short_failure(report)
    report.outcome = "skipped"
    report.wasxfail = f"quarantined: {quarantine.reason}"
    item.user_properties.append(("quarantine_failure", f"{report.when}: {short}"))
    item.config.stash[_FAILURES_KEY].append((item.nodeid, report.when, short, quarantine))
    try:
        item.warn(QuarantinedFailureWarning(
            f"quarantined test failed (not fatal) in {report.when}: {short} [{quarantine.describe()}]"
        ))
    except QuarantinedFailureWarning:
        pass  # a -W error filter must not turn reporting into an internal error
    return report


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    collected = config.stash.get(_COLLECTED_KEY, [])
    failures = config.stash.get(_FAILURES_KEY, [])
    if not collected and not failures:
        return
    terminalreporter.section("quarantined tests", sep="=", yellow=True)
    for nodeid, when, short, quarantine in failures:
        terminalreporter.line(
            f"QUARANTINED FAILURE (not fatal) {nodeid} [{when}] - {short} ({quarantine.describe()})",
            yellow=True,
        )
    terminalreporter.line(
        f"{len(collected)} quarantined test(s) collected; {len(failures)} failure(s) reported as xfailed"
    )

