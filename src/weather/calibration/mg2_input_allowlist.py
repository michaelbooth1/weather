"""The MG-2 daily input bundle contract: an outcome-free allow-list shared by host exporter and receiver.

Data and pure functions only, so the host exporter (built by master) and the workstation receiver
(``weather.calibration.mg2_inputs``) embed the same bytes; ``allowlist_sha256()`` is recorded in every
bundle manifest and must match on both sides. Nothing here reads a file, fetches, or imports a
production package; no production module imports this one.

Contract (binding plan section 9; master's rulings of 2026-10-25):

* per target date D, every path under the bundle mirrors the host data root:
  ``snapshots/<slug>/{replay_inputs.jsonl, snapshots_long.csv, features_long.csv}`` for D's folders,
  ``snapshots/<slug>/forecast_payloads.jsonl`` (NBM rows only) for the D-1, D and D+1 folders,
  ``prev_day/<slug>/metar_rows.jsonl`` for D-1's folders, ``forecast_payload_cas/<payload_ref>``;
* METAR only: no station surface travels. ``sources.station_observations`` (whose source may be a
  Weather Underground surface) and every ``wu_*`` / ``local_history`` source are refused;
* market prices, labels and settlement fields are forbidden at any depth.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

SCHEMA = "mg2_input_allowlist/1"
BUNDLE_SCHEMA = "mg2_input_bundle/1"
MANIFEST = "manifest.json"
MANIFEST_SHA = "manifest.json.sha256"
NBM_SOURCE = "nbm_probabilistic_tmax"
NBM_SCOPE = "shared_market_invariant"

# The 11 fixed US markets (registry display unit F); the gate's cells.
MARKETS = ("atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami", "nyc",
           "san-francisco", "seattle")
# Export cut: local midnight ending D in the westernmost of the 11 markets.
CUT_TIMEZONE = "America/Los_Angeles"
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
SLUG_RE = re.compile(r"^highest-temperature-in-([a-z-]+)-on-([a-z]+)-(\d{1,2})-(\d{4})$")
BLOB_RE = re.compile(r"^sha256/([0-9a-f]{2})/([0-9a-f]{64})\.blob$")
# Bundle paths (posix, relative to the bundle root). Day offsets are relative to the target date D.
PATHS = {
    "replay_inputs": {"pattern": "snapshots/<slug>/replay_inputs.jsonl", "days": (0,)},
    "snapshots_long": {"pattern": "snapshots/<slug>/snapshots_long.csv", "days": (0,)},
    "features_long": {"pattern": "snapshots/<slug>/features_long.csv", "days": (0,)},
    "nbm_manifest": {"pattern": "snapshots/<slug>/forecast_payloads.jsonl", "days": (-1, 0, 1)},
    "prev_day_metar": {"pattern": "prev_day/<slug>/metar_rows.jsonl", "days": (-1,)},
    "nbm_blob": {"pattern": "forecast_payload_cas/sha256/<hh>/<sha256>.blob", "days": ()},
}
FILE_KINDS = {"replay_inputs.jsonl": "replay_inputs", "snapshots_long.csv": "snapshots_long",
              "features_long.csv": "features_long", "forecast_payloads.jsonl": "nbm_manifest"}

REPLAY_TOP = ("schema_version", "snapshot_id", "captured_at_utc", "captured_at_local", "event_slug",
              "target_date", "model_version", "captured_input_hash")
# Source item envelope (the capture's {ok, status, ..., data} shape) and the data keys that travel.
SOURCE_ITEM = ("ok", "status", "stale", "fetched_at")
REPLAY_SOURCES = {
    "metar": {"data": ("rows", "station_id", "target_date_match", "report_time"), "rows_whole": True},
    # PROVISIONAL (rule section 8 captured-source Clarification; L3's captured-forecast analogue).
    "open_meteo_multimodel": {"data": ("day_model_highs", "fetched_at", "target_date_match",
                                       "model_run_age_hours", "model_run_age_status"),
                              "nested": {"day_model_highs": ("gfs_seamless",)}, "provisional": True},
}
PREV_DAY_TOP = ("snapshot_id", "captured_at_utc", "captured_at_local", "event_slug", "target_date", "rows")

CSV_FIELDS = {
    "snapshots_long.csv": ("snapshot_id", "captured_at_utc", "captured_at_local", "event_slug", "model_version",
                           "range_label", "bin_kind", "bin_value_c", "bin_value_hi_c", "model_probability"),
    "features_long.csv": ("snapshot_id", "captured_at_utc", "captured_at_local", "event_slug", "target_date",
                          "model_version", "cutoff_hour", "guidance_physical_floor", "high_so_far",
                          "trusted_current_max"),
}
NBM_FIELDS = ("snapshot_id", "captured_at_utc", "event_slug", "source", "status", "parser_version",
              "provider_issue_time", "provider_update_time", "response_received_at", "fetched_at",
              "first_seen_at", "cycle_key", "payload_hash", "payload_ref", "payload_storage_scope",
              "payload_bytes")

# Forbidden at any depth, in any file (the receiver scans every key; values are never logged).
FORBIDDEN_KEYS = frozenset({
    # labels (the dev scorecard's LABELISH) and settlement
    "winner", "settlement_high", "settlement_bucket", "settlement_source", "is_winner", "p_market_yes",
    "best_bid", "best_ask", "market_mid", "promotion_countable", "label_source", "settlement_authority",
    "quality_grade", "settlement",
    # market prices and identifiers
    "market_yes", "market_no", "edge", "variant_edge", "last_trade_price", "volume", "liquidity",
    "market_status", "polymarket_market_id", "condition_id", "clob_token_ids", "clob_yes_token_id",
    "clob_no_token_id", "enable_order_book",
    # settlement-series, history and station surfaces (master 2026-10-25: METAR only)
    "wu_history", "wu_current", "local_history", "station_observations", "station",
    "wu_history_high_c", "wu_current_c", "wu_max_since_7am_c", "latest_wu_history_time",
    "latest_wu_history_minute", "latest_wu_history_temp", "station_observation_source",
    "station_current_c", "station_max_since_7am_c",
    # not needed and served-model output
    "recorded_distribution",
})
FORBIDDEN_PREFIXES = ("reanalysis_prev_", "wu_")


def contract():
    """The canonical contract object hashed by ``allowlist_sha256``."""
    return {"schema": SCHEMA, "bundle_schema": BUNDLE_SCHEMA, "markets": list(MARKETS),
            "replay_top": list(REPLAY_TOP), "source_item": list(SOURCE_ITEM),
            "replay_sources": {k: {kk: (list(vv) if isinstance(vv, tuple) else
                                        {a: list(b) for a, b in vv.items()} if isinstance(vv, dict) else vv)
                                   for kk, vv in v.items()} for k, v in REPLAY_SOURCES.items()},
            "prev_day_top": list(PREV_DAY_TOP), "csv_fields": {k: list(v) for k, v in CSV_FIELDS.items()},
            "nbm_fields": list(NBM_FIELDS), "nbm_source": NBM_SOURCE, "nbm_scope": NBM_SCOPE,
            "forbidden_keys": sorted(FORBIDDEN_KEYS), "forbidden_prefixes": list(FORBIDDEN_PREFIXES),
            "cut_timezone": CUT_TIMEZONE,
            "paths": {k: {"pattern": v["pattern"], "days": list(v["days"])} for k, v in PATHS.items()},
            "manifest": [MANIFEST, MANIFEST_SHA]}


def allowlist_sha256():
    blob = json.dumps(contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def slug_for(market, day):
    return f"highest-temperature-in-{market}-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"


def parse_slug(name):
    """``(market, date)`` for one of the 11 markets' event slugs, else None."""
    match = SLUG_RE.match(str(name))
    if not match or match.group(1) not in MARKETS or match.group(2) not in MONTHS:
        return None
    try:
        day = date(int(match.group(4)), MONTHS.index(match.group(2)) + 1, int(match.group(3)))
    except ValueError:
        return None
    return (match.group(1), day) if slug_for(match.group(1), day) == name else None


def export_cut_utc(day):
    """Local midnight ending ``day`` in the westernmost market, as aware UTC."""
    local = datetime.combine(day + timedelta(days=1), time(0), tzinfo=ZoneInfo(CUT_TIMEZONE))
    return local.astimezone(timezone.utc)


def blob_ref(payload_hash):
    return f"sha256/{payload_hash[:2]}/{payload_hash}.blob"


def classify_path(relpath, day):
    """``(kind, market, folder_date)`` for an allowed bundle path of target date ``day``, else None."""
    parts = str(relpath).split("/")
    if parts in ([MANIFEST], [MANIFEST_SHA]):
        return ("manifest", None, None)
    if len(parts) == 4 and parts[0] == "forecast_payload_cas":
        match = BLOB_RE.match("/".join(parts[1:]))
        if match and match.group(2)[:2] == match.group(1):
            return ("nbm_blob", None, None)
        return None
    if len(parts) != 3:
        return None
    parsed = parse_slug(parts[1])
    if parsed is None:
        return None
    market, folder_date = parsed
    if parts[0] == "snapshots":
        kind = FILE_KINDS.get(parts[2])
    elif parts[0] == "prev_day" and parts[2] == "metar_rows.jsonl":
        kind = "prev_day_metar"
    else:
        kind = None
    if kind is None or (folder_date - day).days not in PATHS[kind]["days"]:
        return None
    return (kind, market, folder_date)


def forbidden(key):
    key = str(key)
    return key in FORBIDDEN_KEYS or any(key.startswith(p) for p in FORBIDDEN_PREFIXES)


def forbidden_paths(value, path=""):
    """Every key path at any depth whose key is forbidden (names only)."""
    out = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if forbidden(key):
                out.append(here)
            out.extend(forbidden_paths(item, here))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out.extend(forbidden_paths(item, f"{path}[{i}]"))
    return out


def _project_source(name, item):
    spec = REPLAY_SOURCES[name]
    out = {k: item[k] for k in SOURCE_ITEM if k in item}
    data = item.get("data") or {}
    kept = {}
    for key in spec["data"]:
        if key not in data:
            continue
        value = data[key]
        if key in spec.get("nested", {}) and isinstance(value, dict):
            value = {k: value[k] for k in spec["nested"][key] if k in value}
        kept[key] = value
    out["data"] = kept
    return out


def project_replay_record(record):
    """Reference projection of one captured replay payload onto the allow-list (exporter side)."""
    out = {k: record[k] for k in REPLAY_TOP if k in record}
    sources = record.get("sources") or {}
    out["sources"] = {name: _project_source(name, sources[name]) for name in REPLAY_SOURCES if name in sources}
    return out


def project_prev_day_record(record):
    rows = (((record.get("sources") or {}).get("metar") or {}).get("data") or {}).get("rows") or []
    out = {k: record[k] for k in PREV_DAY_TOP if k in record and k != "rows"}
    out["rows"] = rows
    return out


def project_row(row, fields):
    return {k: row.get(k) for k in fields}


def replay_record_problems(record):
    """Unlisted or forbidden key paths of one bundle replay record (names only, never values)."""
    problems = [f"forbidden:{p}" for p in forbidden_paths(record)]
    for key in record:
        if key not in REPLAY_TOP and key != "sources":
            problems.append(f"unlisted:{key}")
    for name, item in (record.get("sources") or {}).items():
        if name not in REPLAY_SOURCES:
            problems.append(f"unlisted:sources.{name}")
            continue
        if not isinstance(item, dict):
            problems.append(f"malformed:sources.{name}")
            continue
        spec = REPLAY_SOURCES[name]
        for key in item:
            if key not in SOURCE_ITEM and key != "data":
                problems.append(f"unlisted:sources.{name}.{key}")
        for key, value in (item.get("data") or {}).items():
            if key not in spec["data"]:
                problems.append(f"unlisted:sources.{name}.data.{key}")
            elif key in spec.get("nested", {}) and isinstance(value, dict):
                problems.extend(f"unlisted:sources.{name}.data.{key}.{k}" for k in value
                                if k not in spec["nested"][key])
    return problems


def prev_day_record_problems(record):
    problems = [f"forbidden:{p}" for p in forbidden_paths(record)]
    problems.extend(f"unlisted:{k}" for k in record if k not in PREV_DAY_TOP)
    return problems


def nbm_row_problems(row):
    problems = [f"forbidden:{p}" for p in forbidden_paths(row)]
    problems.extend(f"unlisted:{k}" for k in row if k not in NBM_FIELDS)
    if row.get("source") != NBM_SOURCE:
        problems.append("nbm_row_not_nbm_source")
    return problems
