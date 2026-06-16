"""Recent model-performance history for the Streamlit dashboard."""

from __future__ import annotations

import json
import math
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from weather.paths import data_path

import pandas as pd

from weather.backtesting.tape_scoring import last_pre_close_rows
from weather.scoring.metrics import (
    daily_first_score,
    score_rows,
    winner_band_catchup,
)
from weather.backtesting.settlement_ledger import (
    band_value_hi,
    clean_temperature_label,
    ledger_label_for_slug,
    parse_band_label,
    resolve_outcome,
)
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.model_constants import TORONTO_TZ


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LABELS_CSV = data_path() / "backtest" / "market_day_labels.csv"
DEFAULT_HISTORY_CACHE = data_path() / "backtest" / "model_history_cache.json"
MODEL_HISTORY_CACHE_SCHEMA = "model_history_cache_v0.2"


def safe_float(value):
    if value in (None, "", "-"):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def safe_int(value):
    number = safe_float(value)
    return int(number) if number is not None else None


def fmt_pct(value, digits=1):
    number = safe_float(value)
    return "-" if number is None else f"{number * 100:.{digits}f}%"


def fmt_signed_pct(value, digits=1):
    number = safe_float(value)
    return "-" if number is None else f"{number * 100:+.{digits}f}%"


def fmt_score(value, digits=4):
    number = safe_float(value)
    return "-" if number is None else f"{number:.{digits}f}"


def fmt_signed(value, digits=4):
    number = safe_float(value)
    return "-" if number is None else f"{number:+.{digits}f}"


def recent_completed_dates(as_of=None, days=3):
    """Last ``days`` completed target dates, excluding the current app date."""
    as_of = as_of or datetime.now(TORONTO_TZ)
    if isinstance(as_of, datetime):
        current = as_of.date()
    elif isinstance(as_of, date):
        current = as_of
    else:
        current = datetime.fromisoformat(str(as_of)).date()
    return [current - timedelta(days=offset) for offset in range(days, 0, -1)]


def _clean_label(label):
    cleaned = clean_temperature_label(label)
    return cleaned.replace("Â", "").strip()


def _read_folder_label(folder):
    path = Path(folder) / "settlement.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_label_index(path=DEFAULT_LABELS_CSV):
    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                event_slug = row.get("event_slug")
                if event_slug:
                    rows[event_slug] = row
    except OSError:
        return {}
    return rows


def load_label(event_slug, folder, label_index=None):
    if label_index and event_slug in label_index:
        return label_index[event_slug]
    return ledger_label_for_slug(event_slug) or _read_folder_label(folder) or {}


def _file_signature(path):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def history_signature(root, selected_dates, specs, labels_csv=DEFAULT_LABELS_CSV):
    root = Path(root)
    files = [_file_signature(labels_csv)]
    for target_date in selected_dates:
        for spec in specs:
            folder = root / event_slug_for_date(target_date, spec.id)
            files.append(_file_signature(folder / "snapshots_long.csv"))
            files.append(_file_signature(folder / "settlement.json"))
    return {
        "schema_version": MODEL_HISTORY_CACHE_SCHEMA,
        "root": str(root.resolve()) if root.exists() else str(root),
        "dates": [item.isoformat() for item in selected_dates],
        "market_ids": [spec.id for spec in specs],
        "files": files,
    }


def _read_history_cache(path, signature):
    path = Path(path)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if cached.get("signature") != signature:
        return None
    payload = cached.get("payload")
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    payload["cache"] = {
        "hit": True,
        "path": str(path),
        "generated_at": cached.get("generated_at"),
    }
    return payload


def _write_history_cache(path, signature, payload):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "generated_at": datetime.now(TORONTO_TZ).isoformat(),
            "signature": signature,
            "payload": payload,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(record, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True


def _timestamp_series(frame, spec):
    if "captured_at_utc" in frame:
        parsed = pd.to_datetime(frame["captured_at_utc"], errors="coerce", utc=True)
        return parsed.dt.tz_convert(spec.timezone)
    if "captured_at_local" in frame:
        return pd.to_datetime(frame["captured_at_local"], errors="coerce")
    return pd.Series([pd.NaT] * len(frame), index=frame.index)


def _prepared_frame(frame, spec):
    prepared = frame.copy()
    prepared["_row_order"] = range(len(prepared))
    prepared["_captured_at_market"] = _timestamp_series(prepared, spec)
    prepared["_model_probability"] = (
        pd.to_numeric(prepared["model_probability"], errors="coerce")
        if "model_probability" in prepared
        else pd.Series([math.nan] * len(prepared), index=prepared.index)
    )
    prepared["_market_yes"] = (
        pd.to_numeric(prepared["market_yes"], errors="coerce")
        if "market_yes" in prepared
        else pd.Series([math.nan] * len(prepared), index=prepared.index)
    )
    return prepared


def _row_band(row):
    parsed = parse_band_label(row.get("range_label"))
    kind = row.get("bin_kind") or parsed["kind"]
    value = safe_int(row.get("bin_value_c"))
    if value is None:
        value = parsed["value"]
    value_hi = band_value_hi(row.get("range_label"), value)
    return kind, value, value_hi


def _row_outcome(row, settlement_bucket):
    kind, value, value_hi = _row_band(row)
    result = resolve_outcome(kind, value, settlement_bucket, value_hi)
    if result is None:
        return None
    return int(bool(result))


def _bin_type(kind):
    if kind == "lte":
        return "lte"
    if kind == "gte":
        return "gte"
    return "eq"


def scoring_rows(frame, settlement_bucket, target_date):
    rows = []
    target_date_value = target_date.isoformat() if target_date else None
    for _, row in frame.iterrows():
        model_probability = safe_float(row.get("_model_probability"))
        market_yes = safe_float(row.get("_market_yes"))
        if model_probability is None or market_yes is None:
            continue
        outcome = _row_outcome(row, settlement_bucket)
        if outcome is None:
            continue
        captured = row.get("_captured_at_market")
        capture_minute = None
        captured_iso = None
        if not pd.isna(captured):
            capture_minute = int(captured.hour) * 60 + int(captured.minute)
            captured_iso = captured.isoformat()
        kind, value, _value_hi = _row_band(row)
        rows.append(
            {
                "row_order": int(row.get("_row_order") or 0),
                "snapshot_id": row.get("snapshot_id"),
                "target_date": target_date_value,
                "event_slug": row.get("event_slug"),
                "captured_at_local": captured_iso,
                "capture_minute": capture_minute,
                "cutoff_hour": capture_minute // 60 if capture_minute is not None else None,
                "model_version": row.get("model_version"),
                "market_id": row.get("_market_id"),
                "city": row.get("_city"),
                "band": _clean_label(row.get("range_label")),
                "bin_kind": kind,
                "bin_type": _bin_type(kind),
                "bin_value_c": safe_float(value),
                "model_probability": model_probability,
                "market_yes": market_yes,
                "market_no": safe_float(row.get("market_no")),
                "outcome": outcome,
            }
        )
    return rows


def _time_sort_key(row):
    captured = row.get("_captured_at_market")
    return (_timestamp_sort_value(captured), int(row.get("_row_order") or 0))


def _timestamp_sort_value(timestamp):
    if timestamp is None or pd.isna(timestamp):
        return float("inf")
    return timestamp.timestamp()


def _time_label(timestamp, target_date=None):
    if timestamp is None or pd.isna(timestamp):
        return None
    prefix = ""
    if target_date is not None and timestamp.date() != target_date:
        prefix = f"{timestamp.strftime('%b')} {timestamp.day} "
    return prefix + timestamp.strftime("%H:%M %Z").strip()


def _minutes_between(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    return round((b - a).total_seconds() / 60.0, 1)


def _snapshot_top_rows(frame, settlement_bucket):
    rows = []
    group_key = "snapshot_id" if "snapshot_id" in frame else "_row_order"
    for _, group in frame.groupby(group_key, sort=False):
        group = group.sort_values(["_captured_at_market", "_row_order"])
        if not group["_model_probability"].notna().any():
            continue
        top_idx = group["_model_probability"].idxmax()
        top = group.loc[top_idx]
        rows.append(
            {
                "captured_at": top.get("_captured_at_market"),
                "label": _clean_label(top.get("range_label")),
                "probability": safe_float(top.get("_model_probability")),
                "is_winner": _row_outcome(top, settlement_bucket) == 1,
            }
        )
    return sorted(
        rows,
        key=lambda row: _timestamp_sort_value(row.get("captured_at")),
    )


def winning_bucket_stats(frame, settlement_bucket, target_date):
    if settlement_bucket is None:
        return {}
    winner_rows = []
    for _, row in frame.iterrows():
        if _row_outcome(row, settlement_bucket) == 1:
            winner_rows.append(row)
    if not winner_rows:
        return {}
    winner_rows = sorted(winner_rows, key=_time_sort_key)
    first_row = winner_rows[0]
    first_capture = first_row.get("_captured_at_market")
    winner_label = _clean_label(first_row.get("range_label"))

    first_over_50 = next(
        (
            row
            for row in winner_rows
            if (safe_float(row.get("_model_probability")) or 0.0) > 0.5
        ),
        None,
    )
    first_market_over_50 = next(
        (row for row in winner_rows if (safe_float(row.get("_market_yes")) or 0.0) > 0.5),
        None,
    )
    max_row = max(
        winner_rows,
        key=lambda row: safe_float(row.get("_model_probability")) or float("-inf"),
    )
    final_row = winner_rows[-1]
    top_rows = _snapshot_top_rows(frame, settlement_bucket)
    first_top = next((row for row in top_rows if row["is_winner"]), None)

    first_over_time = first_over_50.get("_captured_at_market") if first_over_50 is not None else None
    market_over_time = (
        first_market_over_50.get("_captured_at_market")
        if first_market_over_50 is not None
        else None
    )
    max_time = max_row.get("_captured_at_market")
    final_probability = safe_float(final_row.get("_model_probability"))
    final_market = safe_float(final_row.get("_market_yes"))

    return {
        "winning_band": winner_label,
        "winning_first_capture": _time_label(first_capture, target_date),
        "winning_first_probability": safe_float(first_row.get("_model_probability")),
        "winning_first_over_50_time": _time_label(first_over_time, target_date),
        "winning_first_over_50_iso": (
            first_over_time.isoformat() if first_over_time is not None and not pd.isna(first_over_time) else None
        ),
        "winning_minutes_to_50": _minutes_between(first_capture, first_over_time),
        "market_first_over_50_time": _time_label(market_over_time, target_date),
        "model_vs_market_50_minutes": _minutes_between(first_over_time, market_over_time),
        "winning_first_top_time": _time_label(
            first_top.get("captured_at") if first_top else None,
            target_date,
        ),
        "winning_max_probability": safe_float(max_row.get("_model_probability")),
        "winning_max_probability_time": _time_label(max_time, target_date),
        "winning_mean_probability": sum(
            safe_float(row.get("_model_probability")) or 0.0 for row in winner_rows
        )
        / len(winner_rows),
        "winning_final_probability": final_probability,
        "winning_final_market_price": final_market,
        "winning_final_edge": (
            final_probability - final_market
            if final_probability is not None and final_market is not None
            else None
        ),
        "winner_crossed_50": first_over_50 is not None,
    }


def final_top_stats(frame, settlement_bucket, target_date):
    if frame.empty:
        return {}
    top_rows = _snapshot_top_rows(frame, settlement_bucket)
    if not top_rows:
        return {}
    final = top_rows[-1]
    return {
        "final_top_bucket": final["label"],
        "final_top_probability": final["probability"],
        "final_top_was_winner": bool(final["is_winner"]),
        "final_snapshot_time": _time_label(final["captured_at"], target_date),
    }


def _status_summary(status):
    labels = {
        "scored": "Scored",
        "missing_tape": "Missing tape",
        "missing_settlement": "No settlement",
        "read_error": "Read error",
        "no_scored_rows": "No scored rows",
    }
    return labels.get(status, status or "-")


def summarize_market_day(folder, spec, target_date, label_index=None):
    folder = Path(folder)
    event_slug = event_slug_for_date(target_date, spec.id)
    row = {
        "market_id": spec.id,
        "city": spec.city_label,
        "target_date": target_date.isoformat(),
        "unit": spec.display_unit,
        "event_slug": event_slug,
        "folder": str(folder),
        "status": "missing_tape",
        "status_label": _status_summary("missing_tape"),
        "quality_grade": "-",
        "settlement_bucket": None,
        "winning_band": None,
        "snapshot_count": 0,
        "band_count": 0,
        "scored_rows": 0,
        "note": "",
    }
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return row, []
    try:
        frame = pd.read_csv(tape)
    except Exception as exc:  # noqa: BLE001 - page should show the bad artifact
        row.update({"status": "read_error", "status_label": _status_summary("read_error"), "note": str(exc)})
        return row, []

    frame = _prepared_frame(frame, spec)
    frame["_market_id"] = spec.id
    frame["_city"] = spec.city_label
    row["snapshot_count"] = int(frame["snapshot_id"].nunique()) if "snapshot_id" in frame else 0
    row["band_count"] = int(frame["range_label"].nunique()) if "range_label" in frame else 0

    label = load_label(event_slug, folder, label_index=label_index)
    settlement_bucket = safe_int(label.get("settlement_bucket"))
    row.update(
        {
            "quality_grade": label.get("quality_grade") or "-",
            "settlement_bucket": settlement_bucket,
            "settlement_display": (
                f"{settlement_bucket} {spec.display_unit}" if settlement_bucket is not None else "-"
            ),
            "winning_band": _clean_label(label.get("winning_band") or ""),
            "coverage_clean": label.get("coverage_clean"),
            "capture_ratio": safe_float(label.get("capture_ratio")),
            "max_gap_minutes": safe_float(label.get("max_gap_minutes")),
            "settlement_source": label.get("settlement_source") or "-",
            "note": label.get("quality_reason") or label.get("note") or "",
        }
    )
    if settlement_bucket is None:
        row.update({"status": "missing_settlement", "status_label": _status_summary("missing_settlement")})
        return row, []

    rows = scoring_rows(frame, settlement_bucket, target_date)
    row["scored_rows"] = len(rows)
    if not rows:
        row.update({"status": "no_scored_rows", "status_label": _status_summary("no_scored_rows")})
        return row, []

    score = score_rows(rows) or {}
    last_score = score_rows(last_pre_close_rows(rows)) or {}
    catchup = winner_band_catchup(rows)
    row.update(
        {
            "status": "scored",
            "status_label": _status_summary("scored"),
            "model_brier": score.get("model_brier"),
            "market_brier": score.get("market_brier"),
            "n": score.get("n"),
            "base_rate": score.get("base_rate"),
            "brier_delta": score.get("brier_delta"),
            "brier_skill_score": score.get("brier_skill_score"),
            "model_logloss": score.get("model_logloss"),
            "market_logloss": score.get("market_logloss"),
            "logloss_delta": score.get("logloss_delta"),
            "last_model_brier": last_score.get("model_brier"),
            "last_market_brier": last_score.get("market_brier"),
            "last_brier_skill_score": last_score.get("brier_skill_score"),
            "last_logloss_delta": last_score.get("logloss_delta"),
        }
    )
    row.update(catchup)
    row.update(winning_bucket_stats(frame, settlement_bucket, target_date))
    row.update(final_top_stats(frame, settlement_bucket, target_date))
    if not row.get("winning_band"):
        row["winning_band"] = row.get("winning_band") or "-"
    return row, rows


def _group_score_rows(scoring_rows_all, day_rows, key, label_key):
    grouped_rows = defaultdict(list)
    for row in scoring_rows_all:
        grouped_rows[row.get(key)].append(row)

    output = []
    for group, rows in sorted(grouped_rows.items(), key=lambda item: str(item[0])):
        score = score_rows(rows) or {}
        catchup = winner_band_catchup(rows)
        matching_days = [day for day in day_rows if day.get(key) == group and day.get("status") == "scored"]
        crossed = sum(1 for day in matching_days if day.get("winner_crossed_50"))
        final_hits = sum(1 for day in matching_days if day.get("final_top_was_winner"))
        label = matching_days[0].get(label_key) if matching_days else group
        output.append(
            {
                key: group,
                "label": label,
                "market_days": len(matching_days),
                "scored_rows": len(rows),
                "model_brier": score.get("model_brier"),
                "market_brier": score.get("market_brier"),
                "brier_skill_score": score.get("brier_skill_score"),
                "logloss_delta": score.get("logloss_delta"),
                **catchup,
                "winners_crossed_50": crossed,
                "winner_crossed_50_rate": crossed / len(matching_days) if matching_days else None,
                "final_top_hits": final_hits,
                "final_top_hit_rate": final_hits / len(matching_days) if matching_days else None,
            }
        )
    return output


def _group_location_hour_rows(scoring_rows_all, day_rows):
    city_by_market = {
        day.get("market_id"): day.get("city")
        for day in day_rows
        if day.get("market_id") and day.get("city")
    }
    grouped_rows = defaultdict(list)
    for row in scoring_rows_all:
        grouped_rows[(row.get("market_id"), row.get("cutoff_hour"))].append(row)

    output = []
    for (market_id, cutoff_hour), rows in sorted(
        grouped_rows.items(),
        key=lambda item: (str(item[0][0]), -1 if item[0][1] is None else int(item[0][1])),
    ):
        score = score_rows(rows) or {}
        catchup = winner_band_catchup(rows)
        output.append(
            {
                "market_id": market_id,
                "label": city_by_market.get(market_id) or market_id,
                "cutoff_hour": cutoff_hour,
                "scored_rows": len(rows),
                "model_brier": score.get("model_brier"),
                "market_brier": score.get("market_brier"),
                "brier_skill_score": score.get("brier_skill_score"),
                "logloss_delta": score.get("logloss_delta"),
                **catchup,
            }
        )
    return output


def build_history_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    as_of=None,
    days=3,
    dates=None,
    market_ids=None,
    labels_csv=DEFAULT_LABELS_CSV,
    use_cache=False,
    cache_path=DEFAULT_HISTORY_CACHE,
):
    selected_dates = list(dates or recent_completed_dates(as_of=as_of, days=days))
    market_id_set = set(market_ids or [])
    specs = [spec for spec in all_specs() if not market_id_set or spec.id in market_id_set]
    root = Path(snapshots_root)
    signature = history_signature(root, selected_dates, specs, labels_csv=labels_csv)
    if use_cache:
        cached = _read_history_cache(cache_path, signature)
        if cached is not None:
            return cached

    label_index = load_label_index(labels_csv)
    day_rows = []
    all_rows = []

    for target_date in selected_dates:
        for spec in specs:
            folder = root / event_slug_for_date(target_date, spec.id)
            summary, rows = summarize_market_day(
                folder,
                spec,
                target_date,
                label_index=label_index,
            )
            day_rows.append(summary)
            all_rows.extend(rows)

    scored_days = [day for day in day_rows if day.get("status") == "scored"]
    aggregate = score_rows(all_rows) or {}
    last_score = score_rows(last_pre_close_rows(all_rows)) or {}
    daily = daily_first_score([{"score": day} for day in scored_days]) or {}
    catchup = winner_band_catchup(all_rows)
    crossed = sum(1 for day in scored_days if day.get("winner_crossed_50"))
    final_hits = sum(1 for day in scored_days if day.get("final_top_was_winner"))

    overall = {
        "market_days": len(scored_days),
        "locations": len({day["market_id"] for day in scored_days}),
        "scored_rows": len(all_rows),
        "model_brier": aggregate.get("model_brier"),
        "market_brier": aggregate.get("market_brier"),
        "brier_skill_score": aggregate.get("brier_skill_score"),
        "daily_first_brier_skill_score": daily.get("brier_skill_score"),
        "last_pre_close_brier_skill_score": last_score.get("brier_skill_score"),
        "logloss_delta": aggregate.get("logloss_delta"),
        **catchup,
        "winners_crossed_50": crossed,
        "winner_crossed_50_rate": crossed / len(scored_days) if scored_days else None,
        "final_top_hits": final_hits,
        "final_top_hit_rate": final_hits / len(scored_days) if scored_days else None,
    }

    payload = {
        "generated_at": datetime.now(TORONTO_TZ).isoformat(),
        "snapshots_root": str(root),
        "dates": [item.isoformat() for item in selected_dates],
        "days": day_rows,
        "overall": overall,
        "by_location": _group_score_rows(all_rows, scored_days, "market_id", "city"),
        "by_date": _group_score_rows(all_rows, scored_days, "target_date", "target_date"),
        "by_location_hour": _group_location_hour_rows(all_rows, scored_days),
        "cache": {"hit": False, "path": str(cache_path) if use_cache else None},
    }
    if use_cache:
        _write_history_cache(cache_path, signature, payload)
    return payload


def format_day_table(rows):
    table = []
    for row in rows:
        table.append(
            {
                "Date": row.get("target_date"),
                "Location": row.get("city"),
                "Status": row.get("status_label"),
                "Quality": row.get("quality_grade"),
                "Settlement": row.get("settlement_display") or "-",
                "Winner": row.get("winning_band") or "-",
                "Model Brier": fmt_score(row.get("model_brier")),
                "Market Brier": fmt_score(row.get("market_brier")),
                "Brier Skill": fmt_signed_pct(row.get("brier_skill_score")),
                "Winner Catch-Up": fmt_signed_pct(row.get("winner_catchup_gap")),
                "Final Top Hit": "yes" if row.get("final_top_was_winner") else ("no" if row.get("status") == "scored" else "-"),
                "Winner >50": row.get("winning_first_over_50_time") or "never",
                "Winner Model P": fmt_pct(row.get("winner_model_probability")),
                "Winner Market P": fmt_pct(row.get("winner_market_probability")),
                "Winner Max P": fmt_pct(row.get("winning_max_probability")),
                "Winner Final P": fmt_pct(row.get("winning_final_probability")),
                "Final Market": fmt_pct(row.get("winning_final_market_price")),
                "Final Edge": fmt_signed_pct(row.get("winning_final_edge")),
                "Snapshots": row.get("snapshot_count", 0),
                "Max Gap Min": fmt_score(row.get("max_gap_minutes"), digits=1),
            }
        )
    return pd.DataFrame(table)


def format_group_table(rows, group_label):
    table = []
    for row in rows:
        table.append(
            {
                group_label: row.get("label") or row.get(group_label.lower()) or "-",
                "Market Days": row.get("market_days", 0),
                "Rows": row.get("scored_rows", 0),
                "Model Brier": fmt_score(row.get("model_brier")),
                "Market Brier": fmt_score(row.get("market_brier")),
                "Brier Skill": fmt_signed_pct(row.get("brier_skill_score")),
                "Winner Catch-Up": fmt_signed_pct(row.get("winner_catchup_gap")),
                "LogLoss Delta": fmt_signed(row.get("logloss_delta")),
                "Winner Rows": row.get("winner_rows", 0),
                "Winner Model P": fmt_pct(row.get("winner_model_probability")),
                "Winner Market P": fmt_pct(row.get("winner_market_probability")),
                "Winner >50 Rate": fmt_pct(row.get("winner_crossed_50_rate"), digits=0),
                "Final Top Hit Rate": fmt_pct(row.get("final_top_hit_rate"), digits=0),
            }
        )
    return pd.DataFrame(table)


def format_location_hour_table(rows):
    table = []
    for row in rows:
        hour = row.get("cutoff_hour")
        table.append(
            {
                "Location": row.get("label") or row.get("market_id") or "-",
                "Hour": f"{int(hour):02d}:00" if hour is not None else "-",
                "Rows": row.get("scored_rows", 0),
                "Winner Rows": row.get("winner_rows", 0),
                "Brier Skill": fmt_signed_pct(row.get("brier_skill_score")),
                "Winner Catch-Up": fmt_signed_pct(row.get("winner_catchup_gap")),
                "Winner Model P": fmt_pct(row.get("winner_model_probability")),
                "Winner Market P": fmt_pct(row.get("winner_market_probability")),
                "Model >= Market": fmt_pct(row.get("winner_catchup_rate"), digits=0),
                "Model >50": fmt_pct(row.get("winner_model_over_50_rate"), digits=0),
                "Market >50": fmt_pct(row.get("winner_market_over_50_rate"), digits=0),
            }
        )
    return pd.DataFrame(table)


def format_timeline_table(rows):
    table = []
    for row in rows:
        if row.get("status") != "scored":
            continue
        table.append(
            {
                "Date": row.get("target_date"),
                "Location": row.get("city"),
                "Winner": row.get("winning_band") or "-",
                "First Seen": row.get("winning_first_capture") or "-",
                "First >50": row.get("winning_first_over_50_time") or "never",
                "Minutes To >50": fmt_score(row.get("winning_minutes_to_50"), digits=1),
                "First Top": row.get("winning_first_top_time") or "never",
                "Market >50": row.get("market_first_over_50_time") or "never",
                "Model vs Market >50 Min": fmt_score(row.get("model_vs_market_50_minutes"), digits=1),
                "Max Winner P": fmt_pct(row.get("winning_max_probability")),
                "Final Winner P": fmt_pct(row.get("winning_final_probability")),
                "Final Top": row.get("final_top_bucket") or "-",
            }
        )
    return pd.DataFrame(table)
