"""Data-loading helpers for the market-making Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from weather.io import read_csv_rows as io_read_csv_rows
from weather.paths import data_path


RUNS_ROOT = data_path("mm_runs")
BACKTEST_ROOT = data_path("backtest")


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def read_csv(path, limit=None):
    try:
        rows = io_read_csv_rows(path, attach_diagnostics=True)
    except OSError:
        return []
    return rows[-limit:] if limit else rows


def read_jsonl_tail(path, limit=20):
    rows = read_jsonl(path)
    return rows[-limit:] if limit else rows


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


def run_folders(runs_root=RUNS_ROOT):
    runs_root = Path(runs_root)
    if not runs_root.exists():
        return []
    folders = []
    for summary in runs_root.glob("*/*/run_summary.json"):
        folders.append(summary.parent)
    return sorted(folders, key=lambda folder: folder.stat().st_mtime, reverse=True)


def latest_run(runs_root=RUNS_ROOT):
    folders = run_folders(runs_root)
    if not folders:
        return None, {}
    folder = folders[0]
    return folder, read_json(folder / "run_summary.json", {}) or {}


def latest_readiness(backtest_root=BACKTEST_ROOT, target_date=None):
    """Return the newest readiness receipt, bound to ``target_date`` when supplied.

    A readiness receipt is date-scoped evidence. Falling back to a receipt for a
    different market day would make a missing current receipt look healthier than
    it is, so an exact-date miss deliberately returns no evidence.
    """

    root = Path(backtest_root)
    if not root.exists():
        return None, {}
    candidates = [
        path
        for path in root.glob("mm_live_readiness*.json")
        if path.is_file()
    ]
    if target_date is not None:
        matching = []
        for path in candidates:
            payload = read_json(path, {}) or {}
            if (
                isinstance(payload, dict)
                and str(payload.get("target_date") or "") == str(target_date)
            ):
                matching.append((path, payload))
        if not matching:
            return None, {}
        return max(matching, key=lambda item: item[0].stat().st_mtime)
    if not candidates:
        return None, {}
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    payload = read_json(path, {}) or {}
    return path, payload if isinstance(payload, dict) else {}
