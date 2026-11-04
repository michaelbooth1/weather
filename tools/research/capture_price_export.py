r"""Capture-time prices for one look's --market file, capture-host side: one create-only file set per date.

Master rulings of 2026-11-03 on ``--market`` (MG-1 and B). It feeds ``weather.calibration.mg1_market``, which
builds the ``market.parquet`` that ``mg1_look run --market`` and ``b_transfer write --market`` read.

EMBARGO (master 2026-11-03, --market ruling 2). This tool is a REGISTERED STEP OF THE LOOK PATH:

* it runs ONLY on that test's look morning, after the 45th date's finality (``--through``: every date it covers
  must have ended in every market, ``export_cut_utc``), under master's lease, in the same session as the look,
  ON THE CAPTURE HOST;
* neither this tool, the concat, nor the look ever exports a price CSV or parquet to the workstation before the
  look receipt. ``--out`` refuses any export channel the workstation pulls (``data\exports``), the capture tree
  and any UNC (share) path;
* its stdout, logs and per-date receipt carry counts, shas and booleans only. No agent or human views a price
  value;
* the same rule as B's T4: a finite price outside [0, 1] is flagged here (``out_of_range``, never written as a
  value), and the concat REFUSES it, so the look is HELD.

What it reads. Only D's ``snapshots_long.csv`` for the 11 fixed markets, through the unchanged exporter's
``Source(coverage_counts=False)`` (known paths, link and reparse-point checks, the 30-minute quiet guard, the
bounded shared read), keeping only rows captured at or before ``export_cut_utc(D)``, exactly as the exporter
and the R19 counts tool do. So its row set is the bundle's, and the layout built from the bundle keys into it.

What it writes, under ``--out`` (create-only, mode "x"):

* ``<D>.prices.csv``: ``row_key, kind, low, high, p_market_yes, out_of_range``. ``row_key`` is
  ``<market>|<snapshot_id>`` and ``(kind, low, high)`` the band limits, both as the layout builder keys them
  (``mg2_inputs.snapshot_rows`` and ``band_vector``); the concat joins on them to get ``band_index``. The price
  passes R19's ``capture_price`` (a finite float in [0, 1]); anything else is written empty (unpriced), with
  ``out_of_range`` 1 for a finite value outside [0, 1]. A row whose band limits the builder would reject is not
  written and is counted as ``unkeyed``;
* ``<D>.capture_prices.json`` (``capture_price_export/1``): per market the counts (snapshots, rows, priced,
  out of range, unkeyed, after the cut), the R19 cross-check and the shas. No price value;
* ``<D>.SHA256SUMS``, written last: it marks the date published.

The R19 cross-check (master ruling 5). From B's D0 (2026-10-29), each snapshot's ``[n_rows, n_priced]`` must
equal the date's published R19 counts sidecar, else the date refuses. Before it (MG-1's 10-15..10-28) no
sidecar exists: the receipt records ``"kind": "none_before_r19"`` and this tool's own counts, disclosed in the
receipt, with no refusal for the missing cross-check.

Where it lives: ``tools/research/`` (R19 option b, the R11 Head 1 pattern), so it can call R19's own
``capture_price`` and MG-1 and B derive prices one way. Nothing under ``src/`` imports it. It refuses unless it
runs on the dedicated capture host (``weather.execution_host``, the check ``scripts/ops/b_price_coverage.ps1``
makes). Master's host ``.ps1`` runs it under the lease.

    python -P -B -m tools.research.capture_price_export --look mg1 --data-root <repo>\data --out <dir>
        --from 2026-10-15 --through 2026-11-28 [--coverage-root <repo>\data\exports\mg2-inputs]

Exit codes: 0 written; 2 refused (nothing written for that date); 3 a source too fresh (re-run once quiet).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tools.research import b_price_coverage as r19
from weather import paths
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

SCHEMA = "capture_price_export/1"
LOOK_IDS = ("mg1", "b")
PRICES_SUFFIX = ".prices.csv"
RECEIPT_SUFFIX = ".capture_prices.json"
SUMS_SUFFIX = ".SHA256SUMS"
PRICES_COLUMNS = ("row_key", "kind", "low", "high", "p_market_yes", "out_of_range")
SNAPSHOTS_LONG = "snapshots_long.csv"
BAND_KINDS = ("lte", "eq", "gte")
EXIT_REFUSED, EXIT_TOO_FRESH = 2, 3


class PriceExportRefused(RuntimeError):
    """A date cannot be exported (time, path, host, source, cross-check); nothing is written for it."""

    exit_code = EXIT_REFUSED


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _host_identity():
    from weather.execution_host import current_execution_host_id, load_execution_host_assignment

    return current_execution_host_id(), load_execution_host_assignment()["dedicated_capture_execution_host_id"]


def require_capture_host():
    """The prices exist only on the capture host; refuse anywhere else (or where it cannot be proven)."""
    try:
        here, capture = _host_identity()
    except Exception as exc:  # identity not provable: refuse
        raise PriceExportRefused(f"capture-host identity is not provable: {exc}") from exc
    if not here or here != capture:
        raise PriceExportRefused("this tool runs only on the dedicated capture host, where the prices are")


def check_out(out, data_root):
    """``--out`` must be a local absolute folder outside every export channel and the capture tree."""
    raw = str(out)
    if raw.startswith(("\\\\", "//")):
        raise PriceExportRefused(f"output {raw} is a UNC (share) path: prices never leave the host before the look")
    out = Path(out)
    if not out.is_absolute():
        raise PriceExportRefused(f"output {out} is not absolute")
    out = out.resolve()
    data_root = Path(data_root).resolve()
    forbidden = {data_root / "exports", data_root / "snapshots", data_root / "forecast_payload_cas",
                 Path(paths.data_path("exports")).resolve()}
    for root in forbidden:
        if out == root or root in out.parents:
            raise PriceExportRefused(f"output {out} is inside {root}: no price file goes to an export channel or "
                                     "the capture tree")
    return out


def _finite(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def band_key(row):
    """``(kind, low, high)`` as ``mg2_inputs.band_vector`` keys a band, or None when the builder rejects it."""
    kind = row.get("bin_kind")
    low, high = _finite(row.get("bin_value_c")), _finite(row.get("bin_value_hi_c"))
    if kind not in BAND_KINDS or low is None or low != int(low) or (high is not None and high != int(high)):
        return None
    return kind, int(low), int(high) if high is not None else int(low)


def out_of_range(value):
    """True for a finite price outside [0, 1] (B's T4 range check)."""
    number = _finite(value)
    return number is not None and not 0.0 <= number <= 1.0


def export_market(src, market, day, cut, writer):
    """One market's in-cut rows into ``writer``; returns ``(per-snapshot [n_rows, n_priced], counts)``."""
    rel = f"snapshots/{allow.slug_for(market, day)}/{SNAPSHOTS_LONG}"
    per_snapshot = {}
    counts = {"present": False, "rows": 0, "priced_rows": 0, "out_of_range_rows": 0, "unkeyed_rows": 0,
              "rows_after_cut_or_untimed": 0}
    with src.text(rel) as handle:
        if handle is None:
            counts["snapshots"] = 0
            return per_snapshot, counts
        counts["present"] = True
        for row in csv.DictReader(handle):
            captured = mx.parse_time(row.get("captured_at_utc"))
            if captured is None or captured > cut:
                counts["rows_after_cut_or_untimed"] += 1
                continue
            sid = str(row.get("snapshot_id") or "")
            raw = row.get(mx.PRICE_COLUMN)
            price = r19.capture_price(raw)
            n_rows, n_priced = per_snapshot.get(sid, (0, 0))
            per_snapshot[sid] = (n_rows + 1, n_priced + int(price is not None))
            counts["rows"] += 1
            counts["priced_rows"] += int(price is not None)
            flagged = out_of_range(raw)
            counts["out_of_range_rows"] += int(flagged)
            key = band_key(row)
            if key is None:
                counts["unkeyed_rows"] += 1
                continue
            writer.writerow([f"{market}|{sid}", key[0], key[1], key[2], "" if price is None else repr(price),
                             int(flagged)])
    counts["snapshots"] = len(per_snapshot)
    return {sid: [n, k] for sid, (n, k) in sorted(per_snapshot.items())}, counts


def cross_check(day, counts, coverage_root):
    """Master ruling 5: the R19 sidecar must agree from B's D0; before it, there is none to compare (disclosed)."""
    if day < r19.FIRST_DATE:
        return {"kind": "none_before_r19", "match": None,
                "note": f"no R19 counts sidecar exists before {r19.FIRST_DATE}; this receipt's own counts are "
                        "disclosed instead (master 2026-11-03, ruling 5)"}
    target, sums = r19.coverage_paths(coverage_root, day)
    if not target.is_file() or not sums.is_file():
        raise PriceExportRefused(f"{day} has no published R19 counts sidecar under {coverage_root}")
    raw = target.read_bytes()
    listed = sums.read_text(encoding="ascii").split()
    if not listed or listed[0].lower() != _sha(raw):
        raise PriceExportRefused(f"{day}'s R19 sidecar does not match its SHA256SUMS")
    sidecar = json.loads(raw.decode("utf-8"))
    theirs = sidecar.get("counts") or {}
    differ = sorted(m for m in allow.MARKETS if theirs.get(m, {}) != counts.get(m, {}))
    if differ:
        raise PriceExportRefused(f"{day}: per-snapshot [rows, priced] differ from the R19 sidecar in {differ}")
    return {"kind": "r19_sidecar", "match": True, "sidecar_sha256": _sha(raw),
            "sidecar_match_flag": bool(sidecar.get("match"))}


def file_names(day):
    stem = day.isoformat()
    return f"{stem}{PRICES_SUFFIX}", f"{stem}{RECEIPT_SUFFIX}", f"{stem}{SUMS_SUFFIX}"


def export_date(*, look_id, day, through, data_root, out, coverage_root, now=None):
    """Write D's prices, receipt and SHA256SUMS (create-only, the SUMS last). Returns the counts-only receipt."""
    if look_id not in LOOK_IDS:
        raise PriceExportRefused(f"look id {look_id!r} is not one of {LOOK_IDS}")
    now = now or datetime.now(timezone.utc)
    if day > through:
        raise PriceExportRefused(f"{day} is after --through {through}")
    final = allow.export_cut_utc(through)
    if now <= final:
        raise PriceExportRefused(f"--through {through} has not ended in every market (until {final.isoformat()}): "
                                 "this step runs only after the 45th date's finality")
    out = check_out(out, data_root)
    names = file_names(day)
    if any((out / name).exists() for name in names):
        raise PriceExportRefused(f"{day} already has files under {out}: one export per date and look")
    cut = allow.export_cut_utc(day)
    src = mx.Source(Path(data_root).resolve(), coverage_counts=False)
    started = datetime.now(timezone.utc)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(PRICES_COLUMNS)
    per_market, counts = {}, {}
    for market in allow.MARKETS:
        per_market[market], counts[market] = export_market(src, market, day, cut, writer)
    check = cross_check(day, per_market, coverage_root)
    body = buffer.getvalue().encode("utf-8")
    receipt = {"schema": SCHEMA, "look_id": look_id, "target_date": day.isoformat(), "through": through.isoformat(),
               "export_cut_utc": cut.isoformat(), "counts_only": True, "counts": counts, "cross_check": check,
               "prices_file": names[0], "prices_sha256": _sha(body),
               "out_of_range_rows": sum(c["out_of_range_rows"] for c in counts.values()),
               "predicate": "R19 capture_price: a finite float in [0, 1], else empty; finite outside [0, 1] flagged",
               "module_sha256": module_sha256(), "r19_module_sha256": r19.module_sha256(),
               "exporter_module_sha256": hashlib.sha256(Path(mx.__file__).read_bytes()).hexdigest(),
               "allowlist_sha256": allow.allowlist_sha256(), "started_utc": started.isoformat(),
               "finished_utc": datetime.now(timezone.utc).isoformat()}
    receipt_bytes = (json.dumps(receipt, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for name, data in ((names[0], body), (names[1], receipt_bytes)):
            with open(out / name, "xb") as handle:
                written.append(out / name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        sums = f"{_sha(body)}  {names[0]}\n{_sha(receipt_bytes)}  {names[1]}\n".encode("ascii")
        with open(out / names[2], "xb") as handle:  # the published marker, last
            handle.write(sums)
    except FileExistsError as exc:
        for path in written:
            path.unlink(missing_ok=True)
        raise PriceExportRefused(f"{day}'s files appeared during the run") from exc
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return receipt


def dates(first, through):
    day, out = first, []
    while day <= through:
        out.append(day)
        day += timedelta(days=1)
    return out


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m tools.research.capture_price_export",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--look", required=True, choices=LOOK_IDS)
    parser.add_argument("--data-root", default=str(paths.data_path()))
    parser.add_argument("--out", required=True, help="a new local folder on the host (never an export or share)")
    parser.add_argument("--from", dest="first", required=True, help="the look's first date (D0)")
    parser.add_argument("--through", required=True, help="the look's 45th countable date; it must be final")
    parser.add_argument("--coverage-root", default=str(Path(r19.default_out())),
                        help="the R19 sidecar root (<out>\\_b_coverage is under it)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    status = 0
    try:
        require_capture_host()
        first, through = date.fromisoformat(args.first), date.fromisoformat(args.through)
        if first > through:
            raise PriceExportRefused(f"--from {first} is after --through {through}")
    except (PriceExportRefused, ValueError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return EXIT_REFUSED
    for day in dates(first, through):
        try:
            receipt = export_date(look_id=args.look, day=day, through=through, data_root=args.data_root,
                                  out=args.out, coverage_root=args.coverage_root)
        except mx.FileTooFresh as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "too_fresh", "reason": str(exc)}))
            status = max(status, EXIT_TOO_FRESH)
            continue
        except (PriceExportRefused, mx.ExportRefused, r19.CoverageRefused) as exc:
            print(json.dumps({"target_date": day.isoformat(), "status": "refused", "reason": str(exc)}))
            status = max(status, EXIT_REFUSED)
            continue
        print(json.dumps({"target_date": day.isoformat(), "status": "written",
                          "cross_check": receipt["cross_check"]["kind"],
                          "rows": sum(c["rows"] for c in receipt["counts"].values()),
                          "priced_rows": sum(c["priced_rows"] for c in receipt["counts"].values()),
                          "out_of_range_rows": receipt["out_of_range_rows"]}))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
