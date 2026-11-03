"""B-1 post-look disclosure: cells whose paying band the rule-4 floor zeroed (any cause). Descriptive, non-deciding.

Source: lane L51's accepted draft (``claude/b-speci-disclosure-20261101`` @ ``468aa514c``, file
``docs/research/b-floor-disclosure-2026-11-01/b1-clarification-floor-zeroed-band-disclosure-2026-11-01.md``) and
master's 2026-11-03 build ruling. The measure is "paying band zeroed by the rule-4 floor (any cause)". SPECI
attribution is given only if a SPECI flag is in B's bytes.

It runs in B's look session after a scored ``b_scorer`` look (PASS, FAIL or INCONCLUSIVE), on exactly the bytes
B read. It proves that before it writes anything, with the per-date extractor's own checks
(``b_look_per_date._verify_look`` and ``_dates``):

- ``b_look.json`` is the file B's receipt names, its verdict is scored and its outcomes were opened;
- the running B scorer and scorecard are the shas B's look recorded;
- the vectors, drop list and transfer manifest are B's recorded inputs, and the transfer files hash to the
  manifest;
- the look dates, drop list and surviving count are B's;
- B's printed ALL-market 07-16 row (counts, both Briers, the estimate and its interval) is reproduced
  (``REPRODUCTION_TOL``).

What it reports, every number labelled descriptive and non-deciding:

1. ``zeroed_cells``. A zeroed snapshot is a covered 07-16 snapshot whose paying band (label y = 1) has
   ``Table.impossible`` true; MG-2's scored probability for that band is then exactly 0, which is checked. It
   reports the (date, market) cells with at least one zeroed snapshot, out of B's scored cells, one row per cell:
   date, market, covered 07-16 snapshots, zeroed snapshots, first zeroed local hour, and the cell's arm-minus-market
   Brier difference.
2. ``without_zeroed_cells``. Delta(07-16) recomputed by ``b_scorer.excess_rows`` with every snapshot of those cells
   removed from both arms: the same date-clustered interval (``Table.w_date``) restricted to the remaining cells.
   If (1) is empty, it is B's primary row, marked as such.
3. ``speci_attribution``. It is computed only from a SPECI flag in B's bytes. The layout, vectors and transfer
   files B reads carry no such flag (no column named for one), so this revision reports NOT_COMPUTED with the
   columns it checked. It never opens MG-2's bundle or any METAR file. A flag column appearing would still be
   NOT_COMPUTED here: an attribution method needs its own pinned revision.

Nothing here changes, rescues, re-labels or qualifies B's verdict, its label or any VOID. ``b_scorer``,
``b_look_per_date`` and ``mg2_composite`` are imported read-only; no B-bound file is edited. Both outputs are
written with mode "x" beside B's look output: one disclosure per look.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.calibration import b_look_per_date as pdx
from weather.calibration import b_scorer as b
from weather.calibration import mg2_composite as mg2

SCHEMA = "b_floor_disclosure_v1"
RECEIPT_SCHEMA = "b_floor_disclosure_receipt_v1"
DISCLOSURE = "b_floor_disclosure.json"
RECEIPT = "b_floor_disclosure_receipt.json"
LABEL = "descriptive, non-deciding"
MEASURE = "paying band zeroed by the rule-4 floor (any cause)"
REPRODUCTION_TOL = 1e-12
# Column-name tokens that would mark a SPECI flag in B's bytes (lower-cased substring match on column names only).
SPECI_FLAG_TOKENS = ("speci", "report_type", "metar_type", "metartype")
NOT_COMPUTED = "NOT_COMPUTED"


class DisclosureRefused(RuntimeError):
    """The disclosure cannot prove it reads only B's bytes, or cannot reproduce B; nothing is written."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _close(a, b_, tol=REPRODUCTION_TOL):
    return a is not None and b_ is not None and abs(float(a) - float(b_)) <= tol * max(1.0, abs(float(b_)))


def primary_row(table, p, covered):
    """B's own ALL-market 07-16 row (``b_scorer.excess_rows``), or None when nothing is covered."""
    rows = b.excess_rows(table, p, covered, groups=(b.PRIMARY,), per_market=False)
    return b._row(rows, b.PRIMARY[0])


def row_problems(got, printed):
    """Every field of B's printed 07-16 row the disclosure must reproduce before it reports."""
    if got is None or printed is None:
        return ["07-16: missing from B's rows or from the disclosure's table"]
    problems = [f"07-16 {k}: {got[k]} != B's {printed.get(k)}" for k in ("n_snapshots", "n_market_days", "n_dates")
                if got[k] != printed.get(k)]
    problems += [f"07-16 {k}: {got[k]!r} != B's {printed.get(k)!r}" for k in ("brier_arm", "brier_market")
                 if not _close(got[k], printed.get(k))]
    mine, theirs = got["delta"], printed.get("delta") or {}
    if not _close(mine.get("estimate"), theirs.get("estimate")):
        problems.append(f"07-16 estimate {mine.get('estimate')!r} != B's {theirs.get('estimate')!r}")
    ci, ci_b = mine.get("ci95") or [None, None], theirs.get("ci95") or [None, None]
    if len(ci_b) != 2 or not all(_close(x, y) for x, y in zip(ci, ci_b)):
        problems.append(f"07-16 ci95 {ci!r} != B's {ci_b!r}")
    return problems


def zeroed_snapshots(table, p, covered):
    """Covered 07-16 snapshots whose paying band is floor-impossible, and the 07-16 covered mask."""
    import numpy as np

    _, lo, hi = b.PRIMARY
    window = covered & (table.local_hour >= lo) & (table.local_hour <= hi)
    paying_impossible = np.add.reduceat(table.y * table.impossible, table.offsets) > 0
    zeroed = window & paying_impossible
    paying_p = np.add.reduceat(p * table.y, table.offsets)
    if (paying_p[zeroed] != 0.0).any():
        raise DisclosureRefused("a zeroed snapshot's paying band is not scored exactly 0 by the arm")
    return zeroed, window


def zeroed_cells(table, p, covered):
    """(1): one row per (date, market) cell with at least one zeroed snapshot, and the snapshot mask of those cells."""
    import numpy as np

    zeroed, window = zeroed_snapshots(table, p, covered)
    idx, c = table.cells(table.brier(p), window)
    _, m = table.cells(table.brier(table.p_market), window)
    diff = dict(zip(idx.tolist(), (c - m).tolist()))
    hit = sorted(set(table.cell[zeroed].tolist()))
    rows = []
    for cell in hit:
        in_cell = table.cell == cell
        hours = table.local_hour[zeroed & in_cell]
        date_, market = table.keys[cell]
        rows.append({"date": date_, "market": market, "covered_snapshots": int((window & in_cell).sum()),
                     "zeroed_snapshots": int((zeroed & in_cell).sum()), "first_zeroed_local_hour": int(hours.min()),
                     "arm_minus_market_brier": float(diff[cell])})
    return {"label": LABEL, "measure": MEASURE, "n_cells": len(rows), "n_scored_cells": int(len(idx)),
            "n_zeroed_snapshots": int(zeroed.sum()), "cells": rows}, np.isin(table.cell, hit)


def without_cells(table, p, covered, drop, b_primary):
    """(2): Delta(07-16) with every snapshot of the zeroed cells removed from both arms."""
    if not drop.any():
        return {"label": LABEL, "same_as_b_primary": True, "estimate": b_primary["delta"]["estimate"],
                "ci95": b_primary["delta"]["ci95"], "n_market_days": b_primary["n_market_days"],
                "n_dates": b_primary["n_dates"]}
    row = primary_row(table, p, covered & ~drop)
    if row is None:
        return {"label": LABEL, "same_as_b_primary": False, "estimate": None, "ci95": [None, None],
                "n_market_days": 0, "n_dates": 0}
    return {"label": LABEL, "same_as_b_primary": False, "estimate": row["delta"]["estimate"],
            "ci95": row["delta"]["ci95"], "n_market_days": row["n_market_days"], "n_dates": row["n_dates"]}


def speci_flag_columns(frames):
    """Column names in B's bytes that would carry a SPECI flag (names only; no value is read)."""
    found = []
    for name, frame in sorted(frames.items()):
        found += [f"{name}:{col}" for col in frame.columns
                  if any(token in str(col).lower() for token in SPECI_FLAG_TOKENS)]
    return sorted(found)


def speci_attribution(frames):
    """(3): NOT_COMPUTED in this revision, with the reason and the B-byte columns checked."""
    flagged = speci_flag_columns(frames)
    reason = ("no SPECI flag in B's bytes (layout, vectors, transfer files)" if not flagged else
              "a SPECI-named column is in B's bytes, but no attribution method is pinned in this revision")
    return {"label": LABEL, "status": NOT_COMPUTED, "reason": reason, "flag_columns": flagged,
            "checked": {name: sorted(str(c) for c in frame.columns) for name, frame in sorted(frames.items())}}


def disclose(*, look_out, layout_root, vectors, transfer, drop_list):
    """Write the disclosure and its receipt beside B's look output; returns the disclosure payload."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    look_out = Path(look_out)
    for name in (DISCLOSURE, RECEIPT):
        if (look_out / name).exists():
            raise DisclosureRefused(f"{look_out / name} exists: one disclosure per look")
    try:
        look, look_sha, receipt_sha = pdx._verify_look(look_out, vectors, drop_list, transfer)
        surviving = pdx._dates(look, layout_root, drop_list)
    except pdx.PerDateRefused as exc:
        raise DisclosureRefused(str(exc)) from exc
    manifest, rows = b.read_manifest(transfer)
    if manifest is None:
        raise DisclosureRefused(f"transfer manifest: {rows}")
    files, problems = b.transfer_files(transfer, manifest)
    if problems:
        raise DisclosureRefused(f"transfer files: {problems}")
    snaps, bands = mg2.read_inputs(layout_root)
    vector_frame = pd.read_parquet(vectors)
    table = b.build_table(snaps, bands, files["labels.parquet"], files["market.parquet"], surviving)
    p, covered, _ = b.arm(table, vector_frame)
    b_primary = primary_row(table, p, covered)
    problems = row_problems(b_primary, b._row(look.get("rows") or [], b.PRIMARY[0]))
    if problems:
        raise DisclosureRefused(f"the disclosure does not reproduce B: {problems}")
    cells, drop = zeroed_cells(table, p, covered)
    frames = {"layout_snapshots": snaps, "layout_bands": bands, "vectors": vector_frame,
              "transfer_labels": files["labels.parquet"], "transfer_market": files["market.parquet"]}
    decision = look.get("decision") or {}
    payload = {"schema": SCHEMA, "label": LABEL, "b_look_sha256": look_sha,
               "b_verdict": decision.get("verdict"), "b_label": decision.get("label"),
               "b_primary": {"estimate": b_primary["delta"]["estimate"], "ci95": b_primary["delta"]["ci95"]},
               "zeroed_cells": cells, "without_zeroed_cells": without_cells(table, p, covered, drop, b_primary),
               "speci_attribution": speci_attribution(frames),
               "effect_on_b": "none: B's verdict, label and VOID conditions are unchanged"}
    _write_x(look_out / DISCLOSURE, payload)
    receipt = {"schema": RECEIPT_SCHEMA, "module_sha256": module_sha256(), "b_look_sha256": look_sha,
               "b_look_receipt_sha256": receipt_sha, "b_scorer_sha256": b.module_sha256(),
               "disclosure_sha256": b.sha256_file(look_out / DISCLOSURE),
               "inputs": {"vectors_sha256": b.sha256_file(vectors), "drop_list_sha256": b.sha256_file(drop_list),
                          "transfer_manifest_sha256": b.sha256_file(Path(transfer) / b.TRANSFER_MANIFEST),
                          "transfer_files": dict(manifest["files"]),
                          "layout_snapshots_sha256": b.sha256_file(Path(layout_root) / data.SNAPSHOTS_FILE),
                          "layout_bands_sha256": b.sha256_file(Path(layout_root) / data.BANDS_FILE)},
               "disclosed_at_utc": datetime.now(timezone.utc).isoformat()}
    _write_x(look_out / RECEIPT, receipt)
    return payload


def _write_x(path, payload):
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_floor_disclosure",
                                     description=__doc__.splitlines()[0])
    for name in ("look-out", "layout", "vectors", "transfer", "drop-list"):
        parser.add_argument(f"--{name}", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        payload = disclose(look_out=args.look_out, layout_root=args.layout, vectors=args.vectors,
                           transfer=args.transfer, drop_list=args.drop_list)
    except DisclosureRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"label": LABEL, "zeroed_cells": payload["zeroed_cells"]["n_cells"],
                      "speci_attribution": payload["speci_attribution"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
