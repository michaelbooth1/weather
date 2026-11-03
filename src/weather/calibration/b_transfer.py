r"""Rule B-1's one outcome transfer: the ``b_transfer/1`` writer (binding plan sections 9.6 and 9.7).

Research and shadow only. Master runs it once, on the host, at the look; nothing in serving, capture,
release or Scheduler imports it, and the import refuses from a production package. It never imports
``b_scorer``, ``mg2_composite`` or ``mg2_inputs`` (``mg2_composite`` refuses on the capture host, where this
writer runs): the constants the scorer's ``read_manifest`` / ``manifest_problems`` / ``transfer_files`` check
are copied here and pinned equal to the scorer's by a test.

What it does (binding plan 9.6; master's T1-T5 rulings of 2026-11-03; R19 addendum; R24 (3)): the
input-countable dates from D0 in date order, stopping at B's 45th countable date, with the venue winner of
every B layout snapshot on a countable date and the capture-time market prices of those rows.

* **T1 / T5, the countable list.** A date counts for B iff EVERY one of B's 10 market-days (Denver is out of
  B, master 10-25) has ``promotion_countable`` true in the settlement ledger's latest revision
  (``settlement_ledger.current_ledger_label``). A market-day with no ledger row, or more than one event, is not
  countable. The manifest records each market ledger's sha256. A non-countable date moves the 45th date later,
  never earlier. The single per-date flag is B's collapsed flag; the constancy check (one flag per date)
  applies to that flag over B's 10 markets only.
* **R24 (3), the labels.** Only the frozen look-morning copy (``venue_label_audit freeze``) is read, through
  ``read_venue_labels`` (``read_through`` = the date itself, ``allow_reserved_window=True``), and only when
  this module is the running ``__main__`` (its registered entry point). Every frozen file is checked against
  ``freeze_receipt.json`` and every record's source sha256 against the frozen file. ``label_bucket`` maps to
  each snapshot's band index through the layout's bands (``lte`` / ``eq`` / ``gte``).
* **T2.** A reader refusal or a missing label row makes the date non-countable for B. Never a VOID.
* **T3.** Before publish, a key-only check: every B layout snapshot on a countable date has a label row with a
  winner. On a mismatch the transfer refuses, writes nothing, and the look is held.
* **T4 (R19 addendum).** ``p_market_yes`` is written only through :func:`capture_price` (a finite price in
  [0, 1], else NaN). A finite price outside [0, 1] refuses (``REFUSE_FINITE_OUT_OF_RANGE``). Every transferred
  snapshot's ``[n_rows, n_priced]`` must equal its date's published R19 counts sidecar, else it refuses. Any
  other sidecar match flag that is false HOLDS the transfer unless master's dated, outcome-blind override file
  (``--sidecar-override``) names that exact date and flag; the override's sha256 is pinned in the manifest.

Outputs, in a new separate directory (never an input-bundle inbox):

* ``labels.parquet``: ``row_key, date, market, winner, promotion_countable, settlement_bucket,
  label_source``, one row per B layout snapshot on every manifest date (winner only on countable dates);
* ``market.parquet``: ``row_key, band_index, p_market_yes``, only rows the labels carry;
* ``b_transfer_manifest.json`` (``b_transfer/1``, written last, mode "x"): the dates with their
  ``promotion_countable`` flag, the two file sha256s, ``transferred_at_utc``, the MG-1 look receipt sha256
  (B-1 VOID 5), and the ledger, freeze, layout and sidecar provenance.

Refusals come before any output is written. The input-countable dates are the dates of the forward
``mg2_inputs_window/1`` manifest (``mg2_inputs concat``), fixed before and without outcomes; its concatenated
layout (``inputs_snapshots.parquet``, ``inputs_bands.parquet``) sits beside it and is read for keys and band
definitions only.

    python -m weather.calibration.b_transfer write --market <export market.parquet> \
        --input-window <window manifest.json> --ledger-root <settlements root> \
        --frozen-labels <venue_rule_labels/frozen/ID> --coverage-root <_b_coverage folder> \
        --d0 YYYY-MM-DD --mg1-look-receipt <mg1 look receipt.json> --out <new transfer directory>         [--sidecar-override <master override.json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
ENTRY_MODULE = f"weather.calibration.{NAME}"
# Copied from b_scorer (pinned equal by tests/calibration/test_b_transfer.py).
TRANSFER_SCHEMA = "b_transfer/1"
TRANSFER_MANIFEST = "b_transfer_manifest.json"
TRANSFER_FILES = ("labels.parquet", "market.parquet")
N_DATES = 45
MG1_RECEIPT_TIME = "looked_at_utc"
# The fixed 11 markets of the input gate (binding plan 9.4); the embargo is the latest market-local end of the
# 45th date over all 11, never earlier than B's.
MARKET_TZ = {"atlanta": "America/New_York", "miami": "America/New_York", "nyc": "America/New_York",
             "austin": "America/Chicago", "chicago": "America/Chicago", "dallas": "America/Chicago",
             "houston": "America/Chicago", "denver": "America/Denver", "los-angeles": "America/Los_Angeles",
             "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
# B scores 10 of them: Denver is out of B (master 10-25); b_scorer.MARKETS, pinned equal by a test.
B_MARKETS = tuple(sorted(set(MARKET_TZ) - {"denver"}))
WINDOW_SCHEMA = "mg2_inputs_window/1"  # mg2_inputs.WINDOW_SCHEMA (pinned equal by a test)
LAYOUT_FILES = ("inputs_snapshots.parquet", "inputs_bands.parquet")  # mg2_inputs.LAYOUT_FILES (pinned)
INPUT_INBOX_PART = "mg2-inputs"  # the daily input channel's inbox (binding plan 9.7); never a transfer target
LABEL_COLUMNS = ("row_key", "date", "market", "winner", "promotion_countable")
OPTIONAL_LABEL_COLUMNS = ("settlement_bucket", "label_source")
MARKET_COLUMNS = ("row_key", "band_index", "p_market_yes")
# Schema registry names of the two upstream records (R24 freeze receipt, R19 counts sidecar).
FREEZE_RECEIPT_NAME = "venue_label_freeze_receipt"
SIDECAR_NAME = "b_coverage_sidecar"
FREEZE_RECEIPT = "freeze_receipt.json"
SIDECAR_SUMS_SUFFIX = ".SHA256SUMS"
OVERRIDE_NAME = "b_transfer_sidecar_override"  # master's dated release of a false sidecar match flag
# T4: a finite capture-time price outside [0, 1] refuses (held) rather than silently becoming NaN.
REFUSE_FINITE_OUT_OF_RANGE = True
# T2 reasons (per date, never per market).
NON_COUNTABLE_LEDGER = "ledger"
NON_COUNTABLE_LABEL = "label"


class TransferRefused(RuntimeError):
    """The transfer cannot be written (nothing was written); the look is held."""

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


def _registered(name):
    """The active version of a registered schema; refuses when its owning head has not landed."""
    from weather.schema_families import schema_version

    try:
        return schema_version(name)
    except KeyError as exc:
        raise TransferRefused(f"schema {name!r} is not registered: its owning head has not landed") from exc


def embargo_end(last_date):
    """The instant the 45th date has ended in every one of the 11 markets."""
    from zoneinfo import ZoneInfo

    day = date.fromisoformat(str(last_date)) + timedelta(days=1)
    return max(datetime.combine(day, time(0), ZoneInfo(tz)).astimezone(timezone.utc) for tz in MARKET_TZ.values())


def capture_price(value):
    """The capture-time price the B transfer admits: a finite float in [0, 1], else None (R19, R-H's admission).

    A copy of the R19 counts tool's predicate (pinned equal by a test), so the sidecar's ``n_priced`` and the
    transfer's finite prices agree by construction.
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


def _out_of_range(value):
    """True for a finite price outside [0, 1] (T4's range check)."""
    if value is None or isinstance(value, bool):
        return False
    try:
        price = float(str(value).strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(price) and not 0.0 <= price <= 1.0


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
    """The input-countable dates from D0, in order, the window manifest and its sha256."""
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
    return [d for d in days if d >= d0], window, sha256_file(p)


def read_layout_keys(window_path, window):
    """Key-only reads of the window's concatenated layout: B snapshots and their band definitions.

    Snapshots: ``row_key, snapshot_id, date, market``; bands: ``row_key, band_index, kind, low, high``. Each
    file must match the window manifest's sha256. No price, model value or label is read here.
    """
    import pandas as pd

    root = Path(window_path).parent
    files = window.get("files") or {}
    shas = {}
    for name in LAYOUT_FILES:
        path = root / name
        expected = (files.get(name) or {}).get("sha256")
        if not path.is_file() or not expected or sha256_file(path) != expected:
            raise TransferRefused(f"layout {name} beside the window manifest is missing or does not match it")
        shas[name] = expected
    snaps = pd.read_parquet(root / LAYOUT_FILES[0], columns=["row_key", "snapshot_id", "date", "market"])
    bands = pd.read_parquet(root / LAYOUT_FILES[1], columns=["row_key", "band_index", "kind", "low", "high"])
    snaps = snaps.assign(date=snaps.date.astype(str).str[:10], market=snaps.market.astype(str),
                         row_key=snaps.row_key.astype(str))
    if snaps.row_key.duplicated().any():
        raise TransferRefused("duplicate row_key in the window layout")
    snaps = snaps[snaps.market.isin(B_MARKETS)].reset_index(drop=True)
    bands = bands.assign(row_key=bands.row_key.astype(str))
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    return snaps, bands, shas


def check_out(out):
    out = Path(out)
    if INPUT_INBOX_PART in {part.lower() for part in out.resolve().parts}:
        raise TransferRefused(f"{out} is inside the daily input inbox; the transfer goes to a separate path (9.6)")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise TransferRefused(f"output directory {out} must be new or empty: one transfer")
    return out


# --- T1 / T5: the countable list from the ledger's latest revision -------------------------------------------

def _jsonl_rows(raw):
    rows = []
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def read_ledger_flags(ledger_root, days):
    """Per (market, ISO date) for B's 10 markets: the latest revision's ``promotion_countable`` (or False).

    Each market ledger is read once from bytes whose sha256 is returned. Only ``event_slug``, ``target_date``,
    ``revision_number`` and ``promotion_countable`` are kept from each latest revision. A market-day with no
    ledger row, or rows for more than one event, is not countable.
    """
    from weather.backtesting import settlement_ledger as sl

    wanted = {d.isoformat() for d in days}
    flags, shas = {}, {}
    for market in B_MARKETS:
        path = sl.ledger_path_for_market(market, ledger_root)
        if not path.is_file():
            raise TransferRefused(f"settlement ledger missing for {market}: {path}")
        raw = path.read_bytes()
        shas[market] = hashlib.sha256(raw).hexdigest()
        rows = [r for r in _jsonl_rows(raw) if str(r.get("target_date") or "")[:10] in wanted]
        slugs = {}
        for r in rows:
            slugs.setdefault(str(r.get("target_date"))[:10], set()).add(r.get("event_slug"))
        for day in sorted(wanted):
            events = slugs.get(day, set())
            if len(events) != 1:
                flags[(market, day)] = False
                continue
            latest = sl.current_ledger_label(rows, next(iter(events)))
            flags[(market, day)] = bool(latest) and latest.get("promotion_countable") is True
    return flags, shas


def collapse_flags(flags, days):
    """T1: B's per-date flag, true iff every one of B's 10 market-days is countable."""
    return {d.isoformat(): all(flags.get((m, d.isoformat()), False) for m in B_MARKETS) for d in days}


# --- R24 (3): the frozen look-morning label copy --------------------------------------------------------------

def _entry_running():
    """True when the running ``__main__`` is this module at these bytes (the transfer's registered entry)."""
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    if getattr(spec, "name", None) != ENTRY_MODULE or not getattr(spec, "origin", None):
        return False
    try:
        return sha256_file(spec.origin) == module_sha256()
    except OSError:
        return False


def read_freeze(frozen):
    """The R24 freeze receipt and the verified frozen paths per B market; refuses on any mismatch."""
    from weather.backtesting.venue_rule_labels import default_label_path
    from weather.market.market_registry import spec_for_id

    frozen = Path(frozen)
    path = frozen / FREEZE_RECEIPT
    if not path.is_file():
        raise TransferRefused(f"no R24 freeze receipt at {path}: the look reads only the frozen copy")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != _registered(FREEZE_RECEIPT_NAME):
        raise TransferRefused(f"freeze receipt schema {receipt.get('schema_version')!r}")
    try:
        through = date.fromisoformat(str(receipt["through"]))
        frozen_at = _utc(receipt["frozen_at_utc"])
        markets = receipt["markets"]
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferRefused(f"freeze receipt malformed: {exc}") from exc
    paths = {}
    for market in B_MARKETS:
        entry = markets.get(market) or {}
        csv_path = default_label_path(spec_for_id(market), frozen)
        wu_path = frozen / market / "wu" / "daily_summary.csv"
        csv_sha = (entry.get("label_csv") or {}).get("sha256")
        wu_sha = (entry.get("wu_daily_summary") or {}).get("sha256")
        if not csv_sha or not csv_path.is_file() or sha256_file(csv_path) != csv_sha:
            raise TransferRefused(f"frozen label CSV for {market} is missing or differs from the freeze receipt")
        if entry.get("label_csv_matches_manifest") is not True:
            raise TransferRefused(f"frozen label CSV for {market} did not match its manifest at freeze")
        if wu_sha and (not wu_path.is_file() or sha256_file(wu_path) != wu_sha):
            raise TransferRefused(f"frozen WU daily summary for {market} differs from the freeze receipt")
        paths[market] = {"venue_label_csv": csv_path, "wu_daily_summary": wu_path,
                         "shas": {csv_sha} | ({wu_sha} if wu_sha else set())}
    return {"receipt_sha256": sha256_file(path), "look_id": receipt.get("look_id"), "through": through,
            "frozen_at": frozen_at, "audit_status": receipt.get("audit_status"), "root": str(frozen)}, paths


def read_b_labels(frozen, paths, day):
    """``{market: (label_bucket, label_source)}`` for ``day`` from the frozen copy, or None (T2) on any refusal or missing row.

    Runs only inside the registered entry point (R24 (3)); ``read_through`` is ``day`` itself, so no row
    after it is parsed.
    """
    from weather.backtesting.venue_label_reader import read_venue_labels

    if not _entry_running():
        raise TransferRefused(f"labels are read only inside the registered entry point (python -m {ENTRY_MODULE})")
    buckets = {}
    for market in B_MARKETS:
        records, refusals = read_venue_labels(
            market, [day], read_through=day, allow_reserved_window=True, model_scoring=True, label_root=frozen,
            wu_daily_summary=paths[market]["wu_daily_summary"], venue_label_csv=paths[market]["venue_label_csv"])
        record = records.get(day.isoformat())
        if refusals or record is None:
            return None
        if record.get("source_sha256") not in paths[market]["shas"]:
            raise TransferRefused(f"a {market} label was read from bytes that are not the frozen copy")
        buckets[market] = (int(record["label_bucket"]), record.get("label_source"))
    return buckets


def _contains(kind, low, high, bucket):
    return (kind == "lte" or bucket >= low) and (kind == "gte" or bucket <= high)


def winners_for(bands, bucket):
    """Per row_key: the single band index containing ``bucket``, or absent when none or several do."""
    out = {}
    for row_key, group in bands.groupby("row_key", sort=False):
        hits = [int(r.band_index) for r in group.itertuples()
                if _contains(str(r.kind), float(r.low), float(r.high), bucket)]
        if len(hits) == 1:
            out[row_key] = hits[0]
    return out


def select_dates(input_dates, ledger_dates, label_of, through):
    """Input-countable dates in order through B's 45th countable date (T1, T2); non-countable ones listed.

    ``label_of(day)`` returns the day's labels or None (T2: non-countable). Labels are read only for
    ledger-countable dates up to the 45th.
    """
    rows, labels, non_countable, countable = [], {}, {}, 0
    for d in input_dates:
        key = d.isoformat()
        ok = ledger_dates.get(key, False)
        if not ok:
            non_countable[key] = NON_COUNTABLE_LEDGER
        else:
            if d > through:
                raise TransferRefused(f"the frozen label copy ends {through}, before countable date {key}")
            got = label_of(d)
            if got is None:
                ok = False
                non_countable[key] = NON_COUNTABLE_LABEL
            else:
                labels[key] = got
        rows.append((key, ok))
        countable += int(ok)
        if countable == N_DATES:
            return rows, labels, non_countable
    raise TransferRefused(f"only {countable} B-countable dates among {len(rows)} input-countable dates; "
                          f"the transfer needs {N_DATES}")


# --- frames, T3 coverage and T4 prices --------------------------------------------------------------------------

def build_labels(snaps, bands, rows, labels):
    """One label row per B layout snapshot on every manifest date; a winner only on countable dates."""
    import pandas as pd

    flag = dict(rows)
    s = snaps[snaps.date.isin(flag)].copy()
    missing = sorted(set(flag) - set(s.date))
    if missing:
        raise TransferRefused(f"the window layout has no B snapshot on {missing[:3]}")
    winner, bucket, source = {}, {}, {}
    for key, per_market in labels.items():
        day_keys = s[s.date == key]
        for market, (b, src) in per_market.items():
            keys = set(day_keys.row_key[day_keys.market == market])
            for row_key, w in winners_for(bands[bands.row_key.isin(keys)], b).items():
                winner[row_key] = w
            for row_key in keys:
                bucket[row_key], source[row_key] = b, src
    s["winner"] = s.row_key.map(winner)
    s["promotion_countable"] = s.date.map(flag).astype(bool)
    s["settlement_bucket"] = s.row_key.map(bucket)
    s["label_source"] = s.row_key.map(source)
    lab = s[list(LABEL_COLUMNS) + list(OPTIONAL_LABEL_COLUMNS)]
    lab = lab.sort_values(["date", "market", "row_key"]).reset_index(drop=True)
    for d, group in lab.groupby("date"):  # constancy: B's collapsed flag, B's 10 markets only
        if group.promotion_countable.nunique() != 1 or not set(group.market) <= set(B_MARKETS):
            raise TransferRefused(f"promotion_countable varies within {d} over B's markets")
    return pd.DataFrame(lab)


def coverage_problems(snaps, lab, rows):
    """T3, key-only: every B layout snapshot on a countable date has a label row with a winner."""
    countable = {d for d, c in rows if c}
    layout = set(snaps.row_key[snaps.date.isin(countable)])
    labelled = set(lab.row_key[lab.date.isin(countable) & lab.winner.notna()])
    problems = []
    if layout - labelled:
        problems.append(f"{len(layout - labelled)} B layout snapshots on countable dates have no label row")
    if labelled - layout:
        problems.append(f"{len(labelled - layout)} label rows on countable dates have no layout snapshot")
    return problems


def build_market(market, lab):
    """The price frame for the labelled rows, ``p_market_yes`` only through :func:`capture_price` (T4)."""
    import pandas as pd

    mkt = market[list(MARKET_COLUMNS)]
    mkt = mkt[mkt.row_key.astype(str).isin(set(lab.row_key))].copy()
    if mkt.duplicated(["row_key", "band_index"]).any():
        raise TransferRefused("duplicate (row_key, band_index) in the market export")
    bad = int(mkt.p_market_yes.map(_out_of_range).sum())
    if bad and REFUSE_FINITE_OUT_OF_RANGE:
        raise TransferRefused(f"{bad} capture-time prices are finite but outside [0, 1]")
    mkt["row_key"] = mkt.row_key.astype(str)
    mkt["band_index"] = mkt.band_index.astype(int)
    mkt["p_market_yes"] = [float("nan") if (p := capture_price(v)) is None else p for v in mkt.p_market_yes]
    mkt = mkt.sort_values(["row_key", "band_index"]).reset_index(drop=True)
    finite = mkt.p_market_yes.dropna()
    if not finite.between(0.0, 1.0).all():
        raise TransferRefused("a written price is outside [0, 1]")
    return pd.DataFrame(mkt)


def read_sidecar(coverage_root, day):
    """One date's published R19 counts sidecar (its SHA256SUMS line must match) and its sha256."""
    root = Path(coverage_root)
    path, sums = root / f"{day}.json", root / f"{day}{SIDECAR_SUMS_SUFFIX}"
    if not path.is_file() or not sums.is_file():
        raise TransferRefused(f"no published coverage sidecar for {day}")
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    line = sums.read_text(encoding="ascii").split()
    if len(line) < 2 or line[0].lower() != sha or line[1] != path.name:
        raise TransferRefused(f"the coverage sidecar for {day} does not match its SHA256SUMS")
    sidecar = json.loads(raw.decode("utf-8"))
    if sidecar.get("schema") != _registered(SIDECAR_NAME) or sidecar.get("target_date") != day:
        raise TransferRefused(f"the coverage sidecar for {day} has another schema or date")
    return sidecar, sha


def false_flags(sidecar):
    """Every R19 sidecar match flag that is false, by name: ``match``, ``bundle.ready_marker_matches``,
    ``sources.<market>.match`` (a missing flag counts as false)."""
    flags = {"match": sidecar.get("match"),
             "bundle.ready_marker_matches": (sidecar.get("bundle") or {}).get("ready_marker_matches")}
    for market, source in sorted((sidecar.get("sources") or {}).items()):
        flags[f"sources.{market}.match"] = (source or {}).get("match")
    return sorted(name for name, value in flags.items() if value is not True)


def sidecar_problems(lab, mkt, coverage_root):
    """T4: every transferred snapshot's ``[n_rows, n_priced]`` equals its date's sidecar counts.

    Returns the count problems (each refuses), the sidecar shas, and per date the false match flags (each holds
    the transfer unless a master override releases it).
    """
    rows = mkt.groupby("row_key").p_market_yes.agg(["size", "count"])
    shas, false, problems = {}, {}, []
    for day, group in lab.groupby("date", sort=True):
        sidecar, shas[day] = read_sidecar(coverage_root, day)
        if false_flags(sidecar):
            false[day] = false_flags(sidecar)
        counts = sidecar.get("counts") or {}
        bad = 0
        for row_key, market in zip(group.row_key, group.market):
            sid = row_key.split("|", 1)[1]
            got = [int(rows.loc[row_key, "size"]), int(rows.loc[row_key, "count"])] if row_key in rows.index                 else [0, 0]
            if list((counts.get(market) or {}).get(sid) or []) != got:
                bad += 1
        if bad:
            problems.append(f"{day}: {bad} snapshots' [n_rows, n_priced] differ from the coverage sidecar")
    return problems, shas, false


def read_override(path, now):
    """Master's dated, outcome-blind sidecar override: ``{(date, flag)}`` it releases, and its sha256.

    ``{"schema": b_transfer_sidecar_override, "dated": "YYYY-MM-DD", "outcome_blind": true,
    "releases": [{"date": "YYYY-MM-DD", "flag": "<flag name>", "reason": "..."}]}``. Only the exact
    (date, flag) pairs named are released; anything malformed refuses.
    """
    if not path:
        return set(), None
    p = Path(path)
    if not p.is_file():
        raise TransferRefused(f"sidecar override missing: {p}")
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
        dated = date.fromisoformat(str(body["dated"]))
        releases = {(date.fromisoformat(str(r["date"])).isoformat(), str(r["flag"])) for r in body["releases"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferRefused(f"sidecar override malformed: {exc}") from exc
    if body.get("schema") != _registered(OVERRIDE_NAME):
        raise TransferRefused(f"sidecar override schema {body.get('schema')!r}")
    if body.get("outcome_blind") is not True:
        raise TransferRefused("the sidecar override is not marked outcome_blind")
    if dated > now.date():
        raise TransferRefused(f"the sidecar override is dated {dated}, after the transfer")
    return releases, sha256_file(p)


def held_flags(false, releases):
    """The false sidecar flags no override releases, as ``date:flag`` strings (each holds the transfer)."""
    return [f"{day}:{flag}" for day, flags in sorted(false.items()) for flag in flags if (day, flag) not in releases]


def _read_export(path, required, what):
    import pandas as pd

    p = Path(path)
    if not p.is_file():
        raise TransferRefused(f"{what} export missing: {p}")
    frame = pd.read_parquet(p)
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise TransferRefused(f"{what} export lacks columns {missing}")
    return frame, sha256_file(p)


def write(*, market, input_window, ledger_root, frozen_labels, coverage_root, d0, mg1_look_receipt, out,
          sidecar_override=None, now=None):
    """Write the one ``b_transfer/1`` transfer; every refusal comes before the first file is written."""
    now = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    d0 = date.fromisoformat(str(d0))
    out = check_out(out)
    mg1_window_closed(now.date())
    receipt_sha, looked = read_receipt(mg1_look_receipt, now)
    input_dates, window, window_sha = read_input_window(input_window, d0)
    snaps, bands, layout_shas = read_layout_keys(input_window, window)
    freeze, frozen_paths = read_freeze(frozen_labels)
    flags, ledger_shas = read_ledger_flags(ledger_root, input_dates)
    ledger_dates = collapse_flags(flags, input_dates)

    def label_of(day):
        if now < embargo_end(day):
            raise TransferRefused(f"embargo: {day} has not ended in every market")
        return read_b_labels(frozen_labels, frozen_paths, day)

    rows, labels, non_countable = select_dates(input_dates, ledger_dates, label_of, freeze["through"])
    settled = embargo_end(rows[-1][0])
    if now < settled:
        raise TransferRefused(f"embargo: the 45th countable date {rows[-1][0]} has not ended in every market "
                              f"(until {settled.isoformat()})")
    if freeze["frozen_at"] < settled:
        raise TransferRefused("the label copy was frozen before the 45th countable date's finality (R24 (3))")
    lab = build_labels(snaps, bands, rows, labels)
    problems = coverage_problems(snaps, lab, rows)
    if problems:
        raise TransferRefused("T3 layout coverage: " + "; ".join(problems))
    mkt_src, market_sha = _read_export(market, MARKET_COLUMNS, "market")
    mkt = build_market(mkt_src, lab)
    problems, sidecar_shas, sidecar_false = sidecar_problems(lab, mkt, coverage_root)
    if problems:
        raise TransferRefused("T4 price counts: " + "; ".join(problems))
    releases, override_sha = read_override(sidecar_override, now)
    held = held_flags(sidecar_false, releases)
    if held:
        raise TransferRefused(f"HOLD: {len(held)} sidecar match flags are false and not released by a master "
                              f"override: {held[:5]}")

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
        "layout_sha256": layout_shas,
        "export_sha256": {"market": market_sha},
        "countable": {"rule": "T1: every one of B's 10 market-days promotion_countable (ledger latest revision)",
                      "markets": list(B_MARKETS), "ledger_root": str(ledger_root), "ledger_sha256": ledger_shas,
                      "non_countable": [{"date": d, "reason": r} for d, r in sorted(non_countable.items())]},
        "labels": {"reader": "venue_label_reader.read_venue_labels", "read_through": "each date itself",
                   "freeze_receipt_sha256": freeze["receipt_sha256"], "look_id": freeze["look_id"],
                   "frozen_root": freeze["root"], "frozen_through": freeze["through"].isoformat(),
                   "frozen_at_utc": freeze["frozen_at"].isoformat(), "audit_status": freeze["audit_status"]},
        "prices": {"predicate": "capture_price: a finite float in [0, 1], else NaN",
                   "refuse_finite_out_of_range": REFUSE_FINITE_OUT_OF_RANGE, "sidecar_sha256": sidecar_shas,
                   "sidecar_false_flags": sidecar_false, "sidecar_override_sha256": override_sha,
                   "sidecar_released": sorted(f"{d}:{f}" for d, f in releases
                                              if f in sidecar_false.get(d, []))},
        "writer": {"module": ENTRY_MODULE, "source_sha256": module_sha256(), "host": socket.gethostname()},
    }
    with open(out / TRANSFER_MANIFEST, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return {"status": "ok", "out": str(out), "dates": [rows[0][0], rows[-1][0], len(rows)],
            "countable": sum(int(c) for _, c in rows), "manifest_sha256": sha256_file(out / TRANSFER_MANIFEST)}


ARGS = ("market", "input-window", "ledger-root", "frozen-labels", "coverage-root", "d0", "mg1-look-receipt", "out")


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m {ENTRY_MODULE}", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write", help="write the one b_transfer/1 transfer (host, at the look)")
    for name in ARGS:
        w.add_argument(f"--{name}", required=True)
    w.add_argument("--sidecar-override", help="master's dated, outcome-blind override releasing false sidecar flags")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = write(**{name.replace("-", "_"): getattr(args, name.replace("-", "_")) for name in ARGS},
                       sidecar_override=args.sidecar_override)
    except TransferRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return exc.exit_code
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
