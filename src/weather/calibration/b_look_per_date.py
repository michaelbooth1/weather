"""Per-date extraction for ruling (b): B's 07-16 / 07-12 / 13-16 cell differences summed per date.

Master ruling (i), 2026-10-31 (``docs/research/b-look-prep-2026-10-31/``). Research only. It runs in the same look
session, immediately after ``b_scorer look``, on the same sha-pinned transfer bytes the scorer consumed. It writes
only the per-date S_t (the sum of B's (date, market) cell differences, arm Brier minus market Brier) and n_t (the
cell count), for B's primary range and its two splits, beside B's look output, with its own receipt.

It reads no byte B did not, and it proves that before it writes anything:

- ``b_look.json`` is the one B's receipt names, and its verdict is scored (PASS, FAIL or INCONCLUSIVE, with outcomes
  opened);
- the running B scorer and scorecard are the shas B's look recorded;
- the gate vectors, drop list and transfer manifest hash to B's recorded inputs, and the transfer files hash to the
  manifest (``b_scorer.transfer_files``);
- the look date set, the drop list and the surviving count equal B's;
- per range, the snapshot count, the market-day count, the date count, both Briers and the estimate equal B's
  printed row (ALL markets), and sum(S) / sum(n) reproduces B's printed estimate (the delta guard) to DELTA_TOL.

The table is B's own: ``b_scorer.build_table`` and ``b_scorer.arm``, imported read-only; no B-bound file is edited.
The two output files are written with mode "x", so there is one extraction per look.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.calibration import b_scorer as b
from weather.calibration import mg2_composite as mg2

SCHEMA = "b_look_per_date/1"
RECEIPT_SCHEMA = "b_look_per_date_receipt/1"
PER_DATE = "b_per_date.json"
RECEIPT = "b_per_date_receipt.json"
RANGES = (b.PRIMARY,) + b.SPLITS
SCORED = ("PASS", "FAIL", "INCONCLUSIVE")
DELTA_TOL = 1e-12


class PerDateRefused(RuntimeError):
    """The extraction cannot prove it reads only B's bytes, or cannot reproduce B; nothing is written."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _close(a, b_, tol=DELTA_TOL):
    return a is not None and b_ is not None and abs(float(a) - float(b_)) <= tol * max(1.0, abs(float(b_)))


def _verify_look(look_out, vectors, drop_list, transfer):
    """B's look output and the inputs it recorded; returns (look payload, its sha, the receipt's sha)."""
    from weather.reporting.scorecards import dev_scorecard as sc

    look_path, receipt_path = Path(look_out) / b.LOOK, Path(look_out) / b.RECEIPT
    if not look_path.is_file() or not receipt_path.is_file():
        raise PerDateRefused(f"no B look output in {look_out}")
    look, receipt = b._json(look_path), b._json(receipt_path)
    look_sha = b.sha256_file(look_path)
    if receipt.get("b_look_sha256") != look_sha:
        raise PerDateRefused("b_look.json is not the file B's look receipt names")
    verdict = (look.get("decision") or {}).get("verdict")
    if verdict not in SCORED or look.get("outcomes_opened") is not True:
        raise PerDateRefused(f"B's look is {verdict!r}; only a scored look has per-date cells")
    if look.get("b_scorer_sha256") != b.module_sha256():
        raise PerDateRefused("the running B scorer is not the one B's look recorded")
    if look.get("scorecard_code_sha256") != sc.code_sha256():
        raise PerDateRefused("the running scorecard is not the one B's look recorded")
    inputs = look.get("inputs") or {}
    for key, path in (("vectors_sha256", vectors), ("drop_list_sha256", drop_list),
                      ("transfer_manifest_sha256", Path(transfer) / b.TRANSFER_MANIFEST)):
        if not Path(path).is_file() or inputs.get(key) != b.sha256_file(path):
            raise PerDateRefused(f"{key}: {path} is not the input B's look recorded")
    return look, look_sha, b.sha256_file(receipt_path)


def _dates(look, layout_root, drop_list):
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    look_dates = sorted(pd.read_parquet(Path(layout_root) / data.SNAPSHOTS_FILE, columns=["date"])
                        .date.astype(str).unique())
    if not look_dates or [look_dates[0], look_dates[-1], len(look_dates)] != look.get("look_dates"):
        raise PerDateRefused("the layout's look date set is not B's")
    dropped = sorted(str(d) for d in b._json(drop_list).get("dropped", []))
    if dropped != look.get("dropped"):
        raise PerDateRefused("the drop list is not B's")
    surviving = [d for d in look_dates if d not in set(dropped)]
    if len(surviving) != look.get("surviving_dates"):
        raise PerDateRefused("the surviving date count is not B's")
    return surviving


def per_date_cells(table, p, covered, ranges=RANGES):
    """Per range: B's ALL-market (date, market) cell differences summed per date, and B's row fields."""
    import numpy as np

    b_arm, b_mkt = table.brier(p), table.brier(table.p_market)
    hours = table.local_hour
    out = {}
    for name, lo, hi in ranges:
        mask = covered & (hours >= lo) & (hours <= hi)
        if not mask.any():
            out[name] = None
            continue
        idx, c = table.cells(b_arm, mask)
        _, m = table.cells(b_mkt, mask)
        sums = {}
        for i, diff in zip(idx, c - m):
            d = table.keys[i][0]
            s, n = sums.get(d, (0.0, 0))
            sums[d] = (s + float(diff), n + 1)
        out[name] = {"rows": [{"date": d, "S": s, "n": n} for d, (s, n) in sorted(sums.items())],
                     "n_snapshots": int(mask.sum()), "n_market_days": int(len(idx)), "n_dates": len(sums),
                     "brier_arm": float(c.mean()), "brier_market": float(m.mean()),
                     "estimate": float(np.sum(c - m) / len(idx))}
    return out


def reproduction_problems(cells, look):
    """Every range must reproduce B's printed ALL-market row; the primary also B's decision estimate."""
    problems = []
    for name, _, _ in RANGES:
        row, got = b._row(look.get("rows") or [], name), cells.get(name)
        if row is None or got is None:
            if row is not None or got is not None:
                problems.append(f"{name}: present in only one of B's rows and the extraction")
            continue
        for key in ("n_snapshots", "n_market_days", "n_dates"):
            if row.get(key) != got[key]:
                problems.append(f"{name} {key}: {got[key]} != B's {row.get(key)}")
        for key in ("brier_arm", "brier_market"):
            if not _close(got[key], row.get(key)):
                problems.append(f"{name} {key}: {got[key]!r} != B's {row.get(key)!r}")
        printed = (row.get("delta") or {}).get("estimate")
        total_s = sum(r["S"] for r in got["rows"])
        total_n = sum(r["n"] for r in got["rows"])
        if not _close(total_s / total_n, printed):
            problems.append(f"{name}: sum(S)/sum(n) {total_s / total_n!r} != B's printed estimate {printed!r}")
    primary = cells.get(b.PRIMARY[0])
    estimate = (look.get("decision") or {}).get("estimate")
    if primary is None or not _close(sum(r["S"] for r in primary["rows"]) / sum(r["n"] for r in primary["rows"]),
                                     estimate):
        problems.append(f"07-16 does not reproduce B's decision estimate {estimate!r}")
    return problems


def extract(*, look_out, layout_root, vectors, transfer, drop_list):
    """Write ``b_per_date.json`` and its receipt beside B's look output; returns the per-date payload."""
    import pandas as pd

    look_out = Path(look_out)
    for name in (PER_DATE, RECEIPT):
        if (look_out / name).exists():
            raise PerDateRefused(f"{look_out / name} exists: one extraction per look")
    look, look_sha, receipt_sha = _verify_look(look_out, vectors, drop_list, transfer)
    surviving = _dates(look, layout_root, drop_list)
    manifest, rows = b.read_manifest(transfer)
    if manifest is None:
        raise PerDateRefused(f"transfer manifest: {rows}")
    frames, problems = b.transfer_files(transfer, manifest)
    if problems:
        raise PerDateRefused(f"transfer files: {problems}")
    snaps, bands = mg2.read_inputs(layout_root)
    table = b.build_table(snaps, bands, frames["labels.parquet"], frames["market.parquet"], surviving)
    p, covered, _ = b.arm(table, pd.read_parquet(vectors))
    cells = per_date_cells(table, p, covered)
    problems = reproduction_problems(cells, look)
    if problems:
        raise PerDateRefused(f"the extraction does not reproduce B: {problems}")
    payload = {"schema": SCHEMA, "b_look_sha256": look_sha, "primary": cells[b.PRIMARY[0]]["rows"],
               "splits": {name: cells[name]["rows"] for name, _, _ in b.SPLITS if cells.get(name)}}
    _write_x(look_out / PER_DATE, payload)
    from weather.reporting.scorecards import dev_scorecard_data as data

    receipt = {"schema": RECEIPT_SCHEMA, "module_sha256": module_sha256(), "b_look_sha256": look_sha,
               "b_look_receipt_sha256": receipt_sha, "b_scorer_sha256": b.module_sha256(),
               "per_date_sha256": b.sha256_file(look_out / PER_DATE),
               "inputs": {"vectors_sha256": b.sha256_file(vectors), "drop_list_sha256": b.sha256_file(drop_list),
                          "transfer_manifest_sha256": b.sha256_file(Path(transfer) / b.TRANSFER_MANIFEST),
                          "transfer_files": dict(manifest["files"]),
                          "layout_snapshots_sha256": b.sha256_file(Path(layout_root) / data.SNAPSHOTS_FILE),
                          "layout_bands_sha256": b.sha256_file(Path(layout_root) / data.BANDS_FILE)},
               "reproduced": {name: {k: cells[name][k] for k in ("n_market_days", "n_dates", "estimate")}
                              for name, _, _ in RANGES if cells.get(name)},
               "extracted_at_utc": datetime.now(timezone.utc).isoformat()}
    _write_x(look_out / RECEIPT, receipt)
    return payload


def _write_x(path, payload):
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_look_per_date",
                                     description=__doc__.splitlines()[0])
    for name in ("look-out", "layout", "vectors", "transfer", "drop-list"):
        parser.add_argument(f"--{name}", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        payload = extract(look_out=args.look_out, layout_root=args.layout, vectors=args.vectors,
                          transfer=args.transfer, drop_list=args.drop_list)
    except PerDateRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"dates": len(payload["primary"]), "splits": sorted(payload["splits"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
