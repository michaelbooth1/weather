r"""B-1 market-coverage counts, capture-host side: integers only, one create-only sidecar per exported date.

Master ruling R19 (2026-11-01) and B-1 Clarification 4
(``docs/research/b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md``). B-1 section 3's
coverage drop needs, for every snapshot of D, how many band rows it has and how many carry a capture-time price
the B transfer will admit. The exporter's opt-in coverage field cannot give that (it counts snapshots the layout
rejects, keys them by each row's hour, treats inf as priced and sums per market), and the exporter, its wrapper
and registrar stay unchanged until after B. This module is the replacement vehicle for B-1 section 0(d).

* **What it reads.** Only D's ``snapshots_long.csv`` for the 11 fixed markets, through the exporter's own
  ``Source(coverage_counts=False)``: known path, link and reparse-point checks, the 30-minute quiet guard and the
  shared-read bounded range ``[0, size at open)``. Rows captured after ``export_cut_utc(D)`` (or with no
  parseable capture time) are skipped exactly as the exporter skips them.
* **What it writes.** Per snapshot ``[n_rows, n_priced]``, where ``n_priced`` counts rows whose ``market_yes``
  passes :func:`capture_price`. No price value is written, only those two integers. It also re-projects the rows
  to the bundle's ``snapshots_long.csv`` bytes and records whether that sha256 equals the published bundle's
  manifest entry: a false flag means the source changed after the export, which master rules on, outcome-blind,
  before the look.
* **Where.** ``<out>\_b_coverage\<D>.json`` (schema ``b_price_coverage/1``) and ``<D>.SHA256SUMS`` beside it,
  both create-only; the SUMS file is written last and marks the sidecar published. ``<out>`` defaults to
  ``<repo>\data\exports\mg2-inputs`` (the folder the workstation pulls over the share).
* **Catch-up.** ``--catch-up`` covers every published bundle from 2026-10-29 (B's D0) that has no sidecar yet;
  it is idempotent.

Where it lives: ``tools/research/``, not ``src/`` (master ruling 2026-11-01 on R19, option b, the R11 Head 1
pattern). The binding exporter's test pins that nothing under ``src/`` imports the exporter, and that test is not
edited before B's look; a test here pins that nothing under ``src/`` imports or names this module (the schema
family records only its ``b_price_coverage/1`` schema). It imports only the standard library, ``weather.paths``
and the exporter (itself stdlib plus the allow-list), so it runs on the capture host. Nothing imports it
(roll-free: tools and ``.ps1``). It never reads labels, settlements or prices, and never touches the share.

On the capture host it runs only through ``scripts\ops\b_price_coverage.ps1`` (host identity, 00:30-09:00, the
shared lease, a kill-on-close job, the PYTHONPATH pin proof for this tool and the exporter, 5 GiB free, UTC
memory freshness).

    python -P -B -m tools.research.b_price_coverage --data-root <repo>\data [--out <repo>\data\exports\mg2-inputs]
        (--date 2026-10-29 [--date ...] | --catch-up)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from weather import paths
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

SCHEMA = "b_price_coverage/1"
COVERAGE_DIR = "_b_coverage"
FIRST_DATE = date(2026, 10, 29)  # B-1 D0
SUMS_SUFFIX = ".SHA256SUMS"
SNAPSHOTS_LONG = "snapshots_long.csv"
DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CoverageRefused(RuntimeError):
    """A date cannot be counted (unpublished bundle, existing sidecar, bad output); nothing is written for it."""


def capture_price(value):
    """The capture-time price the B transfer admits: a finite float in [0, 1], else None (R-H's dev admission).

    The B transfer writes ``p_market_yes`` only through this function and NaN everywhere else, so
    ``b_scorer.priced_snapshots`` (finite on every band) and these counts agree by construction.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(str(value).strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or not 0.0 <= price <= 1.0:
        return None
    return price


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def default_out():
    return paths.data_path("exports", "mg2-inputs")


def coverage_paths(out, day):
    folder = Path(out) / COVERAGE_DIR
    return folder / f"{day.isoformat()}.json", folder / f"{day.isoformat()}{SUMS_SUFFIX}"


def published_bundle(out, day):
    """``(manifest, manifest_sha256, ready_matches)`` of the published bundle for ``day``; refuses when absent."""
    bundle = Path(out) / day.isoformat()
    manifest_path, ready = bundle / allow.MANIFEST, bundle / allow.MANIFEST_SHA
    if not ready.is_file() or not manifest_path.is_file():
        raise CoverageRefused(f"{day} has no published bundle under {out}")
    raw = manifest_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    ready_sha = ready.read_text(encoding="ascii").split()[0].strip().lower() if ready.stat().st_size else ""
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("target_date") != day.isoformat():
        raise CoverageRefused(f"{bundle} manifest is for {manifest.get('target_date')}, not {day}")
    return manifest, sha, ready_sha == sha


def count_market(src, market, day, cut, bundle_entry):
    """One market's counts and source record. ``bundle_entry`` is the bundle manifest's file entry or None."""
    slug = allow.slug_for(market, day)
    rel = f"snapshots/{slug}/{SNAPSHOTS_LONG}"
    fields = allow.CSV_FIELDS[SNAPSHOTS_LONG]
    counts, rows_in_cut, rows_after_cut = {}, 0, 0
    line, projected = mx._CsvLine(), hashlib.sha256()
    with src.text(rel) as handle:
        if handle is None:
            source = {"present": False}
        else:
            projected.update(line(fields))
            for row in csv.DictReader(handle):
                captured = mx.parse_time(row.get("captured_at_utc"))
                if captured is None or captured > cut:
                    rows_after_cut += 1
                    continue
                rows_in_cut += 1
                projected.update(line([row.get(k, "") or "" for k in fields]))
                sid = str(row.get("snapshot_id") or "")
                n_rows, n_priced = counts.get(sid, (0, 0))
                counts[sid] = (n_rows + 1, n_priced + int(capture_price(row.get(mx.PRICE_COLUMN)) is not None))
            opened = dict(src.opened.get(rel, {}))
            source = {"present": True, "source_bytes": int(opened["source_bytes"]),
                      "source_mtime_utc": opened["source_mtime_utc"],
                      "partial_tail_bytes": int(opened.get("partial_tail_bytes", 0)),
                      "read_mode": opened["read_mode"]}
    projected_sha = projected.hexdigest() if source["present"] else None
    bundle_sha = bundle_entry.get("sha256") if bundle_entry else None
    record = {**source, "path": rel, "rows_in_cut": rows_in_cut, "rows_after_cut_or_untimed": rows_after_cut,
              "projected_sha256": projected_sha, "bundle_sha256": bundle_sha,
              "match": projected_sha == bundle_sha}
    return {sid: [n, k] for sid, (n, k) in sorted(counts.items())}, record


def count_date(*, day, data_root, out, now=None):
    """Write ``<out>\\_b_coverage\\<D>.json`` and its SHA256SUMS (create-only). Returns the sidecar."""
    out = Path(out).resolve()
    data_root = Path(data_root).resolve()
    for forbidden_root in (data_root / "snapshots", data_root / "forecast_payload_cas"):
        if out == forbidden_root or forbidden_root in out.parents:
            raise CoverageRefused(f"output {out} is inside the capture tree {forbidden_root}")
    if day < FIRST_DATE:
        raise CoverageRefused(f"{day} is before B's D0 {FIRST_DATE}")
    now = now or datetime.now(timezone.utc)
    cut = allow.export_cut_utc(day)
    if now <= cut:
        raise CoverageRefused(f"{day}'s export cut {cut.isoformat()} has not passed")
    target, sums = coverage_paths(out, day)
    if target.exists() or sums.exists():
        raise CoverageRefused(f"{target} already exists: one sidecar per date (a json without SHA256SUMS is a "
                              f"killed run's leftover; inspect it by hand)")
    manifest, manifest_sha, ready_matches = published_bundle(out, day)
    entries = {str(e.get("path")): e for e in manifest.get("files") or []}
    src = mx.Source(data_root, coverage_counts=False)
    started = datetime.now(timezone.utc)
    counts, sources = {}, {}
    for market in allow.MARKETS:
        rel = f"snapshots/{allow.slug_for(market, day)}/{SNAPSHOTS_LONG}"
        counts[market], sources[market] = count_market(src, market, day, cut, entries.get(rel))
    match = ready_matches and all(s["match"] for s in sources.values())
    sidecar = {
        "schema": SCHEMA, "target_date": day.isoformat(), "export_cut_utc": cut.isoformat(),
        "counts_only": True, "predicate": "capture_price: a finite float in [0, 1], else not priced",
        "counts": counts, "sources": sources,
        "bundle": {"manifest_sha256": manifest_sha, "ready_marker_matches": ready_matches,
                   "exporter_sha256": manifest.get("exporter_sha256"),
                   "allowlist_sha256": manifest.get("allowlist_sha256")},
        "match": match, "module_sha256": module_sha256(), "exporter_module_sha256": _sha_file(mx.__file__),
        "allowlist_sha256": allow.allowlist_sha256(), "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    body = (json.dumps(sidecar, indent=1, sort_keys=True) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise CoverageRefused(f"{target} appeared during the run") from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    with open(sums, "xb") as handle:  # the published marker, last; LF on every host
        handle.write(f"{hashlib.sha256(body).hexdigest()}  {target.name}\n".encode("ascii"))
    return sidecar


def pending_dates(out):
    """Published bundle dates from ``FIRST_DATE`` with no sidecar SUMS yet, in order."""
    out = Path(out)
    if not out.is_dir():
        return []
    days = []
    for name in sorted(os.listdir(out)):
        if not DATE_DIR.match(name):
            continue
        try:
            day = date.fromisoformat(name)
        except ValueError:
            continue
        if day < FIRST_DATE:
            continue
        if not (out / name / allow.MANIFEST_SHA).is_file():
            continue
        if coverage_paths(out, day)[1].exists():
            continue
        days.append(day)
    return days


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m tools.research.b_price_coverage")
    parser.add_argument("--data-root", default=str(paths.data_path()))
    parser.add_argument("--out", default=str(default_out()),
                        help="the exporter's output root; sidecars go to <out>\\_b_coverage")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", action="append", help="target date D (repeatable)")
    group.add_argument("--catch-up", action="store_true",
                       help=f"every published bundle from {FIRST_DATE} with no sidecar yet")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    days = pending_dates(args.out) if args.catch_up else [date.fromisoformat(d) for d in args.date]
    status = 0
    for day in days:
        try:
            sidecar = count_date(day=day, data_root=args.data_root, out=args.out)
        except mx.FileTooFresh as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "too_fresh", "reason": str(exc)}))
            status = max(status, 3)
            continue
        except (CoverageRefused, mx.ExportRefused) as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "refused", "reason": str(exc)}))
            status = max(status, 2)
            continue
        print(json.dumps({"target_date": day.isoformat(), "status": "counted", "match": sidecar["match"],
                          "snapshots": sum(len(v) for v in sidecar["counts"].values())}))
        if not sidecar["match"]:
            status = max(status, 4)
    if not days:
        print(json.dumps({"status": "nothing_to_do"}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
