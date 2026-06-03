"""WU settlement lag and catch-up model.

WU/Weather.com history is the settlement proxy. Other observations can lead it,
but they should only move probability through a learned catch-up rate, never a
hard floor. This module trains that catch-up artifact from historical METAR vs
WU hourly rows and from settled snapshot tapes that include SWOB/current highs.
"""
import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    parse_snapshot_time,
    safe_float,
    settlement_for_tape,
)
from forecast_error_model import load_daily_summary  # noqa: E402
from market_config import date_from_event_slug  # noqa: E402


DEFAULT_ARTIFACT_PATH = Path("src") / "settlement_lag_model.json"
DEFAULT_REPORT_PATH = Path("data") / "backtest" / "settlement_lag_report.md"
DEFAULT_WU_ROOT = Path("data") / "wunderground" / "cyyz" / "hourly"
DEFAULT_METAR_ROOT = Path("data") / "metar" / "cyyz" / "hourly"
DEFAULT_SETTLED_SLUGS = (
    "highest-temperature-in-toronto-on-may-27-2026",
    "highest-temperature-in-toronto-on-may-28-2026",
    "highest-temperature-in-toronto-on-may-30-2026",
)
CUTOFF_HOURS = tuple(range(8, 21))
SEASON_START = (5, 10)
SEASON_END = (6, 15)


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def in_season_window(date_iso):
    month_day = (int(date_iso[5:7]), int(date_iso[8:10]))
    return SEASON_START <= month_day <= SEASON_END


def load_jsonl_hourly(root):
    rows_by_date = defaultdict(list)
    root = Path(root)
    if not root.exists():
        return rows_by_date
    for path in root.glob("year=*/**/observations.jsonl"):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                local_date = row.get("local_date")
                temp = safe_float(row.get("temp_c"))
                minute = row.get("minute_of_day")
                if minute is None:
                    minute = minute_of_day(row.get("local_time") or row.get("time"))
                if not local_date or temp is None or minute is None:
                    continue
                if not in_season_window(local_date):
                    continue
                rows_by_date[local_date].append({
                    "minute_of_day": int(minute),
                    "temp_c": temp,
                })
    for rows in rows_by_date.values():
        rows.sort(key=lambda row: row["minute_of_day"])
    return rows_by_date


def minute_of_day(value):
    if not value or ":" not in str(value):
        return None
    try:
        hour, minute = str(value)[:5].split(":")
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def high_until(rows, cutoff_minute):
    eligible = [
        row for row in rows
        if row["minute_of_day"] <= cutoff_minute and row.get("temp_c") is not None
    ]
    if not eligible:
        return None, None
    high = max(row["temp_c"] for row in eligible)
    bucket = round_half_up(high)
    return high, bucket


def first_reach_minute(rows, bucket):
    if bucket is None:
        return None
    for row in rows:
        if round_half_up(row.get("temp_c")) is not None and round_half_up(row["temp_c"]) >= bucket:
            return row["minute_of_day"]
    return None


def lead_row(source, target_date, cutoff_hour, source_bucket, wu_floor_bucket, final_bucket, source_rows, wu_rows):
    if source_bucket is None or wu_floor_bucket is None or final_bucket is None:
        return None
    if source_bucket <= wu_floor_bucket:
        return None
    caught_up = int(final_bucket >= source_bucket)
    source_first = first_reach_minute(source_rows, source_bucket)
    wu_first = first_reach_minute(wu_rows, source_bucket)
    lag_minutes = None
    if caught_up and source_first is not None and wu_first is not None:
        lag_minutes = wu_first - source_first
    return {
        "source": source,
        "target_date": target_date,
        "cutoff_hour": cutoff_hour,
        "source_bucket": int(source_bucket),
        "wu_floor_bucket": int(wu_floor_bucket),
        "gap": int(source_bucket - wu_floor_bucket),
        "final_bucket": int(final_bucket),
        "caught_up": caught_up,
        "lag_minutes": lag_minutes,
        "row_kind": "lead",
    }


def revision_row(target_date, cutoff_hour, wu_floor_bucket, final_bucket):
    if wu_floor_bucket is None or final_bucket is None:
        return None
    return {
        "target_date": target_date,
        "cutoff_hour": cutoff_hour,
        "wu_floor_bucket": int(wu_floor_bucket),
        "final_bucket": int(final_bucket),
        "revised_up": int(final_bucket > wu_floor_bucket),
        "revision_gap": int(final_bucket - wu_floor_bucket),
        "row_kind": "revision",
    }


def rows_from_metar_history(wu_rows_by_date, metar_rows_by_date, daily_summary):
    rows = []
    for target_date, wu_rows in wu_rows_by_date.items():
        final = daily_summary.get(target_date)
        metar_rows = metar_rows_by_date.get(target_date)
        if not final or not metar_rows:
            continue
        final_bucket = final["bucket"]
        for cutoff_hour in CUTOFF_HOURS:
            cutoff_minute = cutoff_hour * 60
            _, wu_bucket = high_until(wu_rows, cutoff_minute)
            _, metar_bucket = high_until(metar_rows, cutoff_minute)
            revision = revision_row(target_date, cutoff_hour, wu_bucket, final_bucket)
            if revision:
                rows.append(revision)
            lead = lead_row(
                "metar",
                target_date,
                cutoff_hour,
                metar_bucket,
                wu_bucket,
                final_bucket,
                metar_rows,
                wu_rows,
            )
            if lead:
                rows.append(lead)
    return rows


def rows_from_snapshot_folders(folders, daily_summary):
    try:
        import pandas as pd
    except Exception:
        return []
    daily_index = {
        day: (row["bucket"], row["row_count"])
        for day, row in daily_summary.items()
    }
    rows = []
    for folder in folders:
        folder = Path(folder)
        tape = folder / "snapshots_long.csv"
        if not tape.exists():
            continue
        frame = pd.read_csv(tape)
        target_date = date_from_event_slug(folder.name)
        if not target_date:
            continue
        final_bucket, _, _ = settlement_for_tape(frame, target_date, daily_index, {})
        if final_bucket is None:
            continue
        seen_snapshots = set()
        for _, row in frame.iterrows():
            snapshot_id = row.get("snapshot_id")
            if snapshot_id in seen_snapshots:
                continue
            seen_snapshots.add(snapshot_id)
            captured = parse_snapshot_time(row.get("captured_at_local"))
            cutoff_hour = captured.hour if captured else None
            wu_bucket = round_half_up(row.get("wu_history_high_c"))
            if cutoff_hour is not None:
                revision = revision_row(target_date.isoformat(), cutoff_hour, wu_bucket, final_bucket)
                if revision:
                    rows.append(revision)
            source_specs = (
                ("eccc_swob", row.get("eccc_swob_max_c")),
                ("weather_current", row.get("wu_max_since_7am_c")),
            )
            for source, value in source_specs:
                source_bucket = round_half_up(value)
                lead = lead_row(
                    source,
                    target_date.isoformat(),
                    cutoff_hour,
                    source_bucket,
                    wu_bucket,
                    final_bucket,
                    [{"minute_of_day": (cutoff_hour or 0) * 60, "temp_c": safe_float(value)}],
                    [{"minute_of_day": (cutoff_hour or 0) * 60, "temp_c": safe_float(row.get("wu_history_high_c"))}],
                )
                if lead:
                    rows.append(lead)
    return rows


def smoothed_rate(positives, n, alpha=2.0, prior=0.5):
    if n <= 0:
        return prior
    return (positives + alpha * prior) / (n + alpha)


def context_keys(source, cutoff_hour, gap):
    source = source or "unknown"
    hour = str(cutoff_hour) if cutoff_hour is not None else "unknown"
    gap_bucket = "3_plus" if gap is not None and int(gap) >= 3 else str(gap or "unknown")
    return [
        f"source={source}|hour={hour}|gap={gap_bucket}",
        f"source={source}|gap={gap_bucket}",
        f"source={source}|hour={hour}",
        f"source={source}",
        "global",
    ]


def summarize_leads(rows):
    lead_rows = [row for row in rows if row.get("row_kind") == "lead"]
    grouped = defaultdict(list)
    for row in lead_rows:
        for key in context_keys(row["source"], row.get("cutoff_hour"), row.get("gap")):
            grouped[key].append(row)
    contexts = {}
    for key, group in grouped.items():
        n = len(group)
        positives = sum(row["caught_up"] for row in group)
        lags = [
            row["lag_minutes"] for row in group
            if row.get("lag_minutes") is not None
        ]
        contexts[key] = {
            "n": n,
            "catchup_rate": smoothed_rate(positives, n, prior=0.70),
            "raw_catchup_rate": positives / n if n else None,
            "mean_lag_minutes": sum(lags) / len(lags) if lags else None,
            "median_lag_minutes": statistics.median(lags) if lags else None,
        }
    return dict(sorted(contexts.items()))


def summarize_revisions(rows):
    revision_rows = [row for row in rows if row.get("row_kind") == "revision"]
    grouped = defaultdict(list)
    for row in revision_rows:
        grouped[f"hour={row['cutoff_hour']}"].append(row)
    contexts = {}
    for key, group in grouped.items():
        n = len(group)
        positives = sum(row["revised_up"] for row in group)
        gaps = [max(0, row["revision_gap"]) for row in group]
        contexts[key] = {
            "n": n,
            "revision_up_rate": smoothed_rate(positives, n, prior=0.50),
            "raw_revision_up_rate": positives / n if n else None,
            "mean_positive_revision_gap": (
                sum(gap for gap in gaps if gap > 0) / sum(1 for gap in gaps if gap > 0)
                if any(gap > 0 for gap in gaps) else 0.0
            ),
        }
    return dict(sorted(contexts.items()))


def settlement_catchup_probability(
    artifact,
    source,
    source_bucket,
    wu_floor_bucket,
    cutoff_hour=None,
):
    if not artifact or source_bucket is None or wu_floor_bucket is None:
        return None
    if source_bucket <= wu_floor_bucket:
        return 1.0
    cfg = artifact.get("component") or {}
    contexts = artifact.get("catchup_contexts") or {}
    min_n = int(cfg.get("min_context_n", 20))
    gap = int(source_bucket) - int(wu_floor_bucket)
    for key in context_keys(source, cutoff_hour, gap):
        row = contexts.get(key)
        if row and int(row.get("n", 0)) >= min_n:
            return float(row["catchup_rate"])
    row = contexts.get("global")
    if row:
        return float(row["catchup_rate"])
    return None


def build_artifact(rows, folders):
    lead_rows = [row for row in rows if row.get("row_kind") == "lead"]
    revision_rows = [row for row in rows if row.get("row_kind") == "revision"]
    artifact = {
        "version": "v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "training": {
            "rows": len(rows),
            "lead_rows": len(lead_rows),
            "revision_rows": len(revision_rows),
            "sources": sorted({row["source"] for row in lead_rows}),
            "snapshot_folders": [str(Path(folder)) for folder in folders],
        },
        "component": {
            "enabled": True,
            "min_context_n": 20,
            "default_source": "eccc_swob",
        },
        "catchup_contexts": summarize_leads(rows),
        "revision_contexts": summarize_revisions(rows),
    }
    return artifact


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    root = Path(root)
    return [
        root / slug for slug in DEFAULT_SETTLED_SLUGS
        if (root / slug / "snapshots_long.csv").exists()
    ]


def read_training_rows(wu_root, metar_root, daily_summary_path, folders):
    daily_summary = load_daily_summary(daily_summary_path)
    wu_rows = load_jsonl_hourly(wu_root)
    metar_rows = load_jsonl_hourly(metar_root)
    rows = rows_from_metar_history(wu_rows, metar_rows, daily_summary)
    rows.extend(rows_from_snapshot_folders(folders or [], daily_summary))
    return rows


def fmt_num(value, decimals=3):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def write_report(path, artifact):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    training = artifact["training"]
    lines = [
        "# Settlement Lag Report",
        "",
        f"Generated: {artifact['generated_at_utc']}",
        "",
        "## Scope",
        "",
        f"- Training rows: {training['rows']}",
        f"- Lead rows: {training['lead_rows']}",
        f"- Revision rows: {training['revision_rows']}",
        f"- Sources: {', '.join(training['sources'])}",
        "",
        "## Catch-Up Contexts",
        "",
        "| Context | N | Catch-up rate | Mean lag min | Median lag min |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for key, row in artifact["catchup_contexts"].items():
        if key == "global" or row["n"] >= artifact["component"]["min_context_n"]:
            lines.append(
                f"| {key} | {row['n']} | {fmt_pct(row['catchup_rate'])} | "
                f"{fmt_num(row.get('mean_lag_minutes'), 1)} | "
                f"{fmt_num(row.get('median_lag_minutes'), 1)} |"
            )
    lines.extend([
        "",
        "## WU Revision Contexts",
        "",
        "| Context | N | Revision-up rate | Mean positive gap |",
        "| :--- | ---: | ---: | ---: |",
    ])
    for key, row in artifact["revision_contexts"].items():
        lines.append(
            f"| {key} | {row['n']} | {fmt_pct(row['revision_up_rate'])} | "
            f"{fmt_num(row.get('mean_positive_revision_gap'), 2)} |"
        )
    lines.extend([
        "",
        "## Live Use",
        "",
        "WU history remains the only hard settlement floor. When SWOB leads WU, "
        "live inference uses the learned catch-up rate to decide how strongly "
        "to suppress buckets below the SWOB-observed bucket.",
        "",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_settlement_lag_model(path=DEFAULT_ARTIFACT_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error loading settlement lag model artifact: {exc}")
        return None


def cmd_train(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    rows = read_training_rows(args.wu_root, args.metar_root, args.daily_summary, folders)
    if not rows:
        raise SystemExit("No settlement lag training rows found.")
    artifact = build_artifact(rows, folders)
    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    write_report(args.report, artifact)
    global_context = artifact["catchup_contexts"].get("global", {})
    print(f"Wrote settlement lag artifact to {artifact_path}")
    print(f"Wrote settlement lag report to {args.report}")
    print(
        f"Lead rows {artifact['training']['lead_rows']}; "
        f"global catch-up {global_context.get('catchup_rate', 0.0) * 100:.1f}%"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Train WU settlement lag artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("folders", nargs="*", help="Settled snapshot folders to add to lag training.")
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    train.add_argument("--wu-root", default=str(DEFAULT_WU_ROOT))
    train.add_argument("--metar-root", default=str(DEFAULT_METAR_ROOT))
    train.add_argument("--artifact", default=str(DEFAULT_ARTIFACT_PATH))
    train.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    train.set_defaults(func=cmd_train)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
