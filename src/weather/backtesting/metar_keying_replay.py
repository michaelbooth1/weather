"""Old-vs-new METAR row keying over retained raw AWC payloads (read-only).

``metar-parser-v4`` keys AviationWeather rows on ``obsTime``; the retired
``metar-parser-v3`` keyed them on the nominal ``reportTime``, which carried the
last routine report of each local day into the next day (M0). This command
re-parses the raw AWC payloads that the snapshot store retained for each
captured METAR fetch, once under each keying, with the production parser
(``parse_metar_payload`` / ``metar_data_from_payload``), and writes one JSONL row
per captured snapshot: the rows only one keying admits, the METAR floor
(``guidance_physical_floor`` over the METAR block), the running max, the
since-07:00 max and the current reading. It does not score anything.

Read-only contract:
- It reads ``observation_payloads.jsonl`` (or ``observation_payloads_long.csv``)
  and the content-addressed blobs under ``observation_payloads/`` of the
  requested market-day folders. Each blob's SHA-256 is verified before use.
- It writes exactly one new file, ``--out``, which must not exist and must lie
  outside the runtime ``data/`` tree (missing parent directories are created).
- It refuses every target date after ``LAST_REPLAYABLE_DATE`` (2026-09-29), and
  it skips, without opening its blob, any captured payload whose local capture
  date is after that date.

CLI:
  python -m weather.backtesting.metar_keying_replay --date YYYY-MM-DD [--date ...]
      --market MARKET [--market ...] --out <path.jsonl>
      [--snapshots-root data/snapshots]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY
from weather.backtesting.settled_days import folder_market_id
from weather.paths import data_path
from weather.units import round_half_up

LAST_REPLAYABLE_DATE = date(2026, 9, 29)
OLD_KEYING = "report_time"
NEW_KEYING = "obs_time"
SERVED_FIELDS = (
    "metar_floor",
    "same_day_max",
    "max_since_7am",
    "current_temp",
    "latest_time",
    "latest_report_time",
)
MIDNIGHT_HOURS = {23, 0, 1}


class ReplayRefused(ValueError):
    """A request outside the read-only, closed-date contract."""


def check_dates(dates):
    parsed = sorted({date.fromisoformat(str(value)) for value in dates or []})
    if not parsed:
        raise ReplayRefused("refused: at least one --date is required")
    late = [value for value in parsed if value > LAST_REPLAYABLE_DATE]
    if late:
        raise ReplayRefused(
            f"refused: {', '.join(map(str, late))} after {LAST_REPLAYABLE_DATE}; "
            "dates from 2026-09-30 are not replayable by this command"
        )
    return parsed


def check_markets(markets):
    selected = sorted(set(markets or []))
    if not selected:
        raise ReplayRefused("refused: at least one --market is required")
    unknown = [market for market in selected if market not in REGISTRY]
    if unknown:
        raise ReplayRefused(f"refused: unknown market(s) {', '.join(unknown)}")
    return selected


def check_out_path(out_path):
    out = Path(out_path).resolve()
    data_root = Path(data_path()).resolve()
    if out == data_root or data_root in out.parents:
        raise ReplayRefused(f"refused: --out {out} is inside the runtime data tree {data_root}")
    if out.exists():
        raise ReplayRefused(f"refused: --out {out} already exists; this command never overwrites")
    return out


def select_folders(snapshots_root, dates, markets):
    wanted_dates = set(dates)
    wanted_markets = set(markets)
    root = Path(snapshots_root)
    if not root.is_dir():
        return []
    selected = []
    for folder in sorted(path for path in root.iterdir() if path.is_dir()):
        market_id = folder_market_id(folder)
        target = date_from_event_slug(folder.name)
        if market_id not in wanted_markets or target not in wanted_dates:
            continue
        if target > LAST_REPLAYABLE_DATE:  # defensive; check_dates already refuses
            raise ReplayRefused(f"refused: {folder.name} targets {target}")
        selected.append((folder, market_id, target))
    return selected


def load_manifest(folder):
    """METAR rows of one folder's observation payload manifest."""
    jsonl = folder / "observation_payloads.jsonl"
    rows = []
    if jsonl.is_file():
        with jsonl.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        long_csv = folder / "observation_payloads_long.csv"
        if long_csv.is_file():
            with long_csv.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
    seen = set()
    out = []
    for row in rows:
        if row.get("source") != "metar":
            continue
        key = str(row.get("snapshot_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _local_capture(row):
    value = row.get("captured_at_local") or row.get("captured_at_utc")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def load_blob(folder, row):
    """(payload, status) for one manifest row; the SHA-256 must match."""
    digest = str(row.get("payload_hash") or "").strip().lower()
    if len(digest) != 64:
        return None, "no_payload_hash"
    candidates = [folder / "observation_payloads" / "sha256" / digest[:2] / f"{digest}.json"]
    if row.get("raw_payload_path"):
        candidates.append(Path(str(row["raw_payload_path"])))
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return None, "blob_missing"
    data = path.read_bytes()
    body = data[:-1] if data.endswith(b"\n") else data
    if hashlib.sha256(body).hexdigest() != digest:
        return None, "hash_mismatch"
    try:
        return json.loads(body.decode("utf-8")), "ok"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "unparseable"


def _row_identity(row):
    return (row.get("obs_time"), row.get("report_time"), row.get("raw"))


def _row_brief(row):
    return {
        "time": row.get("time"),
        "obs_time": row.get("obs_time"),
        "report_time": row.get("report_time"),
        "temp_native": row.get("temp_native"),
        "raw": row.get("raw"),
    }


def served_values(model, payload, keying):
    data = model.metar_data_from_payload(payload, keying=keying)
    latest = data.get("latest") or {}
    floor = model.guidance_physical_floor(sources={"metar": {"ok": True, "data": data}})
    return data["rows"], {
        "row_count": len(data["rows"]),
        "metar_floor": floor,
        "metar_floor_bucket": round_half_up(floor) if floor is not None else None,
        "same_day_max": data.get("same_day_max_native"),
        "max_since_7am": data.get("max_since_7am_native"),
        "current_temp": data.get("temp_native"),
        "latest_time": latest.get("time"),
        "latest_report_time": latest.get("report_time"),
    }


def compare_payload(model, payload):
    old_rows, old = served_values(model, payload, OLD_KEYING)
    new_rows, new = served_values(model, payload, NEW_KEYING)
    old_ids = {_row_identity(row) for row in old_rows}
    new_ids = {_row_identity(row) for row in new_rows}
    only_old = [_row_brief(row) for row in old_rows if _row_identity(row) not in new_ids]
    only_new = [_row_brief(row) for row in new_rows if _row_identity(row) not in old_ids]
    changed_fields = [field for field in SERVED_FIELDS if old.get(field) != new.get(field)]
    return {
        "old": old,
        "new": new,
        "rows_only_old": only_old,
        "rows_only_new": only_new,
        "changed_fields": changed_fields,
        "changed": bool(changed_fields or only_old or only_new),
        "floor_bucket_changed": old["metar_floor_bucket"] != new["metar_floor_bucket"],
    }


def run(folders, out_path, *, model_factory=None):
    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel

        def model_factory(market_id, target):
            return TorontoHighTempModel(market_id=market_id, target_date=target.isoformat())

    out = check_out_path(out_path)
    status_counts = Counter()
    changed_by_hour = Counter()
    station_days_floor_up = set()
    station_days_floor_down = set()
    snapshots = changed = floor_changed = bucket_changed = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        for folder, market_id, target in folders:
            model = model_factory(market_id, target)
            cache = {}
            for row in load_manifest(folder):
                captured = _local_capture(row)
                if captured is not None and captured.date() > LAST_REPLAYABLE_DATE:
                    status_counts["skipped_after_cutoff"] += 1
                    continue
                snapshots += 1
                record = {
                    "snapshot_id": str(row.get("snapshot_id")),
                    "market_id": market_id,
                    "target_date": target.isoformat(),
                    "captured_at_local": row.get("captured_at_local"),
                    "hour": captured.hour if captured is not None else None,
                    "near_local_midnight": captured is not None and captured.hour in MIDNIGHT_HOURS,
                    "recorded_parser_version": row.get("parser_version"),
                    "payload_hash": row.get("payload_hash"),
                }
                digest = str(row.get("payload_hash") or "")
                if digest not in cache:
                    payload, status = load_blob(folder, row)
                    cache[digest] = (
                        compare_payload(model, payload) if status == "ok" else None,
                        status,
                    )
                comparison, status = cache[digest]
                record["status"] = status
                status_counts[status] += 1
                if comparison is not None:
                    record.update(comparison)
                    if comparison["changed"]:
                        changed += 1
                        changed_by_hour[record["hour"]] += 1
                    old_floor = comparison["old"]["metar_floor"]
                    new_floor = comparison["new"]["metar_floor"]
                    if old_floor != new_floor:
                        floor_changed += 1
                        key = f"{market_id}:{target.isoformat()}"
                        if old_floor is not None and (new_floor is None or old_floor > new_floor):
                            station_days_floor_down.add(key)
                        else:
                            station_days_floor_up.add(key)
                    bucket_changed += int(comparison["floor_bucket_changed"])
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return {
        "snapshots": snapshots,
        "status": dict(sorted(status_counts.items())),
        "changed_snapshots": changed,
        "changed_by_hour": {str(hour): count for hour, count in sorted(
            changed_by_hour.items(), key=lambda item: (item[0] is None, item[0] or 0))},
        "floor_changed_snapshots": floor_changed,
        "floor_bucket_changed_snapshots": bucket_changed,
        "station_days_old_floor_higher": sorted(station_days_floor_down),
        "station_days_old_floor_lower": sorted(station_days_floor_up),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only old (reportTime) vs new (obsTime) METAR keying replay over "
                    f"retained AWC payloads (dates <= {LAST_REPLAYABLE_DATE} only).",
    )
    parser.add_argument("--date", action="append", required=True,
                        help="Market-day target date; repeatable.")
    parser.add_argument("--market", action="append", required=True, choices=sorted(REGISTRY),
                        help="Registered market id; repeatable.")
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--out", required=True,
                        help="New JSONL file outside data/ (never overwritten).")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        dates = check_dates(args.date)
        markets = check_markets(args.market)
        check_out_path(args.out)
        folders = select_folders(args.snapshots_root, dates, markets)
        summary = run(folders, args.out)
    except ReplayRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({
        "folders": [folder.name for folder, _, _ in folders],
        "out": str(Path(args.out).resolve()),
        **summary,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
