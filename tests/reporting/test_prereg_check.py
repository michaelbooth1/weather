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
DEV_WINDOW_LEDGER.md
- reuse count: 14
This candidate would bring it to 15, on dates 2026-08-01..2026-09-29.
"""

LEDGER = """# Dev-window reuse ledger
Historical count: 999. There are 134 pre-ledger rules and explicit exceptions.
## Rows
| # | Type | Candidate |
| 1 | K | candidate |
| 2 | D | descriptive read |
## Dev reuse count
**Dev reuse count (2026-11-06): 14.** Includes pre-ledger rules and exceptions.
"""


@pytest.fixture(autouse=True)
def canonical_ledger(tmp_path, monkeypatch):
    """All checker tests use synthetic ledger state, never the evolving checkout count."""
    path = tmp_path / "DEV_WINDOW_LEDGER.md"
    path.write_text(LEDGER, encoding="utf-8")
    monkeypatch.setattr(pc, "docs_path", lambda *parts: path)
    return path


@pytest.mark.parametrize("count", ["0", "13", "15", "214"])
def test_stale_or_self_incremented_reuse_count_is_refused(tmp_path, capsys, count):
    path = tmp_path / "rule.md"
    path.write_text(GOOD.replace("reuse count: 14", f"reuse count: {count}"), encoding="utf-8")
    assert pc.main([str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert any("DEV_REUSE_COUNT_MISMATCH" in p and f"cited {count}, ledger 14" in p
               for p in result["problems"])


@pytest.mark.parametrize("citation", [
    "2026-08-01..2026-09-29; candidate number 14.",
    "reuse count: 14.5", "reuse count: -14", "reuse count: 014", "reuse count: 1e4",
    "reuse count: 14\nreuse count: 14", "reuse count: 14\nreuse count: 15",
    "reuse count: 14\nreuse count: invalid",
    "DEV_WINDOW_LEDGER.md lists 14 scored candidates; this is number 15.",
])
def test_unlabelled_or_ambiguous_reuse_count_is_refused(citation):
    text = GOOD.replace("- reuse count: 14", citation)
    assert any("DEV_REUSE_COUNT_INVALID" in p for p in pc.check_text(text))


def test_lower_bound_count_and_incidental_dates_pass():
    assert pc.check_text(GOOD.replace("reuse count: 14", "reuse count: at least 14")) == []


def test_reuse_is_derived_from_summary_not_table_rows_or_historical_numbers():
    assert pc.ledger_reuse_count(LEDGER) == 14
    assert pc.check_text(GOOD, ledger_text=LEDGER) == []
    changed = LEDGER.replace("2026-11-06): 14.", "2026-11-06): 16.")
    assert any("cited 14, ledger 16" in p for p in pc.check_text(GOOD, ledger_text=changed))


@pytest.mark.parametrize("ledger", [
    "", LEDGER.replace("## Dev reuse count", "## Historical count"),
    LEDGER + "\n## Dev reuse count\n**Dev reuse count: 14.**",
    LEDGER + "\n**Dev reuse count: 14.**", LEDGER.replace(": 14.**", ": 14.5.**"),
    LEDGER + "\n**Dev reuse count: invalid.**",
])
def test_missing_or_ambiguous_ledger_summary_fails_closed(ledger):
    assert any("DEV_REUSE_LEDGER_INVALID" in p for p in pc.check_text(GOOD, ledger_text=ledger))


def test_missing_or_non_utf8_ledger_fails_closed(canonical_ledger):
    canonical_ledger.unlink()
    assert any("DEV_REUSE_LEDGER_UNREADABLE" in p for p in pc.check_text(GOOD))
    canonical_ledger.write_bytes(b"\xff")
    assert any("DEV_REUSE_LEDGER_UNREADABLE" in p for p in pc.check_text(GOOD))


def current_template(text):
    """The template's example count/ordinal must be replaced before a rule can pass."""
    return text.replace("DEV_WINDOW_LEDGER.md: this is candidate number 20 on 2026-07-31..09-29.",
                        "DEV_WINDOW_LEDGER.md\n- reuse count: 14")


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


def test_checklist_template_requires_current_ledger_count(tmp_path):
    text = CHECKLIST.read_text(encoding="utf-8")
    block = re.search(r"<!-- template:start -->\s*```markdown\n(.*?)```\s*<!-- template:end -->", text, re.S)
    assert block is not None
    path = tmp_path / "template.md"
    path.write_text(block.group(1), encoding="utf-8")
    assert any("DEV_REUSE_COUNT_INVALID" in p for p in pc.check_file(path)["problems"])
    path.write_text(current_template(block.group(1)), encoding="utf-8")
    assert pc.check_file(path)["verdict"] == "PASS"
    assert "unfair" in text.lower() and "raw R0" in text


# ----------------------------------------------------------------------------- forward: (f) power gate, (g) futility
# Guards: MODEL_IMPROVEMENT_METHOD section 5 rules 6-7 (owner 2026-10-30) and DEV_WINDOW_LEDGER rows 73 and 82:
# VIF floor (1 + rho) / (1 - rho) (a block-3 VIF left Rule B a 5.1% false PASS at rho 0.42), N >= 20, power >= 0.5,
# no pooled sigma, POWERED/SCREEN consistent with delta vs MDE80, Rule B looks exactly.

FORWARD = GOOD + """
## (f) Power gate
- sigma_d: 0.0110 (dev, MG-1 - served 00-16, 2026-08-15..09-29, sha256 b1a504bcf9e5)
- rho: +0.42
- block3 ratio: 1.32
- VIF: 2.45
- delta: 0.0060
- N: 45
- MDE80: 0.0076
- power: 0.64
- class: SCREEN
- N80: 65
- intervals: date-clustered and block-3

## (g) Futility
- look 7: HARM if t > 3.143
- look 14: FUTILE if z > +0.5
- look 21: FUTILE if z > 0
- look 31: FUTILE if z > -0.5
- final N: 45
- interim PASS: never
"""


def _forward(tmp_path, text):
    path = tmp_path / "rule.md"
    path.write_text(text, encoding="utf-8")
    return pc.check_file(path, forward=True)


def test_forward_rule_passes(tmp_path):
    path = tmp_path / "rule.md"
    path.write_text(FORWARD, encoding="utf-8")
    assert pc.main(["--forward", str(path)]) == 0


def test_default_mode_does_not_require_forward_sections(tmp_path):
    path = tmp_path / "rule.md"
    path.write_text(GOOD, encoding="utf-8")
    assert pc.check_file(path)["verdict"] == "PASS"
    result = pc.check_file(path, forward=True)
    assert result["verdict"] == "REFUSED"
    assert {p[:3] for p in result["problems"]} == {"(f)", "(g)"}
    assert all("missing" in p for p in result["problems"])


@pytest.mark.parametrize("old,new,needle", [
    ("- VIF: 2.45", "- VIF: 1.74", "serial-dependence floor"),
    ("- rho: +0.42", "- rho: +0.10", None),                      # floor 1.74 from block3 ratio: 2.45 still fine
    ("- block3 ratio: 1.32", "- block3 ratio: 1.70", "serial-dependence floor"),
    ("(dev, MG-1", "(dev and history pooled, MG-1", "exactly one source block"),
    ("(dev, MG-1", "(MG-1", "exactly one source block"),
    ("sha256 b1a504bcf9e5", "no sha", "sha256"),
    ("- N: 45", "- N: 14", "at least 20"),
    ("- MDE80: 0.0076", "- MDE80: 0.0060", "MDE80 0.006 is below"),
    ("- power: 0.64", "- power: 0.45", "below 0.5"),
    ("- power: 0.64", "- power: 0.90", "overstates"),
    ("- class: SCREEN", "- class: POWERED", "contradicts"),
    ("- N80: 65\n", "", "must state N80"),
    ("- intervals: date-clustered and block-3", "- intervals: date-clustered", "block-3 interval"),
    ("- delta: 0.0060\n", "", "does not state delta"),
    ("- look 14: FUTILE if z > +0.5", "- look 14: FUTILE if z > 0", "look 14 must read"),
    ("- look 7: HARM if t > 3.143", "- look 7: HARM if z > 2.326", "look 7 must read"),
    ("- look 31: FUTILE if z > -0.5\n", "", "look 31 missing"),
    ("- final N: 45", "- final N: 44", "differs from the power gate"),
    ("- interim PASS: never", "- interim PASS: at look 31 if z < -3", "interim PASS: never"),
    ("- final N: 45", "- look 10: FUTILE if z > 0\n- final N: 45", "not Rule B looks"),
    ("- class: SCREEN", "- class: SCREEN TBD", "placeholder"),
])
def test_forward_sections_without_their_content_are_refused(tmp_path, old, new, needle):
    assert old in FORWARD
    result = _forward(tmp_path, FORWARD.replace(old, new))
    if needle is None:
        assert result["verdict"] == "PASS", result["problems"]
        return
    assert result["verdict"] == "REFUSED"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_powered_class_needs_delta_at_or_above_mde(tmp_path):
    text = (FORWARD.replace("- delta: 0.0060", "- delta: 0.0080").replace("- class: SCREEN", "- class: POWERED")
            .replace("- power: 0.64", "- power: 0.84").replace("- N80: 65\n", ""))
    assert _forward(tmp_path, text)["verdict"] == "PASS"


def test_looks_at_or_after_final_n_are_dropped(tmp_path):
    short = (FORWARD.replace("- N: 45", "- N: 30").replace("- final N: 45", "- final N: 30")
             .replace("- MDE80: 0.0076", "- MDE80: 0.0093").replace("- power: 0.64", "- power: 0.47"))
    result = _forward(tmp_path, short)
    assert any("look 31 is not before final N" in p for p in result["problems"])
    assert any("below 0.5" in p for p in result["problems"])
    fixed = short.replace("- look 31: FUTILE if z > -0.5\n", "")
    assert not any(p.startswith("(g)") for p in _forward(tmp_path, fixed)["problems"])


def test_checklist_forward_template_passes_with_forward(tmp_path):
    text = CHECKLIST.read_text(encoding="utf-8")
    base = re.search(r"<!-- template:start -->\s*```markdown\n(.*?)```\s*<!-- template:end -->", text, re.S)
    fwd = re.search(r"<!-- forward-template:start -->\s*```markdown\n(.*?)```\s*<!-- forward-template:end -->",
                    text, re.S)
    assert base is not None and fwd is not None
    result = _forward(tmp_path, current_template(base.group(1)) + "\n" + fwd.group(1))
    assert result["verdict"] == "PASS", result["problems"]
    assert "Rule B" in text and "(1+ρ)/(1−ρ)" in text
