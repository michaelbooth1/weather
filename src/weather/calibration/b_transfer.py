r"""Rule B-1's one outcome transfer: the ``b_transfer/1`` writer (binding plan sections 9.6 and 9.7).

Research and shadow only. Master runs it once, on the host, at the look; nothing in serving, capture,
release or Scheduler imports it, and the import refuses from a production package. It never imports
``b_scorer`` or ``mg2_composite`` (whose import refuses on the capture host, where this writer runs): the
constants the scorer's ``read_manifest`` / ``manifest_problems`` / ``transfer_files`` check are copied here
and pinned equal to the scorer's by a test.

What it does (binding plan 9.6): one export of the venue winner, the settlement bucket and
``promotion_countable`` for the input-countable dates from D0 in date order, stopping at the 45th
promotion-countable date, plus the capture-time market prices of those rows. It writes to a new, separate
directory (never an input-bundle inbox) three files:

* ``labels.parquet``: ``row_key, date, market, winner, promotion_countable`` (+ ``settlement_bucket``,
  ``label_source`` when the export carries them), one row per snapshot, every manifest date present;
* ``market.parquet``: ``row_key, band_index, p_market_yes``, only rows the labels carry;
* ``b_transfer_manifest.json`` (``b_transfer/1``, written last, mode "x"): the dates with their
  ``promotion_countable`` flag, the two file sha256s, ``transferred_at_utc`` and the sha256 of the MG-1 look
  receipt it follows (B-1 VOID 5 compares the receipt's ``looked_at_utc`` with ``transferred_at_utc``).

Refusals come before any output is written. The input-countable dates are the dates of the forward
``mg2_inputs_window/1`` manifest (``mg2_inputs concat``), which is fixed before and without outcomes.

    python -m weather.calibration.b_transfer write --labels <export labels.parquet> \
        --market <export market.parquet> --input-window <window manifest.json> --d0 YYYY-MM-DD \
        --mg1-look-receipt <mg1 look receipt.json> --out <new transfer directory>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


def _refuse_production_import():
    """Fail closed when imported from a production package."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.b_transfer is research-only; imported from {name}")
        frame = frame.f_back


_refuse_production_import()

NAME = "b_transfer"
# Copied from b_scorer (pinned equal by tests/calibration/test_b_transfer.py).
TRANSFER_SCHEMA = "b_transfer/1"
TRANSFER_MANIFEST = "b_transfer_manifest.json"
TRANSFER_FILES = ("labels.parquet", "market.parquet")
N_DATES = 45
MG1_RECEIPT_TIME = "looked_at_utc"
# The fixed 11 markets of the input gate (binding plan 9.4); B scores 10 of them (Denver excluded). The
# embargo is the latest market-local end of the 45th date over all 11, never earlier than B's.
MARKET_TZ = {"atlanta": "America/New_York", "miami": "America/New_York", "nyc": "America/New_York",
             "austin": "America/Chicago", "chicago": "America/Chicago", "dallas": "America/Chicago",
             "houston": "America/Chicago", "denver": "America/Denver", "los-angeles": "America/Los_Angeles",
             "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
WINDOW_SCHEMA = "mg2_inputs_window/1"  # mg2_inputs.WINDOW_SCHEMA (pinned equal by a test)
INPUT_INBOX_PART = "mg2-inputs"  # the daily input channel's inbox (binding plan 9.7); never a transfer target
LABEL_COLUMNS = ("row_key", "date", "market", "winner", "promotion_countable")
OPTIONAL_LABEL_COLUMNS = ("settlement_bucket", "label_source")
MARKET_COLUMNS = ("row_key", "band_index", "p_market_yes")


class TransferRefused(RuntimeError):
    """The transfer cannot be written (nothing was written)."""

    exit_code = 2


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def _utc(value):
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"{value!r} has no UTC offset")
    return moment.astimezone(timezone.utc)


def embargo_end(last_date):
    """The instant the 45th date has ended in every one of the 11 markets."""
    from zoneinfo import ZoneInfo

    day = date.fromisoformat(str(last_date)) + timedelta(days=1)
    return max(datetime.combine(day, time(0), ZoneInfo(tz)).astimezone(timezone.utc) for tz in MARKET_TZ.values())


def read_receipt(path, now):
    """The MG-1 look receipt's sha256 and ``looked_at_utc``; the transfer must come after that instant.

    Full receipt validation (writer, entry-point sha, body sha) is B-1 VOID 5 at the scorer; this only refuses a
    transfer that could never pass it.
    """
    p = Path(path) if path else None
    if p is None or not p.is_file() or p.stat().st_size == 0:
        raise TransferRefused("MG-1's look receipt does not exist: labels travel only after MG-1's look (9.6)")
    try:
        looked = _utc(json.loads(p.read_text(encoding="utf-8"))[MG1_RECEIPT_TIME])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferRefused(f"MG-1 look receipt has no readable {MG1_RECEIPT_TIME}: {exc}") from exc
    if now <= looked:
        raise TransferRefused(f"transfer time {now.isoformat()} is not after the MG-1 look {looked.isoformat()}")
    return sha256_file(p), looked


def mg1_window_closed(today):
    """The recorded MG-1 window must have closed (the scorer's look guard refuses otherwise)."""
    from weather import mg1_reserved_window as w

    start, end = w.window()
    if end is None or today <= end:
        raise TransferRefused(f"the recorded MG-1 window ({start}..{end or 'open'}) has not closed")


def read_input_window(path, d0):
    """The input-countable dates from D0, in order, from a forward ``mg2_inputs_window/1`` manifest."""
    p = Path(path)
    if not p.is_file():
        raise TransferRefused(f"input window manifest missing: {p}")
    window = json.loads(p.read_text(encoding="utf-8"))
    if window.get("schema") != WINDOW_SCHEMA:
        raise TransferRefused(f"input window schema {window.get('schema')!r} != {WINDOW_SCHEMA}")
    try:
        days = [date.fromisoformat(str(d)) for d in window["dates"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferRefused(f"input window dates unreadable: {exc}") from exc
    if days != sorted(set(days)):
        raise TransferRefused("input window dates are not strictly increasing")
    return [d for d in days if d >= d0], sha256_file(p)


def check_out(out):
    out = Path(out)
    if INPUT_INBOX_PART in {part.lower() for part in out.resolve().parts}:
        raise TransferRefused(f"{out} is inside the daily input inbox; the transfer goes to a separate path (9.6)")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise TransferRefused(f"output directory {out} must be new or empty: one transfer")
    return out


def _flags_by_date(labels):
    """Per date the single ``promotion_countable`` flag the export carries (it must not vary within a date)."""
    flags = {}
    for d, group in labels.groupby("date", sort=True):
        values = set(group.promotion_countable.map(bool))
        if len(values) != 1 or group.promotion_countable.isna().any():
            raise TransferRefused(f"promotion_countable varies or is missing within {d}")
        flags[str(d)] = values.pop()
    return flags


def select_dates(input_dates, flags):
    """Input-countable dates in order, through the 45th promotion-countable one (none skipped, none after)."""
    rows, countable = [], 0
    for d in input_dates:
        key = d.isoformat()
        if key not in flags:
            raise TransferRefused(f"the label export does not cover input-countable date {key}")
        rows.append((key, flags[key]))
        countable += int(flags[key])
        if countable == N_DATES:
            return rows
    raise TransferRefused(f"only {countable} promotion-countable dates among {len(rows)} input-countable dates; "
                          f"the transfer needs {N_DATES}")


def build_frames(labels, market, rows):
    """The two transfer frames restricted to the selected dates, in a fixed column and row order."""
    import pandas as pd

    keep = {d for d, _ in rows}
    lab = labels[labels.date.isin(keep)]
    cols = list(LABEL_COLUMNS) + [c for c in OPTIONAL_LABEL_COLUMNS if c in lab.columns]
    lab = lab[cols].copy()
    lab["promotion_countable"] = lab.promotion_countable.map(bool)
    if lab.row_key.duplicated().any():
        raise TransferRefused("duplicate row_key in the label export")
    if not (lab.row_key.astype(str).str.split("|", n=1).str[0] == lab.market.astype(str)).all():
        raise TransferRefused("a label row_key does not start with its market")
    unknown = sorted(set(lab.market.astype(str)) - set(MARKET_TZ))
    if unknown:
        raise TransferRefused(f"labels for markets outside the fixed 11: {unknown}")
    counted = lab[lab.promotion_countable]
    if counted.winner.isna().any():
        raise TransferRefused(f"{int(counted.winner.isna().sum())} label rows on countable dates have no winner")
    lab = lab.sort_values(["date", "market", "row_key"]).reset_index(drop=True)
    mkt = market[list(MARKET_COLUMNS)]
    mkt = mkt[mkt.row_key.isin(set(lab.row_key))].copy()
    if mkt.duplicated(["row_key", "band_index"]).any():
        raise TransferRefused("duplicate (row_key, band_index) in the market export")
    mkt["band_index"] = mkt.band_index.astype(int)
    mkt = mkt.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    return lab, pd.DataFrame(mkt)


def _read_export(path, required, what):
    import pandas as pd

    p = Path(path)
    if not p.is_file():
        raise TransferRefused(f"{what} export missing: {p}")
    frame = pd.read_parquet(p)
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise TransferRefused(f"{what} export lacks columns {missing}")
    if "date" in frame.columns:
        frame = frame.assign(date=frame.date.astype(str).str[:10])
    return frame, sha256_file(p)


def write(*, labels, market, input_window, d0, mg1_look_receipt, out, now=None):
    """Write the one ``b_transfer/1`` transfer; every refusal comes before the first file is written."""
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    d0 = date.fromisoformat(str(d0))
    out = check_out(out)
    mg1_window_closed(now.date())
    receipt_sha, looked = read_receipt(mg1_look_receipt, now)
    input_dates, window_sha = read_input_window(input_window, d0)
    lab_src, labels_sha = _read_export(labels, LABEL_COLUMNS, "label")
    mkt_src, market_sha = _read_export(market, MARKET_COLUMNS, "market")
    rows = select_dates(input_dates, _flags_by_date(lab_src[lab_src.date.isin({d.isoformat() for d in input_dates})]))
    settled = embargo_end(rows[-1][0])
    if now < settled:
        raise TransferRefused(f"embargo: the 45th countable date {rows[-1][0]} has not ended in every market "
                              f"(until {settled.isoformat()})")
    lab, mkt = build_frames(lab_src, mkt_src, rows)

    out.mkdir(parents=True, exist_ok=True)
    lab.to_parquet(out / TRANSFER_FILES[0], index=False)
    mkt.to_parquet(out / TRANSFER_FILES[1], index=False)
    manifest = {
        "schema": TRANSFER_SCHEMA,
        "transferred_at_utc": now.isoformat(),
        "d0": d0.isoformat(),
        "dates": [{"date": d, "promotion_countable": c} for d, c in rows],
        "files": {name: sha256_file(out / name) for name in TRANSFER_FILES},
        "rows": {TRANSFER_FILES[0]: int(len(lab)), TRANSFER_FILES[1]: int(len(mkt))},
        "mg1_look_receipt_sha256": receipt_sha,
        "mg1_looked_at_utc": looked.isoformat(),
        "input_window_sha256": window_sha,
        "export_sha256": {"labels": labels_sha, "market": market_sha},
        "writer": {"module": f"weather.calibration.{NAME}", "source_sha256": module_sha256(),
                   "host": socket.gethostname()},
    }
    with open(out / TRANSFER_MANIFEST, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return {"status": "ok", "out": str(out), "dates": [rows[0][0], rows[-1][0], len(rows)],
            "countable": sum(int(c) for _, c in rows), "manifest_sha256": sha256_file(out / TRANSFER_MANIFEST)}


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.b_transfer", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write", help="write the one b_transfer/1 transfer (host, at the look)")
    for name in ("labels", "market", "input-window", "d0", "mg1-look-receipt", "out"):
        w.add_argument(f"--{name}", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = write(labels=args.labels, market=args.market, input_window=args.input_window, d0=args.d0,
                       mg1_look_receipt=args.mg1_look_receipt, out=args.out)
    except TransferRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return exc.exit_code
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
