"""H1 oracle-handout cut script (maker replay v2 shadow gate, spec v3.4).

Read when: cutting, re-binding or Defending the H1 oracle handout. The contract is
``docs/roadmap/maker-replay-v2-shadow-gate-spec-v3.4-DRAFT-2026-10-07.md`` (accepted
2026-10-07): §1 source pins, §2 handout contents, §3 substitution table, §4 check,
§5 filtered tree with the R1/R2/R4 rulings. Stdlib only. Workstation (non-capture)
tool; it never authors the oracle and grants no transfer or handout authority.

Modes:

``cut``     Verify every source hash and refuse on any mismatch before reading a line;
            apply the 49 live substitutions; copy the code items, the 89a text, the
            rulings sheet and the cover prompt; run the §4 check, the MO1/MO2
            self-tests and the deny-list drift check; build the filtered tree (§5
            globs, the R4b recorded exclusion list ``R4B_WITHHELD``, then the R4
            fail-closed import refusal); create a standalone
            repository in a NEW directory holding one parentless commit; assert the
            R1 invariants; write ``H1-manifest.json`` and print its SHA-256, the
            binding value. Any refusal deletes the partial output directory.
            Globs are case-insensitive and cover everything below a matching
            directory; an included path whose name says replay v2 refuses unless it
            is a handout source (Defender B1). Plan paths are relative, code pins are
            full blob ids, and a CRLF checkout of this script is refused.
``rebind``  Given a manifest and a new build-line commit that descends from the cut
            commit, verify that the code items (H-6..H-9) and the 89a text (H-10) are
            byte-identical there (R2). Identical: print a re-bind record. Different:
            exit non-zero with a diff summary (a re-hand).

Expected outputs (master, 2026-10-07): the full SHA-256 of H-1..H-9 is pinned in
``EXPECTED_OUTPUT_SHA256``; the plan must carry each value in full and equal to it. Cut and
rebind accept only full 64-hex hashes; the ``prefix…suffix`` form is read only by
``spec_abbreviation_matches``, which the tests use to check the constant against v3.4 §7.

Plan layout (Defender D3): plan paths are relative to the plan file, so the plan must sit at
the same depth relative to the frozen spec copies as when its hashes were recorded; the
2026-10-07 dry-run plan lives in ``C:/b/h1plan/`` with ``spec_source_dir`` =
``../../wt/workstation-chat/l-data/swarm-m/h1-frozen-20261007``.

Exit codes: 0 success, 2 refused (fail closed), 1 usage error.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tokenize
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

PLAN_SCHEMA = "h1_cut_plan_v1"
MANIFEST_SCHEMA = "h1_manifest_v1"
REBIND_SCHEMA = "h1_rebind_v1"
MANIFEST_NAME = "H1-manifest.json"
HANDOUT_DIR = "handout"
REPO_DIR = "oracle-repo"
TAR_NAME = "filtered-snapshot.tar"
BRANCH = "main"
SNAPSHOT_IDENT = b"H1 cut <h1-cut@example.invalid> 946684800 +0000"
SNAPSHOT_MESSAGE = b"H1 filtered snapshot\n"
KERNEL_PATH = "src/maker_core/" + "replay/v2/kernel.py"
CODE_IDS = ("H-6", "H-7", "H-8", "H-9")

# Master's ruling (2026-10-07): the full expected output SHA-256 of H-1..H-9 is authoritative and
# mandatory. Produced by the 501f47579 dry-run; agrees with v3.4 §7 (full values for H-1..H-5,
# prefix and suffix for H-6..H-9). A plan must carry each value and it must equal this exactly.
EXPECTED_OUTPUT_SHA256: dict[str, str] = {
    "H-1": "70437cb34b8a77aa9141daaaed4997d9828853f3ba35c0fa4569d71db5485ef0",
    "H-2": "abd9337c6cf332a694a246f88bbc940a448195e5fcda2b59053244495643d987",
    "H-3": "08f6d87c15995017fb1514511bde61812669b3968c75a0df57d07c9eb2c524d9",
    "H-4": "2c24c9f01c62836edffbd49a2496f76f6751955d16680f4b1b4831b3c3eb9a38",
    "H-5": "66668f9c6d8e7ccb138f1a5d6fdede9cd7463f3604146b13efa6159b22c1cacb",
    "H-6": "92f9f721c276797500d03f8cfad5ac92a06bbd8f9f134335245fab7aaecba3b1",
    "H-7": "414acf14605e0eda88df7c94e674d5779bc44309ce5e1a434a636178bbe6e7bb",
    "H-8": "23b4d6966e8a86fc2fcb97561de18877522ea4e8adb4506ab5f4d649c4b38b49",
    "H-9": "60171f9d6d8e564fec3c3b4866fa5e0b224ff8f18cea37283e807dde206062a8",
}


class CutRefused(Exception):
    """A fail-closed refusal. No manifest is written."""


# --------------------------------------------------------------------------- §3 table


@dataclass(frozen=True)
class Sub:
    """One live entry of the v3.4 §3 substitution table (line numbers are 1-based, LF)."""

    id: str
    source: str
    kind: str  # span | cell | lines | delete
    start: int
    end: int
    old: str | None = None
    new: tuple[str, ...] = ()
    first: str | None = None
    last: str | None = None
    left: str | None = None
    right: str | None = None


# Transcribed from v3.4 §3 (49 live entries; S4, S9, S13, S14, S23, S28, S29, S31 and
# S32 are withdrawn by §8 Q1 and have no entry). The test suite re-parses §3 of the
# repository copy and asserts equality with this table.
V34_TABLE: tuple[Sub, ...] = (
    Sub('S1', 'D-shadow-gate-spec-v3.3.md', 'delete', 290, 322, first="### 6.2 The handout (replaces v3.2 §6's item list and its check)", last=''),
    Sub('S2', 'D-shadow-gate-spec-v3.2.md', 'delete', 614, 677, first='## Annex K — U3 only. NOT part of the oracle handout (§6). `[v3.2: MF-8, N3]`', last='10. Fills: 5 = 4 at price + 1 strictly through; E recomputed (A = 11 sessions, B = 3 days); strictly-through E[power] at 21 d ≈ 23 % (A), and the first-live cap almost surely binds; OD11 is now decidable.'),
    Sub('S3', 'D-shadow-gate-spec-v3.2.md', 'span', 79, 79, old='in `REPLACEMENT_REASONS` (`kernel.py:41-42`)', new=("in the Kernel's closed list of replacement reasons (`kernel.py:41-42`)",)),
    Sub('S5', 'D-shadow-gate-spec-v3.2.md', 'span', 149, 149, old="the Kernel's `value.book`", new=("the Kernel's composed decision book",)),
    Sub('S6', 'D-shadow-gate-spec-v3.2.md', 'lines', 245, 247, new=('- But the horizon that the Kernel and `decide()` use is the **captured descriptor\'s** `horizon_days`. The descriptor record payload carries it (`payloads.py:41,80`). The Kernel passes the latest descriptor record\'s horizon into the decision inputs (`kernel.py:524,534`). Registration §4 says activity follows "the latest captured descriptor at or before t", amended by C13 (§4.4) to "captured or derived".',)),
    Sub('S7', 'D-shadow-gate-spec-v3.2.md', 'span', 375, 375, old='hashed into `view_state`)', new=("hashed into the Kernel's view-state wake signature)",)),
    Sub('S8', 'D-shadow-gate-spec-v3.2.md', 'span', 377, 377, old='(the `reason` is in `view_state`)', new=('(the `reason` is in the view-state wake signature)',)),
    Sub('S10', 'D-shadow-gate-spec-v3.2.md', 'span', 460, 460, old='or the strings `def compose_book`', new=('or a denied Kernel string',)),
    Sub('S11', 'D-shadow-gate-spec-v3.2.md', 'lines', 461, 461, new=("  (the denied list is kept with the coordinator's script).",)),
    Sub('S12', 'D-shadow-gate-spec-v3.2.md', 'lines', 555, 555, new=("- W2(a)'s guard against resting legs is an explicit `BundleError`, not an assertion",)),
    Sub('S15', 'D-shadow-gate-spec-v3.1.md', 'span', 67, 67, old="The Kernel's `add_own` iterates", new=("The Kernel's own-leg composition iterates",)),
    Sub('S16', 'D-shadow-gate-spec-v3.1.md', 'cell', 68, 68, new=('After a replacement-reason CANCEL, the Kernel decides the replacement on the pre-cancel decision book with `existing = ()`, after its leg ledger has been cleared; so the cancelled size counts as competing liquidity and displayed depth.',), left='| G2 | ', right=' | `kernel.py:546-549`'),
    Sub('S17', 'D-shadow-gate-spec-v3.1.md', 'span', 71, 71, old='the same composed `value.book`', new=('the same composed decision book',)),
    Sub('S18', 'D-shadow-gate-spec-v3.1.md', 'span', 151, 151, old='part of `view_state` (`kernel.py:198`)', new=("part of the Kernel's view-state wake signature (`kernel.py:198`)",)),
    Sub('S19', 'D-shadow-gate-spec-v3.1.md', 'span', 187, 187, old='`C_book(public, state.legs)`', new=('`C_book` of the public book and the resting legs',)),
    Sub('S20', 'D-shadow-gate-spec-v3.1.md', 'lines', 255, 281, new=('[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]',)),
    Sub('S21', 'D-shadow-gate-spec-v3.1.md', 'lines', 283, 284, new=("The Kernel's frozen composition step is replaced by `C_book` of the latest public book and the resting legs. `decide()`, `policy.py` and the v1 engine are **not**",)),
    Sub('S22', 'D-shadow-gate-spec-v3.1.md', 'span', 299, 299, old='`book_state` reads the public record', new=("the Kernel's book-state wake signature reads the public record",)),
    Sub('S24', 'D-shadow-gate-spec-v3.1.md', 'lines', 373, 380, new=('[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]',)),
    Sub('S25', 'D-shadow-gate-spec-v3.1.md', 'span', 382, 382, old='applied to `state.legs`.', new=('applied to the resting legs.',)),
    Sub('S26', 'D-shadow-gate-spec-v3.1.md', 'span', 383, 383, old='since `state.legs == ()`.', new=('since the resting legs are empty.',)),
    Sub('S27', 'D-shadow-gate-spec-v3.1.md', 'span', 653, 653, old='`REPLACEMENT_REASONS`, `kernel.py:41-42`, transcribed', new=("the Kernel's replacement-reason constant, `kernel.py:41-42`, transcribed",)),
    Sub('S30', 'D-shadow-gate-spec-v3.1.md', 'span', 902, 902, old='KS1 (`add_own` omitted)', new=('KS1 (own-leg composition omitted)',)),
    Sub('S33', 'D-shadow-gate-spec-v3.md', 'span', 42, 42, old='(`view_state`, `kernel.py:179-199`)', new=('(its view-state wake signature, `kernel.py:179-199`)',)),
    Sub('S34', 'D-shadow-gate-spec-v3.md', 'span', 45, 45, old='| F7 | `view_state` includes', new=("| F7 | The Kernel's view-state wake signature includes",)),
    Sub('S35', 'D-shadow-gate-spec-v3.md', 'span', 169, 169, old='(engine `add_own` before `decide()`)', new=("(the engine's own-leg composition before `decide()`)",)),
    Sub('S36', 'D-shadow-gate-spec-v3.md', 'span', 268, 268, old='| `add_own` adds the paper legs', new=("| The Kernel's own-leg composition adds the paper legs",)),
    Sub('S37', 'D-shadow-gate-spec-v3.md', 'span', 268, 268, old='must **not** call `add_own`', new=('must **not** apply that composition',)),
    Sub('S38', 'D-shadow-gate-spec-v3.md', 'span', 268, 268, old='(after `add_own(O)`)', new=('(after composing O in)',)),
    Sub('S39', 'D-shadow-gate-spec-v3.md', 'span', 566, 566, old='| KS1 | `add_own` omitted |', new=('| KS1 | Own-leg composition omitted |',)),
    Sub('S40', 'D-shadow-gate-spec-v2.md', 'span', 89, 89, old='`V2Config.hazard_per_minute`', new=("the replay engine config's `hazard_per_minute`",)),
    Sub('S41', 'D-shadow-gate-spec-v2.md', 'span', 90, 90, old='`fill_rule == V2Config.fill_bound`', new=("`fill_rule` equals the replay engine config's `fill_bound`",)),
    Sub('S42', 'D-shadow-gate-spec-v2.md', 'span', 94, 94, old='| `V2Config` field |', new=('| Replay engine config field |',)),
    Sub('S43', 'D-shadow-gate-spec-v2.md', 'span', 135, 135, old='`state.latest["descriptor"].market`', new=("the latest descriptor record's market",)),
    Sub('S44', 'D-shadow-gate-spec-v2.md', 'span', 137, 137, old='(`add_own`, `kernel.py:527-531`)', new=("(the Kernel's own-leg composition, `kernel.py:527-531`)",)),
    Sub('S45', 'D-shadow-gate-spec-v2.md', 'span', 137, 137, old='then `add_own` exactly as the kernel does', new=('then the own-leg composition exactly as the Kernel does',)),
    Sub('S46', 'D-shadow-gate-spec-v2.md', 'span', 141, 141, old='`state.latest["outcome_view"]`', new=('the latest outcome-view record',)),
    Sub('S47', 'D-shadow-gate-spec-v2.md', 'span', 142, 142, old='`state.latest["info_event"]`', new=('the latest info-event record',)),
    Sub('S48', 'D-shadow-gate-spec-v2.md', 'span', 144, 144, old='(`recomputed_portfolio`, `kernel.py:574-601`)', new=("(the Kernel's portfolio recomputation, `kernel.py:574-601`)",)),
    Sub('S49', 'D-shadow-gate-spec-v2.md', 'span', 153, 153, old='| `state.legs`, the legs after the last decision.', new=('| The resting legs after the last decision.',)),
    Sub('S50', 'D-shadow-gate-spec-v2.md', 'span', 153, 153, old='QUOTE sets them (`record_decision`).', new=("QUOTE sets them (the Kernel's post-decision state update).",)),
    Sub('S51', 'D-shadow-gate-spec-v2.md', 'span', 155, 155, old='| `state.last_quote`, the instant of the last QUOTE decision', new=("| The instant of the last QUOTE decision (the Kernel's last-quote latch)",)),
    Sub('S52', 'D-shadow-gate-spec-v2.md', 'span', 162, 162, old='a changed `record_signature` (', new=('a changed record signature (',)),
    Sub('S53', 'D-shadow-gate-spec-v2.md', 'span', 164, 164, old='a reason in `REPLACEMENT_REASONS`,', new=("a reason in the Kernel's closed replacement-reason list,",)),
    Sub('S54', 'D-shadow-gate-spec-v2.md', 'span', 165, 165, old='| `record_decision` (`kernel.py:345-367`)', new=("| The Kernel's post-decision state update (`kernel.py:345-367`)",)),
    Sub('S55', 'D-shadow-gate-spec-v2.md', 'span', 187, 187, old='`add_own` and portfolio assembly', new=('the own-leg book composition and portfolio assembly',)),
    Sub('S56', 'D-shadow-gate-spec-v2.md', 'span', 190, 190, old='kernel `add_own`/`recomputed_portfolio`', new=("the Kernel's own-leg composition and portfolio recomputation",)),
    Sub('S57', 'D-shadow-gate-spec-v2.md', 'span', 268, 268, old='uses `recomputed_portfolio`.', new=("uses the Kernel's portfolio recomputation.",)),
    Sub('S58', 'D-shadow-gate-spec-v2.md', 'span', 450, 450, old='`add_own`, portfolio assembly', new=('the own-leg book composition, portfolio assembly',)),
)

# §4: denied Kernel identifiers and the identifiers excluded on purpose.
DENIED_IDENTIFIERS = frozenset(
    """
    MAX_OUTPUTS MAX_CLOCK_WINDOWS CAP_FIELDS REPLACEMENT_REASONS V2Config CState _Exclusions
    interval_key make_interval coverage_ok book_state freshness_clock view_state record_signature
    info_boundaries recomputed_portfolio group_by_instant by_condition
    set_legs coverage_touched total_reserve decision_book replacement_book valid_coverage in_clock
    event_window record_decision on_trade reset_day add_own
    """.split()
)
EXCLUDED_IDENTIFIERS = frozenset(
    """
    D EPSILON POLICIES Interval Kernel __init__ __post_init__ append before changed deadline deadlines
    schedule active outputs pull exclude ingest tick portfolio evaluate merged crossed assemble
    compose_book
    """.split()
)
DENIED_LITERALS = ("def compose_book", "add_own", "record_decision", "replace(value", "value.book", "state.latest[")
FENCED_PYTHON = re.compile(r"^\s*```\s*python", re.IGNORECASE)
STATE_ATTR = re.compile(r"\bstate\.[a-z_]")
BACKTICK_SPAN = re.compile(r"`([^`]*)`")

# §5 globs, with the R4 additions (ruled 2026-10-07).
EXCLUSION_GLOBS: tuple[str, ...] = (
    "src/maker_core/replay/**",
    "src/maker_core/shadow/live_kernel.py",
    "src/maker_core/shadow/contract.py",
    "src/maker_core/shadow/runner.py",
    "src/maker_core/shadow/paper.py",
    "src/maker_core/shadow/tape.py",
    "src/maker_core/live/**",
    "src/weather/market/maker_replay_*.py",
    "tests/maker_core/test_replay_*.py",
    "tests/maker_core/test_kernels.py",
    "tests/market/test_maker_replay_*.py",
    "tools/research/maker_replay_v2/**",
    "docs/roadmap/maker-replay-v2-shadow-gate-spec-*",
    "docs/roadmap/agent-report-*-mrv2-*.md",
    "docs/research/maker-replay-v2-registration-DRAFT.md",
    "tests/maker_core/fixtures/**",
    "docs/research/maker-replay-v2-*",
    "tests/operations/test_maker_replay_v2_*",
)

# R4 fail-closed refusal. Written split so that this file does not carry the literal.
_MC = "maker" + "_core"
REPLAY_TEXT = re.compile(_MC + r"\s*[./\\]+\s*replay", re.IGNORECASE)
DYNAMIC_IMPORT_CALLS = frozenset(
    {"import_module", "__import__", "find_spec", "spec_from_file_location", "run_module", "run_path", "load_module"}
)

# Belt and braces for B1: an included path whose name says v2 refuses unless it is a
# handout item's source path. Archive and bytecode files refuse outright (unscannable).
V2_PATH_NAME = re.compile(r"replay[-_]?v2|mrv2", re.IGNORECASE)
UNSCANNABLE_SUFFIXES = (".pyc", ".pyo", ".pyd", ".zip", ".egg", ".whl", ".tar", ".gz", ".tgz", ".bz2", ".xz",
                        ".7z", ".jar")

# R4b (master agent's ruling, 2026-10-07): the recorded exclusion list. These are the
# R4 refusal hits at 501f47579 outside every §5 glob, plus this cut script. Each was
# checked not to be a handout item or required reading of one. The manifest records
# each withheld path with its reason class (never content). Fail closed in both
# directions: a refusal hit not on this list still refuses, and a listed path (other
# than the cut script) that is missing, now glob-excluded, no longer hits, or hits in a
# different class also refuses, because the list was reviewed against one tree and a
# drifted entry would silently withhold an unreviewed file or hide a new import.
REASON_CLASSES = ("v1-import", "string-literal", "path-mention", "cut-script")
CUT_SCRIPT_PATH = "tools/research/maker_replay_v2_h1_cut.py"
R4B_WITHHELD: tuple[tuple[str, str], ...] = (
    ("README.md", "path-mention"),
    ("docs/operations/informed-maker-design-2026-09-25.md", "path-mention"),
    ("docs/operations/maker-replay-bundle.md", "path-mention"),
    ("docs/operations/maker-shadow-runner-design.md", "path-mention"),
    ("docs/operations/package-boundaries.md", "path-mention"),
    ("docs/research/maker-replay-clarification-3-2026-10-01.md", "path-mention"),
    ("docs/research/maker-replay-clarification-4-draft.md", "path-mention"),
    ("docs/research/maker-replay-enrollment-template-2026-09-27.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-09-110l-maker-replay-harness.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-09-110r-replay-execution-pack.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-09-110s-nightly-bundle-export.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-09-111e-exam-executability-revision.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-09-111e-exam-executability.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-10-03-pull-cap-precheck.md", "path-mention"),
    ("docs/roadmap/agent-report-2026-10-111e-followup.md", "path-mention"),
    ("docs/roadmap/audits/exam-plan-b-2026-10-03.md", "path-mention"),
    ("docs/roadmap/correspondence-index.md", "path-mention"),
    ("docs/roadmap/workstation-handoff-2026-09-110l-maker-replay-harness-phase2.md", "path-mention"),
    ("docs/roadmap/workstation-handoff-2026-09-110r-replay-execution-pack.md", "path-mention"),
    ("scripts/ops/workstation_heavy.ps1", "path-mention"),
    ("src/weather/market/maker_fair_value_score.py", "v1-import"),
    ("tests/maker_core/test_exam_pull_cap_precheck.py", "v1-import"),
    ("tests/maker_core/test_re1_runtime.py", "v1-import"),
    ("tests/market/test_maker_fair_value_score.py", "v1-import"),
    ("tests/operations/test_import_architecture.py", "string-literal"),
    ("tools/exam_pull_cap_precheck.py", "v1-import"),
    ("tools/research/pull_cap_precheck/fixture.py", "v1-import"),
    ("tools/research/pull_cap_precheck/measure.py", "v1-import"),
    (CUT_SCRIPT_PATH, "cut-script"),
)


# --------------------------------------------------------------------------- helpers


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def hash_matches(actual: str, expected: str) -> bool:
    """Cut mode: exact equality of two full 64-hex SHA-256 values. Abbreviations never match."""
    full = re.compile(r"[0-9a-f]{64}")
    return bool(full.fullmatch(actual or "")) and bool(full.fullmatch(expected or "")) and actual == expected


def spec_abbreviation_matches(actual: str, expected: str) -> bool:
    """Historical spec text only: the ``prefix…suffix`` form in the v3.4 §7 table (for example
    ``92f9f721…a3b1``). Used solely to cross-check ``EXPECTED_OUTPUT_SHA256`` against that text
    in the tests; nothing in cut or rebind mode calls it."""
    expected = expected.strip().lower()
    for sep in ("…", "..."):
        if sep in expected:
            head, tail = expected.split(sep, 1)
            return len(head) >= 6 and len(tail) >= 4 and actual.startswith(head) and actual.endswith(tail)
    if len(expected) == len(actual):
        return actual == expected
    return len(expected) >= 7 and actual.startswith(expected)


def verify_sha256(data: bytes, expected: str, label: str) -> str:
    actual = sha256_hex(data)
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise CutRefused(f"{label}: source pin must be a full lowercase SHA-256, got {expected!r}")
    if actual != expected:
        raise CutRefused(f"{label}: SHA-256 mismatch (expected {expected}, got {actual}); refused before reading")
    return actual


def _scrubbed_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(repo: Path, *args: str, input_bytes: bytes | None = None, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        env=_scrubbed_env(),
        timeout=600,
    )
    if check and result.returncode != 0:
        raise CutRefused(f"git {' '.join(args[:3])} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def resolve_commit(repo: Path, rev: str) -> str:
    out = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False).decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", out):
        raise CutRefused(f"commit {rev!r} not found in {repo}")
    return out


def read_blob_at(repo: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
        capture_output=True,
        env=_scrubbed_env(),
        timeout=120,
    )
    if result.returncode != 0:
        raise CutRefused(f"{path} is missing at {commit}")
    return result.stdout


def long_path(path: Path) -> Path:
    """Windows extended-length form, so deep repository paths can be written and removed."""
    if os.name != "nt":
        return path
    text = str(path.resolve())
    prefix = "\\\\?\\"
    return path if text.startswith(prefix) else Path(prefix + text)


def remove_tree(path: Path) -> None:
    def _writable_retry(function, target, _exc_info):  # git packs are read-only on Windows
        os.chmod(target, 0o600)
        function(target)

    if path.exists():
        shutil.rmtree(long_path(path), onerror=_writable_retry)


def safe_relpath(path: str, label: str) -> str:
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\\" in path or ":" in path:
        raise CutRefused(f"{label}: unsafe relative path {path!r}")
    return p.as_posix()


# --------------------------------------------------------------------------- §3 cut


def split_lf(text: str) -> tuple[list[str], bool]:
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise CutRefused("source holds a bare CR after CRLF->LF normalisation")
    trailing = text.endswith("\n")
    lines = text.split("\n")
    if trailing:
        lines.pop()
    return lines, trailing


def apply_substitutions(text: str, subs: Sequence[Sub], *, label: str = "source") -> str:
    """Apply one source's substitutions: spans first, then ranges/deletions bottom-up."""
    lines, trailing = split_lf(text)
    n = len(lines)
    original = list(lines)
    spans = [s for s in subs if s.kind in ("span", "cell")]
    ranges = [s for s in subs if s.kind in ("lines", "delete")]
    unknown = [s.id for s in subs if s.kind not in ("span", "cell", "lines", "delete")]
    if unknown:
        raise CutRefused(f"{label}: unknown substitution kinds {unknown}")
    for s in subs:
        if not (1 <= s.start <= s.end <= n):
            raise CutRefused(f"{label} {s.id}: lines {s.start}-{s.end} out of bounds (1-{n})")
    ordered = sorted(ranges, key=lambda s: s.start)
    for a, b in zip(ordered, ordered[1:]):
        if b.start <= a.end:
            raise CutRefused(f"{label}: ranges {a.id} and {b.id} overlap")
    for s in spans:
        if s.start != s.end:
            raise CutRefused(f"{label} {s.id}: a span names exactly one line")
        if any(r.start <= s.start <= r.end for r in ranges):
            raise CutRefused(f"{label} {s.id}: span line lies inside a replaced or deleted range")
    for s in spans:
        i = s.start - 1
        line = lines[i]
        if s.kind == "span":
            if s.old is None or len(s.new) != 1:
                raise CutRefused(f"{label} {s.id}: malformed span entry")
            if original[i].count(s.old) != 1 or line.count(s.old) != 1:
                raise CutRefused(f"{label} {s.id}: span not found exactly once on l.{s.start}")
            lines[i] = line.replace(s.old, s.new[0], 1)
        else:
            if not s.left or not s.right or len(s.new) != 1:
                raise CutRefused(f"{label} {s.id}: malformed cell entry")
            if line.count(s.left) != 1:
                raise CutRefused(f"{label} {s.id}: cell left marker not found exactly once on l.{s.start}")
            head, rest = line.split(s.left, 1)
            if rest.count(s.right) != 1:
                raise CutRefused(f"{label} {s.id}: cell right marker not found exactly once on l.{s.start}")
            _, tail = rest.split(s.right, 1)
            lines[i] = head + s.left + s.new[0] + s.right + tail
    for s in sorted(ranges, key=lambda s: s.start, reverse=True):
        a, b = s.start - 1, s.end
        if s.first is not None and lines[a] != s.first:
            raise CutRefused(f"{label} {s.id}: first line of l.{s.start}-{s.end} does not match the table")
        if s.last is not None and lines[b - 1] != s.last:
            raise CutRefused(f"{label} {s.id}: last line of l.{s.start}-{s.end} does not match the table")
        if s.kind == "delete":
            if s.new:
                raise CutRefused(f"{label} {s.id}: a deletion has no replacement text")
            lines[a:b] = []
        else:
            if not s.new:
                raise CutRefused(f"{label} {s.id}: a line replacement needs text")
            lines[a:b] = list(s.new)
    out = "\n".join(lines)
    return out + "\n" if trailing else out


# --------------------------------------------------------------------------- §4 check


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str


def section4_hits(path: str, text: str) -> list[Hit]:
    hits: list[Hit] = []
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if FENCED_PYTHON.match(line):
            hits.append(Hit(path, number, "rule1:fenced-python"))
        for literal in DENIED_LITERALS:
            if literal in line:
                hits.append(Hit(path, number, f"rule2:{literal}"))
        if STATE_ATTR.search(line):
            hits.append(Hit(path, number, "rule3:state-attribute"))
        for span in BACKTICK_SPAN.findall(line):
            for token in re.findall(r"[A-Za-z0-9_]+", span):
                if token in DENIED_IDENTIFIERS:
                    hits.append(Hit(path, number, f"rule4:{token}"))
    return hits


def kernel_names(source: bytes) -> set[str]:
    """Module-level and method names of the kernel module (names only; bodies are not kept)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CutRefused(f"deny-list drift: the kernel module does not parse ({exc.msg})") from None
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for leaf in ast.walk(target):
                    if isinstance(leaf, ast.Name):
                        names.add(leaf.id)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def drift_check(source: bytes) -> dict:
    names = kernel_names(source)
    unlisted = sorted(names - DENIED_IDENTIFIERS - EXCLUDED_IDENTIFIERS)
    if unlisted:
        raise CutRefused(f"deny-list drift: {len(unlisted)} kernel name(s) in neither §4 list: {', '.join(unlisted)}")
    return {"names": len(names), "unlisted": 0}


# --------------------------------------------------------------------------- §5 filter


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Glob to regex. Case-insensitive; like gitignore, a pattern whose last segment
    matches a directory also excludes everything below it (Defender B1)."""
    parts = pattern.split("/")
    out = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            out.append("(?:[^/]+/)*[^/]+" if last else "(?:[^/]+/)*")
            continue
        segment = "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in part)
        out.append(segment + "(?:/.+)?" if last else segment + "/")
    return re.compile("".join(out), re.IGNORECASE)


_GLOB_RES = tuple(glob_regex(g) for g in EXCLUSION_GLOBS)


def excluded_by(path: str, globs: Iterable[re.Pattern[str]] = _GLOB_RES) -> bool:
    return any(g.fullmatch(path) for g in globs)


def _is_utf16(data: bytes) -> bool:
    return data.startswith((b"\xff\xfe", b"\xfe\xff")) or (len(data) >= 4 and data.count(b"\x00") * 4 >= len(data))


def _decode(data: bytes) -> str:
    if _is_utf16(data):
        for codec in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return data.decode(codec)
            except UnicodeDecodeError:
                continue
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _is_replay_module(name: str | None) -> bool:
    return bool(name) and (name == f"{_MC}.replay" or name.startswith(f"{_MC}.replay."))


def _package_of(path: str) -> list[str]:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    return list(parts[:-1])


def _fold(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
            and len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple))):
        sep = _fold(node.func.value)
        items = [_fold(e) for e in node.args[0].elts]
        if sep is not None and all(i is not None for i in items):
            return sep.join(items)
    return None


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _token_strings(text: str) -> list[str] | None:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    strings = []
    for tok in tokens:
        if tok.type == tokenize.STRING:
            try:
                value = ast.literal_eval(tok.string)
            except (ValueError, SyntaxError):
                value = tok.string
            strings.append(value if isinstance(value, str) else _decode(value))
    return strings


def _string_reasons(strings: list[str], imports_mc: bool, dynamic_nonconst: bool) -> list[str]:
    reasons = []
    for value in strings:
        if REPLAY_TEXT.search(value) or REPLAY_TEXT.search(re.sub(r"\s+", "", value)):
            reasons.append("string literal names the replay package")
            break
    if not reasons and REPLAY_TEXT.search("".join(strings)):
        reasons.append("split string literals join to the replay package name")
    # Pieces that would join into the package name: one literal ends with the package
    # name (or its separator), another starts with the subpackage name.
    heads = [s for s in strings if re.search(_MC + r"\s*[./\\]*\s*$", s)]
    tails = [s for s in strings if re.match(r"^\s*[./\\]*\s*replay", s, re.IGNORECASE)]
    if heads and tails:
        reasons.append("split string: a literal ending in the package name and one starting with 'replay'")
    if imports_mc and tails:
        reasons.append("imports the bare maker package and names 'replay' as a string")
    if dynamic_nonconst and any(_MC in s for s in strings) and any("replay" in s.lower() for s in strings):
        reasons.append("dynamic import with a computed name in a file naming the package and 'replay'")
    return reasons


def _python_reasons(path: str, text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        strings = _token_strings(text)
        if strings is None:
            return ["python file neither parses nor tokenizes (fail closed)"]
        return _string_reasons(strings, imports_mc=_MC in text, dynamic_nonconst=False)
    reasons: list[str] = []
    imports_mc = False
    dynamic_nonconst = False
    constants: list[tuple[int, int, str]] = []
    package = _package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_replay_module(alias.name):
                    reasons.append(f"imports {alias.name}")
                if alias.name == _MC:
                    imports_mc = True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level - 1 <= len(package) else []
                module = ".".join([*base, module] if module else base)
            if _is_replay_module(module):
                reasons.append(f"imports from {module}")
            if module == _MC:
                imports_mc = True
                if any(a.name in ("replay", "*") for a in node.names):
                    reasons.append(f"imports replay (or *) from {module}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            constants.append((node.lineno, node.col_offset, node.value))
        elif isinstance(node, ast.Call) and _call_name(node) in DYNAMIC_IMPORT_CALLS:
            first = node.args[0] if node.args else None
            folded = _fold(first) if first is not None else None
            if folded is None:
                dynamic_nonconst = True
            elif REPLAY_TEXT.search(folded) or _is_replay_module(folded):
                reasons.append(f"dynamic import of {folded}")
        if isinstance(node, (ast.BinOp, ast.JoinedStr, ast.Call)):
            folded = _fold(node)
            if folded is not None and not isinstance(node, ast.Constant):
                if REPLAY_TEXT.search(folded):
                    reasons.append("folded string expression names the replay package")
                constants.append((getattr(node, "lineno", 0), getattr(node, "col_offset", 0), folded))
    strings = [value for _, _, value in sorted(constants)]
    reasons.extend(_string_reasons(strings, imports_mc, dynamic_nonconst))
    return reasons


def refusal_reasons(path: str, data: bytes) -> list[str]:
    """R4: why ``path`` must not be in the filtered tree (empty list: allowed)."""
    text = _decode(data)
    reasons = []
    if REPLAY_TEXT.search(data.decode("latin-1")):
        reasons.append("raw bytes name the replay package")
    if path.lower().endswith(UNSCANNABLE_SUFFIXES):
        reasons.append("archive or bytecode file (unscannable; fail closed)")
    if path.endswith((".py", ".pyi", ".pyw")) and _is_utf16(data):
        reasons.append("UTF-16 python source (fail closed)")
    if REPLAY_TEXT.search(text):
        reasons.append("text names the replay package")
    if path.endswith((".py", ".pyi", ".pyw")):
        reasons.extend(_python_reasons(path, text))
    if path.lower().endswith(TABULAR_SUFFIXES) and engine_output_shaped(path, text):
        reasons.append(ENGINE_OUTPUT_REASON)
    return sorted(set(reasons))


# Defender D1 (2026-10-07): a JSON/JSONL/CSV file shaped like replay engine output is refused
# whatever its path or name. The key must be exactly ``decision_sha256`` (the release field is
# ``promotion_decision_sha256`` and does not count) and must co-occur with a companion key.
TABULAR_SUFFIXES = (".json", ".jsonl", ".ndjson", ".csv")
ENGINE_OUTPUT_KEY = "decision_sha256"
ENGINE_OUTPUT_COMPANIONS = frozenset({"final_cash", "fills", "exclusions_sha256"})
ENGINE_OUTPUT_REASON = "engine-output shaped data (decision_sha256 with final_cash/fills/exclusions_sha256)"
_JSON_KEY = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:')


def _json_keys(value: object, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            keys.add(str(key).strip().casefold())
            _json_keys(inner, keys)
    elif isinstance(value, list):
        for inner in value:
            _json_keys(inner, keys)


def engine_output_shaped(path: str, text: str) -> bool:
    """Keys at any depth (JSON, every JSONL line) or header columns (CSV); fail closed on parse errors
    by falling back to every quoted ``"key":`` in the raw text."""
    keys: set[str] = set()
    lower = path.lower()
    if lower.endswith(".csv"):
        rows = csv.reader(io.StringIO(text.lstrip("\ufeff")))
        header = next(rows, [])
        keys.update(column.strip().casefold() for column in header)
    else:
        documents = text.splitlines() if lower.endswith((".jsonl", ".ndjson")) else [text]
        for document in documents:
            if not document.strip():
                continue
            try:
                _json_keys(json.loads(document.lstrip("\ufeff")), keys)
            except ValueError:
                keys.update(match.group(1).strip().casefold() for match in _JSON_KEY.finditer(document))
    return ENGINE_OUTPUT_KEY in keys and bool(keys & ENGINE_OUTPUT_COMPANIONS)


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    blob: str


def list_tree(repo: Path, commit: str) -> list[TreeEntry]:
    raw = git(repo, "ls-tree", "-r", "-z", "--full-tree", commit)
    entries = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, blob = meta.decode().split(" ")
        name = path.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise CutRefused(f"filtered tree: unsupported entry {name} (mode {mode}, {kind}); fail closed")
        check_tree_path(name)
        entries.append(TreeEntry(name, mode, blob))
    folded: dict[str, str] = {}
    for entry in entries:
        other = folded.setdefault(entry.path.casefold(), entry.path)
        if other != entry.path:
            raise CutRefused(f"filtered tree: case-colliding paths {other!r} and {entry.path!r}")
    return entries


def check_tree_path(name: str) -> None:
    if "\n" in name or name.startswith('"') or "\\" in name or ":" in name:
        raise CutRefused(f"filtered tree: unsupported path {name!r} (fail closed)")


class BlobReader:
    """One ``git cat-file --batch`` process; reads only the blobs asked for."""

    def __init__(self, repo: Path):
        self._proc = subprocess.Popen(
            ["git", "-C", str(repo), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=_scrubbed_env(),
        )

    def read(self, blob: str) -> bytes:
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(blob.encode() + b"\n")
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise CutRefused(f"cat-file: unexpected header for {blob}")
        data = self._proc.stdout.read(int(header[2]))
        self._proc.stdout.read(1)
        return data

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=60)


def reason_class(path: str, reasons: Sequence[str]) -> str:
    """The R4b reason class of a refusal hit."""
    if ENGINE_OUTPUT_REASON in reasons:
        return "engine-output"  # not a withholdable class: always refuses
    if any(r.startswith(("imports", "dynamic import")) for r in reasons):
        return "v1-import"
    if path.endswith((".py", ".pyi", ".pyw")):
        return "string-literal"
    return "path-mention"


def _withheld_map(withheld: Sequence[tuple[str, str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path, cls in withheld:
        if cls not in REASON_CLASSES:
            raise CutRefused(f"R4b list: {path} has unknown reason class {cls!r}")
        if path in mapping:
            raise CutRefused(f"R4b list: {path} is listed twice")
        mapping[path] = cls
    return mapping


def filtered_files(repo: Path, commit: str, withheld: Sequence[tuple[str, str]] = R4B_WITHHELD,
                   handout_sources: Iterable[str] = ()) -> tuple[list[tuple[TreeEntry, bytes]], list[dict]]:
    """Apply the §5 globs, the R4b recorded list, then the R4 refusal over every remaining file.

    Returns the kept files and the withheld records (path and reason class only).
    """
    listed = _withheld_map(withheld)
    allowed_names = {p.casefold() for p in handout_sources}
    files: list[tuple[TreeEntry, bytes]] = []
    records: list[dict] = []
    refused: list[str] = []
    stale: list[str] = []
    seen: set[str] = set()
    reader = BlobReader(repo)
    try:
        for entry in list_tree(repo, commit):
            if excluded_by(entry.path):
                continue
            cls = listed.get(entry.path)
            if cls == "cut-script":
                seen.add(entry.path)
                records.append({"path": entry.path, "reason_class": cls})
                continue
            data = reader.read(entry.blob)
            reasons = refusal_reasons(entry.path, data)
            if cls is not None:
                seen.add(entry.path)
                if not reasons:
                    stale.append(f"{entry.path}: listed as {cls} but no longer hits")
                elif reason_class(entry.path, reasons) != cls:
                    stale.append(f"{entry.path}: listed as {cls} but now hits as {reason_class(entry.path, reasons)}")
                else:
                    records.append({"path": entry.path, "reason_class": cls})
                continue
            if V2_PATH_NAME.search(entry.path) and entry.path.casefold() not in allowed_names:
                reasons = [*reasons, "path name says replay v2 and it is not a handout item"]
            if reasons:
                refused.append(f"{entry.path}: {'; '.join(reasons)}")
            files.append((entry, data))
    finally:
        reader.close()
    for path, cls in listed.items():
        if path not in seen and cls != "cut-script":
            stale.append(f"{path}: listed as {cls} but absent from the filtered tree at {commit[:12]}")
    if refused or stale:
        parts = []
        if refused:
            parts.append(f"R4 import refusal: {len(refused)} unlisted file(s) after filtering:\n  " + "\n  ".join(refused))
        if stale:
            parts.append(f"R4b list is stale: {len(stale)} entr(y/ies):\n  " + "\n  ".join(stale))
        raise CutRefused("\n".join(parts))
    return files, sorted(records, key=lambda r: r["path"])


# --------------------------------------------------------------------------- R1 repo


def deterministic_tar(files: Sequence[tuple[TreeEntry, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for entry, data in sorted(files, key=lambda item: item[0].path):
            info = tarfile.TarInfo(entry.path)
            info.size = len(data)
            info.mode = 0o755 if entry.mode == "100755" else 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def create_standalone_repo(repo_dir: Path, files: Sequence[tuple[TreeEntry, bytes]]) -> dict:
    """git init + one parentless commit via fast-import (exact bytes, fixed identity)."""
    if repo_dir.exists():
        raise CutRefused(f"{repo_dir} already exists; the standalone repository needs a NEW directory")
    repo_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as empty_template:
        git(repo_dir, "init", "-q", f"--template={empty_template}", f"--initial-branch={BRANCH}")
    git(repo_dir, "config", "core.longpaths", "true")
    git(repo_dir, "config", "core.logAllRefUpdates", "false")
    stream = io.BytesIO()
    stream.write(b"commit refs/heads/" + BRANCH.encode() + b"\n")
    stream.write(b"author " + SNAPSHOT_IDENT + b"\n")
    stream.write(b"committer " + SNAPSHOT_IDENT + b"\n")
    stream.write(b"data %d\n" % len(SNAPSHOT_MESSAGE) + SNAPSHOT_MESSAGE)
    for entry, data in sorted(files, key=lambda item: item[0].path):
        stream.write(b"M " + entry.mode.encode() + b" inline " + entry.path.encode("utf-8") + b"\n")
        stream.write(b"data %d\n" % len(data) + data + b"\n")
    stream.write(b"done\n")
    git(repo_dir, "fast-import", "--quiet", "--done", input_bytes=stream.getvalue())
    for entry, data in files:
        target = long_path(repo_dir).joinpath(*entry.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git(repo_dir, "read-tree", BRANCH)
    remove_tree(repo_dir / ".git" / "logs")
    commit = git(repo_dir, "rev-parse", BRANCH).decode().strip()
    tree = git(repo_dir, "rev-parse", f"{BRANCH}^{{tree}}").decode().strip()
    return {"commit": commit, "tree": tree}


def assert_r1_invariants(repo_dir: Path) -> dict:
    """R1: one parentless commit, no remotes, no alternates, no shared or stray objects."""
    git_dir = repo_dir / ".git"
    if not git_dir.is_dir():
        raise CutRefused("R1: .git is not a directory (a gitfile or worktree link is not standalone)")
    for relative in ("objects/info/alternates", "objects/info/http-alternates", "commondir", "info/grafts",
                     "shallow", "worktrees", "modules", "logs", "hooks", "FETCH_HEAD", "ORIG_HEAD"):
        if (git_dir / relative).exists():
            raise CutRefused(f"R1: {relative} must be absent")
    packed = git_dir / "packed-refs"
    if packed.exists():
        for line in packed.read_bytes().decode("utf-8", "replace").split("\n"):
            line = line.strip()
            if line and not line.startswith(("#", "^")) and line.split(" ", 1)[-1] != f"refs/heads/{BRANCH}":
                raise CutRefused("R1: packed-refs holds another ref")
    identity = git(repo_dir, "config", "--local", "--get-regexp", r"^(user|author|committer)\.", check=False).strip()
    if identity:
        raise CutRefused("R1: an identity is configured in the repository")
    commits = git(repo_dir, "rev-list", "--all").decode().split()
    if len(commits) != 1:
        raise CutRefused(f"R1: git rev-list --all counts {len(commits)} commits, not exactly 1")
    parents = git(repo_dir, "rev-list", "--parents", "-n", "1", commits[0]).decode().split()
    if len(parents) != 1:
        raise CutRefused("R1: the snapshot commit has a parent")
    if git(repo_dir, "remote").strip():
        raise CutRefused("R1: the repository has a remote")
    remote_config = git(repo_dir, "config", "--local", "--get-regexp", r"^remote\.", check=False).strip()
    if remote_config:
        raise CutRefused("R1: remote configuration present")
    refs = git(repo_dir, "for-each-ref", "--format=%(refname)").decode().split()
    if refs != [f"refs/heads/{BRANCH}"]:
        raise CutRefused(f"R1: refs other than refs/heads/{BRANCH}: {refs}")
    present = set(git(repo_dir, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)").decode().split())
    reachable = {line.split(" ", 1)[0] for line in git(repo_dir, "rev-list", "--objects", "--all").decode().splitlines()}
    if present != reachable:
        raise CutRefused(f"R1: {len(present - reachable)} object(s) not reachable from the snapshot commit")
    ident = SNAPSHOT_IDENT.decode()
    for field_name in ("an", "ae", "at", "cn", "ce", "ct"):
        value = git(repo_dir, "log", "-1", f"--format=%{field_name}", commits[0]).decode().strip()
        if value not in ident:
            raise CutRefused("R1: the snapshot commit does not carry the fixed identity")
    return {"rev_list_all": 1, "parents": 0, "remotes": 0, "alternates": "absent", "logs": "absent", "refs": refs,
            "objects": len(present)}


# --------------------------------------------------------------------------- plan + cut


@dataclass
class HandoutFile:
    id: str
    kind: str
    handout_path: str
    data: bytes
    source: str
    source_sha256: str
    extra: dict = field(default_factory=dict)

    def record(self) -> dict:
        row = {"id": self.id, "kind": self.kind, "handout_path": self.handout_path, "bytes": len(self.data),
               "sha256": sha256_hex(self.data), "source": self.source, "source_sha256": self.source_sha256}
        row.update(self.extra)
        return row


def _plan_path(plan_dir: Path, value: str) -> Path:
    """Plan paths are relative to the plan file; an absolute path is refused (host-specific binding)."""
    if Path(value).is_absolute() or PurePosixPath(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise CutRefused(f"plan path {value!r} is absolute; use a path relative to the plan file")
    return plan_dir / value


def _read_pinned_item(item: dict, plan_dir: Path, repo: Path, label: str) -> tuple[bytes, str, dict]:
    """A pinned text item: ``{"path", "commit"}`` read from the repository, or ``{"file"}``
    relative to the plan. Returns (bytes, source label, extra manifest fields)."""
    if "path" in item and "commit" in item:
        commit = resolve_commit(repo, item["commit"])
        data = read_blob_at(repo, commit, safe_relpath(item["path"], label))
        verify_sha256(data, item["sha256"], label)
        return data, item["path"], {"source_commit": commit}
    data = _read_pinned_file(_plan_path(plan_dir, item["file"]), item["sha256"], label)
    return data, PurePosixPath(item["file"].replace("\\", "/")).name, {}


def cut_script_identity() -> dict:
    """The executing script's hash; a CRLF checkout is refused so the binding cannot drift."""
    data = Path(__file__).read_bytes()
    if b"\r" in data:
        raise CutRefused("the cut script holds CR bytes (CRLF checkout); check it out with LF endings")
    return {"cut_script_sha256": sha256_hex(data), "cut_script_blob": git_blob_id(data)}


def _read_pinned_file(path: Path, expected: str, label: str) -> bytes:
    if not path.is_file():
        raise CutRefused(f"{label}: {path} is missing")
    data = path.read_bytes()
    verify_sha256(data, expected, label)
    return data


def _mo1(table: Sequence[Sub], texts: dict[str, str], skip: str | None) -> dict:
    if skip is None:
        return {"MO1": "not applicable"}
    target = next((s for s in table if s.id == skip), None)
    if target is None:
        raise CutRefused(f"MO1: substitution {skip} is not in the table")
    subs = [s for s in table if s.source == target.source and s.id != skip]
    planted = apply_substitutions(texts[target.source], subs, label=f"MO1 {target.source}")
    hits = section4_hits("MO1", planted)
    if not hits:
        raise CutRefused(f"MO1: skipping {skip} did not make the §4 check fail; the check does not bite")
    return {"MO1_skipped": skip, "MO1_hits": len(hits)}


def _mo2(sample: bytes, pin: str) -> dict:
    try:
        verify_sha256(sample + b"\n", pin, "MO2")
    except CutRefused:
        return {"MO2_refused": True}
    raise CutRefused("MO2: a mutated source passed the hash pin")


def run_cut(plan_file: Path, repo: Path, out_dir: Path, *, table: Sequence[Sub] = V34_TABLE,
            mo1_skip: str | None = "S6", run_drift: bool = True,
            withheld: Sequence[tuple[str, str]] = R4B_WITHHELD,
            expected_outputs: dict[str, str] | None = None) -> tuple[dict, str]:
    """Cut the handout and the filtered tree. Returns (manifest, binding sha256).

    ``expected_outputs`` defaults to ``EXPECTED_OUTPUT_SHA256``; tests pass a synthetic map."""
    expected_outputs = EXPECTED_OUTPUT_SHA256 if expected_outputs is None else expected_outputs
    out_dir = out_dir.resolve()
    repo = repo.resolve()
    if out_dir.exists():
        raise CutRefused(f"{out_dir} exists; the cut writes only to a NEW directory")
    if out_dir == repo or repo in out_dir.parents:
        raise CutRefused("the output directory must be outside the source repository")
    plan_bytes = plan_file.read_bytes()
    plan = json.loads(plan_bytes)
    if plan.get("schema") != PLAN_SCHEMA:
        raise CutRefused(f"plan schema must be {PLAN_SCHEMA}")
    plan_dir = plan_file.resolve().parent
    commit = resolve_commit(repo, plan["build_line_commit"])

    script_identity = cut_script_identity()

    # 1. Every pin is verified before any line is read. Expected outputs first: the plan must carry
    #    the full value for every pinned item, equal to the constant (abbreviations refuse).
    rows = {row["id"]: row for row in [*plan["spec_cuts"], *plan["code_items"]]}
    if set(rows) != set(expected_outputs):
        raise CutRefused(f"plan items {sorted(rows)} != pinned expected-output items {sorted(expected_outputs)}")
    for item_id, pinned in sorted(expected_outputs.items()):
        value = rows[item_id].get("expected_output_sha256")
        if not value:
            raise CutRefused(f"{item_id}: expected_output_sha256 is missing (mandatory)")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise CutRefused(f"{item_id}: expected_output_sha256 must be a full 64-hex SHA-256, got {value!r}")
        if value != pinned:
            raise CutRefused(f"{item_id}: expected_output_sha256 {value} != the pinned {pinned}")
    spec_dir = _plan_path(plan_dir, plan["spec_source_dir"])
    raw_specs: dict[str, bytes] = {}
    for cut in plan["spec_cuts"]:
        raw_specs[cut["source"]] = _read_pinned_file(spec_dir / cut["source"], cut["sha256"], cut["id"])
    sources_in_table = {s.source for s in table}
    missing = sources_in_table - set(raw_specs)
    if missing:
        raise CutRefused(f"plan lacks spec cuts for table sources {sorted(missing)}")
    code_raw: dict[str, bytes] = {}
    for item in plan["code_items"]:
        if not re.fullmatch(r"[0-9a-f]{40}", item.get("blob", "")):
            raise CutRefused(f"{item['id']}: the code-item pin must be a full 40-hex blob id")
        data = read_blob_at(repo, commit, safe_relpath(item["path"], item["id"]))
        if git_blob_id(data) != item["blob"]:
            raise CutRefused(f"{item['id']}: blob id mismatch at {commit[:12]} for {item['path']}")
        code_raw[item["id"]] = data
    text89 = plan["text_89a"]
    data89 = read_blob_at(repo, commit, safe_relpath(text89["path"], text89["id"]))
    verify_sha256(data89, text89["sha256"], text89["id"])
    rulings = plan["rulings_sheet"]
    rulings_data, rulings_source, rulings_extra = _read_pinned_item(rulings, plan_dir, repo, rulings["id"])
    cover = plan.get("cover_prompt")
    if cover:
        cover_data, cover_source, cover_extra = _read_pinned_item(cover, plan_dir, repo, cover["id"])
    else:
        cover_data = (b"# H-12 cover prompt: PLACEHOLDER\n\nThe signed cover prompt is not written yet. A manifest "
                      b"that carries this placeholder is not bindable.\n")
    spec_in_force = plan.get("spec_in_force")
    spec_in_force_row = None
    if spec_in_force:
        sif, sif_source, _ = _read_pinned_item(spec_in_force, plan_dir, repo, "spec_in_force")
        spec_in_force_row = {"name": sif_source, "sha256": sha256_hex(sif)}

    # 2. Apply the §3 table.
    texts: dict[str, str] = {}
    for name, data in raw_specs.items():
        try:
            texts[name] = data.decode("utf-8")
        except UnicodeDecodeError:
            raise CutRefused(f"{name} is not UTF-8") from None
    handout: list[HandoutFile] = []
    for cut in plan["spec_cuts"]:
        subs = [s for s in table if s.source == cut["source"]]
        body = apply_substitutions(texts[cut["source"]], subs, label=cut["id"]).encode("utf-8")
        handout.append(HandoutFile(cut["id"], "spec_cut", safe_relpath(cut["handout_path"], cut["id"]), body,
                                   cut["source"], cut["sha256"], {"substitutions": [s.id for s in subs]}))
    for item in plan["code_items"]:
        data = code_raw[item["id"]]
        handout.append(HandoutFile(item["id"], "code", safe_relpath(item.get("handout_path", item["path"]), item["id"]),
                                   data, item["path"], sha256_hex(data),
                                   {"commit": commit, "blob": git_blob_id(data)}))
    handout.append(HandoutFile(text89["id"], "text_89a", safe_relpath(text89.get("handout_path", text89["path"]),
                               text89["id"]), data89, text89["path"], text89["sha256"], {"commit": commit}))
    handout.append(HandoutFile(rulings["id"], "rulings_sheet",
                               safe_relpath(rulings.get("handout_path", PurePosixPath(rulings_source).name),
                                            rulings["id"]),
                               rulings_data, rulings_source, rulings["sha256"], rulings_extra))
    cover_id = cover["id"] if cover else "H-12"
    cover_path = (cover.get("handout_path", PurePosixPath(cover_source).name) if cover
                  else "H-12-cover-prompt-PLACEHOLDER.md")
    handout.append(HandoutFile(cover_id, "cover_prompt", safe_relpath(cover_path, cover_id), cover_data,
                               cover_source if cover else "placeholder", sha256_hex(cover_data),
                               cover_extra if cover else {"placeholder": True}))
    paths = [h.handout_path for h in handout]
    if len(set(p.lower() for p in paths)) != len(paths):
        raise CutRefused("handout paths are not unique")
    ids = [h.id for h in handout]
    if len(set(ids)) != len(ids):
        raise CutRefused("handout ids are not unique")

    # 3. Expected output hashes: mandatory, full, and equal to the script constant.
    for item_id, expected in sorted(expected_outputs.items()):
        produced = sha256_hex(next(h for h in handout if h.id == item_id).data)
        if not hash_matches(produced, expected):
            raise CutRefused(f"{item_id}: output SHA-256 {produced} != expected {expected}")

    # 4. §4 check on the actual handout tree, MO1/MO2, deny-list drift.
    hits = [hit for h in handout for hit in section4_hits(h.handout_path, _decode(h.data))]
    if hits:
        listing = "\n  ".join(f"{h.path}:{h.line} {h.rule}" for h in hits[:50])
        raise CutRefused(f"§4 check: {len(hits)} hit(s) on the handout tree:\n  {listing}")
    checks: dict = {"section4_hits": 0}
    checks.update(_mo1(table, texts, mo1_skip if any(s.id == mo1_skip for s in table) else None))
    first_cut = plan["spec_cuts"][0]
    checks.update(_mo2(raw_specs[first_cut["source"]], first_cut["sha256"]))
    if run_drift:
        checks["kernel_drift"] = drift_check(read_blob_at(repo, commit, KERNEL_PATH))

    # 5. Filtered tree, standalone repository, R1.
    handout_sources = {item["path"] for item in plan["code_items"]} | {text89["path"]}
    handout_sources |= {row["path"] for row in (rulings, cover or {}, spec_in_force or {}) if "commit" in row}
    files, withheld_records = filtered_files(repo, commit, withheld, handout_sources)
    checks["import_refusal_files"] = 0
    out_dir.mkdir(parents=True)
    try:
        for h in handout:
            target = long_path(out_dir).joinpath(HANDOUT_DIR, *h.handout_path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(h.data)
        tar_bytes = deterministic_tar(files)
        (out_dir / TAR_NAME).write_bytes(tar_bytes)
        snapshot = create_standalone_repo(out_dir / REPO_DIR, files)
        r1 = assert_r1_invariants(out_dir / REPO_DIR)
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "rev": plan.get("rev", "r1"),
            "bindable": cover is not None,
            "build_line_commit": commit,
            **script_identity,
            "plan_sha256": sha256_hex(plan_bytes),
            "spec_in_force": spec_in_force_row,
            "handout_dir": HANDOUT_DIR,
            "handout": [h.record() for h in handout],
            "checks": checks,
            "filtered_tree": {
                "repo_dir": REPO_DIR,
                "branch": BRANCH,
                "commit": snapshot["commit"],
                "tree": snapshot["tree"],
                "files": len(files),
                "tar": TAR_NAME,
                "tar_sha256": sha256_hex(tar_bytes),
                "exclusion_globs": list(EXCLUSION_GLOBS),
                "withheld_r4b": withheld_records,
                "r1": r1,
            },
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        (out_dir / MANIFEST_NAME).write_bytes(manifest_bytes)
    except BaseException:
        remove_tree(out_dir)
        raise
    return manifest, sha256_hex(manifest_bytes)


def run_rebind(manifest_file: Path, repo: Path, new_rev: str) -> tuple[dict, str]:
    """R2: byte-identical re-bind of H-6..H-9 to a new build-line commit."""
    manifest_bytes = manifest_file.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CutRefused(f"manifest schema must be {MANIFEST_SCHEMA}")
    commit = resolve_commit(repo.resolve(), new_rev)
    old_commit = manifest["build_line_commit"]
    ancestry = subprocess.run(["git", "-C", str(repo.resolve()), "merge-base", "--is-ancestor", old_commit, commit],
                              capture_output=True, env=_scrubbed_env(), check=False, timeout=600)
    if ancestry.returncode != 0:
        raise CutRefused(f"re-bind refused: {commit[:12]} does not descend from the cut commit {old_commit[:12]}")
    code = [row for row in manifest["handout"] if row["kind"] == "code"]
    text89 = [row for row in manifest["handout"] if row["kind"] == "text_89a"]
    if len(text89) != 1:
        raise CutRefused("manifest must carry exactly one text_89a (H-10) row")
    if sorted(row["id"] for row in code) != sorted(CODE_IDS):
        raise CutRefused(f"manifest code items are {[r['id'] for r in code]}, expected {list(CODE_IDS)}")
    differences = []
    for row in sorted([*code, *text89], key=lambda r: r["id"]):
        try:
            data = read_blob_at(repo.resolve(), commit, row["source"])
        except CutRefused:
            differences.append(f"{row['id']} {row['source']}: missing at {commit[:12]}")
            continue
        if sha256_hex(data) != row["sha256"]:
            differences.append(f"{row['id']} {row['source']}: sha256 {row['sha256'][:12]} -> {sha256_hex(data)[:12]}, "
                               f"bytes {row['bytes']} -> {len(data)}")
    if differences:
        raise CutRefused("re-bind refused, a re-hand is required:\n  " + "\n  ".join(differences))
    record = {
        "schema": REBIND_SCHEMA,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "old_commit": manifest["build_line_commit"],
        "new_commit": commit,
        "files": [{"id": r["id"], "source": r["source"], "sha256": r["sha256"]}
                  for r in sorted([*code, *text89], key=lambda r: r["id"])],
    }
    record_bytes = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode("utf-8")
    return record, sha256_hex(record_bytes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    cut = sub.add_parser("cut", help="cut the handout and the filtered tree into a NEW directory")
    cut.add_argument("--plan", required=True, type=Path, help="h1_cut_plan_v1 JSON")
    cut.add_argument("--repo", required=True, type=Path, help="git repository holding the build-line commit")
    cut.add_argument("--out", required=True, type=Path, help="new output directory (must not exist)")
    rebind = sub.add_parser("rebind", help="verify H-6..H-9 are byte-identical at a new build-line commit")
    rebind.add_argument("--manifest", required=True, type=Path)
    rebind.add_argument("--repo", required=True, type=Path)
    rebind.add_argument("--commit", required=True)
    rebind.add_argument("--out", type=Path, help="write the re-bind record here (must not exist)")
    args = parser.parse_args(argv)
    try:
        if args.mode == "cut":
            manifest, binding = run_cut(args.plan, args.repo, args.out)
            print(f"handout files: {len(manifest['handout'])}; filtered tree {manifest['filtered_tree']['tree']} "
                  f"({manifest['filtered_tree']['files']} files); commit {manifest['filtered_tree']['commit']}")
            if not manifest["bindable"]:
                print("NOT BINDABLE: the H-12 cover prompt is a placeholder")
            print(f"binding (SHA-256 of {MANIFEST_NAME}): {binding}")
        else:
            record, digest = run_rebind(args.manifest, args.repo, args.commit)
            text = json.dumps(record, sort_keys=True, indent=2) + "\n"
            if args.out:
                if args.out.exists():
                    raise CutRefused(f"{args.out} exists")
                args.out.write_bytes(text.encode("utf-8"))
            sys.stdout.write(text)
            print(f"re-bind record SHA-256: {digest}")
    except CutRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
