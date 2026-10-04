"""Behaviour of the ``quarantine`` marker (tests/quarantine_plugin.py)."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

import pytest

from tests import quarantine_plugin

pytest_plugins = ["pytester"]

TODAY = dt.date.today()
FUTURE = (TODAY + dt.timedelta(days=14)).isoformat()


def run(pytester: pytest.Pytester, source: str, *args: str) -> tuple[pytest.RunResult, ET.Element | None]:
    pytester.makepyfile(test_subject=source)
    junit = pytester.path / "junit.xml"
    result = pytester.runpytest(
        "-p", "no:cacheprovider", f"--junitxml={junit}", *args, plugins=[quarantine_plugin]
    )
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

@pytest.mark.quarantine(reason="overlaps test_y", sunset="{FUTURE}", replaced_by="test_y")
def test_q():
    assert True
""")
    result.assert_outcomes(passed=1)
    assert result.ret == pytest.ExitCode.OK
    props = properties(case(root, "test_q"))
    assert props["quarantine"] == f"reason=overlaps test_y; sunset={FUTURE}; replaced_by=test_y"
    assert "quarantine_failure" not in props
    result.stdout.fnmatch_lines(["*quarantined tests*", "1 quarantined test(s) collected; 0 failure(s)*"])


def test_failing_quarantined_test_is_reported_but_not_fatal(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="brittle snapshot", sunset="{FUTURE}")
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
        "1 quarantined test(s) collected; 1 failure(s) reported as xfailed",
    ])
    element = case(root, "test_q")
    (skipped,) = element.iter("skipped")
    assert skipped.get("type") == "pytest.xfail"
    assert "quarantined: brittle snapshot" in skipped.get("message")
    props = properties(element)
    assert props["quarantine"] == f"reason=brittle snapshot; sunset={FUTURE}"
    assert props["quarantine_failure"].startswith("call: AssertionError: boom")


def test_setup_error_of_a_quarantined_test_is_not_fatal(pytester: pytest.Pytester) -> None:
    result, root = run(pytester, f"""
import pytest

@pytest.fixture
def broken():
    raise RuntimeError("fixture down")

@pytest.mark.quarantine(reason="fixture debt", sunset="{FUTURE}")
def test_q(broken):
    pass
""")
    result.assert_outcomes(xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.OK
    assert properties(case(root, "test_q"))["quarantine_failure"].startswith("setup: RuntimeError: fixture down")


def test_unquarantined_failures_stay_fatal(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", sunset="{FUTURE}")
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

@pytest.mark.quarantine(reason="r", sunset="{FUTURE}")
class TestQ:
    def test_a(self):
        assert False

    def test_b(self):
        assert True
""")
    result.assert_outcomes(passed=1, xfailed=1, warnings=1)
    assert result.ret == pytest.ExitCode.OK


def test_sunset_today_is_still_allowed(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", sunset="{TODAY.isoformat()}")
def test_q():
    pass
""")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("extra", [(), ("--collect-only",), ("-k", "not test_q")])
def test_expired_sunset_fails_collection_loudly_whatever_the_selection(
    pytester: pytest.Pytester, extra: tuple[str, ...]
) -> None:
    expired = (TODAY - dt.timedelta(days=1)).isoformat()
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="r", sunset="{expired}")
def test_q():
    pass

def test_other():
    pass
""", *extra)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([
        "ERROR: invalid or expired quarantine marker(s):",
        f"*test_subject.py::test_q: quarantine sunset {expired} has passed*",
    ])


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (f'"r", sunset="{FUTURE}"', "keyword arguments only"),
        (f'sunset="{FUTURE}"', "requires a non-empty reason"),
        (f'reason="  ", sunset="{FUTURE}"', "requires a non-empty reason"),
        ('reason="r"', "must be an ISO date"),
        ('reason="r", sunset="2026/10/04"', "must be an ISO date"),
        ('reason="r", sunset="20261004"', "must be an ISO date"),
        ('reason="r", sunset=__import__("datetime").date(2030, 1, 1)', "must be an ISO date"),
        ('reason="r", sunset="2026-02-30"', "not a calendar date"),
        (f'reason="r", sunset="{(TODAY + dt.timedelta(days=91)).isoformat()}"', "more than 90 days"),
        (f'reason="r", sunset="{FUTURE}", replaced_by=""', "replaced_by= must be a non-empty string"),
        (f'reason="r", sunset="{FUTURE}", owner="me"', "unknown quarantine argument(s): owner"),
    ],
)
def test_invalid_marker_fails_collection(pytester: pytest.Pytester, arguments: str, message: str) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine({arguments})
def test_q():
    pass
""")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines([f"*test_subject.py::test_q: *{message}*"])


def test_stacked_markers_are_rejected(pytester: pytest.Pytester) -> None:
    result, _ = run(pytester, f"""
import pytest

@pytest.mark.quarantine(reason="a", sunset="{FUTURE}")
class TestQ:
    @pytest.mark.quarantine(reason="b", sunset="{FUTURE}")
    def test_q(self):
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
    marker = pytest.mark.quarantine(reason=" r ", sunset=FUTURE, replaced_by=" tests/x.py::test_y ").mark
    parsed = quarantine_plugin.parse_marker(marker, on=TODAY)
    assert parsed == quarantine_plugin.Quarantine("r", dt.date.fromisoformat(FUTURE), "tests/x.py::test_y")
