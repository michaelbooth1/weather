"""Frozen settlement labels and per-market resolution specs.

The settlement ledger is the durable supervised-label source for market-day
evaluation. Folder-local ``settlement.json`` files are convenient evidence
copies; the per-market JSONL ledgers under ``data/settlements`` are the source
of truth that scoring tools should consult first.
"""
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path

import pandas as pd
import requests

from weather.collection.collection_health import coverage_summary, local_window, parse_times
from weather.market.market_config import date_from_event_slug, polymarket_url_for_slug
from weather.market.market_registry import all_specs, spec_for_slug
from weather.schema_registry import schema_version
from weather.units import round_half_up


LEDGER_SCHEMA_VERSION = schema_version("settlement_ledger")
RESOLUTION_SPEC_SCHEMA_VERSION = schema_version("resolution_spec")
DEFAULT_LEDGER_ROOT = data_path() / "settlements"
LEDGER_ROOT_ENV = "SETTLEMENT_LEDGER_ROOT"
DEFAULT_LABELS_CSV = data_path() / "backtest" / "market_day_labels.csv"
COMPLETE_DAY_MIN_ROWS = 18
GAMMA_EVENT_URL_TEMPLATE = "https://gamma-api.polymarket.com/events/slug/{slug}"

SNAPSHOT_HIGH_COLUMNS = (
    "wu_history_high_native",
    "wu_history_high",
    "wu_history_high_c",  # legacy name; values are native-unit in the platform era
)
DAILY_BUCKET_COLUMNS = ("max_temp_bucket_native", "max_temp_bucket", "max_temp_bucket_c")
DAILY_HIGH_COLUMNS = ("max_temp_native", "max_temp", "max_temp_c")
CORE_PROB_COLUMNS = ("model_probability", "market_yes")
MATERIAL_COVERAGE_WINDOW = "12:00-18:00 local"
MATERIAL_PEAK_WINDOW = "14:00-17:00 local"
MATERIAL_CAPTURE_RATIO_MIN = 0.80
MATERIAL_MAX_GAP_MINUTES = 60.0
MATERIAL_PEAK_MAX_GAP_MINUTES = 45.0
MATERIAL_COUNTABLE_COVERAGE_GRADES = {
    "strict_complete",
    "minor_gap_material",
    "manual_override",
}
PROMOTION_RECONCILIATION_STATUSES = {"match"}

LABEL_COLUMNS = [
    "schema_version",
    "event_slug",
    "market_id",
    "city",
    "target_date",
    "settlement_high",
    "settlement_bucket",
    "settlement_unit",
    "winning_band",
    "winning_band_kind",
    "winning_band_value",
    "winning_band_value_hi",
    "settlement_source",
    "quality_grade",
    "quality_reason",
    "snapshot_count",
    "band_count",
    "row_count",
    "coverage_clean",
    "capture_ratio",
    "max_gap_minutes",
    "coverage_reason",
    "material_coverage_grade",
    "material_coverage_reason",
    "material_coverage_window",
    "material_coverage_gap_count",
    "material_coverage_max_gap_minutes",
    "material_peak_gap_minutes",
    "material_coverage_decisive_gap_count",
    "material_coverage_gap_windows",
    "promotion_countable",
    "promotion_countable_reason",
    "resolution_source_type",
    "resolution_wu_history_id",
    "resolution_station",
    "resolution_timezone",
    "daily_max_window",
    "rounding",
    "daily_summary_path",
    "snapshot_tape_path",
    "ledger_path",
    "polymarket_url",
    "gamma_event_url",
    "reconciliation_status",
    "polymarket_winning_band",
    "note",
    "finalized_at_utc",
]


def safe_float(value):
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def first_number(row, columns):
    for column in columns:
        if column not in row:
            continue
        value = safe_float(row.get(column))
        if value is not None:
            return value
    return None


def missing_fraction(frame, columns):
    checks = []
    for column in columns:
        if column not in frame:
            checks.append(1.0)
            continue
        checks.append(float(frame[column].isna().mean()))
    return max(checks) if checks else 0.0


def quality_grade(
    snapshot_count,
    band_count,
    settlement_bucket,
    settlement_source,
    missing_core_fraction=0.0,
    collection_clean=True,
):
    if settlement_bucket is None:
        return "missing_settlement"
    if snapshot_count <= 0 or band_count <= 0:
        return "missing_tape"
    if snapshot_count < 6 or not collection_clean:
        return "partial"
    if "sparse" in str(settlement_source):
        return "partial"
    if str(settlement_source) == "override":
        return "manual_override"
    if missing_core_fraction > 0.20:
        return "stale_source"
    return "complete"


def quality_reason(grade, missing_core_fraction, coverage_reason=None):
    if grade == "missing_settlement":
        return "no settlement bucket available"
    if grade == "missing_tape":
        return "snapshot tape missing required rows or bands"
    if grade == "manual_override":
        return "manual settlement override"
    if grade == "partial":
        if coverage_reason and coverage_reason != "ok":
            return f"collection coverage incomplete: {coverage_reason}"
        return "too few snapshots or sparse settlement source"
    if grade == "stale_source":
        return f"core source missing fraction {missing_core_fraction:.1%}"
    return "complete enough for headline scoring"


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _overlaps(start, end, window_start, window_end):
    return start < window_end and end > window_start


def _gap_window_label(gap, target_date, tzinfo):
    after = gap.get("after")
    before = gap.get("before")
    if not isinstance(after, datetime) or not isinstance(before, datetime) or target_date is None:
        return "unknown"
    settlement_start, settlement_end = local_window(target_date, tzinfo)
    peak_start = datetime.combine(target_date, datetime.strptime("14:00", "%H:%M").time().replace(tzinfo=tzinfo))
    peak_end = datetime.combine(target_date, datetime.strptime("17:00", "%H:%M").time().replace(tzinfo=tzinfo))
    if _overlaps(after, before, peak_start, peak_end):
        return "peak_heating_window"
    if _overlaps(after, before, settlement_start, settlement_end):
        return "settlement_window"
    return "outside_settlement_window"


def material_coverage_gap_rows(coverage, target_date=None):
    coverage = coverage or {}
    first = coverage.get("first")
    tzinfo = first.tzinfo if isinstance(first, datetime) else None
    rows = []
    for gap in coverage.get("gaps") or []:
        window = _gap_window_label(gap, target_date, tzinfo)
        gap_minutes = safe_float(gap.get("gap_minutes")) or 0.0
        material = bool(
            gap_minutes > MATERIAL_MAX_GAP_MINUTES
            or (window == "peak_heating_window" and gap_minutes > MATERIAL_PEAK_MAX_GAP_MINUTES)
        )
        rows.append({
            "after": _iso(gap.get("after")),
            "before": _iso(gap.get("before")),
            "gap_minutes": gap_minutes,
            "window": window,
            "material": material,
        })
    return rows


def _compact_gap_windows(gaps):
    return "; ".join(
        f"{gap.get('window')}:{float(gap.get('gap_minutes') or 0):.0f}m"
        for gap in gaps or []
    )


def material_coverage_grade(
    snapshot_count,
    band_count,
    settlement_bucket,
    settlement_source,
    missing_core_fraction=0.0,
    coverage=None,
    target_date=None,
):
    coverage = coverage or {}
    gaps = material_coverage_gap_rows(coverage, target_date=target_date)
    capture_ratio = safe_float(coverage.get("capture_ratio"))
    max_gap = max((safe_float(gap.get("gap_minutes")) or 0.0 for gap in gaps), default=0.0)
    peak_gap = max(
        (
            safe_float(gap.get("gap_minutes")) or 0.0
            for gap in gaps
            if gap.get("window") == "peak_heating_window"
        ),
        default=0.0,
    )
    decisive_gaps = [gap for gap in gaps if gap.get("material")]

    if settlement_bucket is None:
        grade = "missing_settlement"
        reason = "no settlement bucket available"
    elif snapshot_count <= 0 or band_count <= 0:
        grade = "missing_tape"
        reason = "snapshot tape missing required rows or bands"
    elif str(settlement_source) == "override":
        grade = "manual_override"
        reason = "manual settlement override"
    elif snapshot_count < 6:
        grade = "insufficient_captures"
        reason = f"snapshot_count {snapshot_count} below material floor 6"
    elif "sparse" in str(settlement_source) or str(settlement_source) == "none":
        grade = "sparse_settlement_source"
        reason = f"settlement_source={settlement_source}"
    elif missing_core_fraction > 0.20:
        grade = "stale_source"
        reason = f"core source missing fraction {missing_core_fraction:.1%}"
    elif not coverage.get("covers_afternoon"):
        grade = "decisive_gap"
        reason = coverage.get("reason") or "afternoon window not fully covered"
    elif capture_ratio is None or capture_ratio < MATERIAL_CAPTURE_RATIO_MIN:
        grade = "low_capture_ratio"
        ratio = 0.0 if capture_ratio is None else capture_ratio
        reason = f"capture_ratio {ratio:.1%} below material threshold {MATERIAL_CAPTURE_RATIO_MIN:.0%}"
    elif decisive_gaps:
        grade = "decisive_gap"
        largest = max(safe_float(gap.get("gap_minutes")) or 0.0 for gap in decisive_gaps)
        reason = f"{len(decisive_gaps)} material gap(s), max {largest:.0f} min"
    elif coverage.get("clean"):
        grade = "strict_complete"
        reason = "zero-gap coverage across settlement window"
    elif gaps:
        grade = "minor_gap_material"
        reason = f"{len(gaps)} non-material gap(s), max {max_gap:.0f} min"
    else:
        grade = "strict_complete"
        reason = "material coverage complete"

    return {
        "grade": grade,
        "reason": reason,
        "promotion_coverage_countable": grade in MATERIAL_COUNTABLE_COVERAGE_GRADES,
        "window": f"{MATERIAL_COVERAGE_WINDOW}; peak={MATERIAL_PEAK_WINDOW}",
        "gap_count": len(gaps),
        "max_gap_minutes": max_gap,
        "peak_gap_minutes": peak_gap,
        "decisive_gap_count": len(decisive_gaps),
        "gap_windows": _compact_gap_windows(gaps),
        "gaps": gaps,
    }


def promotion_countability(material_coverage, reconciliation_status):
    material_coverage = material_coverage or {}
    grade = material_coverage.get("grade")
    if grade not in MATERIAL_COUNTABLE_COVERAGE_GRADES:
        return False, material_coverage.get("reason") or f"material_coverage_grade={grade}"
    if str(reconciliation_status) not in PROMOTION_RECONCILIATION_STATUSES:
        return False, f"settlement reconciliation status is {reconciliation_status or 'missing'}"
    return True, "settlement reconciled and material coverage countable"


def captured_times(frame):
    if "captured_at_local" not in frame:
        return []
    rows = frame
    if "snapshot_id" in frame:
        rows = frame.drop_duplicates("snapshot_id")
    return parse_times(rows["captured_at_local"].dropna().astype(str).tolist())


def daily_summary_path_for_spec(spec):
    return spec.data_root / "daily" / "daily_summary.csv"


def load_daily_summary(path):
    """Load a native-unit WU daily summary.

    The historical column names end in ``_c`` for compatibility, but for
    Fahrenheit markets the platform-era backfills store Fahrenheit values there.
    The ledger records the actual market unit explicitly.
    """
    index = {}
    path = Path(path)
    if not path.exists():
        return index
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date = row.get("local_date")
            if not local_date:
                continue
            bucket = first_number(row, DAILY_BUCKET_COLUMNS)
            if bucket is None:
                continue
            try:
                row_count = int(float(row.get("row_count") or 0))
            except (TypeError, ValueError):
                row_count = 0
            index[local_date] = {
                "bucket": int(bucket),
                "high": first_number(row, DAILY_HIGH_COLUMNS),
                "row_count": row_count,
                "max_temp_times": row.get("max_temp_times") or "",
                "path": str(path),
            }
    return index


def normalize_summary(summary):
    if summary is None:
        return None
    if isinstance(summary, dict):
        return summary
    if isinstance(summary, (tuple, list)) and len(summary) >= 2:
        return {"bucket": int(summary[0]), "high": None, "row_count": int(summary[1])}
    return None


def infer_event_slug_from_frame(frame):
    if "event_slug" not in frame:
        return None
    values = frame["event_slug"].dropna().astype(str)
    for value in values:
        if value:
            return value
    return None


def override_bucket(overrides, spec, target_date, event_slug):
    if not overrides or target_date is None:
        return None
    iso = target_date.isoformat()
    keys = [event_slug, f"{spec.id}:{iso}" if spec else None, iso]
    for key in keys:
        if key and key in overrides:
            return int(overrides[key])
    return None


def snapshot_settlement_high(frame):
    for column in SNAPSHOT_HIGH_COLUMNS:
        if column not in frame:
            continue
        high = safe_float(pd.to_numeric(frame[column], errors="coerce").max())
        if high is not None:
            return high, column
    return None, None


def settlement_from_sources(frame, target_date, daily_index, overrides=None, spec=None, event_slug=None):
    """Return a settlement evidence dict from override, daily summary, or tape."""
    event_slug = event_slug or infer_event_slug_from_frame(frame)
    spec = spec or spec_for_slug(event_slug)
    override = override_bucket(overrides or {}, spec, target_date, event_slug)
    snapshot_high, snapshot_column = snapshot_settlement_high(frame)
    snapshot_bucket = round_half_up(snapshot_high)
    iso = target_date.isoformat() if target_date else None
    summary = normalize_summary((daily_index or {}).get(iso))

    note_bits = []
    if summary is not None and snapshot_bucket is not None and summary["bucket"] != snapshot_bucket:
        note_bits.append(
            f"daily_summary={summary['bucket']} (rows={summary['row_count']}) "
            f"disagrees with snapshot high={snapshot_bucket}"
        )

    if override is not None:
        return {
            "bucket": override,
            "high": float(override),
            "source": "override",
            "note": "; ".join(note_bits) or "manual override",
            "snapshot_high": snapshot_high,
            "snapshot_column": snapshot_column,
            "summary": summary,
        }
    if summary is not None and summary["row_count"] >= COMPLETE_DAY_MIN_ROWS:
        return {
            "bucket": int(summary["bucket"]),
            "high": summary.get("high"),
            "source": "daily_summary",
            "note": "; ".join(note_bits),
            "snapshot_high": snapshot_high,
            "snapshot_column": snapshot_column,
            "summary": summary,
        }
    if snapshot_bucket is not None:
        return {
            "bucket": snapshot_bucket,
            "high": snapshot_high,
            "source": "snapshot_high",
            "note": "; ".join(note_bits) or "snapshot wu_history_high (daily summary missing/incomplete)",
            "snapshot_high": snapshot_high,
            "snapshot_column": snapshot_column,
            "summary": summary,
        }
    if summary is not None:
        return {
            "bucket": int(summary["bucket"]),
            "high": summary.get("high"),
            "source": "daily_summary(sparse)",
            "note": "; ".join(note_bits),
            "snapshot_high": snapshot_high,
            "snapshot_column": snapshot_column,
            "summary": summary,
        }
    return {
        "bucket": None,
        "high": None,
        "source": "none",
        "note": "no settlement available",
        "snapshot_high": snapshot_high,
        "snapshot_column": snapshot_column,
        "summary": summary,
    }


def resolution_spec_for(spec):
    return {
        "schema_version": RESOLUTION_SPEC_SCHEMA_VERSION,
        "market_id": spec.id,
        "city": spec.city_label,
        "event_slug_prefix": spec.slug_prefix,
        "market_unit": spec.display_unit,
        "resolution_source_type": "wunderground_history",
        "resolution_source_name": "Weather.com/Wunderground historical observations",
        "wu_history_id": spec.wu_history_id,
        "station_icao": spec.icao,
        "timezone": spec.timezone,
        "daily_max_window": {
            "date_basis": "market local target date",
            "start_local": "00:00:00",
            "end_local": "23:59:59",
            "timezone": spec.timezone,
        },
        "rounding": {
            "method": "round_half_up",
            "precision": "whole degree",
            "unit": spec.display_unit,
        },
        "data_root": str(spec.data_root),
    }


def write_resolution_specs(path=DEFAULT_LEDGER_ROOT / "resolution_specs.json", specs=None):
    specs = list(specs or all_specs())
    payload = {
        "schema_version": RESOLUTION_SPEC_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "markets": [resolution_spec_for(spec) for spec in specs],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_band_label(label):
    text = str(label or "")
    low = text.lower()
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    if not numbers:
        return {"kind": None, "value": None, "value_hi": None, "label": text}
    if "below" in low or "under" in low:
        return {"kind": "lte", "value": numbers[0], "value_hi": numbers[0], "label": text}
    if "higher" in low or "above" in low:
        return {"kind": "gte", "value": numbers[0], "value_hi": numbers[-1], "label": text}
    return {
        "kind": "eq",
        "value": numbers[0],
        "value_hi": numbers[-1] if len(numbers) >= 2 else numbers[0],
        "label": text,
    }


def clean_temperature_label(label):
    text = str(label or "")
    text = text.replace("\u00b0", " ")
    text = text.replace("\u2103", " C")
    text = text.replace("\u2109", " F")
    text = text.replace("\u00ba", " ")
    text = text.replace("\u00c2", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" C C", " C").replace(" F F", " F")
    return text


def band_value_hi(range_label, value):
    parsed = parse_band_label(range_label)
    return parsed["value_hi"] if parsed["value_hi"] is not None else value


def resolve_outcome(kind, value, settlement_bucket, value_hi=None):
    if settlement_bucket is None or kind is None or value is None:
        return None
    value = int(value)
    settlement_bucket = int(settlement_bucket)
    value_hi = int(value_hi) if value_hi is not None else value
    if kind == "lte":
        return settlement_bucket <= value
    if kind == "gte":
        return settlement_bucket >= value
    return value <= settlement_bucket <= value_hi


def winning_band_from_frame(frame, settlement_bucket):
    if settlement_bucket is None or "range_label" not in frame:
        return {}
    seen = set()
    for _, series in frame.iterrows():
        row = series.to_dict()
        label = row.get("range_label")
        parsed = parse_band_label(label)
        kind = row.get("bin_kind") or parsed["kind"]
        value = safe_int(row.get("bin_value_c"))
        if value is None:
            value = parsed["value"]
        value_hi = band_value_hi(label, value)
        key = (str(label), kind, value, value_hi)
        if key in seen:
            continue
        seen.add(key)
        if resolve_outcome(kind, value, settlement_bucket, value_hi):
            return {
                "label": str(label),
                "kind": kind,
                "value": value,
                "value_hi": value_hi,
            }
    return {}


def parse_json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def price_for_outcome(name, outcomes, prices):
    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == name.lower() and index < len(prices):
            return safe_float(prices[index])
    return None


def gamma_event_url(event_slug):
    return GAMMA_EVENT_URL_TEMPLATE.format(slug=event_slug)


def fetch_gamma_event(event_slug, timeout=10):
    response = requests.get(gamma_event_url(event_slug), timeout=timeout)
    response.raise_for_status()
    return response.json()


def polymarket_winning_markets(event):
    winners = []
    for market in (event or {}).get("markets", []) or []:
        outcomes = parse_json_list(market.get("outcomes"))
        prices = parse_json_list(market.get("outcomePrices"))
        yes_price = price_for_outcome("Yes", outcomes, prices)
        no_price = price_for_outcome("No", outcomes, prices)
        if yes_price is None:
            continue
        closed = bool(market.get("closed") or (event or {}).get("closed"))
        resolved = str(market.get("umaResolutionStatus") or "").lower() == "resolved"
        if yes_price >= 0.999 or ((closed or resolved) and yes_price > 0.5):
            label = clean_temperature_label(market.get("groupItemTitle") or market.get("question") or "")
            parsed = parse_band_label(label)
            winners.append({
                "label": label,
                "yes_price": yes_price,
                "no_price": no_price,
                "closed": closed,
                "resolved": resolved,
                "kind": parsed["kind"],
                "value": parsed["value"],
                "value_hi": parsed["value_hi"],
                "condition_id": market.get("conditionId"),
                "question": market.get("question"),
            })
    return winners


def reconcile_with_polymarket(event, settlement_bucket, local_winning_band=None):
    event = event or {}
    event_closed = bool(event.get("closed"))
    winners = polymarket_winning_markets(event)
    if not winners:
        status = "not_closed" if not event_closed else "unavailable"
        return {
            "status": status,
            "event_closed": event_closed,
            "winning_markets": [],
            "local_winning_band": local_winning_band or {},
        }
    matches = [
        item for item in winners
        if resolve_outcome(item["kind"], item["value"], settlement_bucket, item["value_hi"])
    ]
    return {
        "status": "match" if matches else "mismatch",
        "event_closed": event_closed,
        "winning_markets": winners,
        "matching_winning_markets": matches,
        "local_winning_band": local_winning_band or {},
    }


def build_reconciliation(event_slug, settlement_bucket, local_winning_band, requested=False, event=None):
    url = gamma_event_url(event_slug)
    if not requested and event is None:
        return {
            "status": "not_requested",
            "gamma_event_url": url,
            "event_closed": None,
            "winning_markets": [],
            "local_winning_band": local_winning_band or {},
        }
    try:
        event = event if event is not None else fetch_gamma_event(event_slug)
        reconciliation = reconcile_with_polymarket(event, settlement_bucket, local_winning_band)
        reconciliation["gamma_event_url"] = url
        return reconciliation
    except Exception as exc:
        return {
            "status": "fetch_error",
            "gamma_event_url": url,
            "error": str(exc),
            "event_closed": None,
            "winning_markets": [],
            "local_winning_band": local_winning_band or {},
        }


def resolve_ledger_root(ledger_root=None):
    if ledger_root is not None:
        return Path(ledger_root)
    return Path(os.environ.get(LEDGER_ROOT_ENV, DEFAULT_LEDGER_ROOT))


def ledger_path_for_market(market_id, ledger_root=None):
    return resolve_ledger_root(ledger_root) / str(market_id) / "ledger.jsonl"


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def upsert_ledger_record(label, ledger_root=None):
    path = ledger_path_for_market(label["market_id"], ledger_root)
    rows = [row for row in read_jsonl(path) if row.get("event_slug") != label.get("event_slug")]
    label = dict(label)
    label["ledger_path"] = str(path)
    rows.append(label)
    rows.sort(key=lambda row: (row.get("target_date") or "", row.get("event_slug") or ""))
    write_jsonl(path, rows)
    return path


def ledger_label_for_slug(event_slug, ledger_root=None):
    spec = spec_for_slug(event_slug)
    root = resolve_ledger_root(ledger_root)
    paths = [ledger_path_for_market(spec.id, root)] if spec else sorted(root.glob("*/ledger.jsonl"))
    for path in paths:
        for row in read_jsonl(path):
            if row.get("event_slug") == event_slug:
                return row
    return None


def write_folder_label(folder, label):
    path = Path(folder) / "settlement.json"
    path.write_text(json.dumps(label, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_mismatch_alert(label, ledger_root=None):
    if label.get("reconciliation_status") != "mismatch":
        return None
    path = resolve_ledger_root(ledger_root) / "reconciliation_alerts.jsonl"
    alert = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "event_slug": label.get("event_slug"),
        "market_id": label.get("market_id"),
        "settlement_bucket": label.get("settlement_bucket"),
        "settlement_unit": label.get("settlement_unit"),
        "winning_band": label.get("winning_band"),
        "polymarket_winning_band": label.get("polymarket_winning_band"),
        "gamma_event_url": label.get("gamma_event_url"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(alert, sort_keys=True) + "\n")
    return path


def build_label(
    folder,
    daily_summary_path=None,
    daily_index=None,
    overrides=None,
    finalized_at=None,
    interval_minutes=10.0,
    gap_tolerance=1.5,
    reconcile_polymarket=False,
    polymarket_event=None,
    ledger_root=None,
):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None
    frame = pd.read_csv(tape)
    event_slug = folder.name
    target_date = date_from_event_slug(event_slug)
    spec = spec_for_slug(event_slug)
    if spec is None:
        return None

    daily_summary_path = Path(daily_summary_path) if daily_summary_path else daily_summary_path_for_spec(spec)
    daily_index = daily_index if daily_index is not None else load_daily_summary(daily_summary_path)
    settlement = settlement_from_sources(
        frame,
        target_date,
        daily_index,
        overrides=overrides or {},
        spec=spec,
        event_slug=event_slug,
    )
    bucket = settlement["bucket"]
    winning = winning_band_from_frame(frame, bucket)

    snapshot_count = int(frame["snapshot_id"].nunique()) if "snapshot_id" in frame else 0
    band_count = int(frame["range_label"].nunique()) if "range_label" in frame else 0
    core_columns = list(CORE_PROB_COLUMNS)
    high_column = next((column for column in SNAPSHOT_HIGH_COLUMNS if column in frame), None)
    core_columns.append(high_column or SNAPSHOT_HIGH_COLUMNS[-1])
    missing_core = missing_fraction(frame, core_columns)
    coverage = coverage_summary(captured_times(frame), interval_minutes, gap_tolerance, target_date=target_date)
    coverage_clean = bool(coverage.get("clean"))
    grade = quality_grade(
        snapshot_count,
        band_count,
        bucket,
        settlement["source"],
        missing_core,
        collection_clean=coverage_clean,
    )
    finalized_at = finalized_at or datetime.now(timezone.utc)
    resolution = resolution_spec_for(spec)
    reconciliation = build_reconciliation(
        event_slug,
        bucket,
        winning,
        requested=reconcile_polymarket,
        event=polymarket_event,
    )
    winning_markets = reconciliation.get("winning_markets") or []
    polymarket_winning_band = winning_markets[0].get("label") if winning_markets else None
    ledger_path = ledger_path_for_market(spec.id, ledger_root)
    material = material_coverage_grade(
        snapshot_count,
        band_count,
        bucket,
        settlement["source"],
        missing_core,
        coverage=coverage,
        target_date=target_date,
    )
    is_promotion_countable, promotion_countable_reason = promotion_countability(
        material,
        reconciliation.get("status"),
    )

    label = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "event_slug": event_slug,
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": target_date.isoformat() if target_date else "",
        "polymarket_url": polymarket_url_for_slug(event_slug),
        "gamma_event_url": gamma_event_url(event_slug),
        "settlement_high": settlement["high"],
        "settlement_bucket": bucket,
        "settlement_unit": spec.display_unit,
        "winning_band": winning.get("label"),
        "winning_band_kind": winning.get("kind"),
        "winning_band_value": winning.get("value"),
        "winning_band_value_hi": winning.get("value_hi"),
        "settlement_source": settlement["source"],
        "quality_grade": grade,
        "quality_reason": quality_reason(grade, missing_core, coverage.get("reason")),
        "snapshot_count": snapshot_count,
        "band_count": band_count,
        "row_count": len(frame),
        "coverage_clean": coverage_clean,
        "capture_ratio": coverage.get("capture_ratio"),
        "max_gap_minutes": coverage.get("max_gap_minutes"),
        "coverage_reason": coverage.get("reason"),
        "material_coverage_grade": material["grade"],
        "material_coverage_reason": material["reason"],
        "material_coverage_window": material["window"],
        "material_coverage_gap_count": material["gap_count"],
        "material_coverage_max_gap_minutes": material["max_gap_minutes"],
        "material_peak_gap_minutes": material["peak_gap_minutes"],
        "material_coverage_decisive_gap_count": material["decisive_gap_count"],
        "material_coverage_gap_windows": material["gap_windows"],
        "material_coverage_gaps": material["gaps"],
        "promotion_countable": is_promotion_countable,
        "promotion_countable_reason": promotion_countable_reason,
        "resolution_source_type": resolution["resolution_source_type"],
        "resolution_wu_history_id": resolution["wu_history_id"],
        "resolution_station": resolution["station_icao"],
        "resolution_timezone": resolution["timezone"],
        "daily_max_window": "00:00:00-23:59:59 local",
        "rounding": "round_half_up whole degree",
        "daily_summary_path": str(daily_summary_path),
        "snapshot_tape_path": str(tape),
        "ledger_path": str(ledger_path),
        "evidence": {
            "daily_summary_path": str(daily_summary_path),
            "snapshot_tape_path": str(tape),
            "snapshot_high_column": settlement.get("snapshot_column"),
            "summary": settlement.get("summary"),
            "polymarket_reconciliation": reconciliation,
            "resolution_spec": resolution,
        },
        "polymarket_reconciliation": reconciliation,
        "reconciliation_status": reconciliation.get("status"),
        "polymarket_winning_band": polymarket_winning_band,
        "note": settlement["note"],
        "finalized_at_utc": finalized_at.isoformat(),
    }
    return label


def write_labels_csv(path, labels):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(labels, key=lambda row: (row.get("market_id") or "", row.get("target_date") or ""))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            writer.writerow(row)


def finalize_folder(
    folder,
    daily_summary_path=None,
    daily_index=None,
    overrides=None,
    finalized_at=None,
    interval_minutes=10.0,
    gap_tolerance=1.5,
    reconcile_polymarket=False,
    polymarket_event=None,
    ledger_root=None,
):
    label = build_label(
        folder,
        daily_summary_path=daily_summary_path,
        daily_index=daily_index,
        overrides=overrides,
        finalized_at=finalized_at,
        interval_minutes=interval_minutes,
        gap_tolerance=gap_tolerance,
        reconcile_polymarket=reconcile_polymarket,
        polymarket_event=polymarket_event,
        ledger_root=ledger_root,
    )
    if not label:
        return None
    write_folder_label(folder, label)
    ledger_path = upsert_ledger_record(label, ledger_root)
    label["ledger_path"] = str(ledger_path)
    append_mismatch_alert(label, ledger_root)
    return label


def finalize_folders(
    folders,
    daily_summary_path=None,
    labels_csv=DEFAULT_LABELS_CSV,
    overrides=None,
    interval_minutes=10.0,
    gap_tolerance=1.5,
    reconcile_polymarket=False,
    ledger_root=None,
):
    finalized_at = datetime.now(timezone.utc)
    labels = []
    ledger_root = resolve_ledger_root(ledger_root)
    write_resolution_specs(Path(ledger_root) / "resolution_specs.json")
    for folder in folders:
        label = finalize_folder(
            folder,
            daily_summary_path=daily_summary_path,
            overrides=overrides,
            finalized_at=finalized_at,
            interval_minutes=interval_minutes,
            gap_tolerance=gap_tolerance,
            reconcile_polymarket=reconcile_polymarket,
            ledger_root=ledger_root,
        )
        if label:
            labels.append(label)
    write_labels_csv(labels_csv, labels)
    return labels
