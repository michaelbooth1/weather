"""Pre-read guard for the C2/C3 released-window export (defense in depth; lane L8, 2026-10-31).

Research tool, not a production dependency. Master ruled on 2026-10-31 that it be built. It runs over the staged
export data root BEFORE either C2 (``fill_toxicity_desk_study``) or C3 (``maker_fair_value_score`` via the plugin
capture bundle) reads it. Neither reader has a date gate of its own, and neither goes through
``MakerEvidencePanel``. The guard edits nothing: not ``export_gate``, not the maker panel or embargo code, and not
the readers.

It refuses, by LOCAL TARGET DATE / UTC capture day (master's rulings, 2026-10-31):

1. Any ``maker_evidence/<day>/`` with ``day`` >= 2026-10-15 (C5), and any entry there that is not a
   ``YYYY-MM-DD`` directory.
2. Any ``snapshots/<slug>/`` folder whose target is 2026-10-15 or later (C5), or whose market-day is Austin
   2026-10-03 (C7). A directory that is not a registered market's event slug is refused too.
3. Any ``settlements/<market>/ledger.jsonl`` row whose event slug or target is 2026-10-15 or later, or is Austin
   2026-10-03. Only the scope fields (``event_slug``, ``market_id``, ``target_date``) are used. The row is held
   in memory only for the length of the check, and no label field is written, printed or compared.

It does NOT open sealed 88a segments. Master ruled option (a): segments are exported whole and the C2/C3 readers
drop the Austin 10-03 event themselves. So a multi-market segment that carries Austin 10-03 records passes this
guard by design. Its file listing only is checked.

Exit 0 and a JSON summary on stdout when nothing is refused; exit 2 and the first refusal on stderr otherwise. It
writes nothing unless ``--receipt`` names a new file outside the data root.

    python -m tools.research.released_window.c23_preread_guard --data-root C:\\t\\c23\\data [--receipt <new file>]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug

SCHEMA = "c23_preread_guard_receipt/1"
EMBARGO_FIRST = date(2026, 10, 15)
EXCLUDED_MARKET_DAYS = frozenset({("austin", date(2026, 10, 3))})
DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEDGER_NAMES = ("ledger.jsonl", "ledger.jsonl.gz")


class Refused(RuntimeError):
    """A guard refused; the export must not be read by C2 or C3."""


def _parse_day(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _market_day_errors(market, target, where):
    errors = []
    if target >= EMBARGO_FIRST:
        errors.append(f"{where}: target {target.isoformat()} is embargoed (10-15 or later, C5)")
    if (market, target) in EXCLUDED_MARKET_DAYS:
        errors.append(f"{where}: excluded market-day {market} {target.isoformat()} (C7)")
    return errors


def check_maker_evidence(data_root):
    """Every child of maker_evidence/ is a UTC-day directory before 2026-10-15."""
    root = Path(data_root) / "maker_evidence"
    days, segments = [], 0
    if not root.exists():
        return {"days": days, "segments": segments}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not DAY_NAME.match(entry.name) or _parse_day(entry.name) is None:
            raise Refused(f"refused: maker_evidence entry {entry.name!r} is not a YYYY-MM-DD day directory")
        day = _parse_day(entry.name)
        if day >= EMBARGO_FIRST:
            raise Refused(f"refused: maker_evidence/{entry.name} is embargoed (UTC day 10-15 or later, C5)")
        days.append(entry.name)
        segments += sum(1 for child in entry.iterdir() if child.is_dir())
    return {"days": days, "segments": segments}


def check_slug_folders(data_root):
    """Every snapshots/<dir> is a registered event slug whose market-day is released."""
    root = Path(data_root) / "snapshots"
    folders = 0
    if not root.exists():
        return {"slug_folders": folders}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        spec, target = spec_for_slug(entry.name), date_from_event_slug(entry.name)
        if spec is None or target is None:
            raise Refused(f"refused: snapshots/{entry.name} is not a registered market's event slug")
        errors = _market_day_errors(spec.id, target, f"snapshots/{entry.name}")
        if errors:
            raise Refused(f"refused: {errors[0]}")
        folders += 1
    return {"slug_folders": folders}


def _open_ledger(path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _row_market_day(row, market_dir):
    slug = row.get("event_slug")
    if slug:
        spec, target = spec_for_slug(slug), date_from_event_slug(slug)
        if spec is None or target is None:
            return None, None
        return spec.id, target
    target = _parse_day(row.get("target_date"))
    return str(row.get("market_id") or market_dir), target


def check_ledgers(data_root):
    """Every ledger row's market-day (scope fields only) is released."""
    root = Path(data_root) / "settlements"
    rows = 0
    if not root.exists():
        return {"ledger_rows": rows}
    for market_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for name in LEDGER_NAMES:
            path = market_dir / name
            if not path.is_file():
                continue
            with _open_ledger(path) as stream:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    where = f"settlements/{market_dir.name}/{name} line {number}"
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        raise Refused(f"refused: {where} is not valid JSON") from None
                    market, target = _row_market_day(row, market_dir.name)
                    if target is None:
                        raise Refused(f"refused: {where} has no parseable event slug or target date")
                    errors = _market_day_errors(market, target, where)
                    if errors:
                        raise Refused(f"refused: {errors[0]}")
                    rows += 1
    return {"ledger_rows": rows}


def _under(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def run(data_root):
    data_root = Path(data_root)
    if not data_root.is_dir():
        raise Refused(f"refused: --data-root {data_root} is not a directory")
    summary = {"schema": SCHEMA, "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "data_root": str(data_root), "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "embargo_first": EMBARGO_FIRST.isoformat(),
               "excluded_market_days": sorted([m, d.isoformat()] for m, d in EXCLUDED_MARKET_DAYS),
               "sealed_segments_opened": False}
    summary.update(check_maker_evidence(data_root))
    summary.update(check_slug_folders(data_root))
    summary.update(check_ledgers(data_root))
    summary["verdict"] = "PASS"
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="C2/C3 pre-read guard over a staged export (refuses 10-15+ and "
                                                 "Austin 10-03).")
    parser.add_argument("--data-root", required=True, help="staged export data root")
    parser.add_argument("--receipt", default=None, help="optional new file, outside the data root")
    args = parser.parse_args(argv)
    try:
        if args.receipt is not None:
            receipt = Path(args.receipt)
            if receipt.exists():
                raise Refused(f"refused: --receipt {receipt} already exists")
            if _under(receipt, args.data_root):
                raise Refused(f"refused: --receipt {receipt} is inside the data root")
        summary = run(args.data_root)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = json.dumps(summary, indent=1, sort_keys=True)
    if args.receipt is not None:
        Path(args.receipt).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
