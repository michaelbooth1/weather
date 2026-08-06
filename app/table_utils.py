"""Arrow-safe table helpers for Streamlit views."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd


def is_blank(value):
    if value is None:
        return True
    try:
        return bool(value == "")
    except (TypeError, ValueError):
        return False


def display_cell(value):
    if is_blank(value):
        return "-"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def arrow_safe_dataframe(rows, *, force_string_columns=("Value",)):
    normalized = []
    for row in rows or []:
        item = dict(row)
        for column in force_string_columns:
            if column in item:
                item[column] = display_cell(item[column])
        normalized.append(item)
    frame = pd.DataFrame(normalized)
    for column in frame.columns:
        values = [value for value in frame[column].tolist() if not is_blank(value)]
        types = {
            bool if isinstance(value, bool) else type(value)
            for value in values
        }
        if len(types) > 1:
            frame[column] = frame[column].map(display_cell)
    return frame


def arrow_safe_records(rows, *, force_string_columns=("Value",)):
    return arrow_safe_dataframe(rows, force_string_columns=force_string_columns).to_dict("records")


def csv_data_row_count(path):
    """Return the number of CSV data rows, or ``None`` when unreadable."""

    path = Path(path)
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return max(0, sum(1 for _line in handle) - 1)
    except OSError:
        return None
