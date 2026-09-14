"""Real pytest XML plus malformed, contradictory and entity-bearing artifacts."""

import hashlib

import pytest

from tests.operations.test_qualification_journal import observed
from weather.operations.qualification import journal, junit
from weather.operations.qualification.records import QualificationError


RESULTS = [{"nodeid": "tests/test_example.py::test_pass", "outcome": "pass"},
           {"nodeid": "tests/test_example.py::test_skip", "outcome": "skip"},
           {"nodeid": "tests/test_example.py::test_xfail", "outcome": "xfail"}]
XML = b'''<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="3" failures="0" errors="0" skipped="2" time="0.02">
<testcase classname="tests.test_example" name="test_pass" time="0.001"/>
<testcase classname="tests.test_example" name="test_skip" time="0.001"><skipped type="pytest.skip" message="native counterpart"/></testcase>
<testcase classname="tests.test_example" name="test_xfail" time="0.001"><skipped type="pytest.xfail" message="reviewed limitation"/></testcase>
</testsuite></testsuites>'''


def verify(tmp_path, raw):
    (tmp_path / "run.xml").write_bytes(raw)
    ref = {"path": "run.xml", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    return junit.verify(tmp_path, ref, RESULTS)


def test_counts_and_ordered_cases_corroborate_events(tmp_path):
    assert verify(tmp_path, XML) == {"tests": 3, "failures": 0, "errors": 0, "skipped": 2}


@pytest.mark.parametrize("old,new", [(b'tests="3"', b'tests="0"'), (b'failures="0"', b'failures="1"'),
                                    (b'name="test_pass"', b'name="another_test"'),
                                    (b'pytest.xfail', b'pytest.skip'),
                                    (b'classname="tests.test_example"', b'classname="tests.other"')])
def test_zero_collection_or_contradictory_junit_is_rejected(tmp_path, old, new):
    with pytest.raises(QualificationError):
        verify(tmp_path, XML.replace(old, new))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtd_is_rejected_in_any_xml_encoding(tmp_path, encoding):
    xml = XML.decode().replace('encoding="utf-8"', f'encoding="{encoding}"')
    xml = xml.replace('<testsuites>', '<!DOCTYPE testsuites [<!ENTITY secret SYSTEM "file:///unreadable">]><testsuites>')
    with pytest.raises(QualificationError, match="DTD/entity"):
        verify(tmp_path, xml.encode(encoding))


def test_actual_native_pytest_junit_agrees_with_its_event_journal(observed):
    root, candidate, journal_ref, _ = observed
    result = journal.consume(root, journal_ref, candidate_root=candidate, native_exit_code=0)
    raw = (root / "run.xml").read_bytes()
    ref = {"path": "run.xml", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert junit.verify(root, ref, result["results"])["tests"] == 3