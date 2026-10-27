"""The S0 to S1 check: the only permitted post-binding edit of ``b_scorer.py`` is the MG1_LOOK_ENTRY_SHA256 line.

Guards: B-1 clarification of 2026-10-26 section 4 (master's addition of 2026-10-27): "B binds b_scorer sha S0. The
only permitted post-binding scorer edit is setting MG1_LOOK_ENTRY_SHA256 by the dated MG-1 scoring
clarification, giving S1. B's look runs at S1, and the S0 to S1 diff must be exactly that constant line."
S0 here is the real ``b_scorer.py`` source; S1 variants are built from it in memory.
"""
import json
from pathlib import Path

import pytest

from weather.calibration import b_scorer_entry_edit as edit

ROOT = Path(__file__).resolve().parents[2]
S0 = (ROOT / "src/weather/calibration/b_scorer.py").read_bytes()
LINE = b"MG1_LOOK_ENTRY_SHA256 = MG1_LOOK_ENTRY_UNRECORDED\n"
SHA = "1" * 64


def _s1(value=f'"{SHA}"'.encode()):
    return S0.replace(LINE, b"MG1_LOOK_ENTRY_SHA256 = " + value + b"\n")


def test_s0_holds_the_constant_once_as_the_sentinel():
    assert S0.count(LINE) == 1
    assert sum(1 for line in S0.splitlines() if line.startswith(b"MG1_LOOK_ENTRY_SHA256")) == 1


def test_setting_the_constant_passes_and_returns_the_recorded_sha():
    assert edit.s1_problems(S0, _s1()) == ([], SHA)


@pytest.mark.parametrize("name,s1,fragment", [
    ("another line", _s1().replace(b'MG1_RECEIPT_TIME = "looked_at_utc"', b'MG1_RECEIPT_TIME = "completed_at_utc"'),
     "2 hunk(s)"),
    ("only another line", S0.replace(b'MG1_RECEIPT_TIME = "looked_at_utc"', b'MG1_RECEIPT_TIME = "x"'),
     "not the MG1_LOOK_ENTRY_SHA256 assignment"),
    ("two adjacent lines", _s1().replace(LINE.replace(b"MG1_LOOK_ENTRY_UNRECORDED", f'"{SHA}"'.encode()),
                                         LINE.replace(b"MG1_LOOK_ENTRY_UNRECORDED", f'"{SHA}"'.encode())
                                         + b"MG1_LOOK_EXTRA = 1\n"), "not the one MG1_LOOK_ENTRY_SHA256 line"),
    ("the constant removed", S0.replace(LINE, b""), "S1 has 0"),
    ("the constant duplicated", _s1() + b'MG1_LOOK_ENTRY_SHA256 = "' + SHA.encode() + b'"\n', "S1 has 2"),
    ("unchanged", S0, "identical"),
    ("not a sha literal", _s1(b"MG1_LOOK_ENTRY_UNRECORDED  # still"), "not a 64-hex string literal"),
    ("an uppercase sha", _s1(f'"{"A" * 64}"'.encode()), "not a 64-hex string literal"),
    ("a line ending", _s1().replace(b'"' + SHA.encode() + b'"\n', b'"' + SHA.encode() + b'"\r\n'),
     "line ending changed"),
    ("a trailing edit", _s1() + b"# a trailing comment\n", "2 hunk(s)"),
])
def test_any_other_change_fails(name, s1, fragment):
    problems, recorded = edit.s1_problems(S0, s1)
    assert recorded is None and problems, name
    assert any(fragment in p for p in problems), (name, problems)


def test_cli_reports_the_verdict_and_exits_nonzero_on_failure(tmp_path, capsys):
    s0, s1, bad = tmp_path / "s0.py", tmp_path / "s1.py", tmp_path / "bad.py"
    s0.write_bytes(S0)
    s1.write_bytes(_s1())
    bad.write_bytes(S0.replace(LINE, b""))
    assert edit.main(["--s0", str(s0), "--s1", str(s1)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pass"] is True and out["mg1_look_entry_sha256"] == SHA and out["s0_sha256"] != out["s1_sha256"]
    assert edit.main(["--s0", str(s0), "--s1", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["pass"] is False
