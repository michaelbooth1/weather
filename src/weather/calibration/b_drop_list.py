r"""B-1 section 3 coverage drop list, workstation side: log the host's counts, fix each date's verdict once, materialize.

Master ruling R19 (2026-11-01) and B-1 Clarification 4
(``docs/research/b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md``). Research and shadow
only; outcome-blind. Nothing here opens a label, settlement, price or transfer file: the host sidecar
(the host counts tool ``tools/research/`` runs through ``scripts/ops``; schema family ``b_coverage``, record
``b_coverage_sidecar``) carries integers only. This module never imports the host tool or the exporter.

* ``log``: copy ``<share-root>\_b_coverage\<D>.json`` and its ``<D>.SHA256SUMS`` into the local store, verify the
  sha256 against the SUMS line and the schema, and append one ``log`` row to the sibling ledger
  ``C:\t\mg2\forward\b_coverage_receipts.jsonl``. The share root is a parameter (master picks the address).
* ``verdict``: once per date, as soon as D's per-date layout and logged sidecar exist. Joins every layout snapshot
  to its ``[n_rows, n_priced]`` and calls ``b_scorer.market_coverage`` itself (the 10 markets, local 07-16, a
  snapshot priced when every band row carries an admitted capture-time price). The date is dropped when its share
  is below ``b_scorer.COVERAGE_MIN`` (0.90); a date with no 07-16 snapshot is dropped. It refuses on an unlogged
  sidecar sha, a sidecar whose ``match`` is false, a sidecar for another bundle, a layout snapshot the sidecar
  lacks, or ``n_rows`` different from the layout's band count. The verdict row is appended and never recomputed.
* ``materialize``: at the look, after the transfer has fixed the countable set and the 45-date window layout has
  been concatenated, and before MG-2 score: the logged verdicts of exactly the window's member dates, written
  create-only as ``b_drop_list/1`` (the file ``b_scorer look`` and ``b_look_wrapper look`` take as
  ``--drop-list``). It refuses on a member with no verdict or whose layout manifest sha differs from the
  verdict's. A logged date outside the window (not promotion-countable) is left out, so the drop list stays
  inside the look date set.

    python -m weather.calibration.b_drop_list log --share-root <share> --date 2026-10-29
    python -m weather.calibration.b_drop_list verdict --date 2026-10-29 --layout <per-date layout dir>
    python -m weather.calibration.b_drop_list materialize --window <concatenated layout dir> --out <drop list>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from weather.calibration import mg2_input_allowlist as allow
from weather.schema_families import schema_version
from weather.calibration import b_scorer  # refuses from a production package and on the capture host


def _refuse_production_import():
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in b_scorer._PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.b_drop_list is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

RECEIPT_SCHEMA = schema_version("b_coverage_receipt")
SIDECAR_SCHEMA = schema_version("b_coverage_sidecar")  # the host tool's sidecar schema
COVERAGE_DIR = "_b_coverage"  # beside the MG-2 input bundles on the share
SUMS_SUFFIX = ".SHA256SUMS"
DROP_LIST_SCHEMA = b_scorer.DROP_LIST_SCHEMA
LEDGER = Path(r"C:\t\mg2\forward\b_coverage_receipts.jsonl")
STORE = Path(r"C:\t\mg2\forward\b_coverage")
LAYOUT_FILES = ("inputs_snapshots.parquet", "inputs_bands.parquet")


class DropListRefused(RuntimeError):
    """The step cannot run; nothing is appended or written."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def module_sha256():
    return sha256_file(__file__)


def _now():
    return datetime.now(timezone.utc).isoformat()


def read_ledger(ledger, day=None, kind=None):
    path = Path(ledger)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if (day is None or r.get("target_date") == day.isoformat())
            and (kind is None or r.get("kind") == kind)]


def append_row(ledger, row):
    """Append one receipt line; the ledger is never rewritten."""
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": RECEIPT_SCHEMA, **row}
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


# ----------------------------------------------------------------------------- sidecar checks

def _sums_sha(path, name):
    lines = [ln.split() for ln in Path(path).read_text(encoding="ascii").splitlines() if ln.strip()]
    if len(lines) != 1 or len(lines[0]) != 2 or lines[0][1] != name:
        raise DropListRefused(f"{path} is not one '<sha256>  {name}' line")
    return lines[0][0].lower()


def sidecar_problems(sidecar, day):
    """Schema, date and integers-only shape of a host coverage sidecar (names only, never values)."""
    problems = []
    if sidecar.get("schema") != SIDECAR_SCHEMA:
        problems.append(f"schema {sidecar.get('schema')!r}")
    if sidecar.get("target_date") != day.isoformat():
        problems.append(f"target_date {sidecar.get('target_date')!r}")
    if sidecar.get("counts_only") is not True:
        problems.append("counts_only is not true")
    counts = sidecar.get("counts")
    if not isinstance(counts, dict) or sorted(counts) != sorted(allow.MARKETS):
        problems.append("counts markets")
    for market, snaps in (counts or {}).items() if isinstance(counts, dict) else ():
        for sid, pair in (snaps or {}).items():
            if not (isinstance(pair, list) and len(pair) == 2 and all(type(v) is int for v in pair)
                    and 0 <= pair[1] <= pair[0]):
                problems.append(f"counts {market}/{sid} is not [n_rows, n_priced] integers")
                break
    if not isinstance(sidecar.get("match"), bool):
        problems.append("match is not a boolean")
    if not isinstance((sidecar.get("bundle") or {}).get("manifest_sha256"), str):
        problems.append("bundle manifest sha256 missing")
    return problems


def log(*, share_root, day, store=STORE, ledger=LEDGER):
    """Copy and verify one date's sidecar from the share, then append a ``log`` row (idempotent per sha)."""
    name = f"{day.isoformat()}.json"
    src_dir = Path(share_root) / COVERAGE_DIR
    src, src_sums = src_dir / name, src_dir / f"{day.isoformat()}{SUMS_SUFFIX}"
    if not src_sums.is_file() or not src.is_file():
        return {"status": "not_ready", "target_date": day.isoformat()}
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    partial = store / f".{name}.partial"
    shutil.copyfile(src, partial)
    try:
        expected = _sums_sha(src_sums, name)
        sha = sha256_file(partial)
        if sha != expected:
            raise DropListRefused(f"{src} hashes to {sha}, not its SHA256SUMS {expected}")
        sidecar = json.loads(partial.read_text(encoding="utf-8"))
        problems = sidecar_problems(sidecar, day)
        if problems:
            raise DropListRefused(f"sidecar {src} refused: {problems}")
        logged = read_ledger(ledger, day, "log")
        if logged:
            if logged[0]["sidecar_sha256"] == sha:
                return {"status": "already_logged", **logged[0]}
            raise DropListRefused(f"{day} was logged with sidecar {logged[0]['sidecar_sha256']}; the share now has "
                                  f"{sha}: master rules before anything else")
        target = store / name
        if target.exists() and sha256_file(target) != sha:
            raise DropListRefused(f"{target} exists with other bytes and no log row: inspect it by hand")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return append_row(ledger, {"kind": "log", "target_date": day.isoformat(), "sidecar_sha256": sha,
                               "sidecar_path": str(target), "bundle_manifest_sha256":
                               sidecar["bundle"]["manifest_sha256"], "match": sidecar["match"],
                               "sidecar_module_sha256": sidecar.get("module_sha256"),
                               "module_sha256": module_sha256(), "logged_at_utc": _now()})


# ----------------------------------------------------------------------------- verdict

def read_layout(root, day):
    """One per-date layout (snapshots, bands) re-hashed against its manifest; ``(manifest, manifest_sha, s, b)``."""
    import pandas as pd

    root = Path(root)
    path = root / "manifest.json"
    if not path.is_file():
        raise DropListRefused(f"layout {root} has no manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("target_date") != day.isoformat():
        raise DropListRefused(f"layout {root} is for {manifest.get('target_date')}, not {day}")
    for name in LAYOUT_FILES:
        entry = (manifest.get("files") or {}).get(name) or {}
        if not (root / name).is_file() or sha256_file(root / name) != entry.get("sha256"):
            raise DropListRefused(f"layout {root}: {name} does not match its manifest")
    snaps = pd.read_parquet(root / LAYOUT_FILES[0])
    bands = pd.read_parquet(root / LAYOUT_FILES[1])
    if len(snaps) != manifest.get("snapshots") or (len(snaps) and set(snaps.date.astype(str)) != {day.isoformat()}):
        raise DropListRefused(f"layout {root}: snapshot rows do not match its target date {day}")
    return manifest, sha256_file(path), snaps, bands


def priced_from_counts(snaps, bands, counts):
    """Per layout row_key: True when every band row is priced. Refuses on a missing snapshot or a band mismatch."""
    import pandas as pd

    band_rows = bands.groupby("row_key").size()
    flags, problems = {}, []
    for key, market, sid, n_bands in zip(snaps.row_key, snaps.market.astype(str), snaps.snapshot_id,
                                         snaps.n_bands):
        pair = (counts.get(market) or {}).get(str(sid if sid is not None else ""))
        if pair is None:
            problems.append(f"{key}: no sidecar counts")
            continue
        n_rows, n_priced = pair
        if n_rows != int(n_bands) or n_rows != int(band_rows.get(key, 0)):
            problems.append(f"{key}: n_rows {n_rows} != n_bands {int(n_bands)} / band rows "
                            f"{int(band_rows.get(key, 0))}")
            continue
        flags[key] = n_rows > 0 and n_priced == n_rows
    if problems:
        raise DropListRefused(f"{len(problems)} layout snapshots do not join the sidecar: {problems[:5]}")
    return pd.Series(flags, dtype=bool)


def date_coverage(snaps, priced, day):
    """``b_scorer.market_coverage`` for one date; a date with no 07-16 snapshot of the 10 markets has share 0."""
    entry = b_scorer.market_coverage(snaps, priced).get(day.isoformat())
    if entry is None:
        return {"snapshots": 0, "priced": 0, "share": 0.0}
    return {"snapshots": int(entry["snapshots"]), "priced": int(entry["priced"]), "share": float(entry["share"])}


def verdict(*, day, layout, store=STORE, ledger=LEDGER):
    """Fix ``day``'s coverage verdict once from its per-date layout and logged sidecar; append it."""
    if read_ledger(ledger, day, "verdict"):
        raise DropListRefused(f"{day} already has a verdict: it is fixed once and never recomputed")
    logged = read_ledger(ledger, day, "log")
    if not logged:
        raise DropListRefused(f"{day} has no logged sidecar")
    if len(logged) != 1:
        raise DropListRefused(f"{day} has {len(logged)} log rows")
    path = Path(store) / f"{day.isoformat()}.json"
    if not path.is_file() or sha256_file(path) != logged[0]["sidecar_sha256"]:
        raise DropListRefused(f"{path} is missing or its sha is not the logged {logged[0]['sidecar_sha256']}")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    problems = sidecar_problems(sidecar, day)
    if problems:
        raise DropListRefused(f"sidecar {path} refused: {problems}")
    if sidecar["match"] is not True:
        raise DropListRefused(f"{day}'s sidecar match flag is false (the source changed since export): master "
                              f"rules, outcome-blind, before any verdict")
    manifest, manifest_sha, snaps, bands = read_layout(layout, day)
    if manifest.get("bundle_manifest_sha256") != sidecar["bundle"]["manifest_sha256"]:
        raise DropListRefused(f"layout bundle {manifest.get('bundle_manifest_sha256')} is not the sidecar's bundle "
                              f"{sidecar['bundle']['manifest_sha256']}")
    priced = priced_from_counts(snaps, bands, sidecar["counts"])
    coverage = date_coverage(snaps, priced, day)
    dropped = coverage["share"] < b_scorer.COVERAGE_MIN
    return append_row(ledger, {"kind": "verdict", "target_date": day.isoformat(), **coverage,
                               "coverage_min": b_scorer.COVERAGE_MIN, "dropped": dropped,
                               "layout_manifest_sha256": manifest_sha,
                               "bundle_manifest_sha256": manifest.get("bundle_manifest_sha256"),
                               "sidecar_sha256": logged[0]["sidecar_sha256"],
                               "b_scorer_sha256": b_scorer.module_sha256(), "module_sha256": module_sha256(),
                               "verdict_at_utc": _now()})


# ----------------------------------------------------------------------------- materialize

def materialize(*, window, out, ledger=LEDGER):
    """``b_drop_list/1`` from the logged verdicts of exactly the window layout's member dates (create-only)."""
    window = Path(window)
    path = window / "manifest.json"
    if not path.is_file():
        raise DropListRefused(f"window layout {window} has no manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    members = manifest.get("members") or []
    dates = [str(m.get("target_date")) for m in members]
    if not members or dates != sorted(set(dates)) or dates != list(manifest.get("dates") or []):
        raise DropListRefused("window members are missing, unordered, duplicated or differ from its dates")
    rows, problems = [], []
    for member in members:
        day = date.fromisoformat(member["target_date"])
        found = read_ledger(ledger, day, "verdict")
        if len(found) != 1:
            problems.append(f"{day}: {len(found)} verdict rows")
            continue
        if found[0]["layout_manifest_sha256"] != member.get("manifest_sha256"):
            problems.append(f"{day}: window member layout {member.get('manifest_sha256')} is not the verdict's "
                            f"{found[0]['layout_manifest_sha256']}")
            continue
        rows.append(found[0])
    if problems:
        raise DropListRefused(f"materialize refused: {problems[:5]}")
    payload = {"schema": DROP_LIST_SCHEMA, "dropped": sorted(r["target_date"] for r in rows if r["dropped"]),
               "dates": dates, "coverage_min": b_scorer.COVERAGE_MIN,
               "verdicts": [{k: r[k] for k in ("target_date", "snapshots", "priced", "share", "dropped",
                                               "layout_manifest_sha256", "sidecar_sha256")} for r in rows],
               "window_manifest_sha256": sha256_file(path), "ledger_sha256": sha256_file(ledger),
               "module_sha256": module_sha256(), "written_at_utc": _now()}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise DropListRefused(f"{out} exists: the drop list is written once") from exc
    return payload


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_drop_list")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("log", help="copy and verify one date's sidecar from the share; append a log row")
    p.add_argument("--share-root", required=True, help="the MG-2 input share root (master picks the address)")
    p.add_argument("--date", required=True)
    p.add_argument("--store", default=str(STORE))
    p.add_argument("--ledger", default=str(LEDGER))
    v = sub.add_parser("verdict", help="fix one date's coverage verdict once (per-date layout + logged sidecar)")
    v.add_argument("--date", required=True)
    v.add_argument("--layout", required=True, help="the per-date layout directory")
    v.add_argument("--store", default=str(STORE))
    v.add_argument("--ledger", default=str(LEDGER))
    m = sub.add_parser("materialize", help="b_drop_list/1 for the concatenated window layout's dates")
    m.add_argument("--window", required=True, help="the concatenated window layout directory")
    m.add_argument("--out", required=True)
    m.add_argument("--ledger", default=str(LEDGER))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "log":
            result = log(share_root=args.share_root, day=date.fromisoformat(args.date), store=args.store,
                         ledger=args.ledger)
        elif args.command == "verdict":
            result = verdict(day=date.fromisoformat(args.date), layout=args.layout, store=args.store,
                             ledger=args.ledger)
        else:
            payload = materialize(window=args.window, out=args.out, ledger=args.ledger)
            result = {"status": "written", "dropped": payload["dropped"], "dates": len(payload["dates"]),
                      "sha256": sha256_file(args.out)}
    except DropListRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
