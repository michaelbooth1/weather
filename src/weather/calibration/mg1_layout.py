r"""MG-1 input layout, workstation side: verified bundles to one label-free layout for D0..MG1_LAST.

R11 Head 1 (master rulings 2026-11-01). Research only. MG-1's look reads its inputs from one window layout made
of the same per-date pieces the MG-2 transfer uses (``weather.calibration.mg2_inputs``: ``verify_bundle``,
``build``, ``concat``). Those pieces are used unchanged. This module adds only what MG-1 needs:

* **Two sources, one per date range.** Dates before MG-2's D0 (2026-10-15..2026-10-27) come from the host
  backfill (a tools-side wrapper that runs the unchanged MG-2 exporter on those dates), staged on the share.
  Dates from 2026-10-28 come from B's existing MG-2 bundles, already verified in the MG-2 inbox (``<mg2-inbox>\<D>\verified``). Those bundles
  are re-verified IN PLACE and never moved, written or receipted in the MG-2 ledger.
* **Verification without the deadline.** The MG-2 receiver's deadline (23:59 on D+1) is a forward-transfer rule.
  A backfill bundle is days late by design, so this module runs every section 9.3 check (``verify_bundle``) and
  skips only the deadline. A backfill bundle must also carry its sidecar receipt
  (``<D>.mg1_backfill_receipt.json``), and that receipt must name the same manifest sha256, coverage counts off
  and the exporter sha recorded in the manifest.
* **Its own ledger.** One append-only line per outcome, in MG-1's own receipts ledger (default
  ``C:\t\mg1\inputs\input_receipts.jsonl``), never the MG-2 one. ``concat`` requires a ``verified`` line there
  for every date, for the same bundle manifest.
* **Window.** ``concat`` takes exactly the dates ``mg1_reserved_window.window()`` gives (D0..MG1_LAST,
  inclusive), refuses an open-ended window, and refuses a date with no layout. Non-countable market-days stay
  in the layout. The MG-1 scoring head drops them before its join (R11 item 2).
* **No evening-fix transfer.** It never reads the evening-fix (B transfer) export: a source or inbox path that
  holds ``b_transfer_manifest.json``, ``labels.parquet`` or ``market.parquet`` is refused, and only allow-listed
  bundle files pass ``verify_bundle``.
* **The share root is a parameter.** Master picks it (it follows the R20 host-name switch). Nothing here
  names a host address.

Commands (``python -m weather.calibration.mg1_layout``):

    stage   --share-root S --inbox I --date D [--ledger L]   copy <S>\<D>\ and its sidecar receipt (backfill dates)
    admit   --inbox I --date D [--mg2-inbox M] [--ledger L]  verify (no deadline) and record in MG-1's ledger
    build   --inbox I --date D --layouts O --parser-worktree W [--mg2-inbox M] [--parser-python P]
    concat  --layouts O --out W [--ledger L]                  one window layout for D0..MG1_LAST
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather import mg1_reserved_window as window
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_inputs as mi  # refuses on the capture host

LEDGER = Path(r"C:\t\mg1\inputs\input_receipts.jsonl")
RECEIPT_SCHEMA = "mg1_layout_receipt/1"
WINDOW_RECEIPT = "mg1_layout_window.json"
# The host backfill's contract (master 2026-11-01, option d: nothing under src/ imports the tools-side wrapper,
# so its constants are restated here and pinned equal to it by tests/calibration/test_mg1_layout.py).
BACKFILL_FIRST = date(2026, 10, 15)
BACKFILL_LAST = date(2026, 10, 27)
BACKFILL_RECEIPT_SCHEMA = "mg1_backfill_receipt/1"
BACKFILL_RECEIPT_SUFFIX = ".mg1_backfill_receipt.json"  # <share>/<D>.mg1_backfill_receipt.json beside the bundle
SIDECAR = "mg1_backfill_receipt.json"  # copied to <inbox>/<D>/mg1_backfill_receipt.json beside verified/
# Files of the evening-fix B transfer (b_scorer.TRANSFER_MANIFEST / TRANSFER_FILES); pinned equal by a test.
TRANSFER_NAMES = ("b_transfer_manifest.json", "labels.parquet", "market.parquet")


class LayoutRefused(RuntimeError):
    """The MG-1 layout step refused; nothing is moved, built or recorded beyond what the message says."""


def source_kind(day):
    """``backfill`` for 2026-10-15..2026-10-27, ``mg2`` from MG-2's D0 (2026-10-28) on."""
    if BACKFILL_FIRST <= day <= BACKFILL_LAST:
        return "backfill"
    start, _last = window.window()
    if day > BACKFILL_LAST and day >= start:
        return "mg2"
    raise LayoutRefused(f"{day} is before MG-1's D0 {BACKFILL_FIRST}")


def _refuse_transfer(*paths):
    for path in paths:
        path = Path(path)
        for here in (path, path.parent):
            for name in TRANSFER_NAMES:
                if os.path.lexists(here / name):
                    raise LayoutRefused(f"{here} holds {name}: the evening-fix transfer is never read here")


def read_ledger(ledger=LEDGER, day=None):
    return mi.read_ledger(ledger, day)


def append_receipt(ledger, receipt):
    """Append one MG-1 receipt line (``mg1_layout_receipt/1``); the ledger is never rewritten."""
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**receipt, "schema": RECEIPT_SCHEMA}, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return {**receipt, "schema": RECEIPT_SCHEMA}


def _verified_row(ledger, day):
    for row in read_ledger(ledger, day):
        if row.get("status") == "verified":
            return row
    return None


# ----------------------------------------------------------------------------- stage (backfill dates)

def stage(*, share_root, inbox, day, ledger=LEDGER):
    """Copy ``<share_root>\\<D>\\`` (read-only) and its sidecar receipt into ``<inbox>\\<D>\\``."""
    if source_kind(day) != "backfill":
        raise LayoutRefused(f"{day} is an MG-2 date: its bundle is B's verified one, not a staged backfill")
    _refuse_transfer(Path(share_root) / day.isoformat(), Path(inbox) / day.isoformat())
    sidecar = Path(share_root) / f"{day.isoformat()}{BACKFILL_RECEIPT_SUFFIX}"
    result = mi.pull(share_root=share_root, day=day, inbox=inbox, ledger=ledger)
    if result.get("status") == "pulled":
        if not sidecar.is_file():
            raise LayoutRefused(f"{sidecar} is missing: a backfill bundle travels with its receipt")
        shutil.copyfile(sidecar, Path(inbox) / day.isoformat() / SIDECAR)
    return result


# ----------------------------------------------------------------------------- admit (verify, no deadline)

def _sidecar_problems(base, manifest, manifest_sha):
    path = Path(base) / SIDECAR
    if not path.is_file():
        return ["backfill_receipt_missing"]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["backfill_receipt_unreadable"]
    problems = []
    if receipt.get("schema") != BACKFILL_RECEIPT_SCHEMA:
        problems.append("backfill_receipt_schema")
    if receipt.get("manifest_sha256") != manifest_sha:
        problems.append("backfill_receipt_manifest_sha256")
    if receipt.get("coverage_counts") is not False or (manifest or {}).get("coverage_counts") is not False:
        problems.append("coverage_counts_not_false")
    if (receipt.get("exporter") or {}).get("sha256") != (manifest or {}).get("exporter_sha256"):
        problems.append("backfill_receipt_exporter_sha256")
    if receipt.get("target_date") != (manifest or {}).get("target_date"):
        problems.append("backfill_receipt_target_date")
    return problems


def bundle_dir(*, inbox, day, mg2_inbox=None):
    """The verified bundle directory MG-1 builds from for ``day``."""
    if source_kind(day) == "backfill":
        return Path(inbox) / day.isoformat() / "verified"
    if mg2_inbox is None:
        raise LayoutRefused(f"{day} is an MG-2 date: pass --mg2-inbox (B's verified bundles)")
    return Path(mg2_inbox) / day.isoformat() / "verified"


def admit(*, inbox, day, ledger=LEDGER, mg2_inbox=None, now=None):
    """Every section 9.3 check except the deadline; record the outcome in MG-1's own ledger.

    A backfill bundle moves from ``<inbox>\\<D>\\incoming`` to ``verified`` (or ``_refused``). B's MG-2 bundle
    is checked in place and never moved or written.
    """
    kind = source_kind(day)
    done = _verified_row(ledger, day)
    if done:
        return {"status": "already_recorded", "receipt": done}
    now = (now or datetime.now(timezone.utc)).isoformat()
    base = Path(inbox) / day.isoformat()
    if kind == "backfill":
        source = base / "incoming"
    else:
        source = bundle_dir(inbox=inbox, day=day, mg2_inbox=mg2_inbox)
    _refuse_transfer(source)
    if not (source / allow.MANIFEST_SHA).is_file():
        return {"status": "not_ready", "target_date": day.isoformat(), "source": kind}
    checks, manifest, manifest_sha = mi.verify_bundle(source, day)
    if kind == "backfill":
        checks["backfill_receipt"] = _sidecar_problems(base, manifest, manifest_sha)
    failed = [k for k, v in checks.items() if v]
    summary = {k: {"pass": not v, "problems": v[:50], "problem_count": len(v)} for k, v in checks.items()}
    receipt = {"target_date": day.isoformat(), "recorded_at": now, "source": kind, "deadline_checked": False,
               "allowlist_sha256": allow.allowlist_sha256(), "manifest_sha256": manifest_sha, "checks": summary}
    if not failed:
        if kind == "backfill":
            os.replace(source, base / "verified")
            source = base / "verified"
        return append_receipt(ledger, {**receipt, "status": "verified", "reason": None, "path": str(source)})
    path = str(source)
    if kind == "backfill":
        attempt = 1 + sum(1 for r in read_ledger(ledger, day) if str(r.get("status", "")).startswith("refused"))
        target = Path(inbox) / "_refused" / day.isoformat() / f"attempt-{attempt}"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        path = str(target)
    return append_receipt(ledger, {**receipt, "status": f"refused:{failed[0]}", "reason": ",".join(failed),
                                   "path": path})


# ----------------------------------------------------------------------------- build and concat

def build(*, inbox, day, layouts, ledger=LEDGER, mg2_inbox=None, parser=None, parser_worktree=None,
          parser_python=None):
    """The per-date label-free layout ``<layouts>\\<D>\\`` from the bundle MG-1's ledger verified."""
    row = _verified_row(ledger, day)
    if row is None:
        raise LayoutRefused(f"{day} has no verified line in MG-1's ledger {ledger}")
    bundle = bundle_dir(inbox=inbox, day=day, mg2_inbox=mg2_inbox)
    _refuse_transfer(bundle)
    if mi.sha256_file(bundle / allow.MANIFEST) != row.get("manifest_sha256"):
        raise LayoutRefused(f"{day}: the bundle manifest changed since MG-1 verified it")
    return mi.build(bundle=bundle, out=Path(layouts) / day.isoformat(), day=day, parser=parser,
                    parser_worktree=parser_worktree, parser_python=parser_python)


def window_dates():
    start, last = window.window()
    if last is None:
        raise LayoutRefused("the MG-1 window is open-ended (fail-wide recording): no layout")
    return [start + timedelta(days=k) for k in range((last - start).days + 1)]


def concat(*, layouts, out, ledger=LEDGER):
    """One window layout for exactly D0..MG1_LAST; refuses a missing date or a date MG-1 did not verify."""
    days = window_dates()
    missing = [d.isoformat() for d in days if not (Path(layouts) / d.isoformat() / "manifest.json").is_file()]
    if missing:
        raise LayoutRefused(f"{len(missing)} window dates have no layout: {missing[:10]}")
    result = mi.concat(layouts=[Path(layouts) / d.isoformat() for d in days], out=out, ledger=ledger)
    if result.get("dates") != [d.isoformat() for d in days]:
        raise LayoutRefused("the concatenated dates are not the MG-1 window")
    sources = {d.isoformat(): source_kind(d) for d in days}
    record = {"schema": "mg1_layout_window/1", "d0": days[0].isoformat(), "last": days[-1].isoformat(),
              "dates": len(days), "sources": sources, "ledger": str(ledger),
              "ledger_sha256": mi.sha256_file(ledger), "module_sha256": mi.sha256_file(__file__),
              "window_manifest_sha256": mi.sha256_file(Path(out) / "manifest.json"),
              "written_at_utc": datetime.now(timezone.utc).isoformat()}
    with open(Path(out) / WINDOW_RECEIPT, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return {**result, "mg1": {k: record[k] for k in ("d0", "last", "dates", "window_manifest_sha256")}}


# ----------------------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="python -m weather.calibration.mg1_layout", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("stage", help="copy <share>\\<D>\\ and its sidecar receipt (backfill dates only)")
    q.add_argument("--share-root", required=True)
    q.add_argument("--inbox", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--ledger", default=str(LEDGER))
    q = sub.add_parser("admit", help="verify a bundle without the deadline and record it in MG-1's ledger")
    q.add_argument("--inbox", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--mg2-inbox", default=None, help="B's MG-2 inbox (dates from 2026-10-28), read only")
    q.add_argument("--ledger", default=str(LEDGER))
    q = sub.add_parser("build", help="per-date label-free layout <layouts>\\<D>\\")
    q.add_argument("--inbox", required=True)
    q.add_argument("--date", required=True)
    q.add_argument("--layouts", required=True)
    q.add_argument("--mg2-inbox", default=None)
    q.add_argument("--ledger", default=str(LEDGER))
    q.add_argument("--parser-worktree", required=True)
    q.add_argument("--parser-python", default=None)
    q = sub.add_parser("concat", help="one window layout for D0..MG1_LAST")
    q.add_argument("--layouts", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--ledger", default=str(LEDGER))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    day = date.fromisoformat(args.date) if getattr(args, "date", None) else None
    try:
        if args.command == "stage":
            result = stage(share_root=args.share_root, inbox=args.inbox, day=day, ledger=args.ledger)
        elif args.command == "admit":
            result = admit(inbox=args.inbox, day=day, ledger=args.ledger, mg2_inbox=args.mg2_inbox)
        elif args.command == "build":
            result = build(inbox=args.inbox, day=day, layouts=args.layouts, ledger=args.ledger,
                           mg2_inbox=args.mg2_inbox, parser_worktree=args.parser_worktree,
                           parser_python=args.parser_python)
        else:
            result = concat(layouts=args.layouts, out=args.out, ledger=args.ledger)
    except (LayoutRefused, mi.InputRefused) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), flush=True)
        return 2
    print(json.dumps(result, sort_keys=True, default=str), flush=True)
    return 3 if str(result.get("status", "ok")).startswith("refused") else 0


if __name__ == "__main__":
    raise SystemExit(main())
