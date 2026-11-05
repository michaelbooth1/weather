r"""Row-28b forward inputs, workstation side: verify trimmed bundles, record holes, and the invariance comparison.

Design: ``docs/research/row28b-asof-trim-design-2026-11-04.md`` §5 and master's rulings of 2026-11-04. Research and
shadow only. The import refuses from a production package and on the dedicated capture host (through
``mg2_inputs`` -> ``mg2_composite``). Nothing here fetches, pulls, reads a label, settlement or price, or prints an
input value: outputs are names, counts, booleans and shas.

* ``verify``: one trimmed bundle (``r28b_input_trim`` output, already copied to the workstation by master's route).
  It runs the bound ``mg2_inputs.verify_bundle`` unchanged (the MG-2 receiver's D+1 deadline does not apply: the
  anti-tamper rule is instead that the trimmed manifest sha equals the one master logged from the host), accepts a
  ``market_missing`` problem only for a market the manifest itself declares absent (W2 or source-absent), and adds
  the ``r28b_trim`` checks (schema, the pinned trim module sha, H_LAST, ``prev_day`` dropped, no record captured
  after its market's T*). One line goes to the row-28b ledger, never to MG-2's.
* ``hole``: records a host-named hole (a date not exported by its D+1 deadline, master Q2) in the ledger.
* ``compare``: the invariance check on the FIRST forward batch (master Q6). The 343b emitter's own functions
  (``read_snapshots``, ``shadow_rows``, ``refuse_absent_emit_sources``, ``emit_holes``) run on the full and on the
  trimmed layout with the same state. The report holds booleans, counts and shas only. PASS needs
  ``shadow_rows`` byte-equal, equal hole keys, equal refusal outcome, and every stats counter equal except the
  ones in ``ALLOWED_TO_DIFFER`` (listed by name in the report). Anything else is a STOP: a STOP marker is written
  beside the ledger and ``gate`` reports ``emit_allowed: false`` until master rules (the marker is removed only by
  master).
* ``gate``: ``emit_allowed`` is true only when the latest comparison in the ledger is PASS and no STOP marker
  exists. Nothing emits from a trimmed set while it is false.

    python -m weather.calibration.r28b_inputs verify --bundle <dir> --date D --expected-manifest-sha <sha>
        --trim-module-sha <sha> [--ledger C:\t\r28b\forward\input_receipts.jsonl]
    python -m weather.calibration.r28b_inputs hole --date D --reason <name> --host-hole-sha <sha> [--ledger ...]
    python -m weather.calibration.r28b_inputs compare --state <pkl> --state-sha <sha> --first D --last D
        --full-snapshots <parquet> --full-replay-root <dir> --trimmed-snapshots <parquet>
        --trimmed-replay-root <dir> --out <report.json> [--ledger ...]
    python -m weather.calibration.r28b_inputs gate [--ledger ...]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from weather.calibration import mg2_inputs as _mi  # refuses on the capture host and from a production importer
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import r28b_input_trim as trim

LEDGER = Path(r"C:\t\r28b\forward\input_receipts.jsonl")
RECEIPT_SCHEMA = "r28b_input_receipt/1"
COMPARE_SCHEMA = "r28b_trim_invariance/1"
STOP_MARKER = "STOP_r28b_trim_invariance"
# Master 2026-11-04: the 343b gate and its counters stay 7..20, so exactly these stats counters (design §3.3) may
# differ between full and trimmed inputs. Every other counter, the rows and the hole keys must be equal.
ALLOWED_TO_DIFFER = ("outside_cutoff_hours", "no_fit_for_hour", "replay_hours")


class R28bRefused(RuntimeError):
    """The request cannot run; nothing is written."""


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _ledger(ledger):
    path = Path(ledger)
    if path.resolve() == Path(_mi.LEDGER).resolve():
        raise R28bRefused("row-28b never writes MG-2's input ledger")
    return path


def read_ledger(ledger):
    path = Path(ledger)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(ledger, row):
    path = _ledger(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def _in_window(day):
    if not trim.WINDOW_FIRST <= day <= trim.WINDOW_LAST:
        raise R28bRefused(f"{day} is outside the row-28b input window {trim.WINDOW_FIRST}..{trim.WINDOW_LAST}")


def _late_records(bundle, manifest, day):
    """Count of records captured after their market's T* (or unparseable), over the trimmed files. Counts only."""
    stars = (manifest.get("r28b_trim") or {}).get("markets") or {}
    late = 0
    for entry in manifest.get("files") or []:
        rel = str(entry.get("path"))
        kind = allow.classify_path(rel, day)
        if kind is None or kind[0] in ("manifest", "nbm_blob"):
            continue
        cut = trim.parse_time((stars.get(kind[1]) or {}).get("t_star_utc"))
        path = Path(bundle) / rel
        if kind[0] in ("snapshots_long", "features_long"):
            with open(path, encoding="utf-8", newline="") as handle:
                times = [row.get("captured_at_utc") for row in csv.DictReader(handle)]
        else:
            times = [r.get("captured_at_utc") for _raw, r in trim.jsonl_records(path)]
        late += sum(1 for t in times if cut is None or trim.parse_time(t) is None or trim.parse_time(t) > cut)
    return late


def verify(*, bundle, day, expected_manifest_sha, trim_module_sha, ledger=LEDGER, now=None):
    """Verify one trimmed bundle and record the outcome (names only) in the row-28b ledger."""
    _in_window(day)
    ledger = _ledger(ledger)
    for row in read_ledger(ledger):
        if row.get("target_date") == day.isoformat() and row.get("kind") in ("verify", "hole") and \
                row.get("status") in ("verified", "hole"):
            return {"status": "already_recorded", "receipt": row}
    bundle = Path(bundle)
    checks, manifest, manifest_sha = _mi.verify_bundle(bundle, day)
    manifest = manifest or {}
    absent = {m for m, v in (manifest.get("markets") or {}).items() if not v.get("present")}
    problems = []
    for name, items in sorted(checks.items()):
        allowed = {f"market_missing:{m}" for m in absent} if name == "markets" else set()
        problems.extend(f"{name}:{p}" for p in items if p not in allowed)
    block = manifest.get("r28b_trim") or {}
    if manifest_sha != expected_manifest_sha:
        problems.append("manifest_sha_not_the_host_logged_sha")
    if block.get("schema") != trim.SCHEMA:
        problems.append("r28b_trim_schema")
    if block.get("trim_module_sha256") != trim_module_sha:
        problems.append("trim_module_sha_not_pinned")
    if block.get("h_last") != trim.H_LAST or block.get("prev_day") != "dropped":
        problems.append("r28b_trim_rules")
    if any(str(e.get("path", "")).startswith("prev_day/") for e in manifest.get("files") or []) or \
            (bundle / "prev_day").exists():
        problems.append("prev_day_present")
    if not problems:
        late = _late_records(bundle, manifest, day)
        if late:
            problems.append(f"records_after_t_star:{late}")
    receipt = {"schema": RECEIPT_SCHEMA, "kind": "verify", "target_date": day.isoformat(),
               "status": "refused" if problems else "verified", "manifest_sha256": manifest_sha,
               "expected_manifest_sha256": expected_manifest_sha, "trim_module_sha256": trim_module_sha,
               "absent_markets": sorted(absent), "problems": sorted(problems)[:50],
               "recorded_at": _now(now).isoformat()}
    return _append(ledger, receipt)


def record_hole(*, day, reason, host_hole_sha, ledger=LEDGER, now=None):
    """Record a host-named hole (master Q2) for ``day``."""
    _in_window(day)
    if reason not in trim.HOLE_REASONS:
        raise R28bRefused(f"unknown hole reason {reason}; expected one of {trim.HOLE_REASONS}")
    for row in read_ledger(ledger):
        if row.get("target_date") == day.isoformat() and row.get("status") in ("verified", "hole"):
            raise R28bRefused(f"{day} already has a {row['status']} receipt")
    return _append(ledger, {"schema": RECEIPT_SCHEMA, "kind": "hole", "target_date": day.isoformat(),
                            "status": "hole", "reason": reason, "host_hole_sha256": host_hole_sha,
                            "recorded_at": _now(now).isoformat()})


# ----------------------------------------------------------------------------- invariance comparison (Q6)

def _emitter():
    """The 343b emitter and the bound MG-2 serve module, imported only for the comparison (read-only use)."""
    from weather.calibration import mg2_p3d_n as p3
    from weather.calibration import yearround_refit as yr
    return yr, p3


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _side(yr, p3, state, snapshots, replay_root, first, last):
    snaps = yr.read_snapshots(yr.guard_path(snapshots), first, last)
    presence = {}
    rows, stats, _used = yr.shadow_rows(state, snaps, yr.guard_path(replay_root), first, last, yr.EMIT_MARKETS,
                                        presence=presence)
    refusal = None
    try:
        yr.refuse_absent_emit_sources(snaps, presence, first, last, yr.EMIT_MARKETS)
    except yr.YearroundRefused as exc:
        refusal = _sha(str(exc).encode("utf-8"))
    holes = yr.emit_holes(rows, presence, first, last, yr.EMIT_MARKETS)
    body = "".join(p3.jsonl_line(m, sid, t, d) for m, sid, t, _key, d in rows).encode("utf-8")
    keys = sorted({(h["market"], h["target_date"]) for h in holes})
    return {"body": body, "keys": keys, "stats": stats, "refusal": refusal,
            "summary": {"snapshots_sha256": trim.sha256_file(snapshots), "rows": len(rows), "holes": len(holes),
                        "shadow_rows_sha256": _sha(body),
                        "hole_keys_sha256": _sha(json.dumps(keys).encode("utf-8")),
                        "refused": refusal is not None}}


def _stats_differences(full, trimmed):
    """Counter names (not values) whose per-market value differs between the two sides."""
    names = set()
    for market in set(full) | set(trimmed):
        a, b = full.get(market) or {}, trimmed.get(market) or {}
        for key in set(a) | set(b):
            if a.get(key) != b.get(key):
                names.add(key)
    return names


def compare(*, state, state_sha, first, last, full_snapshots, full_replay_root, trimmed_snapshots,
            trimmed_replay_root, out, ledger=LEDGER, now=None):
    """Emit on the full and on the trimmed inputs and report equality (booleans, counts and shas only)."""
    _in_window(first)
    _in_window(last)
    if last < first:
        raise R28bRefused("--last is before --first")
    ledger, out = _ledger(ledger), Path(out)
    if out.exists():
        raise R28bRefused(f"{out} already exists (write-once)")
    yr, p3 = _emitter()
    loaded = p3.load_state(yr.guard_path(state), state_sha, forward=True)
    full = _side(yr, p3, loaded, full_snapshots, full_replay_root, first, last)
    trimmed = _side(yr, p3, loaded, trimmed_snapshots, trimmed_replay_root, first, last)
    differing = _stats_differences(full["stats"], trimmed["stats"])
    allowed = sorted(differing & set(ALLOWED_TO_DIFFER))
    disallowed = sorted(differing - set(ALLOWED_TO_DIFFER))
    rows_equal = full["body"] == trimmed["body"]
    keys_equal = full["keys"] == trimmed["keys"]
    refusal_equal = full["refusal"] == trimmed["refusal"]
    verdict = "PASS" if rows_equal and keys_equal and refusal_equal and not disallowed else "STOP"
    report = {"schema": COMPARE_SCHEMA, "first": first.isoformat(), "last": last.isoformat(),
              "state_sha256": state_sha, "full": full["summary"], "trimmed": trimmed["summary"],
              "shadow_rows_equal": rows_equal, "hole_keys_equal": keys_equal, "refusal_equal": refusal_equal,
              "stats_allowed_to_differ": list(ALLOWED_TO_DIFFER), "stats_differing_allowed": allowed,
              "stats_differing_disallowed": disallowed, "verdict": verdict,
              "written_utc": _now(now).isoformat()}
    body = (json.dumps(report, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "xb") as handle:
        handle.write(body)
    if verdict != "PASS":
        marker = ledger.parent / STOP_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"first": report["first"], "last": report["last"],
                                      "report_sha256": _sha(body)}) + "\n", encoding="utf-8")
    _append(ledger, {"schema": RECEIPT_SCHEMA, "kind": "compare", "first": report["first"], "last": report["last"],
                     "verdict": verdict, "report_sha256": _sha(body), "recorded_at": report["written_utc"]})
    return report


def emit_allowed(ledger=LEDGER):
    """True only when the latest comparison is PASS and no STOP marker stands."""
    ledger = Path(ledger)
    if (ledger.parent / STOP_MARKER).exists():
        return False
    compares = [r for r in read_ledger(ledger) if r.get("kind") == "compare"]
    return bool(compares) and compares[-1].get("verdict") == "PASS"


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.r28b_inputs")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="verify one trimmed bundle against the host-logged manifest sha")
    v.add_argument("--bundle", required=True)
    v.add_argument("--date", required=True)
    v.add_argument("--expected-manifest-sha", required=True)
    v.add_argument("--trim-module-sha", required=True)
    h = sub.add_parser("hole", help="record a host-named hole")
    h.add_argument("--date", required=True)
    h.add_argument("--reason", required=True, choices=trim.HOLE_REASONS)
    h.add_argument("--host-hole-sha", required=True)
    c = sub.add_parser("compare", help="first-batch invariance: emit on full and trimmed inputs")
    for name in ("--state", "--state-sha", "--first", "--last", "--full-snapshots", "--full-replay-root",
                 "--trimmed-snapshots", "--trimmed-replay-root", "--out"):
        c.add_argument(name, required=True)
    sub.add_parser("gate", help="print emit_allowed")
    for p in (v, h, c, sub.choices["gate"]):
        p.add_argument("--ledger", default=str(LEDGER))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            result = verify(bundle=args.bundle, day=date.fromisoformat(args.date),
                            expected_manifest_sha=args.expected_manifest_sha, trim_module_sha=args.trim_module_sha,
                            ledger=args.ledger)
            code = 0 if result.get("status") in ("verified", "already_recorded") else 2
        elif args.command == "hole":
            result = record_hole(day=date.fromisoformat(args.date), reason=args.reason,
                                 host_hole_sha=args.host_hole_sha, ledger=args.ledger)
            code = 0
        elif args.command == "compare":
            result = compare(state=args.state, state_sha=args.state_sha, first=date.fromisoformat(args.first),
                             last=date.fromisoformat(args.last), full_snapshots=args.full_snapshots,
                             full_replay_root=args.full_replay_root, trimmed_snapshots=args.trimmed_snapshots,
                             trimmed_replay_root=args.trimmed_replay_root, out=args.out, ledger=args.ledger)
            code = 0 if result["verdict"] == "PASS" else 5
        else:
            result = {"emit_allowed": emit_allowed(args.ledger)}
            code = 0 if result["emit_allowed"] else 5
    except (R28bRefused, ValueError, OSError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
