"""Fleet data-layer audit.

This report answers a broader question than collection health: are we capturing
the right data, often enough, with enough history to improve the model? It
combines snapshot cadence/completeness, historical source coverage, loop state,
and known market-microstructure gaps into one durable artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import fmt_num, markdown_table
from collection_health import summarize_folder
from market_config import date_from_event_slug
from market_registry import all_specs, spec_for_slug
from market_microstructure import CLOB_LOOP_STATUS_PATH, clob_loop_health
from snapshot_tracker import LOOP_STATUS_PATH, loop_health
from toronto_model import TORONTO_TZ


SCHEMA_VERSION = "data_layer_audit_v0.2"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_OUT = Path("data") / "backtest" / "data_layer_audit.json"
DEFAULT_REPORT = Path("data") / "backtest" / "data_layer_audit_report.md"

SNAPSHOT_LONG = "snapshots_long.csv"
SNAPSHOT_OPTIONAL_ARTIFACTS = {
    "replay_inputs": "replay_inputs.jsonl",
    "features": "features_long.csv",
    "components": "components_long.csv",
    "forecasts": "forecasts_long.csv",
    "settlement": "settlement.json",
}

HISTORICAL_SOURCE_ROOTS = {
    "wu": Path("data") / "wunderground",
    "metar": Path("data") / "metar",
    "ghcnh": Path("data") / "noaa_ghcnh",
    "reanalysis": Path("data") / "reanalysis",
}

MICROSTRUCTURE_DOCS = [
    {
        "name": "Polymarket CLOB order book",
        "url": "https://docs.polymarket.com/api-reference/market-data/get-order-book",
        "why": "Read-only endpoint returns current bids/asks, market details, and last trade price.",
    },
    {
        "name": "Polymarket market WebSocket",
        "url": "https://docs.polymarket.com/api-reference/wss/market",
        "why": "Public stream for real-time orderbook, price, and market lifecycle updates.",
    },
    {
        "name": "Polymarket price history",
        "url": "https://docs.polymarket.com/api-reference/markets/get-prices-history",
        "why": "Read-only historical price series by token with configurable fidelity.",
    },
]


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def iter_dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def season_dates(start, end, start_month=5, start_day=20, end_month=6, end_day=30):
    days = []
    for year in range(start.year, end.year + 1):
        lo = max(start, date(year, start_month, start_day))
        hi = min(end, date(year, end_month, end_day))
        if lo <= hi:
            days.extend(iter_dates(lo, hi))
    return days


def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def safe_max(values):
    values = [value for value in values if value is not None]
    return max(values) if values else None


def pct(part, total):
    return (float(part) / float(total)) if total else None


def read_loop_status(path=LOOP_STATUS_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def loop_summary(path=LOOP_STATUS_PATH, interval_minutes=10.0):
    status = read_loop_status(path)
    health = loop_health(status, datetime.now(TORONTO_TZ), interval_minutes)
    return {
        "status_path": str(path),
        "state": health.get("state"),
        "pid": health.get("pid"),
        "configured_interval_minutes": (status or {}).get("interval_minutes"),
        "heartbeat_age_min": health.get("heartbeat_age_min"),
        "last_snapshot_age_min": health.get("last_snapshot_age_min"),
        "consecutive_errors": health.get("consecutive_errors"),
        "last_error": health.get("last_error"),
        "started_at": health.get("started_at"),
    }


def clob_loop_summary(path=CLOB_LOOP_STATUS_PATH, interval_seconds=60.0):
    status = read_loop_status(path)
    health = clob_loop_health(status, datetime.now(timezone.utc), interval_seconds)
    return {
        "status_path": str(path),
        "state": health.get("state"),
        "pid": health.get("pid"),
        "configured_interval_seconds": (status or {}).get("interval_seconds"),
        "fast_interval_seconds": (status or {}).get("fast_interval_seconds"),
        "heartbeat_age_seconds": health.get("heartbeat_age_seconds"),
        "last_books_age_seconds": health.get("last_books_age_seconds"),
        "consecutive_errors": health.get("consecutive_errors"),
        "error_markets": health.get("error_markets"),
        "last_error": health.get("last_error"),
        "last_mode": health.get("last_mode"),
        "last_sleep_seconds": health.get("last_sleep_seconds"),
        "started_at": health.get("started_at"),
    }


def parse_snapshot_times(path):
    times = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = row.get("snapshot_id")
            ts = row.get("captured_at_local")
            if not sid or sid in times or not ts:
                continue
            try:
                times[sid] = datetime.fromisoformat(ts)
            except ValueError:
                continue
    ordered = sorted(times.values())
    gaps = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(ordered, ordered[1:])
    ]
    return ordered, gaps


def scan_snapshot_csv(path):
    row_count = 0
    field_totals = {}
    nonempty = {}
    market_rows_with_token = 0
    fields = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        for field in fields:
            field_totals[field] = 0
            nonempty[field] = 0
        for row in reader:
            row_count += 1
            for field in fields:
                field_totals[field] += 1
                if row.get(field) not in (None, ""):
                    nonempty[field] += 1
            if (
                row.get("clob_token_id")
                or row.get("clob_yes_token_id")
                or row.get("clob_no_token_id")
                or row.get("condition_id")
            ):
                market_rows_with_token += 1
    return {
        "row_count": row_count,
        "fields": fields,
        "field_totals": field_totals,
        "nonempty": nonempty,
        "rows_with_market_token_ids": market_rows_with_token,
    }


def snapshot_folder_audit(folder, interval_minutes=10.0, tolerance=1.5):
    folder = Path(folder)
    path = folder / SNAPSHOT_LONG
    spec = spec_for_slug(folder.name)
    target_date = date_from_event_slug(folder.name)
    times, gaps = parse_snapshot_times(path)
    scanned = scan_snapshot_csv(path)
    try:
        coverage = summarize_folder(
            folder,
            interval_minutes=interval_minutes,
            tolerance=tolerance,
            live=False,
        )
    except Exception as exc:  # noqa: BLE001 - audit should survive one bad tape
        coverage = {"clean": False, "reason": f"{type(exc).__name__}: {exc}"}
    artifact_presence = {
        name: (folder / filename).exists()
        for name, filename in SNAPSHOT_OPTIONAL_ARTIFACTS.items()
    }
    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": spec.id if spec else None,
        "city": spec.city_label if spec else None,
        "target_date": target_date.isoformat() if target_date else None,
        "snapshot_count": len(times),
        "band_row_count": scanned["row_count"],
        "first_capture": times[0].isoformat() if times else None,
        "last_capture": times[-1].isoformat() if times else None,
        "median_gap_minutes": safe_median(gaps),
        "max_gap_minutes": safe_max(gaps),
        "coverage_clean": bool(coverage.get("clean")),
        "coverage_reason": coverage.get("reason"),
        "capture_ratio": coverage.get("capture_ratio"),
        "artifact_presence": artifact_presence,
        "fields": scanned["fields"],
        "field_totals": scanned["field_totals"],
        "nonempty": scanned["nonempty"],
        "rows_with_market_token_ids": scanned["rows_with_market_token_ids"],
    }


def snapshot_audit(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, interval_minutes=10.0, tolerance=1.5):
    folders = sorted(Path(snapshots_root).glob(f"*/{SNAPSHOT_LONG}"))
    folder_rows = [
        snapshot_folder_audit(path.parent, interval_minutes=interval_minutes, tolerance=tolerance)
        for path in folders
    ]
    by_market = defaultdict(list)
    field_nonempty = Counter()
    field_totals = Counter()
    artifact_totals = Counter()
    for row in folder_rows:
        by_market[row.get("market_id")].append(row)
        field_nonempty.update(row.get("nonempty") or {})
        field_totals.update(row.get("field_totals") or {})
        for name, present in (row.get("artifact_presence") or {}).items():
            if present:
                artifact_totals[name] += 1
    low_fill = []
    for field, total in sorted(field_totals.items()):
        filled = field_nonempty[field]
        rate = pct(filled, total)
        if rate is not None and rate < 0.90:
            low_fill.append({
                "field": field,
                "nonempty": filled,
                "total": total,
                "fill_rate": rate,
            })
    low_fill.sort(key=lambda item: (item["fill_rate"], item["field"]))
    market_rows = []
    for market_id, rows in sorted(by_market.items()):
        if market_id is None:
            continue
        market_rows.append({
            "market_id": market_id,
            "market_day_count": len(rows),
            "settled_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("settlement")),
            "clean_days": sum(1 for row in rows if row.get("coverage_clean")),
            "replay_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("replay_inputs")),
            "feature_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("features")),
            "component_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("components")),
            "forecast_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("forecasts")),
            "median_snapshots_per_day": safe_median([row.get("snapshot_count") for row in rows]),
            "median_gap_minutes": safe_median([row.get("median_gap_minutes") for row in rows]),
            "max_gap_minutes": safe_max([row.get("max_gap_minutes") for row in rows]),
            "latest_target_date": max([row.get("target_date") for row in rows if row.get("target_date")], default=None),
        })
    return {
        "snapshots_root": str(snapshots_root),
        "folder_count": len(folder_rows),
        "total_snapshots": sum(row.get("snapshot_count") or 0 for row in folder_rows),
        "total_band_rows": sum(row.get("band_row_count") or 0 for row in folder_rows),
        "clean_folder_count": sum(1 for row in folder_rows if row.get("coverage_clean")),
        "median_snapshots_per_folder": safe_median([row.get("snapshot_count") for row in folder_rows]),
        "median_capture_gap_minutes": safe_median([row.get("median_gap_minutes") for row in folder_rows]),
        "max_capture_gap_minutes": safe_max([row.get("max_gap_minutes") for row in folder_rows]),
        "artifact_day_counts": dict(sorted(artifact_totals.items())),
        "low_fill_fields": low_fill[:25],
        "has_market_token_ids": any(row.get("rows_with_market_token_ids", 0) > 0 for row in folder_rows),
        "by_market": market_rows,
        "folders": folder_rows,
    }


def daily_dates_from_csv(path):
    path = Path(path)
    if not path.exists():
        return set()
    dates = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("local_date") or row.get("date")
            if not value:
                continue
            try:
                dates.add(date.fromisoformat(str(value)[:10]))
            except ValueError:
                continue
    return dates


def source_daily_summary_path(source, spec):
    station = spec.icao.lower()
    if source == "wu":
        return Path("data") / "wunderground" / station / "daily" / "daily_summary.csv"
    if source == "metar":
        return Path("data") / "metar" / station / "daily" / "daily_summary.csv"
    if source == "ghcnh":
        return Path("data") / "noaa_ghcnh" / station / "daily" / "daily_summary.csv"
    if source == "reanalysis":
        return Path("data") / "reanalysis" / station / "daily" / "daily_summary.csv"
    raise KeyError(source)


def coverage_for_dates(covered, expected):
    expected_set = set(expected)
    covered_expected = covered & expected_set
    missing = sorted(expected_set - covered)
    return {
        "expected_days": len(expected_set),
        "covered_days": len(covered_expected),
        "missing_days": len(missing),
        "coverage_rate": pct(len(covered_expected), len(expected_set)),
        "first_covered": min(covered).isoformat() if covered else None,
        "last_covered": max(covered).isoformat() if covered else None,
        "sample_missing": [item.isoformat() for item in missing[:10]],
    }


def historical_source_audit(spec, source, expected_period, expected_season):
    path = source_daily_summary_path(source, spec)
    covered = daily_dates_from_csv(path)
    return {
        "source": source,
        "path": str(path),
        "exists": path.exists(),
        "daily_days": len(covered),
        "period": coverage_for_dates(covered, expected_period),
        "target_season": coverage_for_dates(covered, expected_season),
    }


def historical_audit(start, end):
    expected_period = list(iter_dates(start, end))
    expected_season = season_dates(start, end)
    markets = []
    for spec in all_specs():
        sources = {
            source: historical_source_audit(spec, source, expected_period, expected_season)
            for source in ("wu", "metar", "ghcnh", "reanalysis")
        }
        markets.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "station": spec.icao,
            "unit": spec.display_unit,
            "sources": sources,
        })
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_expected_days": len(expected_period),
        "target_season_expected_days": len(expected_season),
        "target_season_window": "May 20 through June 30 each year",
        "markets": markets,
    }


def source_inventory():
    return {
        "live_weather_sources": [
            {
                "source": "wu_history",
                "role": "settlement-source intraday high and rows",
                "utility": "highest; this is the source hierarchy anchor",
            },
            {
                "source": "wu_current",
                "role": "current Weather.com station reading and since-7am max",
                "utility": "high; useful live support but not a hard settlement source",
            },
            {
                "source": "metar",
                "role": "airport observation cross-check",
                "utility": "high for US markets and Toronto source redundancy",
            },
            {
                "source": "weather_forecast/open_meteo/nws_hourly/global_ensemble/eccc_citypage",
                "role": "forecast distribution, disagreement, and remaining-heat signal",
                "utility": "high, but issue-time fidelity and raw payload retention can improve",
            },
            {
                "source": "eccc_swob",
                "role": "Toronto official observation lead signal",
                "utility": "Toronto-only, useful as a soft lead source",
            },
        ],
        "market_sources": [
            {
                "source": "Polymarket Gamma event markets",
                "captured": "yes/no prices, bid/ask, last, volume, liquidity, status",
                "gap": "metadata only; CLOB recorder is the canonical depth stream",
            },
            {
                "source": "Polymarket CLOB book recorder",
                "captured": "token ids, condition ids, raw books, book levels, depth summaries, optional price history, WebSocket events",
                "gap": "must stay supervised because missing book-depth history cannot be reconstructed",
            },
        ],
        "derived_artifacts": [
            "snapshots_long/wide",
            "snapshots.jsonl",
            "replay_inputs.jsonl",
            "features_long/jsonl",
            "components_long/jsonl",
            "forecasts_long/jsonl",
            "settlement.json and settlement ledger",
            "source redundancy truth table",
        ],
    }


def recommendation(priority, title, evidence, action, roadmap_item=None):
    return {
        "priority": priority,
        "title": title,
        "evidence": evidence,
        "action": action,
        "roadmap_item": roadmap_item,
    }


def build_recommendations(snapshot, historical, loop, clob_loop=None):
    recs = []
    if not snapshot.get("has_market_token_ids"):
        recs.append(recommendation(
            "P0",
            "Persist CLOB token IDs and full order-book snapshots",
            "Snapshot tapes currently keep shallow Gamma price fields but no condition/token ids or order-book levels.",
            (
                "Add a market microstructure capture artifact per event: token ids, book timestamp/hash, "
                "top levels, cumulative depth, spread, midpoint, imbalance, executable price for fixed sizes, "
                "and last trade metadata. Use Gamma's clobTokenIds for discovery."
            ),
            "Item 38 / data layer",
        ))
    best_bid = next((row for row in snapshot.get("low_fill_fields") or [] if row.get("field") == "best_bid"), None)
    if best_bid:
        recs.append(recommendation(
            "P0",
            "Stop relying on Gamma best bid as the bid-side market signal",
            f"best_bid fill rate is {best_bid['fill_rate']:.1%} across snapshot rows.",
            "Use CLOB /books or the market WebSocket as the canonical bid/ask/depth source; keep Gamma as metadata.",
            "Item 38",
        ))
    clob_loop = clob_loop or {}
    clob_state = clob_loop.get("state")
    clob_managed = clob_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING")
    interval = safe_float(loop.get("configured_interval_minutes"))
    if (interval is None or interval >= 10) and not clob_managed:
        recs.append(recommendation(
            "P0",
            "Split weather/model cadence from market-book cadence",
            f"The managed loop interval is {loop.get('configured_interval_minutes')} minutes.",
            (
                "Keep full weather/model snapshots at 5-10 minutes, but capture Polymarket books every "
                "30-60 seconds or subscribe to the public market WebSocket. Near close or when edge changes, "
                "increase market-book capture to 10-15 seconds without refetching every weather source."
            ),
            "Item 37 / Item 38",
        ))
    if clob_loop and not clob_managed:
        recs.append(recommendation(
            "P0",
            "Start and supervise the CLOB book loop",
            f"CLOB loop state is {clob_state}; status path is {clob_loop.get('status_path')}.",
            (
                "Run `src.market_microstructure start-detached` and register "
                "`scripts/register_clob_supervisor.ps1` so book-depth history is "
                "captured continuously and restarted after crashes or reboots."
            ),
            "Item 37 / Item 38",
        ))
    elif clob_state in ("DEGRADED", "ERRORING"):
        recs.append(recommendation(
            "P1",
            "Investigate CLOB loop degraded markets",
            f"CLOB loop state is {clob_state}; error markets: {', '.join(clob_loop.get('error_markets') or [])}.",
            "Check `data/snapshots/clob_diagnostics.jsonl` and Polymarket event availability for the failing markets.",
            "Item 37",
        ))

    low_sources = []
    for market in historical.get("markets") or []:
        for source, source_row in (market.get("sources") or {}).items():
            season = source_row.get("target_season") or {}
            if season.get("coverage_rate") is not None and season["coverage_rate"] < 0.95:
                low_sources.append((market["market_id"], source, season["covered_days"], season["expected_days"]))
    if low_sources:
        sample = ", ".join(f"{m}:{s} {c}/{e}" for m, s, c, e in low_sources[:8])
        recs.append(recommendation(
            "P1",
            "Deep-fill redundant historical weather sources for the target season",
            f"Target-season coverage below 95% for {len(low_sources)} market/source pairs; sample: {sample}.",
            (
                "Backfill METAR/ASOS, GHCNh, and reanalysis for at least May 20-June 30 across all markets "
                "from 1995 forward, then widen to April-September. Keep WU as settlement primary."
            ),
            "Items 5, 29, 30, 33",
        ))

    replay_days = snapshot.get("artifact_day_counts", {}).get("replay_inputs", 0)
    if replay_days < snapshot.get("folder_count", 0):
        recs.append(recommendation(
            "P1",
            "Reconstruct or mark legacy days without replay inputs",
            f"{replay_days}/{snapshot.get('folder_count', 0)} snapshot folders have replay_inputs.jsonl.",
            "For old useful tapes, run a deterministic replay-input backfill where possible; otherwise label them evaluation-only.",
            "Item 36",
        ))

    recs.append(recommendation(
        "P1",
        "Archive forecast raw payloads and issue-time metadata",
        "Forecast rows are useful, but Weather.com/Open-Meteo/NWS issue time usually falls back to capture time.",
        (
            "Persist raw forecast payload hashes/files for each source and capture provider issue/update time when available. "
            "This lets future models distinguish source update lag from true forecast changes."
        ),
        "Items 3, 22, 30",
    ))
    recs.append(recommendation(
        "P2",
        "Add source-status and latency rows per capture",
        "Replay inputs include merged sources, but source health is not a first-class long table.",
        (
            "Write source_status_long.csv with source id, ok/stale/error, fetched_at, age, latency, payload hash, "
            "and row counts. This makes stale-source behavior trainable and alertable."
        ),
        "Item 17 / Item 37",
    ))
    return recs


def build_audit(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    historical_start=None,
    historical_end=None,
):
    historical_start = historical_start or date(1995, 5, 20)
    historical_end = historical_end or datetime.now(TORONTO_TZ).date()
    loop = loop_summary(interval_minutes=interval_minutes)
    clob_loop = clob_loop_summary(interval_seconds=60.0)
    snapshot = snapshot_audit(snapshots_root, interval_minutes=interval_minutes, tolerance=tolerance)
    historical = historical_audit(historical_start, historical_end)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_inventory": source_inventory(),
        "loop": loop,
        "clob_loop": clob_loop,
        "snapshots": snapshot,
        "historical": historical,
        "microstructure_reference": MICROSTRUCTURE_DOCS,
    }
    payload["recommendations"] = build_recommendations(snapshot, historical, loop, clob_loop)
    return payload


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def _fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def _historical_table_rows(payload):
    rows = []
    for market in payload.get("markets") or []:
        for source, item in (market.get("sources") or {}).items():
            season = item.get("target_season") or {}
            period = item.get("period") or {}
            rows.append([
                market.get("market_id"),
                source,
                item.get("daily_days"),
                f"{season.get('covered_days', 0)}/{season.get('expected_days', 0)}",
                _fmt_pct(season.get("coverage_rate")),
                f"{period.get('covered_days', 0)}/{period.get('expected_days', 0)}",
                _fmt_pct(period.get("coverage_rate")),
                item.get("path"),
            ])
    return rows


def _snapshot_market_rows(snapshot):
    return [
        [
            row.get("market_id"),
            row.get("market_day_count"),
            row.get("settled_days"),
            row.get("clean_days"),
            row.get("replay_days"),
            row.get("feature_days"),
            row.get("component_days"),
            row.get("forecast_days"),
            fmt_num(row.get("median_snapshots_per_day"), 1),
            fmt_num(row.get("median_gap_minutes"), 2),
            fmt_num(row.get("max_gap_minutes"), 1),
        ]
        for row in snapshot.get("by_market") or []
    ]


def write_report(path, payload):
    path = Path(path)
    snapshot = payload.get("snapshots") or {}
    loop = payload.get("loop") or {}
    clob_loop = payload.get("clob_loop") or {}
    historical = payload.get("historical") or {}
    lines = [
        "# Data Layer Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Executive Summary",
        "",
        (
            "The weather/model loop and the fast CLOB book loop are separate by "
            "design: weather/model snapshots stay on a 5-10 minute cadence while "
            "book depth is captured on a faster supervised path."
        ),
        "",
        "## Loop And Snapshot Cadence",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Loop state", loop.get("state")],
            ["Configured interval", f"{loop.get('configured_interval_minutes')} min"],
            ["Heartbeat age", f"{loop.get('heartbeat_age_min')} min"],
            ["Last snapshot age", f"{loop.get('last_snapshot_age_min')} min"],
            ["CLOB loop state", clob_loop.get("state")],
            ["CLOB configured interval", f"{clob_loop.get('configured_interval_seconds')} sec"],
            ["CLOB fast interval", f"{clob_loop.get('fast_interval_seconds')} sec"],
            ["CLOB heartbeat age", f"{clob_loop.get('heartbeat_age_seconds')} sec"],
            ["CLOB last books age", f"{clob_loop.get('last_books_age_seconds')} sec"],
            ["CLOB error markets", ", ".join(clob_loop.get("error_markets") or []) or "-"],
            ["Snapshot folders", snapshot.get("folder_count")],
            ["Total snapshots", snapshot.get("total_snapshots")],
            ["Total band rows", snapshot.get("total_band_rows")],
            ["Clean folders", snapshot.get("clean_folder_count")],
            ["Median snapshots/folder", fmt_num(snapshot.get("median_snapshots_per_folder"), 1)],
            ["Median capture gap", f"{fmt_num(snapshot.get('median_capture_gap_minutes'), 2)} min"],
            ["Max capture gap", f"{fmt_num(snapshot.get('max_capture_gap_minutes'), 1)} min"],
            ["Market token IDs persisted", snapshot.get("has_market_token_ids")],
        ],
    )
    lines += [
        "",
        "## Snapshot Artifacts By Market",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Settled", "Clean", "Replay", "Features",
            "Components", "Forecasts", "Median Snaps", "Median Gap", "Max Gap",
        ],
        _snapshot_market_rows(snapshot),
    )
    lines += [
        "",
        "## Low-Fill Snapshot Fields",
        "",
    ]
    lines += markdown_table(
        ["Field", "Nonempty", "Total", "Fill Rate"],
        [
            [
                row.get("field"),
                row.get("nonempty"),
                row.get("total"),
                _fmt_pct(row.get("fill_rate")),
            ]
            for row in snapshot.get("low_fill_fields") or []
        ],
    )
    lines += [
        "",
        "## Historical Coverage",
        "",
        f"Full audit period: `{historical.get('start')}` to `{historical.get('end')}`.",
        f"Target season: {historical.get('target_season_window')}.",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Source", "Daily Rows", "Season Covered", "Season Rate",
            "Full Covered", "Full Rate", "Path",
        ],
        _historical_table_rows(historical),
    )
    lines += [
        "",
        "## Market Microstructure References",
        "",
    ]
    lines += markdown_table(
        ["Capability", "URL", "Why It Matters"],
        [
            [item.get("name"), item.get("url"), item.get("why")]
            for item in payload.get("microstructure_reference") or []
        ],
    )
    lines += [
        "",
        "## Recommendations",
        "",
    ]
    lines += markdown_table(
        ["Priority", "Recommendation", "Evidence", "Action", "Roadmap"],
        [
            [
                item.get("priority"),
                item.get("title"),
                item.get("evidence"),
                item.get("action"),
                item.get("roadmap_item") or "-",
            ]
            for item in payload.get("recommendations") or []
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit capture cadence, data usefulness, and historical coverage.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    parser.add_argument("--historical-start", default="1995-05-20")
    parser.add_argument("--historical-end", default="")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_audit(
        snapshots_root=Path(args.snapshots_root),
        interval_minutes=args.interval_minutes,
        tolerance=args.tolerance,
        historical_start=parse_date(args.historical_start),
        historical_end=parse_date(args.historical_end),
    )
    out_path = write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    print(f"Wrote data layer audit JSON to {out_path}")
    print(f"Wrote data layer audit report to {report_path}")
    rec_counts = Counter(item.get("priority") for item in payload.get("recommendations") or [])
    print("Recommendations: " + ", ".join(f"{key}={value}" for key, value in sorted(rec_counts.items())))


if __name__ == "__main__":
    main()
