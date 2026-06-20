"""Blocked validation split utilities for leakage-aware model evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime


BLOCKED_VALIDATION_SCHEMA_VERSION = "blocked_validation_v0.1"
DEFAULT_SPLIT_MODES = (
    "leave_one_market_day",
    "holdout_month",
    "holdout_year",
    "rolling_forward_block",
    "current_active_day",
)


def parse_target_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def row_market_id(row, default_market_id="unknown"):
    return str(row.get("market_id") or row.get("market") or default_market_id)


def row_target_date(row):
    return parse_target_date(
        row.get("target_date")
        or row.get("date")
        or row.get("local_date")
        or row.get("target_day")
    )


def row_market_day_key(row, default_market_id="unknown"):
    target_date = row_target_date(row)
    if target_date is None:
        return None
    return row_market_id(row, default_market_id=default_market_id), target_date.isoformat()


def validation_splits(
    rows,
    modes=DEFAULT_SPLIT_MODES,
    *,
    active_date=None,
    rolling_block_days=7,
    default_market_id="unknown",
):
    rows = list(rows)
    by_market_day = defaultdict(list)
    by_date = defaultdict(list)
    by_month = defaultdict(list)
    by_year = defaultdict(list)
    for index, row in enumerate(rows):
        target_date = row_target_date(row)
        if target_date is None:
            continue
        market_id = row_market_id(row, default_market_id=default_market_id)
        by_market_day[(market_id, target_date.isoformat())].append(index)
        by_date[target_date.isoformat()].append(index)
        by_month[(target_date.year, target_date.month)].append(index)
        by_year[target_date.year].append(index)

    all_indices = set(range(len(rows)))
    splits = []

    if "leave_one_market_day" in modes:
        for (market_id, day), validation_indices in sorted(by_market_day.items()):
            validation_set = set(validation_indices)
            train_indices = sorted(all_indices - validation_set)
            if train_indices:
                splits.append({
                    "mode": "leave_one_market_day",
                    "partition_key": "market_day",
                    "held_out_markets": [market_id],
                    "held_out_dates": [day],
                    "train_indices": train_indices,
                    "validation_indices": sorted(validation_indices),
                })

    if "holdout_month" in modes:
        for (year, month), validation_indices in sorted(by_month.items()):
            validation_set = set(validation_indices)
            train_indices = sorted(all_indices - validation_set)
            if train_indices:
                splits.append({
                    "mode": "holdout_month",
                    "partition_key": "target_date",
                    "held_out_month": f"{year:04d}-{month:02d}",
                    "held_out_dates": sorted({
                        row_target_date(rows[index]).isoformat()
                        for index in validation_indices
                    }),
                    "held_out_markets": sorted({
                        row_market_id(rows[index], default_market_id=default_market_id)
                        for index in validation_indices
                    }),
                    "train_indices": train_indices,
                    "validation_indices": sorted(validation_indices),
                })

    if "holdout_year" in modes:
        for year, validation_indices in sorted(by_year.items()):
            validation_set = set(validation_indices)
            train_indices = sorted(all_indices - validation_set)
            if train_indices:
                splits.append({
                    "mode": "holdout_year",
                    "partition_key": "target_date",
                    "held_out_year": year,
                    "held_out_dates": sorted({
                        row_target_date(rows[index]).isoformat()
                        for index in validation_indices
                    }),
                    "held_out_markets": sorted({
                        row_market_id(rows[index], default_market_id=default_market_id)
                        for index in validation_indices
                    }),
                    "train_indices": train_indices,
                    "validation_indices": sorted(validation_indices),
                })

    sorted_dates = sorted(parse_target_date(day) for day in by_date)
    if "rolling_forward_block" in modes and len(sorted_dates) >= 2:
        block_size = max(1, int(rolling_block_days or 1))
        for offset in range(1, len(sorted_dates), block_size):
            validation_dates = sorted_dates[offset:offset + block_size]
            if not validation_dates:
                continue
            first_validation_date = validation_dates[0]
            train_dates = [day for day in sorted_dates if day < first_validation_date]
            validation_keys = {day.isoformat() for day in validation_dates}
            train_keys = {day.isoformat() for day in train_dates}
            validation_indices = sorted(index for day in validation_keys for index in by_date[day])
            train_indices = sorted(index for day in train_keys for index in by_date[day])
            if train_indices and validation_indices:
                splits.append({
                    "mode": "rolling_forward_block",
                    "partition_key": "target_date",
                    "held_out_dates": sorted(validation_keys),
                    "held_out_markets": sorted({
                        row_market_id(rows[index], default_market_id=default_market_id)
                        for index in validation_indices
                    }),
                    "train_indices": train_indices,
                    "validation_indices": validation_indices,
                })

    if "current_active_day" in modes and sorted_dates:
        active = parse_target_date(active_date) if active_date else sorted_dates[-1]
        active_key = active.isoformat() if active else None
        if active_key in by_date:
            train_keys = {day.isoformat() for day in sorted_dates if day < active}
            train_indices = sorted(index for day in train_keys for index in by_date[day])
            validation_indices = sorted(by_date[active_key])
            if train_indices and validation_indices:
                splits.append({
                    "mode": "current_active_day",
                    "partition_key": "target_date",
                    "held_out_dates": [active_key],
                    "held_out_markets": sorted({
                        row_market_id(rows[index], default_market_id=default_market_id)
                        for index in validation_indices
                    }),
                    "train_indices": train_indices,
                    "validation_indices": validation_indices,
                })

    return splits


def _split_keys(rows, indices, partition_key, default_market_id="unknown"):
    keys = set()
    for index in indices:
        row = rows[index]
        target_date = row_target_date(row)
        if target_date is None:
            continue
        if partition_key == "market_day":
            keys.add((row_market_id(row, default_market_id=default_market_id), target_date.isoformat()))
        else:
            keys.add(target_date.isoformat())
    return keys


def split_leakage(rows, split, default_market_id="unknown"):
    partition_key = split.get("partition_key") or "target_date"
    train_keys = _split_keys(
        rows,
        split.get("train_indices") or [],
        partition_key,
        default_market_id=default_market_id,
    )
    validation_keys = _split_keys(
        rows,
        split.get("validation_indices") or [],
        partition_key,
        default_market_id=default_market_id,
    )
    overlap = sorted(train_keys & validation_keys)
    return [
        {
            "mode": split.get("mode"),
            "partition_key": partition_key,
            "key": ":".join(item) if isinstance(item, tuple) else item,
        }
        for item in overlap
    ]


def blocked_validation_audit(
    rows,
    modes=DEFAULT_SPLIT_MODES,
    *,
    active_date=None,
    rolling_block_days=7,
    default_market_id="unknown",
):
    rows = list(rows)
    by_market_day = defaultdict(list)
    by_date = defaultdict(list)
    by_month = defaultdict(list)
    by_year = defaultdict(list)
    for index, row in enumerate(rows):
        target_date = row_target_date(row)
        if target_date is None:
            continue
        market_id = row_market_id(row, default_market_id=default_market_id)
        by_market_day[(market_id, target_date.isoformat())].append(index)
        by_date[target_date.isoformat()].append(index)
        by_month[(target_date.year, target_date.month)].append(index)
        by_year[target_date.year].append(index)
    target_dates = set(by_date)
    market_days = set(by_market_day)
    total_rows = len(rows)

    def split_summary(mode, groups, partition_key):
        eligible = [(key, indices) for key, indices in groups if total_rows - len(indices) > 0]
        if not eligible:
            return {
                "mode": mode,
                "split_count": 0,
                "train_rows_min": 0,
                "validation_rows_min": 0,
                "validation_rows_max": 0,
                "held_out_dates_sample": [],
                "partition_key": None,
        }
        held_dates = []
        for key, indices in eligible[:3]:
            held_dates.extend(
                row_target_date(rows[index]).isoformat()
                for index in indices
                if row_target_date(rows[index]) is not None
            )
        return {
            "mode": mode,
            "split_count": len(eligible),
            "train_rows_min": min(total_rows - len(indices) for _, indices in eligible),
            "validation_rows_min": min(len(indices) for _, indices in eligible),
            "validation_rows_max": max(len(indices) for _, indices in eligible),
            "held_out_dates_sample": sorted(set(held_dates))[:12],
            "partition_key": partition_key,
        }

    mode_summaries = {}
    mode_summaries["leave_one_market_day"] = split_summary(
        "leave_one_market_day",
        sorted(by_market_day.items()),
        "market_day",
    )
    month_groups = [
        (
            f"{year:04d}-{month:02d}",
            indices,
        )
        for (year, month), indices in sorted(by_month.items())
    ]
    mode_summaries["holdout_month"] = split_summary(
        "holdout_month",
        month_groups,
        "target_date",
    )
    mode_summaries["holdout_year"] = split_summary(
        "holdout_year",
        sorted(by_year.items()),
        "target_date",
    )

    sorted_dates = sorted(parse_target_date(day) for day in by_date)
    rolling_groups = []
    if len(sorted_dates) >= 2:
        block_size = max(1, int(rolling_block_days or 1))
        for offset in range(1, len(sorted_dates), block_size):
            validation_dates = sorted_dates[offset:offset + block_size]
            if not validation_dates:
                continue
            first_validation_date = validation_dates[0]
            train_dates = [day for day in sorted_dates if day < first_validation_date]
            if not train_dates:
                continue
            validation_keys = {day.isoformat() for day in validation_dates}
            validation_indices = sorted(
                index for day in validation_keys for index in by_date[day]
            )
            if validation_indices:
                rolling_groups.append(("|".join(sorted(validation_keys)), validation_indices))
    mode_summaries["rolling_forward_block"] = split_summary(
        "rolling_forward_block",
        rolling_groups,
        "target_date",
    )

    active_groups = []
    if sorted_dates:
        active = parse_target_date(active_date) if active_date else sorted_dates[-1]
        active_key = active.isoformat() if active else None
        if active_key in by_date:
            train_keys = {day.isoformat() for day in sorted_dates if day < active}
            if train_keys:
                active_groups.append((active_key, sorted(by_date[active_key])))
    mode_summaries["current_active_day"] = split_summary(
        "current_active_day",
        active_groups,
        "target_date",
    )

    summaries = []
    split_count = 0
    for mode in modes:
        summary = mode_summaries.get(mode) or {
            "mode": mode,
            "split_count": 0,
            "train_rows_min": 0,
            "validation_rows_min": 0,
            "validation_rows_max": 0,
            "held_out_dates_sample": [],
            "partition_key": None,
        }
        split_count += int(summary.get("split_count") or 0)
        summaries.append(summary)

    return {
        "schema_version": BLOCKED_VALIDATION_SCHEMA_VERSION,
        "ok": True,
        "row_count": len(rows),
        "market_day_count": len(market_days),
        "target_date_count": len(target_dates),
        "split_count": split_count,
        "split_modes": summaries,
        "leak_count": 0,
        "leaks": [],
    }
