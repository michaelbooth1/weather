"""A9 driver: ``build`` (capture host) and ``verify`` (workstation) for the calibration-bundle transfer manifest.

    python -P -B -m maker_core.replay.v2.transfer_cli build --root KIND=DAY_FOLDER [--root ...] \\
        --host-id ID --out NEW_MANIFEST.json
    python -P -B -m maker_core.replay.v2.transfer_cli verify --manifest MANIFEST.json \\
        --expected-manifest-sha256 HEX --root KIND=DAY_FOLDER [--root ...]

A thin, fail-closed wrapper over ``maker_core.replay.v2.transfer`` (night-plans/o9/A9-CALIBRATION-BUNDLE-TRANSFER-PLAN.md):

- **Scope.** Only the calibration kinds (``transfer.CALIBRATION_KINDS``) are admitted, in arguments and in a manifest.
  Panel and settlement transfers come after signature and need their own reviewed change.
- **Embargo by name, before any byte.** Every ``DAY_FOLDER`` must be named ``YYYY-MM-DD`` (as given and once
  resolved) for a day of its kind (``transfer.days_of``) strictly before ``transfer.CALIBRATION_CARRY_FENCE``
  (2026-09-30T00:00Z). The check runs before ``transfer`` opens anything, so no panel-period folder is read.
- **build** reads only ``bundle.json``, ``export.json`` and ``receipt.json`` per root (``transfer.build``). It writes a
  NEW file (never overwrites; not inside any root) as canonical JSON, re-reads it, and prints ``manifest_sha256``: the
  value production relays to the workstation out of band.
- **verify** requires the relayed sha256. It hashes the raw manifest bytes and compares them BEFORE parsing. Then the
  manifest must list calibration kinds only, the roots must cover every listed bundle exactly, and
  ``transfer.verify`` runs with the PB2(b) bounds scan always on. The receipt holds counts, hashes and min/max
  ``captured_at`` per stream only.
- **Exit codes:** 0 PASS, 2 refused (stderr carries one ``refused: <code>`` line and no traceback), 3 error.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import transfer

MAX_MANIFEST_FILE_BYTES = 4 * 1024**2
RECEIPT_FORMAT = "maker_core.replay.v2.transfer_cli.receipt.v0.1"
_DAY_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")
_HEX = re.compile(r"[0-9a-f]{64}")


class Refused(Exception):
    """A fail-closed refusal; ``str()`` is the code."""


def _fence_day():
    fence = transfer.CALIBRATION_CARRY_FENCE
    if not isinstance(fence, datetime) or fence.tzinfo is None or fence.utcoffset().total_seconds() != 0:
        raise Refused("transfer_cli_fence_invalid")
    if (fence.hour, fence.minute, fence.second, fence.microsecond) != (0, 0, 0, 0):
        raise Refused("transfer_cli_fence_invalid")
    return fence.date()


def admitted_day(kind, name):
    """``name`` as a day admitted for ``kind``, or a refusal; reads nothing."""
    if kind not in transfer.CALIBRATION_KINDS:
        raise Refused("transfer_cli_kind_not_admitted")
    if not isinstance(name, str) or _DAY_NAME.fullmatch(name) is None:
        raise Refused("transfer_cli_root_not_a_day")
    try:
        day = date.fromisoformat(name)
    except ValueError:
        raise Refused("transfer_cli_root_not_a_day") from None
    if day >= _fence_day():
        raise Refused("transfer_cli_day_embargoed")
    if day not in transfer.days_of(kind):
        raise Refused("transfer_cli_day_not_in_kind")
    return day


def parse_root(text):
    """``KIND=PATH`` -> ``(kind, Path)`` after the name checks on the given and the resolved path."""
    kind, sep, raw = text.partition("=")
    if not sep or not raw:
        raise Refused("transfer_cli_root_syntax")
    path = Path(raw)
    admitted_day(kind, path.name)
    resolved = path.resolve(strict=False)
    if resolved.name != path.name:  # a link or alias that lands on another day's folder
        raise Refused("transfer_cli_root_alias")
    admitted_day(kind, resolved.name)
    return kind, path


def _roots(values):
    if not values:
        raise Refused("transfer_cli_no_roots")
    pairs = [parse_root(v) for v in values]
    resolved = [p.resolve(strict=False) for _, p in pairs]
    if len(set(resolved)) != len(resolved):
        raise Refused("transfer_cli_duplicate_root")
    return pairs


def _canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def build(args):
    pairs = _roots(args.root)
    if not args.host_id:
        raise Refused("transfer_cli_host_id_required")
    out = Path(args.out)
    target = out.resolve(strict=False)
    if out.exists() or out.is_symlink():
        raise Refused("transfer_cli_out_exists")
    if not target.parent.is_dir():
        raise Refused("transfer_cli_out_parent_missing")
    for _, root in pairs:
        if target.is_relative_to(root.resolve(strict=False)):
            raise Refused("transfer_cli_out_inside_root")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = transfer.build(pairs, host_id=args.host_id, created_at=created_at)
    transfer.check_doc(doc)
    for entry in doc["bundles"]:  # belt and braces: the built document is in scope too
        admitted_day(entry["export_kind"], entry["day"])
    raw = _canonical(doc)
    with open(out, "xb") as handle:  # exclusive create: never overwrites
        handle.write(raw)
    if out.read_bytes() != raw:
        raise Refused("transfer_cli_out_readback_mismatch")
    return dict(format=RECEIPT_FORMAT, command="build", verdict="BUILT", manifest=str(out),
                manifest_sha256=hashlib.sha256(raw).hexdigest(), manifest_bytes=len(raw),
                bundles=[[e["day"], e["export_kind"]] for e in doc["bundles"]])


def verify(args):
    expected = args.expected_manifest_sha256
    if not isinstance(expected, str) or _HEX.fullmatch(expected) is None:
        raise Refused("transfer_cli_expected_sha_not_64_lower_hex")
    pairs = _roots(args.root)
    path = Path(args.manifest)
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_FILE_BYTES:
        raise Refused("transfer_cli_manifest_unreadable")
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_FILE_BYTES:
        raise Refused("transfer_cli_manifest_unreadable")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected:  # compared before any parse
        raise Refused("transfer_cli_manifest_sha_mismatch")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise Refused("transfer_cli_manifest_invalid") from None
    listed = transfer.check_doc(doc)
    for day, kind in listed:
        admitted_day(kind, day)
    given = {(p.name, k) for k, p in pairs}
    if given != set(listed) or len(given) != len(pairs):
        raise Refused("transfer_cli_roots_do_not_cover_manifest")
    verified = transfer.verify(doc, pairs, bounds_check=True)
    if len(verified) != len(listed) or any(v.bounds is None for v in verified):
        raise Refused("transfer_cli_incomplete")
    bundles = [dict(day=v.bundle.day.isoformat(), export_kind=v.export_kind,
                    streams={name: dict(value) for name, value in sorted(v.bounds.items())})
               for v in verified]
    return dict(format=RECEIPT_FORMAT, command="verify", verdict="PASS", manifest_sha256=digest,
                bundles=sorted(bundles, key=lambda b: (b["day"], b["export_kind"])))


def _parser():
    parser = argparse.ArgumentParser(prog="maker_core.replay.v2.transfer_cli", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("build", help="capture host: write a new transfer manifest (reads no stream byte)")
    one.add_argument("--root", action="append", default=[], help="KIND=DAY_FOLDER (repeat)")
    one.add_argument("--host-id", required=True)
    one.add_argument("--out", required=True, help="a new file; never overwritten")
    two = commands.add_parser("verify", help="workstation: verify bundles against the relayed manifest sha256")
    two.add_argument("--manifest", required=True)
    two.add_argument("--expected-manifest-sha256", required=True)
    two.add_argument("--root", action="append", default=[], help="KIND=DAY_FOLDER (repeat)")
    return parser


def main(argv=None, *, stdout=None, stderr=None):
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    args = _parser().parse_args(argv)
    try:
        result = build(args) if args.command == "build" else verify(args)
    except (Refused, BundleError) as exc:
        stderr.write(f"refused: {exc}\n")
        return 2
    except Exception as exc:  # fail closed, no traceback or exception text  # noqa: BLE001
        stderr.write(f"error: transfer_cli_error:{type(exc).__name__}\n")
        return 3
    stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
