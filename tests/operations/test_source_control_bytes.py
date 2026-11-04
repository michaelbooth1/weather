"""No tracked text source carries an invisible control character.

Guards: vacuous-test defect found 2026-10-25 -- tests/calibration/test_mg2_p3d_n.py's "no production
importer" regex held literal backspace bytes where ``\\b`` was meant, so it could never match and the
test passed whatever the code did (master ruling 2026-10-25). Widened by master ruling 2026-10-30 after
the escape trap hit three times in one day: "C:\\t..." written as a TAB in ledger and register paths,
and TAB/FF/CR in a .ps1 comment that broke a launcher at parse time.

Scope: every tracked ``.ps1``, ``.psm1``, ``.md``, ``.json`` and ``.py`` file, read as git stores it (the
index blob, so ``core.autocrlf`` in a checkout cannot cause a false failure). CRLF is normalised to LF,
then any Unicode control character (category Cc: C0, DEL, C1) other than LF and HT fails. A lone CR,
or a CR not followed by LF, fails: ``"\\restart"`` expanded to CR + ``estart`` in a runbook path.
A file that legitimately needs a control character goes in ``ALLOWLIST`` with a one-line reason.

Relation to other checks: ``weather.operations.agent_docs_audit`` also refuses HT in docs/ Markdown and
in every AGENTS.md and README.md. That is stricter in its scope and is not contradicted here. HT stays
legal repo-wide because sources may use it. ``tests/hygiene_ratchet.py`` is not the home for this rule:
it counts AST patterns per test module against a count baseline, and this is a byte scan of the whole
repository with justified per-file exceptions.
"""

from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

import pytest

from weather.paths import REPO_ROOT

pytestmark = [pytest.mark.ratchet, pytest.mark.spawns]

SCANNED_SUFFIXES = (".ps1", ".psm1", ".md", ".json", ".py")
ALLOWED_CONTROLS = frozenset("\n\t")

#: Tracked path -> one-line justification. Entries for B-bound files or src/ capture modules carry
#: "fix after 12-14". An entry whose file no longer offends fails the test, so the list only shrinks.
ALLOWLIST: dict[str, str] = {}


def control_characters(data: bytes) -> list[tuple[int, int]]:
    """Return (1-based line, code point) for every forbidden control character (pure; unit-tested)."""
    text = data.replace(b"\r\n", b"\n").decode("utf-8", errors="replace")
    found, line = [], 1
    for char in text:
        if char == "\n":
            line += 1
        elif char not in ALLOWED_CONTROLS and unicodedata.category(char) == "Cc":
            found.append((line, ord(char)))
    return found


def tracked_sources(repo_root: Path) -> dict[str, bytes]:
    """Index blob content of every tracked file with a scanned suffix."""
    listing = subprocess.run(["git", "-C", str(repo_root), "ls-files", "-s", "-z"],
                             capture_output=True, check=True, timeout=120).stdout
    entries = []
    for record in filter(None, listing.split(b"\0")):
        meta, raw_path = record.split(b"\t", 1)
        mode, sha, stage = meta.split()
        path = raw_path.decode("utf-8")
        if stage == b"0" and mode != b"160000" and path.lower().endswith(SCANNED_SUFFIXES):
            entries.append((path, sha))
    batch = subprocess.run(["git", "-C", str(repo_root), "cat-file", "--batch"],
                           input=b"".join(sha + b"\n" for _path, sha in entries),
                           capture_output=True, check=True, timeout=300).stdout
    blobs, offset = {}, 0
    for path, _sha in entries:
        header_end = batch.index(b"\n", offset)
        size = int(batch[offset:header_end].split()[2])
        blobs[path] = batch[header_end + 1:header_end + 1 + size]
        offset = header_end + 1 + size + 1
    return blobs


def test_no_tracked_source_carries_a_control_character() -> None:
    sources = tracked_sources(REPO_ROOT)
    assert len(sources) > 1000, "the scan found almost no tracked sources"
    offenders = [f"{path}:{line}: U+{value:04X}"
                 for path, data in sorted(sources.items()) if path not in ALLOWLIST
                 for line, value in control_characters(data)]
    assert offenders == [], (
        "control characters in tracked sources (write the escape, e.g. r'\\b', '\\t' or '\\r', not the "
        "character; or add an ALLOWLIST entry with a reason):\n  " + "\n  ".join(offenders))


def test_allowlist_entries_are_tracked_still_offend_and_carry_a_reason() -> None:
    sources = tracked_sources(REPO_ROOT)
    for path, reason in ALLOWLIST.items():
        assert len(reason.strip()) >= 12, f"{path}: an allowlist entry needs a one-line justification"
        assert path in sources, f"{path}: allowlisted but not a tracked scanned source; remove it"
        assert control_characters(sources[path]), f"{path}: no longer offends; remove the entry"


@pytest.mark.parametrize("value", [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0x7F])
def test_every_forbidden_c0_and_del_is_reported(value: int) -> None:
    assert control_characters(b"x = 1\ny = '" + bytes([value]) + b"'\n") == [(2, value)]


@pytest.mark.parametrize("data, expected", [
    (b"-File scripts\\ops\restart_maker_evidence_capture.ps1\n", [(1, 0x0D)]),
    (b"ok\r\n\rtail\r", [(2, 0x0D), (2, 0x0D)]),
    (b"a\r\r\nb\n", [(1, 0x0D)]),
    ("c1 \u0085 next-line\n".encode("utf-8"), [(1, 0x85)]),
], ids=["lone-cr-from-backslash-r", "cr-without-lf", "cr-before-crlf", "c1-control"])
def test_lone_cr_and_c1_are_reported(data: bytes, expected: list[tuple[int, int]]) -> None:
    assert control_characters(data) == expected


@pytest.mark.parametrize("data", [
    b"a = 1\tb = 2\r\n",
    b"pattern = r'\\bimport\\b'\npath = 'C:\\\\t\\\\l2'\n",
    "s = 'caf\u00e9 \u2014 \u00b0F'\n".encode("utf-8"),
    b"\xef\xbb\xbf# bom\r\n",
], ids=["tab-crlf", "escaped-sequences", "utf8-text", "utf8-bom"])
def test_allowed_text_is_not_reported(data: bytes) -> None:
    assert control_characters(data) == []


def test_the_literal_backspace_regex_defect_is_caught() -> None:
    # The 2026-10-25 shape: re.compile("\bfrom weather\b") in a non-raw string stores 0x08 twice.
    source = 'PATTERN = re.compile("\bfrom weather\b")\n'.encode("utf-8")
    assert control_characters(source) == [(1, 0x08), (1, 0x08)]


def test_scan_reads_index_blobs_of_scanned_suffixes_only(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), "-c", "core.autocrlf=false", *args],
                       check=True, capture_output=True, timeout=60)

    git("init", "-q")
    files = {"a.ps1": b"# ok\r\n", "b.md": b"x\ry\n", "c.json": b"{}\n", "d.PY": b"\x0c\n",
             "e.psm1": b"\t\n", "f.csv": b"\x00\n", "g.txt": b"\x07\n"}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    git("add", "--", *files)
    (tmp_path / "b.md").write_bytes(b"clean in the checkout only\n")
    (tmp_path / "untracked.py").write_bytes(b"\x08\n")
    sources = tracked_sources(tmp_path)
    assert sorted(sources) == ["a.ps1", "b.md", "c.json", "d.PY", "e.psm1"]
    assert sources["b.md"] == b"x\ry\n"
    assert {path: control_characters(data) for path, data in sources.items() if control_characters(data)} \
        == {"b.md": [(1, 0x0D)], "d.PY": [(1, 0x0C)]}
