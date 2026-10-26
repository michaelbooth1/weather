"""Lane L12: verify and seal an NBM NBS/NBH station-block corpus built by nbm_nbs_nbh_fetch.py.

Re-hashes every blocks file and every station block against its manifest row, then writes
``SHA256SUMS`` (manifest plus every ``raw/**/*.blocks`` file, sha256sum format, POSIX relative
paths) and ``coverage.md`` (ok blocks / planned objects per product x station x year, every
station x year x cycle cell below 100%, and the gap list). Offline; reads and writes only under
the corpus directory. Run it with ``python -I`` because the corpus holds downloaded bytes.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path


def load_manifest(root):
    """{(utc_date, cycle, product): row}; a later row for the same key wins (resume refetch)."""
    rows = {}
    with (Path(root) / "manifest.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[(r["utc_date"], r["cycle"], r["product"])] = r
    return rows


def verify(root, rows):
    """(mismatches, ok counter keyed (product, station, year, cycle), expected counter, gaps, stations)."""
    root = Path(root)
    bad = []
    ok = collections.Counter()
    expect = collections.Counter()
    gaps = []
    stations = set()
    for (d, c, p), r in sorted(rows.items()):
        y = d[:4]
        expect[(p, y, c)] += 1
        if r["status"] != "ok":
            gaps.append(f"{d} {c}Z {p}: {r['status']}")
            continue
        blob = (root / r["blocks_file"]).read_bytes()
        if hashlib.sha256(blob).hexdigest() != r["blocks_sha256"]:
            bad.append(r["blocks_file"])
        for st, v in r["stations"].items():
            stations.add(st)
            if v["status"] != "ok":
                gaps.append(f"{d} {c}Z {p} {st}: {v['status']} (object size {r['size']})")
                continue
            piece = blob[v["file_offset"]: v["file_offset"] + v["length"]]
            if hashlib.sha256(piece).hexdigest() != v["sha256"]:
                bad.append(f"{r['blocks_file']}#{st}")
            ok[(p, st, y, c)] += 1
    return bad, ok, expect, gaps, sorted(stations)


def write_sha256sums(root):
    root = Path(root)
    files = sorted([root / "manifest.jsonl"] + list((root / "raw").rglob("*.blocks")))
    with (root / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as fh:
        for f in files:
            fh.write(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(root).as_posix()}\n")
    return files, hashlib.sha256((root / "SHA256SUMS").read_bytes()).hexdigest()


def coverage_lines(root, ok, expect, gaps, stations, n_objects, n_files, n_bad, sums_sha):
    years = sorted({k[1] for k in expect})
    cycles = sorted({k[2] for k in expect})
    products = [p for p in ("nbs", "nbh") if any(k[0] == p for k in expect)]
    out = [f"# Coverage: {root}", "", f"objects {n_objects}, files {n_files}, hash mismatches {n_bad}",
           f"SHA256SUMS sha256 {sums_sha}", ""]
    for p in products:
        out.append(f"## {p.upper()}: ok blocks / planned objects, station x year "
                   f"(all cycles {cycles[0]}-{cycles[-1]}Z)")
        out.append("| station | " + " | ".join(years) + " |")
        out.append("| --- |" + " --- |" * len(years))
        for st in stations:
            cells = [f"{sum(ok[(p, st, y, c)] for c in cycles)}/{sum(expect[(p, y, c)] for c in cycles)}"
                     for y in years]
            out.append(f"| {st} | " + " | ".join(cells) + " |")
        out.append("")
        out.append(f"## {p.upper()}: cycles with any missing block (station x year x cycle cells below 100%)")
        short = [f"{st} {y} {c}Z {ok[(p, st, y, c)]}/{expect[(p, y, c)]}"
                 for st in stations for y in years for c in cycles
                 if expect[(p, y, c)] and ok[(p, st, y, c)] < expect[(p, y, c)]]
        out.extend(short or ["none"])
        out.append("")
    out.append("## Gaps")
    out.extend(gaps or ["none"])
    return out


def finalize(root):
    root = Path(root)
    rows = load_manifest(root)
    bad, ok, expect, gaps, stations = verify(root, rows)
    files, sums_sha = write_sha256sums(root)
    lines = coverage_lines(root, ok, expect, gaps, stations, len(rows), len(files), len(bad), sums_sha)
    (root / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"objects": len(rows), "files": len(files), "bytes": sum(f.stat().st_size for f in files),
            "mismatches": bad, "gaps": gaps, "sha256sums": sums_sha}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus_dir")
    args = ap.parse_args(argv)
    res = finalize(args.corpus_dir)
    print(f"objects={res['objects']} files={res['files']} bytes={res['bytes']} "
          f"mismatches={len(res['mismatches'])} gaps={len(res['gaps'])} sha256sums={res['sha256sums']}")
    return 1 if res["mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
