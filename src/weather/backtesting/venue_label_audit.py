"""Venue-rule labels for forward looks: per-run refresh, look-morning freeze, counts-only audit (R24).

Master ruling R24 (2026-11-01). The forward looks (MG-1, B/MG-2, L6_G, row 72, T+1, F8-MH) label their
post-cutover dates with the venue rule, and nothing produced those labels on the host. This module wraps
``weather.backtesting.venue_rule_labels`` into three host commands:

* ``refresh --through D [--start 2026-10-22]`` creates a new ``data/venue_rule_labels/runs/<utcRunId>/``
  (never reused), snapshots ``config/location_market_events.json`` and ``config/venue_rule_stations.json``
  into it, fetches routine-only IEM METAR for every label station serially 5 s apart into the run, builds
  all 12 built-in markets from the run, writes ``refresh_receipt.json`` (shas and counts) and runs the audit.
  Label stations: the 12 ``BUILTIN_SPECS`` ICAOs, every built-in station in the station config, and the
  ``resolutionSource`` ICAO of built-in events only (``slug_prefix`` match). A ``D`` after today is refused.
* ``freeze --look ID`` refreshes, then copies each market's CSV, manifest and the WU daily summary its
  manifest names to ``data/venue_rule_labels/frozen/ID/<market>/`` (``daily/daily_summary.csv``,
  ``manifest.json``, ``wu/daily_summary.csv``) with ``freeze_receipt.json``. It refuses unless the run's audit
  is OK, builds in a tmp folder and renames it only once verified; ``freeze --recover ID --ruling FILE`` moves a
  defective freeze aside (``weather.backtesting.venue_label_freeze``, master rulings 2026-11-03). The layout is
  the label reader's ``label_root`` layout, so a look reads the frozen copy with ``label_root=frozen/ID`` and
  ``wu_daily_summary=frozen/ID/<market>/wu/daily_summary.csv``.
* ``audit [--run ID]`` reads the run's manifests, the CSV provenance columns and ``row_count``, and prints
  per-market counts only. It evaluates a label value only to a yes/no (is it present; does a pre-cutover
  row pass the WU bucket through unchanged) and never emits one. ``STATION_DRIFT`` (an active built-in
  event's ICAO differs from the config or registry station for its date) exits non-zero.

Embargo: this module never imports the label reader, never opens the reserved window, and never writes a
label value, bucket or winner to stdout, a receipt or the audit. Research and host-ops only; no capture
loop or serving path imports it. Contract: ``docs/operations/venue-rule-labels.md`` ("Forward-look labels").
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from weather.backtesting.settlement_ledger import COMPLETE_DAY_MIN_ROWS
from weather.backtesting.venue_rule_labels import (
    BUILTIN_MARKET_IDS,
    DEFAULT_LABEL_ROOT,
    DEFAULT_STATION_CONFIG,
    LABEL_SOURCE_METAR,
    LABEL_SOURCE_WU,
    LABEL_SOURCE_WU_FALLBACK,
    STATION_BASIS_CONFIG,
    VENUE_RULE_CUTOVER_DATE,
    VENUE_RULE_VERSION,
    build_market_labels,
    default_label_path,
    default_manifest_path,
    fetch_routine,
    load_station_config,
    station_from_resolution_source,
)
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import config_path
from weather.schema_families import schema_version
from weather.sources.daily_summary import native_bucket, native_high

REFRESH_RECEIPT_SCHEMA = schema_version("venue_label_refresh_receipt")
FREEZE_RECEIPT_SCHEMA = schema_version("venue_label_freeze_receipt")
# The build-manifest key lists the freeze copies into each market's receipt entry (keys only, never the CSV).
FREEZE_KEY_FIELDS = ("label_dates", "skipped_dates")
AUDIT_SCHEMA = schema_version("venue_label_audit")

DEFAULT_START = date(2026, 10, 22)
DEFAULT_EVENTS = config_path("location_market_events.json")
RUNS_DIRNAME = "runs"
FROZEN_DIRNAME = "frozen"
LABELS_DIRNAME = "labels"
FETCH_SPACING_SECONDS = 5.0
EXIT_STATION_DRIFT = 3
STATION_DRIFT = "STATION_DRIFT"
DENVER_KDEN = ("denver", "KDEN")
_LOOK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

# The label reader's refusal reasons, mirrored (this module must not import the reader; a test pins equality).
REFUSED_MODEL_SCORING_EXCLUDED = "market_unsupported_for_model_scoring"
REFUSED_NO_WU_ROW = "no_wu_row"
REFUSED_NO_VENUE_CSV = "no_venue_label_csv"
REFUSED_NO_VENUE_ROW = "no_venue_label_row"
REFUSED_THIN_VENUE_ROW = "venue_label_row_below_complete_day_rows"
REFUSED_BAD_VENUE_ROW = "venue_label_row_provenance_mismatch"
MODEL_SCORING_EXCLUDED_FROM = {"denver": VENUE_RULE_CUTOVER_DATE}
_VENUE_SOURCES = (LABEL_SOURCE_METAR, LABEL_SOURCE_WU_FALLBACK)


class AuditRefused(ValueError):
    """The command is not allowed (date after today, reused run or look folder, bad look id)."""


def _sha256(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dates(start, through):
    return [date.fromordinal(day) for day in range(start.toordinal(), through.toordinal() + 1)]


# --- stations -----------------------------------------------------------------------------------------------


def builtin_event_sources(events_payload):
    """``[(market_id, event_date, resolution_source_url)]`` for built-in events only (``slug_prefix`` match)."""

    out = []
    for location in (events_payload or {}).get("locations") or ():
        for event in location.get("active_events") or ():
            slug = str(event.get("event_slug") or "")
            for spec in BUILTIN_SPECS:
                if spec.slug_prefix in slug and event.get("event_date"):
                    out.append((spec.id, str(event["event_date"]), event.get("resolution_source_url") or ""))
    return out


def label_stations(station_config, events_payload):
    """Every ICAO the builds can read: registry, built-in config entries, built-in event resolution sources."""

    stations = {spec.icao.upper() for spec in BUILTIN_SPECS}
    for market_id, entries in station_config.items():
        if market_id in BUILTIN_MARKET_IDS:
            stations |= {icao for _, icao in entries}
    for _, _, url in builtin_event_sources(events_payload):
        icao = station_from_resolution_source(url)
        if icao:
            stations.add(icao)
    return sorted(stations)


def expected_station(spec, target_date, station_config):
    """The config station effective on the date, else the registry station: ``(icao, basis)``."""

    chosen = None
    for effective_from, icao in station_config.get(spec.id, ()):
        if effective_from <= target_date:
            chosen = icao
    return (chosen, STATION_BASIS_CONFIG) if chosen else (spec.icao.upper(), "registry")


def station_drift(events_payload, station_config, start):
    """``(drift_rows, unparsed_count)`` over active built-in events dated on or after ``start``."""

    specs = {spec.id: spec for spec in BUILTIN_SPECS}
    drift, unparsed = [], 0
    for market_id, event_date, url in builtin_event_sources(events_payload):
        try:
            day = date.fromisoformat(event_date[:10])
        except ValueError:
            unparsed += 1
            continue
        if day < start:
            continue
        icao = station_from_resolution_source(url)
        if not icao:
            unparsed += 1
            continue
        expected, basis = expected_station(specs[market_id], day, station_config)
        if icao != expected:
            drift.append({"market_id": market_id, "event_date": day.isoformat(), "event_icao": icao,
                          "expected_icao": expected, "expected_basis": basis})
    return sorted(drift, key=lambda row: (row["market_id"], row["event_date"])), unparsed


# --- audit --------------------------------------------------------------------------------------------------


def read_dated_rows(path, start, through):
    """Rows keyed by local date inside ``[start, through]``; rows outside are dropped before any column is read."""

    path = Path(path)
    if not path.is_file():
        return None
    rows = {}
    for row in csv.DictReader(path.read_bytes().decode("utf-8-sig").splitlines()):
        local_date = (row.get("local_date") or "").strip()
        if not local_date:
            continue
        day = date.fromisoformat(local_date)
        if start <= day <= through:
            rows[local_date] = row
    return rows


def _has_label(row):
    return native_high(row) is not None and native_bucket(row) is not None


def _same_bucket(left, right):
    return native_bucket(left) == native_bucket(right)


def predicted_refusals(market_id, targets, venue_rows, wu_rows, model_scoring):
    """The label reader's refusal reason per date, from the same rows it would read (``read_through`` = last)."""

    excluded_from = MODEL_SCORING_EXCLUDED_FROM.get(market_id) if model_scoring else None
    refusals = {}
    for target in targets:
        key = target.isoformat()
        if excluded_from is not None and target >= excluded_from:
            refusals[key] = REFUSED_MODEL_SCORING_EXCLUDED
        elif target < VENUE_RULE_CUTOVER_DATE:
            row = (wu_rows or {}).get(key)
            if row is None or not _has_label(row):
                refusals[key] = REFUSED_NO_WU_ROW
        elif venue_rows is None:
            refusals[key] = REFUSED_NO_VENUE_CSV
        elif key not in venue_rows:
            refusals[key] = REFUSED_NO_VENUE_ROW
        else:
            row = venue_rows[key]
            if (row.get("label_source") not in _VENUE_SOURCES
                    or row.get("label_rule_version") != VENUE_RULE_VERSION
                    or row.get("label_cutover_date") != VENUE_RULE_CUTOVER_DATE.isoformat()):
                refusals[key] = REFUSED_BAD_VENUE_ROW
            elif (_int(row.get("row_count")) or 0) < COMPLETE_DAY_MIN_ROWS:
                refusals[key] = REFUSED_THIN_VENUE_ROW
            elif not _has_label(row):
                refusals[key] = REFUSED_BAD_VENUE_ROW
    return refusals


def _counts(values):
    return dict(sorted(Counter(values).items()))


def audit_market(spec, labels_root, start, through, current_station_config_sha):
    """Counts-only audit of one market's manifest and CSV for target dates ``start..through``."""

    manifest_path = default_manifest_path(spec, labels_root)
    csv_path = default_label_path(spec, labels_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    meta = manifest or {}
    venue_rows = read_dated_rows(csv_path, start, through)
    rows = venue_rows or {}
    wu_rows = read_dated_rows(meta["wu_daily_summary"], start, through) if meta.get("wu_daily_summary") else None
    targets = _dates(start, through)
    post = {key: row for key, row in rows.items() if date.fromisoformat(key) >= VENUE_RULE_CUTOVER_DATE}
    pre = {key: row for key, row in rows.items() if key not in post}
    skipped = {day: reason for day, reason in (meta.get("skipped_dates") or {}).items()
               if start <= date.fromisoformat(day) <= through}
    inputs = meta.get("metar_inputs") or ()
    is_denver = spec.id == DENVER_KDEN[0]
    return {
        "manifest_present": manifest is not None,
        "csv_present": venue_rows is not None,
        "output_sha256_matches_manifest": (
            venue_rows is not None and manifest is not None and _sha256(csv_path) == meta.get("output_sha256")),
        "station_config_sha256": meta.get("station_config_sha256"),
        "station_config_sha256_matches_checked_in": (
            manifest is not None and meta.get("station_config_sha256") == current_station_config_sha),
        "metar_input_count": len(inputs),
        "metar_inputs_without_sha256": sum(1 for item in inputs if not item.get("sha256")),
        "label_source_counts": _counts(row.get("label_source") or "" for row in rows.values()),
        "skipped_date_count": len(skipped),
        "skipped_reason_counts": _counts(skipped.values()),
        "predicted_refusal_counts": _counts(
            predicted_refusals(spec.id, targets, venue_rows, wu_rows, model_scoring=False).values()),
        "predicted_refusal_counts_model_scoring": _counts(
            predicted_refusals(spec.id, targets, venue_rows, wu_rows, model_scoring=True).values()),
        "thin_row_count": sum(1 for row in post.values() if (_int(row.get("row_count")) or 0) < COMPLETE_DAY_MIN_ROWS),
        "body_basis_row_count": sum(1 for row in post.values() if "body" in (row.get("label_value_basis") or "")),
        "denver_kden_config_override_rows": sum(
            1 for row in post.values()
            if row.get("label_station") == DENVER_KDEN[1] and row.get("label_station_basis") == STATION_BASIS_CONFIG
        ) if is_denver else None,
        "denver_fallback_rows": (
            sum(1 for row in post.values() if row.get("label_source") == LABEL_SOURCE_WU_FALLBACK) if is_denver else None),
        "pre_cutover_rows": len(pre),
        "pre_cutover_pass_through_mismatches": sum(
            1 for key, row in pre.items()
            if row.get("label_source") != LABEL_SOURCE_WU or key not in (wu_rows or {})
            or not _same_bucket(row, wu_rows[key])),
    }

def audit_run(run_dir, *, station_config_path=DEFAULT_STATION_CONFIG):
    """The counts-only audit of one run; ``status`` is ``STATION_DRIFT`` or ``OK``."""

    run_dir = Path(run_dir)
    receipt = json.loads((run_dir / "refresh_receipt.json").read_text(encoding="utf-8"))
    start, through = date.fromisoformat(receipt["start"]), date.fromisoformat(receipt["through"])
    events = json.loads((run_dir / "location_market_events.json").read_text(encoding="utf-8"))
    station_config = load_station_config(run_dir / "venue_rule_stations.json")
    drift, unparsed = station_drift(events, station_config, start)
    current_sha = _sha256(station_config_path)
    markets = {spec.id: audit_market(spec, run_dir / LABELS_DIRNAME, start, through, current_sha)
               for spec in BUILTIN_SPECS}
    return {
        "schema_version": AUDIT_SCHEMA,
        "run_id": receipt["run_id"],
        "start": start.isoformat(),
        "through": through.isoformat(),
        "status": STATION_DRIFT if drift else "OK",
        "station_drift": drift,
        "event_station_unparsed_count": unparsed,
        "checked_in_station_config_sha256": current_sha,
        "complete_day_min_rows": COMPLETE_DAY_MIN_ROWS,
        "markets": markets,
    }


# --- refresh and freeze -------------------------------------------------------------------------------------


def _utc_run_id(now):
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def refresh(
    through,
    *,
    start=DEFAULT_START,
    label_root=DEFAULT_LABEL_ROOT,
    events_path=None,
    station_config_path=None,
    wu_daily_summaries=None,
    client=None,
    sleep=None,
    now=None,
    today=None,
):
    """Fetch and build one new run; returns ``(run_dir, receipt, audit)``. ``client`` and ``sleep`` are for tests."""

    now = now or datetime.now(timezone.utc)
    today = today or date.today()
    events_path = Path(events_path or DEFAULT_EVENTS)
    station_config_path = Path(station_config_path or DEFAULT_STATION_CONFIG)
    sleep = sleep or time.sleep
    if through > today:
        raise AuditRefused(f"--through {through.isoformat()} is after today {today.isoformat()}")
    if start > through:
        raise AuditRefused(f"--start {start.isoformat()} is after --through {through.isoformat()}")
    run_id = _utc_run_id(now)
    run_dir = Path(label_root) / RUNS_DIRNAME / run_id
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir()
    except FileExistsError as exc:
        raise AuditRefused(f"{run_dir} exists: a run folder is never reused") from exc
    events_copy = run_dir / "location_market_events.json"
    shutil.copyfile(events_path, events_copy)
    config_copy = run_dir / "venue_rule_stations.json"
    shutil.copyfile(station_config_path, config_copy)
    events = json.loads(events_copy.read_text(encoding="utf-8"))
    stations = label_stations(load_station_config(config_copy), events)
    fetches = []
    for index, icao in enumerate(stations):
        if index:
            sleep(FETCH_SPACING_SECONDS)
        path = fetch_routine(icao, start, through, metar_root=run_dir, client=client)
        fetches.append({"icao": icao, "path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size})
    markets = {}
    for spec in BUILTIN_SPECS:
        manifest = build_market_labels(
            spec,
            wu_daily_summary=(wu_daily_summaries or {}).get(spec.id),
            metar_root=run_dir,
            station_config_path=config_copy,
            events_payload=events,
            out=default_label_path(spec, run_dir / LABELS_DIRNAME),
            manifest=default_manifest_path(spec, run_dir / LABELS_DIRNAME),
        )
        markets[spec.id] = {
            "output_sha256": manifest["output_sha256"],
            "manifest_sha256": _sha256(default_manifest_path(spec, run_dir / LABELS_DIRNAME)),
            "wu_daily_summary_sha256": manifest["wu_daily_summary_sha256"],
            "label_source_counts": manifest["label_source_counts"],
            "skipped_date_count": len(manifest["skipped_dates"]),
        }
    receipt = {
        "schema_version": REFRESH_RECEIPT_SCHEMA,
        "run_id": run_id,
        "start": start.isoformat(),
        "through": through.isoformat(),
        "created_at_utc": now.astimezone(timezone.utc).isoformat(),
        "module_sha256": _sha256(__file__),
        "events_snapshot": {"source": str(events_path), "sha256": _sha256(events_copy)},
        "station_config": {"source": str(station_config_path), "sha256": _sha256(config_copy)},
        "stations": stations,
        "fetch_spacing_seconds": FETCH_SPACING_SECONDS,
        "fetches": fetches,
        "markets": markets,
    }
    _write_json(run_dir / "refresh_receipt.json", receipt)
    audit = audit_run(run_dir, station_config_path=station_config_path)
    _write_json(run_dir / "audit.json", audit)
    return run_dir, receipt, audit


def freeze(look_id, through, **kwargs):
    """``freeze --look ID``: ``weather.backtesting.venue_label_freeze.freeze`` (refuses unless OK; atomic)."""
    from weather.backtesting import venue_label_freeze

    return venue_label_freeze.freeze(look_id, through, **kwargs)


def latest_run(label_root=DEFAULT_LABEL_ROOT):
    """The newest run that finished (has a refresh receipt); a run that failed mid-fetch has none."""

    runs = sorted(path.parent for path in (Path(label_root) / RUNS_DIRNAME).glob("*/refresh_receipt.json"))
    if not runs:
        raise AuditRefused(f"no finished run under {Path(label_root) / RUNS_DIRNAME}")
    return runs[-1]


# --- CLI ----------------------------------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.backtesting.venue_label_audit",
                                     description="Venue-rule labels for forward looks (R24).")
    parser.add_argument("--label-root", default=str(DEFAULT_LABEL_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("refresh", "freeze"):
        command = sub.add_parser(name, help="network: routine-only IEM fetches into a new run, then build and audit")
        command.add_argument("--through", required=name == "refresh", type=date.fromisoformat)
        command.add_argument("--start", default=DEFAULT_START, type=date.fromisoformat)
        if name == "freeze":
            command.add_argument("--look", help="the look id to freeze (with --through)")
            command.add_argument("--recover", metavar="LOOK", help="move a defective frozen/LOOK aside (no fetch)")
            command.add_argument("--ruling", help="master's dated, outcome-blind recovery ruling (with --recover)")
    audit = sub.add_parser("audit", help="counts-only audit of a run (default: the latest)")
    audit.add_argument("--run", default="")
    return parser


def _summary(receipt_like, audit):
    return {"status": audit["status"], "run_id": audit["run_id"], **receipt_like}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "refresh":
            run_dir, _, audit = refresh(args.through, start=args.start, label_root=args.label_root)
            extra = {"run_dir": str(run_dir)}
        elif args.command == "freeze" and args.recover:
            from weather.backtesting import venue_label_freeze

            if not args.ruling or args.look or args.through:
                raise AuditRefused("freeze --recover LOOK takes --ruling FILE and no --look or --through")
            print(json.dumps(venue_label_freeze.recover(args.recover, args.ruling, label_root=args.label_root),
                             indent=2, sort_keys=True))
            return 0
        elif args.command == "freeze":
            if not args.look or not args.through or args.ruling:
                raise AuditRefused("freeze takes --look ID and --through D (--ruling only with --recover)")
            look_dir, receipt, audit = freeze(args.look, args.through, start=args.start, label_root=args.label_root)
            extra = {"look_dir": str(look_dir), "freeze_receipt_sha256": _sha256(look_dir / "freeze_receipt.json"),
                     "ignored_partial_dirs": receipt["ignored_partial_dirs"],
                     "frozen_sha256": {market: {name: entry[name]["sha256"] for name in ("label_csv", "manifest",
                                                                                    "wu_daily_summary")}
                                       for market, entry in receipt["markets"].items()}}
        else:
            run_dir = Path(args.label_root) / RUNS_DIRNAME / args.run if args.run else latest_run(args.label_root)
            audit = audit_run(run_dir)
            extra = {"run_dir": str(run_dir)}
    except AuditRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    print(json.dumps({**_summary(extra, audit), "audit": audit}, indent=2, sort_keys=True))
    return EXIT_STATION_DRIFT if audit["status"] == STATION_DRIFT else 0


if __name__ == "__main__":
    sys.exit(main())
