"""DESCRIPTIVE analysis of the live-fill calibration pilot (design section 3). Never a decision gate by itself.

Inputs are normalized JSONL files (one object per line):
  legs       {order_id, token_id, condition_id, price, size, placed_at_utc, ended_at_utc,
              fills: [{at_utc, size}], queue_ahead: [{at_utc, visible_at_price, own_size, phase}]}
             (extract_legs builds these from the session journals)
  prints     {token_id, price, size, at_utc}            public prints (88a `last_trade_price` events, normalize_88a_print)
  mids       {token_id, at_utc, mid}                     88a two-sided mids
  settlement {condition_id: winning_token_id}            JSON object (the settlement ledger's winner)

Outputs: N_at, N_thr, c_at, c_thr, queue-ahead-conditioned c_at, own-fill markouts at 1/5/30 min and settlement, the
share-weighted mean markout, and f_hat. For our resting BUY at p on token T, a print on T at p is "at price" and a
print below p is "strictly through".

Reserved dates: any input row dated 2026-09-30..2026-10-15 (UTC) is refused unless allow_reserved=True. That
window holds the unread replay-v2 panel; the default is refuse.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

from weather.market import lfc_constants as LFC
from weather.market.mm_stage2_hold import canonical_bytes, utc, write_new

ANALYSIS_SCHEMA = 'lfc_analysis_v0.1'
HORIZONS_SECONDS = (60, 300, 1800)
MID_TOLERANCE_SECONDS = 120
FILL_MATCH_SECONDS = 120
QUEUE_BUCKETS = ((Decimal(0), Decimal(0)), (Decimal('0.000001'), Decimal(50)), (Decimal('50.000001'), Decimal(200)),
                 (Decimal('200.000001'), None))
INFORMED_MARKOUT = Decimal('-0.02')


class ReservedDateRefused(ValueError):
    """An input carries a reserved panel date and no explicit override was given."""


def _d(value):
    return Decimal(str(value))


def check_dates(stamps, *, allow_reserved=False):
    reserved = sorted({utc(s).date().isoformat() for s in stamps
                       if LFC.RESERVED_FIRST_DAY <= utc(s).date().isoformat() <= LFC.RESERVED_LAST_DAY})
    if reserved and not allow_reserved:
        raise ReservedDateRefused('reserved_dates_refused: ' + ','.join(reserved[:5]))
    return reserved


def normalize_88a_print(row):
    """88a `last_trade_price` event -> normalized print (timestamp is epoch milliseconds)."""
    if row.get('event_type') != 'last_trade_price':
        return None
    from datetime import datetime, timezone
    at = datetime.fromtimestamp(int(row['timestamp']) / 1000, tz=timezone.utc)
    return {'token_id': str(row['asset_id']), 'price': str(row['price']), 'size': str(row['size']),
            'at_utc': at.isoformat()}


def extract_legs(journal_path):
    """Own legs from one RE-1/pilot session journal (fill times are 'no later than' the detecting row)."""
    rows = [json.loads(line) for line in Path(journal_path).read_bytes().splitlines() if line.strip()]
    legs, order = {}, []
    for row in rows:
        event, at = row.get('event'), row.get('recorded_at_utc')
        if event == 'submit_response':
            response = row.get('response') or {}
            oid = str(response.get('order_id') or response.get('id') or response.get('orderID') or '')
            request = next((r for r in reversed(rows[:rows.index(row)]) if r.get('event') == 'submit_request'), None)
            if oid and request:
                req = request['request']
                legs[oid] = {'order_id': oid, 'token_id': req['token_id'], 'condition_id': rows[0]['scope']['condition_id'],
                             'price': req['price'], 'size': req['size'], 'placed_at_utc': at, 'ended_at_utc': None,
                             'fills': [], 'queue_ahead': []}
                order.append(oid)
        elif event == 'lfc_queue_ahead' and row.get('order_id') in legs:
            legs[row['order_id']]['queue_ahead'].append({'at_utc': at, 'visible_at_price': row.get('visible_at_price'),
                                                         'own_size': row.get('own_size'), 'phase': row.get('phase')})
        elif event in {'cancel_response', 'cleanup_cancel_response', 'cleanup_cancel_ours_response'}:
            oid = str(row.get('order_id') or (row.get('request') or {}).get('order_id') or '')
            if oid in legs and legs[oid]['ended_at_utc'] is None:
                legs[oid]['ended_at_utc'] = at
        elif event == 'terminal_order':
            info = row.get('order') or {}
            oid = str(info.get('id') or info.get('order_id') or '')
            matched = _d(info.get('size_matched', 0) or 0)
            if oid in legs and matched > 0 and not legs[oid]['fills']:
                fill_rows = [r for r in rows if r.get('event') == 'fill']
                legs[oid]['fills'].append({'at_utc': fill_rows[0]['recorded_at_utc'] if fill_rows else at,
                                           'size': str(matched)})
    end = rows[-1]['recorded_at_utc'] if rows else None
    for oid in order:
        if legs[oid]['ended_at_utc'] is None:
            legs[oid]['ended_at_utc'] = end
    return [legs[oid] for oid in order]


def _nearest_mid(mids, token, at, tolerance=MID_TOLERANCE_SECONDS):
    best = None
    for row in mids.get(token, ()):
        gap = abs((row[0] - at).total_seconds())
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, row[1])
    return None if best is None else best[1]


def _queue_at(leg, at):
    rows = [q for q in leg['queue_ahead'] if q.get('visible_at_price') is not None and utc(q['at_utc']) <= at]
    if not rows:
        return None
    last = rows[-1]
    # The placement snapshot predates our order; later book snapshots include our own resting size.
    own = Decimal(0) if last.get('phase') == 'placement' else _d(last.get('own_size') or 0)
    return max(Decimal(0), _d(last['visible_at_price']) - own)


def _bucket(value):
    if value is None:
        return 'unknown'
    for low, high in QUEUE_BUCKETS:
        if value >= low and (high is None or value <= high):
            return f'{low:f}-{high:f}' if high is not None else f'{low:f}-inf'
    return 'unknown'


def analyze(legs, prints, mids, settlement, *, allow_reserved=False):
    stamps = [p['at_utc'] for p in prints] + [m['at_utc'] for m in mids]
    for leg in legs:
        stamps += [leg['placed_at_utc'], leg['ended_at_utc']] + [f['at_utc'] for f in leg['fills']]
    reserved = check_dates([s for s in stamps if s], allow_reserved=allow_reserved)
    mid_index = {}
    for m in mids:
        mid_index.setdefault(str(m['token_id']), []).append((utc(m['at_utc']), _d(m['mid'])))
    totals = {'at': [Decimal(0), Decimal(0), 0], 'thr': [Decimal(0), Decimal(0), 0]}
    by_queue = {}
    used_fills = set()
    for leg in legs:
        price, size = _d(leg['price']), _d(leg['size'])
        start, end = utc(leg['placed_at_utc']), utc(leg['ended_at_utc'])
        fills = sorted(((utc(f['at_utc']), _d(f['size'])) for f in leg['fills']), key=lambda r: r[0])
        filled_before = Decimal(0)
        for p in sorted((p for p in prints if str(p['token_id']) == str(leg['token_id'])), key=lambda r: utc(r['at_utc'])):
            at, print_price = utc(p['at_utc']), _d(p['price'])
            if not start <= at <= end or print_price > price:
                continue
            kind = 'at' if print_price == price else 'thr'
            remaining = max(Decimal(0), size - filled_before)
            if remaining <= 0:
                continue
            attributed = Decimal(0)
            for index, (fill_at, fill_size) in enumerate(fills):
                key = (leg['order_id'], index)
                if key not in used_fills and abs((fill_at - at).total_seconds()) <= FILL_MATCH_SECONDS:
                    used_fills.add(key)
                    attributed += fill_size
            denominator = min(_d(p['size']), remaining)
            totals[kind][0] += min(attributed, denominator)
            totals[kind][1] += denominator
            totals[kind][2] += 1
            filled_before += attributed
            if kind == 'at':
                bucket = by_queue.setdefault(_bucket(_queue_at(leg, at)), [Decimal(0), Decimal(0), 0])
                bucket[0] += min(attributed, denominator)
                bucket[1] += denominator
                bucket[2] += 1
    markouts = []
    for leg in legs:
        price = _d(leg['price'])
        winner = settlement.get(leg['condition_id'])
        for fill in leg['fills']:
            at = utc(fill['at_utc'])
            row = {'order_id': leg['order_id'], 'token_id': leg['token_id'], 'size': fill['size'], 'price': str(price)}
            for horizon in HORIZONS_SECONDS:
                mid = _nearest_mid(mid_index, str(leg['token_id']), at + timedelta(seconds=horizon))
                row[f'markout_{horizon}s'] = None if mid is None else str(mid - price)
            row['markout_settlement'] = (None if winner is None else
                                         str((Decimal(1) if str(winner) == str(leg['token_id']) else Decimal(0)) - price))
            markouts.append(row)

    def ratio(values):
        return None if values[1] == 0 else str(values[0] / values[1])
    weighted = [(_d(m['size']), _d(m['markout_1800s'])) for m in markouts if m['markout_1800s'] is not None]
    informed = [m for m in markouts if m['markout_1800s'] is not None and m['markout_settlement'] is not None]
    f_hat = (None if not informed else str(Decimal(sum(1 for m in informed if _d(m['markout_1800s']) <= INFORMED_MARKOUT
                                                    and _d(m['markout_settlement']) < 0)) / len(informed)))
    return {'schema_version': ANALYSIS_SCHEMA, 'kind': 'lfc_analysis', 'descriptive_only': True,
            'reserved_dates_included': reserved,
            'N_at': totals['at'][2], 'N_thr': totals['thr'][2], 'c_at': ratio(totals['at']), 'c_thr': ratio(totals['thr']),
            'c_at_by_queue_ahead': {k: {'c_at': ratio(v), 'N_at': v[2]} for k, v in sorted(by_queue.items())},
            'fills': len(markouts), 'markouts': markouts,
            'share_weighted_markout_1800s': (None if not weighted else
                                             str(sum(s * m for s, m in weighted) / sum(s for s, _ in weighted))),
            'f_hat': f_hat, 'f_hat_definition': '30-min markout <= -0.02 and settlement markout < 0, over fills with both'}


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--legs', type=Path, required=True)
    parser.add_argument('--prints', type=Path, required=True)
    parser.add_argument('--mids', type=Path, required=True)
    parser.add_argument('--settlement', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-reserved-dates', action='store_true',
                        help='explicit override: read inputs dated 2026-09-30..2026-10-15 (default: refuse)')
    args = parser.parse_args(argv)
    result = analyze(_jsonl(args.legs), _jsonl(args.prints), _jsonl(args.mids), json.loads(args.settlement.read_bytes()),
                     allow_reserved=args.allow_reserved_dates)
    write_new(args.output, result)
    print(canonical_bytes({k: result[k] for k in ('N_at', 'N_thr', 'c_at', 'c_thr', 'fills', 'f_hat')}).decode().strip())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
