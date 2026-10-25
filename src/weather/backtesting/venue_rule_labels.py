"""Venue-rule settlement labels for training and evaluation (event Rules from 2026-10-23).

From the 2026-10-23 events the venue resolves the built-in markets on the raw
AviationWeather METAR feed (EF 10x): the label is the highest **routine**
METAR temperature on the market's local date.

* A report that begins with ``SPECI`` does not count. IEM raw text has no
  prefix, so routine-only IEM files are fetched with ``report_type=3`` and
  declared routine; a prefix in the text always wins over the declaration.
* Temperature is the remark T-group in tenths of a degree C; a missing or
  malformed T-group falls back to the whole-degree body value.
* Fahrenheit markets convert with ``C x 9/5 + 32`` and round half up to a
  whole degree; Celsius markets round the tenths half up to a whole degree C
  (both through ``weather.units``).
* A corrected (``COR``) report replaces the original at its observation time
  while it is received before the next local day's first report. IEM rows
  carry no receipt time, so an IEM correction is accepted.
* A local date is labelled only once a later report exists (the venue resolves
  at the next day's first report). When the stream spans the date but holds no
  routine temperature, WU Daily Observations is the fallback, used only when
  the WU station is the venue station.
* Dates before ``VENUE_RULE_CUTOVER_DATE`` keep the WU label unchanged.

The output is a per-market daily-summary CSV in the shared native schema
(``max_temp``, ``max_temp_bucket``, ``row_count``, ``max_temp_times``) plus
``label_*`` provenance columns, so every consumer that already takes a
daily-summary path (ledger finalize, forecast-error training) reads it as-is.
This module is training/evaluation only: no capture loop or serving path
imports it. The spec is ``docs/operations/venue-rule-labels.md``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from weather.market.market_registry import BUILTIN_SPECS, spec_for_id
from weather.paths import config_path, data_path
from weather.sources.daily_summary import native_bucket, native_high
from weather.sources.historical_schema import DAILY_COLUMNS, summarize_daily
from weather.sources.metar_history import (
    IEM_REPORT_TYPE_ROUTINE,
    REPORT_TYPE_ROUTINE,
    MetarClient,
    classify_report_type,
    is_corrected_report,
    normalize_csv,
    parse_date,
    report_temperature_c,
)
from weather.units import c_to_native, round_half_up

# The one cutover: target dates on or after it take the venue rule.
VENUE_RULE_CUTOVER_DATE = date(2026, 10, 23)
VENUE_RULE_VERSION = "venue-metar-routine-v1"
STATION_CONFIG_SCHEMA = "venue-rule-stations-v1"
MANIFEST_SCHEMA = "venue-rule-labels-manifest-v1"

DEFAULT_STATION_CONFIG = config_path("venue_rule_stations.json")
DEFAULT_LABEL_ROOT = data_path("venue_rule_labels")
DEFAULT_METAR_ROOT = DEFAULT_LABEL_ROOT / "metar"

LABEL_SOURCE_METAR = "metar_routine"
LABEL_SOURCE_WU = "wu_history"
LABEL_SOURCE_WU_FALLBACK = "wu_fallback_no_routine_metar"

STATION_BASIS_CONFIG = "config_override"
STATION_BASIS_EVENT = "event_resolution_source"
STATION_BASIS_REGISTRY = "registry"

PROVENANCE_COLUMNS = [
    "label_source",
    "label_station",
    "label_station_basis",
    "label_event_station",
    "label_rule_version",
    "label_cutover_date",
    "label_value_basis",
    "label_routine_report_count",
    "label_corrected_report_count",
    "label_note",
]
OUTPUT_COLUMNS = list(DAILY_COLUMNS) + PROVENANCE_COLUMNS

BUILTIN_MARKET_IDS = frozenset(spec.id for spec in BUILTIN_SPECS)


def venue_rule_applies(spec, target_date, cutover=VENUE_RULE_CUTOVER_DATE):
    """True when the venue rule labels ``spec`` on ``target_date``."""

    return spec.id in BUILTIN_MARKET_IDS and parse_date(target_date) >= cutover


def default_label_path(spec, root=DEFAULT_LABEL_ROOT):
    return Path(root) / spec.id / "daily" / "daily_summary.csv"


def default_manifest_path(spec, root=DEFAULT_LABEL_ROOT):
    return Path(root) / spec.id / "manifest.json"


def wu_station_icao(spec):
    """The station of the market's configured WU history (``KBKF:9:US`` -> ``KBKF``)."""

    return str(spec.wu_history_id or spec.icao).split(":", 1)[0].upper()


# --- station selection --------------------------------------------------------


def station_from_resolution_source(url):
    """Return the ICAO named by an event ``resolutionSource`` URL, or None."""

    if not url:
        return None
    parsed = urlparse(str(url))
    query = parse_qs(parsed.query)
    for key in ("ids", "site", "station"):
        for value in query.get(key) or ():
            first = value.split(",", 1)[0].strip().upper()
            if len(first) == 4 and first.isalnum():
                return first
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1].upper()
    if len(tail) == 4 and tail.isalnum() and tail[0].isalpha():
        return tail
    return None


def load_station_config(path=DEFAULT_STATION_CONFIG):
    """Read the dated per-market station overrides (empty when absent)."""

    path = Path(path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != STATION_CONFIG_SCHEMA:
        raise ValueError(
            f"{path}: schema_version {payload.get('schema_version')!r}, expected {STATION_CONFIG_SCHEMA!r}"
        )
    markets = {}
    for market_id, entries in (payload.get("markets") or {}).items():
        parsed = []
        for entry in entries:
            icao = str(entry["station_icao"]).strip().upper()
            if len(icao) != 4 or not icao.isalnum():
                raise ValueError(f"{path}: {market_id}: invalid station_icao {icao!r}")
            parsed.append((date.fromisoformat(entry["effective_from"]), icao))
        effective = [item[0] for item in parsed]
        if len(set(effective)) != len(effective):
            raise ValueError(f"{path}: {market_id}: duplicate effective_from")
        markets[market_id] = sorted(parsed)
    return markets


def resolve_station(spec, target_date, station_config=None, event_resolution_source=None):
    """Pick the label station for one market-date.

    A dated config entry (the latest ``effective_from`` on or before the date)
    wins; then the event's ``resolutionSource`` ICAO; then the registry ICAO.
    """

    target_date = parse_date(target_date)
    event_station = station_from_resolution_source(event_resolution_source)
    chosen = None
    for effective_from, icao in (station_config or {}).get(spec.id, ()):
        if effective_from <= target_date:
            chosen = icao
    if chosen:
        basis = STATION_BASIS_CONFIG
    elif event_station:
        chosen, basis = event_station, STATION_BASIS_EVENT
    else:
        chosen, basis = spec.icao.upper(), STATION_BASIS_REGISTRY
    return {"icao": chosen, "basis": basis, "event_icao": event_station or ""}


def event_sources_by_date(events_payload, spec):
    """Map event date -> resolutionSource URL for one market from a Gamma snapshot."""

    out = {}
    for location in (events_payload or {}).get("locations") or ():
        for event in location.get("active_events") or ():
            slug = str(event.get("event_slug") or "")
            if spec.slug_prefix not in slug or not event.get("event_date"):
                continue
            out[str(event["event_date"])] = event.get("resolution_source_url") or ""
    return out


# --- per-report parsing -------------------------------------------------------


def native_value(temperature_c, unit):
    """Exact-tenths C -> native unit value (float) for half-up bucketing."""

    return c_to_native(float(temperature_c), unit, digits=None)


def _receipt_times(text):
    """Optional ``receipt_time`` column keyed by IEM ``valid`` (AWC receipts)."""

    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        value = (row.get("receipt_time") or "").strip()
        if value and row.get("valid"):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            out[row["valid"].strip()] = parsed.astimezone(timezone.utc)
    return out


def reports_from_csv(text, spec, station, declared_report_type=None):
    """Parse one IEM-shaped CSV (``valid``, ``tmpc``, ``metar``) into report dicts.

    Every report is kept with its type; the caller filters. ``spec`` supplies
    the zone and unit, ``station`` the ICAO the file is for.
    """

    station_spec = replace(spec, icao=station)
    receipts = _receipt_times(text)
    reports = []
    for record in normalize_csv(text, station_spec):
        raw = record.get("source_quality") or ""
        temperature_c, basis = report_temperature_c(raw)
        valid_utc = datetime.fromisoformat(record["valid_time_utc"])
        iem_valid = valid_utc.strftime("%Y-%m-%d %H:%M")
        reports.append({
            "station": station,
            "valid_time_utc": valid_utc,
            "record": record,
            "local_date": record["local_date"],
            "report_type": classify_report_type(raw, declared=declared_report_type),
            "corrected": is_corrected_report(raw),
            "temperature_c": temperature_c,
            "value_basis": basis,
            "receipt_utc": receipts.get(iem_valid),
            "raw": raw,
        })
    reports.sort(key=lambda item: item["valid_time_utc"])
    return reports


def select_reports(routine_reports):
    """One report per observation time; an accepted correction replaces the original.

    A correction is accepted unless its receipt time is known and falls at or
    after the first report of the next local day.
    """

    first_by_date = {}
    for report in routine_reports:
        first_by_date.setdefault(report["local_date"], report["valid_time_utc"])
    dates = sorted(first_by_date)

    def deadline(local_date):
        later = [day for day in dates if day > local_date]
        return first_by_date[later[0]] if later else None

    chosen = {}
    rejected = 0
    for report in routine_reports:
        key = report["valid_time_utc"]
        if report["corrected"]:
            limit = deadline(report["local_date"])
            receipt = report.get("receipt_utc")
            if receipt is not None and (limit is None or receipt >= limit):
                rejected += 1
                continue
            chosen[key] = report
            continue
        current = chosen.get(key)
        if current is None or not current["corrected"]:
            chosen[key] = report
    return [chosen[key] for key in sorted(chosen)], rejected


# --- daily labels -------------------------------------------------------------


def venue_daily_labels(reports, spec):
    """Return ``{local_date: daily_row}`` for the routine reports of one station.

    A date is labelled only when a later report exists. Rows follow
    ``historical_schema.summarize_daily`` with the venue value as ``temp_native``.
    """

    routine = [report for report in reports if report["report_type"] == REPORT_TYPE_ROUTINE]
    selected, rejected = select_reports(routine)
    latest_date = max((report["local_date"] for report in reports), default=None)
    by_date = defaultdict(list)
    for report in selected:
        if report["temperature_c"] is not None:
            by_date[report["local_date"]].append(report)
    labels = {}
    for local_date, day_reports in by_date.items():
        if latest_date is None or local_date >= latest_date:
            continue
        records = [
            {**report["record"], "temp_native": native_value(report["temperature_c"], spec.display_unit)}
            for report in day_reports
        ]
        (row,) = summarize_daily(records)
        bases = sorted({report["value_basis"] for report in day_reports})
        row.update({
            "source": "metar_routine",
            "label_source": LABEL_SOURCE_METAR,
            "label_value_basis": "|".join(bases),
            "label_routine_report_count": len(day_reports),
            "label_corrected_report_count": sum(1 for report in day_reports if report["corrected"]),
            "label_note": f"rejected_late_corrections={rejected}" if rejected else "",
        })
        labels[local_date] = row
    return labels


def stream_span(reports):
    """``(first, last)`` local dates the station's report stream covers, or Nones."""

    dates = [report["local_date"] for report in reports]
    return (min(dates), max(dates)) if dates else (None, None)


def read_wu_rows(path):
    """WU daily-summary rows keyed by local date, with the native high and bucket."""

    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date = row.get("local_date")
            bucket = native_bucket(row)
            if local_date and bucket is not None:
                rows[local_date] = row
    return rows


def _wu_output_row(spec, wu_row, label_source, note=""):
    out = {column: wu_row.get(column, "") for column in DAILY_COLUMNS}
    out.update({
        "market_id": wu_row.get("market_id") or spec.id,
        "local_date": wu_row["local_date"],
        "max_temp": native_high(wu_row),
        "max_temp_bucket": native_bucket(wu_row),
        "label_source": label_source,
        "label_station": wu_station_icao(spec),
        "label_value_basis": "wu_daily_summary",
        "label_note": note,
    })
    return out


def build_label_rows(
    spec,
    wu_rows,
    reports_by_station,
    station_config=None,
    event_sources=None,
    cutover=VENUE_RULE_CUTOVER_DATE,
    target_dates=None,
):
    """Composite daily label rows for one market, sorted by date.

    ``reports_by_station`` maps ICAO -> parsed reports (any types). Before the
    cutover a date keeps its WU row. From it, the venue rule labels the date
    from the resolved station; a spanned date without a routine temperature
    falls back to WU only when the WU station is the venue station. A date the
    station's stream does not span, or the stream's last date, has no row.
    """

    event_sources = event_sources or {}
    labels_by_station = {
        icao: venue_daily_labels(reports, spec) for icao, reports in reports_by_station.items()
    }
    spans = {icao: stream_span(reports) for icao, reports in reports_by_station.items()}
    if target_dates is None:
        candidates = set(wu_rows)
        for labels in labels_by_station.values():
            candidates.update(labels)
    else:
        candidates = {parse_date(day).isoformat() for day in target_dates}
    rows = []
    skipped = {}
    for local_date in sorted(candidates):
        day = date.fromisoformat(local_date)
        if not venue_rule_applies(spec, day, cutover=cutover):
            if local_date in wu_rows:
                row = _wu_output_row(spec, wu_rows[local_date], LABEL_SOURCE_WU)
                row.update({"label_station_basis": STATION_BASIS_REGISTRY})
                rows.append(row)
            else:
                skipped[local_date] = "no_wu_row_before_cutover"
            continue
        station = resolve_station(spec, day, station_config, event_sources.get(local_date))
        common = {
            "label_station_basis": station["basis"],
            "label_event_station": station["event_icao"],
        }
        label = labels_by_station.get(station["icao"], {}).get(local_date)
        if label is not None:
            row = {column: label.get(column, "") for column in OUTPUT_COLUMNS}
            row.update(common)
            row["label_station"] = station["icao"]
            rows.append(row)
            continue
        first, last = spans.get(station["icao"], (None, None))
        if first is None or not (first <= local_date < last):
            skipped[local_date] = f"metar_stream_does_not_close_{station['icao']}"
            continue
        if wu_station_icao(spec) != station["icao"]:
            skipped[local_date] = f"no_routine_metar_and_wu_station_is_not_{station['icao']}"
            continue
        if local_date not in wu_rows:
            skipped[local_date] = "no_routine_metar_and_no_wu_row"
            continue
        row = _wu_output_row(spec, wu_rows[local_date], LABEL_SOURCE_WU_FALLBACK)
        row.update(common)
        rows.append(row)
    for row in rows:
        row["label_rule_version"] = VENUE_RULE_VERSION
        row["label_cutover_date"] = cutover.isoformat()
        row.setdefault("label_event_station", "")
    return rows, skipped


def write_label_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
    return path


def _sha256(path):
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def routine_csv_files(metar_root, icao):
    return sorted((Path(metar_root) / icao.lower() / "routine").glob("*.csv"))


def build_market_labels(
    spec,
    wu_daily_summary=None,
    metar_root=DEFAULT_METAR_ROOT,
    station_config_path=DEFAULT_STATION_CONFIG,
    events_payload=None,
    out=None,
    manifest=None,
    cutover=VENUE_RULE_CUTOVER_DATE,
):
    """Build and write one market's composite label CSV and its manifest."""

    wu_daily_summary = Path(wu_daily_summary or spec.data_root / "daily" / "daily_summary.csv")
    station_config = load_station_config(station_config_path)
    stations = {spec.icao.upper()} | {
        icao for _, icao in station_config.get(spec.id, ())
    }
    event_sources = event_sources_by_date(events_payload, spec)
    stations |= {
        icao for icao in map(station_from_resolution_source, event_sources.values()) if icao
    }
    inputs = []
    reports_by_station = {}
    for icao in sorted(stations):
        reports = []
        for path in routine_csv_files(metar_root, icao):
            reports.extend(reports_from_csv(
                path.read_text(encoding="utf-8"), spec, icao, declared_report_type=IEM_REPORT_TYPE_ROUTINE,
            ))
            inputs.append({"path": str(path), "sha256": _sha256(path), "station": icao})
        if reports:
            reports.sort(key=lambda item: item["valid_time_utc"])
            reports_by_station[icao] = reports
    rows, skipped = build_label_rows(
        spec,
        read_wu_rows(wu_daily_summary),
        reports_by_station,
        station_config=station_config,
        event_sources=event_sources,
        cutover=cutover,
    )
    out = Path(out or default_label_path(spec))
    write_label_csv(out, rows)
    counts = defaultdict(int)
    for row in rows:
        counts[row["label_source"]] += 1
    payload = {
        "schema_version": MANIFEST_SCHEMA,
        "market_id": spec.id,
        "rule_version": VENUE_RULE_VERSION,
        "cutover_date": cutover.isoformat(),
        "unit": spec.display_unit,
        "output": str(out),
        "output_sha256": _sha256(out),
        "wu_daily_summary": str(wu_daily_summary),
        "wu_daily_summary_sha256": _sha256(wu_daily_summary),
        "station_config": str(station_config_path),
        "station_config_sha256": _sha256(station_config_path),
        "metar_inputs": inputs,
        "label_source_counts": dict(sorted(counts.items())),
        "skipped_dates": dict(sorted(skipped.items())),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest = Path(manifest or default_manifest_path(spec))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def fetch_routine(icao, start_date, end_date, metar_root=DEFAULT_METAR_ROOT, client=None):
    """Download one routine-only IEM CSV with raw text (network; host use)."""

    start_date, end_date = parse_date(start_date), parse_date(end_date)
    client = client or MetarClient()
    text = client.fetch(
        icao, start_date, end_date, report_types=(IEM_REPORT_TYPE_ROUTINE,), include_metar_text=True,
    )
    path = Path(metar_root) / icao.lower() / "routine" / (
        f"asos_routine_{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_parser():
    parser = argparse.ArgumentParser(description="Venue-rule (routine METAR) settlement labels.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Write one market's composite label CSV and manifest.")
    build.add_argument("--market", required=True)
    build.add_argument("--wu-daily-summary", default="")
    build.add_argument("--metar-root", default=str(DEFAULT_METAR_ROOT))
    build.add_argument("--station-config", default=str(DEFAULT_STATION_CONFIG))
    build.add_argument("--events", default="", help="Optional Gamma event snapshot for resolutionSource ICAOs.")
    build.add_argument("--out", default="")
    build.add_argument("--manifest", default="")
    fetch = sub.add_parser("fetch", help="Download routine-only IEM METAR (network).")
    fetch.add_argument("--station", required=True)
    fetch.add_argument("--start", required=True)
    fetch.add_argument("--end", required=True)
    fetch.add_argument("--metar-root", default=str(DEFAULT_METAR_ROOT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        print(fetch_routine(args.station.upper(), args.start, args.end, metar_root=args.metar_root))
        return 0
    events = json.loads(Path(args.events).read_text(encoding="utf-8")) if args.events else None
    payload = build_market_labels(
        spec_for_id(args.market),
        wu_daily_summary=args.wu_daily_summary or None,
        metar_root=args.metar_root,
        station_config_path=args.station_config,
        events_payload=events,
        out=args.out or None,
        manifest=args.manifest or None,
    )
    print(json.dumps({key: payload[key] for key in ("output", "label_source_counts")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
