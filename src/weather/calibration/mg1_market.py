r"""The look's ``--market`` file, capture-host side: per-date capture-price files to one ``market.parquet``.

Master rulings of 2026-11-03 on ``--market`` (MG-1 and B). Research only. ``mg1_look run --market`` reads the
file this module writes (and, on B's look morning, ``b_transfer write --market``, each with its own layout). It
reads the per-date files of the host price tool (``tools/research/capture_price_export.py``) and the look's
label-free layout, and writes ``market.parquet`` plus ``mg1_market_manifest.json``.

EMBARGO (master 2026-11-03, --market ruling 2). This concat is a REGISTERED STEP OF THE LOOK PATH:

* it runs ONLY on that test's look morning, after the 45th date's finality (the price tool refuses before it),
  under master's lease, in the same session as the look, ON THE CAPTURE HOST;
* neither this concat nor the look ever exports a price CSV or parquet to the workstation before the look
  receipt. ``--out`` must be a new local folder: an export channel the workstation pulls (``data\exports``),
  the capture tree and any UNC (share) path are refused;
* its stdout and manifest carry counts, shas and booleans only. No agent or human views a price value;
* the same rule as B's T4: a finite price outside [0, 1] REFUSES (exit 4, held), so the look is HELD.

What it checks, before anything is written:

* every layout date has a published price file set (``<D>.SHA256SUMS`` naming exactly the prices CSV and the
  ``capture_price_export/1`` receipt at their shas), for this look id and date;
* each layout band ``(row_key, kind, low, high)`` matches exactly one price row; that gives its
  ``band_index``. A layout band with no price row refuses (unmatched). Two price rows for one layout band refuse
  (duplicate). Price rows of snapshots the layout dropped are counted and ignored;
* every matched price is empty (unpriced, written NaN) or a finite float in [0, 1], and no matched row carries
  the tool's ``out_of_range`` flag. Otherwise it holds.

The manifest (``mg1_market/1``, written last, mode "x") records the look id, the layout and market shas, per
date the SUMS, prices and receipt shas with the receipt's R19 cross-check (``none_before_r19`` is disclosed for
10-15..10-28, master ruling 5), the counts, and ``range_ok`` and ``duplicate_free``, which ``mg1_look``'s
pre-stamp check requires to be true. A refused run writes nothing, so a written manifest has both true.

Host-only guard (master asked for one "of the right kind"). This module must run where the prices are, so it
is the inverse of ``mg2_inputs``' capture-host refusal: ``build`` refuses unless ``weather.execution_host``'s
current id equals the tracked assignment's ``dedicated_capture_execution_host_id``. That is the same identity
check the R19 counts tool's host wrapper (``scripts/ops``) makes before it admits that tool. It is a run-time
check, not an import-time one, so the workstation's tests can import the module and fake the identity. The
portable-execution status is not consulted: this is not live execution. Master's host ``.ps1`` adds the lease
and the window.

Nothing under ``src/`` imports the host tool: its file-name constants are copied here and pinned equal by a
test.

    python -m weather.calibration.mg1_market build --look mg1 --layout <layout dir> --prices <price tool out>
        --out <new local folder>

Exit codes: 0 written; 2 refused; 4 held (an out-of-range price).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather import paths

NAME = "mg1_market"
SCHEMA = "mg1_market/1"
MANIFEST = "mg1_market_manifest.json"
MARKET_FILE = "market.parquet"
MARKET_COLUMNS = ("row_key", "band_index", "p_market_yes")
LOOK_IDS = ("mg1", "b")
LAYOUT_SNAPSHOTS = "inputs_snapshots.parquet"
LAYOUT_BANDS = "inputs_bands.parquet"
# Copied from tools/research/capture_price_export.py (pinned equal by tests/calibration/test_mg1_market.py).
PRICES_SCHEMA = "capture_price_export/1"
PRICES_SUFFIX = ".prices.csv"
RECEIPT_SUFFIX = ".capture_prices.json"
SUMS_SUFFIX = ".SHA256SUMS"
PRICES_COLUMNS = ("row_key", "kind", "low", "high", "p_market_yes", "out_of_range")
EXIT_REFUSED, EXIT_HELD = 2, 4


class MarketRefused(RuntimeError):
    """The market file cannot be built; nothing was written."""

    exit_code = EXIT_REFUSED


class MarketHeld(MarketRefused):
    """A matched price is out of range (B's T4); nothing was written and the look is held."""

    exit_code = EXIT_HELD


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def _host_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment

    return current_execution_host_id(), load_execution_host_assignment()["dedicated_capture_execution_host_id"]


def require_capture_host():
    """Refuse unless this is the dedicated capture host (or where that cannot be proven)."""
    try:
        here, capture = _host_identity()
    except Exception as exc:  # identity not provable: refuse
        raise MarketRefused(f"capture-host identity is not provable: {exc}") from exc
    if not here or here != capture:
        raise MarketRefused("mg1_market runs only on the dedicated capture host, where the prices are")


def check_out(out):
    raw = str(out)
    if raw.startswith(("\\\\", "//")):
        raise MarketRefused(f"output {raw} is a UNC (share) path: prices never leave the host before the look")
    out = Path(out)
    if not out.is_absolute():
        raise MarketRefused(f"output {out} is not absolute")
    out = out.resolve()
    for root in (Path(paths.data_path("exports")).resolve(), Path(paths.data_path("snapshots")).resolve()):
        if out == root or root in out.parents:
            raise MarketRefused(f"output {out} is inside {root}: no price file goes to an export channel")
    if out.exists():
        raise MarketRefused(f"output {out} already exists: the market file is written once, in a new folder")
    return out


def _date_files(prices, day, look_id):
    """The verified ``(rows, receipt, shas)`` of one date's published price file set."""
    prices = Path(prices)
    csv_name, receipt_name = f"{day}{PRICES_SUFFIX}", f"{day}{RECEIPT_SUFFIX}"
    sums = prices / f"{day}{SUMS_SUFFIX}"
    if not sums.is_file():
        raise MarketRefused(f"{day} has no published price files under {prices} (no {sums.name})")
    listed = {}
    for line in sums.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) != 2:
            raise MarketRefused(f"{sums.name} has a malformed line")
        listed[parts[1]] = parts[0].lower()
    if set(listed) != {csv_name, receipt_name}:
        raise MarketRefused(f"{sums.name} must name exactly {csv_name} and {receipt_name}")
    raw = {}
    for name in (csv_name, receipt_name):
        path = prices / name
        if not path.is_file() or sha256_file(path) != listed[name]:
            raise MarketRefused(f"{name} is missing or differs from {sums.name}")
        raw[name] = path.read_bytes()
    receipt = json.loads(raw[receipt_name].decode("utf-8"))
    if (receipt.get("schema") != PRICES_SCHEMA or receipt.get("look_id") != look_id
            or receipt.get("target_date") != day):
        raise MarketRefused(f"{receipt_name} is not the {PRICES_SCHEMA} receipt of look {look_id!r} for {day}")
    reader = csv.reader(io.StringIO(raw[csv_name].decode("utf-8")))
    header = next(reader, None)
    if tuple(header or ()) != PRICES_COLUMNS:
        raise MarketRefused(f"{csv_name} columns are {header}, not {list(PRICES_COLUMNS)}")
    rows = list(reader)
    shas = {"sums_sha256": sha256_file(sums), "prices_sha256": listed[csv_name],
            "receipt_sha256": listed[receipt_name], "cross_check": receipt.get("cross_check")}
    return rows, shas


def _price(text, flag):
    """``(value or NaN, ok)``: ok is False for a flagged or non-[0, 1] price (B's T4)."""
    if flag not in ("0", "1"):
        return math.nan, False
    if text == "":
        return math.nan, flag == "0"
    try:
        value = float(text)
    except ValueError:
        return math.nan, False
    return value, flag == "0" and math.isfinite(value) and 0.0 <= value <= 1.0


def build(*, look_id, layout, prices, out, now=None):
    """Write ``<out>/market.parquet`` and its manifest (last). Every refusal comes before the first write."""
    import pandas as pd

    require_capture_host()
    if look_id not in LOOK_IDS:
        raise MarketRefused(f"look id {look_id!r} is not one of {LOOK_IDS}")
    out = check_out(out)
    layout = Path(layout)
    snaps = pd.read_parquet(layout / LAYOUT_SNAPSHOTS, columns=["row_key", "date"])
    bands = pd.read_parquet(layout / LAYOUT_BANDS, columns=["row_key", "band_index", "kind", "low", "high"])
    days = sorted(set(snaps.date.astype(str)))
    if not days:
        raise MarketRefused("the layout has no snapshots")
    wanted = {(str(r.row_key), str(r.kind), int(r.low), int(r.high)): int(r.band_index)
              for r in bands.itertuples(index=False)}
    if len(wanted) != len(bands):
        raise MarketRefused("the layout repeats a (row_key, kind, low, high) band")
    found, dates, extra = {}, {}, 0
    duplicates = out_of_range = 0
    for day in days:
        rows, dates[day] = _date_files(prices, day, look_id)
        for row in rows:
            if len(row) != len(PRICES_COLUMNS):
                raise MarketRefused(f"{day}{PRICES_SUFFIX} has a malformed row")
            try:
                key = (row[0], row[1], int(row[2]), int(row[3]))
            except ValueError as exc:
                raise MarketRefused(f"{day}{PRICES_SUFFIX} has a malformed band limit") from exc
            if key not in wanted:
                extra += 1
                continue
            if key in found:
                duplicates += 1
                continue
            value, ok = _price(row[4], row[5])
            out_of_range += int(not ok)
            found[key] = value
    if duplicates:
        raise MarketRefused(f"{duplicates} layout bands have more than one price row (duplicate_free false)")
    unmatched = len(wanted) - len(found)
    if unmatched:
        raise MarketRefused(f"{unmatched} layout bands have no price row (unmatched)")
    if out_of_range:
        raise MarketHeld(f"held: {out_of_range} matched capture-time prices are finite but outside [0, 1] or "
                         "flagged (range_ok false); nothing was written")
    frame = pd.DataFrame([(k[0], wanted[k], found[k]) for k in wanted], columns=list(MARKET_COLUMNS))
    frame = frame.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    frame["band_index"] = frame.band_index.astype("int64")
    frame["p_market_yes"] = frame.p_market_yes.astype("float64")
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    body = buffer.getvalue()
    priced_bands = frame.p_market_yes.notna()
    per_snapshot = priced_bands.groupby(frame.row_key).all()
    manifest = {"schema": SCHEMA, "look_id": look_id,
                "built_at_utc": (now or datetime.now(timezone.utc)).isoformat(),
                "market_file": MARKET_FILE, "market_sha256": hashlib.sha256(body).hexdigest(),
                "columns": list(MARKET_COLUMNS),
                "layout": {"path": str(layout), "snapshots_sha256": sha256_file(layout / LAYOUT_SNAPSHOTS),
                           "bands_sha256": sha256_file(layout / LAYOUT_BANDS)},
                "prices_root": str(Path(prices)), "dates": dates,
                "counts": {"dates": len(days), "snapshots": int(len(per_snapshot)), "bands": int(len(frame)),
                           "priced_bands": int(priced_bands.sum()), "priced_snapshots": int(per_snapshot.sum()),
                           "price_rows_not_in_layout": extra, "unmatched_bands": 0},
                "range_ok": True, "duplicate_free": True, "counts_only": True, "module_sha256": module_sha256()}
    out.mkdir(parents=True)
    with open(out / MARKET_FILE, "xb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    with open(out / MANIFEST, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return out / MARKET_FILE, manifest


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("build", help="the look's market.parquet and manifest, on the capture host")
    run.add_argument("--look", required=True, choices=LOOK_IDS)
    run.add_argument("--layout", required=True, help="the look's label-free layout (inputs_*.parquet)")
    run.add_argument("--prices", required=True, help="the capture_price_export output folder")
    run.add_argument("--out", required=True, help="a new local folder on the host")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        path, manifest = build(look_id=args.look, layout=args.layout, prices=args.prices, out=args.out)
    except MarketRefused as exc:
        print(str(exc) if isinstance(exc, MarketHeld) else f"refused: {exc}", file=sys.stderr)
        return exc.exit_code
    print(json.dumps({"market": str(path), "market_sha256": manifest["market_sha256"],
                      "range_ok": manifest["range_ok"], "duplicate_free": manifest["duplicate_free"],
                      "counts": manifest["counts"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
