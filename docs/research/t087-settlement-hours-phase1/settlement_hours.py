"""T087 descriptive, offline minimal-extract analysis. No fetch or default data path.

Run from the pinned repo root with its interpreter and PYTHONPATH=<repo>/src.
Phase 1 uses only in-memory synthetic fixtures in test_settlement_hours.py.
CLI refuses before opening any extract unless --phase2-owner-extract is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from weather.backtesting.venue_rule_labels import (
    load_station_config, native_value, resolve_station, select_reports,
)
from weather.market.market_registry import BUILTIN_SPECS
from weather.sources.metar_history import (
    REPORT_TYPE_ROUTINE, classify_report_type, is_corrected_report,
    report_temperature_c,
)
from weather.units import parse_temperature_band, round_half_up

START = date(2026, 10, 23)
THROUGH = date(2026, 11, 9)  # fixed before the master opens data; never today()
DEV_CUTOFF = date(2026, 9, 29)
SCHEMA = "t087-minimal-v1"
SPECS = {spec.id: spec for spec in BUILTIN_SPECS}
DAY_FIELDS = {"market_id", "target_date", "resolution_source_url", "bands",
              "paid_band", "observations", "complete"}
OBS_FIELDS = {"valid", "metar", "declared_report_type"}


class Refused(ValueError):
    """No result may be inferred for this input."""


def fields(obj, required, optional=()):
    if not isinstance(obj, dict) or not required <= obj.keys() or obj.keys() - required - set(optional):
        raise Refused("schema_fields")


def utc(value):
    if not isinstance(value, str):
        raise Refused("timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Refused("invalid_timestamp") from None
    if parsed.tzinfo is None:
        raise Refused("timestamp_requires_offset")
    return parsed.astimezone(timezone.utc)


def bounds(spec, day):
    """Calendar arithmetic in local time; elapsed comparisons exclusively UTC."""
    local = lambda d, hour: datetime.combine(d, time(hour), spec.tz).astimezone(timezone.utc)
    return local(day - timedelta(days=1), 21), local(day, 0), local(day + timedelta(days=1), 0)


def linked_window(url, station, envelope_start, day_start, day_end):
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc != "aviationweather.gov"
            or parsed.path != "/api/data/metar" or parsed.fragment
            or set(query) != {"ids", "format", "date", "hours"}
            or any(len(values) != 1 for values in query.values())):
        raise Refused("unsupported_resolution_source")
    if query["ids"] != [station] or query["format"] != ["raw"]:
        raise Refused("source_station_or_format_mismatch")
    if query["hours"][0] not in {"27", "30"}:
        raise Refused("unsupported_link_hours")
    hours = int(query["hours"][0])
    end = utc(query["date"][0])
    start = end - timedelta(hours=hours)
    if start < envelope_start:
        raise Refused("link_needs_observations_before_authorized_21")
    if start > day_start or end < day_end:
        raise Refused("link_does_not_cover_whole_target_date")
    return start, end, hours


def parsed_bands(labels, unit):
    if not isinstance(labels, list) or len(labels) < 2:
        raise Refused("missing_event_band_menu")
    bands = [parse_temperature_band(label, expected_unit=unit) for label in labels]
    if any(band is None for band in bands) or len(set(bands)) != len(bands):
        raise Refused("invalid_or_duplicate_event_band")
    ordered = sorted(bands, key=lambda b: (b.value, b.value_hi, b.kind))
    if (ordered[0].kind != "lte" or ordered[-1].kind != "gte"
            or any(b.kind != "eq" for b in ordered[1:-1])
            or any(a.value_hi + 1 != b.value for a, b in zip(ordered, ordered[1:]))):
        raise Refused("event_bands_do_not_partition_integer_degrees")
    return dict(zip(bands, labels))


def band_for(bucket, menu):
    matches = [band for band in menu if
               (bucket <= band.value if band.kind == "lte" else
                bucket >= band.value if band.kind == "gte" else
                band.value <= bucket <= band.value_hi)]
    if len(matches) != 1:
        raise Refused("degree_has_no_unique_event_band")
    return matches[0]


def prepare_reports(rows, spec, station, envelope_start, day_end, next_time=None):
    if not isinstance(rows, list):
        raise Refused("observations_must_be_list")
    reports = []
    seen = set()
    originals = {}
    corrections = {}
    for row in rows:
        fields(row, OBS_FIELDS, {"receipt_time"})
        valid = utc(row["valid"])
        if not envelope_start <= valid < day_end:
            raise Refused("observation_outside_authorized_envelope")
        raw = row["metar"]
        if not isinstance(raw, str):
            raise Refused("metar_must_be_text")
        # Explicit prefix wins, exactly as in the production routine filter.
        kind = classify_report_type(raw, declared=row["declared_report_type"])
        tokens = raw.replace("=", " ").split()
        head = tokens[:5]
        if station not in head:
            raise Refused("observation_station_mismatch")
        receipt = utc(row["receipt_time"]) if row.get("receipt_time") else None
        if receipt is not None and receipt < valid:
            raise Refused("receipt_precedes_observation")
        identity = (valid, raw, receipt, kind)
        if identity in seen:
            continue
        seen.add(identity)
        corrected = is_corrected_report(raw)
        if kind != REPORT_TYPE_ROUTINE:
            continue
        temperature, basis = report_temperature_c(raw)
        entry = dict(valid_time_utc=valid, local_date=valid.astimezone(spec.tz).date().isoformat(),
                     report_type=kind, corrected=corrected, receipt_utc=receipt,
                     temperature_c=temperature, value_basis=basis, raw=raw)
        table = corrections if corrected else originals
        # Without receipt order, multiple distinct revisions cannot safely be ordered.
        if valid in table and table[valid]["raw"] != raw:
            raise Refused("ambiguous_duplicate_observation_revision")
        table[valid] = entry
        reports.append(entry)
    reports.sort(key=lambda r: r["valid_time_utc"])  # stable COR ordering, production selector below
    if next_time is not None:
        next_valid = utc(next_time)
        if next_valid < day_end or next_valid >= day_end + timedelta(days=1):
            raise Refused("invalid_next_routine_timestamp")
        # Timestamp only: no next-date temperature or raw report is admitted.
        reports.append(dict(valid_time_utc=next_valid,
                            local_date=next_valid.astimezone(spec.tz).date().isoformat(),
                            corrected=False, receipt_utc=None, temperature_c=None))
    elif any(r["corrected"] and r["receipt_utc"] is not None
             and r["local_date"] == (day_end - timedelta(seconds=1)).astimezone(spec.tz).date().isoformat()
             for r in reports):
        raise Refused("correction_needs_next_routine_timestamp")
    selected, rejected = select_reports(reports)
    return [r for r in selected if r["valid_time_utc"] < day_end and r["temperature_c"] is not None], rejected


def maximum(reports, start, end, spec, menu):
    subset = [r for r in reports if start <= r["valid_time_utc"] < end]
    if not subset:
        raise Refused("no_routine_temperature_in_window")
    high_c = max(r["temperature_c"] for r in subset)
    high = native_value(high_c, spec.display_unit)
    degree = round_half_up(high)
    band = band_for(degree, menu)
    return {"max_native": high, "degree": degree, "band": menu[band],
            "maximum_times_utc": [r["valid_time_utc"].isoformat() for r in subset if r["temperature_c"] == high_c],
            "routine_temperature_count": len(subset)}, band


def compare_day(row, station_config):
    fields(row, DAY_FIELDS, {"next_routine_time_utc"})
    spec = SPECS[row["market_id"]]
    day = date.fromisoformat(row["target_date"])
    if row["complete"] is not True:
        raise Refused("extract_not_certified_complete")
    station = resolve_station(spec, day, station_config)["icao"]
    envelope_start, day_start, day_end = bounds(spec, day)
    start, query_end, hours = linked_window(row["resolution_source_url"], station, envelope_start, day_start, day_end)
    menu = parsed_bands(row["bands"], spec.display_unit)
    paid = parse_temperature_band(row["paid_band"], expected_unit=spec.display_unit)
    if paid not in menu:
        raise Refused("paid_band_not_final_or_not_in_event_menu")
    selected, rejected = prepare_reports(row["observations"], spec, station, envelope_start, day_end,
                                         row.get("next_routine_time_utc"))
    strict, strict_band = maximum(selected, day_start, day_end, spec, menu)
    linked, linked_band = maximum(selected, start, day_end, spec, menu)
    return {"market_id": spec.id, "target_date": day.isoformat(), "station": station,
            "unit": spec.display_unit, "hours": hours,
            "linked_start_utc": start.isoformat(), "query_end_utc": query_end.isoformat(),
            "analysis_end_exclusive_utc": day_end.isoformat(),
            "next_morning_tail_not_read": query_end > day_end,
            "strict": strict, "linked_through_day_end": linked, "paid_band": menu[paid],
            "strict_matches_paid": strict_band == paid, "linked_matches_paid": linked_band == paid,
            "bands_differ": strict_band != linked_band, "rejected_late_corrections": rejected}


def analyze(payload, *, phase2=False, synthetic=False):
    fields(payload, {"schema", "through", "days"})
    if payload["schema"] != SCHEMA or payload["through"] != THROUGH.isoformat():
        raise Refused("extract_schema_or_frozen_through_mismatch")
    if not isinstance(payload["days"], list):
        raise Refused("days_must_be_list")
    expected = {(m, (START + timedelta(days=n)).isoformat()) for m in SPECS
                for n in range((THROUGH - START).days + 1)}
    supplied = set()
    # Validate every key BEFORE parsing any observation/paid-band value.
    for row in payload["days"]:
        if not isinstance(row, dict):
            raise Refused("invalid_day")
        try:
            day = date.fromisoformat(row["target_date"])
            key = (row["market_id"], day.isoformat())
        except (KeyError, TypeError, ValueError):
            raise Refused("invalid_market_date_key") from None
        if not phase2 and not synthetic and day > DEV_CUTOFF:
            raise Refused("phase1_post_09_29_read_forbidden")
        if key not in expected or key in supplied:
            raise Refused("out_of_scope_or_duplicate_market_date")
        supplied.add(key)
    station_config = load_station_config()  # tracked station config only, never runtime state
    all_results, refusals = [], []
    for row in sorted(payload["days"], key=lambda r: (r["target_date"], r["market_id"])):
        try:
            all_results.append(compare_day(row, station_config))
        except Refused as error:
            refusals.append({"market_id": row["market_id"], "target_date": row["target_date"], "reason": str(error)})
    dates = sorted({r["target_date"] for r in all_results})
    differences = [r for r in all_results if r["bands_differ"]]
    return {"verdict": "DESCRIBE", "claim_type": "SYNTHETIC" if synthetic else "MEASURED",
            "scope": "dated_link_start_through_target_local_day_end_only",
            "expected_market_days": len(expected), "supplied_market_days": len(supplied),
            "missing_keys": [dict(market_id=m, target_date=d) for m, d in sorted(expected - supplied)],
            "comparable_market_days": len(all_results), "effective_dates": dates,
            "differing_market_days": len(differences), "differences": differences,
            "refusals": refusals, "comparable_days": all_results,
            "interval": None, "interval_reason": "exact finite enumeration; no population inference or edge claim"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phase2-owner-extract", action="store_true",
                        help="master's separately logged Phase 2 launch only; forbidden during Phase 1")
    args = parser.parse_args(argv)
    if not args.phase2_owner_extract:
        parser.error("Phase 1: refusing before opening the extract; master launches Phase 2 separately")
    if args.out.exists():
        parser.error("output already exists; choose a new path")
    if args.extract.stat().st_size > 32 * 1024 * 1024:
        parser.error("extract exceeds 32 MiB minimal-input cap")
    raw = args.extract.read_bytes()
    try:
        result = analyze(json.loads(raw), phase2=True)
    except (Refused, ValueError, TypeError) as error:
        parser.error(f"extract refused ({type(error).__name__}); no result written")
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({key: result[key] for key in ("verdict", "comparable_market_days", "differing_market_days")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
