import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests


TORONTO_TZ = ZoneInfo("America/Toronto")
STATION_ICAO = "CYYZ"
STATION_NAME = "Toronto Pearson International"
DEFAULT_SWOB_ROOT = Path("data") / "eccc_swob" / "cyyz"
DEFAULT_WU_ROOT = Path("data") / "wunderground" / "cyyz"
DEFAULT_SNAPSHOT_ROOT = Path("data") / "snapshots"

SWOB_FILE_RE = re.compile(r'href="([^"]*CYYZ-MAN-swob\.xml)"')

HOURLY_FIELDS = [
    "station",
    "obs_id",
    "obs_name",
    "valid_time_utc",
    "valid_time_local",
    "local_date",
    "local_time",
    "minute",
    "temp_c",
    "dewpoint_c",
    "heat_index_c",
    "wind_chill_c",
    "humidity",
    "pressure",
    "visibility",
    "wind_dir_deg",
    "wind_cardinal",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "precip_hourly",
    "precip_total",
    "clouds",
    "condition",
    "icon",
    "qualifier",
    "swob_station_pressure_hpa",
    "swob_mslp_hpa",
    "swob_altimeter_inhg",
    "swob_max_1h_c",
    "swob_max_6h_c",
    "swob_max_24h_c",
    "swob_min_1h_c",
    "swob_min_6h_c",
    "swob_min_24h_c",
    "swob_remark",
    "source",
    "source_file",
]

DAILY_FIELDS = [
    "local_date",
    "row_count",
    "first_time",
    "last_time",
    "max_temp_c",
    "max_temp_times",
    "max_temp_source",
    "min_temp_c",
    "avg_temp_c",
    "max_dewpoint_c",
    "max_wind_kmh",
    "max_gust_kmh",
    "max_temp_bucket_c",
    "has_non_hourly_rows",
    "non_hourly_count",
    "max_on_hour_mark",
    "condition_mode",
    "cloud_mode",
    "swob_air_temp_max_c",
    "swob_air_temp_max_times",
    "swob_max_1h_c",
    "swob_max_1h_times",
    "swob_max_6h_c",
    "swob_max_24h_c",
]

COMPARISON_FIELDS = [
    "local_date",
    "wu_source",
    "wu_max_c",
    "wu_bucket_c",
    "wu_times",
    "wu_row_count",
    "swob_max_c",
    "swob_bucket_c",
    "swob_times",
    "swob_row_count",
    "temp_diff_c",
    "abs_temp_diff_c",
    "bucket_diff_c",
    "exact_bucket_match",
    "swob_exceeds_wu",
    "swob_misses_wu",
    "swob_reached_wu_final",
    "swob_first_reach_time",
    "wu_first_max_time",
    "lead_minutes",
]

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class SWOBHistoryStore:
    def __init__(self, root=DEFAULT_SWOB_ROOT):
        self.root = Path(root)
        self.raw_root = self.root / "raw"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"
        self.analysis_root = self.root / "analysis"

    def fetch_day(self, target_date, timeout=20, force=False, sleep_seconds=0.1):
        target_date = ensure_date(target_date)
        raw_dir = self.raw_day_dir(target_date)
        manifest_path = raw_dir / "manifest.json"
        if (
            manifest_path.exists()
            and not force
            and list(raw_dir.glob("*-CYYZ-MAN-swob.xml"))
        ):
            with manifest_path.open("r", encoding="utf-8") as handle:
                cached = json.load(handle)
            cached["cached"] = True
            return cached

        raw_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "station": STATION_ICAO,
            "utc_date": target_date.isoformat(),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "missing",
            "source_url": None,
            "file_count": 0,
            "files": [],
            "errors": [],
            "cached": False,
        }

        index_html = None
        base_url = None
        for url in swob_directory_urls(target_date):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                index_html = response.text
                base_url = url
                break
            except requests.RequestException as exc:
                manifest["errors"].append({"url": url, "error": str(exc)})

        if index_html is None or base_url is None:
            write_json(manifest_path, manifest)
            return manifest

        manifest["source_url"] = base_url
        files = parse_swob_file_list(index_html)
        for filename in files:
            try:
                file_url = urljoin(base_url, filename)
                response = requests.get(file_url, timeout=timeout)
                response.raise_for_status()
                local_path = raw_dir / Path(filename).name
                local_path.write_text(response.text, encoding="utf-8")
                manifest["files"].append(
                    {
                        "filename": local_path.name,
                        "url": file_url,
                        "bytes": len(response.content),
                        "sha256": sha256_bytes(response.content),
                    }
                )
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            except requests.RequestException as exc:
                manifest["errors"].append({"url": filename, "error": str(exc)})

        manifest["file_count"] = len(manifest["files"])
        manifest["status"] = "ok" if manifest["file_count"] else "empty"
        write_json(manifest_path, manifest)
        return manifest

    def raw_day_dir(self, target_date):
        target_date = ensure_date(target_date)
        return (
            self.raw_root
            / f"year={target_date:%Y}"
            / f"month={target_date:%m}"
            / f"day={target_date:%d}"
        )

    def iter_raw_files(self):
        pattern = "year=*/month=*/day=*/*-CYYZ-MAN-swob.xml"
        yield from sorted(self.raw_root.glob(pattern))

    def rebuild_normalized_files(self):
        records = []
        for path in self.iter_raw_files():
            try:
                row = parse_swob_xml(path.read_text(encoding="utf-8"), source_file=path.name)
            except ET.ParseError:
                continue
            if row.get("local_date") and row.get("valid_time_utc"):
                records.append(row)

        records = dedupe_records(records)
        records.sort(key=lambda row: row["valid_time_utc"])
        self.write_hourly_partitions(records)
        daily_rows = summarize_daily(records)
        self.write_daily_summary(daily_rows)
        self.write_manifest(records, daily_rows)
        return records, daily_rows

    def write_hourly_partitions(self, records):
        if self.hourly_root.exists():
            for old_file in self.hourly_root.glob("year=*/month=*/observations.jsonl"):
                old_file.unlink()

        grouped = defaultdict(list)
        for row in records:
            local_dt = date.fromisoformat(row["local_date"])
            grouped[(local_dt.year, local_dt.month)].append(row)

        for (year, month), rows in sorted(grouped.items()):
            path = self.hourly_root / f"year={year:04d}" / f"month={month:02d}" / "observations.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")

    def write_daily_summary(self, daily_rows):
        path = self.daily_root / "daily_summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=DAILY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(daily_rows)

    def write_manifest(self, hourly_records, daily_rows):
        partitions = []
        if self.hourly_root.exists():
            for path in sorted(self.hourly_root.glob("year=*/month=*/observations.jsonl")):
                rel_path = path.relative_to(self.root).as_posix()
                partitions.append(
                    {
                        "path": rel_path,
                        "row_count": count_lines(path),
                        "sha256": sha256_file(path),
                    }
                )

        payload = {
            "station": STATION_ICAO,
            "station_name": STATION_NAME,
            "timezone": str(TORONTO_TZ),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": "Environment and Climate Change Canada SWOB-ML",
            "hourly_record_count": len(hourly_records),
            "daily_record_count": len(daily_rows),
            "first_date": daily_rows[0]["local_date"] if daily_rows else None,
            "last_date": daily_rows[-1]["local_date"] if daily_rows else None,
            "layout": {
                "raw": "raw/year=YYYY/month=MM/day=DD/*.xml",
                "hourly": "hourly/year=YYYY/month=MM/observations.jsonl",
                "daily": "daily/daily_summary.csv",
                "analysis": "analysis/comparison_report.md",
            },
            "partitions": partitions,
        }
        write_json(self.root / "manifest.json", payload)

    def iter_hourly_records(self):
        for path in sorted(self.hourly_root.glob("year=*/month=*/observations.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)


def swob_directory_urls(target_date):
    target_date = ensure_date(target_date)
    day = target_date.strftime("%Y%m%d")
    return [
        f"https://dd.weather.gc.ca/today/observations/swob-ml/{day}/CYYZ/",
        f"https://dd.weather.gc.ca/{day}/WXO-DD/observations/swob-ml/{day}/CYYZ/",
    ]


def parse_swob_file_list(html):
    return sorted({Path(match).name for match in SWOB_FILE_RE.findall(html or "")})


def parse_swob_xml(xml_text, source_file=""):
    root = ET.fromstring(xml_text)
    values = {}
    for element in root.iter():
        name = element.attrib.get("name")
        if name and name not in values:
            values[name] = element.attrib.get("value")

    utc_dt = parse_swob_time(values.get("date_tm"))
    local_dt = utc_dt.astimezone(TORONTO_TZ) if utc_dt else None
    cloud = cloud_summary(values)
    present_wx = values.get("prsnt_wx_1")
    remark = values.get("rmk")

    return {
        "station": values.get("icao_stn_id") or STATION_ICAO,
        "obs_id": values.get("icao_stn_id") or STATION_ICAO,
        "obs_name": values.get("stn_nam") or STATION_NAME,
        "valid_time_utc": utc_dt.isoformat() if utc_dt else None,
        "valid_time_local": local_dt.isoformat() if local_dt else None,
        "local_date": local_dt.date().isoformat() if local_dt else None,
        "local_time": local_dt.strftime("%H:%M") if local_dt else None,
        "minute": local_dt.minute if local_dt else None,
        "temp_c": to_number(values.get("air_temp")),
        "dewpoint_c": to_number(values.get("dwpt_temp")),
        "heat_index_c": None,
        "wind_chill_c": None,
        "humidity": to_number(values.get("rel_hum")),
        "pressure": to_number(values.get("stn_pres")),
        "visibility": to_number(values.get("vis")),
        "wind_dir_deg": to_number(values.get("avg_wnd_dir_10m_pst2mts")),
        "wind_cardinal": cardinal_from_degrees(to_number(values.get("avg_wnd_dir_10m_pst2mts"))),
        "wind_speed_kmh": to_number(values.get("avg_wnd_spd_10m_pst2mts")),
        "wind_gust_kmh": to_number(values.get("max_wnd_gst_spd_10m_pst10mts")),
        "precip_hourly": to_number(values.get("rnfl_snc_last_syno_hr")),
        "precip_total": None,
        "clouds": cloud,
        "condition": present_weather_summary(present_wx, remark),
        "icon": None,
        "qualifier": None,
        "swob_station_pressure_hpa": to_number(values.get("stn_pres")),
        "swob_mslp_hpa": to_number(values.get("mslp")),
        "swob_altimeter_inhg": to_number(values.get("altmetr_setng")),
        "swob_max_1h_c": to_number(values.get("max_air_temp_pst1hr")),
        "swob_max_6h_c": to_number(values.get("max_air_temp_pst6hrs")),
        "swob_max_24h_c": to_number(values.get("max_air_temp_pst24hrs")),
        "swob_min_1h_c": to_number(values.get("min_air_temp_pst1hr")),
        "swob_min_6h_c": to_number(values.get("min_air_temp_pst6hrs")),
        "swob_min_24h_c": to_number(values.get("min_air_temp_pst24hrs")),
        "swob_remark": remark,
        "source": "eccc_swob",
        "source_file": source_file,
    }


def parse_swob_time(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def cloud_summary(values):
    layers = []
    for idx in range(1, 5):
        amount = values.get(f"cld_amt_code_{idx}")
        cloud_type = values.get(f"cld_typ_{idx}")
        base = values.get(f"cld_bas_hgt_{idx}")
        parts = []
        if amount not in (None, "", "MSNG"):
            parts.append(f"amt={amount}")
        if cloud_type not in (None, "", "MSNG"):
            parts.append(f"type={cloud_type}")
        if base not in (None, "", "MSNG"):
            parts.append(f"base_m={base}")
        if parts:
            layers.append("/".join(parts))
    return "|".join(layers) if layers else None


def present_weather_summary(code, remark):
    parts = []
    if code not in (None, "", "MSNG"):
        parts.append(f"present_wx_code={code}")
    if remark not in (None, "", "MSNG"):
        parts.append(f"remark={remark}")
    return " | ".join(parts) if parts else None


def summarize_daily(records):
    grouped = defaultdict(list)
    for row in records:
        if row.get("local_date"):
            grouped[row["local_date"]].append(row)

    daily_rows = []
    for local_date, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: row["valid_time_local"])
        air_values = [row.get("temp_c") for row in rows if row.get("temp_c") is not None]
        proxy_values = []
        for row in rows:
            proxy = max_value([row.get("temp_c"), row.get("swob_max_1h_c")])
            if proxy is not None:
                proxy_values.append(proxy)

        if proxy_values:
            max_temp = max(proxy_values)
            max_temp_bucket = round_half_up(max_temp)
            max_times = [
                row["local_time"]
                for row in rows
                if same_number(max_value([row.get("temp_c"), row.get("swob_max_1h_c")]), max_temp)
            ]
            max_sources = sorted(
                {
                    proxy_source(row, max_temp)
                    for row in rows
                    if same_number(max_value([row.get("temp_c"), row.get("swob_max_1h_c")]), max_temp)
                }
            )
            max_on_hour_mark = any(
                same_number(max_value([row.get("temp_c"), row.get("swob_max_1h_c")]), max_temp)
                and row.get("minute") == 0
                for row in rows
            )
        else:
            max_temp = None
            max_temp_bucket = None
            max_times = []
            max_sources = []
            max_on_hour_mark = False

        if air_values:
            min_temp = min(air_values)
            avg_temp = round(sum(air_values) / len(air_values), 2)
            air_max = max(air_values)
            air_max_times = [
                row["local_time"]
                for row in rows
                if same_number(row.get("temp_c"), air_max)
            ]
        else:
            min_temp = None
            avg_temp = None
            air_max = None
            air_max_times = []

        max_1h = max_value(row.get("swob_max_1h_c") for row in rows)
        max_1h_times = [
            row["local_time"]
            for row in rows
            if max_1h is not None and same_number(row.get("swob_max_1h_c"), max_1h)
        ]
        non_hourly_rows = [
            row for row in rows
            if row.get("minute") not in (None, 0)
        ]

        daily_rows.append(
            {
                "local_date": local_date,
                "row_count": len(rows),
                "first_time": rows[0].get("local_time"),
                "last_time": rows[-1].get("local_time"),
                "max_temp_c": max_temp,
                "max_temp_times": "|".join(max_times),
                "max_temp_source": "|".join(max_sources),
                "min_temp_c": min_temp,
                "avg_temp_c": avg_temp,
                "max_dewpoint_c": max_value(row.get("dewpoint_c") for row in rows),
                "max_wind_kmh": max_value(row.get("wind_speed_kmh") for row in rows),
                "max_gust_kmh": max_value(row.get("wind_gust_kmh") for row in rows),
                "max_temp_bucket_c": max_temp_bucket,
                "has_non_hourly_rows": bool(non_hourly_rows),
                "non_hourly_count": len(non_hourly_rows),
                "max_on_hour_mark": max_on_hour_mark,
                "condition_mode": mode(row.get("condition") for row in rows),
                "cloud_mode": mode(row.get("clouds") for row in rows),
                "swob_air_temp_max_c": air_max,
                "swob_air_temp_max_times": "|".join(air_max_times),
                "swob_max_1h_c": max_1h,
                "swob_max_1h_times": "|".join(max_1h_times),
                "swob_max_6h_c": max_value(row.get("swob_max_6h_c") for row in rows),
                "swob_max_24h_c": max_value(row.get("swob_max_24h_c") for row in rows),
            }
        )
    return daily_rows


def compare_with_wu(
    swob_root=DEFAULT_SWOB_ROOT,
    wu_root=DEFAULT_WU_ROOT,
    snapshot_root=DEFAULT_SNAPSHOT_ROOT,
    target_month=5,
    target_day=27,
    window_days=7,
    target_only=True,
    min_swob_row_count=18,
):
    store = SWOBHistoryStore(swob_root)
    swob_daily = load_daily_summary(store.daily_root / "daily_summary.csv")
    if not swob_daily:
        _, daily_rows = store.rebuild_normalized_files()
        swob_daily = {row["local_date"]: row for row in daily_rows}
    wu_daily = load_wu_daily(Path(wu_root) / "daily" / "daily_summary.csv")
    apply_snapshot_high_overrides(wu_daily, snapshot_root)

    swob_hourly = defaultdict(list)
    for row in store.iter_hourly_records():
        swob_hourly[row["local_date"]].append(row)

    rows = []
    for local_date, swob in sorted(swob_daily.items()):
        if target_only and not in_target_window(local_date, target_month, target_day, window_days):
            continue
        if int(to_number(swob.get("row_count")) or 0) < min_swob_row_count:
            continue
        wu = wu_daily.get(local_date)
        if not wu:
            continue
        row = comparison_row(local_date, swob, wu, swob_hourly.get(local_date, []))
        if row:
            rows.append(row)

    summary = summarize_comparison(rows, target_month, target_day, window_days, min_swob_row_count)
    write_comparison_artifacts(store.analysis_root, rows, summary)
    return {
        "rows": rows,
        "summary": summary,
        "comparison_rows_path": str(store.analysis_root / "comparison_rows.csv"),
        "summary_path": str(store.analysis_root / "comparison_summary.json"),
        "report_path": str(store.analysis_root / "comparison_report.md"),
    }


def comparison_row(local_date, swob, wu, swob_hourly_rows):
    swob_max = to_number(swob.get("max_temp_c"))
    wu_max = to_number(wu.get("max_temp_c"))
    if swob_max is None or wu_max is None:
        return None

    swob_bucket = round_half_up(swob_max)
    wu_bucket = round_half_up(wu_max)
    temp_diff = round(swob_max - wu_max, 3)
    wu_first = first_time_value(wu.get("max_temp_times"))
    swob_first = first_swob_reach_time(swob_hourly_rows, wu_max)
    lead_minutes = ""
    if wu_first and swob_first:
        lead_minutes = time_to_minutes(wu_first) - time_to_minutes(swob_first)

    return {
        "local_date": local_date,
        "wu_source": wu.get("source", "wu_daily_summary"),
        "wu_max_c": wu_max,
        "wu_bucket_c": wu_bucket,
        "wu_times": wu.get("max_temp_times", ""),
        "wu_row_count": wu.get("row_count", ""),
        "swob_max_c": swob_max,
        "swob_bucket_c": swob_bucket,
        "swob_times": swob.get("max_temp_times", ""),
        "swob_row_count": swob.get("row_count", ""),
        "temp_diff_c": temp_diff,
        "abs_temp_diff_c": round(abs(temp_diff), 3),
        "bucket_diff_c": swob_bucket - wu_bucket,
        "exact_bucket_match": swob_bucket == wu_bucket,
        "swob_exceeds_wu": swob_max > wu_max,
        "swob_misses_wu": swob_max < wu_max,
        "swob_reached_wu_final": swob_first != "",
        "swob_first_reach_time": swob_first,
        "wu_first_max_time": wu_first,
        "lead_minutes": lead_minutes,
    }


def first_swob_reach_time(rows, threshold):
    for row in sorted(rows, key=lambda item: item.get("valid_time_local") or ""):
        proxy = max_value([row.get("temp_c"), row.get("swob_max_1h_c")])
        if proxy is not None and proxy >= threshold:
            return row.get("local_time") or ""
    return ""


def summarize_comparison(rows, target_month, target_day, window_days, min_swob_row_count):
    total = len(rows)
    diffs = [float(row["temp_diff_c"]) for row in rows]
    abs_diffs = [float(row["abs_temp_diff_c"]) for row in rows]
    leads = [
        int(row["lead_minutes"])
        for row in rows
        if row.get("lead_minutes") not in ("", None)
    ]
    bucket_diffs = Counter(int(row["bucket_diff_c"]) for row in rows)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_window": f"{target_month:02d}-{target_day:02d} +/- {window_days} days",
        "min_swob_row_count": min_swob_row_count,
        "days_compared": total,
        "mean_bias_c": round(sum(diffs) / total, 4) if total else None,
        "mean_abs_error_c": round(sum(abs_diffs) / total, 4) if total else None,
        "exact_bucket_match_rate": rate(rows, "exact_bucket_match"),
        "swob_exceeds_wu_rate": rate(rows, "swob_exceeds_wu"),
        "swob_misses_wu_rate": rate(rows, "swob_misses_wu"),
        "swob_reached_wu_final_rate": rate(rows, "swob_reached_wu_final"),
        "lead_timing_days": len(leads),
        "mean_lead_minutes": round(sum(leads) / len(leads), 2) if leads else None,
        "median_lead_minutes": statistics.median(leads) if leads else None,
        "bucket_diff_counts": {
            str(diff): count for diff, count in sorted(bucket_diffs.items())
        },
    }


def write_comparison_artifacts(analysis_root, rows, summary):
    analysis_root = Path(analysis_root)
    analysis_root.mkdir(parents=True, exist_ok=True)

    rows_path = analysis_root / "comparison_rows.csv"
    with rows_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPARISON_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    write_json(analysis_root / "comparison_summary.json", summary)
    report = build_report(rows, summary)
    (analysis_root / "comparison_report.md").write_text(report, encoding="utf-8")


def build_report(rows, summary):
    lines = [
        "# ECCC SWOB vs Wunderground Daily High Comparison",
        "",
        f"Generated at UTC: `{summary['generated_at_utc']}`",
        "",
        "## Scope",
        "",
        f"- Station: `{STATION_ICAO}` ({STATION_NAME})",
        f"- Target window: `{summary['target_window']}`",
        f"- Minimum SWOB rows per scored day: `{summary['min_swob_row_count']}`",
        "- SWOB daily high proxy: max of air temperature and SWOB rolling one-hour max.",
        "- WU source: daily summary, with snapshot `wu_history_high_c` overriding stale or missing current-day summaries when higher.",
        "",
        "## Overall Metrics",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Days compared | {summary['days_compared']} |",
        f"| Mean bias (SWOB - WU) | {format_number(summary['mean_bias_c'])} C |",
        f"| Mean absolute error | {format_number(summary['mean_abs_error_c'])} C |",
        f"| Exact bucket match rate | {format_rate(summary['exact_bucket_match_rate'])} |",
        f"| SWOB exceeds WU rate | {format_rate(summary['swob_exceeds_wu_rate'])} |",
        f"| SWOB misses WU rate | {format_rate(summary['swob_misses_wu_rate'])} |",
        f"| SWOB reaches WU final high rate | {format_rate(summary['swob_reached_wu_final_rate'])} |",
        f"| Lead timing sample | {summary['lead_timing_days']} days |",
        f"| Mean lead minutes | {format_number(summary['mean_lead_minutes'])} |",
        f"| Median lead minutes | {format_number(summary['median_lead_minutes'])} |",
        "",
        "## Bucket Differences",
        "",
        "| Bucket diff (SWOB - WU) | Count |",
        "| :--- | ---: |",
    ]
    for diff, count in summary["bucket_diff_counts"].items():
        lines.append(f"| {int(diff):+d} | {count} |")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            interpretation(summary),
            "",
            "## Matched Days",
            "",
            "| Date | SWOB Max | WU High | Diff | Buckets | SWOB First Reach | WU First Max | Lead Minutes | WU Source |",
            "| :--- | ---: | ---: | ---: | :--- | :--- | :--- | ---: | :--- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {date} | {swob:.1f} C | {wu:.1f} C | {diff:+.1f} C | {sb}/{wb} | {sr} | {wr} | {lead} | {source} |".format(
                date=row["local_date"],
                swob=float(row["swob_max_c"]),
                wu=float(row["wu_max_c"]),
                diff=float(row["temp_diff_c"]),
                sb=row["swob_bucket_c"],
                wb=row["wu_bucket_c"],
                sr=row.get("swob_first_reach_time") or "",
                wr=row.get("wu_first_max_time") or "",
                lead=row.get("lead_minutes") if row.get("lead_minutes") != "" else "",
                source=row.get("wu_source") or "",
            )
        )

    lines.append("")
    return "\n".join(lines)


def interpretation(summary):
    if not summary["days_compared"]:
        return "No matched SWOB/WU target-window days are available yet."
    bias = summary["mean_bias_c"] or 0
    exceed = summary["swob_exceeds_wu_rate"] or 0
    miss = summary["swob_misses_wu_rate"] or 0
    lead_days = summary["lead_timing_days"]
    lead = summary["mean_lead_minutes"]
    bias_text = "close to WU"
    if bias > 0.05:
        bias_text = "above WU"
    elif bias < -0.05:
        bias_text = "below WU"
    lead_text = "Lead timing is not available for the current matched rows."
    if lead_days and lead is not None:
        direction = "before" if lead > 0 else "after" if lead < 0 else "at the same time as"
        lead_text = f"Across {lead_days} rows with timing, SWOB first reached the WU final high {abs(lead):.1f} minutes {direction} WU's first max timestamp on average."
    return (
        f"SWOB is currently {bias_text} on the matched sample "
        f"(exceeds {exceed:.1%}, misses {miss:.1%}). {lead_text}"
    )


def load_daily_summary(path):
    path = Path(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["local_date"]: row for row in csv.DictReader(handle)}


def load_wu_daily(path):
    rows = {}
    for local_date, row in load_daily_summary(path).items():
        rows[local_date] = {
            "local_date": local_date,
            "source": "wu_daily_summary",
            "max_temp_c": row.get("max_temp_c"),
            "max_temp_times": row.get("max_temp_times", ""),
            "max_temp_bucket_c": row.get("max_temp_bucket_c"),
            "row_count": row.get("row_count", ""),
        }
    return rows


def apply_snapshot_high_overrides(wu_daily, snapshot_root):
    for local_date, snapshot in load_snapshot_wu_highs(snapshot_root).items():
        snapshot_high = snapshot.get("max_temp_c")
        if snapshot_high is None:
            continue
        existing = wu_daily.get(local_date)
        existing_high = to_number(existing.get("max_temp_c")) if existing else None
        if existing_high is None or snapshot_high >= existing_high:
            existing_times = ""
            if existing and same_number(existing_high, snapshot_high):
                existing_times = existing.get("max_temp_times", "")
            wu_daily[local_date] = {
                "local_date": local_date,
                "source": snapshot.get("source", "snapshot_history_high"),
                "max_temp_c": snapshot_high,
                "max_temp_times": existing_times,
                "max_temp_bucket_c": round_half_up(snapshot_high),
                "row_count": existing.get("row_count", "") if existing else "",
            }


def load_snapshot_wu_highs(snapshot_root):
    snapshot_root = Path(snapshot_root)
    rows_by_date = {}
    if not snapshot_root.exists():
        return rows_by_date
    for path in sorted(snapshot_root.glob("*/snapshots_long.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                local_date = event_date_from_slug(row.get("event_slug") or path.parent.name)
                high = to_number(row.get("wu_history_high_c"))
                if not local_date or high is None:
                    continue
                existing = rows_by_date.get(local_date)
                captured_at = row.get("captured_at_local", "")
                if (
                    existing is None
                    or high > existing["max_temp_c"]
                    or captured_at > existing.get("captured_at_local", "")
                ):
                    rows_by_date[local_date] = {
                        "max_temp_c": high,
                        "captured_at_local": captured_at,
                        "source": "snapshot_history_high",
                        "path": str(path),
                    }
    return rows_by_date


def event_date_from_slug(slug):
    if not slug:
        return None
    match = re.search(
        r"on-([a-z]+)-(\d{1,2})-(\d{4})",
        slug.lower(),
    )
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def dedupe_records(records):
    deduped = {}
    for row in records:
        key = (row.get("valid_time_utc"), row.get("source_file"))
        deduped[key] = row
    return list(deduped.values())


def proxy_source(row, max_temp):
    sources = []
    if same_number(row.get("temp_c"), max_temp):
        sources.append("air_temp")
    if same_number(row.get("swob_max_1h_c"), max_temp):
        sources.append("swob_1h")
    return "+".join(sources) if sources else "proxy"


def in_target_window(local_date, target_month, target_day, window_days):
    if isinstance(local_date, str):
        local_date = date.fromisoformat(local_date)
    reference_year = 2000
    target = date(reference_year, target_month, target_day)
    current = date(reference_year, local_date.month, local_date.day)
    return abs((current - target).days) <= window_days


def first_time_value(value):
    if not value:
        return ""
    return str(value).split("|")[0]


def time_to_minutes(value):
    hour, minute = str(value).split(":")[:2]
    return int(hour) * 60 + int(minute)


def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))


def to_number(value):
    if value in (None, "", "MSNG", "M"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def max_value(values):
    cleaned = [to_number(value) for value in values]
    cleaned = [value for value in cleaned if value is not None]
    return max(cleaned) if cleaned else None


def same_number(left, right, tolerance=1e-9):
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= tolerance


def mode(values):
    cleaned = [value for value in values if value not in (None, "")]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def rate(rows, field):
    return (
        sum(1 for row in rows if row.get(field) is True) / len(rows)
        if rows else None
    )


def format_rate(value):
    return "n/a" if value is None else f"{value:.1%}"


def format_number(value):
    return "n/a" if value is None else f"{float(value):.2f}"


def cardinal_from_degrees(value):
    value = to_number(value)
    if value is None:
        return None
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = int((value % 360) / 22.5 + 0.5) % 16
    return directions[index]


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def ensure_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_date(str(value))


def date_range(start_date, end_date):
    current = ensure_date(start_date)
    end_date = ensure_date(end_date)
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def count_lines(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def cmd_fetch(args):
    store = SWOBHistoryStore(args.data_root)
    for target_date in date_range(args.start, args.end):
        manifest = store.fetch_day(
            target_date,
            timeout=args.timeout,
            force=args.force,
            sleep_seconds=args.sleep,
        )
        print(
            f"{target_date}: {manifest['status']} "
            f"({manifest.get('file_count', 0)} files)"
        )


def cmd_rebuild(args):
    store = SWOBHistoryStore(args.data_root)
    hourly, daily = store.rebuild_normalized_files()
    print(f"Wrote {len(hourly)} hourly SWOB rows and {len(daily)} daily rows")


def cmd_compare(args):
    result = compare_with_wu(
        swob_root=args.data_root,
        wu_root=args.wu_root,
        snapshot_root=args.snapshot_root,
        target_month=args.month,
        target_day=args.day,
        window_days=args.window_days,
        target_only=not args.all_dates,
        min_swob_row_count=args.min_swob_row_count,
    )
    summary = result["summary"]
    print(
        f"Compared {summary['days_compared']} days; "
        f"report: {result['report_path']}"
    )


def cmd_run(args):
    store = SWOBHistoryStore(args.data_root)
    fetch_end = ensure_date(args.end) + timedelta(days=1)
    for target_date in date_range(args.start, fetch_end):
        manifest = store.fetch_day(
            target_date,
            timeout=args.timeout,
            force=args.force,
            sleep_seconds=args.sleep,
        )
        print(
            f"{target_date}: {manifest['status']} "
            f"({manifest.get('file_count', 0)} files)"
        )
    hourly, daily = store.rebuild_normalized_files()
    print(f"Wrote {len(hourly)} hourly SWOB rows and {len(daily)} daily rows")
    result = compare_with_wu(
        swob_root=args.data_root,
        wu_root=args.wu_root,
        snapshot_root=args.snapshot_root,
        target_month=args.month,
        target_day=args.day,
        window_days=args.window_days,
        target_only=not args.all_dates,
        min_swob_row_count=args.min_swob_row_count,
    )
    print(
        f"Compared {result['summary']['days_compared']} days; "
        f"report: {result['report_path']}"
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Collect and analyze ECCC SWOB-ML CYYZ observations."
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_SWOB_ROOT),
        help="Root folder for local ECCC SWOB CYYZ data.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--start", required=True, help="UTC SWOB date YYYY-MM-DD")
    fetch.add_argument("--end", required=True, help="UTC SWOB date YYYY-MM-DD")
    fetch.add_argument("--timeout", type=float, default=20)
    fetch.add_argument("--sleep", type=float, default=0.1)
    fetch.add_argument("--force", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    rebuild = subparsers.add_parser("rebuild")
    rebuild.set_defaults(func=cmd_rebuild)

    compare = subparsers.add_parser("compare")
    add_compare_args(compare)
    compare.set_defaults(func=cmd_compare)

    run = subparsers.add_parser("run")
    run.add_argument("--start", required=True, help="Local target date YYYY-MM-DD")
    run.add_argument("--end", required=True, help="Local target date YYYY-MM-DD")
    run.add_argument("--timeout", type=float, default=20)
    run.add_argument("--sleep", type=float, default=0.1)
    run.add_argument("--force", action="store_true")
    add_compare_args(run)
    run.set_defaults(func=cmd_run)

    return parser


def add_compare_args(parser):
    parser.add_argument("--wu-root", default=str(DEFAULT_WU_ROOT))
    parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    parser.add_argument("--month", type=int, default=5)
    parser.add_argument("--day", type=int, default=27)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--min-swob-row-count", type=int, default=18)
    parser.add_argument("--all-dates", action="store_true")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
