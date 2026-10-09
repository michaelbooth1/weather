"""Mechanical panel exclusion of the band-days carrying the live-fill calibration pilot's own orders.

Design section 4: our resting legs enter the public books and absorb prints, so every (band, day) that carried one
of our orders must be dropped from the desk-study decision panel, the replay-v2 panel and shadow scoring before
any panel read. This module derives that set from the session journals alone (never from a panel) and offers one
function the panel selectors call.

Integration point: the desk-study / v2 panel selectors (maker_shadow_panel, EMBARGOED_UTC_DAYS) are NOT on this
branch (codex/re1-wallet-200-20260923). Their selectors must call `exclude_band_days(rows, load_exclusions(path))`
on the candidate quote-minute rows before any aggregate is read. A band is a condition id, and a condition belongs
to exactly one event date, so the default mode drops every row of a band that carried our orders.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path

from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new

EXCLUSION_SCHEMA = 'lfc_panel_exclusion_v0.1'
_ORDER_EVENTS = {'submit_request', 'submit_response'}


def _rows(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def session_band_days(directory):
    """One record per session directory whose journal shows at least one submit; None otherwise.

    The window runs from the first submit request to the last journal row (cleanup and terminal reads included),
    so every UTC day on which one of our orders could have rested is covered.
    """
    directory = Path(directory)
    journal = directory / 'journal.jsonl'
    rows = _rows(journal)
    if not rows or rows[0].get('event') != 'opened':
        raise ValueError('journal_without_opening_row: ' + str(journal))
    submits = [r for r in rows if r.get('event') in _ORDER_EVENTS]
    if not submits:
        return None
    scope = rows[0]['scope']
    first, last = utc(submits[0]['recorded_at_utc']), utc(rows[-1]['recorded_at_utc'])
    if rows[-1].get('event') != 'terminal':
        # A crashed session: our orders may have rested until the GTD expiry at the fixed end plus 60 s.
        last = max(last, utc(scope['end_at_utc']) + timedelta(seconds=60))
    days, day = [], first.date()
    while day <= last.date():
        days.append(day.isoformat())
        day += timedelta(days=1)
    market_id = event_date = event_slug = None
    selection = directory / 'selection.json'
    if selection.exists():
        table = json.loads(selection.read_bytes())
        row = next((r for r in table.get('rows', ()) if r.get('condition_id') == scope['condition_id']), {})
        market_id, event_date, event_slug = row.get('market_id'), row.get('target_date'), row.get('event_slug')
    return {'condition_id': scope['condition_id'], 'token_ids': list(scope['token_ids']), 'market_id': market_id,
            'event_date': event_date, 'event_slug': event_slug, 'utc_days': days,
            'first_order_at_utc': first.isoformat(), 'last_activity_at_utc': last.isoformat(),
            'session_directory': directory.name, 'session_id': scope.get('session_id')}


def band_days(root):
    """All band-days carrying our orders, from every session directory under the pilot root."""
    records = []
    for journal in sorted(Path(root).glob('*/journal.jsonl')):
        if journal.parent.name.startswith('preflight-'):
            continue
        record = session_band_days(journal.parent)
        if record is not None:
            records.append(record)
    return records


def exclusion_payload(records):
    pairs = sorted({(r['condition_id'], d) for r in records for d in r['utc_days']})
    body = {'schema_version': EXCLUSION_SCHEMA, 'kind': 'lfc_panel_exclusion', 'records': records,
            'band_utc_days': [list(p) for p in pairs],
            'band_event_dates': sorted({(r['condition_id'], r['event_date']) for r in records if r['event_date']})}
    body['band_event_dates'] = [list(p) for p in body['band_event_dates']]
    return {**body, 'sha256': digest(body)}


def load_exclusions(path):
    payload = json.loads(Path(path).read_bytes())
    body = {k: v for k, v in payload.items() if k != 'sha256'}
    if payload.get('schema_version') != EXCLUSION_SCHEMA or digest(body) != payload.get('sha256'):
        raise ValueError('exclusion file schema or digest differs')
    return payload


def exclude_band_days(rows, exclusions, *, condition_key='condition_id', day_key='utc_day', mode='band'):
    """Split panel rows into (kept, dropped). mode='band' drops every row of a band that carried our orders
    (default, conservative); mode='band_utc_day' drops only the rows on the UTC days our orders could rest."""
    if mode not in {'band', 'band_utc_day'}:
        raise ValueError('exclusion mode')
    bands = {c for c, _ in exclusions['band_utc_days']}
    pairs = {(c, d) for c, d in exclusions['band_utc_days']}
    kept, dropped = [], []
    for row in rows:
        condition = str(row[condition_key]).lower()
        hit = (condition in {b.lower() for b in bands} if mode == 'band' else
               (condition, str(row[day_key])[:10]) in {(c.lower(), d) for c, d in pairs})
        (dropped if hit else kept).append(row)
    return kept, dropped


def main(argv=None):
    parser = argparse.ArgumentParser(description='Emit the band-days carrying the pilot\'s own orders.')
    parser.add_argument('--root', type=Path, help='pilot campaign root (default: the fixed Windows token root)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.root is None:
        from weather.market.lfc_pilot import pilot_root
        args.root = pilot_root()
    payload = exclusion_payload(band_days(args.root))
    write_new(args.output, payload)
    print(canonical_bytes({'output': str(args.output), 'sha256': payload['sha256'],
                           'bands': len({r['condition_id'] for r in payload['records']})}).decode().strip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
