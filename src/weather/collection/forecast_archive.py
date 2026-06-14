import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import date_from_event_slug
from daily_summary import native_high
from toronto_model import TARGET_DATE, TORONTO_TZ
from wu_history import DEFAULT_DATA_ROOT


FORECAST_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "target_date",
    "source",
    "forecast_kind",
    "issue_time",
    "issue_time_basis",
    "valid_time",
    "horizon_minutes",
    "target_temp_c",
    "forecast_high_c",
    "cloud_cover",
    "wind_speed_kmh",
    "condition",
    "source_url",
    "payload_hash",
    "is_changed",
]

OLD_FORECAST_COLUMN_MAP = {
    "temp_c": "target_temp_c",
}


def build_forecast_rows(
    sources,
    model_client,
    captured_at,
    snapshot_id,
    event_slug,
    archive_path=None,
    target_date=None,
):
    target_date = target_date or getattr(model_client, "target_date", TARGET_DATE)
    tz = getattr(getattr(model_client, "spec", None), "tz", TORONTO_TZ)
    captured_utc = captured_at.astimezone(timezone.utc).isoformat()
    captured_local = captured_at.isoformat()
    rows = []

    weather = model_client.source_data(sources, "weather_forecast")
    for raw in weather.get("rows", []) or []:
        valid_time = normalize_valid_time(raw.get("valid_time") or raw.get("time"), target_date, tz)
        row = forecast_row(
            snapshot_id=snapshot_id,
            captured_at_utc=captured_utc,
            captured_at_local=captured_local,
            event_slug=event_slug,
            source="weather_forecast",
            forecast_kind="hourly",
            issue_time=captured_local,
            issue_time_basis="capture_fallback",
            valid_time=valid_time,
            captured_at=captured_at,
            target_temp_c=raw.get("temp_c"),
            forecast_high_c=None,
            cloud_cover=raw.get("cloud_cover"),
            wind_speed_kmh=raw.get("wind_kmh"),
            condition=raw.get("condition"),
            source_url=weather.get("url"),
        )
        rows.append(row)

    open_meteo = model_client.source_data(sources, "open_meteo")
    for raw in open_meteo.get("rows", []) or []:
        valid_time = normalize_valid_time(raw.get("valid_time") or raw.get("time"), target_date, tz)
        row = forecast_row(
            snapshot_id=snapshot_id,
            captured_at_utc=captured_utc,
            captured_at_local=captured_local,
            event_slug=event_slug,
            source="open_meteo",
            forecast_kind="hourly",
            issue_time=captured_local,
            issue_time_basis="capture_fallback",
            valid_time=valid_time,
            captured_at=captured_at,
            target_temp_c=raw.get("temp_c"),
            forecast_high_c=None,
            cloud_cover=raw.get("cloud_cover"),
            wind_speed_kmh=raw.get("wind_kmh"),
            condition=f"solar {raw.get('solar', '-')} W/m2",
            source_url=open_meteo.get("url"),
        )
        rows.append(row)

    nws = model_client.source_data(sources, "nws_hourly")
    for raw in nws.get("rows", []) or []:
        valid_time = normalize_valid_time(raw.get("valid_time") or raw.get("time"), target_date, tz)
        row = forecast_row(
            snapshot_id=snapshot_id,
            captured_at_utc=captured_utc,
            captured_at_local=captured_local,
            event_slug=event_slug,
            source="nws_hourly",
            forecast_kind="hourly",
            issue_time=captured_local,
            issue_time_basis="capture_fallback",
            valid_time=valid_time,
            captured_at=captured_at,
            target_temp_c=raw.get("temp_c"),
            forecast_high_c=None,
            cloud_cover=None,
            wind_speed_kmh=raw.get("wind_kmh"),
            condition=raw.get("condition"),
            source_url=nws.get("url"),
        )
        rows.append(row)

    global_ensemble = model_client.source_data(sources, "global_ensemble")
    for raw in global_ensemble.get("rows", []) or []:
        valid_time = normalize_valid_time(raw.get("valid_time") or raw.get("time"), target_date, tz)
        row = forecast_row(
            snapshot_id=snapshot_id,
            captured_at_utc=captured_utc,
            captured_at_local=captured_local,
            event_slug=event_slug,
            source="global_ensemble",
            forecast_kind="hourly",
            issue_time=captured_local,
            issue_time_basis="capture_fallback",
            valid_time=valid_time,
            captured_at=captured_at,
            target_temp_c=raw.get("temp_c"),
            forecast_high_c=None,
            cloud_cover=None,
            wind_speed_kmh=None,
            condition=(
                f"GFS ensemble; member spread {raw.get('ensemble_member_spread')}"
                if raw.get("ensemble_member_spread") is not None
                else raw.get("condition")
            ),
            source_url=global_ensemble.get("url"),
        )
        rows.append(row)

    eccc = model_client.source_data(sources, "eccc_citypage")
    if eccc:
        issue_time = eccc.get("last_updated") or captured_local
        issue_basis = "source_last_updated" if eccc.get("last_updated") else "capture_fallback"
        row = forecast_row(
            snapshot_id=snapshot_id,
            captured_at_utc=captured_utc,
            captured_at_local=captured_local,
            event_slug=event_slug,
            source="eccc_citypage",
            forecast_kind="daily_high",
            issue_time=issue_time,
            issue_time_basis=issue_basis,
            valid_time=target_date.isoformat(),
            captured_at=captured_at,
            target_temp_c=eccc.get("forecast_high_c"),
            forecast_high_c=eccc.get("forecast_high_c"),
            cloud_cover=None,
            wind_speed_kmh=eccc.get("wind_kmh"),
            condition=build_eccc_condition(eccc),
            source_url=eccc.get("url"),
        )
        if should_archive_eccc_row(row, archive_path):
            rows.append(row)

    return rows


def forecast_row(
    snapshot_id,
    captured_at_utc,
    captured_at_local,
    event_slug,
    source,
    forecast_kind,
    issue_time,
    issue_time_basis,
    valid_time,
    captured_at,
    target_temp_c,
    forecast_high_c,
    cloud_cover,
    wind_speed_kmh,
    condition,
    source_url,
):
    target_date = target_date_from_valid_time(valid_time)
    row = {
        "snapshot_id": snapshot_id,
        "captured_at_utc": captured_at_utc,
        "captured_at_local": captured_at_local,
        "event_slug": event_slug,
        "target_date": target_date,
        "source": source,
        "forecast_kind": forecast_kind,
        "issue_time": issue_time,
        "issue_time_basis": issue_time_basis,
        "valid_time": valid_time,
        "horizon_minutes": horizon_minutes(captured_at, valid_time),
        "target_temp_c": target_temp_c,
        "forecast_high_c": forecast_high_c,
        "cloud_cover": cloud_cover,
        "wind_speed_kmh": wind_speed_kmh,
        "condition": condition,
        "source_url": source_url,
    }
    row["payload_hash"] = payload_hash(row)
    row["is_changed"] = "true"
    return row


def normalize_valid_time(value, target_date=TARGET_DATE, tz=TORONTO_TZ):
    if not value:
        return ""
    text = str(value)
    if "T" in text:
        return text
    if len(text) == 5 and ":" in text:
        hour, minute = [int(part) for part in text.split(":")]
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=tz,
        ).isoformat()
    return text


def target_date_from_valid_time(valid_time, fallback_date=TARGET_DATE):
    if not valid_time:
        return fallback_date.isoformat()
    text = str(valid_time)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return fallback_date.isoformat()


def horizon_minutes(captured_at, valid_time):
    if not valid_time or "T" not in str(valid_time):
        return ""
    try:
        valid_dt = datetime.fromisoformat(str(valid_time)).astimezone(TORONTO_TZ)
        return int(round((valid_dt - captured_at).total_seconds() / 60.0))
    except ValueError:
        return ""


def build_eccc_condition(eccc):
    parts = []
    if eccc.get("forecast_summary"):
        parts.append(f"summary: {eccc.get('forecast_summary')}")
    if eccc.get("forecast_cloud"):
        parts.append(f"cloud: {eccc.get('forecast_cloud')}")
    if eccc.get("forecast_wind"):
        parts.append(f"wind: {eccc.get('forecast_wind')}")
    return " | ".join(parts)


def payload_hash(row):
    payload = {
        "source": row.get("source"),
        "forecast_kind": row.get("forecast_kind"),
        "issue_time": row.get("issue_time"),
        "valid_time": row.get("valid_time"),
        "target_temp_c": row.get("target_temp_c"),
        "forecast_high_c": row.get("forecast_high_c"),
        "cloud_cover": row.get("cloud_cover"),
        "wind_speed_kmh": row.get("wind_speed_kmh"),
        "condition": row.get("condition"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def should_archive_eccc_row(row, archive_path):
    if archive_path is None:
        row["is_changed"] = "true"
        return True
    prior_hash = last_payload_hash(archive_path, row["source"], row["forecast_kind"])
    changed = prior_hash != row["payload_hash"]
    row["is_changed"] = "true" if changed else "false"
    return changed


def last_payload_hash(path, source, forecast_kind):
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except csv.Error:
        return None
    for row in reversed(rows):
        if row.get("source") == source and row.get("forecast_kind") == forecast_kind:
            return row.get("payload_hash")
    return None


def migrate_csv_schema(path, columns):
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if existing_fields == list(columns):
        return
    migrated = []
    for row in rows:
        new_row = {column: "" for column in columns}
        for old_key, value in row.items():
            new_key = OLD_FORECAST_COLUMN_MAP.get(old_key, old_key)
            if new_key in new_row:
                new_row[new_key] = value
        if not new_row.get("event_slug"):
            new_row["event_slug"] = infer_event_slug(path)
        if not new_row.get("target_date"):
            new_row["target_date"] = target_date_from_valid_time(new_row.get("valid_time"))
        if not new_row.get("forecast_kind"):
            new_row["forecast_kind"] = "hourly" if new_row.get("valid_time") not in ("", "high") else "daily_high"
        if not new_row.get("issue_time"):
            new_row["issue_time"] = new_row.get("captured_at_local", "")
            new_row["issue_time_basis"] = "capture_fallback"
        if not new_row.get("valid_time") and row.get("valid_time"):
            new_row["valid_time"] = normalize_valid_time(row.get("valid_time"))
        elif new_row.get("valid_time"):
            new_row["valid_time"] = normalize_valid_time(new_row["valid_time"])
        if not new_row.get("horizon_minutes"):
            new_row["horizon_minutes"] = horizon_minutes_from_strings(
                new_row.get("captured_at_local"),
                new_row.get("valid_time"),
            )
        if not new_row.get("payload_hash"):
            new_row["payload_hash"] = payload_hash(new_row)
        if not new_row.get("is_changed"):
            new_row["is_changed"] = "unknown"
        migrated.append(new_row)
    write_rows(path, columns, migrated)


def infer_event_slug(path):
    try:
        return Path(path).parent.name
    except Exception:
        return ""


def horizon_minutes_from_strings(captured_at, valid_time):
    if not captured_at or not valid_time or "T" not in str(valid_time):
        return ""
    try:
        captured_dt = datetime.fromisoformat(str(captured_at)).astimezone(TORONTO_TZ)
        return horizon_minutes(captured_dt, valid_time)
    except ValueError:
        return ""


def write_rows(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_rows(path, columns, rows):
    if not rows:
        return
    path = Path(path)
    migrate_csv_schema(path, columns)
    write_header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def backfill_eccc_from_snapshots(snapshot_folder):
    folder = Path(snapshot_folder)
    snapshots_path = folder / "snapshots_long.csv"
    forecasts_path = folder / "forecasts_long.csv"
    if not snapshots_path.exists():
        return 0
    migrate_csv_schema(forecasts_path, FORECAST_COLUMNS)
    existing_hashes = set()
    if forecasts_path.exists():
        with forecasts_path.open("r", encoding="utf-8", newline="") as handle:
            existing_hashes = {row.get("payload_hash") for row in csv.DictReader(handle)}

    rows = []
    with snapshots_path.open("r", encoding="utf-8", newline="") as handle:
        for snapshot in csv.DictReader(handle):
            if snapshot.get("range_label") != first_band_label(snapshots_path, snapshot.get("snapshot_id")):
                continue
            high = snapshot.get("eccc_forecast_high_c")
            if high in (None, "", "nan"):
                continue
            captured_local = snapshot.get("captured_at_local", "")
            captured_at = parse_datetime(captured_local)
            if captured_at is None:
                continue
            target_date = (
                date_from_event_slug(snapshot.get("event_slug") or folder.name)
                or captured_at.date()
            )
            row = forecast_row(
                snapshot_id=snapshot.get("snapshot_id"),
                captured_at_utc=snapshot.get("captured_at_utc"),
                captured_at_local=captured_local,
                event_slug=snapshot.get("event_slug") or folder.name,
                source="eccc_citypage",
                forecast_kind="daily_high",
                issue_time=captured_local,
                issue_time_basis="legacy_snapshot",
                valid_time=target_date.isoformat(),
                captured_at=captured_at,
                target_temp_c=high,
                forecast_high_c=high,
                cloud_cover=None,
                wind_speed_kmh=None,
                condition="legacy snapshot high",
                source_url="",
            )
            if row["payload_hash"] in existing_hashes:
                continue
            row["is_changed"] = "true"
            existing_hashes.add(row["payload_hash"])
            rows.append(row)
    append_rows(forecasts_path, FORECAST_COLUMNS, rows)
    return len(rows)


def first_band_label(snapshots_path, snapshot_id):
    with Path(snapshots_path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("snapshot_id") == snapshot_id:
                return row.get("range_label")
    return None


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(TORONTO_TZ)
    except ValueError:
        return None


def analyze_forecast_archive(snapshot_folder, data_root=DEFAULT_DATA_ROOT):
    folder = Path(snapshot_folder)
    forecasts_path = folder / "forecasts_long.csv"
    if not forecasts_path.exists():
        raise FileNotFoundError(f"No forecasts_long.csv found at {forecasts_path}")
    migrate_csv_schema(forecasts_path, FORECAST_COLUMNS)
    rows = read_forecasts(forecasts_path)
    final_highs, final_basis = load_final_highs(data_root, folder)
    scored = score_forecasts(rows, final_highs, final_basis)
    report_path = folder / "forecast_bias_report.md"
    json_path = folder / "forecast_bias_report.json"
    summary = summarize_scored_forecasts(scored)
    report_path.write_text(build_bias_report(folder, rows, scored, summary), encoding="utf-8")
    json_path.write_text(json.dumps({"summary": summary, "scored_rows": scored}, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "rows": len(rows),
        "scored_rows": len(scored),
        "report_path": str(report_path),
        "json_path": str(json_path),
    }


def read_forecasts(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_final_highs(data_root, snapshot_folder):
    final_highs = {}
    basis = {}
    summary_path = Path(data_root) / "daily" / "daily_summary.csv"
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                high = native_high(row)
                if high is not None:
                    final_highs[row["local_date"]] = high
                    basis[row["local_date"]] = "wu_daily_summary"

    snapshots_path = Path(snapshot_folder) / "snapshots_long.csv"
    if snapshots_path.exists():
        latest_by_date = {}
        with snapshots_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                date_value = row.get("captured_at_local", "")[:10] or TARGET_DATE.isoformat()
                high = to_float(row.get("wu_history_high_c"))
                if high is not None:
                    latest_by_date[date_value] = high
        for date_value, high in latest_by_date.items():
            if date_value not in final_highs:
                final_highs[date_value] = high
                basis[date_value] = "latest_snapshot_wu_history"
            elif high > final_highs[date_value]:
                final_highs[date_value] = high
                basis[date_value] = "wu_daily_summary_plus_latest_snapshot"
    return final_highs, basis


def score_forecasts(rows, final_highs, final_basis):
    scored = []
    for row in rows:
        target_date = row.get("target_date") or target_date_from_valid_time(row.get("valid_time"))
        final_high = final_highs.get(target_date)
        forecast_temp = to_float(row.get("target_temp_c") or row.get("forecast_high_c"))
        if final_high is None or forecast_temp is None:
            continue
        error = forecast_temp - final_high
        scored.append(
            {
                "snapshot_id": row.get("snapshot_id"),
                "source": row.get("source"),
                "forecast_kind": row.get("forecast_kind"),
                "target_date": target_date,
                "valid_time": row.get("valid_time"),
                "horizon_minutes": to_float(row.get("horizon_minutes")),
                "horizon_bucket": horizon_bucket(to_float(row.get("horizon_minutes"))),
                "forecast_temp_c": forecast_temp,
                "final_high_c": final_high,
                "final_high_basis": final_basis.get(target_date),
                "error_c": error,
                "abs_error_c": abs(error),
                "squared_error_c": error * error,
                "bucket_hit": int(round_half_up(forecast_temp) == round_half_up(final_high)),
            }
        )
    return scored


def summarize_scored_forecasts(scored):
    summary = {
        "by_source": summarize_groups(scored, ["source"]),
        "by_source_kind": summarize_groups(scored, ["source", "forecast_kind"]),
        "by_source_horizon": summarize_groups(scored, ["source", "horizon_bucket"]),
    }
    return summary


def summarize_groups(scored, keys):
    grouped = defaultdict(list)
    for row in scored:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    output = []
    for key, rows in sorted(grouped.items()):
        errors = [row["error_c"] for row in rows]
        abs_errors = [row["abs_error_c"] for row in rows]
        squared_errors = [row["squared_error_c"] for row in rows]
        bucket_hits = [row["bucket_hit"] for row in rows]
        item = {name: value for name, value in zip(keys, key)}
        item.update(
            {
                "rows": len(rows),
                "mean_error_c": mean(errors),
                "mae_c": mean(abs_errors),
                "rmse_c": math.sqrt(mean(squared_errors)),
                "bucket_accuracy": mean(bucket_hits),
            }
        )
        output.append(item)
    return output


def build_bias_report(folder, rows, scored, summary):
    lines = [
        "# Forecast Bias And Error Report",
        "",
        f"**Snapshot folder:** `{Path(folder).as_posix()}`  ",
        f"**Generated:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  ",
        f"**Archived forecast rows:** {len(rows)}  ",
        f"**Scored forecast rows:** {len(scored)}",
        "",
        "## Method",
        "",
        (
            "Rows are scored when a target date has a WU final high in "
            "`daily_summary.csv`; the latest WU history high in the snapshot "
            "tape is used when the local daily summary is missing or trails "
            "the live snapshot high."
        ),
        "",
        "Forecast error is `forecast temperature - WU final high`.",
        "",
        "## By Source",
        "",
        markdown_table(
            ["Source", "Rows", "Mean Error", "MAE", "RMSE", "Bucket Accuracy"],
            [
                [
                    item.get("source"),
                    item["rows"],
                    fmt_temp_delta(item["mean_error_c"]),
                    fmt_temp(item["mae_c"]),
                    fmt_temp(item["rmse_c"]),
                    fmt_pct(item["bucket_accuracy"]),
                ]
                for item in summary["by_source"]
            ],
        ),
        "",
        "## By Source And Kind",
        "",
        markdown_table(
            ["Source", "Kind", "Rows", "Mean Error", "MAE", "RMSE", "Bucket Accuracy"],
            [
                [
                    item.get("source"),
                    item.get("forecast_kind"),
                    item["rows"],
                    fmt_temp_delta(item["mean_error_c"]),
                    fmt_temp(item["mae_c"]),
                    fmt_temp(item["rmse_c"]),
                    fmt_pct(item["bucket_accuracy"]),
                ]
                for item in summary["by_source_kind"]
            ],
        ),
        "",
        "## By Horizon",
        "",
        markdown_table(
            ["Source", "Horizon", "Rows", "Mean Error", "MAE", "RMSE", "Bucket Accuracy"],
            [
                [
                    item.get("source"),
                    item.get("horizon_bucket"),
                    item["rows"],
                    fmt_temp_delta(item["mean_error_c"]),
                    fmt_temp(item["mae_c"]),
                    fmt_temp(item["rmse_c"]),
                    fmt_pct(item["bucket_accuracy"]),
                ]
                for item in summary["by_source_horizon"]
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def horizon_bucket(value):
    if value is None:
        return "unknown"
    if value < 0:
        return "expired"
    if value <= 60:
        return "0-1h"
    if value <= 180:
        return "1-3h"
    if value <= 360:
        return "3-6h"
    return "6h+"


def to_float(value):
    if value in (None, "", "nan"):
        return None
    try:
        if isinstance(value, str) and value.lower() == "nan":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def fmt_temp(value):
    return "-" if value is None else f"{float(value):.2f} C"


def fmt_temp_delta(value):
    return "-" if value is None else f"{float(value):+.2f} C"


def fmt_pct(value):
    return "-" if value is None else f"{float(value) * 100:.1f}%"


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description="Manage and analyze forecast snapshot archives.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("snapshot_folder")

    backfill = subparsers.add_parser("backfill-eccc")
    backfill.add_argument("snapshot_folder")

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("snapshot_folder")
    analyze.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    folder = Path(args.snapshot_folder)
    if args.command == "migrate":
        migrate_csv_schema(folder / "forecasts_long.csv", FORECAST_COLUMNS)
        print(f"Migrated {folder / 'forecasts_long.csv'}")
        return 0
    if args.command == "backfill-eccc":
        count = backfill_eccc_from_snapshots(folder)
        print(f"Backfilled {count} ECCC forecast rows")
        return 0
    if args.command == "analyze":
        result = analyze_forecast_archive(folder, Path(args.data_root))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
