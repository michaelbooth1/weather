"""Source-side official guidance row collection helpers.

This module grows raw/normalized evidence rows only. It intentionally does not
evaluate sparse-coverage gates or promotion decisions.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path

from weather.market.market_registry import spec_for_id, spec_for_slug
from weather.paths import data_path
from weather.units import to_float


OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION = "official_guidance_collection_v0.1"
DEFAULT_COLLECTION_CSV = data_path() / "backtest" / "item137_official_guidance_collection.csv"
DEFAULT_COLLECTION_SUMMARY = data_path() / "backtest" / "item137_official_guidance_collection_summary.json"
OFFICIAL_GUIDANCE_COLLECTION_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "target_date",
    "captured_at",
    "source",
    "source_family",
    "model_name",
    "valid_time",
    "minute_of_day",
    "temp_native",
    "max_temp_native",
    "wind_direction_degrees",
    "wind_gust_kmh",
    "cloud_cover",
    "sky_cover",
    "precipitation_probability",
    "precipitation",
    "quantitative_precipitation",
    "hazards_count",
    "model_temp_spread",
    "source_url",
    "payload_hash",
    "fetched_at",
    "provider_issue_time",
    "provider_update_time",
    "row_json",
]

SOURCE_FAMILIES = {
    "nws_grid": "official_us_guidance",
    "open_meteo_multimodel": "multi_model_guidance",
    "open_meteo_global_models": "multi_model_guidance",
    "eccc_gem": "official_canadian_guidance",
}


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _source_data(sources, name):
    item = (sources or {}).get(name) or {}
    if "data" in item and isinstance(item.get("data"), dict):
        return item.get("data") or {}
    return item if isinstance(item, dict) else {}


def _source_meta(data, source, captured_at=None):
    return {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "source": source,
        "source_family": SOURCE_FAMILIES.get(source, source),
        "source_url": data.get("url") or data.get("source_url"),
        "payload_hash": data.get("payload_hash"),
        "fetched_at": data.get("fetched_at"),
        "provider_issue_time": data.get("provider_issue_time"),
        "provider_update_time": data.get("provider_update_time") or data.get("last_updated"),
        "captured_at": _iso(captured_at),
    }


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _minute(row):
    if (row or {}).get("minute_of_day") not in (None, ""):
        try:
            return int((row or {}).get("minute_of_day"))
        except (TypeError, ValueError):
            return None
    value = (row or {}).get("time") or (row or {}).get("valid_time")
    if not value:
        return None
    text = str(value)
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.hour * 60 + parsed.minute
    try:
        hour, minute = text[:5].split(":")
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def _valid_time(row, target_date, spec):
    value = (row or {}).get("valid_time")
    if value:
        return value
    text = (row or {}).get("time")
    if not text or ":" not in str(text):
        return parse_date(target_date).isoformat()
    hour, minute = [int(part) for part in str(text)[:5].split(":")]
    target = parse_date(target_date)
    return datetime(target.year, target.month, target.day, hour, minute, tzinfo=spec.tz).isoformat()


def _base_row(spec, target_date, source, data, raw_row, captured_at=None, model_name=None, include_row_json=True):
    row = {
        "market": spec.id,
        "station": spec.icao,
        "target_date": parse_date(target_date).isoformat(),
        "model_name": model_name,
        "valid_time": _valid_time(raw_row, target_date, spec),
        "minute_of_day": _minute(raw_row),
        "row_json": json.dumps(raw_row or {}, sort_keys=True, default=str) if include_row_json else "",
    }
    row.update(_source_meta(data, source, captured_at=captured_at))
    return row


def _nws_grid_rows(spec, target_date, data, captured_at=None, include_row_json=True):
    output = []
    for raw in data.get("day_rows") or []:
        row = _base_row(
            spec,
            target_date,
            "nws_grid",
            data,
            raw,
            captured_at=captured_at,
            include_row_json=include_row_json,
        )
        row.update({
            "temp_native": to_float(raw.get("temp_native")),
            "max_temp_native": to_float(raw.get("max_temp_native")),
            "wind_direction_degrees": to_float(raw.get("wind_direction_degrees")),
            "wind_gust_kmh": to_float(raw.get("wind_gust_kmh")),
            "cloud_cover": to_float(raw.get("cloud_cover")),
            "sky_cover": to_float(raw.get("sky_cover")),
            "precipitation_probability": to_float(raw.get("precipitation_probability")),
            "precipitation": to_float(raw.get("precipitation")),
            "quantitative_precipitation": to_float(raw.get("quantitative_precipitation")),
            "hazards_count": to_float(raw.get("hazards_count")),
        })
        output.append(row)
    return output


def _model_member_rows(spec, target_date, source, data, captured_at=None, include_row_json=True):
    output = []
    for raw in data.get("day_rows") or []:
        models = raw.get("models") or {}
        for model_name, values in sorted(models.items()):
            values = values or {}
            row = _base_row(
                spec,
                target_date,
                source,
                data,
                raw,
                captured_at=captured_at,
                model_name=model_name,
                include_row_json=include_row_json,
            )
            row.update({
                "temp_native": to_float(values.get("temp_native")),
                "wind_direction_degrees": to_float(values.get("wind_direction_degrees")),
                "wind_gust_kmh": to_float(values.get("wind_gust_kmh")),
                "cloud_cover": to_float(values.get("cloud_cover")),
                "precipitation": to_float(values.get("precipitation")),
                "precipitation_probability": to_float(values.get("precipitation_probability")),
                "model_temp_spread": to_float(raw.get("model_temp_spread")),
            })
            output.append(row)
    return output


def build_official_guidance_collection_payload(sources, spec, target_date, captured_at=None, include_row_json=True):
    rows = []
    nws_grid = _source_data(sources, "nws_grid")
    if nws_grid:
        rows.extend(_nws_grid_rows(
            spec,
            target_date,
            nws_grid,
            captured_at=captured_at,
            include_row_json=include_row_json,
        ))
    for source in ("open_meteo_multimodel", "open_meteo_global_models", "eccc_gem"):
        data = _source_data(sources, source)
        if data:
            rows.extend(_model_member_rows(
                spec,
                target_date,
                source,
                data,
                captured_at=captured_at,
                include_row_json=include_row_json,
            ))
    source_counts = {}
    for row in rows:
        source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
    return {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "market": spec.id,
        "station": spec.icao,
        "target_date": parse_date(target_date).isoformat(),
        "captured_at": _iso(captured_at),
        "row_count": len(rows),
        "source_counts": dict(sorted(source_counts.items())),
        "rows": rows,
    }


def write_official_guidance_collection_rows(path, payload, append=False):
    rows = (payload or {}).get("rows") or []
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not append or not path.exists()
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OFFICIAL_GUIDANCE_COLLECTION_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "written_row_count": len(rows),
        "path": str(path),
    }


def _replay_paths(paths):
    output = []
    for raw_path in paths or []:
        path = Path(raw_path)
        if path.is_file() and path.name == "replay_inputs.jsonl":
            output.append(path)
        elif path.is_dir():
            output.extend(sorted(path.rglob("replay_inputs.jsonl")))
    return sorted(dict.fromkeys(output))


def _spec_for_replay(payload):
    event_slug = payload.get("event_slug")
    spec = spec_for_slug(event_slug)
    if spec is not None:
        return spec
    model_identity = payload.get("model_identity") or {}
    market_id = model_identity.get("market_id") or payload.get("market_id")
    return spec_for_id(market_id)


def collect_official_guidance_from_replay_inputs(
    paths,
    csv_out=None,
    summary_out=None,
    limit=None,
    include_row_json=False,
):
    replay_paths = _replay_paths(paths)
    rows = []
    files_read = 0
    replay_rows_read = 0
    errors = []
    source_counts = {}
    market_counts = {}
    for path in replay_paths:
        files_read += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        for line_number, line in enumerate(lines, start=1):
            if limit is not None and replay_rows_read >= int(limit):
                break
            if not line.strip():
                continue
            replay_rows_read += 1
            try:
                replay = json.loads(line)
                spec = _spec_for_replay(replay)
                target_date = replay.get("target_date") or replay.get("captured_at_local", "")[:10]
                collected = build_official_guidance_collection_payload(
                    replay.get("sources") or {},
                    spec,
                    target_date,
                    captured_at=replay.get("captured_at_local") or replay.get("captured_at_utc"),
                    include_row_json=include_row_json,
                )
            except Exception as exc:  # noqa: BLE001 - collect all viable rows
                errors.append({"path": str(path), "line": line_number, "error": str(exc)})
                continue
            for source, count in (collected.get("source_counts") or {}).items():
                source_counts[source] = source_counts.get(source, 0) + int(count)
            if collected.get("row_count"):
                market_counts[spec.id] = market_counts.get(spec.id, 0) + int(collected["row_count"])
                rows.extend(collected["rows"])
        if limit is not None and replay_rows_read >= int(limit):
            break
    payload = {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "source": "replay_inputs",
        "replay_file_count": files_read,
        "replay_rows_read": replay_rows_read,
        "row_count": len(rows),
        "source_counts": dict(sorted(source_counts.items())),
        "market_counts": dict(sorted(market_counts.items())),
        "error_count": len(errors),
        "errors": errors[:20],
        "rows": rows,
    }
    if csv_out:
        write_official_guidance_collection_rows(csv_out, payload, append=False)
        payload["csv_out"] = str(csv_out)
    if summary_out:
        summary_path = Path(summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {key: value for key, value in payload.items() if key != "rows"}
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        payload["summary_out"] = str(summary_path)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="Collect official-guidance source rows from replay inputs.")
    parser.add_argument("paths", nargs="+", help="Snapshot root(s) or replay_inputs.jsonl file(s).")
    parser.add_argument("--csv-out", default=str(DEFAULT_COLLECTION_CSV))
    parser.add_argument("--summary-out", default=str(DEFAULT_COLLECTION_SUMMARY))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-row-json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = collect_official_guidance_from_replay_inputs(
        args.paths,
        csv_out=args.csv_out,
        summary_out=args.summary_out,
        limit=args.limit,
        include_row_json=args.include_row_json,
    )
    print(json.dumps({key: value for key, value in payload.items() if key != "rows"}, indent=2, sort_keys=True))
    return 1 if payload.get("error_count") else 0


if __name__ == "__main__":
    raise SystemExit(main())
