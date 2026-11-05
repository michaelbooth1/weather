r"""MG-1 input backfill, capture-host side: the MG-2 input exporter on MG-1's dates 2026-10-15..2026-10-27.

R11 Head 1 (master rulings 2026-11-01, R11 item 7: the 2026-10-26 inputs-only export rule covers 10-15..10-27).
The MG-2 exporter (``weather.calibration.mg2_input_export``) admits a target date only when every event folder it
reads is in the development window or on/after MG-2's D0 (2026-10-28). MG-1's window starts on 2026-10-15, so its
first 13 dates have no bundle. This wrapper runs the unchanged exporter on exactly those dates:

* **Gate.** ``export`` is called with the exporter's module-level ``check_date`` swapped, inside ``try/finally``,
  for this module's ``check_date``. That gate admits only target dates 2026-10-15..2026-10-27 (inclusive) whose
  export cut has passed, and nothing else. The original gate is restored however ``export`` ends. Nothing else
  about the exporter changes: same projections, same shared-read bounded opens, same quiet guard, same bundle and
  manifest (a test pins the manifest to a direct export of the same fixture).
* **Coverage counts are always off.** There is no flag. ``coverage_counts=False`` is passed on every call, and the
  manifest is checked for ``coverage_counts is False`` before the receipt is written.
* **Output.** ``<out>\<D>\`` and ``<out>\<D>.SHA256SUMS`` exactly as the exporter writes them, with
  ``<out>`` defaulting to ``<repo>\data\exports\mg1-inputs`` (not the MG-2 folder). Beside them the wrapper writes
  the sidecar receipt ``<out>\<D>.mg1_backfill_receipt.json`` (mode "x"). It sits outside the bundle because the
  receiver refuses unlisted files inside one. The receipt holds the wrapper and exporter sha256, the allow-list
  sha256 and the manifest sha256.
* **Resumable per date.** A date whose bundle, sums and receipt all exist is skipped (``already_exported``). A
  bundle with no receipt, or a leftover staging folder, is refused for inspection.
* **Precheck.** ``precheck`` is metadata only. It runs ``os.lstat`` on the section 9.1 input paths of each date
  and opens no file. It also reports the free bytes on the output volume. NBM blob sizes are not known without
  reading the NBM manifests, so they are not estimated.

Where it lives: ``tools/research/``, not ``src/`` (master ruling 2026-11-01, option d). The binding exporter's
test pins that nothing under ``src/`` imports it, and a test here pins that nothing under ``src/`` imports or names
this backfill and that the exporter's bytes are unchanged. Standard library plus ``mg2_input_export`` (itself
stdlib plus the allow-list), so it runs on the capture host. Nothing imports it (roll-free: tools and ``.ps1``). It never reads labels, settlements or prices, and it never touches the share:
master stages the bundles on the share, at a root that master picks.

    python -P -B -m tools.research.mg1_input_backfill precheck [--date D ...] [--data-root ...] [--out ...]
    python -P -B -m tools.research.mg1_input_backfill export [--date D ...] [--data-root ...] [--out ...]

On the capture host it runs only through ``scripts\ops\mg1_input_backfill.ps1`` (host identity, 00:30-09:00,
the shared lease, a kill-on-close job, the PYTHONPATH pin proof, 5 GiB free, UTC memory freshness).

With no ``--date``, both commands cover every date 2026-10-15..2026-10-27.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import stat
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

RECEIPT_SCHEMA = "mg1_backfill_receipt/1"
RECEIPT_SUFFIX = ".mg1_backfill_receipt.json"
MODULE = "tools.research.mg1_input_backfill"
FIRST = date(2026, 10, 15)  # MG-1 D0
LAST = date(2026, 10, 27)  # the day before MG-2's D0 (mx.FORWARD_FIRST)
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = _REPO / "data"
DEFAULT_OUT = _REPO / "data" / "exports" / "mg1-inputs"
# The section 9.1 file names the exporter may open per folder offset (precheck stats these; it opens none).
INPUT_NAMES = {-1: ("replay_inputs.jsonl", "forecast_payloads.jsonl", "forecast_payloads_long.csv"),
               0: ("replay_inputs.jsonl", "snapshots_long.csv", "features_long.csv", "forecast_payloads.jsonl",
                   "forecast_payloads_long.csv"),
               1: ("forecast_payloads.jsonl", "forecast_payloads_long.csv")}


class BackfillRefused(mx.ExportRefused):
    """The backfill refused a date or its output; nothing is published for that date."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def all_dates():
    return [FIRST + timedelta(days=k) for k in range((LAST - FIRST).days + 1)]


def check_date(day, now=None):
    """The backfill gate: only 2026-10-15..2026-10-27, and only after the date's export cut has passed."""
    if not isinstance(day, date) or isinstance(day, datetime) or not FIRST <= day <= LAST:
        raise BackfillRefused(f"{day} is outside the MG-1 backfill dates {FIRST}..{LAST}: refused")
    now = now or datetime.now(timezone.utc)
    if now <= allow.export_cut_utc(day):
        raise BackfillRefused(f"{day}'s export cut {allow.export_cut_utc(day).isoformat()} has not passed")


@contextlib.contextmanager
def _backfill_gate():
    """Swap the exporter's date gate for ``check_date``; the original is restored however the body ends."""
    original = mx.check_date
    mx.check_date = check_date
    try:
        yield
    finally:
        mx.check_date = original


def receipt_path(out, day):
    return Path(out) / f"{day.isoformat()}{RECEIPT_SUFFIX}"


def _outputs(out, day):
    out = Path(out)
    return (out / day.isoformat(), out / f"{day.isoformat()}{mx.SUMS_SUFFIX}", out / f".{day.isoformat()}.partial",
            receipt_path(out, day))


def _state(out, day):
    final, sums, staging, receipt = _outputs(out, day)
    if staging.exists():
        return "staging_left_over"
    present = [p.exists() for p in (final, sums, receipt)]
    if all(present):
        return "already_exported"
    if any(present):
        return "partial_outputs"
    return "new"


def export_one(*, day, data_root=DEFAULT_DATA_ROOT, out=DEFAULT_OUT, now=None, repo=None, clock=time.time):
    """Export one MG-1 backfill date through the unchanged exporter. Returns ``(status, manifest, receipt)``."""
    check_date(day, now)
    state = _state(out, day)
    if state == "already_exported":
        receipt = json.loads(receipt_path(out, day).read_text(encoding="utf-8"))
        return "already_exported", None, receipt
    if state != "new":
        raise BackfillRefused(f"{day}: {state} under {out}; inspect it and move it aside before a re-export")
    with _backfill_gate():
        manifest = mx.export(day=day, data_root=data_root, out=out, now=now, repo=repo, clock=clock,
                             coverage_counts=False)
    if manifest.get("coverage_counts") is not False:
        raise BackfillRefused(f"{day}: the manifest does not record coverage_counts false")
    final, sums, _staging, receipt_file = _outputs(out, day)
    exporter_sha = sha256_file(mx.__file__)
    if manifest.get("exporter_sha256") != exporter_sha:
        raise BackfillRefused(f"{day}: the exporter changed on disk during the export")
    receipt = {
        "schema": RECEIPT_SCHEMA, "target_date": day.isoformat(),
        "gate": {"first": FIRST.isoformat(), "last": LAST.isoformat(), "rule": "R11 item 7 (master 2026-11-01)"},
        "wrapper": {"module": MODULE,
                    "sha256": sha256_file(__file__)},
        "exporter": {"module": "weather.calibration.mg2_input_export", "sha256": exporter_sha,
                     "schema": manifest.get("exporter_schema")},
        "allowlist_sha256": manifest.get("allowlist_sha256"),
        "manifest_sha256": sha256_file(final / allow.MANIFEST),
        "sha256sums_sha256": sha256_file(sums),
        "coverage_counts": False, "host_repo_head": manifest.get("host_repo_head"),
        "files": len(manifest.get("files") or []),
        "absent_markets": sorted(m for m, v in (manifest.get("markets") or {}).items() if not v.get("present")),
        "nbm_blobs": manifest.get("nbm_blobs"),
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with open(receipt_file, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    return "exported", manifest, receipt


def _lstat_size(root, rel):
    """Size of a regular, non-link file by metadata only; None when absent. Opens nothing."""
    here = Path(root)
    for part in rel.split("/"):
        here = here / part
        if not os.path.lexists(here):
            return None
        info = os.lstat(here)
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BackfillRefused(f"link or reparse point refused: {rel}")
    return info.st_size if stat.S_ISREG(info.st_mode) else None


def precheck(*, days, data_root=DEFAULT_DATA_ROOT, out=DEFAULT_OUT, now=None):
    """Metadata-only plan: per date the gate, the output state and the section 9.1 input bytes present."""
    data_root, out = Path(data_root), Path(out)
    rows, total = [], 0
    for day in days:
        row = {"target_date": day.isoformat()}
        try:
            check_date(day, now)
        except BackfillRefused as exc:
            rows.append({**row, "status": "refused", "reason": str(exc)})
            continue
        present, missing, size = 0, 0, 0
        for market in allow.MARKETS:
            for offset, names in INPUT_NAMES.items():
                slug = allow.slug_for(market, day + timedelta(days=offset))
                for name in names:
                    found = _lstat_size(data_root, f"snapshots/{slug}/{name}")
                    if found is None:
                        missing += 1
                    else:
                        present += 1
                        size += found
        total += size
        rows.append({**row, "status": _state(out, day), "input_files_present": present,
                     "input_names_absent": missing, "input_bytes": size})
    probe = out if out.exists() else next((p for p in out.parents if p.exists()), out.anchor or out)
    free = shutil.disk_usage(probe).free
    return {"dates": rows, "input_bytes_total": total, "out": str(out), "out_volume_free_bytes": free,
            "nbm_blob_bytes": "not estimated (needs the NBM manifests opened)", "files_opened": 0}


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m {MODULE}",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("precheck", "metadata-only existence and size check; opens no file"),
                       ("export", "export each date through the unchanged MG-2 exporter (coverage counts off)")):
        q = sub.add_parser(name, help=text)
        q.add_argument("--date", action="append", default=None,
                       help=f"target date (repeatable); default every date {FIRST}..{LAST}")
        q.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
        q.add_argument("--out", default=str(DEFAULT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    days = [date.fromisoformat(d) for d in args.date] if args.date else all_dates()
    if args.command == "precheck":
        print(json.dumps(precheck(days=days, data_root=args.data_root, out=args.out), indent=1, sort_keys=True))
        return 0
    status = 0
    for day in days:
        try:
            outcome, manifest, receipt = export_one(day=day, data_root=args.data_root, out=args.out)
        except mx.FileTooFresh as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "too_fresh", "reason": str(exc)}))
            status = max(status, 3)
            continue
        except mx.ExportRefused as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "refused", "reason": str(exc)}))
            status = max(status, 2)
            continue
        absent = receipt.get("absent_markets") or []
        blobs = receipt.get("nbm_blobs") or {}
        print(json.dumps({"target_date": day.isoformat(), "status": outcome if not absent else "incomplete",
                          "absent_markets": absent, "files": receipt.get("files"), "nbm_blobs": blobs,
                          "manifest_sha256": receipt.get("manifest_sha256")}))
        bad_refs = manifest.get("nbm_rows_bad_ref") if manifest else 0
        if absent or blobs.get("missing") or blobs.get("hash_mismatch") or bad_refs:
            status = max(status, 3)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
