"""R-O Clarification 1 capture-side extractor (research-only; branch claude/ro-run-env-20261027, never lands).

Reads the capture host's raw Open-Meteo ensemble payload blobs under ``<event dir>/forecast_payloads/`` and writes,
per blob and per member, the max over the R-O history nodes plus the full local-day max. Standard library only.

* Input: one or more event directories (``highest-temperature-in-<city>-on-<month>-<day>-<year>``), given on the
  command line or one per line in ``--dirs-file``. The run REFUSES, before opening any file, if a directory name does
  not parse or its target date D is outside 2026-07-30..2026-09-29.
* Only files in ``<dir>/forecast_payloads/`` are opened (Python's default open is shared-read on Windows). A blob is
  an ensemble payload only if its JSON has ``hourly`` keys ``temperature_2m_member01``..; every other blob is counted
  as skipped and nothing else in it is used. gzip blobs (magic 1f8b) are decompressed. Nothing else is parsed.
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


def extract_payload(payload, d):
    """{member: (node_max|None, n_nodes, nodes_wanted, day_max|None, n_day_hours)} or None if not an ensemble blob."""
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict):
        return None
    members = sorted(k for k in hourly if MEMBER.match(k))
    if not members:
        return None
    offset = int(payload.get("utc_offset_seconds") or 0)
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


def read_blob(path):
    with open(path, "rb") as fh:  # default CPython open on Windows shares read and write
        raw = fh.read()
    body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    return raw, body


def run(dirs, out_dir):
    checked = check_dirs(dirs)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "ro_capture_members.csv"
    if csv_path.exists():
        raise Refused(f"refusing to overwrite {csv_path}")
    counts = {"event_dirs": len(checked), "blobs_seen": 0, "blobs_ensemble": 0, "blobs_skipped_not_ensemble": 0,
              "blobs_unreadable": 0, "event_dirs_without_payloads": 0, "rows": 0}
    inputs = []
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(FIELDS)
        for folder, _city, d in checked:
            pdir = folder / "forecast_payloads"
            if not pdir.is_dir():
                counts["event_dirs_without_payloads"] += 1
                continue
            for blob in sorted(p for p in pdir.iterdir() if p.is_file()):
                counts["blobs_seen"] += 1
                try:
                    raw, body = read_blob(blob)
                except OSError:
                    counts["blobs_unreadable"] += 1
                    continue
                if b"temperature_2m_member" not in body:
                    counts["blobs_skipped_not_ensemble"] += 1
                    continue
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    counts["blobs_unreadable"] += 1
                    continue
                res = extract_payload(payload, d)
                if res is None:
                    counts["blobs_skipped_not_ensemble"] += 1
                    continue
                counts["blobs_ensemble"] += 1
                sha = hashlib.sha256(raw).hexdigest()
                inputs.append({"path": f"{folder.name}/forecast_payloads/{blob.name}", "sha256": sha,
                               "bytes": len(raw)})
                mtime = datetime.fromtimestamp(blob.stat().st_mtime, timezone.utc).isoformat()
                unit = ((payload.get("hourly_units") or {}).get("temperature_2m"))
                for member, (node_max, n_nodes, n_want, day_max, n_day) in sorted(res.items()):
                    w.writerow((folder.name, d.isoformat(), blob.name, sha, mtime, payload.get("generationtime_ms"),
                                payload.get("utc_offset_seconds"), unit, member,
                                "" if node_max is None else repr(node_max), n_nodes, n_want,
                                "" if day_max is None else repr(day_max), n_day))
                    counts["rows"] += 1
    manifest = {"schema": "ro_capture_members/1", "window": [WINDOW[0].isoformat(), WINDOW[1].isoformat()],
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "node_steps_06z": list(NODE_STEPS), "counts": counts, "inputs": inputs,
                "output": {"path": csv_path.name, "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()}}
    (out / "ro_capture_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
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
