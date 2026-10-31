"""Row 80 release layout builder: a HARNESS v3 layout for the released targets 2026-10-01..2026-10-14 only.

Research tool (lane L8, 2026-10-31), not a production dependency. It exists because the HARNESS v3 builder
(branch ``claude/harness-v3-20261019``) refuses every target after 2026-09-29, the row 80 driver ``rep.py``
is frozen, and the B-bound dev scorecard files may not be edited. Runbook:
``docs/research/iterate-faster-2026-10-30/row80-look-runbook.md`` section 3 (branch
``claude/embargo-release-export-manifest-20261031``).

What it does, in order, and nothing else:

1. Refuses unless the harness worktree is a clean checkout of ``HARNESS_PIN``, ``harness_sha256()`` equals the
   rule's ``EXPECTED_HARNESS_SHA256`` and ``PARSER_HEAD`` is the pinned NBM parser head.
2. Refuses unless every path is free of ``88a``/``panel``, no output path is under ``C:\\swarm``, and ``--out``
   is new or empty.
3. ``harness.verify_extract`` (SHA256SUMS, manifest ``COMPLETE`` at the pinned parser head).
4. Scope check on the verified extract: every row's target is inside 10-01..10-14, every market is one of the
   eleven US markets in degrees F, and no Austin 10-03 row (the staging reader drops it; this re-checks).
   The boundary is the LOCAL TARGET DATE (master's ruling, 2026-10-31): a target of 10-14 or earlier is
   released whatever its capture time, including a 10-14 label recorded on UTC 10-15; a target of 10-15 or
   later is refused whatever its capture time (C5).
5. In-process only, for the duration of the build: ``harness.LAST_TARGET_DATE`` and
   ``v3_outcomes.DEV_LAST_DATE`` are set to ``RELEASE_LAST`` and restored afterwards. No file is edited.
6. ``harness.build_cache(extract, <out>/cache)`` (fresh cache, never ``force``), then
   ``v3_outcomes.split_v2_cache(<out>/layout, cache=<out>/cache)``.
7. Asserts the layout manifest's ``source.harness_sha256`` and that every file's dates are inside the window,
   then writes ``<out>/layout_receipt.json``.

It computes no score, Brier value, ratio or label-versus-forecast comparison. The layout holds labels and
market prices (as every v3 layout does); the first read of them is the row 80 look.

Run it as a script with an isolated interpreter, never with ``-m`` from a repository root: the harness code
is imported from the pinned worktree as ``tools.research.model_parity``, and a ``tools`` package already
imported from another tree is refused::

    python -I tools/research/released_window/r80_layout.py --harness-worktree <clean 2f3f3e8e worktree> \
        --extract <guidance extract dir> --out <new empty dir>
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "r80_release_layout_receipt/1"
HARNESS_PIN = "2f3f3e8e6b542a419204afe802dae4545abc10d7"
EXPECTED_HARNESS_SHA256 = "8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74"
PARSER_HEAD = "2e17ce0eb"
RELEASE_FIRST = "2026-10-01"
RELEASE_LAST = "2026-10-14"
EMBARGO_FIRST_TARGET = "2026-10-15"
US11 = frozenset({"nyc", "atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami",
                  "san-francisco", "seattle"})
EXCLUDED_MARKET_DAYS = frozenset({("austin", "2026-10-03")})
FORBIDDEN_PATH = re.compile(r"88a|panel", re.IGNORECASE)
SWARM_ROOT = Path(r"C:\swarm")
EXTRACT_FILES = ("guidance_rows.jsonl.gz", "market_days.jsonl.gz")


class Refused(RuntimeError):
    """A guard refused; nothing after it ran."""


# ----------------------------------------------------------------------------- path guards

def screen_path(path, label):
    if FORBIDDEN_PATH.search(str(path)):
        raise Refused(f"refused: {label} path {path} names 88a or panel data")
    return Path(path)


def _under(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def check_out_dir(out, swarm_root=SWARM_ROOT):
    """``out`` must be new or an empty directory, outside C:\\swarm, and free of 88a/panel."""
    out = screen_path(out, "--out")
    if _under(out, swarm_root):
        raise Refused(f"refused: --out {out} is under {swarm_root} (the dev cache and layouts are never written)")
    if out.exists():
        if not out.is_dir():
            raise Refused(f"refused: --out {out} exists and is not a directory")
        if any(out.iterdir()):
            raise Refused(f"refused: --out {out} is not empty")
    return out


# ----------------------------------------------------------------------------- harness loading

def _git(worktree, *args, runner=subprocess.run):
    done = runner(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Refused(f"refused: git {' '.join(args)} failed in {worktree}: {done.stderr.strip()}")
    return done.stdout.strip()


def check_worktree(worktree, runner=subprocess.run):
    """The harness worktree is a clean checkout of HARNESS_PIN (tracked files)."""
    head = _git(worktree, "rev-parse", "HEAD", runner=runner)
    if head != HARNESS_PIN:
        raise Refused(f"refused: harness worktree HEAD {head} != {HARNESS_PIN}")
    dirty = _git(worktree, "status", "--porcelain", "--untracked-files=no", runner=runner)
    if dirty:
        raise Refused("refused: harness worktree has tracked changes")
    return head


def load_harness(worktree, modules=None):
    """Import harness and v3_outcomes from ``worktree`` only."""
    modules = sys.modules if modules is None else modules
    if "tools" in modules:
        raise Refused("refused: a 'tools' package is already imported; run this file with python -I, not -m")
    worktree = Path(worktree).resolve()
    sys.path.insert(0, str(worktree))
    harness = importlib.import_module("tools.research.model_parity.harness")
    outcomes = importlib.import_module("tools.research.model_parity.v3_outcomes")
    for module in (harness, outcomes):
        if not _under(module.__file__, worktree):
            raise Refused(f"refused: {module.__name__} resolved outside the harness worktree ({module.__file__})")
    return harness, outcomes


def check_harness(harness):
    sha = harness.harness_sha256()
    if sha != EXPECTED_HARNESS_SHA256:
        raise Refused(f"refused: harness_sha256 {sha} != the rule's {EXPECTED_HARNESS_SHA256}")
    if harness.PARSER_HEAD != PARSER_HEAD:
        raise Refused(f"refused: harness PARSER_HEAD {harness.PARSER_HEAD!r} != {PARSER_HEAD!r}")
    return sha


# ----------------------------------------------------------------------------- extract scope

def _row_scope_errors(row, kind):
    target, market = str(row.get("target_date")), str(row.get("market"))
    errors = []
    if target >= EMBARGO_FIRST_TARGET:
        errors.append(f"{kind} target {target} is embargoed (local target 10-15 or later, whatever its capture time)")
    elif not RELEASE_FIRST <= target <= RELEASE_LAST:
        errors.append(f"{kind} target {target} outside {RELEASE_FIRST}..{RELEASE_LAST}")
    if market not in US11:
        errors.append(f"{kind} market {market!r} is not one of the eleven US markets")
    if (market, target) in EXCLUDED_MARKET_DAYS:
        errors.append(f"{kind} holds excluded market-day {market} {target}")
    if kind == "guidance_rows" and row.get("unit") != "F":
        errors.append(f"guidance_rows unit {row.get('unit')!r} is not F")
    return errors


def check_extract_scope(extract):
    """Read only the scope fields of the verified extract; refuse on the first out-of-scope row."""
    counts = {}
    for name in EXTRACT_FILES:
        kind = name.split(".")[0]
        n = 0
        with gzip.open(Path(extract) / name, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                errors = _row_scope_errors(json.loads(line), kind)
                if errors:
                    raise Refused(f"refused: {errors[0]} (line {n + 1} of {name})")
                n += 1
        counts[kind] = n
    if not counts.get("guidance_rows"):
        raise Refused("refused: the extract holds no guidance rows")
    return counts


# ----------------------------------------------------------------------------- build

@contextlib.contextmanager
def release_overrides(harness, outcomes, last=RELEASE_LAST):
    """Set the two dev date bounds to ``last`` in-process only; restore them on exit."""
    saved = (harness.LAST_TARGET_DATE, outcomes.DEV_LAST_DATE)
    harness.LAST_TARGET_DATE = last
    outcomes.DEV_LAST_DATE = last
    try:
        yield {"harness.LAST_TARGET_DATE": [saved[0], last], "v3_outcomes.DEV_LAST_DATE": [saved[1], last]}
    finally:
        harness.LAST_TARGET_DATE, outcomes.DEV_LAST_DATE = saved


def check_layout_manifest(manifest):
    source_sha = (manifest.get("source") or {}).get("harness_sha256")
    if source_sha != EXPECTED_HARNESS_SHA256:
        raise Refused(f"refused: layout source.harness_sha256 {source_sha} != {EXPECTED_HARNESS_SHA256}")
    for name, entry in manifest.get("files", {}).items():
        dates = entry.get("dates") or []
        if not dates:
            raise Refused(f"refused: layout file {name} declares no dates")
        embargoed = [d for d in dates if str(d) >= EMBARGO_FIRST_TARGET]
        if embargoed:
            raise Refused(f"refused: layout file {name} declares embargoed target {embargoed[0]} (10-15 or later)")
        outside = [d for d in dates if not RELEASE_FIRST <= str(d) <= RELEASE_LAST]
        if outside:
            raise Refused(f"refused: layout file {name} declares dates outside the window (first {outside[0]})")


def _sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(extract, out, harness, outcomes, worktree_head=None, swarm_root=SWARM_ROOT):
    """Steps 2-7 of the module docstring; ``harness``/``outcomes`` are already loaded and checked."""
    extract = screen_path(extract, "--extract")
    out = check_out_dir(out, swarm_root)
    harness_sha = check_harness(harness)
    verified = harness.verify_extract(extract)
    scope = check_extract_scope(extract)
    cache, layout = out / "cache", out / "layout"
    with release_overrides(harness, outcomes) as overrides:
        cache_receipt = harness.build_cache(root=extract, cache=cache)
        manifest = outcomes.split_v2_cache(layout, cache=cache)
    check_layout_manifest(manifest)
    manifest_path = layout / "manifest.json"
    receipt = {
        "schema": SCHEMA, "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "row 80 (RISE-T3R3 replication) release layout, targets 2026-10-01..2026-10-14; no score",
        "harness_pin": HARNESS_PIN, "harness_worktree_head": worktree_head, "harness_sha256": harness_sha,
        "module_sha256": _sha_file(__file__), "extract": {"path": str(extract), "verified": verified,
                                                        "scope_rows": scope},
        "overrides_in_process": overrides, "cache_dir": str(cache),
        "cache_receipt_sha256": _sha_file(cache / "cache_receipt.json"),
        "cache_after_window_rows": cache_receipt.get("rows_with_target_after_2026_09_29"),
        "layout_dir": str(layout), "layout_manifest_sha256": _sha_file(manifest_path),
        "layout_dates": sorted({d for e in manifest["files"].values() for d in e["dates"]}),
        "excluded_market_days": sorted(list(k) for k in EXCLUDED_MARKET_DAYS),
    }
    (out / "layout_receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    return receipt


def build_parser():
    parser = argparse.ArgumentParser(description="Row 80 release layout (targets 2026-10-01..2026-10-14); no score.")
    parser.add_argument("--harness-worktree", required=True, help=f"clean worktree at {HARNESS_PIN}")
    parser.add_argument("--extract", required=True, help="guidance extract dir (SHA256SUMS, manifest COMPLETE)")
    parser.add_argument("--out", required=True, help="new or empty output dir (cache/, layout/, receipt)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for path, label in ((args.harness_worktree, "--harness-worktree"), (args.extract, "--extract")):
            screen_path(path, label)
        check_out_dir(args.out)
        head = check_worktree(args.harness_worktree)
        harness, outcomes = load_harness(args.harness_worktree)
        receipt = build(args.extract, args.out, harness, outcomes, worktree_head=head)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"layout_manifest_sha256": receipt["layout_manifest_sha256"],
                      "receipt": str(Path(args.out) / "layout_receipt.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
