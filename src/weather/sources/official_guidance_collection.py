"""Source-side official guidance row collection helpers.

This module grows raw/normalized evidence rows only. It intentionally does not
evaluate sparse-coverage gates or promotion decisions.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
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
    "run_time",
    "forecast_hour",
    "product",
    "level",
    "field",
    "unit",
    "grid",
    "domain",
    "object_key",
    "payload_bytes",
    "row_json",
]

SOURCE_FAMILIES = {
    "nws_grid": "official_us_guidance",
    "open_meteo_multimodel": "multi_model_guidance",
    "open_meteo_global_models": "multi_model_guidance",
    "eccc_gem": "official_canadian_guidance",
    "eccc_hrdps": "official_canadian_guidance",
}

HRDPS_SOURCE_KEYS = ("eccc_hrdps", "eccc_hrdps_grib", "hrdps_grib")
HRDPS_ARCHIVE_URL_TEMPLATE = (
    "https://dd.weather.gc.ca/{archive_date}/WXO-DD/model_hrdps/continental/2.5km"
    "/{run_hour}/{forecast_hour}/"
)
HRDPS_PRIORITY_PRODUCTS = (
    "TMP:AGL-2m",
    "GUST:AGL-10m",
    "RH:AGL-2m",
    "APCP:Sfc",
    "APCP-Accum1h:Sfc",
    "HGT:ISBL_0500",
    "TMP:ISBL_0850",
    "TMP:ISBL_0925",
    "WDIR:AGL-10m",
    "WIND:AGL-10m",
    "SKSTATE:Sfc",
)
HRDPS_ARCHIVE_FILE_RE = re.compile(
    r"(?P<object_key>(?P<run>\d{8}T\d{2}Z)_MSC_(?P<model>HRDPS(?:-WEonG)?)_"
    r"(?P<product>[A-Z0-9-]+)_(?P<level>[^_]+)_(?P<grid>RLatLon[0-9.]+)_"
    r"PT(?P<forecast_hour>\d{3})H\.grib2)"
)
HRDPS_ARCHIVE_LINK_RE = re.compile(
    r'<a href="(?P<href>[^"]+\.grib2)">.*?</a>\s+'
    r"(?P<modified>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+"
    r"(?P<size>[0-9.]+[KMG]?)",
    re.IGNORECASE | re.DOTALL,
)


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


def _compact_archive_date(value) -> str:
    text = str(value or "").strip()
    if "-" in text:
        return parse_date(text).strftime("%Y%m%d")
    return text[:8]


def _hrdps_product_filter(products=None) -> set[tuple[str, str]]:
    selected = products or HRDPS_PRIORITY_PRODUCTS
    output = set()
    for item in selected:
        product, _, level = str(item).partition(":")
        if product and level:
            output.add((product, level))
    return output


def _parse_listing_size(value):
    text = str(value or "").strip().upper()
    if not text:
        return None
    multiplier = 1
    if text.endswith("K"):
        multiplier = 1024
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1024 * 1024
        text = text[:-1]
    elif text.endswith("G"):
        multiplier = 1024 * 1024 * 1024
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def _parse_hrdps_run_time(value):
    return datetime.strptime(str(value), "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)


def _hrdps_forecast_hours_for_target_date(run_date, run_hour, target_date, tz):
    run = datetime.strptime(f"{_compact_archive_date(run_date)}T{int(run_hour):02d}Z", "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    target = parse_date(target_date)
    hours = []
    for forecast_hour in range(1, 49):
        valid = run + timedelta(hours=forecast_hour)
        if valid.astimezone(tz).date() == target:
            hours.append(f"{forecast_hour:03d}")
    return hours


def _read_url_text(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed public weather data URLs
        return response.read().decode("utf-8", errors="replace")


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


def _hrdps_temperature_value(raw):
    for key in ("temp_native", "temperature", "temperature_2m", "value"):
        value = to_float((raw or {}).get(key))
        if value is not None:
            if key == "value":
                field = str((raw or {}).get("field") or (raw or {}).get("product") or "").lower()
                if field and "tmp" not in field and "temp" not in field:
                    continue
            return value
    return None


def _hrdps_rows_from(data):
    rows = []
    for key in ("hrdps_rows", "grib_rows", "grib_probes", "probes", "rows"):
        for raw in (data or {}).get(key) or []:
            if not isinstance(raw, dict):
                continue
            model = str(raw.get("model") or "").upper()
            product = str(raw.get("product") or raw.get("field") or raw.get("variable") or "").upper()
            source_url = str(raw.get("source_url") or "")
            if model == "HRDPS" or "HRDPS" in source_url or product:
                rows.append(raw)
    return rows


def _hrdps_probe_rows(spec, target_date, source, data, captured_at=None, include_row_json=True):
    output = []
    for raw in _hrdps_rows_from(data):
        row = _base_row(
            spec,
            target_date,
            source,
            data,
            raw,
            captured_at=captured_at,
            model_name=raw.get("model") or "HRDPS",
            include_row_json=include_row_json,
        )
        row.update({
            "temp_native": _hrdps_temperature_value(raw),
            "source_url": raw.get("source_url") or row.get("source_url"),
            "payload_hash": raw.get("payload_hash") or row.get("payload_hash"),
            "fetched_at": raw.get("fetched_at") or row.get("fetched_at"),
            "run_time": raw.get("run_time") or raw.get("run_time_utc"),
            "forecast_hour": raw.get("forecast_hour"),
            "product": raw.get("product") or raw.get("variable"),
            "level": raw.get("level"),
            "field": raw.get("field"),
            "unit": raw.get("unit"),
            "grid": raw.get("grid"),
            "domain": raw.get("domain"),
            "object_key": raw.get("object_key"),
            "payload_bytes": raw.get("payload_bytes"),
        })
        output.append(row)
    return output


def _hrdps_archive_rows_from_listing(
    text,
    listing_url,
    spec,
    target_date,
    products=None,
    captured_at=None,
    include_row_json=True,
):
    selected_products = _hrdps_product_filter(products)
    output = []
    for match in HRDPS_ARCHIVE_LINK_RE.finditer(text or ""):
        href = match.group("href")
        parsed = HRDPS_ARCHIVE_FILE_RE.search(href)
        if not parsed:
            continue
        meta = parsed.groupdict()
        if (meta["product"], meta["level"]) not in selected_products:
            continue
        run_time = _parse_hrdps_run_time(meta["run"])
        forecast_hour = int(meta["forecast_hour"])
        valid_time = run_time + timedelta(hours=forecast_hour)
        valid_local = valid_time.astimezone(spec.tz)
        modified = datetime.strptime(match.group("modified"), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        size = _parse_listing_size(match.group("size"))
        source_url = urllib.parse.urljoin(listing_url, href)
        raw_row = {
            "model": meta["model"],
            "product": meta["product"],
            "level": meta["level"],
            "field": meta["product"],
            "valid_time": valid_time.isoformat(),
            "source_url": source_url,
            "object_key": meta["object_key"],
            "run_time": run_time.isoformat(),
            "forecast_hour": forecast_hour,
            "grid": meta["grid"],
            "domain": "continental",
            "payload_bytes": size,
            "provider_update_time": modified.isoformat(),
            "listing_url": listing_url,
            "listing_size": match.group("size"),
        }
        row = _base_row(
            spec,
            target_date,
            "eccc_hrdps",
            {
                "source_url": source_url,
                "fetched_at": _iso(captured_at),
                "provider_update_time": modified.isoformat(),
            },
            raw_row,
            captured_at=captured_at,
            model_name=meta["model"],
            include_row_json=include_row_json,
        )
        row.update({
            "valid_time": valid_time.isoformat(),
            "minute_of_day": valid_local.hour * 60 + valid_local.minute,
            "source_url": source_url,
            "fetched_at": _iso(captured_at),
            "provider_update_time": modified.isoformat(),
            "run_time": run_time.isoformat(),
            "forecast_hour": forecast_hour,
            "product": meta["product"],
            "level": meta["level"],
            "field": meta["product"],
            "grid": meta["grid"],
            "domain": "continental",
            "object_key": meta["object_key"],
            "payload_bytes": size,
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
    eccc_gem = _source_data(sources, "eccc_gem")
    if eccc_gem:
        rows.extend(_hrdps_probe_rows(
            spec,
            target_date,
            "eccc_hrdps",
            eccc_gem,
            captured_at=captured_at,
            include_row_json=include_row_json,
        ))
    for source_key in HRDPS_SOURCE_KEYS:
        data = _source_data(sources, source_key)
        if data:
            rows.extend(_hrdps_probe_rows(
                spec,
                target_date,
                "eccc_hrdps",
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


def build_hrdps_archive_collection_payload(
    archive_dates,
    target_dates=None,
    products=None,
    captured_at=None,
    include_row_json=True,
    fetch_text=None,
):
    spec = spec_for_id("toronto")
    target_dates = target_dates or archive_dates
    if len(target_dates) != len(archive_dates):
        raise ValueError("target_dates must be the same length as archive_dates")
    fetch_text = fetch_text or _read_url_text
    rows = []
    errors = []
    directories_read = 0
    captured_at = captured_at or datetime.now(timezone.utc)
    for archive_date, target_date in zip(archive_dates, target_dates):
        archive = _compact_archive_date(archive_date)
        for run_hour in ("00", "06", "12", "18"):
            forecast_hours = _hrdps_forecast_hours_for_target_date(archive, run_hour, target_date, spec.tz)
            for forecast_hour in forecast_hours:
                url = HRDPS_ARCHIVE_URL_TEMPLATE.format(
                    archive_date=archive,
                    run_hour=run_hour,
                    forecast_hour=forecast_hour,
                )
                try:
                    text = fetch_text(url)
                    directories_read += 1
                except Exception as exc:  # noqa: BLE001 - source coverage should keep partial rows
                    errors.append({"url": url, "error": str(exc)})
                    continue
                rows.extend(_hrdps_archive_rows_from_listing(
                    text,
                    url,
                    spec,
                    target_date,
                    products=products,
                    captured_at=captured_at,
                    include_row_json=include_row_json,
                ))
    source_counts = {}
    for row in rows:
        source_counts[row["source"]] = source_counts.get(row["source"], 0) + 1
    return {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "source": "hrdps_datamart_archive",
        "market": spec.id,
        "station": spec.icao,
        "archive_dates": [_compact_archive_date(value) for value in archive_dates],
        "row_count": len(rows),
        "directory_count": directories_read,
        "source_counts": dict(sorted(source_counts.items())),
        "error_count": len(errors),
        "errors": errors[:20],
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


def _row_identity(row):
    return tuple(
        row.get(key)
        for key in (
            "market",
            "station",
            "target_date",
            "source",
            "source_family",
            "model_name",
            "valid_time",
            "minute_of_day",
            "source_url",
            "payload_hash",
            "provider_issue_time",
            "provider_update_time",
            "run_time",
            "forecast_hour",
            "product",
            "level",
            "field",
            "unit",
            "grid",
            "domain",
            "object_key",
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
        )
    )


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
    dedupe=False,
):
    replay_paths = _replay_paths(paths)
    rows = []
    seen_rows = set()
    duplicate_row_count = 0
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
            if collected.get("row_count"):
                added_count = 0
                for row in collected["rows"]:
                    if dedupe:
                        key = _row_identity(row)
                        if key in seen_rows:
                            duplicate_row_count += 1
                            continue
                        seen_rows.add(key)
                    source = row["source"]
                    source_counts[source] = source_counts.get(source, 0) + 1
                    rows.append(row)
                    added_count += 1
                if added_count:
                    market_counts[spec.id] = market_counts.get(spec.id, 0) + added_count
        if limit is not None and replay_rows_read >= int(limit):
            break
    payload = {
        "schema_version": OFFICIAL_GUIDANCE_COLLECTION_SCHEMA_VERSION,
        "source": "replay_inputs",
        "replay_file_count": files_read,
        "replay_rows_read": replay_rows_read,
        "row_count": len(rows),
        "dedupe": bool(dedupe),
        "duplicate_row_count": duplicate_row_count,
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


def merge_collection_payload(base, extra):
    extra_rows = (extra or {}).get("rows") or []
    base.setdefault("rows", []).extend(extra_rows)
    base["row_count"] = len(base.get("rows") or [])
    base["source"] = "+".join(dict.fromkeys(str(base.get("source") or "").split("+") + [str(extra.get("source") or "")]))
    base["error_count"] = int(base.get("error_count") or 0) + int(extra.get("error_count") or 0)
    base["errors"] = ((base.get("errors") or []) + (extra.get("errors") or []))[:20]
    source_counts = dict(base.get("source_counts") or {})
    for source, count in (extra.get("source_counts") or {}).items():
        source_counts[source] = source_counts.get(source, 0) + int(count)
    base["source_counts"] = dict(sorted(source_counts.items()))
    market_counts = dict(base.get("market_counts") or {})
    market = extra.get("market")
    if market and extra_rows:
        market_counts[market] = market_counts.get(market, 0) + len(extra_rows)
    base["market_counts"] = dict(sorted(market_counts.items()))
    collection_summary = {key: value for key, value in (extra or {}).items() if key != "rows"}
    base.setdefault("extra_collections", []).append(collection_summary)
    return base


def write_collection_summary(path, payload):
    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in payload.items() if key != "rows"}
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    payload["summary_out"] = str(summary_path)
    return summary_path


def build_parser():
    parser = argparse.ArgumentParser(description="Collect official-guidance source rows from replay inputs.")
    parser.add_argument("paths", nargs="+", help="Snapshot root(s) or replay_inputs.jsonl file(s).")
    parser.add_argument("--csv-out", default=str(DEFAULT_COLLECTION_CSV))
    parser.add_argument("--summary-out", default=str(DEFAULT_COLLECTION_SUMMARY))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-row-json", action="store_true")
    parser.add_argument("--dedupe", action="store_true", help="Write each raw provider row identity once.")
    parser.add_argument(
        "--hrdps-archive-dates",
        default="",
        help="Comma-separated YYYY-MM-DD/YYYYMMDD ECCC archive dates to add as raw HRDPS index rows.",
    )
    parser.add_argument(
        "--hrdps-products",
        default=",".join(HRDPS_PRIORITY_PRODUCTS),
        help="Comma-separated HRDPS product:level pairs for archive index collection.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = collect_official_guidance_from_replay_inputs(
        args.paths,
        csv_out=None,
        summary_out=None,
        limit=args.limit,
        include_row_json=args.include_row_json,
        dedupe=args.dedupe,
    )
    hrdps_dates = [value.strip() for value in str(args.hrdps_archive_dates or "").split(",") if value.strip()]
    if hrdps_dates:
        hrdps_payload = build_hrdps_archive_collection_payload(
            hrdps_dates,
            products=[value.strip() for value in str(args.hrdps_products or "").split(",") if value.strip()],
            include_row_json=args.include_row_json,
        )
        merge_collection_payload(payload, hrdps_payload)
    if args.csv_out:
        write_official_guidance_collection_rows(args.csv_out, payload, append=False)
        payload["csv_out"] = str(args.csv_out)
    if args.summary_out:
        write_collection_summary(args.summary_out, payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "rows"}, indent=2, sort_keys=True))
    return 1 if payload.get("error_count") else 0


if __name__ == "__main__":
    raise SystemExit(main())
