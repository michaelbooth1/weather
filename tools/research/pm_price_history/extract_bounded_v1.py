"""Bounded one-shot extractor for 3a labels (O-1) and floor observations (O-2): rows dated <= 2026-05-26 only.

Master's terms (row 113, O-1/O-2):
- reads the rolling WU daily files (``--kind daily``) or the hourly observation partitions (``--kind hourly``)
  under ``--source-root`` (a parameter; no host or share is hard-coded) and emits ONLY rows whose
  ``local_date`` is within ``--first``..``--last`` with ``--last`` <= 2026-05-26;
- NEVER writes, counts or logs anything about a later row: no skipped count, no maximum date, no source row
  total, no source sha or size. Every counter in the manifest is over emitted rows only;
- an unparseable or missing ``local_date`` refuses the whole extraction (fail closed) without echoing the row;
  every exception is reported by its type only;
- hourly partitions (``year=YYYY/month=MM``) whose month starts after ``--last`` are never opened;
- writes the extract, ``manifest.json`` (script sha256, arguments, emitted counts) and ``SHA256SUMS``, then
  marks every output read-only. The output directory must not exist.

Refuses unless ``--expect-sha`` equals this file's sha256. No network. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HARD_LAST = date(2026, 5, 26)
DEFAULT_FIRST = date(2025, 1, 1)
B12_ICAO = ("cyyz", "katl", "kaus", "kbkf", "kdal", "khou", "klax", "klga", "kmia", "kord", "ksea", "ksfo")
DAILY_NAME = "daily_summary.csv"
HOURLY_NAME = "observations.jsonl"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_PART = re.compile(r"year=(\d{4})[\\/]month=(\d{2})[\\/]" + re.escape(HOURLY_NAME) + r"$")
_ICAO = re.compile(r"[a-z0-9]{4}")


class Refusal(Exception):
    """Fail-closed refusal. Its message never carries source content."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def strict_date(text) -> date:
    """YYYY-MM-DD exactly, a real calendar date; anything else refuses without echoing the value."""
    if not isinstance(text, str) or not _DATE.fullmatch(text):
        raise Refusal("refused: a row has a missing or unparseable local_date (row not echoed)")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise Refusal("refused: a row has a missing or unparseable local_date (row not echoed)") from None


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return start, date.fromordinal(nxt.toordinal() - 1)


class Emitted:
    def __init__(self):
        self.files = {}

    def add(self, rel: str, d: date):
        f = self.files.setdefault(rel, {"rows": 0, "first": None, "last": None})
        f["rows"] += 1
        iso = d.isoformat()
        f["first"] = iso if f["first"] is None or iso < f["first"] else f["first"]
        f["last"] = iso if f["last"] is None or iso > f["last"] else f["last"]


def extract_daily(src_root: Path, out: Path, stations, first: date, last: date, em: Emitted):
    for icao in stations:
        src = src_root / icao / "daily" / DAILY_NAME
        if not src.is_file():
            continue
        rel = f"{icao}/{DAILY_NAME}"
        dst = out / icao / DAILY_NAME
        dst.parent.mkdir(parents=True, exist_ok=False)
        with open(src, encoding="utf-8", newline="") as h:
            reader = csv.DictReader(h)
            header = reader.fieldnames
            if not header or "local_date" not in header:
                raise Refusal("refused: a daily file has no local_date column")
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                d = strict_date(row.get("local_date"))
                if first <= d <= last:
                    writer.writerow(row)
                    em.add(rel, d)
        with open(dst, "x", encoding="utf-8", newline="") as w:
            w.write(buf.getvalue())


def hourly_partitions(base: Path, first: date, last: date):
    """Partitions overlapping first..last, selected from folder names alone (later months never opened)."""
    out = []
    for year_dir in sorted(base.glob("year=*")):
        for month_dir in sorted(year_dir.glob("month=*")):
            path = month_dir / HOURLY_NAME
            m = _PART.search(str(path).replace("\\", "/"))
            if not m:
                continue
            lo, hi = month_bounds(int(m.group(1)), int(m.group(2)))
            if lo <= last and hi >= first and path.is_file():
                out.append((int(m.group(1)), int(m.group(2)), path))
    return out


def extract_hourly(src_root: Path, out: Path, stations, first: date, last: date, em: Emitted):
    for icao in stations:
        base = src_root / icao / "hourly"
        if not base.is_dir():
            continue
        for year, month, src in hourly_partitions(base, first, last):
            rel = f"{icao}/hourly/year={year:04d}/month={month:02d}/{HOURLY_NAME}"
            kept = []
            with open(src, encoding="utf-8") as h:
                for line in h:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        raise Refusal("refused: an hourly line is not valid JSON (line not echoed)") from None
                    if not isinstance(row, dict):
                        raise Refusal("refused: an hourly line is not an object (line not echoed)")
                    d = strict_date(row.get("local_date"))
                    if first <= d <= last:
                        kept.append(line if line.endswith("\n") else line + "\n")
                        em.add(rel, d)
            if kept:
                dst = out / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open(dst, "x", encoding="utf-8", newline="") as w:
                    w.writelines(kept)


def make_read_only(root: Path):
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            os.chmod(path, stat.S_IREAD)


def run(args, script_sha: str) -> dict:
    first = strict_date(args.first)
    last = strict_date(args.last)
    if last > HARD_LAST:
        raise Refusal(f"refused: --last after {HARD_LAST.isoformat()}")
    if first > last:
        raise Refusal("refused: --first after --last")
    stations = tuple(s.strip().lower() for s in args.stations.split(",") if s.strip())
    if not stations or any(not _ICAO.fullmatch(s) for s in stations):
        raise Refusal("refused: --stations must be four-character station ids")
    src_root = Path(args.source_root)
    if not src_root.is_dir():
        raise Refusal("refused: --source-root is not a directory")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out_root) / f"extract-{args.kind}-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    em = Emitted()
    (extract_daily if args.kind == "daily" else extract_hourly)(src_root, out, stations, first, last, em)
    files = {rel: {**v, "sha256": sha256_file(out / rel)} for rel, v in sorted(em.files.items())}
    if args.kind == "daily":
        for rel in sorted(p.relative_to(out).as_posix() for p in out.rglob(DAILY_NAME)):
            files.setdefault(rel, {"rows": 0, "first": None, "last": None, "sha256": sha256_file(out / rel)})
    manifest = {"schema": "pm_history_bounded_extract/1", "kind": args.kind, "first": first.isoformat(),
                "last": last.isoformat(), "hard_last": HARD_LAST.isoformat(), "stations": list(stations),
                "source_root": str(src_root), "script": Path(__file__).name, "script_sha256": script_sha,
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "counters_note": "every counter is over emitted rows only; nothing about any later row is recorded",
                "emitted_rows_total": sum(v["rows"] for v in files.values()), "files": files}
    with open(out / "manifest.json", "x", encoding="utf-8") as h:
        h.write(json.dumps(manifest, indent=1, sort_keys=True))
    lines = [f"{sha256_file(out / rel)}  {rel}" for rel in [*files, "manifest.json"]]
    with open(out / "SHA256SUMS", "x", encoding="utf-8", newline="\n") as h:
        h.write("\n".join(lines) + "\n")
    make_read_only(out)
    return {"out": str(out), "manifest_sha256": sha256_file(out / "manifest.json"),
            "sha256sums_sha256": sha256_file(out / "SHA256SUMS"), "emitted_rows_total": manifest["emitted_rows_total"],
            "files": len(files), "script_sha256": script_sha}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kind", required=True, choices=("daily", "hourly"))
    ap.add_argument("--source-root", required=True, help="the wunderground data root (parameter)")
    ap.add_argument("--stations", default=",".join(B12_ICAO))
    ap.add_argument("--first", default=DEFAULT_FIRST.isoformat())
    ap.add_argument("--last", default=HARD_LAST.isoformat())
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--expect-sha", required=True)
    args = ap.parse_args(argv)
    script_sha = sha256_file(Path(__file__).resolve())
    if args.expect_sha != script_sha:
        print(f"refused: --expect-sha must equal this script's sha256 {script_sha}", file=sys.stderr)
        return 2
    try:
        result = run(args, script_sha)
    except Refusal as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:                                          # type only: no source content
        print(f"refused: extraction failed ({type(exc).__name__}); nothing about source rows recorded",
              file=sys.stderr)
        return 3
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
