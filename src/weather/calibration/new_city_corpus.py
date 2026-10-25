"""METAR-labelled training-corpus builder for candidate new cities (M1).

Owner decision 2026-10-23: new METAR-settled cities are labelled from free IEM
METAR. This module joins three things for a candidate market from
``config/candidate_markets.json`` (``weather.market.candidate_markets``):

1. **Label** -- the venue rule of ``weather.backtesting.venue_rule_labels``
   (lane A1): the local-date maximum of routine METAR temperatures (SPECI
   excluded, T-group tenths, accepted corrections applied), keyed on the
   observation instant in the market's IANA zone, half-up to a whole native
   degree. A day is ``complete`` only when no gap between consecutive reports
   (local midnight to local midnight, DST-aware) exceeds the label source's
   ``complete_day_max_gap_minutes``; other days are never training labels.
2. **Observed-so-far features at each cutoff** -- the METAR print-cutoff
   equivalent of the WU rule: only reports whose observation instant is at or
   before the local cutoff instant are admitted, and the effective cutoff is
   the latest cutoff hour the newest admitted report has reached (a report up
   to ``alias_window_minutes`` before the hour counts for that hour), exactly as
   ``ModelUtilsMixin.aliased_settlement_print_minute`` and
   ``effective_intraday_cutoff_hour`` do for WU prints.
3. **Point-in-time forecast** -- rows of a published PIT forecast corpus
   (``weather.sources.forecast_training_corpus``) for the same market, target
   date and cutoff. A row whose issue or availability time is after its
   feature cutoff, or whose cutoff instant disagrees with this module's, is
   refused.

It never fetches. Inputs are local IEM CSV files and a verified PIT corpus
manifest; the output is a content-addressed directory. Nothing here is read by
serving, capture or release code.

CLI:
  python -m weather.calibration.new_city_corpus labels --market london --routine-csv <f> [...] --special-csv <f> [...] --last-date 2026-09-29 --out <labels.jsonl>
  python -m weather.calibration.new_city_corpus build --markets london,paris --metar-root <venue_rule_labels METAR root> --pit-corpus-manifest <manifest.json> --last-date 2025-12-31 --publish-root <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from weather.backtesting import venue_rule_labels as venue
from weather.market.candidate_markets import load_candidate_registry
from weather.schema_families import schema_version
from weather.sources.metar_history import (
    IEM_REPORT_TYPE_ROUTINE,
    IEM_REPORT_TYPE_SPECIAL,
    REPORT_TYPE_ROUTINE,
    REPORT_TYPE_SPECIAL,
    dedupe_records,
    normalize_csv,
)
from weather.units import round_half_up, to_float


LABEL_SCHEMA_VERSION = schema_version("new_city_metar_label")
ROW_SCHEMA_VERSION = schema_version("new_city_training_row")
MANIFEST_SCHEMA_VERSION = schema_version("new_city_training_corpus_manifest")


class CorpusBuildError(ValueError):
    """An input would break the label, cutoff or point-in-time contract."""


def _parse_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise CorpusBuildError(f"timestamp has no offset: {value!r}")
    return dt.astimezone(timezone.utc)


def local_day_bounds_utc(target_date, tz):
    """UTC instants of local midnight at the start and end of ``target_date``."""
    day = _parse_date(target_date)
    start = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    return start, end


def cutoff_instant_utc(target_date, cutoff_hour, tz):
    day = _parse_date(target_date)
    return datetime.combine(day, time(int(cutoff_hour), 0), tzinfo=tz).astimezone(timezone.utc)


def read_iem_records(paths, spec, *, last_date):
    """Normalized, deduplicated METAR records from IEM ASOS CSV files.

    Rows whose local date is after ``last_date`` are dropped at read time and
    never reach a label, a feature or the input span.
    """
    last = _parse_date(last_date).isoformat()
    records = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        records.extend(row for row in normalize_csv(text, spec) if row["local_date"] <= last)
    return dedupe_records(records)


def venue_routine_records(routine_paths, special_paths, candidate, *, last_date):
    """Venue-rule label records: routine METARs only, through ``venue_rule_labels``.

    The venue rule (lane A1, ``weather.backtesting.venue_rule_labels``) takes the
    highest routine METAR, SPECI excluded, tenths from the T-group, and an
    accepted correction replaces the original. IEM raw text has no METAR/SPECI
    prefix, so the request's ``report_type`` declares the type. For a station
    whose half-hourly routine reports IEM files as ``report_type=4`` (measured:
    every EGLC type-4 report is at :20, every LFPB one at :30), the candidate
    row names that minute in ``iem_special_schedule_minute``; a type-4 report
    at exactly that minute, without a SPECI prefix, is the scheduled routine
    report and counts. Any other type-4 report stays special. Returns
    ``(records, counts)`` with ``temp_native`` set to the venue value.
    """
    spec = candidate.spec
    last = _parse_date(last_date).isoformat()
    minute = candidate.iem_special_schedule_minute
    reports = []
    counts = defaultdict(int)
    for paths, declared in ((routine_paths, IEM_REPORT_TYPE_ROUTINE), (special_paths, IEM_REPORT_TYPE_SPECIAL)):
        for path in paths:
            text = Path(path).read_text(encoding="utf-8")
            for report in venue.reports_from_csv(text, spec, spec.icao, declared_report_type=declared):
                if report["local_date"] > last:
                    continue
                if (
                    declared == IEM_REPORT_TYPE_SPECIAL
                    and report["report_type"] == REPORT_TYPE_SPECIAL
                    and minute is not None
                    and report["valid_time_utc"].minute == minute
                    and not str(report["raw"]).lstrip().upper().startswith("SPECI")
                ):
                    report = {**report, "report_type": REPORT_TYPE_ROUTINE}
                    counts["scheduled_type4_routine"] += 1
                counts[report["report_type"]] += 1
                reports.append(report)
    routine = sorted(
        (report for report in reports if report["report_type"] == REPORT_TYPE_ROUTINE),
        key=lambda item: item["valid_time_utc"],
    )
    selected, rejected = venue.select_reports(routine)
    counts["rejected_late_corrections"] += rejected
    records = []
    for report in selected:
        if report["temperature_c"] is None:
            counts["no_temperature"] += 1
            continue
        counts[f"basis_{report['value_basis']}"] += 1
        records.append({**report["record"], "temp_native": venue.native_value(report["temperature_c"], spec.display_unit)})
    return records, dict(counts)


def station_csvs(metar_root, icao):
    """``(routine, special)`` CSV paths in the ``venue_rule_labels`` METAR layout."""
    base = Path(metar_root) / icao.lower()
    return sorted((base / "routine").glob("*.csv")), sorted((base / "special").glob("*.csv"))


def records_by_local_date(records):
    grouped = defaultdict(list)
    for row in records:
        if row.get("local_date") and to_float(row.get("temp_native")) is not None:
            grouped[row["local_date"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: item["valid_time_utc"])
    return dict(grouped)


def _max_gap_minutes(rows, target_date, tz):
    start, end = local_day_bounds_utc(target_date, tz)
    instants = [start] + [_utc(row["valid_time_utc"]) for row in rows] + [end]
    gaps = [(later - earlier).total_seconds() / 60.0 for earlier, later in zip(instants, instants[1:])]
    return max(gaps)


def daily_label(rows, target_date, candidate):
    """Label for one local date from that date's METAR rows (may be incomplete)."""
    spec = candidate.spec
    temps = [to_float(row.get("temp_native")) for row in rows]
    temps = [value for value in temps if value is not None]
    start, end = local_day_bounds_utc(target_date, spec.tz)
    if not temps:
        max_gap = (end - start).total_seconds() / 60.0
        high = None
    else:
        max_gap = _max_gap_minutes(rows, target_date, spec.tz)
        high = max(temps)
    threshold = candidate.label_source.complete_day_max_gap_minutes
    return {
        "schema_version": LABEL_SCHEMA_VERSION,
        "market_id": spec.id,
        "station": spec.icao,
        "label_source": candidate.label_source.name,
        "temperature_unit": spec.display_unit,
        "target_date": _parse_date(target_date).isoformat(),
        "local_day_hours": round((end - start).total_seconds() / 3600.0, 2),
        "row_count": len(temps),
        "max_gap_minutes": round(max_gap, 1),
        "label_complete": bool(temps) and max_gap <= threshold,
        "observed_high_native": high,
        "label_native": round_half_up(high) if high is not None else None,
        "max_times_local": "|".join(
            row["local_time"] for row in rows if high is not None and to_float(row.get("temp_native")) == high
        ),
    }


INPUT_SPAN_SLACK = timedelta(minutes=60)


def daily_labels(records, candidate, *, last_date):
    """Labels for every local date with rows, ignoring dates after ``last_date``.

    A date whose local day is not inside the span the input files cover (first
    to last report, with an hour of slack for the report cadence) is a fetch
    edge, not an observed day, and is never ``label_complete``.
    """
    last = _parse_date(last_date)
    grouped = records_by_local_date(records)
    instants = [_utc(row["valid_time_utc"]) for rows in grouped.values() for row in rows]
    labels = {}
    for local_date, rows in sorted(grouped.items()):
        if _parse_date(local_date) > last:
            continue
        label = daily_label(rows, local_date, candidate)
        start, end = local_day_bounds_utc(local_date, candidate.spec.tz)
        inside = start >= min(instants) - INPUT_SPAN_SLACK and end <= max(instants) + INPUT_SPAN_SLACK
        label["inside_input_span"] = inside
        label["label_complete"] = label["label_complete"] and inside
        labels[local_date] = label
    return labels


def aliased_minute(minute, wall_cutoff_hour, alias_window):
    """Same rule as ``ModelUtilsMixin.aliased_settlement_print_minute``."""
    next_hour = ((int(minute) // 60) + 1) * 60
    if next_hour <= int(wall_cutoff_hour) * 60 and 0 < (next_hour - int(minute)) <= int(alias_window):
        return next_hour
    return int(minute)


def observed_at_cutoff(rows, target_date, cutoff_hour, candidate):
    """Observed-so-far METAR features admitted at one local cutoff."""
    spec = candidate.spec
    rule = candidate.print_cutoff
    cutoff_hour = int(cutoff_hour)
    if cutoff_hour not in rule.cutoff_hours_local:
        raise CorpusBuildError(f"cutoff hour {cutoff_hour} is not in the print-cutoff rule")
    as_of = cutoff_instant_utc(target_date, cutoff_hour, spec.tz)
    admitted = [
        row for row in rows
        if row.get("local_date") == _parse_date(target_date).isoformat()
        and _utc(row["valid_time_utc"]) <= as_of
        and to_float(row.get("temp_native")) is not None
    ]
    first_cutoff = rule.cutoff_hours_local[0]
    if not admitted:
        return {
            "feature_as_of_utc": as_of.isoformat(),
            "effective_cutoff_hour": first_cutoff,
            "obs_rows": 0,
            "obs_max_so_far_native": None,
            "obs_latest_native": None,
            "obs_latest_valid_time_utc": None,
        }
    latest = admitted[-1]
    local_latest = _utc(latest["valid_time_utc"]).astimezone(spec.tz)
    minute = aliased_minute(local_latest.hour * 60 + local_latest.minute, cutoff_hour, rule.alias_window_minutes)
    eligible = [hour for hour in rule.cutoff_hours_local if hour <= cutoff_hour and hour * 60 <= minute]
    return {
        "feature_as_of_utc": as_of.isoformat(),
        "effective_cutoff_hour": eligible[-1] if eligible else first_cutoff,
        "obs_rows": len(admitted),
        "obs_max_so_far_native": max(to_float(row["temp_native"]) for row in admitted),
        "obs_latest_native": to_float(latest["temp_native"]),
        "obs_latest_valid_time_utc": latest["valid_time_utc"],
    }


def _read_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_pit_forecast_daily(manifest_path, market_ids, *, require_all=True):
    """Daily-high rows of a published PIT corpus for ``market_ids``, hash-checked."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = (manifest.get("files") or {}).get("forecast_daily.jsonl")
    if not entry:
        raise CorpusBuildError("PIT corpus manifest lists no forecast_daily.jsonl")
    daily_path = manifest_path.parent / "forecast_daily.jsonl"
    digest = hashlib.sha256(daily_path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise CorpusBuildError("PIT forecast_daily.jsonl hash does not match its manifest")
    wanted = set(market_ids)
    missing = sorted(wanted - set(manifest.get("market_ids") or []))
    if missing and require_all:
        raise CorpusBuildError(f"PIT corpus has no rows for markets: {', '.join(missing)}")
    rows = [row for row in _read_jsonl(daily_path) if row.get("market_id") in wanted]
    return manifest, digest, rows


def routine_floor_at_cutoff(routine_rows, target_date, cutoff_hour, candidate):
    """Highest label-rule (routine, venue-value) report at or before the cutoff, and its band floor.

    The label is the maximum of the same reports over the whole local day, so the
    label can never be below ``round_half_up`` of this value: a hard floor.
    """
    as_of = cutoff_instant_utc(target_date, cutoff_hour, candidate.spec.tz)
    day = _parse_date(target_date).isoformat()
    values = [
        to_float(row["temp_native"]) for row in routine_rows
        if row.get("local_date") == day and _utc(row["valid_time_utc"]) <= as_of
        and to_float(row.get("temp_native")) is not None
    ]
    high = max(values) if values else None
    return {
        "obs_routine_max_so_far_native": high,
        "floor_native": round_half_up(high) if high is not None else None,
    }


def join_rows(forecast_rows, labels_by_market, records_by_market, candidates, *, last_date, routine_by_market=None):
    """Join PIT forecast rows to complete METAR labels and cutoff features."""
    routine_by_market = routine_by_market or {}
    last = _parse_date(last_date)
    out = []
    rejected = defaultdict(int)
    for row in sorted(
        forecast_rows,
        key=lambda item: (item["market_id"], item["target_date"], int(item["cutoff_hour_local"])),
    ):
        market_id = row["market_id"]
        candidate = candidates[market_id]
        spec = candidate.spec
        target_date = row["target_date"]
        if _parse_date(target_date) > last:
            rejected["after_last_date"] += 1
            continue
        if row.get("temperature_unit") != spec.display_unit:
            raise CorpusBuildError(f"{market_id} {target_date}: forecast unit is not the native unit")
        cutoff_hour = int(row["cutoff_hour_local"])
        as_of = cutoff_instant_utc(target_date, cutoff_hour, spec.tz)
        if _utc(row["feature_as_of_utc"]) != as_of:
            raise CorpusBuildError(f"{market_id} {target_date} h{cutoff_hour}: PIT cutoff instant disagrees")
        for field in ("issue_time_utc", "available_at_utc"):
            if _utc(row[field]) > as_of:
                raise CorpusBuildError(f"{market_id} {target_date} h{cutoff_hour}: {field} after the cutoff")
        label = labels_by_market.get(market_id, {}).get(target_date)
        if label is None:
            rejected["no_label"] += 1
            continue
        if not label["label_complete"]:
            rejected["label_incomplete"] += 1
            continue
        observed = observed_at_cutoff(
            records_by_market.get(market_id, {}).get(target_date, []),
            target_date,
            cutoff_hour,
            candidate,
        )
        floor = routine_floor_at_cutoff(
            routine_by_market.get(market_id, {}).get(target_date, []), target_date, cutoff_hour, candidate,
        )
        if floor["floor_native"] is not None and floor["floor_native"] > label["label_native"]:
            raise CorpusBuildError(f"{market_id} {target_date} h{cutoff_hour}: floor above the label")
        out.append({
            "schema_version": ROW_SCHEMA_VERSION,
            "market_id": market_id,
            "station": spec.icao,
            "temperature_unit": spec.display_unit,
            "target_date": target_date,
            "cutoff_hour_local": cutoff_hour,
            **observed,
            **floor,
            "forecast_high_native": to_float(row.get("forecast_high_native")),
            "forecast_source_model": row.get("source_model"),
            "forecast_lead_days": row.get("lead_days"),
            "forecast_issue_time_utc": row.get("issue_time_utc"),
            "forecast_available_at_utc": row.get("available_at_utc"),
            "forecast_derived_row_sha256": row.get("derived_row_sha256"),
            "label_native": label["label_native"],
            "label_source": label["label_source"],
        })
    return out, dict(rejected)


def _jsonl_bytes(rows):
    return "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")


def publish_corpus(publish_root, files, manifest_body):
    """Write ``files`` and a manifest into ``<publish_root>/corpora/<id>`` atomically."""
    publish_root = Path(publish_root)
    file_hashes = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}
    identity = dict(manifest_body)
    identity["files"] = {name: {"sha256": digest, "byte_count": len(files[name])} for name, digest in file_hashes.items()}
    corpus_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    manifest = {**identity, "corpus_id": corpus_id}
    final = publish_root / "corpora" / corpus_id
    if final.exists():
        raise CorpusBuildError(f"corpus {corpus_id} already exists; corpora are never overwritten")
    final.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    try:
        for name, body in files.items():
            (temp / name).write_bytes(body)
        (temp / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, final)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return final, manifest


def build(*, market_ids, metar_root, pit_corpus_manifest, last_date, publish_root, registry_path=None):
    registry = load_candidate_registry(registry_path)
    unknown = sorted(set(market_ids) - set(registry))
    if unknown:
        raise CorpusBuildError(f"not candidate markets: {', '.join(unknown)}")
    candidates = {market_id: registry[market_id] for market_id in market_ids}
    labels_by_market = {}
    records_by_market = {}
    metar_inputs = {}
    label_counts = {}
    routine_by_market = {}
    for market_id, candidate in candidates.items():
        routine, special = station_csvs(metar_root, candidate.spec.icao)
        if not routine:
            raise CorpusBuildError(f"no routine IEM CSV for {candidate.spec.icao} under {metar_root}")
        metar_inputs[market_id] = [
            {"name": f"{path.parent.name}/{path.name}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in routine + special
        ]
        label_records, label_counts[market_id] = venue_routine_records(
            routine, special, candidate, last_date=last_date,
        )
        labels_by_market[market_id] = daily_labels(label_records, candidate, last_date=last_date)
        routine_by_market[market_id] = records_by_local_date(label_records)
        # Observed-so-far features use every report a live station feed carries.
        records_by_market[market_id] = records_by_local_date(
            read_iem_records(routine + special, candidate.spec, last_date=last_date)
        )
    manifests = [pit_corpus_manifest] if isinstance(pit_corpus_manifest, (str, Path)) else list(pit_corpus_manifest)
    pit_inputs = []
    forecast_rows = []
    seen = set()
    for manifest_path in manifests:
        pit_manifest, pit_digest, rows_for = load_pit_forecast_daily(manifest_path, market_ids, require_all=False)
        pit_inputs.append({"corpus_id": pit_manifest.get("corpus_id"), "forecast_daily_sha256": pit_digest})
        for row in rows_for:
            key = (row["market_id"], row["target_date"], int(row["cutoff_hour_local"]))
            if key in seen:
                raise CorpusBuildError(f"PIT corpora overlap at {key}")
            seen.add(key)
            forecast_rows.append(row)
    covered = {row["market_id"] for row in forecast_rows}
    if set(market_ids) - covered:
        raise CorpusBuildError(f"PIT corpora have no rows for markets: {', '.join(sorted(set(market_ids) - covered))}")
    rows, rejected = join_rows(
        forecast_rows, labels_by_market, records_by_market, candidates,
        last_date=last_date, routine_by_market=routine_by_market,
    )
    if not rows:
        raise CorpusBuildError("join produced no rows; nothing is published")
    labels = [label for market in sorted(labels_by_market) for _, label in sorted(labels_by_market[market].items())]
    files = {"rows.jsonl": _jsonl_bytes(rows), "labels.jsonl": _jsonl_bytes(labels)}
    body = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "corpus_role": "training_only",
        "market_ids": sorted(market_ids),
        "last_date": _parse_date(last_date).isoformat(),
        "label_sources": {market_id: candidates[market_id].label_source.name for market_id in sorted(candidates)},
        "label_rule": venue.VENUE_RULE_VERSION,
        "label_report_counts": label_counts,
        "metar_inputs": metar_inputs,
        "pit_corpora": pit_inputs,
        "row_count": len(rows),
        "label_count": len(labels),
        "label_complete_count": sum(1 for label in labels if label["label_complete"]),
        "rejected": rejected,
    }
    return publish_corpus(publish_root, files, body)


def _labels_command(args):
    registry = load_candidate_registry(args.registry or None)
    if args.market not in registry:
        raise CorpusBuildError(f"not a candidate market: {args.market!r}")
    candidate = registry[args.market]
    records, counts = venue_routine_records(
        args.routine_csv, args.special_csv or [], candidate, last_date=args.last_date,
    )
    labels = daily_labels(records, candidate, last_date=args.last_date)
    body = _jsonl_bytes(list(labels.values()))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_bytes(body)
    complete = sum(1 for label in labels.values() if label["label_complete"])
    print(json.dumps({"market": args.market, "dates": len(labels), "complete": complete, "reports": counts}))
    return 0


FIT_SCHEMA = "new_city_candidate_fit/3"  # research result, not a registry artifact
FIT_FEATURES = ("forecast_high_native", "obs_max_so_far_native", "obs_routine_max_so_far_native", "obs_latest_native")
FIT_MODELS = ("baseline", "ols", "hgb", "ols_hgb_resid")
FIT_BOOTSTRAP_DRAWS = 2000
FIT_SEED = 20261023
FIT_CV_FOLDS = 5
FIT_MIN_TRAIN_ROWS = 60
EVALUATION_LAST_DATE = date(2025, 12, 31)
FIT_BLOCKS = (
    ("07-09", 7, 9), ("10-12", 10, 12), ("07-12", 7, 12),
    ("13-16", 13, 16), ("17-20", 17, 20), ("all", 7, 20),
)
FIT_COMPARISONS = (
    ("ols", "baseline"), ("hgb", "baseline"), ("hgb", "ols"),
    ("ols_hgb_resid", "baseline"), ("ols_hgb_resid", "ols"),
)
HGB_PARAMS = {
    "loss": "squared_error", "learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 15,
    "min_samples_leaf": 40, "l2_regularization": 1.0, "early_stopping": False,
}
SD_FLOOR = 0.3


def _band_ladder(label, unit, width=None):
    """Interior band lower edges around ``label``: 1 C bands, or 2 F bands on even starts."""
    width = width or (2 if unit == "F" else 1)
    centre = int(label) - (int(label) % width)
    return [centre + width * k for k in range(-12, 13)], width


def _normal_cdf(x):
    import math

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def band_probabilities(mean, sd, edges, width, floor=None):
    """P(whole-degree label in [edge, edge + width)) for a normal on the half-up value.

    With ``floor`` (a whole native degree the label cannot be below) the normal is
    truncated at ``floor - 0.5`` and renormalised: no band below the floor gets mass,
    and the band holding the floor takes the cut-off tail.
    """
    sd = max(float(sd), SD_FLOOR)
    cut = None if floor is None else float(floor) - 0.5
    probs = []
    for edge in edges:
        lo, hi = edge - 0.5, edge + width - 0.5
        if cut is not None:
            if hi <= cut:
                probs.append(0.0)
                continue
            lo = max(lo, cut)
        probs.append(_normal_cdf((hi - mean) / sd) - _normal_cdf((lo - mean) / sd))
    if cut is not None:
        total = sum(probs)
        if total <= 1e-12:
            probs = [1.0 if edge <= floor < edge + width else 0.0 for edge in edges]
        else:
            tail = 1.0 - _normal_cdf((edges[-1] + width - 0.5 - mean) / sd)
            probs = [p / (total + tail) for p in probs]
    return probs


def _brier_log(probs, edges, width, label):
    import math

    truth = [1.0 if edge <= label < edge + width else 0.0 for edge in edges]
    brier = sum((p - y) ** 2 for p, y in zip(probs, truth))
    hit = sum(p for p, y in zip(probs, truth) if y) / max(sum(probs), 1e-12)
    return brier, math.log(max(hit, 1e-4))


def _x_of(row):
    fc = row["forecast_high_native"]
    out = []
    for field in FIT_FEATURES:
        value = row.get(field)
        out.append(fc if value is None else value)
    return out


def _ols(xs, ys):
    import numpy as np

    x = np.column_stack([np.ones(len(xs)), np.asarray(xs, dtype=float)])
    y = np.asarray(ys, dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    return beta, float(resid.std(ddof=x.shape[1])) if len(y) > x.shape[1] else float("nan")


def _hgb_fit(xs, ys, *, monotone=True):
    from sklearn.ensemble import HistGradientBoostingRegressor

    model = HistGradientBoostingRegressor(
        **HGB_PARAMS, monotonic_cst=[1 if monotone else 0] * len(FIT_FEATURES), random_state=FIT_SEED,
    )
    return model.fit(xs, ys)


class _OlsPlusResidualHgb:
    """OLS mean plus an unconstrained HGB fitted on the OLS training residuals."""

    def __init__(self, xs, ys):
        import numpy as np

        xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
        self.beta, _ = _ols(xs, ys)
        self.resid_model = _hgb_fit(xs, ys - self._ols_mean(xs), monotone=False)

    def _ols_mean(self, xs):
        return self.beta[0] + xs @ self.beta[1:]

    def predict(self, xs):
        import numpy as np

        xs = np.asarray(xs, dtype=float)
        return self._ols_mean(xs) + self.resid_model.predict(xs)


def _date_folds(dates):
    import numpy as np

    unique = sorted(set(dates))
    fold_of = {d: i % FIT_CV_FOLDS for i, d in enumerate(unique)}
    return np.asarray([fold_of[d] for d in dates])


def _ols_hgb_resid_with_cv_sd(xs, ys, dates):
    """OLS + residual HGB on all training rows; sd from out-of-fold residuals by date.

    Each fold refits both stages on its training dates, so the sd is honest for the
    two-stage model.
    """
    import numpy as np

    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    folds = _date_folds(dates)
    resid = np.empty(len(ys))
    for k in range(FIT_CV_FOLDS):
        held = folds == k
        resid[held] = ys[held] - _OlsPlusResidualHgb(xs[~held], ys[~held]).predict(xs[held])
    return _OlsPlusResidualHgb(xs, ys), float(resid.std(ddof=1))


def _hgb_with_cv_sd(xs, ys, dates):
    """HGB fitted on all training rows; sd from out-of-fold residuals, folds by date."""
    import numpy as np

    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    folds = _date_folds(dates)
    resid = np.empty(len(ys))
    for k in range(FIT_CV_FOLDS):
        held = folds == k
        resid[held] = ys[held] - _hgb_fit(xs[~held], ys[~held]).predict(xs[held])
    return _hgb_fit(xs, ys), float(resid.std(ddof=1))


def fit_and_evaluate(rows, *, train_through, test_from, test_to):
    """Score baseline, OLS and monotone HGB per market x cutoff on held-out dates.

    * ``baseline``: the lead-1 PIT forecast high plus a per market x cutoff bias,
      with the training residual sd; no observations and no floor.
    * ``ols``: least squares of the label on ``FIT_FEATURES``; training residual sd.
    * ``hgb``: histogram gradient boosting, monotone increasing in every feature,
      squared error; sd from 5-fold (by date) out-of-fold residuals.
    * ``ols_hgb_resid``: the OLS mean plus an unconstrained HGB fitted on the OLS
      training residuals; sd from 5-fold (by date) out-of-fold residuals of the
      two-stage model, each fold refitting both stages.

    OLS, HGB and OLS + residual HGB carry the hard floor, applied after the residual is added: the label is never below the band of the
    highest label-rule report observed by the cutoff. All three give a
    discretised normal over the venue band ladder (1 C bands; 2 F bands on even
    starts). Deltas carry a date-clustered bootstrap per market and block.
    """
    import numpy as np

    train_through, test_from, test_to = _parse_date(train_through), _parse_date(test_from), _parse_date(test_to)
    if test_to > EVALUATION_LAST_DATE or train_through > EVALUATION_LAST_DATE:
        raise CorpusBuildError("training or evaluation dates after 2025-12-31 are refused")
    if not train_through < test_from <= test_to:
        raise CorpusBuildError("train_through must precede test_from")
    groups = defaultdict(list)
    for row in rows:
        if any(row.get(field) is None for field in ("forecast_high_native", "label_native")):
            continue
        groups[(row["market_id"], int(row["cutoff_hour_local"]))].append(row)
    scored = []
    models = {}
    floor_violations = defaultdict(int)
    for (market_id, hour), items in sorted(groups.items()):
        train = [r for r in items if _parse_date(r["target_date"]) <= train_through]
        test = [r for r in items if test_from <= _parse_date(r["target_date"]) <= test_to]
        if len(train) < FIT_MIN_TRAIN_ROWS or not test:
            continue
        unit = items[0]["temperature_unit"]
        y_train = [r["label_native"] for r in train]
        bias = float(np.mean([r["label_native"] - r["forecast_high_native"] for r in train]))
        base_sd = float(np.std([r["label_native"] - r["forecast_high_native"] - bias for r in train], ddof=1))
        beta, ols_sd = _ols([_x_of(r) for r in train], y_train)
        hgb, hgb_sd = _hgb_with_cv_sd([_x_of(r) for r in train], y_train, [r["target_date"] for r in train])
        x_test = np.asarray([_x_of(r) for r in test], dtype=float)
        hgb_test = hgb.predict(x_test)
        res_model, res_sd = _ols_hgb_resid_with_cv_sd([_x_of(r) for r in train], y_train, [r["target_date"] for r in train])
        res_test = res_model.predict(x_test)
        models[f"{market_id}|{hour}"] = {
            "n_train": len(train), "bias": round(bias, 4), "baseline_sd": round(base_sd, 4),
            "ols_beta": [round(float(b), 4) for b in beta], "ols_sd": round(ols_sd, 4),
            "hgb_cv_sd": round(hgb_sd, 4), "ols_hgb_resid_cv_sd": round(res_sd, 4),
        }
        for r, hgb_mean, res_mean in zip(test, hgb_test, res_test):
            edges, width = _band_ladder(r["label_native"], unit)
            floor = r.get("floor_native")
            if floor is not None and floor > r["label_native"]:
                floor_violations[market_id] += 1
            means = {
                "baseline": (r["forecast_high_native"] + bias, base_sd, None),
                "ols": (float(beta[0] + np.dot(beta[1:], _x_of(r))), ols_sd, floor),
                "hgb": (float(hgb_mean), hgb_sd, floor),
                "ols_hgb_resid": (float(res_mean), res_sd, floor),
            }
            item = {"market_id": market_id, "cutoff_hour_local": hour, "target_date": r["target_date"]}
            for name, (mean, sd, fl) in means.items():
                brier, log = _brier_log(band_probabilities(mean, sd, edges, width, floor=fl), edges, width, r["label_native"])
                item[f"{name}_brier"], item[f"{name}_log"] = brier, log
            scored.append(item)
    if not scored:
        raise CorpusBuildError("no market x cutoff had enough training rows and held-out rows")

    def summary(items):
        dates = sorted({item["target_date"] for item in items})
        index = {d: i for i, d in enumerate(dates)}
        keys = [f"{m}_{s}" for m in FIT_MODELS for s in ("brier", "log")]
        by_date = np.zeros((len(dates), len(keys)))
        counts = np.zeros(len(dates))
        for item in items:
            i = index[item["target_date"]]
            by_date[i] += [item[k] for k in keys]
            counts[i] += 1
        by_date /= counts[:, None]
        col = {k: j for j, k in enumerate(keys)}
        rng = np.random.default_rng(FIT_SEED)
        draws = rng.integers(0, len(dates), size=(FIT_BOOTSTRAP_DRAWS, len(dates)))
        out = {"n_dates": len(dates), "n_rows": len(items)}
        for k in keys:
            out[k] = round(float(by_date[:, col[k]].mean()), 5)
        for a, b in FIT_COMPARISONS:
            for score in ("brier", "log"):
                diff = by_date[:, col[f"{a}_{score}"]] - by_date[:, col[f"{b}_{score}"]]
                boot = diff[draws].mean(axis=1)
                out[f"{a}_minus_{b}_{score}"] = round(float(diff.mean()), 5)
                out[f"{a}_minus_{b}_{score}_ci95"] = [round(float(v), 5) for v in np.percentile(boot, [2.5, 97.5])]
        return out

    results = {}
    for market_id in sorted({item["market_id"] for item in scored}):
        for name, lo, hi in FIT_BLOCKS:
            items = [i for i in scored if i["market_id"] == market_id and lo <= i["cutoff_hour_local"] <= hi]
            if items:
                results[f"{market_id}|{name}"] = summary(items)
    return {
        "schema": FIT_SCHEMA,
        "train_through": train_through.isoformat(),
        "test_from": test_from.isoformat(),
        "test_to": test_to.isoformat(),
        "features": list(FIT_FEATURES),
        "models": list(FIT_MODELS),
        "hgb_params": HGB_PARAMS,
        "hard_floor": "ols, hgb and ols_hgb_resid (after adding the residual): no mass below round_half_up(highest label-rule report by the cutoff)",
        "headline_blocks": ["07-09", "10-12", "07-12"],
        "floor_above_label_rows": dict(floor_violations),
        "bootstrap": {"draws": FIT_BOOTSTRAP_DRAWS, "seed": FIT_SEED, "cluster": "target_date, per market and block"},
        "benchmark": "weather-only baseline (bias-corrected PIT forecast); no market prices",
        "fitted": models,
        "results": results,
    }


def _fit_command(args):
    manifest_path = Path(args.corpus_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows_path = manifest_path.parent / "rows.jsonl"
    if hashlib.sha256(rows_path.read_bytes()).hexdigest() != manifest["files"]["rows.jsonl"]["sha256"]:
        raise CorpusBuildError("corpus rows.jsonl hash does not match its manifest")
    wanted = {item.strip() for item in args.markets.split(",") if item.strip()} if args.markets else None
    rows = [row for row in _read_jsonl(rows_path) if wanted is None or row["market_id"] in wanted]
    result = fit_and_evaluate(rows, train_through=args.train_through, test_from=args.test_from, test_to=args.test_to)
    result["corpus_id"] = manifest["corpus_id"]
    body = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    out = Path(args.out_dir) / f"{digest}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_bytes(body)
    print(json.dumps({"result": str(out), "results": result["results"]}, indent=1))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Build METAR-labelled training rows for candidate cities.")
    sub = parser.add_subparsers(dest="command", required=True)
    labels = sub.add_parser("labels", help="Write daily METAR labels for one candidate market.")
    labels.add_argument("--market", required=True)
    labels.add_argument("--routine-csv", nargs="+", required=True)
    labels.add_argument("--special-csv", nargs="*", default=[])
    labels.add_argument("--last-date", required=True)
    labels.add_argument("--out", default="")
    labels.add_argument("--registry", default="")
    corpus = sub.add_parser("build", help="Join a PIT forecast corpus to METAR labels and publish.")
    corpus.add_argument("--markets", required=True)
    corpus.add_argument("--metar-root", required=True)
    corpus.add_argument("--pit-corpus-manifest", nargs="+", required=True)
    corpus.add_argument("--last-date", required=True)
    corpus.add_argument("--publish-root", required=True)
    corpus.add_argument("--registry", default="")
    fit = sub.add_parser("fit", help="Fit the first per-market candidate and score held-out dates.")
    fit.add_argument("--corpus-manifest", required=True)
    fit.add_argument("--markets", default="")
    fit.add_argument("--train-through", required=True)
    fit.add_argument("--test-from", required=True)
    fit.add_argument("--test-to", required=True)
    fit.add_argument("--out-dir", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "labels":
        return _labels_command(args)
    if args.command == "fit":
        return _fit_command(args)
    final, manifest = build(
        market_ids=[item.strip() for item in args.markets.split(",") if item.strip()],
        metar_root=args.metar_root,
        pit_corpus_manifest=args.pit_corpus_manifest,
        last_date=args.last_date,
        publish_root=args.publish_root,
        registry_path=args.registry or None,
    )
    print(json.dumps({"corpus": str(final), "rows": manifest["row_count"], "rejected": manifest["rejected"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
