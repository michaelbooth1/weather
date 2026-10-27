"""R-O Clarification 1 capture-side extractor (research-only; branch claude/ro-run-env-20261027, never lands).

Reads the capture host's raw Open-Meteo ensemble payload blobs under ``<event dir>/forecast_payloads/`` and writes,
per blob and per member, the max over the R-O history nodes plus the full local-day max. Standard library only.

* Input: one or more event directories (``highest-temperature-in-<city>-on-<month>-<day>-<year>``), given on the
  command line or one per line in ``--dirs-file``. The run REFUSES, before opening any file, if a directory name does
  not parse or its target date D is outside 2026-07-30..2026-09-29.
* Layout (capture host): ``<dir>/forecast_payloads/sha256/<2-hex>/<sha256>.<ext>``. Exactly that walk, no
  recursion; anything else under ``forecast_payloads`` is counted as ignored. Only those files are opened (Python's
  default open is shared-read on Windows). Integrity: sha256 of the RAW stored bytes (before any gzip decode) must
  equal the filename stem, because the store is content-addressed on what it wrote; a mismatched blob is not used,
  is counted, and makes the run exit non-zero. A blob is an ensemble payload only if its JSON has ``hourly`` keys
  ``temperature_2m_member01``..; other blobs are counted as skipped. gzip blobs (magic 1f8b) are decompressed.
* ``utc_offset_seconds`` is never defaulted: a blob without a numeric value is skipped and counted as
  ``blobs_no_offset`` (a present 0 is accepted).
* The run writes the CSV and manifest, then exits non-zero if any blob sha mismatched, if any event dir that has a
  ``forecast_payloads`` dir yielded no ensemble blob, or if no ensemble blob was found at all.
* Nodes mirror ``pooled_residual_model.ro_member_highs`` (cycle 06Z of D, fh 6, 9, ..., 24, i.e. valid 12Z D ..
  06Z D+1, kept only when the valid local date is D). Labels are Open-Meteo naive local times with one
  ``utc_offset_seconds`` per payload; instant = label - offset (as ``weather.time.provider_hourly_local_times``), and
  the local date of an instant is (instant + offset).date(). A member's node max needs every node present.
* The full-day max (all labels whose local date is D) mirrors ``model_sources.fetch_global_ensemble`` so P can link a
  blob to a workstation snapshot by reproducing the captured ``day_member_high_p10/p90`` and ``day_max_native``.

Output: ``<out>/ro_capture_members.csv`` (one row per blob x member, member ``control`` = ``temperature_2m``) and
``<out>/ro_capture_manifest.json`` (script sha, every input blob's sha256 and size, output sha, counts).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WINDOW = (date(2026, 7, 30), date(2026, 9, 29))
NODE_STEPS = (6, 9, 12, 15, 18, 21, 24)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
SLUG = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d{1,2})-(\d{4})$")
MEMBER = re.compile(r"^temperature_2m_member(\d{2})$")
FIELDS = ("event", "target_date", "blob", "blob_sha256", "blob_mtime_utc", "generationtime_ms",
          "utc_offset_seconds", "temperature_unit", "member", "node_max", "n_nodes", "nodes_wanted", "day_max",
          "n_day_hours")


class Refused(SystemExit):
    pass


def slug_date(name):
    m = SLUG.match(name)
    if not m or m.group(2) not in MONTHS:
        return None
    return m.group(1), date(int(m.group(4)), MONTHS.index(m.group(2)) + 1, int(m.group(3)))


def check_dirs(dirs):
    """[(Path, city, D)]; raises Refused before any file is opened if a name is unparsed or D is out of window."""
    out, bad = [], []
    for d in dirs:
        p = Path(d)
        parsed = slug_date(p.name)
        if parsed is None or not (WINDOW[0] <= parsed[1] <= WINDOW[1]):
            bad.append(p.name)
        else:
            out.append((p, parsed[0], parsed[1]))
    if bad:
        raise Refused(f"refusing: {len(bad)} director(ies) unparsed or outside "
                      f"{WINDOW[0]}..{WINDOW[1]}: {', '.join(sorted(bad)[:5])}")
    return out


def node_instants(d):
    cycle = datetime(d.year, d.month, d.day, 6, tzinfo=timezone.utc)
    return [cycle + timedelta(hours=fh) for fh in NODE_STEPS]


def label_instant(label, offset):
    naive = datetime.fromisoformat(str(label))
    if naive.tzinfo is not None:
        return naive.astimezone(timezone.utc)
    return (naive - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)


def local_date(instant, offset):
    return (instant + timedelta(seconds=offset)).date()


def number(values, i):
    try:
        v = values[i]
    except (IndexError, TypeError):
        return None
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def payload_offset(payload):
    """The payload's utc_offset_seconds as int, or None when absent or not a number (never defaulted)."""
    v = payload.get("utc_offset_seconds") if isinstance(payload, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def is_ensemble(payload):
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    return isinstance(hourly, dict) and any(MEMBER.match(k) for k in hourly)


def extract_payload(payload, d, offset):
    """{member: (node_max|None, n_nodes, nodes_wanted, day_max|None, n_day_hours)} or None if not an ensemble blob."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return None
    members = sorted(k for k in hourly if MEMBER.match(k))
    if not members:
        return None
    instants = []
    for label in hourly.get("time") or []:
        try:
            instants.append(label_instant(label, offset))
        except (TypeError, ValueError):
            instants.append(None)
    want = {v for v in node_instants(d) if local_date(v, offset) == d}
    out = {}
    for key, name in [("temperature_2m", "control")] + [(k, MEMBER.match(k).group(1)) for k in members]:
        series = hourly.get(key)
        if series is None:
            continue
        nodes, day = {}, []
        for i, inst in enumerate(instants):
            if inst is None:
                continue
            v = number(series, i)
            if v is None:
                continue
            if local_date(inst, offset) == d:
                day.append(v)
            if inst in want:
                nodes[inst] = v
        node_max = max(nodes.values()) if want and set(nodes) == want else None
        out[name] = (node_max, len(nodes), len(want), max(day) if day else None, len(day))
    return out


HEX2 = re.compile(r"^[0-9a-f]{2}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def read_blob(path):
    with open(path, "rb") as fh:  # default CPython open on Windows shares read and write
        raw = fh.read()
    body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    return raw, body


def blob_paths(pdir, counts):
    """Exactly forecast_payloads/sha256/<2-hex>/<file>; everything else is counted as ignored (no recursion)."""
    out = []
    for entry in sorted(pdir.iterdir()):
        if entry.name == "sha256" and entry.is_dir():
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and HEX2.match(sub.name):
                    for f in sorted(sub.iterdir()):
                        if f.is_file():
                            out.append(f)
                        else:
                            counts["entries_ignored"] += 1
                else:
                    counts["entries_ignored"] += 1
        else:
            counts["entries_ignored"] += 1
    return out


def run(dirs, out_dir):
    """Write the CSV and manifest and return the manifest; raises Refused (after writing) on a failure condition."""
    checked = check_dirs(dirs)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "ro_capture_members.csv"
    if csv_path.exists():
        raise Refused(f"refusing to overwrite {csv_path}")
    counts = {k: 0 for k in ("event_dirs", "event_dirs_without_payloads", "event_dirs_zero_ensemble", "entries_ignored",
                             "blobs_seen", "blobs_sha_mismatch", "blobs_unreadable", "blobs_skipped_not_ensemble",
                             "blobs_no_offset", "blobs_ensemble", "rows")}
    counts["event_dirs"] = len(checked)
    inputs, mismatches, zero_dirs = [], [], []
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(FIELDS)
        for folder, _city, d in checked:
            pdir = folder / "forecast_payloads"
            if not pdir.is_dir():
                counts["event_dirs_without_payloads"] += 1
                continue
            ensemble_here = 0
            for blob in blob_paths(pdir, counts):
                counts["blobs_seen"] += 1
                rel = f"{folder.name}/forecast_payloads/{blob.relative_to(pdir).as_posix()}"
                try:
                    raw, body = read_blob(blob)
                except (OSError, EOFError, gzip.BadGzipFile):
                    counts["blobs_unreadable"] += 1
                    continue
                sha = hashlib.sha256(raw).hexdigest()
                stem = blob.name.split(".", 1)[0]
                if not HEX64.match(stem) or stem != sha:
                    counts["blobs_sha_mismatch"] += 1
                    mismatches.append(rel)
                    continue
                if b"temperature_2m_member" not in body:
                    counts["blobs_skipped_not_ensemble"] += 1
                    continue
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    counts["blobs_unreadable"] += 1
                    continue
                if not is_ensemble(payload):
                    counts["blobs_skipped_not_ensemble"] += 1
                    continue
                offset = payload_offset(payload)
                if offset is None:
                    counts["blobs_no_offset"] += 1
                    continue
                res = extract_payload(payload, d, offset)
                counts["blobs_ensemble"] += 1
                ensemble_here += 1
                inputs.append({"path": rel, "sha256": sha, "bytes": len(raw)})
                mtime = datetime.fromtimestamp(blob.stat().st_mtime, timezone.utc).isoformat()
                unit = (payload.get("hourly_units") or {}).get("temperature_2m")
                for member, (node_max, n_nodes, n_want, day_max, n_day) in sorted(res.items()):
                    w.writerow((folder.name, d.isoformat(), blob.name, sha, mtime, payload.get("generationtime_ms"),
                                offset, unit, member, "" if node_max is None else repr(node_max), n_nodes, n_want,
                                "" if day_max is None else repr(day_max), n_day))
                    counts["rows"] += 1
            if ensemble_here == 0:
                counts["event_dirs_zero_ensemble"] += 1
                zero_dirs.append(folder.name)
    failures = []
    if counts["blobs_sha_mismatch"]:
        failures.append(f"{counts['blobs_sha_mismatch']} blob(s) whose sha256 != filename stem")
    if zero_dirs:
        failures.append(f"{len(zero_dirs)} event dir(s) with forecast_payloads but no ensemble blob")
    if counts["blobs_ensemble"] == 0:
        failures.append("no ensemble blob found at all")
    manifest = {"schema": "ro_capture_members/2", "window": [WINDOW[0].isoformat(), WINDOW[1].isoformat()],
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "node_steps_06z": list(NODE_STEPS), "counts": counts, "inputs": inputs,
                "sha_mismatches": mismatches[:200], "zero_ensemble_dirs": zero_dirs,
                "status": "failed" if failures else "ok", "failures": failures,
                "output": {"path": csv_path.name, "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()}}
    (out / "ro_capture_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    if failures:
        raise Refused("FAILED: " + "; ".join(failures))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*", help="event directories (each holding forecast_payloads/)")
    ap.add_argument("--dirs-file", help="file with one event directory per line")
    ap.add_argument("--out", required=True, help="output directory (CSV + manifest)")
    args = ap.parse_args(argv)
    dirs = list(args.dirs)
    if args.dirs_file:
        dirs += [line.strip() for line in Path(args.dirs_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not dirs:
        ap.error("no event directories given")
    m = run(dirs, args.out)
    print(json.dumps({"counts": m["counts"], "output": m["output"], "script_sha256": m["script_sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
