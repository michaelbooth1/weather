"""Export whole settlement-ledger rows for the evening-fix Stage 1 transfer (stdlib only, v1).

Scratch tool for the HOST, written for master's review (L16, 2026-11-01). Not in git.

What it does
------------
Reads the per-market settlement ledgers the scorer reads at c32629156:

    <ledger root>/<market_id>/ledger.jsonl
    (settlement_ledger.py:795-796 ledger_path_for_market; root = --ledger-root, else the
     SETTLEMENT_LEDGER_ROOT environment variable, else <repo>/data/settlements:
     settlement_ledger.py:31-32 and 789-792; data_path() = <repo>/data, paths.py:11,22)

and copies, byte-verbatim and in file order, every ledger line whose ``event_slug`` is one of
the window's slugs, into ONE file ``ledger_rows.jsonl``. That is the single file
``evening_fix_scorer --ledger-rows`` expects (evening_fix_scorer.py:638;
evening_fix_transfer.TransferredLedger(path, slugs), evening_fix_transfer.py:194-224).

Slug set (metadata only): the ``event_slug`` values of the ``lockin_anchor_replay --no-market``
JSONL file(s) given with --replay-jsonl. Only that one field is read from each replay row. The
transfer loader refuses any ledger row whose slug has no replay row (evening_fix_transfer.py:210-211),
so the slug set must come from the replay itself. Each slug's target date is parsed from the slug
text (``...-<month>-<day>-<year>``), never from an outcome field.

Refusals (exit 2, nothing written, no row content printed):
- the output directory already exists;
- a replay slug without a parseable date, or dated outside 2026-10-16..2026-10-28;
- a selected ledger row whose ``target_date`` is missing, outside 2026-10-16..2026-10-28, or not the
  date in its slug;
- one slug present in more than one market ledger file (the scorer's history would then differ).

Hash chain: rows are never re-serialised, so ``label_hash`` / ``revision_id`` / supersession links
(settlement_ledger.py:904-961 verify_ledger_history) stay intact. Each slug lives in one market file
and its rows are copied in that file's order. Lines the production reader skips (blank or invalid
JSON, settlement_ledger.py:799-813 read_jsonl) are skipped here too and only counted.

Denver: kept, exactly like every other market. Clarification 1 section 6 (line 63 of
evening-lockin-fix-scoring-clarification-1-2026-10-31.md): "Denver stays in US11 and in the primary
as signed. A Denver-excluded sensitivity ... is reported beside the primary. It decides nothing."
The scorer computes that sensitivity itself (evening_fix_scorer.py:518-523), so the transfer must
carry Denver's whole rows. Whatever label rule Denver's rows carry (KDEN since 10-23) is the
ledger's own latest revision; this tool does not choose or alter it.

Outputs, in --out-dir (created atomically by renaming a temporary sibling directory):
    ledger_rows.jsonl  SHA256SUMS  receipt.json
The receipt holds counts per date and per market, input paths and sha256, the script sha256 and the
time. It holds no row content. stdout/stderr carry counts and sha256 values only.

Usage (host):
    python export_ledger_rows_v1.py --repo-root C:\\Users\\micha\\Desktop\\github\\weather
        --replay-jsonl <replay.jsonl> [--replay-jsonl <more.jsonl> ...]
        --out-dir C:\\xfer\\evening-fix-20261102
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = "evening_fix_ledger_rows_export_v1"
WINDOW_START = date(2026, 10, 16)
WINDOW_END = date(2026, 10, 28)      # Clarification 1 section 2: 10-28 is the only extension date
LEDGER_ROOT_ENV = "SETTLEMENT_LEDGER_ROOT"
LEDGER_FILENAME = "ledger.jsonl"
OUT_ROWS = "ledger_rows.jsonl"
OUT_RECEIPT = "receipt.json"
OUT_SUMS = "SHA256SUMS"
MONTHS = {name: number for number, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"), 1)}
SLUG_DATE = re.compile(r"-([a-z]+)-(\d{1,2})-(\d{4})$")
DENVER_NOTE = (
    "Denver kept as every other market (Clarification 1 sec. 6, line 63: Denver stays in US11 and the "
    "primary; the Denver-excluded sensitivity is computed by the scorer, evening_fix_scorer.py:518-523)."
)


class Refused(Exception):
    """A contract breach: exit 2, write nothing."""


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slug_date(slug):
    match = SLUG_DATE.search(str(slug).lower())
    if not match or match.group(1) not in MONTHS:
        return None
    try:
        return date(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2)))
    except ValueError:
        return None


def in_window(day):
    return day is not None and WINDOW_START <= day <= WINDOW_END


def resolve_ledger_root(args):
    if args.ledger_root:
        return Path(args.ledger_root), "--ledger-root"
    if os.environ.get(LEDGER_ROOT_ENV):
        return Path(os.environ[LEDGER_ROOT_ENV]), f"env {LEDGER_ROOT_ENV}"
    if not args.repo_root:
        raise Refused("refused: give --repo-root or --ledger-root")
    return Path(args.repo_root) / "data" / "settlements", "--repo-root/data/settlements"


def window_slugs(replay_paths):
    """slug -> target date, from the replay rows' event_slug field only."""
    slugs = {}
    inputs = []
    for raw in replay_paths:
        path = Path(raw)
        if not path.is_file():
            raise Refused(f"refused: replay file not found: {path}")
        rows = 0
        with path.open("rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rows += 1
                slug = json.loads(line.decode("utf-8")).get("event_slug")
                if not slug:
                    raise Refused(f"refused: replay row {rows} of {path.name} has no event_slug")
                day = slug_date(slug)
                if not in_window(day):
                    raise Refused(
                        f"refused: a replay slug in {path.name} (row {rows}) is dated {day}, outside "
                        f"{WINDOW_START}..{WINDOW_END}"
                    )
                slugs[slug] = day
        inputs.append({"path": str(path.resolve()), "sha256": sha256_file(path),
                       "bytes": path.stat().st_size, "rows": rows})
    if not slugs:
        raise Refused("refused: the replay file(s) name no slug")
    return slugs, inputs


def split_lines(data):
    """Raw lines without their trailing newline; a final unterminated line is kept."""
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def select_rows(ledger_root, slugs):
    if not ledger_root.is_dir():
        raise Refused(f"refused: ledger root is not a directory: {ledger_root}")
    files = sorted(ledger_root.glob(f"*/{LEDGER_FILENAME}"))
    if not files:
        raise Refused(f"refused: no */{LEDGER_FILENAME} under {ledger_root}")
    selected = []                  # raw line bytes, in file order
    per_date, per_market = Counter(), Counter()
    slug_market = {}
    inputs = []
    skipped_unparseable = 0
    for path in files:
        data = path.read_bytes()
        inputs.append({"path": str(path.resolve()), "sha256": sha256_bytes(data), "bytes": len(data)})
        market = path.parent.name
        for number, raw in enumerate(split_lines(data), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                skipped_unparseable += 1   # read_jsonl skips these too
                continue
            if not isinstance(row, dict):
                skipped_unparseable += 1
                continue
            slug = row.get("event_slug")
            if slug not in slugs:
                continue
            where = f"{market}/{LEDGER_FILENAME} line {number}"
            if slug_market.setdefault(slug, market) != market:
                raise Refused(f"refused: one slug appears in two market ledgers ({slug_market[slug]}, {market})")
            target_raw = row.get("target_date")
            try:
                target = date.fromisoformat(str(target_raw)[:10]) if target_raw else None
            except ValueError:
                target = None
            if not in_window(target):
                raise Refused(f"refused: {where} targets {target}, outside {WINDOW_START}..{WINDOW_END}")
            if target != slugs[slug]:
                raise Refused(f"refused: {where} target_date {target} differs from its slug date {slugs[slug]}")
            selected.append(raw)
            per_date[target.isoformat()] += 1
            per_market[market] += 1
    return selected, per_date, per_market, slug_market, inputs, skipped_unparseable


def write_synced(path, data):
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def write_atomically(out_dir, rows_bytes, receipt):
    parent = out_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{out_dir.name}.tmp-{os.getpid()}"
    if tmp.exists():
        raise Refused(f"refused: temporary directory exists: {tmp}")
    tmp.mkdir()
    try:
        write_synced(tmp / OUT_ROWS, rows_bytes)
        rows_sha = sha256_bytes(rows_bytes)
        receipt["output"] = {"file": OUT_ROWS, "sha256": rows_sha, "bytes": len(rows_bytes)}
        receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        write_synced(tmp / OUT_RECEIPT, receipt_bytes)
        sums = f"{rows_sha}  {OUT_ROWS}\n{sha256_bytes(receipt_bytes)}  {OUT_RECEIPT}\n"
        write_synced(tmp / OUT_SUMS, sums.encode("ascii"))
        if out_dir.exists():
            raise Refused(f"refused: output directory appeared meanwhile: {out_dir}")
        os.rename(tmp, out_dir)   # same parent: atomic; never replaces an existing directory
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return rows_sha, sha256_bytes(receipt_bytes)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export window settlement-ledger rows (no row content printed).")
    parser.add_argument("--replay-jsonl", action="append", required=True,
                        help="lockin_anchor_replay --no-market JSONL; only event_slug is read. Repeatable.")
    parser.add_argument("--out-dir", required=True, help="New directory (refused if it exists).")
    parser.add_argument("--repo-root", default=None, help="Repository root; ledger root = <repo>/data/settlements.")
    parser.add_argument("--ledger-root", default=None, help="Explicit ledger root (overrides env and --repo-root).")
    args = parser.parse_args(argv)
    try:
        out_dir = Path(args.out_dir).resolve()
        if out_dir.exists():
            raise Refused(f"refused: output directory exists: {out_dir}")
        ledger_root, root_source = resolve_ledger_root(args)
        slugs, replay_inputs = window_slugs(args.replay_jsonl)
        selected, per_date, per_market, slug_market, ledger_inputs, skipped = select_rows(ledger_root, slugs)
        rows_bytes = b"".join(raw + b"\n" for raw in selected)
        receipt = {
            "schema": SCHEMA,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "script": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(__file__)},
            "python": sys.version.split()[0],
            "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
            "ledger_root": str(ledger_root.resolve()),
            "ledger_root_source": root_source,
            "ledger_inputs": ledger_inputs,
            "replay_inputs": replay_inputs,
            "counts": {
                "replay_slugs": len(slugs),
                "slugs_with_ledger_rows": len(slug_market),
                "slugs_without_ledger_rows": len(slugs) - len(slug_market),
                "rows_exported": len(selected),
                "rows_per_date": dict(sorted(per_date.items())),
                "rows_per_market": dict(sorted(per_market.items())),
                "unparseable_ledger_lines_skipped": skipped,
            },
            "denver": DENVER_NOTE,
            "row_content_in_receipt": False,
        }
        rows_sha, receipt_sha = write_atomically(out_dir, rows_bytes, receipt)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({
        "out_dir": str(out_dir),
        "rows_exported": len(selected),
        "replay_slugs": len(slugs),
        "slugs_with_ledger_rows": len(slug_market),
        "rows_per_date": dict(sorted(per_date.items())),
        "ledger_rows_sha256": rows_sha,
        "receipt_sha256": receipt_sha,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
