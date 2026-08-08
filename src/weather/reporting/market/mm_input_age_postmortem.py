"""Measure maker input ages at active-window decision ticks.

The quote-intent tape has one row per market band, so this report deduplicates
to one observation per ``(run, generated_at_utc, market_id)`` before computing
age distributions. It reads historical evidence only and never runs capture or
the maker.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.market.market_making_evidence import (
    DEFAULT_ACTIVE_WINDOW_END,
    DEFAULT_ACTIVE_WINDOW_START,
    parse_hhmm,
)
from weather.market.mm_policy import DEFAULT_POLICY_CONFIG
from weather.reporting.market.mm_countability_postmortem import iter_day_dirs, iter_run_dirs


QUOTE_TAPE_NAME = "quote_intents_long.csv"
RUN_CONFIG_NAME = "run_config.json"
DEFAULT_TIMEZONE = "America/Toronto"


def _maybe_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _read_thresholds(run_dir):
    model = float(DEFAULT_POLICY_CONFIG["max_model_age_seconds"])
    book = float(DEFAULT_POLICY_CONFIG["max_book_age_seconds"])
    try:
        payload = json.loads((run_dir / RUN_CONFIG_NAME).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return model, book
    config = payload.get("policy_config") or {}
    configured_model = _maybe_float(config.get("max_model_age_seconds"))
    configured_book = _maybe_float(config.get("max_book_age_seconds"))
    return (
        model if configured_model is None else configured_model,
        book if configured_book is None else configured_book,
    )


def iter_quote_tapes(runs_root, *, include_quarantine=False):
    """Yield canonical quote tapes, optionally including retired runs."""
    for _, day_dir in iter_day_dirs(runs_root):
        if include_quarantine:
            yield from sorted(day_dir.rglob(QUOTE_TAPE_NAME))
            continue
        for run_dir in iter_run_dirs(day_dir):
            path = run_dir / QUOTE_TAPE_NAME
            if path.is_file():
                yield path


def _new_bucket():
    return {
        "samples": 0,
        "model_ages": [],
        "book_ages": [],
        "model_fresh": 0,
        "book_fresh": 0,
        "both_fresh": 0,
        "preflight_pass": 0,
        "days": set(),
    }


def _record(
    bucket,
    *,
    day,
    model_age,
    book_age,
    model_threshold,
    book_threshold,
    preflight_pass,
):
    bucket["samples"] += 1
    bucket["days"].add(day)
    model_fresh = model_age is not None and model_age <= model_threshold
    book_fresh = book_age is not None and book_age <= book_threshold
    if model_age is not None:
        bucket["model_ages"].append(model_age)
    if book_age is not None:
        bucket["book_ages"].append(book_age)
    bucket["model_fresh"] += int(model_fresh)
    bucket["book_fresh"] += int(book_fresh)
    bucket["both_fresh"] += int(model_fresh and book_fresh)
    bucket["preflight_pass"] += int(preflight_pass)


def _quantile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _percent(count, total):
    return (count / total) if total else None


def _finish_bucket(bucket):
    samples = bucket["samples"]
    model_ages = bucket["model_ages"]
    book_ages = bucket["book_ages"]
    return {
        "samples": samples,
        "days": len(bucket["days"]),
        "model_age_seconds": {
            "present": len(model_ages),
            "p50": _quantile(model_ages, 0.50),
            "p95": _quantile(model_ages, 0.95),
            "max": max(model_ages) if model_ages else None,
            "fresh_fraction": _percent(bucket["model_fresh"], samples),
        },
        "book_age_seconds": {
            "present": len(book_ages),
            "p50": _quantile(book_ages, 0.50),
            "p95": _quantile(book_ages, 0.95),
            "max": max(book_ages) if book_ages else None,
            "fresh_fraction": _percent(bucket["book_fresh"], samples),
        },
        "both_fresh_fraction": _percent(bucket["both_fresh"], samples),
        "preflight_pass_fraction": _percent(bucket["preflight_pass"], samples),
    }


def build_input_age_postmortem(
    runs_root,
    *,
    timezone_name=DEFAULT_TIMEZONE,
    active_window_start=DEFAULT_ACTIVE_WINDOW_START,
    active_window_end=DEFAULT_ACTIVE_WINDOW_END,
    include_quarantine=False,
):
    """Build active-window age distributions by market and Toronto hour."""
    timezone = ZoneInfo(timezone_name)
    window_start = parse_hhmm(active_window_start)
    window_end = parse_hhmm(active_window_end)
    overall = _new_bucket()
    by_market = defaultdict(_new_bucket)
    by_hour = defaultdict(_new_bucket)
    files = 0

    for path in iter_quote_tapes(runs_root, include_quarantine=include_quarantine):
        files += 1
        model_threshold, book_threshold = _read_thresholds(path.parent)
        seen = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                generated_at = row.get("generated_at_utc")
                market = str(row.get("market_id") or "").strip()
                key = (generated_at, market)
                if not generated_at or not market or key in seen:
                    continue
                seen.add(key)
                generated = _parse_datetime(generated_at)
                if generated is None:
                    continue
                local = generated.astimezone(timezone)
                target_date = str(row.get("target_date") or "")
                if target_date != local.date().isoformat():
                    continue
                if not (window_start <= local.time().replace(tzinfo=None) <= window_end):
                    continue
                model_age = _maybe_float(row.get("model_age_seconds"))
                book_age = _maybe_float(row.get("book_age_seconds"))
                values = {
                    "day": target_date,
                    "model_age": model_age,
                    "book_age": book_age,
                    "model_threshold": model_threshold,
                    "book_threshold": book_threshold,
                    "preflight_pass": str(row.get("preflight_status") or "").upper() == "PASS",
                }
                _record(overall, **values)
                _record(by_market[market], **values)
                _record(by_hour[local.hour], **values)

    return {
        "report_version": 1,
        "runs_root": str(Path(runs_root)),
        "timezone": timezone_name,
        "active_window_start_local": active_window_start,
        "active_window_end_local": active_window_end,
        "include_quarantine": bool(include_quarantine),
        "quote_tape_files": files,
        "configured_fallback_thresholds_seconds": {
            "model": float(DEFAULT_POLICY_CONFIG["max_model_age_seconds"]),
            "book": float(DEFAULT_POLICY_CONFIG["max_book_age_seconds"]),
        },
        "overall": _finish_bucket(overall),
        "by_market": [
            {"market_id": market, **_finish_bucket(bucket)}
            for market, bucket in sorted(by_market.items())
        ],
        "by_local_hour": [
            {"hour": hour, **_finish_bucket(bucket)}
            for hour, bucket in sorted(by_hour.items())
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-root", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--include-quarantine", action="store_true")
    args = parser.parse_args(argv)
    report = build_input_age_postmortem(
        args.runs_root,
        include_quarantine=args.include_quarantine,
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(
            f"{report['overall']['samples']} active-window market ticks across "
            f"{report['quote_tape_files']} quote tapes"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
