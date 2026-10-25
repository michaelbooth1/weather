"""Pre-registration checker refuses a rule file missing any checklist section.

Guards: lane L7 brief (2026-10-24) and docs/operations/PREREGISTRATION_CHECKLIST.md - a rule needs (a)
the positive control with expected values, (b) a comparator fairness statement (same floor and
calibration; the unfair raw-R0 lesson), (c) the targeted loss slice and size from the atlas, (d) MDE
and cluster count, (e) the dev-window reuse count from the ledger.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from weather.reporting.scorecards import prereg_check as pc

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "docs" / "operations" / "PREREGISTRATION_CHECKLIST.md"

GOOD = """# Rule r-x

## (a) Positive control
Served vs market pooled R 1.774 (all) and 1.526 (00-16), reproduced by the loss atlas first.

## (b) Comparator fairness
The comparator gets the same rule-4 floor and the same calibration as the candidate.

## (c) Targeted loss slice
Loss atlas `0123456789abcdef`: the 07-12 centre slice, 76.5% of 0.0258.

## (d) MDE and clusters
MDE80 0.0060 at 11 market clusters and 43 date clusters.

## (e) Dev-window reuse
DEV_WINDOW_LEDGER.md lists 14 scored candidates before this one; this is number 15.
"""


def test_complete_rule_passes(tmp_path):
    path = tmp_path / "rule.md"
    path.write_text(GOOD, encoding="utf-8")
    assert pc.main([str(path)]) == 0


@pytest.mark.parametrize("letter,heading", [("a", "## (a) Positive control"), ("b", "## (b) Comparator fairness"),
                                            ("c", "## (c) Targeted loss slice"), ("d", "## (d) MDE and clusters"),
                                            ("e", "## (e) Dev-window reuse")])
def test_each_missing_section_is_refused(tmp_path, capsys, letter, heading):
    path = tmp_path / "rule.md"
    path.write_text(GOOD.replace(heading, "## Notes"), encoding="utf-8")
    assert pc.main([str(path)]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "REFUSED"
    assert any(p.startswith(f"({letter})") and "missing" in p for p in out["problems"])


@pytest.mark.parametrize("old,new,needle", [
    ("1.774 (all) and 1.526 (00-16)", "the served control", "expected values"),
    ("same calibration", "same scoring", "calibration"),
    ("same rule-4 floor and the", "same", "floor"),
    ("`0123456789abcdef`", "(not yet run)", "sha256"),
    ("at 11 market clusters and 43 date clusters", "", "cluster count"),
    ("DEV_WINDOW_LEDGER.md", "the ledger", "DEV_WINDOW_LEDGER"),
    ("76.5% of 0.0258.", "76.5% of 0.0258. TBD", "placeholder"),
])
def test_sections_without_their_content_are_refused(tmp_path, old, new, needle):
    path = tmp_path / "rule.md"
    assert old in GOOD
    path.write_text(GOOD.replace(old, new), encoding="utf-8")
    result = pc.check_file(path)
    assert result["verdict"] == "REFUSED"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_headings_inside_code_fences_do_not_count(tmp_path):
    path = tmp_path / "rule.md"
    path.write_text("# r\n```\n" + GOOD + "```\n", encoding="utf-8")
    assert pc.check_file(path)["verdict"] == "REFUSED"


def test_unreadable_file_is_refused(tmp_path):
    assert pc.main([str(tmp_path / "missing.md")]) == 2


def test_checklist_template_passes_the_checker(tmp_path):
    text = CHECKLIST.read_text(encoding="utf-8")
    block = re.search(r"<!-- template:start -->\s*```markdown\n(.*?)```\s*<!-- template:end -->", text, re.S)
    assert block is not None
    path = tmp_path / "template.md"
    path.write_text(block.group(1), encoding="utf-8")
    assert pc.check_file(path)["verdict"] == "PASS"
    assert "unfair" in text.lower() and "raw R0" in text
