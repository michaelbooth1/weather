"""Mechanical panel exclusion for the live-fill calibration campaign (signed pre-registration section 4).

Rule: exclude every band-day (C', D) where C' is any condition in the same event as a condition that carried a
campaign order and D is a local quote date on which a campaign order rested. It applies to every registration whose
panel overlaps the campaign (desk study, v2 or shadow parity, later candidate exams), whether or not the session
filled. Session 0 adds no exclusion (its market is outside every panel by construction).

Mechanics: before the first post the session script appends the would-be exclusions for the selected band and date
to `panel_exclusions.jsonl` in the campaign root, one JSON line with exactly the signed fields `event_slug`,
`condition_ids` (every condition of the event), `local_quote_date`, `session_id` and `appended_utc`, and records the
line's SHA-256 in the session `journal.jsonl`. When a session window spans more than one local date of the market's
timezone, one line per date is written (so a T+1/T+2 band of a far-east market is never under-excluded).

Integration point: the desk-study, v2 and shadow panel selectors are NOT on this branch
(codex/re1-wallet-200-20260923). Each must call `drop_excluded(rows, load_panel_exclusions(path), ...)` on its
candidate rows before any outcome is read; this module never reads a panel.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.market.mm_stage2_hold import canonical_bytes, utc, write_new

EXCLUSION_FILE = 'panel_exclusions.jsonl'
FIELDS = ('appended_utc', 'condition_ids', 'event_slug', 'local_quote_date', 'session_id')


def local_quote_dates(start, end, timezone_name, *, gtd_seconds=60):
    """Every local date of the market's timezone on which an order of the session could rest (to GTD expiry)."""
    zone = ZoneInfo(timezone_name)
    first = utc(start).astimezone(zone).date()
    last = (utc(end) + timedelta(seconds=gtd_seconds)).astimezone(zone).date()
    if last < first:
        raise ValueError('exclusion_window_inverted')
    return [(first + timedelta(days=d)).isoformat() for d in range((last - first).days + 1)]


def exclusion_lines(*, event_slug, condition_ids, session_id, start, end, timezone_name, appended):
    conditions = sorted({str(c) for c in condition_ids})
    if not event_slug or not conditions or not session_id:
        raise ValueError('exclusion_incomplete')
    return [{'event_slug': str(event_slug), 'condition_ids': conditions, 'local_quote_date': day,
             'session_id': str(session_id), 'appended_utc': utc(appended).isoformat()}
            for day in local_quote_dates(start, end, timezone_name)]


def append_exclusions(root, lines):
    """Append the lines (fsynced) and return each line's SHA-256 over its exact bytes. Raises on any failure."""
    path = Path(root) / EXCLUSION_FILE
    encoded = [canonical_bytes(line) for line in lines]
    for line in lines:
        if tuple(sorted(line)) != FIELDS:
            raise ValueError('exclusion_fields')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing and not existing.endswith(b'\n'):
            raise ValueError('exclusion_file_truncated')
    with path.open('ab') as handle:
        for raw in encoded:
            handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return [hashlib.sha256(raw).hexdigest() for raw in encoded]


def load_panel_exclusions(path):
    """Every line, validated; a malformed file refuses (selectors must not read a panel without it)."""
    raw = Path(path).read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('exclusion_file_truncated')
    lines = []
    for line in raw.splitlines():
        if not line.strip():
            raise ValueError('exclusion_blank_line')
        value = json.loads(line)
        if (not isinstance(value, dict) or tuple(sorted(value)) != FIELDS or not isinstance(value['condition_ids'], list)
                or not value['condition_ids']):
            raise ValueError('exclusion_line_shape')
        lines.append(value)
    return lines


def excluded_band_days(lines):
    return {(str(c).lower(), line['local_quote_date']) for line in lines for c in line['condition_ids']}


def excluded_conditions(lines):
    return {str(c).lower() for line in lines for c in line['condition_ids']}


def drop_excluded(rows, lines, *, condition_key='condition_id', date_key='local_quote_date'):
    """Split panel rows into (kept, dropped) by the excluded (condition, local quote date) band-days."""
    excluded = excluded_band_days(lines)
    kept, dropped = [], []
    for row in rows:
        day = str(row[date_key])[:10]
        (dropped if (str(row[condition_key]).lower(), day) in excluded else kept).append(row)
    return kept, dropped


def main(argv=None):
    parser = argparse.ArgumentParser(description='Summarise panel_exclusions.jsonl as excluded band-days.')
    parser.add_argument('--exclusions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    lines = load_panel_exclusions(args.exclusions)
    payload = {'source_sha256': hashlib.sha256(args.exclusions.read_bytes()).hexdigest(), 'lines': len(lines),
               'band_days': [list(pair) for pair in sorted(excluded_band_days(lines))]}
    sha = write_new(args.output, payload)
    print(json.dumps({'output': str(args.output), 'sha256': sha, 'band_days': len(payload['band_days'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
