"""Behaviour of the ``quarantine`` marker (tests/quarantine_plugin.py), run through pytester."""

from __future__ import annotations

import datetime as dt
import json
import xml.etree.ElementTree as ET

import pytest

from tests import quarantine_plugin

pytest_plugins = ["pytester"]

TODAY = dt.date.today()
ADDED = (TODAY - dt.timedelta(days=7)).isoformat()
FUTURE = (TODAY + dt.timedelta(days=14)).isoformat()


def iso(days: int) -> str:
    return (TODAY + dt.timedelta(days=days)).isoformat()


def registry(pytester: pytest.Pytester, entries: dict[str, dict]) -> None:
    path = pytester.path / "tests" / "quarantine_registry.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"format": 1, "entries": entries}), encoding="utf-8")


def run(pytester: pytest.Pytester, source: str, *args: str,
        entries: dict[str, dict] | None = None, mode: str | None = "fail"):
    pytester.makepyfile(test_subject=source)
    registry(pytester, entries if entries is not None else {
        "test_subject.py::test_q": {"first_added": ADDED, "renewals": []},
        "test_subject.py::TestQ::test_a": {"first_added": ADDED, "renewals": []},
        "test_subject.py::TestQ::test_b": {"first_added": ADDED, "renewals": []},
    })
    junit = pytester.path / "junit.xml"
    options = ["-p", "no:cacheprovider", f"--junitxml={junit}"]
    if mode:
        options.append(f"--quarantine-expired={mode}")
    result = pytester.runpytest(*options, *args, plugins=[quarantine_plugin])
    root = ET.parse(junit).getroot() if junit.exists() else None
    return result, root


def case(root: ET.Element, name: str) -> ET.Element:
    (element,) = [c for c in root.iter("testcase") if c.get("name") == name]
    return element


def properties(element: ET.Element) -> dict[str, str]:
    return {p.get("name"): p.get("value") for p in element.iter("property")}


def test_marker_is_registered_in_the_repository_pytest_config(request: pytest.FixtureRequest) -> None:
    names = [line.split(":", 1)[0].split("(", 1)[0].strip() for line in request.config.getini("markers")]
    assert names.count("quarantine") == 1


def test_passing_quarantined_test_passes_and_is_labelled_in_junit(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="overlaps test_y", added="{ADDED}", sunset="{FUTURE}", replaced_by="test_y")
def test_q():
    assert True
""")
    result.assert_outcomes(passed=1)
    assert result.ret == pytest.ExitCode.OK
    props = properties(case(root, "test_q"))
    assert props["quarantine"] == f"reason=overlaps test_y; added={ADDED}; sunset={FUTURE}; replaced_by=test_y"
    assert "quarantine_failure" not in props
    result.stdout.fnmatch_lines(["*quarantined tests*", "1 quarantined test(s) collected; 0 failure(s)*"])


def test_failing_quarantined_test_is_reported_but_not_fatal(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="brittle snapshot", added="{ADDED}", sunset="{FUTURE}")
def test_q():
    assert 1 == 2, "boom"

def test_ok():
    assert True
""")
    result.assert_outcomes(passed=1, xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines([
        "*QuarantinedFailureWarning: quarantined test failed (not fatal) in call: AssertionError: boom*",
        "*quarantined tests*",
        "QUARANTINED FAILURE (not fatal) test_subject.py::test_q [[]call[]] - AssertionError: boom*brittle snapshot*",
        "1 quarantined test(s) collected; 1 failure(s) reported as xfailed; 0 past sunset",
    ])
    element = case(root, "test_q")
    (skipped,) = element.iter("skipped")
    assert skipped.get("type") == "pytest.xfail"
    assert "quarantined: brittle snapshot" in skipped.get("message")
    props = properties(element)
    assert props["quarantine"] == f"reason=brittle snapshot; added={ADDED}; sunset={FUTURE}"
    assert props["quarantine_failure"].startswith("call: AssertionError: boom")


def test_setup_error_of_a_quarantined_test_is_not_fatal(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, f"""
import pytest

@pytest.fixture
def broken():
    raise RuntimeError("fixture down")

@pytest.mark.quarantine(reason="fixture debt", added="{ADDED}", sunset="{FUTURE}")
def test_q(broken):
    pass
""")
    result.assert_outcomes(xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.OK
    assert properties(case(root, "test_q"))["quarantine_failure"].startswith("setup: RuntimeError: fixture down")


def test_unquarantined_failures_stay_fatal(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{ADDED}", sunset="{FUTURE}")
def test_q():
    assert False

def test_real():
    assert False
""")
    result.assert_outcomes(failed=1, xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_class_level_marker_applies_to_each_method(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{ADDED}", sunset="{FUTURE}")
class TestQ:
    def test_a(self):
        assert False

    def test_b(self):
        assert True
""")
    result.assert_outcomes(passed=1, xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.OK


def test_parametrized_cases_share_one_registry_entry(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{ADDED}", sunset="{FUTURE}")
@pytest.mark.parametrize("n", [1, 2])
def test_q(n):
    assert n == 1
""")
    result.assert_outcomes(passed=1, xfailed=1, warnings=1)


def test_sunset_today_is_still_allowed(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{ADDED}", sunset="{TODAY.isoformat()}")
def test_q():
    pass
""")
    result.assert_outcomes(passed=1)


EXPIRED_SOURCE = f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{iso(-20)}", sunset="{iso(-1)}")
def test_q():
    assert False

def test_other():
    pass
"""
EXPIRED_ENTRIES = {"test_subject.py::test_q": {"first_added": iso(-20), "renewals": []}}


@pytest.mark.parametrize("extra", [(), ("--collect-only",), ("-k", "not test_q")])
def test_expired_sunset_fails_collection_in_fail_mode_whatever_the_selection(
    pytester: pytest.Pytester, extra: tuple[str, ...]
) -> None:
    result, _ = run(pytester, EXPIRED_SOURCE, *extra, entries=EXPIRED_ENTRIES, mode="fail")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([
        "ERROR: invalid or expired quarantine marker(s):",
        f"*test_subject.py::test_q: quarantine sunset {iso(-1)} has passed*",
    ])


def test_expired_sunset_is_reported_not_fatal_in_report_mode(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, EXPIRED_SOURCE, entries=EXPIRED_ENTRIES, mode="report")
    # The calendar alone changes nothing: the test stays quarantined and the run passes.
    result.assert_outcomes(passed=1, xfailed=1, warnings=2)
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines([
        "*QuarantineExpiredWarning*sunset*has passed*",
        f"EXPIRED QUARANTINE (enforced in CI) test_subject.py::test_q: quarantine sunset {iso(-1)} has passed*",
        "1 quarantined test(s) collected; 1 failure(s) reported as xfailed; 1 past sunset",
    ])
    assert properties(case(root, "test_q"))["quarantine_expired"] == iso(-1)


@pytest.mark.parametrize(("github_actions", "expected"), [("true", "fail"), ("", "report"), (None, "report")])
def test_expired_mode_defaults_to_fail_only_under_github_actions(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, github_actions: str | None, expected: str
) -> None:
    if github_actions is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    result, _ = run(pytester, EXPIRED_SOURCE, entries=EXPIRED_ENTRIES, mode=None)
    expected_ret = pytest.ExitCode.USAGE_ERROR if expected == "fail" else pytest.ExitCode.OK
    assert result.ret == expected_ret


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (f'"r", added="{ADDED}", sunset="{FUTURE}"', "keyword arguments only"),
        (f'added="{ADDED}", sunset="{FUTURE}"', "requires a non-empty reason"),
        (f'reason="  ", added="{ADDED}", sunset="{FUTURE}"', "requires a non-empty reason"),
        (f'reason="r", sunset="{FUTURE}"', "added= must be an ISO date"),
        (f'reason="r", added="{ADDED}"', "sunset= must be an ISO date"),
        (f'reason="r", added="{ADDED}", sunset="2026/10/04"', "sunset= must be an ISO date"),
        (f'reason="r", added="{ADDED}", sunset="20261004"', "sunset= must be an ISO date"),
        (f'reason="r", added="{ADDED}", sunset=__import__("datetime").date(2030, 1, 1)', "must be an ISO date"),
        (f'reason="r", added="{ADDED}", sunset="2026-02-30"', "not a calendar date"),
        (f'reason="r", added="{iso(1)}", sunset="{iso(10)}"', "is in the future"),
        (f'reason="r", added="{ADDED}", sunset="{iso(-8)}"', "is before added"),
        (f'reason="r", added="{ADDED}", sunset="{iso(-7 + 43)}"', "more than 6 weeks after added"),
        (f'reason="r", added="{ADDED}", sunset="{FUTURE}", replaced_by=""', "replaced_by= must be a non-empty string"),
        (f'reason="r", added="{ADDED}", sunset="{FUTURE}", owner="me"', "unknown quarantine argument(s): owner"),
    ],
)
def test_invalid_marker_fails_collection(pytester: pytest.Pytester, arguments: str, message: str) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine({arguments})
def test_q():
    pass
""", mode="report")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([f"*test_subject.py::test_q: *{message}*"])


@pytest.mark.parametrize(
    ("entries", "added", "sunset", "message"),
    [
        ({}, ADDED, FUTURE, "no entry for test_subject.py::test_q"),
        ({"test_subject.py::test_q": {"first_added": iso(-30), "renewals": []}}, ADDED, FUTURE,
         "does not match the latest registry date"),
        # A renewal is a registry edit: the marker's added= must be the newest renewal date.
        ({"test_subject.py::test_q": {"first_added": iso(-40), "renewals": [ADDED]}}, iso(-40), iso(-1),
         "does not match the latest registry date"),
        # However often it is renewed, no quarantine outlives TOTAL_WEEKS after first_added.
        ({"test_subject.py::test_q": {"first_added": iso(-80), "renewals": [iso(-40), ADDED]}}, ADDED, FUTURE,
         "more than 12 weeks after first_added"),
        ({"test_subject.py::test_q": {"first_added": ADDED, "renewals": [iso(-30)]}}, iso(-30), iso(5),
         "not in order"),
    ],
)
def test_registry_mismatch_fails_collection(
    pytester: pytest.Pytester, entries: dict, added: str, sunset: str, message: str
) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{added}", sunset="{sunset}")
def test_q():
    pass
""", entries=entries, mode="report")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([f"*{message}*"])


def test_one_recorded_renewal_is_accepted(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", added="{ADDED}", sunset="{FUTURE}")
def test_q():
    pass
""", entries={"test_subject.py::test_q": {"first_added": iso(-40), "renewals": [ADDED]}})
    result.assert_outcomes(passed=1)


def test_stacked_markers_are_rejected(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="a", added="{ADDED}", sunset="{FUTURE}")
class TestQ:
    @pytest.mark.quarantine(reason="b", added="{ADDED}", sunset="{FUTURE}")
    def test_a(self):
        pass
""")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*more than one quarantine marker*"])


def test_unmarked_suite_has_no_quarantine_report(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, """
def test_plain():
    pass
""")
    result.assert_outcomes(passed=1)
    assert "quarantined tests" not in result.stdout.str()
    assert properties(case(root, "test_plain")) == {}


def test_parse_marker_returns_normalised_fields() -> None:
    marker = pytest.mark.quarantine(reason=" r ", added=ADDED, sunset=FUTURE, replaced_by=" tests/x.py::test_y ").mark
    parsed = quarantine_plugin.parse_marker(marker, on=TODAY)
    assert parsed == quarantine_plugin.Quarantine(
        "r", dt.date.fromisoformat(ADDED), dt.date.fromisoformat(FUTURE), "tests/x.py::test_y"
    )
