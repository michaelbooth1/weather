"""The ``quarantine`` marker: the first, reversible stage of cutting a test.

``@pytest.mark.quarantine(reason="...", added="YYYY-MM-DD", sunset="YYYY-MM-DD", replaced_by="...")``

* A quarantined test is still collected and still runs.
* If it fails (in setup or in the call), the failure is reported but is not fatal: the
  report becomes a non-strict xfail carrying the quarantine reason, a
  ``QuarantinedFailureWarning`` is emitted, the terminal report gains a
  "quarantined tests" section, and the JUnit test case carries a
  ``quarantine_failure`` property next to the ``quarantine`` property every
  quarantined test gets. A teardown error stays fatal.
* ``reason``, ``added`` and ``sunset`` are required; ``replaced_by`` is optional. Dates
  are ISO ``YYYY-MM-DD``. ``added`` is not in the future and ``sunset`` is at most
  ``PERIOD_WEEKS`` weeks after it.
* Every quarantined test has an entry in ``tests/quarantine_registry.json``
  (``first_added`` plus a ``renewals`` list). ``added`` must equal the latest of those
  dates, and ``sunset`` is never more than ``TOTAL_WEEKS`` weeks after ``first_added``.
  A renewal is therefore a visible registry edit, and no quarantine outlives
  ``TOTAL_WEEKS`` weeks however often it is renewed.
* A passed sunset is enforced where it cannot cost an integration night: under GitHub
  Actions (``GITHUB_ACTIONS=true``) collection fails with a usage error naming the test.
  Anywhere else (workstation, capture-host bounded suite) the expiry is reported (a
  ``QuarantineExpiredWarning``, the terminal section and a ``quarantine_expired`` JUnit
  property) and the test stays quarantined, so a calendar date alone never changes a
  local outcome. ``--quarantine-expired=fail|report`` overrides the detection.
* Malformed markers and registry mismatches always fail collection: they are authoring
  errors that CI catches before merge.

`tests/conftest.py` registers these hooks (``tests/test_quarantine_registry.py`` proves
it); ``docs/development.md`` owns the staged-cut procedure. Under pytest-xdist the
terminal section only sees the controller's reports; JUnit properties stay per test.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

MARKER = "quarantine"
MARKER_HELP = (
    "quarantine(reason, added, sunset, replaced_by=None): staged cut; the test still runs but "
    "a failure is reported as a non-fatal xfail; needs an entry in tests/quarantine_registry.json "
    "(see docs/development.md)"
)
PERIOD_WEEKS = 6
TOTAL_WEEKS = 12
REQUIRED_KWARGS = frozenset({"reason", "added", "sunset"})
ALLOWED_KWARGS = REQUIRED_KWARGS | {"replaced_by"}
DEFAULT_REGISTRY = "tests/quarantine_registry.json"
_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


class QuarantinedFailureWarning(pytest.PytestWarning):
    """A quarantined test failed; reported, but not fatal to the run."""


class QuarantineExpiredWarning(pytest.PytestWarning):
    """A quarantine's sunset has passed; enforced in CI, reported elsewhere."""


@dataclass(frozen=True)
class Quarantine:
    reason: str
    added: dt.date
    sunset: dt.date
    replaced_by: str | None

    def describe(self) -> str:
        text = f"reason={self.reason}; added={self.added.isoformat()}; sunset={self.sunset.isoformat()}"
        if self.replaced_by:
            text += f"; replaced_by={self.replaced_by}"
        return text


_QUARANTINE_KEY = pytest.StashKey[Quarantine]()
_COLLECTED_KEY = pytest.StashKey[list]()
_FAILURES_KEY = pytest.StashKey[list]()
_EXPIRED_KEY = pytest.StashKey[list]()


def today() -> dt.date:
    return dt.date.today()


def _iso_date(value: object, field: str) -> dt.date:
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        raise ValueError(f"quarantine {field}= must be an ISO date string YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"quarantine {field}= is not a calendar date: {value!r}") from None


def parse_arguments(args: tuple, kwargs: dict, *, on: dt.date) -> Quarantine:
    """Validate one quarantine marker's arguments; raise ``ValueError`` naming the defect."""
    if args:
        raise ValueError("quarantine takes keyword arguments only (reason=, added=, sunset=, replaced_by=)")
    unknown = sorted(set(kwargs) - ALLOWED_KWARGS)
    if unknown:
        raise ValueError(f"unknown quarantine argument(s): {', '.join(unknown)}")
    reason = kwargs.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("quarantine requires a non-empty reason=")
    added = _iso_date(kwargs.get("added"), "added")
    sunset = _iso_date(kwargs.get("sunset"), "sunset")
    if added > on:
        raise ValueError(f"quarantine added={added.isoformat()} is in the future")
    if sunset < added:
        raise ValueError(f"quarantine sunset {sunset.isoformat()} is before added {added.isoformat()}")
    if sunset > added + dt.timedelta(weeks=PERIOD_WEEKS):
        raise ValueError(
            f"quarantine sunset {sunset.isoformat()} is more than {PERIOD_WEEKS} weeks after "
            f"added {added.isoformat()}"
        )
    replaced_by = kwargs.get("replaced_by")
    if replaced_by is not None and (not isinstance(replaced_by, str) or not replaced_by.strip()):
        raise ValueError("quarantine replaced_by= must be a non-empty string when given")
    return Quarantine(reason.strip(), added, sunset, replaced_by.strip() if replaced_by else None)


def parse_marker(marker: pytest.Mark, *, on: dt.date) -> Quarantine:
    return parse_arguments(marker.args, marker.kwargs, on=on)


def registry_key(nodeid: str) -> str:
    """Registry entries name the test function, not each parametrized case."""
    return nodeid.split("[", 1)[0]


def load_registry(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != 1 or not isinstance(payload.get("entries"), dict):
        raise ValueError(f"{path}: expected {{'format': 1, 'entries': {{...}}}}")
    return payload["entries"]


def check_registry(key: str, quarantine: Quarantine, entries: dict[str, dict]) -> None:
    """Raise ``ValueError`` unless the marker agrees with its registry entry."""
    entry = entries.get(key)
    if entry is None:
        raise ValueError(f"no entry for {key} in {DEFAULT_REGISTRY}; add first_added and renewals")
    first = _iso_date(entry.get("first_added"), "registry first_added")
    renewals = entry.get("renewals", [])
    if not isinstance(renewals, list):
        raise ValueError(f"{DEFAULT_REGISTRY}: renewals for {key} must be a list")
    dates = [first] + [_iso_date(value, "registry renewal") for value in renewals]
    if dates != sorted(dates):
        raise ValueError(f"{DEFAULT_REGISTRY}: dates for {key} are not in order")
    if quarantine.added != dates[-1]:
        raise ValueError(
            f"added={quarantine.added.isoformat()} does not match the latest registry date "
            f"{dates[-1].isoformat()} for {key}; a renewal is recorded in {DEFAULT_REGISTRY}"
        )
    if quarantine.sunset > first + dt.timedelta(weeks=TOTAL_WEEKS):
        raise ValueError(
            f"sunset {quarantine.sunset.isoformat()} is more than {TOTAL_WEEKS} weeks after "
            f"first_added {first.isoformat()}; the quarantine cannot be renewed again"
        )


def expired_mode(config: pytest.Config) -> str:
    option = config.getoption("quarantine_expired", default=None)
    if option:
        return option
    return "fail" if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" else "report"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--quarantine-expired", dest="quarantine_expired", choices=("fail", "report"), default=None,
        help="what a passed quarantine sunset does: fail collection (default under GitHub Actions) "
             "or report it and keep the test quarantined (default elsewhere)",
    )
    parser.addini("quarantine_registry", f"quarantine registry path (default {DEFAULT_REGISTRY})",
                  default=DEFAULT_REGISTRY)


def pytest_configure(config: pytest.Config) -> None:
    registered = any(line.split(":", 1)[0].split("(", 1)[0].strip() == MARKER
                     for line in config.getini("markers"))
    if not registered:
        config.addinivalue_line("markers", MARKER_HELP)
    config.stash[_COLLECTED_KEY] = []
    config.stash[_FAILURES_KEY] = []
    config.stash[_EXPIRED_KEY] = []


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list) -> None:
    # tryfirst: validate every collected item before -k/-m deselection, so an expired
    # quarantine cannot hide behind a narrower selection.
    on = today()
    mode = expired_mode(config)
    problems = []
    entries = None
    for item in items:
        markers = list(item.iter_markers(MARKER))
        if not markers:
            continue
        if len(markers) > 1:
            problems.append(f"{item.nodeid}: more than one quarantine marker applies")
            continue
        try:
            quarantine = parse_marker(markers[0], on=on)
            if entries is None:
                entries = load_registry(config.rootpath / config.getini("quarantine_registry"))
            check_registry(registry_key(item.nodeid), quarantine, entries)
        except ValueError as exc:
            problems.append(f"{item.nodeid}: {exc}")
            continue
        if quarantine.sunset < on:
            message = (
                f"{item.nodeid}: quarantine sunset {quarantine.sunset.isoformat()} has passed "
                f"(today {on.isoformat()}); delete the test with owner approval, restore it, "
                f"or renew it once in {DEFAULT_REGISTRY}"
            )
            if mode == "fail":
                problems.append(message)
                continue
            config.stash[_EXPIRED_KEY].append(message)
            item.user_properties.append(("quarantine_expired", quarantine.sunset.isoformat()))
            item.warn(QuarantineExpiredWarning(message))
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
    expired = config.stash.get(_EXPIRED_KEY, [])
    if not collected and not failures:
        return
    terminalreporter.section("quarantined tests", sep="=", yellow=True)
    for message in expired:
        terminalreporter.line(f"EXPIRED QUARANTINE (enforced in CI) {message}", red=True)
    for nodeid, when, short, quarantine in failures:
        terminalreporter.line(
            f"QUARANTINED FAILURE (not fatal) {nodeid} [{when}] - {short} ({quarantine.describe()})",
            yellow=True,
        )
    terminalreporter.line(
        f"{len(collected)} quarantined test(s) collected; {len(failures)} failure(s) reported as "
        f"xfailed; {len(expired)} past sunset"
    )
