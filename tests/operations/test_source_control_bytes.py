"""No Python source under src/ or tests/ carries an invisible control byte.

Guards: vacuous-test defect found 2026-10-25 -- tests/calibration/test_mg2_p3d_n.py's "no production
importer" regex held literal backspace bytes where ``\\b`` was meant, so it could never match and the
test passed whatever the code did (master ruling 2026-10-25: refuse C0 control bytes except tab, LF
and CR in src/**/*.py and tests/**/*.py; binary fixtures are not .py and stay out of scope).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from weather.paths import REPO_ROOT

pytestmark = pytest.mark.ratchet

SCANNED_ROOTS = ("src", "tests")
# C0 controls other than tab (0x09), LF (0x0a) and CR (0x0d).
CONTROL_BYTE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def control_bytes(data: bytes) -> list[tuple[int, int]]:
    """Return (1-based line, byte value) for every forbidden control byte (pure; unit-tested below)."""
    return [(data.count(b"\n", 0, match.start()) + 1, match.group()[0])
            for match in CONTROL_BYTE.finditer(data)]


def scanned_sources(repo_root: Path) -> list[Path]:
    return sorted(path for root in SCANNED_ROOTS for path in (repo_root / root).rglob("*.py"))


def test_no_python_source_carries_a_control_byte() -> None:
    sources = scanned_sources(REPO_ROOT)
    assert len(sources) > 100, "the scan found almost no sources; the roots moved"
    offenders = []
    for path in sources:
        for line, value in control_bytes(path.read_bytes()):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{line}: byte 0x{value:02x}")
    assert offenders == [], (
        "control bytes in Python source (write the escape, e.g. r'\\b', not the byte):\n  "
        + "\n  ".join(offenders))


@pytest.mark.parametrize("value", [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20)])
def test_every_forbidden_control_byte_is_reported(value: int) -> None:
    assert control_bytes(b"x = 1\ny = '" + bytes([value]) + b"'\n") == [(2, value)]


@pytest.mark.parametrize("data", [
    b"a = 1\tb = 2\r\n",
    b"pattern = r'\\bimport\\b'\n",
    "s = 'café — °F'\n".encode("utf-8"),
    b"x = 0x7f\n" + bytes([0x7F]) + b"\n",
], ids=["tab-lf-cr", "escaped-word-boundary", "utf8-text", "del-is-not-c0"])
def test_allowed_bytes_are_not_reported(data: bytes) -> None:
    assert control_bytes(data) == []


def test_the_literal_backspace_regex_defect_is_caught() -> None:
    # The 2026-10-25 shape: re.compile("\bfrom weather\b") in a non-raw string stores 0x08 twice.
    source = 'PATTERN = re.compile("\bfrom weather\b")\n'.encode("utf-8")
    assert control_bytes(source) == [(1, 0x08), (1, 0x08)]


def test_scan_covers_both_roots_and_only_python(tmp_path: Path) -> None:
    for name in ("src/pkg/a.py", "tests/b.py", "tests/fixtures/c.csv.gz", "docs/d.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    found = [path.relative_to(tmp_path).as_posix() for path in scanned_sources(tmp_path)]
    assert found == ["src/pkg/a.py", "tests/b.py"]
