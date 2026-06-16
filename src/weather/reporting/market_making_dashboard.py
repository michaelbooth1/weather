"""Data-loading helpers for the market-making Streamlit dashboard."""

from __future__ import annotations

import csv
import json
from pathlib import Path

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
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
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
